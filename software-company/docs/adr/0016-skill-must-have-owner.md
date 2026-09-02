# ADR-0016: Mỗi skill phải có agent chủ quản

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0008

## Bối cảnh
ADR-0008 chia skill thành hai mức: `skills` (đầy đủ) và `skills_core` (chỉ H1 + quy trình + checklist, do
`load_skill(core_only=True)` cắt). Mười skill chỉ xuất hiện ở `skills_core` khắp nơi: observability,
license-compliance, incident-management, performance-testing, privacy-compliance, ui-ux-design,
event-driven-architecture, i18n, ai-feature-engineering, finops.

Nghĩa là phần Quy tắc, Ví dụ và Tiêu chuẩn tham chiếu của mười skill ấy chưa bao giờ tới tay một model nào,
dù `docs/standards.md` bắt buộc chúng. Skill viết ra nhưng không ai đọc là tài liệu chết.

## Quyết định
Bất biến: **mỗi file trong `skills/` phải có ít nhất một agent nạp nó ở mức đầy đủ** (trong `skills`, không
phải `skills_core`). Chủ quản là agent chịu trách nhiệm cuối cùng về lĩnh vực đó — ví dụ `ui-ux-design` về
`researcher`, agent sở hữu namespace `design`.

`load_agents()` từ chối nạp nếu còn skill mồ côi, nên vi phạm là lỗi khởi động chứ không phải lỗi phát hiện
khi đọc output model.

## Hệ quả
- Thêm skill mới thì phải chỉ định chủ quản ngay trong cùng thay đổi, nếu không hệ thống không khởi động.
- Bỏ một skill khỏi `skills` của agent chủ quản thì phải chuyển chủ quản cho agent khác.
- `skills_core` giữ nguyên ý nghĩa: agent phải đạt checklist nhưng không sở hữu lĩnh vực.
