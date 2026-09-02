---
name: customer-acceptance
version: 2
standards: [ISO/IEC/IEEE 29119-1 (acceptance testing), PMBOK 7 (scope/change control), ISO 21502, IEEE 730 (biên bản)]
---
# Skill: customer-acceptance

## Tiêu chuẩn tham chiếu
- ISO/IEC/IEEE 29119-1: nghiệm thu là kiểm thử theo tiêu chí đã thống nhất trước
- PMBOK 7: kiểm soát phạm vi và thay đổi có kỷ luật
- ISO 21502: quản lý bàn giao và lợi ích
- IEEE 730: hồ sơ, biên bản, chữ ký

## Quy trình (làm đúng thứ tự)
Chốt tiêu chí nghiệm thu ngay trong PRD (Gate 2) → viết kịch bản UAT ánh xạ 1-1 với Must → chuẩn bị staging và dữ liệu khách chấp thuận → chạy UAT cùng người của khách → ghi finding truy vết về requirement_id → phân loại accepted / conditional / rejected → lấy chữ ký → mở change request cho mọi thứ ngoài spec → ghi bài học vào `knowledge`.
Kịch bản UAT phải tồn tại TRƯỚC khi code, không viết lúc sắp nghiệm thu.

## Quy tắc — tiêu chí và phạm vi
- Tiêu chí nghiệm thu = tiêu chí Gherkin trong PRD đã duyệt. Không thêm tiêu chí mới tại buổi nghiệm thu; tiêu chí mới là change request.
- Mỗi yêu cầu Must có ít nhất một kịch bản UAT; ánh xạ 1-1 kiểm được bằng bảng truy vết.
- Cái không nằm trong phạm vi được ghi rõ trong biên bản như phần trong phạm vi, để tránh tranh cãi sau.
- Không nghiệm thu bằng lời: "khách bảo ok" không phải bằng chứng. Bằng chứng là biên bản có chữ ký, kèm kết quả từng kịch bản.

## Quy tắc — thực thi UAT
- UAT chạy trên staging giống production về cấu hình, với dữ liệu khách đã chấp thuận (dữ liệu thật phải được che hoặc có văn bản cho phép, xem `privacy-compliance`).
- Người thực hiện là người dùng nghiệp vụ của khách; công ty hỗ trợ và ghi chép, không tự bấm thay rồi kết luận.
- Mỗi kịch bản ghi: bước, kết quả mong đợi, kết quả thực tế, đạt/không, bằng chứng (ảnh, log, id giao dịch).
- Lỗi phát hiện trong UAT phân mức theo tác động nghiệp vụ (chặn nghiệp vụ / có đường vòng / mỹ quan), không theo cảm tính; mức chặn thì không được kết luận accepted.
- Hiệu năng, bảo mật, khả năng tiếp cận đã có tiêu chí NFR thì cũng phải nghiệm thu bằng số, không bỏ qua vì "khách không hỏi".

## Quy tắc — thay đổi và biên bản
- Mọi yêu cầu ngoài spec là change request: mô tả, lý do, ảnh hưởng (ngày, token, chi phí, rủi ro), phương án thay thế, quyết định của khách — rồi mới thành requirement và ticket.
- Change request bị từ chối cũng lưu, kèm lý do; đây là hồ sơ bảo vệ cả hai bên.
- Biên bản ghi rõ một trong ba: `accepted`; `conditional` kèm danh sách việc còn lại, người chịu trách nhiệm và hạn; `rejected` kèm lý do truy vết về requirement_id.
- Người ký nghiệm thu là người có thẩm quyền của khách; công ty không tự ký thay, agent không ký thay người.
- Sau nghiệm thu: chuyển trạng thái bảo hành/hỗ trợ rõ ràng (thời hạn, kênh, SLA), và ghi các phát hiện lặp lại vào `knowledge`.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Kịch bản UAT có trước Gate 2 và ánh xạ 1-1 với mọi Must
- [ ] UAT chạy trên staging với dữ liệu được khách chấp thuận
- [ ] Mỗi kịch bản có kết quả thực tế và bằng chứng
- [ ] Finding truy vết được về requirement_id và có mức tác động nghiệp vụ
- [ ] NFR có tiêu chí số cũng được nghiệm thu bằng số
- [ ] Mọi yêu cầu ngoài spec đi qua change request có impact và quyết định trước khi vào tasks
- [ ] Biên bản có kết luận rõ ràng và chữ ký người của khách
- [ ] Điều kiện còn lại (nếu conditional) có owner và hạn

## Ví dụ tốt
UAT-07 ↔ REQ-014: khách tự đặt đơn trên staging, p95 hiển thị 240ms (NFR 300ms), ảnh chụp và id đơn đính kèm → đạt. CR-12: khách muốn thêm xuất Excel; impact 1.5 ngày / 40k token / lùi phát hành 2 ngày; khách đồng ý → REQ-031 → TCK-58. Biên bản: conditional, còn 1 mục mỹ quan, owner frontend, hạn 12/09.

## Ví dụ xấu
Nhận yêu cầu qua chat rồi làm luôn, không ghi change request; nghiệm thu bằng câu "khách bảo ok"; buổi nghiệm thu phát sinh 6 tiêu chí mới và đội nhận hết vì ngại từ chối.
