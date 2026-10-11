# Trực ban và dừng khẩn

> Người trực mở **đúng file này** khi có chuyện. Mọi lệnh dưới đây **đã được chạy thật** ngày 2026-09-05,
> không phải suy đoán từ đọc code; chỗ nào chưa kiểm được thì ghi rõ là chưa.
> Bối cảnh vận hành ba người: `docs/QUY-TRINH-GIT.md` §8 (bảo vệ nhánh), `docs/HUONG-DAN-VAN-HANH.md` (cài đặt).

## 1. Dừng khẩn — làm gì trong 60 giây đầu

**Không có nút "kill switch" một phát.** Có ba mức, mức càng thấp càng ít thiệt hại:

| Mức | Khi nào | Lệnh | Đã đo |
|---|---|---|---|
| **1. Một ticket** | Một ticket chạy sai: sửa nhầm file, vòng lặp, tốn token bất thường | `publish` một `supervisor-actions` `pause` với `--key <ticket_id>` | **0,27 s** để phát lệnh |
| **2. Cả dự án** | Nhiều ticket cùng hỏng, hoặc chưa biết ticket nào | Như trên nhưng `--key <project_id>` và `project_id` trong payload | cùng cơ chế |
| **3. Toàn hệ thống** | Nghi ngờ nghiêm trọng (rò rỉ, agent chạm thứ không được phép) | **Dừng tiến trình `orchestrator run`** (Ctrl-C hoặc kill PID) | tức thì |

### Mức 0 — dừng chính HUB (container console+orchestrator, ADR-0013)

Chỉ áp dụng khi hub chạy bằng `docker compose up -d` (gốc repo) theo ADR-0013 — **khác hẳn** Mức 4 dưới đây
(Mức 4 là container *sản phẩm của khách*, đặt tên `company-<project_id>-<env>`; hub luôn tên project mặc định
lấy theo tên thư mục, service `hub`).

```bash
docker compose down          # dừng console + orchestrator đang chạy trong container hub
docker compose ps            # xác nhận không còn service nào "running"
```

**State của bản container nằm ở `companies/<công ty>/var/`** (ADR-0014), KHÁC chỗ bản chạy trần
(`companies/software-company/company.sqlite`). Đọc bus bằng CLI trên host trong lúc hub chạy trong container thì
phải trỏ đúng chỗ, nếu không sẽ đọc một bus rỗng và tưởng công ty đứng im:

```bash
cd companies/software-company
uv run python -m company.orchestrator --db var/company.sqlite status
```

`down` KHÔNG đụng tới container sản phẩm của khách (Mức 4) — chúng là compose project khác, đứng độc lập vì
`docker.sock` chỉ được **mount qua** cho orchestrator gọi, không phải orchestrator chạy `dockerd` trong hub.
Trạng thái công ty (`company.sqlite`, `.artifacts`) nằm ở volume, `down` không xoá dữ liệu; `docker compose up
-d --build` chạy lại là tiếp tục đúng chỗ (bus SQLite, giống Mức 3 dưới).

### Mức 1 — dừng một ticket

```bash
cd companies/software-company
cat > /tmp/pause.json <<'JSON'
{"target": "TCK-1", "action": "pause", "reason": "ngắn gọn: vì sao dừng", "project_id": null}
JSON
uv run python -m company.orchestrator --db company.sqlite \
  publish supervisor-actions /tmp/pause.json --actor human:<tên bạn> --key TCK-1
# → published supervisor-actions key=TCK-1 event=9e0d1dc8...
```

**Hai chỗ dễ gõ sai lúc vội** (cả hai đều đã vấp khi diễn tập):

- **`--db` phải đứng TRƯỚC `publish`.** Đặt sau sẽ ra `error: unrecognized arguments: --db`.
- **`--key` là bắt buộc** với topic này. CLI tự suy key từ `ticket_id`/`release_id`/`project_id`/`change_id`
  trong payload, mà payload `supervisor-actions` chỉ có `target` — thiếu `--key` sẽ ra `cần --key`.

Sau khi publish: orchestrator đang chạy sẽ **hoãn** (`deferred`) mọi event của target đó
(`paused:<target>` trong `status`). Việc đang gọi model dở thì **chạy nốt lượt hiện tại** rồi mới dừng —
pause chặn *event tiếp theo*, không cắt ngang lời gọi đang bay.

### Mức 2 — dừng cả dự án

