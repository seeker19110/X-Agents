# ADR-0054: lệnh `lock` cho builder — sinh lại lockfile Python bằng `uv`, có mạng PyPI qua egress

Trạng thái: Accepted · Ngày: 2026-10-12 · Nối tiếp ADR-0013 (stack theo repo khách), ADR-0035 (sandbox, mạng tắt),
ADR-0044 (môi trường của khách), ADR gốc 0010 (egress Squid, allowlist domain). Chủ dự án chọn hướng này 2026-10-12
thay cho "chấp nhận replan thêm ticket có mạng" (X-Agents không cấp được lượt có mạng cho ticket).

## Bối cảnh

Hub thật 2026-10-12, dự án `QLKH-DD-CSV`, ticket `DDCSV-02` (entrypoint): builder thêm `starlette`, `uvicorn`,
`pg8000` vào `pyproject.toml` nhưng **không sinh lại được `requirements.lock`** — repo khách cài frozen
`--require-hashes`, sandbox `container` tắt mạng (ADR-0035), tool `run` chỉ có `lint`/`test`/`git_*`. Security chặn
ba lần cùng lý do (lock-check, pip-audit, SBOM, cổng license không quét được gói mới), ticket `blocked`, CR replan
`REPLAN-DDCSV-02-1` đề xuất "ticket platform có mạng" — thứ orchestrator không có.

Hạ tầng cần thiết đã có từ trước: `registry_domains` (S2) cấp `pypi.org`/`files.pythonhosted.org` cho argv `uv` ở
chế độ container, `ContainerSandbox` mở sidecar Squid với ACL domain (ADR gốc 0010), `supply_chain.installed_licenses`
đã chạy `uv` qua đúng đường đó. Thiếu đúng một thứ: **một lệnh trong allowlist** để builder gọi.

## Quyết định

1. **`Stack.lock`** — công thức sinh lại lockfile, do **code** suy từ repo khách, model chỉ chọn tên `lock`:
   - `uv.lock` ở gốc ⇒ `uv lock`;
   - `requirements.lock` hoặc `requirements.txt` có dòng chú thích đầu file chứa `uv pip compile …` (header chuẩn của
     uv, hay câu "Sinh bằng: …" của khách) ⇒ `uv pip compile` + đối số từ header, **chỉ** nhận: cờ trong allowlist
     (`--generate-hashes`, `--python-version X`, `-o/--output-file`, `--all-extras`, `--extra`, `--group`, `-c`,
     `--universal`, `--strip-extras`, `--no-deps`, `--upgrade`, `--no-header`, `--no-annotate`); file vào phải tồn tại;
     file ra/constraint phải nằm trong gốc; token chỉ gồm `[A-Za-z0-9_./=@+-]`. Lệch một điều ⇒ **không có công
     thức** (fail-closed), không đoán.
   - Không có hai thứ trên ⇒ `lock` không xuất hiện trong allowlist. Stack khác Python chưa có `lock` (chưa đo ca).
2. **`run lock`** đi qua đúng `Sandbox` của worktree như `lint`/`test`, `allowed_domains = registry_domains(argv)`:
   chế độ container ⇒ chỉ PyPI qua Squid; chế độ subprocess ⇒ mạng máy chủ như mọi lệnh khác (không đổi). Không nhận
   `paths` — công thức là của repo, model không thêm đối số. Env lọc `clean_env()` như cũ.
3. **Image sandbox phải có `uv`** (ADR-0035 §Hệ quả: image mang công cụ). Thiếu ⇒ exit 127 ghi trong output tool,
   builder thấy ngay, không im lặng.

## Từ chối

- **Ticket "có mạng" riêng** (đề xuất của replan): không có cơ chế cấp mạng theo ticket; thêm là một bề mặt tin cậy mới
  theo lời khai của plan. Lệnh có allowlist + domain allowlist hẹp hơn nhiều.
- **Người sinh lockfile tay rồi `takeover`**: đúng với một ticket, sai với mọi ticket sau có thêm phụ thuộc — đúng chỗ
  "sửa X-Agents, không làm thay".
- **Cho `uv` mọi domain**: trái ADR gốc 0010 (ACL domain chính xác).

## Hệ quả

- Người vận hành dựng lại image sandbox có `uv` (`pip install uv`), ghi ở Dockerfile ngoài repo
  (`~/.config/x-agents/images/qlkh/`).
- Header chứa công thức là **dữ liệu của repo khách**: builder sửa được nó. Allowlist cờ + ràng buộc đường dẫn + ACL
  domain là ba lớp giữ; sửa header để thêm cờ lạ ⇒ không còn công thức, lệnh biến mất khỏi allowlist.
- Chưa làm, cố ý: `npm install --package-lock-only`, `cargo generate-lockfile`, `go mod tidy` — cùng khuôn `Stack.lock`,
  thêm khi có ca đo.

## Đo hai chiều

- Tắt `lock_command` (trả `None`) ⇒ `test_uv_lock_thi_lenh_la_uv_lock`, `test_requirements_lock_doc_cong_thuc_tu_header`
  đỏ; `lock` biến mất khỏi allowlist.
- Bỏ allowlist cờ / ràng buộc đường dẫn ⇒ `test_header_khong_hop_le_thi_khong_co_lock` đỏ (5 ca).
- Bỏ `registry_domains` khỏi `run` ⇒ `test_run_lock_di_qua_sandbox_voi_mang_pypi_o_che_do_container` đỏ.
