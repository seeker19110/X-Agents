# CR-<change_id>: <tiêu đề>
Dùng khi khách hoặc nội bộ muốn đổi phạm vi đã chốt trong SOW/PRD; account-manager điền rồi phát event lên topic `change-requests`.

- change_id: CR-xx · project_id: P-xx
- requested_by: <người/vai trò yêu cầu> · Ngày:
- decision: pending|accepted|rejected|deferred

## Mô tả (description)
<thay đổi cụ thể là gì>

## Lý do
<vì sao cần thay đổi, chuyện gì xảy ra nếu không làm>

## Yêu cầu bị ảnh hưởng (affects_requirements)
- REQ-xx, REQ-yy

## Phương án thay thế
| # | Phương án | Ưu | Nhược | Vì sao không chọn |
|---|---|---|---|---|

## Tác động (impact)
| Khía cạnh | Đánh giá |
|---|---|
| Phạm vi | |
| Lịch (schedule) | +<n> ngày |
| Ước lượng (estimate_days / estimate_tokens) | |
| Chi phí (cost) | |
| Rủi ro (kỹ thuật, bảo mật, dữ liệu) | |

## Quyết định
- Người quyết định: <phía khách> / <phía cung cấp>
- Ngày quyết định: · Kết quả: accepted|rejected|deferred
- Lý do:
- Việc tiếp theo: <cập nhật PRD/SOW, tạo ticket TCK-xx>

## Checklist
- [ ] Đã ước lượng tác động lịch và chi phí
- [ ] Đã kiểm tra ảnh hưởng tới threat-model / data-contract
- [ ] Người có thẩm quyền phía khách đã duyệt
- [ ] Đã cập nhật PRD và bảng truy vết