Cùng lệnh, đổi `--key` thành `project_id` và điền `"project_id": "<id>"` trong payload. Orchestrator kiểm
cả hai: target trùng ticket **hoặc** trùng dự án đều bị hoãn.

### Mức 3 — dừng tất cả

Không có lệnh CLI. Dừng tiến trình `orchestrator run`. An toàn vì mọi trạng thái nằm trong bus SQLite:
mở lại là replay dựng lại đúng chỗ, event chưa xử lý (`deferred`) được nhận lại.

### Sao lưu bus khi orchestrator còn chạy

Chạy từ thư mục công ty, trỏ đúng DB đang vận hành; `--db` đứng trước subcommand. Lệnh dùng SQLite backup API,
đọc được event còn trong WAL, kiểm `integrity_check`, rồi công bố file mới. Đích đã tồn tại sẽ bị từ chối để
không ghi đè bản trước. Chọn đường dẫn ngoài checkout và giữ bản sao ở nơi người trực kiểm soát quyền truy cập.

```bash
cd companies/software-company
uv run python -m company.orchestrator --db company.sqlite backup --out /duong-dan-an-toan/company-2026-10-05.sqlite
```

Nếu hub chạy trong container, dùng `--db var/company.sqlite` trên host (xem Mức 0). Bản sao này chỉ chứa bus
SQLite; thư mục `.artifacts` của blackboard là dữ liệu riêng và cần lịch sao lưu riêng. Ca tự động đã đo backup
khi kết nối ghi còn mở ở WAL; chưa chạy lệnh trên bus vận hành thật trong phiên này.

Watcher vận hành nên chạy ở checkout riêng bám `origin/main` thay vì worktree đang sửa tính năng. Chuẩn bị khi
watcher đã dừng, rồi khởi động lại với đúng cấu hình/DB của máy trực:

```bash
git fetch origin
git worktree add --detach ../X-Agents-runtime-main origin/main
cd ../X-Agents-runtime-main
uv sync --locked
```

Chỉ tạo checkout mới sau khi kiểm `git worktree list` để không đụng checkout đã có. Các lệnh trên là quy trình
đề xuất cho O1; chưa chuyển watcher đang chạy của máy trực trong phiên này.

> **Dừng orchestrator KHÔNG còn đồng nghĩa với dừng sản phẩm** (ADR-0039, từ 2026-09-08). Khi
> `COMPANY_DEPLOY` bật, lượt deploy dựng container **sống lâu** của khách bằng `docker compose up -d` và
> **cố ý không giết chúng** — đó là cả điểm của "deployed là container đang chạy". Giết tiến trình
> orchestrator chỉ dừng các agent; sản phẩm của khách vẫn nhận request, vẫn giữ cổng, vẫn ghi dữ liệu.

**Tắt riêng `keeper` mà không tắt hai công ty kia.** `keeper` là một tiến trình RIÊNG (`keeper.cli watch`) trên
một bus riêng (`keeper.sqlite`), nên nó dừng độc lập — dừng đúng tiến trình đó là xong, không cần chạm
`orchestrator run` của hai công ty:

```bash
# xem có tiến trình keeper nào đang chạy không (Windows / PowerShell)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object CommandLine -match 'keeper.cli watch' | Select-Object ProcessId, CommandLine
# Linux/macOS: pgrep -af 'keeper.cli watch'
```

Dừng tiến trình đó (Ctrl-C ở cửa sổ đang chạy nó là cách sạch nhất). An toàn như Mức 3: trạng thái nằm trong
`keeper.sqlite`, mở lại là replay đúng chỗ.

Muốn nó **chạy tiếp nhưng không mở PR nào nữa** thay vì tắt hẳn — hạ trần ngân sách rồi khởi động lại nó:

```bash
export KEEPER_MAX_PR_PER_WEEK=0        # cổng `budget` của `pr_blockers()` chặn mọi ticket
cd companies/keeper && uv run python -m keeper.cli watch --db keeper.sqlite --repo ../..
```

Nó vẫn triage và vẫn ghi `pr.blocked` kèm tên cổng chặn vào `audit-log`, nên hàng đợi không im lặng biến mất.

### Mức 4 — dừng SẢN PHẨM đang chạy (container)

Mỗi môi trường là một compose project riêng, tên do code đặt: `company-<project_id>-<env>` với
`env ∈ staging | production`.

