# TRAPS.md — bẫy đã mắc trong repo này

Mỗi mục là chuyện **đã xảy ra thật**, có ngày, có PR. Không phải danh sách "nên tránh" chung chung. Đọc trước khi
sửa lỗi lạ: phần lớn lỗi mới là một thể hiện khác của khuôn cũ. Bẫy riêng của từng package nằm ở `<pkg>/TRAPS.md`.

Cách dùng: gặp triệu chứng → tìm khuôn ở §1 → xem cách rà → mới đi sửa. Sửa xong → thêm mục mới ở đây nếu là bẫy mới,
hoặc thêm ngày/PR vào mục cũ nếu là lần tái phát.

## 1. Sáu khuôn lỗi lặp lại (16 lỗi phiên 2026-09-04, 0 lỗi nghiệp vụ; khuôn 5 thêm 2026-09-06, khuôn 6 thêm 2026-09-13)

**Khuôn 1 — chế độ hỏng không tự khai báo.** Một tình huống riêng bị gói vào thông điệp chung, nên người và hệ
thống đều xử lý sai: timeout 120s báo `HTTP 500` thân rỗng; hết hạn mức đầu ra báo "không phải JSON"; structured
output trả qua `tool_calls` mà client đọc `content` rỗng **với mã 200**; hạn mức 82 giờ bị che bằng cooldown mặc
định 1 giờ. Hệ quả là retry vô ích, chờ thừa, đốt quota. *Cách rà*: mọi nhánh `except`/`else` chung — hỏi "nếu
là trường hợp X thì thông điệp này có nói X không?".

**Khuôn 2 — state chỉ sống trong RAM, mất khi mở lại bus.** Không hỏng ồn ào; dự án đứng im trong khi `status`
xanh: lệnh thử-lại trong `self.queue`, trạng thái `blocked` suy từ số retry, `Supervisor.actions` bị replay nuốt.
*Chốt chặn*: `test_moi_trang_thai_nghiep_vu_song_sot_qua_restart` trong `companies/software-company/tests/test_orchestrator.py`.
*Cách rà*: mỗi thuộc tính mới của orchestrator — "mở lại bus thì dựng lại từ đâu?".

**Khuôn 3 — khoá chống-trùng nuốt lần hai HỢP LỆ.** `self.once`, `project_paused`, `_escalated_once`,
`partial[event_id]`: ticket bị chặn lần hai sinh đúng khoá lần một → không gate nào mở; `gate:{sid}` dùng chung
cho `remind` và `overdue`; `project_paused` không bao giờ gỡ → trần ngân sách chặn đúng một lần cả vòng đời. Rà
2026-09-04: 7 khoá, 3 hỏng. *Cách rà*: grep `in self.once` / `not in self.<set>`, hỏi "tình huống này có lặp lại
hợp lệ không?" — nếu có, khoá phải mang **giai đoạn/thế hệ**, không chỉ danh tính. Gỡ cờ thì coi chừng bật lại ngay.
*Tái phát 2026-09-08 (audit sâu)*: đúng `gate:{sid}` ấy vẫn sống trong `studio/orchestrator.py` suốt thời gian
company đã vá xong — `gate.overdue` của studio **chưa bao giờ** vào audit-log, và studio còn thiếu luôn bước
escalate khi quá hạn. Guard `test_orch_khuon_loi.py` không thấy vì nó khoá phạm vi ở `src/company/orch/`. Hai
bài học: (a) **vá một khuôn thì vá ở mọi công ty**, không chỉ nơi phát hiện — hai orchestrator là bản sao của
cùng một thiết kế; (b) **test canh quy ước phải nói rõ nó canh tới đâu**, vì phạm vi hẹp của nó đọc y hệt "cả
repo sạch". Studio nay có `Studio-creators/tests/test_khuon_loi.py` đối xứng.

**Thế hệ phải là cùng một giá trị ở mọi tiến trình.** Cùng phiên: khoá `once` của gate lấy `GateRequest.created_at`
làm thế hệ, nhưng tiến trình tạo gate giữ mốc dựng dataclass còn tiến trình dựng lại từ replay đặt
`created_at=env.ts` của envelope `gate.request` — lệch vài trăm micro giây. Cả hai công ty đều thế. Hệ quả: mỗi
lần mở lại bus là mọi gate đang chờ đổi thế hệ, khoá cũ hết khớp, gate đã nhắc/đã escalate bị **nhắc lại và
escalate lại**. Sửa ở `PersistentGate.request` (gán `r.created_at = env.ts` trước khi publish) chứ không ở nơi
dùng khoá. *Cách rà*: một khoá `once` mang thế hệ → hỏi tiếp "giá trị này có bằng chính nó sau restart không?".
Test in-process không bao giờ thấy lớp lỗi này; phải có test mở lại bus.

