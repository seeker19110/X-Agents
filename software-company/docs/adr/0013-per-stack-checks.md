# ADR-0013: Lint/test theo stack của repo khách

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0010

## Bối cảnh
ADR-0010 đặt nguyên tắc: bằng chứng trong PR do code điền, không phải lời model tự khai. Nhưng `run_checks`
chạy cứng `ruff` và `pytest`. Với repo Node, Go, Rust hay Android, hai lệnh đó hoặc không tồn tại hoặc không
chạm vào code vừa sửa, nên `local_checks.lint/tests` của frontend, mobile, platform và data là bằng chứng
hình thức. Một PR React có thể mang `verified_by: workspace` mà chưa hề được kiểm.

## Quyết định
`stacks.py` nhận diện stack theo file dấu hiệu ở gốc worktree (pyproject/setup.cfg/requirements, package.json,
go.mod, Cargo.toml, build.gradle, pom.xml) và khai argv lint/test tương ứng. `TicketWorkspace.lint/test`
và bảng tool `run` của agent lấy lệnh từ đó; `local_checks` thêm trường `stack`.

Ranh giới tin cậy không đổi: argv vẫn do code ghép, model chỉ chọn tên lệnh trong allowlist.

Không nhận ra stack, hoặc `package.json` không có script tương ứng, thì `lint`/`tests` là `false` với lý do
trong output, và tool `run` chỉ còn lệnh git. Thà nói không kiểm được còn hơn báo pass bằng một lệnh không
liên quan đến thay đổi.

## Hệ quả
- Reviewer đọc `local_checks.stack` để biết bằng chứng đến từ đâu.
- Repo đa ngôn ngữ lấy stack ở gốc; muốn chính xác hơn thì mở rộng `MARKERS` theo thư mục con.
- Thêm stack mới là thêm một dòng vào `MARKERS`, không đụng runner hay tool.