```bash
docker compose -p company-<project_id>-staging down      # dừng staging của một dự án
docker compose -p company-<project_id>-production down   # dừng production của dự án đó
docker ps --filter "name=company-" --format "{{.Names}}\t{{.Ports}}"   # còn cái gì đang chạy, chiếm cổng nào
```

Không nhớ `project_id`? Đọc `evidence.deploy.project` của `release-events` cuối (console: cột phễu release,
bậc "Đã lên production"), hoặc `docker ps` như trên rồi `down` đúng tên.

**Cảnh báo cổng (rủi ro đã biết).** Cổng lấy từ compose file **của khách**, orchestrator chỉ đọc lại cổng đã
map để probe — nó không tự chọn và không sửa compose. Hệ quả trên máy trực:

- staging và production của **cùng** một dự án khai cùng cổng → project thứ hai `up -d` hỏng, lượt đó thành
  `deploy_failed` (không im lặng), nhưng chỉ vì hàng xóm. Khách phải khai cổng khác nhau cho hai môi trường.
- hai **dự án** khác nhau cũng có thể trùng cổng với nhau, và với cả console (`8200`) hay dev server đang mở.
- container đã `down` mà cổng vẫn bận → còn một project khác đang giữ: `docker ps --filter "name=company-"`.

`deploy_failed` **khác** `failed`: nó nói "chưa dựng được môi trường chạy", ticket của RC **không** bị trả về
làm lại; việc phải làm nằm ở máy trực. Đọc `evidence.deploy` (phần nào hỏng + `logs_tail`) của release-event
cuối, sửa, rồi quyết gate escalation của RC. Container của lượt hỏng đã được `compose down` tự động — không
phải dọn tay, cũng đừng `down` lần nữa để "cho chắc" khi lượt sau đã dựng lại được.

### Chạy tiếp sau khi đã xử lý

```bash
cat > /tmp/resume.json <<'JSON'
{"target": "TCK-1", "action": "resume", "reason": "đã xử lý: <việc đã làm>"}
JSON
uv run python -m company.orchestrator --db company.sqlite \
  publish supervisor-actions /tmp/resume.json --actor human:<tên bạn> --key TCK-1
```

`resume` gỡ pause **và** gọi lại hàng đợi bị hoãn — không cần khởi động lại tiến trình.

### Máy duyệt escalation — reviewer có chữ ký (ADR gốc 0024)

Mặc định TẮT. Người trực bật có chủ ý, ghi vào bàn giao ca:

```bash
cd companies/software-company
uv run python -m company.gate_reviewer init-key --id doc-lap        # một lần; in đường dẫn khoá + registry
export COMPANY_GATE_REVIEWER=1                                        # cả tiến trình orchestrator lẫn phiên reviewer
```

Rồi mở **một phiên Claude mới** (không phải phiên đang điều phối/sửa code) và chạy `/gate-review`. Phiên đó chỉ
`approve` escalation ticket/dự án, mỗi subject một lần; lần chặn thứ hai của cùng subject về người. Dừng: bỏ
`COMPANY_GATE_REVIEWER` — tắt rồi mở lại tiến trình thì quyết định cũ của reviewer không được áp, gate hiện lại
chờ người (hỏng thì đóng). Thu hồi khoá: đặt `not_after` về hiện tại trong registry.

**Phạm vi `rong`** (ADR gốc 0025 — phiên chính quyết mọi gate trừ spec): thêm `COMPANY_GATE_REVIEWER_SCOPE=rong` vào
env của CẢ orchestrator lẫn phiên ký, khoá `init-key --id phien-chinh`. Phiên chính chạy `/gate-review` và ký
`gate_reviewer decide <subject> --id phien-chinh [--decision reject] ...`. Dừng: bỏ biến rồi mở lại orchestrator —
quyết định ngoài S2 của reviewer không còn được áp, các gate đó hiện lại chờ người.

### Bước agent chậm ở đâu — span (ADR gốc 0009)

`export COMPANY_OTEL=1` trước khi mở orchestrator software-company thì span `runner.step` → `llm.complete` →
`tool.call` phát sang OpenTelemetry (người vận hành tự cài `opentelemetry-api` + exporter; chưa cài thì đo nhưng
không phát gì); không đặt biến thì không đo gì. Chuỗi một ticket trên bus nối bằng `correlation_id`: event nguồn của kế
hoạch (`approved-specs`/`change-requests`) → `tasks` → PR (kể cả PR người tiếp quản).

### Giới hạn đã biết (đừng trông chờ những thứ này)

