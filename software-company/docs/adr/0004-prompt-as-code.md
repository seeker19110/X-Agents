# ADR-0004: Prompt là code

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
System prompt và skill quyết định hành vi agent nhiều hơn code Python, nhưng chưa có quy ước
version, review, hay rollback. Một thay đổi prompt có thể làm reviewer bỏ lọt lỗi mà không ai
biết version nào gây ra.

## Quyết định
1. Mỗi file `agents/**/*.md` có `version: <int>` trong front matter; sửa nội dung → tăng version.
2. Thay đổi `agents/`, `skills/`, `gates/`, `templates/` đi qua PR như code: reviewer đọc diff,
   CI chạy `tests/` (registry load, namespace nhất quán) và case vàng của agent bị đổi.
3. Rollback = revert commit. Không sửa prompt ngoài repo.
4. Supervisor ghi vào `knowledge` khi một version gây lỗi lặp ≥ 2 lần, kèm version.
5. Skill dùng chung nhiều agent: đổi skill = đổi mọi agent dùng nó → PR phải liệt kê agent ảnh hưởng.

## Hệ quả
- `AgentSpec.version` mặc định 1 cho file cũ; test bắt buộc ≥ 1.
- Thư mục `tests/golden/<agent>/` (bổ sung dần) chứa case vàng; chưa có thì PR ghi rõ "chưa có eval".
- Skill `prompt-engineering` mô tả chi tiết; supervisor và delivery-lead bắt buộc dùng.
