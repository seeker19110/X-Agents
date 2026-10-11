# ADR-0040: `COMPANY_DEPLOY=process` — deploy khách không dùng Docker (QLKH chạy trên WSL)

Trạng thái: Accepted, **bị thay một phần bởi ADR gốc 0031** (`docs/adr/0031-chi-chay-tren-linux.md`: runner mặc
định đổi từ cầu `wsl.exe --cd . bash` sang `bash`; mode `process` giữ nguyên) · Ngày: 2026-09-14 · Nối tiếp ADR-0039 (deploy thật bằng `docker compose`). Ranh giới tin
cậy và ba ràng buộc của ADR-0039 §"Bối cảnh" giữ nguyên — ADR này chỉ thêm một **mode** thứ hai, không đổi
mode `compose`.

## Bối cảnh

ADR-0039 giả định mọi khách đều đóng gói bằng Docker Compose. QLKH thì không: theo ADR-0013 của chính repo
khách (`D:\khach\qlkh\architecture\...`), staging chạy bằng tiến trình Python trần qua `nohup` trên máy WSL của
chủ dự án — không có `docker-compose.yml`, không dùng Docker/systemd (loại có chủ đích, xem lý do trong ADR đó).
Khách đã tự viết `infra/staging/wsl/{deploy,rollback,smoke}.sh` để deploy/kiểm tiến trình này.

Hệ quả đo được 2026-09-13: 5 `release-events` (REL-001/005/006/007/008) kẹt ở gate `escalation` vì
`deploy.py` chỉ biết `docker compose`; không có compose file trong repo khách nên `deploy()` trả `skipped`,
`ops` không có cách nào tự chứng minh `deployed` (đúng luật ADR-0039 — không tin lời khai), và không có route
tự động nào đưa staging QLKH tới trạng thái "đang chạy, đã kiểm".

Không thể tái dùng `infra/staging/wsl/deploy.sh` **y nguyên**: nó tự `git clone`/`checkout` một bản riêng vào
`$QLKH_STAGING_DIR` (mô hình "khách tự deploy production của họ"), trong khi company đã checkout đúng sha cần
deploy vào worktree tích hợp (`Integration.path`, ADR-0027). Gọi `deploy.sh` lại là dựng **hai** bản checkout
lệch nhau; script mới ở đây (`deploy_process`) chạy trực tiếp trên `Integration.path` — không clone lại.

## Quyết định

1. **`COMPANY_DEPLOY` thêm giá trị `process`** (bên cạnh `auto | compose | off`). `runtime.deploy` của spec
   (đã có từ ADR-0039, trước đây chỉ là đường dẫn compose file) nay là đường dẫn **tương đối** trong repo khách
   tới một script deploy theo giao thức cố định (mục 2) — không dò tên mặc định như compose (không đoán khách
   dùng script nào).

2. **Giao thức script deploy `process`, do CODE gọi, đường dẫn do spec khai**: `<runtime> <script> up` (khởi
   động/khởi động lại, idempotent), `<runtime> <script> down` (dừng, dùng ở nhánh hỏng — cùng vai trò
   `compose down` của ADR-0039 §3). Không có lệnh con thứ ba: khác compose (`ps`/`logs` tách rời), ở đây script
   tự chịu trách nhiệm "khởi động xong mới trả exit 0" (khớp đúng những gì `infra/staging/wsl/deploy.sh` của
   QLKH đã làm — chờ `/healthz` trước khi thoát) vì mỗi khách có cách kiểm tiến trình sống khác nhau, company
   không đoán được entrypoint để tự polling PID.

3. **`deployed` vẫn là kết luận từ HAI phần, không phải lời khai** (khác compose ba phần vì không có `ps` cho
   tiến trình trần): `<script> up` thoát 0 **và** smoke probe vào `rt.port` (đã khai trong spec, không đọc từ
   đâu ra như compose) trả đúng `expect_status`. Thiếu một trong hai → `deploy_failed`, evidence ghi lý do,
   chạy `<script> down` (không bỏ lại tiến trình nửa sống). `evidence.deploy` giữ đúng hình dạng
   `DeployRecord.record()` của ADR-0039 (`port`, `started_at`, `smoke`, `verified_by=orchestrator`) —
   console/gate_brief chỉ phải biết một hình cho cả hai mode; trường `services`/`container_ids` rỗng vì
   process mode không có khái niệm container.

4. **Cầu nối WSL từ orchestrator chạy trên Windows native.** Hub chạy trên Windows (không phải trong WSL);
   khách của QLKH chỉ tồn tại trong userland Linux của WSL (Node/uv/venv theo đúng ADR-0014 của khách). Runner
   mặc định của mode `process` không phải một binary đơn mà một **argv prefix** đọc từ
   `COMPANY_DEPLOY_RUNTIME` dạng chuỗi shlex, mặc định `"wsl.exe --cd . bash"` — `.` được thay bằng
   `str(repo_root)` (đường dẫn Windows, `wsl.exe --cd` tự dịch sang `/mnt/<ổ>/...`, đã đo thật). Trên máy
   Linux/macOS (CI, hoặc nếu hub tự chạy trong WSL), người vận hành đặt `COMPANY_DEPLOY_RUNTIME=bash` để bỏ
   qua lớp cầu nối. `which` kiểm phần tử ĐẦU của prefix (`wsl.exe` hoặc `bash`) — đúng khuôn fail-closed
   ADR-0039 §4/ADR-0035: `COMPANY_DEPLOY=process` khai đích danh mà thiếu binary đầu là lỗi, không tụt hạng.

5. **argv do CODE ghép, không nội suy chuỗi từ payload model** (khuôn ADR-0039 §6): `[*prefix, script, "up"|"down"]`,
   `script` đã xác nhận là file có thật trong `repo_root` (giống `compose_file`, đổi tên `deploy_script`) trước
   khi dùng. Không thêm tham số nào khác từ spec vào argv.

6. **Không đổi mode `compose`.** `process` là ngoại lệ thêm cho khách không dùng Docker, không phải thay thế —
   khách nào có compose file vẫn đi đường cũ. Một dự án chỉ khai MỘT trong hai (đường dẫn script hay compose
   nằm trong cùng trường `runtime.deploy`; đuôi file quyết định: script `.sh`/không có compose file hợp lệ →
   company thử theo mode đang bật, không tự suy đoán chéo).

## Từ chối

- **Chạy hẳn hub trong WSL** thay vì bridge từ Windows: đúng hơn về lâu dài (bớt một lớp dịch đường dẫn) nhưng
  đổi toàn bộ mô hình vận hành hub hiện tại (dịch vụ Windows, `.claude/launch.json`, mọi worktree khác của
  người dùng) — ngoài phạm vi một bản vá deploy. Ghi lại làm nợ kiến trúc nếu người vận hành sau này chuyển hẳn
  sang chạy hub trong WSL/container Linux (xem ADR-0013/0014 container hoá hub).
- **Gọi thẳng `infra/staging/wsl/deploy.sh` của khách**: bị loại ở mục "Bối cảnh" — nó tự clone/checkout, xung
  đột với mô hình worktree tích hợp của company.
- **Thêm lệnh con thứ ba `status`/`ps` như compose**: process trần không có API liệt kê chuẩn; polling PID là
  việc của script khách (nó đã tự làm qua pidfile), company chỉ cần biết "lên chưa" qua chính smoke probe HTTP
  đã có sẵn.