- **Không thu hồi thông tin xác thực.** Gói đăng ký / khoá API vẫn dùng được sau khi pause. Nghi rò rỉ
  thì phải thu hồi ở phía nhà cung cấp — pause không thay được việc đó.
- **Không cắt lời gọi model đang chạy.** Lượt hiện tại chạy hết; trần thật là `budget_tokens` của ticket.
- **Không có mức "một phiên bản agent".** Muốn chặn riêng một agent hỏng: pause từng ticket của nó, hoặc dừng cả tiến trình.
- **Không có lệnh tắt.** `orchestrator` không có subcommand `stop`/`pause`; đường duy nhất là `publish`.

> Đã diễn tập ngày 2026-09-05: publish pause thành công trong 0,27 s; thử giả danh (`--actor supervisor`)
> **bị chặn** đúng như thiết kế (`--actor phải là người (human:<tên>)`). Bảy test `pause`/`resume` xanh.

---

## 2. Lịch trực luân phiên (ba người)

Một người trực **một tuần**, đổi ca sáng thứ Hai. Người trực là **địa chỉ duy nhất** cho mọi việc bất thường
trong tuần đó — không phải người duy nhất làm, mà là người **không được bỏ qua**.

| Việc | Người trực | Nhịp |
|---|---|---|
| Hàng đợi cổng người (`gate_cli list`) | Xử lý hoặc chuyển đúng người | ≥ 2 lần/ngày làm việc |
| `orchestrator status` — việc hoãn, kẹt, gate quá hạn | Đọc, gỡ hoặc leo thang | đầu và cuối ngày |
| `orchestrator diagnose` — khuôn lỗi lặp, ticket quay vòng | Đọc | 1 lần/ngày |
| Chi phí (`orchestrator metrics`) | So với hôm trước; tăng > 50% thì dừng và tìm hiểu | 1 lần/ngày |
| Sự cố / dừng khẩn | **Là người bấm**, theo §1 | khi có |

**Bàn giao cuối ca (viết ra, không nói miệng):** việc đang dở · ticket đang pause và vì sao ·
gate đang chờ ai · bất thường chi phí · thứ người sau **không được quên**.

**Người trực KHÔNG tự duyệt việc của chính mình.** Cổng nào có `four-eyes` thì vẫn cần người thứ hai —
đang trực không phải lý do miễn trừ. Nếu chỉ còn một người ở thời điểm đó: **để việc chờ**, đừng tự ký.

---

## 3. Cổng phát hành gộp lô (G6)

Duyệt phát hành **theo lô, không lẻ từng việc** — mỗi lần mở màn duyệt tốn phần lớn thời gian ở việc dựng lại
bối cảnh, nên gộp 3–5 việc thì rẻ hơn nhiều lần duyệt lẻ.

- **Nhịp:** 1 lô/ngày làm việc, giờ cố định (đề xuất cuối buổi sáng). Ba người thì mỗi ngày một người duyệt.
- **Không gộp** thứ chạm `auth`, `payment`, `crypto`, hoặc có migration dữ liệu: những thứ này duyệt **riêng**,
  đọc kỹ, vì gộp làm loãng chú ý đúng chỗ cần chú ý nhất.
- **Trần lô:** 5 việc. Đông hơn thì tách lô — một màn duyệt 12 việc là một màn duyệt không ai đọc hết.
- **Chờ quá 24 giờ thì không gộp nữa**: phát hành ngay lô đang có, đừng để việc chín rục chờ cho đủ lô.

Sau mỗi lô, ghi lại: số việc, ai duyệt, mất bao lâu. Nếu thời gian duyệt trung bình **dưới 90 giây/việc**,
đó là dấu hiệu duyệt cho có — xem lại trước khi nó thành thói quen.

---

## 4. Việc chưa làm được (ghi để không ai tưởng đã có)

| Thiếu | Hệ quả | Cách tạm |
|---|---|---|
| Kill switch một lệnh, ba mức | Lúc khẩn phải soạn JSON rồi publish | §1, và giữ sẵn hai file `pause.json` / `resume.json` trong máy |
| Thu hồi thông tin xác thực khi dừng | Pause không chặn được rò rỉ đang diễn ra | Thu hồi thủ công ở nhà cung cấp |
| Cảnh báo tự động (R8) | Người trực phải tự đọc `status` | Nhịp đọc ở §2 |
| Đo thời gian người duyệt cổng | Không biết cổng đã thành nghi thức chưa | Ghi tay sau mỗi lô (§3) |
