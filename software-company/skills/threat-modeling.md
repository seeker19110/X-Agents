---
name: threat-modeling
version: 2
standards: [STRIDE, CVSS 4.0, OWASP ASVS, MITRE ATT&CK, OWASP SAMM, LINDDUN]
---
# Skill: threat-modeling

## Tiêu chuẩn tham chiếu
- STRIDE trên sơ đồ luồng dữ liệu (DFD) có ranh giới tin cậy
- CVSS 4.0 để chấm mức; kết hợp khả năng khai thác thực tế để ưu tiên
- OWASP ASVS (L2 mặc định; L3 cho tài chính, y tế) làm danh mục kiểm soát
- MITRE ATT&CK để mô tả kịch bản tấn công thực tế
- LINDDUN cho mối đe dọa về quyền riêng tư (bổ sung cho STRIDE)
- OWASP SAMM để đo độ chín của chương trình bảo mật

## Quy trình (làm đúng thứ tự)
Xác định tài sản cần bảo vệ và kẻ tấn công giả định → vẽ DFD với ranh giới tin cậy → duyệt STRIDE cho từng phần tử và từng luồng cắt qua ranh giới → thêm LINDDUN cho dữ liệu cá nhân → chấm mức và ưu tiên → chọn biện pháp giảm nhẹ ánh xạ về ASVS → gắn owner và ticket → kiểm chứng bằng test → rà lại khi kiến trúc đổi.
Bốn câu hỏi khung: đang xây cái gì, cái gì có thể sai, sẽ làm gì với nó, và đã làm đủ tốt chưa.

## Quy tắc — mô hình
- Threat model có trước ticket đầu tiên; cập nhật khi đổi kiến trúc, thêm tích hợp bên ngoài, thêm loại dữ liệu cá nhân, hoặc thay đổi mô hình phân quyền.
- DFD tối thiểu có: tác nhân, tiến trình, kho dữ liệu, thực thể ngoài, và ranh giới tin cậy. Không có ranh giới tin cậy thì chưa phải threat model.
- Kẻ tấn công giả định phải cụ thể: người ngoài không xác thực, người dùng hợp lệ leo thang quyền, khách hàng khác trong hệ thống đa khách, nhân viên nội bộ, bên thứ ba bị xâm nhập, và chuỗi cung ứng.
- Mọi luồng cắt qua ranh giới tin cậy đều phải được xét đủ sáu chữ STRIDE, không bỏ chữ nào vì "chỗ này chắc không sao".
- Với dữ liệu cá nhân, xét thêm mối đe dọa riêng tư: liên kết được danh tính, suy luận ra thuộc tính nhạy cảm, lưu quá lâu, dùng sai mục đích (xem `privacy-compliance`).

## Quy tắc — mối đe dọa và giảm nhẹ
- Mỗi threat có: id, chữ cái STRIDE, tài sản bị ảnh hưởng, kịch bản cụ thể, mức CVSS, biện pháp giảm nhẹ, owner, và trạng thái (open / mitigated / accepted-with-ADR).
- Kịch bản viết theo cách kẻ tấn công thực hiện, không viết chung chung: "client sửa `price` trong request rồi gửi lại" chứ không phải "dữ liệu có thể bị sửa".
- Biện pháp giảm nhẹ ánh xạ về một kiểm soát ASVS cụ thể và về một ticket thật; giảm nhẹ không có ticket coi như chưa có.
- Threat mức High/Critical không có giảm nhẹ thì không qua Gate 2. Rủi ro được chấp nhận phải có ADR và người ký, kèm điều kiện xem lại.
- Mỗi giảm nhẹ quan trọng phải có cách kiểm chứng: test tự động, quy tắc quét, hoặc mục kiểm trong review — nếu không thì nó sẽ lặng lẽ biến mất sau vài lần refactor.
- Ticket hiện thực mang `risk_tags` trỏ về threat id, để reviewer biết chỗ nào cần soi kỹ (xem `code-review`).

## Quy tắc — duy trì
- Threat model có version, lưu trong namespace `threat-model`, và được rà theo lịch (tối thiểu mỗi bản phát hành lớn).
- Sự cố bảo mật thật phải được đối chiếu ngược: mô hình đã dự đoán chưa, nếu chưa thì thiếu ở đâu — cập nhật mô hình và ghi bài học (xem `incident-management`).
- Không sao chép threat model từ dự án khác; tài sản và ranh giới khác nhau thì mối đe dọa khác nhau.
- Giả định bảo mật (ví dụ "mạng nội bộ tin cậy") phải viết ra; giả định ẩn là nơi sự cố hay xảy ra nhất.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] DFD có ranh giới tin cậy và được cập nhật theo kiến trúc hiện tại
- [ ] Kẻ tấn công giả định được nêu cụ thể, gồm cả nội bộ và đa khách
- [ ] Mọi luồng cắt ranh giới được duyệt đủ STRIDE; dữ liệu cá nhân được duyệt thêm mối đe dọa riêng tư
- [ ] Mỗi threat có id, kịch bản cụ thể, mức, owner và trạng thái
- [ ] High/Critical đều có giảm nhẹ, hoặc ADR chấp nhận rủi ro có người ký
- [ ] Mỗi giảm nhẹ có cách kiểm chứng tự động hoặc mục kiểm trong review
- [ ] Ticket có `risk_tags` trỏ về threat id
- [ ] Threat model có version trong `threat-model` và được rà theo lịch
- [ ] Giả định bảo mật được ghi tường minh

## Ví dụ tốt
T-04 (Tampering, CVSS 8.1): client sửa trường `price` trong yêu cầu tạo đơn rồi gửi lại, mua hàng với giá tự đặt. Giảm nhẹ: máy chủ tính lại giá từ catalog và bỏ qua giá do client gửi (ASVS 5.1.4); kiểm chứng bằng test `test_order_ignores_client_price` trong CI; owner backend; TCK-12; trạng thái mitigated. Giả định ghi rõ: mạng nội bộ KHÔNG được coi là tin cậy.

## Ví dụ xấu
"Hệ thống dùng HTTPS nên an toàn." Không DFD, không ranh giới tin cậy, không kẻ tấn công nội bộ; danh sách mối đe dọa chép từ dự án trước; ba threat High ở trạng thái "sẽ xử lý sau" suốt bốn tháng và không ai đứng tên.