**Khuôn 4 — event cũ trong hàng đợi phát lại như mới sau resume/restart.** Hàng đợi giữ event theo danh tính,
không theo thế hệ: task retry cũ + PR cũ nằm đó (hoãn vì paused), duyệt gate → phát lại → backend chạy trên worktree
đã commit → "không sửa gì" ×3 → blocked → escalation mở lại. QLKH-004 mở lại 7 lần, 10.7M token (PR #55). *Cách rà*:
"event này còn đúng với trạng thái HIỆN TẠI của chủ thể không?". *Hệ quả vận hành*: sửa tay thì **commit + takeover
trước, duyệt gate sau**.

**Khuôn 5 — xếp thứ tự theo dấu thời gian, tưởng là thứ tự toàn phần.** Hai event ghi trong cùng một lượt có thể
trùng `ts` tới micro giây. `history.sort(key=lambda h: h["at"])` khi ấy để hoà cho thứ tự chèn quyết định, nên hồ sơ
lật giữa hai cách sắp xếp tuỳ đồng hồ có nhích hay không: test golden `escalation` chập chờn ~1/6 lần, và người đọc
thấy `tasks retry=2` TRƯỚC lỗi gây ra nó (PR sau #104). *Cách rà*: mọi `sort`/`sorted` theo thời gian phải có khoá
phụ là **thứ tự ghi vào bus** (`seq`) — bus đã `ORDER BY seq`, dùng nó. `trace.py` (#99) làm đúng vì nó duyệt
`bus.replay()` và không sắp xếp lại. *Dấu hiệu nhận ra*: test chỉ đỏ 1 trong vài lần chạy, chạy lại thì xanh — đừng
chạy lại cho qua, đó là non-determinism thật.

**Khuôn 6 — kiểm danh tính bằng tiền tố chuỗi, tưởng là kiểm giá trị.** `is_loopback_host` ở CẢ
`platform/console/src/console/server.py` và `platform/gateway/src/gateway/server.py` kết thúc bằng
`startswith("127.")`, nên mọi TÊN MIỀN bắt đầu bằng "127." cũng khớp: `127.0.0.1.evil.example` (kẻ tấn công chỉ
cần một bản ghi A trỏ về 127.0.0.1 — không cần DNS rebinding) đi lọt cả `Host` lẫn `Origin`, vì hai hàng rào
gọi chung một hàm. Console khi đó cùng nguồn với trang tấn công ⇒ nó đọc được token phiên nhúng trong HTML rồi
gọi `/api/gate/decide`; gateway không có xác thực client nên trang ấy đốt quota thật. Audit 2026-09-13 mục S1,
vá ở PR sau #287. *Cách rà*: mọi lần một QUYẾT ĐỊNH BẢO MẬT đọc chuỗi bằng `startswith`/`endswith`/`in` —
hỏi "chuỗi này có cấu trúc riêng không?" IP thì parse bằng `ipaddress`, đường dẫn thì `resolve()`, host thì so
sau khi tách cổng. `keeper/patcher.py:99` đã học đúng bài này cho đường dẫn (`a/../llm.yaml`), server HTTP thì
chưa. *Dấu hiệu nhận ra*: **docstring khẳng định chắc nịt thứ mà mã không làm** — hai file đều viết "KHÔNG
phân giải DNS, tên lạ là không loopback, chấm hết" ngay trên đúng dòng cho tên lạ đi qua. Rà cả họ (2026-09-13):
chỉ hai file này nhận `Host`/`Origin` từ ngoài, `mcp_bridge.py` dùng "127.0.0.1" làm địa chỉ BIND chứ không
làm điều kiện, không dính.

Nguyên tắc rút ra: *không đường nào được kết thúc trong im lặng, và không đường nào được lặp mãi trong im lặng.*
Cơ chế cứu thường ĐÃ CÓ, chỉ là điều kiện kích hoạt quá hẹp (`_stall` chỉ lo `RESEARCH_TOPICS`, `_rework_after_error`
chỉ lo `tools="rw"`). Cái rơi ra ngoài luôn rơi vào im lặng.

## 2. Bẫy chẩn đoán (của người sửa, không phải của hệ)

| Bẫy | Đã xảy ra | Lần sau |
|---|---|---|
| **Suy từ thông điệp lỗi** | 2026-09-04: chẩn đoán sai 6 lần liên tiếp, mỗi lần đều nghe hợp lý; đúng ở mọi lần dựng phép thử đối chứng | Tái hiện lượt thật, tách từng biến, so một con số đặc trưng với lượt thật. Kết quả RỖNG chưa chắc là KHÔNG CÓ — có thể hỏi sai chỗ |
| **Test xanh cả hai chiều** | 3 test "xanh" mà vô dụng: kịch bản không đi qua nhánh sửa; đúng-sai theo nền tảng (đồng hồ Windows thô 15ms); test bất biến chạy vòng đời sạch | Tắt bản sửa → phải đỏ. Liệt kê rõ kịch bản KHÔNG đi qua |
| **`import` nằm trong thân hàm → xoá tên là hỏng IM LẶNG** | 2026-09-07 (K3.3c1): dời `_strip_code_fence` sang core; `runner._co_ve_la_json` nhập nó **bên trong hàm** nên không ai đỏ lúc import. 73 test hỏng với triệu chứng khác hẳn (đường ống dừng ở `research-findings` thay vì `clarification-questions`), không lời báo lỗi nào nhắc tới cái tên vừa mất | Trước khi xoá/đổi tên một hàm: `grep -rn '<tên>'` trên **cả src lẫn tests**, không chỉ tin ruff/mypy — import trong thân hàm không bị bắt lúc phân tích tĩnh. Và triệu chứng lệch xa nguyên nhân là dấu hiệu một ngoại lệ đang bị nuốt ở đâu đó |
| **Ép agent làm việc nó không có tool** | 4 vòng rework bắt reviewer xoá một file rác; bộ tool không có `rm`/`git rm`; agent không nói "tôi không xoá được" | Thất bại lặp ở đúng một loại thao tác → mở `tools.py` đọc allowlist TRƯỚC khi chỉnh hint |
| **Sửa một lỗi rồi dừng** | PR #30 sửa một khoá `once`; rà cả họ → thêm 3 khoá hỏng (#31, #32) | Rút một câu hỏi từ lỗi, áp cho mọi chỗ cùng cơ chế, ghi cả chỗ an toàn |
| **Tin dashboard xanh** | Đêm 2026-09-05: `queue: 0, blocked: [], gates: {}` trong khi 18/19 release không đi đâu; `delivery: {}` nghĩa là chưa giao gì; nhãn `merged` ≠ đã gộp | Hỏi "còn việc nào chạy được không?"; tách sự thật git khỏi nhãn FSM. Ghi nhận thiết kế lại: `platform/console/TRAPS.md` |
| **Bốn gate xanh, sản phẩm không chạy** | 2026-09-06 QLKH: 389 test pass, 25 release, 0 điểm vào — `deployed` là lời khai, `regression-staging` là verdict đọc diff | "Chạy cho tôi xem" trước khi tin. Vá: ADR-0029 smoke do orchestrator chạy (PR #90) |
| **Tin test canh quy ước kiểu grep** | 2026-09-07 (#127): test khuôn 3 canh "mọi khoá `once` có thế hệ" xanh suốt #125→#126 trong khi `gate.escalate:{sid}` vẫn hỏng — mẫu chỉ bắt `once=`, mà chuỗi `"once_key="` KHÔNG chứa chuỗi con `"once="` | Test grep xanh chỉ chứng minh **những gì mẫu nhìn thấy** là sạch. Chạy mẫu trên một vi phạm đã biết trước khi tin nó; và kiểm lại LÝ DO từng mục trong danh sách miễn, đừng kế thừa |
| **Số đo trong comment có hạn dùng** | 2026-09-08 (K3.3c3): `company/llm.py` ghi `CLI_NO_TOOL_TURNS = 6` kèm số đo thật ngày 2026-09-05 — `--max-turns 1` + `--json-schema` bị `error_max_turns`, reviewer chết 3/4 lượt. Studio dùng `--max-turns 1`, nên phiên này kết luận "studio có bug đang sống" và suýt mở PR vá. **Đo lại trên CLI 2.1.263 thì KHÔNG tái hiện**: cả prompt tầm thường lẫn schema nặng đều `success`, cap 1 dùng 2 lượt, cap 6 dùng 3 | Comment mô tả hành vi của một công cụ NGOÀI repo là ảnh chụp một phiên bản, không phải bất biến. Dựa vào nó để kết luận thì **đo lại trước**; ghi kèm phiên bản công cụ vào comment thì người sau biết nó đã cũ tới đâu. Cùng khuôn "suy từ thông điệp lỗi" ở dòng đầu bảng, chỉ khác là suy từ ghi chú của người khác |
| **Gộp vai để "giảm cổng"** | 2026-09-13 (#286): yêu cầu vận hành là *"nhiều cổng dễ bị tắc"*, việc làm ra lại là gộp agent `security` vào `qa` (ADR-0040). Gộp xong: **không bỏ được cổng nào, không giảm lượt gọi model nào** — nhãn bằng chứng `security` vẫn phải phát ở một lượt riêng — mà `qa` còn buộc lên tier `strong` cho MỌI lượt (đắt hơn) và mất người chấm bảo mật độc lập. Lùi toàn bộ | **Số vai và số cổng là hai trục khác nhau.** Trước khi gộp, hỏi đúng một câu: *"việc này bỏ được CỔNG nào, bớt được LƯỢT GỌI nào?"* — không trả lời được bằng tên cụ thể thì nó không giải quyết vấn đề đang than. Muốn bớt chờ người thì sửa **điều kiện mở gate** / `RISK_RULES` (`gate_risk.py`), đừng bớt vai |
| **Quyết lại điều một ADR đã quyết** | 2026-09-13 (#286): gộp `security` vào `qa` chính là lật bất biến #2 mà ADR-0037 đã cân nhắc và cố ý giữ, với lý do y hệt (*"rà từng vai: có cơ chế nào trong code cần vai này khác vai kia không?"*). Phiên này đi lại toàn bộ con đường ấy rồi quay về đúng chỗ cũ, tốn một PR | `ls docs/adr/` và grep tên thứ sắp đổi **trước** khi đề xuất, không phải sau. ADR cũ đã quyết → hoặc nêu **dữ kiện mới** mà nó chưa có, hoặc đừng mở lại. `AGENTS.md` luật bắt buộc 11 bắt tìm PR/issue trùng; ADR cũng phải tìm y như vậy |
| **Ba lần vá, mỗi lần lòi chỗ mới** | 2026-09-13 (#286): gộp vai xong lần lượt gãy khoá `partial` → model lẫn nhãn `source` → prompt phình làm model không sinh nổi JSON. Mỗi lần đều vá được, và mỗi lần đều tưởng là lần cuối | Đây là `AGENTS.md` luật bắt buộc 6 đang xảy ra thật: **ba lần liên tiếp lòi vấn đề mới ở chỗ khác ⇒ không còn là bug, là kiến trúc sai.** Dừng, mang giả thiết ra hỏi người; đừng vá lần 4. Dấu hiệu nhận ra sớm: ba lỗi không giống nhau về triệu chứng nhưng **cùng một nguyên nhân gốc** |
| **Tiêu chí nghiệm thu cũng có thể là proxy sai** | 2026-09-07 (#131): K1.8 đặt `wc -l orchestrator.py ≤ 300`, nhưng 250/498 dòng là import + re-export + bảng gán method — chính bề mặt shim mà K1.7 của cùng epic CỐ Ý tạo ra; hai tiêu chí không thể cùng đúng | Tiêu chí không đạt được mà không phá một tiêu chí khác của cùng epic → nghi tiêu chí sai, đừng nghi việc chưa xong. Đo lại rồi đổi **tiêu chí**, và ghi lý do ở nơi người sau đọc (đặc tả + file test) — khác hẳn lặng lẽ hạ số |

## 3. Bẫy thao tác git / CI

**`(#PENDING)` trong CHANGELOG nay là CI ĐỎ — để TRỐNG, đừng đặt chỗ giữ.** Từ phép (d) của `keeper drift`,
mọi `(#PRNUM)`/`(#PENDING)`/`(#n)` **ngoài dấu backtick** trong `CHANGELOG.md` làm job `drift-check` đỏ. Lý do
có phép này: 3/4 ca thiếu dòng CHANGELOG (2026-09-09) là *quên điền số* chứ không phải quên viết dòng, và một
chỗ giữ chỗ không ai quay lại điền thì tệ hơn không có gì — nó trông như đã xong. *Cách làm đúng theo luật 10*:
commit 1 viết dòng CHANGELOG **kết thúc không có số**; sau `gh pr create` thì commit 2 thêm `(#<n>)` vào chính
PR đó. Muốn NHẮC TỚI một placeholder trong văn xuôi (kể lại một bug, trích luật) thì bọc backtick — phép (d)
bỏ qua code span, đúng để tài liệu mô tả được nó mà không tự làm mình đỏ.

**`sed 's/(#<n>)/(#N)/'` để điền số PR sửa nhầm lịch sử CHANGELOG.** Mắc **hai lần trong cùng một ngày**
(2026-09-14, PR #295 rồi #297 — lần thứ hai dù vừa sửa lần thứ nhất xong). Chuỗi `(#<n>)` xuất hiện ở HAI loại
chỗ trong `CHANGELOG.md`: chỗ cần điền (dòng của PR đang mở) và chỗ **trích dẫn nó làm ví dụ** — dòng của #157
kể lại chính luật bắt buộc 10. `sed` không phân biệt được hai loại, nên một lệnh thay-thế-hàng-loạt sửa cả
dòng lịch sử của một PR đã merge.
Cách rà: sau khi điền số, `grep -n '(#<n>)\|(#N)' CHANGELOG.md` và `git diff --stat` — dòng CHANGELOG của PR
đang mở chỉ được đụng ĐÚNG MỘT dòng. Khuôn tổng quát: **thay-thế-hàng-loạt trên file lịch sử thì phải đọc lại
toàn bộ chỗ khớp trước khi commit**, hoặc neo lệnh theo số dòng thay vì theo chuỗi.

**`quality` đỏ với 0 failure — run đã bị thay thế, không phải lỗi.** Mắc ba lần trong phiên 2026-09-08 (#172,
#173, #174). Luật 10 bắt điền `(#<n>)` vào chính PR đó, mà số PR chỉ có sau khi tạo PR — nên luôn có commit thứ
hai đẩy sau commit thứ nhất vài chục giây. `concurrency: cancel-in-progress` cắt run đầu, và `quality` **cố ý**
coi `cancelled` là đỏ (job bị bỏ qua không được tính là qua cổng). Kết quả: mỗi PR sinh đúng một `quality` đỏ
trên head CŨ. *Cách nhận ra*: mở log job `quality` và đọc mảng `RESULTS` — có `failure` mới là lỗi thật; toàn
`success` + `cancelled` là run đã bị thay thế, và bản đúng là run trên head hiện tại. Nó **không chặn merge**
(required check chấm trên head SHA hiện tại), nên đừng đi tìm lỗi trong diff. Đã cân nhắc sửa `ci.yml` hoặc luật
10 và **quyết định không**: cả hai đánh đổi đều tệ hơn cái giá vài phút CI.


| Bẫy | Đã xảy ra | Lần sau |
|---|---|---|
| **Thêm `.gitattributes` không đổi byte của worktree ĐÃ tồn tại** | 2026-09-14 (QLKH-034): merge commit thêm `*.sh text eol=lf` vào `company/integration`, HEAD đúng, nhưng `deploy_process.sh` trong worktree tích hợp vẫn CRLF (`head -c 24 \| xxd` → `bash 0d 0a`) — git chỉ viết lại file có blob đổi; `.gitattributes` chỉ tác động lên checkout MỚI. REL-011 `deploy_failed` đúng dòng 42–43 như trước khi vá | Sau khi merge `.gitattributes`, ép checkout lại từng file trong mọi worktree đang có (`rm <file>` + `git checkout -- <file>`; `git add --renormalize` không đủ vì working tree không đổi), rồi đếm CR bằng Python — `grep -c $'\r'` của Git Bash đếm sai |
| **Hai phiên cùng append `docs/sessions/<ngày>.md`** | 2026-09-09, `/thi-hanh p3` chạy song song `/thi-hanh keeper`: **ba** lần `git rebase origin/main` liên tiếp đều xung đột ở đúng file đó, không file nào khác. Một lần giải sai làm **nhân đôi** một dòng `CHANGELOG.md` — một bản mang `(#PR)`, một bản mang số thật; `sed` điền số sau đó biến cả hai thành giống hệt nhau nên `grep '(#PR)'` trả 0 và trông như đã xong | Xung đột ở nhật ký phiên gần như luôn là *cả hai cùng thêm mục mới* → giữ **cả hai**, mục của PR merge trước xếp trên. Giải xong thì **đếm lại**: `grep -c` cho tiêu đề mục và cho dòng CHANGELOG phải ra đúng 1. Và khi `git show --stat` của một commit *sửa một dòng* hiện `1 +` thay vì `1 +, 1 -` thì đó là nhân đôi, không phải sửa |
| **`git push` thất bại nhưng lệnh sau vẫn chạy** | Hai lần trong phiên 2026-09-09: rebase xung đột → `push` bị từ chối non-fast-forward, nhưng lệnh nối sau vẫn chạy nên `gh pr create` tạo PR **trỏ vào commit cũ** trên remote. Output vẫn in `branch set up to track`, trông như thành công | Sau mỗi `push`, so `git rev-parse HEAD` với `git rev-parse origin/<nhánh>` — hai số phải bằng nhau (luật cấm 8). `gh pr view <n> --json commits` có thể trễ đồng bộ vài giây; đọc kết quả đầu tiên thành kết luận là sai |
| **Đọc `$?` sau một pipe là đọc exit code của lệnh CUỐI trong pipe** | 2026-09-09: `evals … | grep FAIL | head` rồi `echo $?` cho **0** trong khi lệnh eval trả **1** — suýt kết luận cổng điểm eval mới không có răng | Muốn exit code thật thì chạy riêng và vứt stdout: `cmd >/dev/null 2>&1; echo $?`. Hoặc bật `set -o pipefail` |
| **PR không có check nào chạy** | 2026-09-07 (#134): `statusCheckRollup` rỗng, `actions/runs?branch=…` rỗng, PR khác cùng lúc vẫn chạy. Nghi file workflow mới bị từ chối; bỏ nó ra đẩy lại — **vẫn không chạy**. Thật ra `mergeStateStatus = DIRTY`: PR xung đột với `main` | GitHub chạy check trên commit **merge** — PR không merge được thì không có gì để chạy. Kiểm `gh pr view <n> --json mergeStateStatus` TRƯỚC khi nghi Actions hỏng; `DIRTY` = rebase, `BLOCKED` = đang chờ check |
| **PR dependabot của một uv workspace luôn ĐỎ, dù bản nâng vô hại** | 2026-09-09: chín PR (#228–#236) mở cùng lúc, không PR nào gộp được. Chúng chỉ nới sàn `>=` trong `pyproject.toml` CON, không đụng `uv.lock` — mà lock chỉ có MỘT, ở GỐC workspace, nằm ngoài mọi `directory` dependabot được cấu hình. Mọi job CI chạy `uv sync --locked`, lệnh này đỏ khi lock lệch pyproject. Hỏng do CẤU TRÚC cấu hình, không do nội dung bản nâng | Sửa gốc: **một** mục `uv` `directory: /` thay vì sáu mục theo package (#245). Gặp lại kiểu này thì đừng đọc log test — chạy `uv lock --check`: nó nói thẳng "lockfile needs to be updated". Gộp tay thì phải `uv lock` trong CÙNG PR, và kiểm diff lock chỉ đổi dòng `specifier` (không đổi version nào) trước khi tin là vô hại |
| **Gắn nhãn để miễn một cổng CI mà cổng không chạy lại** | 2026-09-09 (#246): cổng `metadata` in ra "hoặc gắn nhãn no-changelog", nhưng `pull_request.types` thiếu `labeled` nên gắn nhãn KHÔNG kích cổng. Bấm re-run tay cũng vô ích: `rerun_failed_jobs` phát lại **payload sự kiện gốc**, mà `github.event.pull_request.labels` đóng băng trong payload đó — gắn nhãn lúc 23:03:15, chạy lại lúc 23:03:23, log vẫn in `LABELS: dependencies,python:uv` | Cổng đọc nhãn thì `types` PHẢI có `labeled`/`unlabeled` (#247), nếu không lời khuyên nó in ra là lời khuyên chết. Chưa vá thì đường duy nhất là đóng/mở lại PR hoặc đẩy một commit — không phải re-run. Rộng hơn: **bất cứ giá trị nào lấy từ `github.event.*` đều là ảnh chụp lúc kích hoạt, không phải trạng thái hiện tại** |
| **Kết luận hiện trạng trên mốc cũ** | 2026-09-07: đọc bảng theo dõi trong một worktree cũ (`main` ở #125), thấy K1.4 "một phần", **làm lại toàn bộ** — sửa 3 khoá `once`, test hai chiều, đo hai chiều. Xong mới `fetch`: `origin/main` đã ở #142 và K1.4 chính là **#127**, kể cả lỗ hổng regex `once_key=` mình tưởng vừa tìm ra | `git fetch origin` **trước tiên**, rồi `CHANGELOG.md` mục "Chưa phát hành" + `gh pr list --state merged`, *rồi mới* mở bảng theo dõi. Bảng theo dõi cập nhật bằng tay nên trôi nhanh nhất repo |
| **Bảng theo dõi ghi "xong" mà chưa xong** | 2026-09-07: K1.5 ghi "xong (từ trước)", dẫn `verify.py:109-111` — nhưng đó là `verdict_with_run` (đường QA hồi quy), còn yêu cầu nói về `smoke()` (đường deploy staging); cờ `legacy` chưa từng tồn tại (#144) | Với mỗi mục định làm, chạy **lệnh nghiệm thu của chính mục đó** trước khi viết dòng code đầu tiên; `grep` tên hàm/cờ mà mục yêu cầu — rỗng nghĩa là chưa làm, bất kể bảng ghi gì |
| **`cmd \| tail` nuốt mã thoát** | 2026-09-07: `pytest … 2>&1 \| tail -12` báo "exit code 0" trong khi pytest lỗi `unrecognized arguments: -n` | Ghi ra file rồi `echo EXIT=$?`. Đừng đọc mã thoát qua ống dẫn |
| **`.pyc` cũ sống sót sau khi khôi phục file (đo hai chiều)** | 2026-09-07 (K3.3b): kịch bản đo hai chiều đổi mã → chạy test → `cp file.bak file` khôi phục. Ca vừa xanh thành **đỏ vĩnh viễn** sau khi khôi phục; `inspect.getsource` in ra mã ĐÚNG nhưng chương trình chạy mã CŨ. Đột biến chỉ đảo chỗ hai dòng nên file khôi phục **cùng kích thước**, và cả hai thao tác nằm trong **cùng một giây** — `__pycache__` khoá theo (mtime, size) nên `.pyc` của bản đột biến được coi là còn hợp lệ | Sau mỗi lần khôi phục file trong kịch bản đo hai chiều: `find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`, hoặc chạy pytest với `PYTHONDONTWRITEBYTECODE=1`. Dấu hiệu nhận ra: mã trên đĩa và hành vi lệch nhau, `inspect.getsource` vô can |
| **Worktree mới thiếu nhóm `dev`** | 2026-09-07: `uv run pytest -n auto` trong worktree vừa tạo báo `unrecognized arguments: -n` — `.venv` riêng của worktree chưa có `pytest-xdist` | `uv sync` ở **gốc worktree** (không phải trong thư mục package) ngay sau `git worktree add` |
| Hai phiên chung một clone | 2026-09-06 15:07: phiên B checkout `main`, commit của phiên A rơi vào `main`, nhánh A rỗng (#86) | `git worktree add` cho mỗi phiên; `git worktree list` trước khi bắt đầu |
| Push sau khi auto-merge đã bật | #77 thiếu sweep, commit rơi khỏi PR, phải mở #78 | `gh pr view --json commits` sau push; hoặc bật auto-merge sau commit cuối |
| Chạy test không `--cov` rồi tin là xanh | CI Linux đỏ coverage (#78) | Chạy đúng lệnh CI: `pytest -n auto --cov` |
| Scope PR hai từ | `fix(company,console)` bị `metadata` chặn (#80) | Một từ, chữ thường |
| Sửa `checklists.md` mà không `make subagents` | `test_ban_dan_xuat_tren_dia_khop_nguon` đỏ (#90) | Sửa nguồn → sinh lại → commit `.claude/agents/` |
| Thêm file test / ADR mà không sửa README | `test_readme_khop_so_lieu_that` đỏ: README ghi 43 file, thực tế 44 | README của companies/software-company/Studio ghi số ca/file test và ADR mới nhất — test đếm lại từ đĩa |
| **Chạy mypy/ruff từ GỐC repo thay vì thư mục package** | 2026-09-08 (#188): `uv run mypy platform/xagents-core/src/xagents_core` từ gốc báo **Success**, CI `core-static` báo `registry.py:122: Missing type arguments for generic type "dict"`. Mypy đọc `[tool.mypy]` theo **thư mục chạy**, không theo đường dẫn tham số — từ gốc nó lấy cấu hình lỏng của pyproject gốc, `strict = true` của `platform/xagents-core/pyproject.toml` không được áp | Chạy mypy/ruff **trong đúng thư mục package**, đúng lệnh CI: `cd platform/xagents-core && uv run mypy src/xagents_core` (core KHÔNG có `--ignore-missing-imports`). "Đường dẫn đúng" không bằng "thư mục đúng" |
| **Sửa một chữ trong prompt = mọi bản ghi eval lệch** | 2026-09-09 (#PR, K3.6d1): định gộp `build_user_message` của hai công ty lên core. Đo trước: thêm **một dấu cách** vào chuỗi cuối của prompt studio rồi `python -m studio.evals all --replay` → mọi ca báo *"bản ghi eval lệch prompt hiện tại"*. Khoá bản ghi là `hash(system_prompt, user_message)` | Trước khi chạm bất cứ chuỗi nào đi vào prompt (`build_user_message`, `context_writes_schema`, `tools_prompt`, `agents/`, `skills/`): hoặc giữ nguyên **từng byte**, hoặc chấp nhận 7 bước `CONTRIBUTING.md` §3 với `make eval-record` bằng model thật. Nghiệm thu rẻ: `evals all --replay` hai công ty phải 0 FAIL |
| Thêm job CI mà không nối `needs` của `quality` | Kết quả job không được tính | `quality` là required check bất biến; nối job mới vào `needs` |
| Khởi động lại orchestrator quên lock | Tiến trình mới thoát ngay, tưởng đã restart | Kiểm `company.sqlite.lock` đổi PID và có audit mới. Nay `run --watch` tự khởi động lại (#83) |
| `--db` đặt sau `publish` | `unrecognized arguments` lúc diễn tập dừng khẩn | `--db` đứng TRƯỚC subcommand; `--key` bắt buộc với `supervisor-actions` |
| `status`/`gate_cli` chạy ở gốc repo | Gốc có `company.sqlite` rỗng → nhìn như không có gì | Chạy trong `companies/software-company/` |
| Heredoc chứa `'''`/backtick | Vỡ parse 2 lần | Ghi file scratchpad rồi `python file.py` |
| `git stash`/`checkout` trong lúc `make eval-record` | Bản ghi mang version prompt sai (2026-09-05) | Không đụng file prompt khi đang ghi eval; `RecordingClient` nay chốt version lúc bắt đầu |
| **Hook cổng đọc `CLAUDE_PROJECT_DIR` thay vì cây đang commit** | 2026-09-15 (`pt.10`): `CLAUDE.md` luật 2 bắt mỗi phiên một worktree, nhưng `pre-commit-gate.sh` đọc `git -C "$CLAUDE_PROJECT_DIR"` = checkout chính. Hỏng **cả hai chiều cùng lúc**: phép 1 thấy nhánh `main` của checkout chính → chặn oan mọi commit đúng luật; phép 2–4 đọc index checkout chính (rỗng) → file cấm, hạ `fail_under` và cổng gói **không được canh gì cả**. Không ca test nào thấy vì mọi ca cũ đặt cwd = `CLAUDE_PROJECT_DIR`. **Tái phát 2026-09-27 ở phép 4**: bản vá chỉ chuyển phép đọc git sang `$CAY`, cổng vẫn gọi `$ROOT/scripts/dev-task.sh` — mà `dev-task.sh` tự lấy cây từ `CLAUDE_PROJECT_DIR` để `cd` và chọn venv. Từ worktree `release-bang-chung`, hook đỏ `uv trampoline failed to canonicalize script path` ở `uv run mypy` (venv checkout chính: Python 3.11, mypy.exe 04/09); cùng cổng chạy thẳng trong worktree xanh. Chiều kia cũng mở: checkout chính xanh thì code worktree đỏ vẫn qua. Ca test cũ không thấy vì repo giả không có `scripts/dev-task.sh` → phép 4 luôn "bỏ qua" | Trong hook: tách hai nghĩa thành hai biến — `$ROOT` chỉ để **tìm script** trong repo, `$CAY = git rev-parse --show-toplevel` (lùi về `$ROOT` nếu rỗng) cho **mọi phép đọc trạng thái git**. Ca test của hook phải dựng worktree thật, nhánh của checkout chính khác nhánh worktree; hai chiều (không chặn oan + vẫn chặn file cấm). Đã rà cả họ: `block-dangerous-git.sh` không đọc trạng thái git (chỉ parse chuỗi lệnh) và `auto-format.sh` chỉ dùng `$ROOT` để tìm `dev-task.sh` + thao tác trên đường dẫn tuyệt đối từ payload → cả hai an toàn, không phải sửa. **Sau lần tái phát**: "tìm script" ≠ "script chạy trên cây nào" — gọi script nào thì `grep` cả biến môi trường script đó đọc. Phép 4 nay `CLAUDE_PROJECT_DIR="$CAY" "$CAY/scripts/dev-task.sh"`, lùi về `$ROOT` khi cây không có script; ca test đặt `dev-task.sh` giả **riêng mỗi cây**, khai bản nào chạy và biến trỏ cây nào. Hook chạy là bản của **checkout chính** (`settings.json` trỏ `${CLAUDE_PROJECT_DIR}/.claude/hooks/`) → sửa hook chỉ có hiệu lực sau merge + `pull` ở checkout chính. Rà lại `auto-format.sh`: `format-file` chạy `ruff format` bằng venv checkout chính trên file worktree — lệch phiên bản ruff chỉ đổi kiểu format, CI không chạy `ruff format --check`; venv chính hỏng thì format im lặng không chạy (hook luôn exit 0). Không cổng nào sai → để nguyên |
| **Hook `auto-format.sh` format CẢ file sau một lần Edit** | 2026-09-22 → 09-27 (sửa ở #364), năm lần trong bốn ngày: `format-file` chạy `ruff format` toàn file, trong khi phần lớn repo cố ý viết gọn một dòng (`a = 1; b = 2`, `if x: return` — `.pre-commit-config.yaml` đã ghi "chỉ ruff-check, không ruff-format") và CI chỉ chạy `ruff check`. Sửa 5 dòng `orch/guards.py` thành +82, 6 dòng `workspace.py` thành +212; `orch/gates_flow.py` 399 → 591 dòng, vượt trần 400 của `test_orch_khuon_loi.py`; `orchestrator.py` vượt trần thân hàm 260 dù logic không đổi. Tiền đề sai nằm ngay trong chú thích hook ("`ruff format` lệch là lỗi lint ở CI"). Cả năm lần đều ghi vào nhật ký rồi lách bằng script python thay chuỗi, không phiên nào sửa hook | `format-file` chỉ format khi bản trong **index** vốn sạch (`git show :./<file> \| ruff format --check --stdin-filename <file> -`) hoặc file mới chưa track; ngoài repo hay git lỗi → bỏ qua (không chắc thì đừng đụng: bỏ sót format rẻ, phình diff đắt). `--stdin-filename` là bắt buộc: thiếu nó ruff lấy cấu hình mặc định (line-length 88) và file sạch cũng thành bẩn. Đo trên chính `guards.py`, cùng một dòng thêm: bản cũ +52/−23, bản mới +1/−0. Như mọi hook (dòng trên), bản chạy là của checkout chính → có hiệu lực sau merge + `pull` ở đó. Rà cả họ: `.pre-commit-config.yaml` chỉ `ruff-check`; `dev-task.sh format` (cả gói) vẫn format toàn bộ nhưng không hook nào gọi — chỉ chạy khi cố ý. Khuôn chung: **bẫy đã vào nhật ký phiên từ lần thứ hai là bẫy của `TRAPS.md`** — lách lần hai thì sửa gốc |

## 4. Bẫy vận hành công ty (người trực)

| Bẫy | Đã xảy ra | Lần sau |
|---|---|---|
| Duyệt gate lý do "ok" | 2026-09-06 13:05 → agent nhận hint rỗng | root_cause + decision + hint; console khoá < 20 ký tự (#80) |
| Duyệt nhầm loại gate | Duyệt `escalation` cho REL-xxx tưởng đã giao hàng; chỉ `kind=release` mới deploy | Đọc `kind` và hậu quả trước khi bấm |
| Ghi tay blackboard để mở khoá | Threat-model cũ chặn mọi RC | Đổi qua đúng vai: CR → `product` (pha spec) ghi `prd`, `security` ghi `threat-model` |
| Console mở, orchestrator tắt | Việc giao nằm im | Bật `run --watch` cùng lúc |
| Agent tự dừng `pending_human` không ai xử lý | 10 RC kẹt, status xanh (#77/#78) | Mọi "chờ người" của agent phải mở gate; sweep mỗi nhịp |
| Trường identity do model khai | `env`/`release_id`/`ticket_id` lệch → Gate 3 không mở (#72, #75) | Identity lấy từ ROUTE; model chỉ điền nội dung; audit `*_overridden` |
| Lượt production không thấy bằng chứng staging | Agent nói "chưa qua staging" dù có (#80) | Agent không có tool đọc bus → payload phải mang đủ bằng chứng |
| Từ chối escalation của RC cũ = trả ticket đã giao về làm lại | #80 `_superseded_release` | Hành vi "đóng" phải xét nội dung đã tới khách chưa |
| Reviewer chấm trên diff đã bị cắt mà không biết | security-engineer chặn QLKH-012 vì "thiếu diff" — openapi 804 dòng ăn hết hạn mức | Diff ưu tiên mã nguồn, nói rõ file bị bỏ (#67); reviewer có tool đọc (#87) |

## 5. Cách thêm mục mới

Một bẫy đủ điều kiện vào đây khi: (a) đã xảy ra thật, (b) tốn ít nhất một giờ hoặc một PR, (c) có câu "lần sau"
cụ thể mà người khác làm theo được. Ghi ngày + PR. Mục cũ tái phát thì thêm ngày, đừng tạo mục mới.

## 6. Câu tự biện hộ thường gặp trước khi né luật

Khác §1–4: đây không phải sự cố đã xảy ra, mà là **câu mình sẽ tự nói với mình** ngay trước khi phá một luật ở
`AGENTS.md` — ghi trước để nhận ra lúc nó xuất hiện trong đầu. Bắt gặp một câu ở cột trái → dừng, làm theo cột
phải trước khi tiếp tục. (Lấy cảm hứng từ bảng "Common Rationalizations" của skill `superpowers`.)

| Câu tự biện hộ | Sự thật |
|---|---|
| "Chắc chạy được, khỏi chạy lại" | Luật cấm 8: chưa chạy trong chính lượt này thì chưa được nói đã xanh |
| "Đơn giản quá, khỏi viết test trước" | Code đơn giản vẫn có bug đơn giản; test trước tốn 30 giây, không tốn hơn viết sau |
| "Viết test sau cũng đạt mục đích như test trước" | Test viết sau xanh ngay từ đầu — chưa từng chứng minh nó BẮT được lỗi. Test trước bắt buộc phải thấy nó đỏ đúng lý do trước |
| "Đã tự tay thử rồi, khỏi cần test" | Thử tay không để lại bằng chứng, không chạy lại được khi code đổi, dễ quên ca biên khi vội |
| "Giữ code cũ làm tham khảo, viết test rồi khớp vào sau" | Đó vẫn là viết-sau, chỉ trá hình. Xoá hẳn, viết test trước, code lại từ đầu |
| "Đã thử 3 lần, thử thêm lần 4 chắc trúng" | Luật bắt buộc 6: 3 lần vá liên tiếp lòi vấn đề mới ở chỗ khác = kiến trúc sai, không phải chưa đủ may. Dừng, hỏi người |
| "Log/lỗi nói rõ nguyên nhân rồi, khỏi tái hiện" | Suy từ thông điệp lỗi đã sai 6/6 lần trong repo này (§2) — tái hiện với đối chứng trước khi tin |
| "Việc nhỏ, khỏi cần tách nhánh/worktree" | Luật cấm 2: hai phiên chung một clone làm mất commit không cảnh báo gì (§3) — nhỏ hay lớn không miễn |
| "Merge tay một lần cho nhanh, CI đang chạy chậm" | `docs/QUY-TRINH-GIT.md` §5: cấm duy nhất ở bước merge — chờ CI xanh, không đi tắt |
| "Coverage thiếu đúng 1 dòng, hạ `fail_under` một xíu rồi trả lại sau" | Luật cấm 6: không có "trả lại sau" — hạ số bị phát hiện ngay khi ai đó grep `fail_under`; thêm test rẻ hơn debug niềm tin |
| "PR này chắc chưa ai làm, cứ mở luôn" | Luật bắt buộc 11: kiểm cả PR/issue đã đóng bằng từ khoá trước — mở trùng tốn CI, tốn review, có thể lặp lại đúng lý do lần trước đã đóng |
| "Dashboard xanh, chắc ổn" | Bẫy "Tin dashboard xanh" ở §2: số 0/rỗng có thể là chưa đo, không phải đã đo và sạch — hỏi "chạy cho tôi xem" trước khi tin |
