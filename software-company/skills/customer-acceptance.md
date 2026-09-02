---
name: customer-acceptance
version: 1
standards: [ISO/IEC/IEEE 29119-1 (acceptance testing), PMBOK 7 (scope/change control), ISO 21502, IEEE 730 (biên bản)]
---
# Skill: customer-acceptance

## Tiêu chuẩn tham chiếu
- ISO/IEC/IEEE 29119-1 (acceptance testing)
- PMBOK 7 (scope/change control)
- ISO 21502
- IEEE 730 (biên bản)

## Quy tắc
- Tiêu chí nghiệm thu = tiêu chí Gherkin trong PRD đã duyệt; không thêm tiêu chí mới lúc nghiệm thu.
- UAT chạy trên staging bằng dữ liệu khách chấp thuận; kịch bản UAT có trước Gate 2.
- Mọi yêu cầu ngoài spec là change request: có mô tả, ảnh hưởng (ngày, token, chi phí), quyết định của khách, rồi mới thành ticket.
- Biên bản nghiệm thu ghi rõ accepted / conditional (kèm danh sách còn lại có hạn) / rejected (kèm lý do truy vết về requirement_id).
- Người ký nghiệm thu là người của khách; công ty không tự ký.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Kịch bản UAT map 1-1 với Must requirement
- [ ] Change request có impact và quyết định trước khi vào tasks
- [ ] Biên bản có người ký của khách
- [ ] Finding nghiệm thu truy vết được về requirement_id

## Ví dụ tốt
CR-12: khách muốn thêm xuất Excel; impact 1.5 ngày/40k token, khách đồng ý, tạo REQ-031 rồi ticket.

## Ví dụ xấu
Nhận yêu cầu qua chat rồi làm luôn, không ghi change request; nghiệm thu bằng 'khách bảo ok'.
