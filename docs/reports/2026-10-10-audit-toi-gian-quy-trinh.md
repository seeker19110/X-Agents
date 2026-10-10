# Audit tối giản quy trình — 2026-10-10

Căn cứ `main@2dd4750` (#395), nhánh `claude/ecstatic-bardeen-qtt4iz`, phiên cloud, lịch sử đầy đủ (`git fetch
--unshallow`, 867 commit). Đề bài: **bớt quy trình mà không làm giảm chất lượng sản phẩm tạo ra**.

## 0. Kết luận một đoạn

Phần quy trình bảo vệ sản phẩm (cổng CI 32 job, phủ 100%, test đỏ trước, eval replay, golden, assetscan,
gitleaks, ruleset không bypass) **không có gì nên cắt**. Phần đắt là **thủ tục ghi chép xung quanh PR**. Đo
được: 18/25 PR không phải dependabot kể từ 28/09 phải có một commit riêng chỉ để điền `(#n)`, nên mỗi PR chạy
thêm một lượt CI (~32 phút-runner, ~8,5 phút chờ). 14/251 PR kể từ 07/09 chỉ để vá CHANGELOG, nhật ký phiên
hoặc số PR. Mỗi lần merge một PR dependabot, `main` đỏ vì hai cổng hiểu ngược nhau về nhãn `no-changelog`.
Mẫu PR bắt tự khai ba lần cùng một điều mà CI đã kiểm. Audit cũng tìm ra ba chỗ quy trình **sai thật**
(F1–F3): sửa chúng vừa bớt việc vừa tăng chất lượng.

## 1. Tiêu chí cắt

Chỉ đề xuất bỏ hoặc gộp một bước khi bước đó thoả ít nhất một trong ba điều kiện:

- **(a) Trùng cổng máy**: một cổng CI hay hook đã chặn đúng điều đó, và không ai bypass được (ruleset
  `bypass_actors` rỗng).
- **(b) Chỉ là sổ sách**: không bảo vệ thuộc tính nào của sản phẩm hay của `main`, chỉ ghi lại việc đã làm. Thứ
  ghi lại phải vẫn truy được từ git hoặc PR.
- **(c) Bản sao**: cùng một luật được chép ở nhiều chỗ, mà mỗi bản sao lại cần thêm một test để không lệch.

Bước nào bảo vệ hành vi sản phẩm thì **không** đưa vào diện cắt, dù đắt (xem §4).

## 2. Số đo

| Chỉ số | Giá trị | Cách đo |
|---|---|---|
| PR merge từ 07/09 | 251 | `git log --since=2026-09-07`, subject có `(#n)` |
| PR chỉ chạm `CHANGELOG.md` và/hoặc `docs/sessions/` | 12 | `git show --name-only` từng commit, không còn file nào khác |
| PR chỉ để điền số PR | 2 (#349, #225) | subject "điền số PR" |
| PR từ 28/09 có commit con riêng để điền `(#n)` | 18/25 (bỏ 3 PR dependabot) | thân commit squash: "điền số PR", "record PR", "link … to PR" |
| Một lượt CI cho PR | 32 job, 32,0 phút-runner, ~8,5 phút chờ | run 37342626964 (#395), API Actions |
| Đường găng CI | `unit (windows-latest, 3.13)` 402 s | cùng run |
| Lượt CI của #395 | 2 (lượt 1 bị huỷ khi đẩy commit điền số) | run 37342608871 `cancelled`, 37342626964 `success` |
| Hook commit, phần console đầy đủ | 109 s, 671 test | `scripts/dev-task.sh gate console`, máy cloud này |
| Chỉ các test cổng canh của console | 9 s, 230 test | `pytest tests/test_cong_*.py` |
| Luật nạp mỗi phiên Claude Code | 26,5 KB (`AGENTS.md` 16,8 KB + `CLAUDE.md` 9,8 KB) | `wc -c` |
| PR chạm hạ tầng quy trình (hook, `.github/`, luật, `test_cong_*`) từ 07/09 | 60/251 (24%) | `git show --name-only` |

## 3. Phát hiện và đề xuất

### Ưu tiên 1: quy trình sai thật (sửa vừa bớt việc vừa tăng chất lượng)

**F1. `drift-check` phép (c) và nhãn `no-changelog` hiểu ngược nhau, nên `main` đỏ sau mỗi PR dependabot.**
`.github/dependabot.yml` gắn `no-changelog` để `metadata` cho qua. Sau khi merge, `keeper drift` phép (c)
(`companies/keeper/src/keeper/drift.py`, `changelog_drift`) đòi mọi `(#n)` trong `git log` phải có trong
CHANGELOG. Hàm này không biết nhãn, nên `main` đỏ cho tới khi có người mở PR bù. Đã xảy ra hai lần: #333 bù
#331/#332, #383 bù #371–#373. PR `eval-record` cũng gắn `no-changelog`, nên dính cùng lỗi.
Từ khi `scripts/pr_changelog_check.py` (#362) chặn **trước** merge và ruleset không cho bypass, phép (c) không
còn bắt được PR nào có lỗi thật. Nó chỉ còn bắt các PR được miễn hợp lệ, tức toàn báo động giả.
→ **Đề xuất:** bỏ phép (c) (giữ phép (d), tức phép bắt chỗ trống số PR), hoặc tối thiểu cho phép (c) bỏ qua
subject `build(deps)`/`ci(deps)`/`chore(<gói>): ghi lại eval`. *Không giảm chất lượng vì* điều phép (c) canh đã
được `metadata` chặn trước merge, đúng điều kiện (a).

**F2. `dev-task.sh gate` tự nhận "khớp đúng `ci.yml`" nhưng thiếu một lệnh.** Từ #381, job `static` chạy mypy
company thêm một lần với extra `graph` (`uv run --locked --extra graph mypy src/company …`).
`scripts/dev-task.sh` chỉ có lần đầu (`DEV_TASK_DRY_RUN=1 scripts/dev-task.sh gate company` in đúng một dòng
mypy). Hook commit và BÁO CÁO XÁC THỰC đều tin vào `gate`, nên lỗi kiểu ở `graph.py` lọt cổng cục bộ và chỉ lộ
trên CI. `test_cong_khung.py` không bắt được vì nó chỉ kiểm chuỗi `mypy src/<module>`.
→ **Đề xuất:** thêm lần mypy `--extra graph` vào `typecheck company`, kèm một test đối chiếu số lệnh mypy của
`static` trong `ci.yml` với dry-run. *Tăng chất lượng*: cổng cục bộ bắt được thêm một loại lỗi.

**F3. Nhật ký phiên là "chỉ cảnh báo" ở CI nhưng thành "chặn merge" qua ô DoD.** `pr-policy.yml` (K8.4) cố ý
để thiếu `docs/sessions/<ngày>.md` chỉ là cảnh báo. Nhưng ô DoD trong `.github/pull_request_template.md` lại
gộp "`CHANGELOG` mang `(#n)` **và** `docs/sessions/<ngày>.md` nằm trong CHÍNH PR này" vào một ô, và
`scripts/pr_dod_check.py` chặn mọi ô chưa tick. Người viết PR chỉ còn hai lựa chọn: viết nhật ký cho mỗi PR
(đúng thứ K8.4 nói là "phạt sai chỗ"), hoặc tick một điều chưa đúng (trái luật cấm 8). Hai luật mâu thuẫn nhau.
→ **Đề xuất:** tách phần nhật ký ra khỏi ô DoD. Nhật ký phiên theo luật bắt buộc 9 (cuối phiên), không theo
luật 10 (mỗi PR). *Không giảm chất lượng*: nhật ký không bảo vệ sản phẩm, điều kiện (b).

### Ưu tiên 2: bớt việc tay, giữ nguyên cổng máy

**F4. Luật "`(#n)` trong CHANGELOG ngay trong PR" làm mỗi PR tốn thêm một lượt đẩy và một lượt CI.** Số PR chỉ
có sau `gh pr create`, nên 18/25 PR gần đây phải đẩy thêm một commit chỉ để điền số. Lượt CI đang chạy bị huỷ
(`cancel-in-progress`) và một lượt 32 job chạy lại. Lượt sau thường dài hơn, vì có trường hợp lượt đầu đã gần
xong. Các PR theo §2d (PR nháp sớm) không bị, nhưng đa số PR chỉ có một task. Số PR **đã có sẵn** trong subject
commit squash trên `main` (`… (#395)`), nên dòng CHANGELOG mang thêm số là thông tin trùng.
→ **Đề xuất (cần người quyết, vì đổi luật bắt buộc 10):** vẫn bắt buộc dòng CHANGELOG trong chính PR, nhưng
**không bắt** `(#n)`. Liên kết dòng với PR thì tra `git log -S"<dòng>"` hoặc `git blame CHANGELOG.md`, cả hai
đều trả về commit squash có số. `pr_changelog_check.py` chỉ còn kiểm "có dòng thêm"; phép (d) giữ nguyên để
chặn chỗ trống kiểu `(#PENDING)`. Đi cùng F1. *Không giảm chất lượng*: điều kiện (b); không cổng nào bảo vệ
sản phẩm bị bỏ. Tiết kiệm ước tính: ~1 lượt CI và ~8 phút chờ cho mỗi PR, đồng thời hết loại PR "bù số".

**F5. Mẫu PR bắt tự khai ba lần cùng một điều mà CI đã kiểm.** Mục *Validation* (4 ô), *Definition of Done*
(7 ô) và khối *BÁO CÁO XÁC THỰC* (8 dòng) cùng hỏi "cổng xanh chưa", "test đỏ trước chưa", "CHANGELOG chưa".
Khối BÁO CÁO còn bắt ghi `make lint` / `make test` / `make cov`: ba lệnh, pytest chạy hai lần, và ngược với
`CLAUDE.md` điều 6 ("một lệnh cho cổng: `dev-task.sh gate`, đừng tự gõ rời"). Ô tick là lời khai. Luật cấm 8
đã nói không tin lời khai, và `quality` mới là thứ chặn merge.
→ **Đề xuất:** giữ **một** khối BÁO CÁO XÁC THỰC và thay ba dòng `make` bằng một dòng
`scripts/dev-task.sh gate <gói>`. Bỏ mục *Validation* vì trùng khối BÁO CÁO. DoD chỉ giữ các ô máy không kiểm
được: khớp đặc tả/ADR, chỉ gồm thay đổi trong phạm vi, breaking change, tài liệu. Sửa `AGENTS.md` luật cấm 8
cùng lúc, vì `test_mau_pr_mang_nguyen_van_khoi_bao_cao_xac_thuc` đòi hai khối trùng nhau. *Không giảm chất
lượng*: điều kiện (a). Phần không máy nào kiểm được (tên ca test đỏ, đặc tả, phạm vi) vẫn nằm lại.

**F6. Hook commit chạy đủ 671 test console (109 s) cho cả commit chỉ sửa tài liệu.** Lý do đúng: console giữ
các cổng cấp repo (link, README đếm test, mẫu PR…). Nhưng phần đó chỉ là các file `test_cong_*` cộng vài file
đọc tài liệu (`test_readme_goc.py`, `test_pr_*_check.py`, `test_ecc_vendor.py`, `test_auto_compact_config.py`).
Chạy riêng các file `test_cong_*` mất 9 s.
→ **Đề xuất:** gắn marker `cong_repo` cho các test đọc file ngoài gói. Commit không chạm mã Python thì hook
chạy `pytest -m cong_repo` thay cho cả suite có `--cov`. Có thể kèm một test canh "test đọc `ROOT/…` phải mang
marker", theo cùng khuôn `TEST_DOC_NGOAI_GOI` đang có. *Không giảm chất lượng*: CI vẫn chạy đủ, hook chỉ là
lớp chặn sớm, và commit tài liệu không làm đổi được độ phủ mã.

**F7. Một luật, nhiều bản chép, mỗi bản lại có test canh.** `CLAUDE.md` mở đầu bằng "chỉ là thứ khác biệt khi
agent là Claude Code", nhưng phần "Bảy điều" chép lại luật cấm 1, 3, 6 và luật bắt buộc 3, 4, 6, 11 của
`AGENTS.md` (được `@AGENTS.md` nạp ngay dòng đầu). Bước 0 của `docs/QUY-TRINH-GIT.md` §5 chép lại luật 10 và
11. Bốn file của harness khác chép hai danh sách, rồi cần `test_ban_sao_luat_khong_thieu_phan_tu_danh_sach`
canh chúng. Mỗi phiên Claude Code nạp 26,5 KB luật, trong đó có nhiều đoạn kể lại lịch sử sự cố.
→ **Đề xuất:** `CLAUDE.md` chỉ giữ phần thật sự khác biệt (hook, skill, compact, Windows). Thay "Bảy điều" bằng
một dòng trỏ về các mục của `AGENTS.md`. Chuyển các đoạn kể sự cố trong luật (vd đoạn reflog 2026-09-06 ở
`QUY-TRINH-GIT.md` §2b, các đoạn "vì sao" dài ở §8) sang `TRAPS.md` hoặc ADR, để lại một dòng dẫn. *Không giảm
chất lượng*: điều kiện (c). Số luật không đổi, chỉ bớt bản sao, và bớt bản sao thì bớt luôn test canh bản sao.

### Ưu tiên 3: đã xét, **không** đề xuất cắt

| Ứng viên | Vì sao giữ |
|---|---|
| Lọc CI theo đường dẫn (PR tài liệu bỏ job test) | Console đọc tài liệu nên PR tài liệu vẫn có thể đỏ. `quality` coi `skipped` là đỏ, nên lọc theo đường dẫn phải đẻ thêm cơ chế mới, đúng thứ đề bài muốn bớt |
| Chân Windows, chân Python 3.11 | Đã bắt lỗi thật mà Linux 3.13 không thấy (#203). 3.11 là cận dưới `requires-python` |
| `static` tách khỏi `unit` | Gộp lại chỉ tiết kiệm ~15 s/job, không rút được đường găng (402 s Windows) |
| "Chỉ một PR mở" (§2c) | Ruleset đặt `strict: false`, nên đây là thứ chặn xung đột ngữ nghĩa giữa hai PR. Sau F4, phần xung đột vì dòng CHANGELOG sẽ giảm nên luật này đỡ đắt hơn |
| `pip-audit` toàn bộ lock trên mọi PR | Chặn PR vì một CVE không do PR gây ra (3 PR dependabot #396–#398 đỏ ở `audit` từ 08/10). Đổi sang chạy theo lịch là đánh đổi bảo mật, cần người quyết, không thuộc diện "không giảm chất lượng" |
| Bảy bước `CONTRIBUTING.md` §3 | Mỗi bước có một cổng CI tương ứng (golden-check, eval-replay `--strict`, asset-scan, subagents check). Đây là chi phí của "prompt là code", không phải thủ tục |

## 4. Giữ nguyên (lõi chất lượng)

`fail_under = 100` ở năm gói · TDD đỏ trước, đo hai chiều · 32 job CI và `quality` · eval `--selftest` +
`--replay --strict` · golden-check + subagents check · asset-scan + budget · gitleaks + pip-audit +
dependency-review · ecc-check · protection-guard + ruleset không bypass · hook chặn commit lên `main`, chặn file
cấm, chặn hạ `fail_under`.

## 5. Thứ tự làm đề xuất

| Bước | Việc | Cần người quyết? | Gói chạm |
|---|---|---|---|
| 1 | F2: `dev-task.sh` thêm mypy `--extra graph` và test đối chiếu `ci.yml` | Không, là lỗi | scripts, console tests |
| 2 | F1 + F3: bỏ phép (c) (hoặc miễn deps/eval), tách nhật ký khỏi ô DoD | Không, là mâu thuẫn giữa các luật | keeper, `.github/` |
| 3 | F4 + F5: bỏ bắt `(#n)`, gọn mẫu PR và khối BÁO CÁO | **Có**: đổi `AGENTS.md` luật bắt buộc 10 và luật cấm 8 | `AGENTS.md`, `.github/`, scripts, console tests |
| 4 | F6: marker `cong_repo` cho hook | Không | `.claude/hooks`, console tests |
| 5 | F7: rút `CLAUDE.md` về phần khác biệt, chuyển đoạn kể sự cố sang `TRAPS.md` | Nên hỏi: đổi giọng luật | tài liệu |

Mỗi bước là một PR riêng, có test đỏ trước theo luật bắt buộc 4. Bước 1–2 sửa lỗi nên có thể làm ngay. Bước 3
đổi luật nên cần người chốt trước.

## 6. Thi hành (cùng ngày)

Người dùng duyệt cả năm bước, không cần hỏi lại. Mục tiêu: chất lượng cao, bớt thủ tục. Bốn nhóm chạy song
song, mỗi nhóm một worktree, chia theo file để không giẫm chân nhau. Phiên chính gộp lại, ghi CHANGELOG và nhật
ký đúng **một lần**, rồi chạy `gate all`.

| Nhóm | Phát hiện | File chính |
|---|---|---|
| A, keeper | F1: bỏ phép (c) `changelog_drift`, giữ (d) | `companies/keeper/src/keeper/drift.py`, `cli.py`, test, tài liệu keeper |
| B, khung cổng | F2 + F6: `dev-task.sh` khớp `ci.yml`, marker `cong_repo` cho hook | `scripts/dev-task.sh`, `.claude/hooks/pre-commit-gate.sh`, console tests |
| C, thủ tục PR | F3 + F4 + F5: bỏ bắt `(#n)`, gọn mẫu PR và khối BÁO CÁO | `AGENTS.md`, `.github/`, `scripts/pr_*`, `docs/QUY-TRINH-GIT.md` §2d/§5 |
| D, tài liệu | F7: `CLAUDE.md` chỉ giữ phần khác biệt, chuyển đoạn kể sự cố sang `TRAPS.md` | `CLAUDE.md`, `docs/QUY-TRINH-GIT.md` §2b/§8, `TRAPS.md` |

### Kết quả gộp

| Phát hiện | Commit | Bằng chứng đo |
|---|---|---|
| F7 | `051be22` | `CLAUDE.md` không còn chép luật của `AGENTS.md`; `test_cong_repo` xanh |
| F4 | `23d795e` | `pr_changelog_check` chỉ đòi có dòng thêm; test đổi theo, đỏ trước khi sửa script |
| F3 + F5 | `b92d75e` | ba test mới về mẫu PR, đỏ trước khi sửa mẫu |
| F1 | `a4b2300` | `keeper drift` không còn phép (c); `drift-check` bỏ `fetch-depth: 0` |
| F2 | `71608da` | `DEV_TASK_DRY_RUN=1 dev-task.sh typecheck company` in đủ hai lệnh mypy của job `static` |
| F6 | `02118cd` | `repo-gate`: 341 test trong ~28 s, thay cho gate console đầy đủ 694 test trong ~104 s |

Lúc gộp còn sót vài chú thích trỏ "`CLAUDE.md` luật 2/§8". Phiên chính đã sửa chúng thành `AGENTS.md` luật cấm 2 và
§"Hàng rào thi hành". Tài liệu lịch sử (`CHANGELOG`, `docs/sessions/`, `docs/thi-hanh/`) giữ nguyên chữ cũ.
