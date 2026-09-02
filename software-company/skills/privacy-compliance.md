---
name: privacy-compliance
version: 2
standards: [GDPR, Nghị định 13/2023/NĐ-CP, ISO/IEC 27701, DPIA, Privacy by Design]
---
# Skill: privacy-compliance

## Tiêu chuẩn tham chiếu
- GDPR: Art. 5 (nguyên tắc), Art. 6 (cơ sở pháp lý), Art. 25 (privacy by design), Art. 32 (an toàn), Art. 33–34 (thông báo vi phạm), Art. 35 (DPIA)
- Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân (Việt Nam): hồ sơ đánh giá tác động, chuyển dữ liệu ra nước ngoài, quyền của chủ thể
- ISO/IEC 27701 (hệ thống quản lý thông tin riêng tư)
- Privacy by Design: mặc định là ít dữ liệu nhất, không phải nhiều nhất

## Quy trình (làm đúng thứ tự)
Kiểm kê dữ liệu định thu thập → xác định cơ sở pháp lý và mục đích cho từng trường → tối thiểu hóa (bỏ trường không có mục đích rõ) → phân loại và ghi vào schema/data contract → đặt retention và job xóa → thiết kế quyền chủ thể trước khi thu thập → DPIA nếu thuộc diện bắt buộc → kiểm soát bên xử lý và chuyển dữ liệu xuyên biên giới → giám sát và diễn tập xử lý vi phạm.
Câu hỏi đầu tiên luôn là "có cần trường này không", không phải "lưu ở đâu".

## Quy tắc — dữ liệu và mục đích
- Phân loại: công khai / nội bộ / cá nhân / cá nhân nhạy cảm (sức khỏe, sinh trắc, chính trị, tôn giáo, tình trạng pháp lý, trẻ em). Phân loại ghi trong schema và data contract, không chỉ trong tài liệu.
- Mỗi trường dữ liệu cá nhân có: cơ sở pháp lý, mục đích cụ thể, thời hạn lưu, và ai được truy cập. Không đủ bốn thông tin này thì không được thu thập.
- Không thu thập "để sau này có thể cần"; mở rộng mục đích sử dụng sau này cần cơ sở mới, không mặc nhiên kế thừa.
- Đồng ý phải là hành động chủ động, tách bạch từng mục đích, rút lại dễ như khi cho, và được ghi nhận (thời điểm, phiên bản văn bản). Ô đánh dấu sẵn không phải là đồng ý.
- Dữ liệu nhạy cảm và dữ liệu trẻ em có yêu cầu chặt hơn: hạn chế truy cập, mã hóa, và thường cần DPIA.

## Quy tắc — kỹ thuật
- Giảm thiểu ở biên: mask khi log, cắt bớt khi truyền, giả danh hóa khi đưa vào kho phân tích (khóa nối là hash có muối, muối quản lý như secret).
- Mã hóa khi lưu và khi truyền; khóa quản lý riêng, có xoay vòng; quyền truy cập theo vai trò và ghi nhật ký truy cập dữ liệu nhạy cảm.
- Retention có job xóa thật, chạy định kỳ, có kiểm chứng; xóa phải lan tới backup theo chính sách khai báo, tới log, và tới hệ thống hạ nguồn.
- Quyền chủ thể (truy cập, sửa, xóa, hạn chế, phản đối, mang dữ liệu đi) phải có quy trình hoặc API trước khi thu thập, đáp ứng trong thời hạn luật định.
- Môi trường thử nghiệm không dùng dữ liệu thật; nếu buộc phải dùng thì che dữ liệu và có văn bản cho phép.
- Không gửi dữ liệu cá nhân cho nhà cung cấp AI/bên thứ ba nếu chưa có hợp đồng xử lý dữ liệu và đánh giá phù hợp (xem `ai-feature-engineering`).

## Quy tắc — hồ sơ và sự cố
- DPIA bắt buộc khi: xử lý dữ liệu nhạy cảm quy mô lớn, theo dõi hành vi có hệ thống, chấm điểm hoặc quyết định tự động ảnh hưởng tới người, dữ liệu trẻ em, hoặc kết hợp nhiều nguồn dữ liệu.
- Chuyển dữ liệu ra nước ngoài: lập hồ sơ đánh giá tác động theo NĐ13 và cơ chế hợp pháp theo GDPR trước khi bật tính năng, không làm sau.
- Bên xử lý (nhà cung cấp) phải có hợp đồng, danh sách bên xử lý phụ, và cam kết an toàn; danh sách này được rà soát định kỳ.
- Nghi ngờ lộ dữ liệu cá nhân là sự cố có đồng hồ đếm ngược: xử lý theo `incident-management`, đánh giá nghĩa vụ thông báo cơ quan và chủ thể trong thời hạn luật định, và giữ nguyên bằng chứng.
- Hồ sơ hoạt động xử lý dữ liệu được cập nhật khi thêm trường, thêm mục đích, hoặc thêm nhà cung cấp — không phải mỗi năm một lần.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi trường PII có phân loại trong schema và data contract
- [ ] Mỗi trường có cơ sở pháp lý, mục đích, retention, và người được truy cập
- [ ] Job xóa theo retention có thật, chạy được, và lan tới log/backup/hạ nguồn
- [ ] Quyền truy cập/xóa/rút đồng ý hoạt động và đúng thời hạn
- [ ] DPIA có khi thuộc diện bắt buộc; hồ sơ chuyển dữ liệu xuyên biên giới hoàn tất trước khi bật
- [ ] Log và môi trường thử nghiệm không chứa PII thô
- [ ] Nhà cung cấp xử lý dữ liệu có hợp đồng và được rà soát
- [ ] Có quy trình và diễn tập xử lý vi phạm dữ liệu

## Ví dụ tốt
Trường `phone`: loại cá nhân, cơ sở là thực hiện hợp đồng, mục đích gửi OTP, lưu 90 ngày sau khi đóng tài khoản, chỉ đội hỗ trợ đọc được; job xóa chạy hằng đêm và có báo cáo số bản ghi đã xóa; log hiển thị `+84***123`; kho phân tích chỉ nhận `phone_hash`. DPIA hoàn thành trước khi bật tính năng chấm điểm rủi ro khách hàng.

## Ví dụ xấu
Lưu số CCCD trong bảng `users` "để sau này cần"; đồng ý gộp một ô cho cả marketing lẫn dịch vụ; log ghi nguyên payload đăng ký gồm họ tên và số điện thoại; dữ liệu production copy sang môi trường dev cho tiện; yêu cầu xóa tài khoản chỉ đánh dấu `is_deleted = true` và dữ liệu vẫn còn nguyên ở kho phân tích.
