---
name: incident-management
version: 2
standards: [ITIL 4, Google SRE incident response, Blameless postmortem, ICS (chỉ huy sự cố), Error budget policy]
---
# Skill: incident-management

## Tiêu chuẩn tham chiếu
- ITIL 4: phân biệt incident (khôi phục dịch vụ) và problem (loại bỏ nguyên nhân)
- Google SRE: vai trò chỉ huy sự cố, người liên lạc, người ghi chép; error budget policy
- Blameless postmortem: tìm lỗi hệ thống, không tìm người có lỗi
- Mô hình chỉ huy sự cố (ICS): một người điều phối, phân vai rõ

## Quy trình (làm đúng thứ tự)
Phát hiện → phân mức SEV → cử chỉ huy sự cố và mở kênh riêng → giảm nhẹ trước (lùi phiên bản, tắt cờ, chuyển hướng tải) → thông báo bên bị ảnh hưởng → chỉ điều tra sâu sau khi dịch vụ đã ổn → tuyên bố kết thúc → postmortem trong 48h → theo dõi action item tới khi đóng.
Khôi phục trước, hiểu sau. Tìm nguyên nhân trong lúc người dùng đang chịu ảnh hưởng là sai thứ tự.

## Quy tắc — phân mức và điều phối
- SEV1: mất dịch vụ hoặc mất/lộ dữ liệu diện rộng — phản hồi ngay, thông báo lãnh đạo, cập nhật mỗi 30 phút. SEV2: chức năng chính suy giảm với một phần đáng kể người dùng — phản hồi trong 30 phút, cập nhật mỗi 60 phút. SEV3: ảnh hưởng hạn chế, có đường vòng — trong giờ làm việc. SEV4: sai sót nhỏ, xử lý theo hàng đợi thường.
- Mức đặt theo tác động lên người dùng và dữ liệu, không theo độ khó kỹ thuật; nghi ngờ thì chọn mức cao hơn rồi hạ sau.
- Mỗi sự cố có đúng một chỉ huy; chỉ huy điều phối chứ không tự tay sửa. Người liên lạc lo thông báo, người ghi chép lo dòng thời gian.
- Kênh liên lạc duy nhất cho sự cố; mọi hành động ghi vào đó theo thời gian thực — dòng thời gian dựng sau trí nhớ luôn sai.
- Thay đổi trong lúc sự cố phải nhỏ, có một người xác nhận, và được ghi lại; không "thử nhiều thứ cùng lúc" vì sẽ không biết cái gì có tác dụng.
- Nghi ngờ có yếu tố bảo mật hoặc lộ dữ liệu cá nhân: kích hoạt thêm quy trình của `security` và `privacy-compliance`, giữ nguyên bằng chứng, và tính tới nghĩa vụ thông báo theo luật.

## Quy tắc — thông báo
- Thông báo cho người bị ảnh hưởng sớm và trung thực: đang xảy ra gì, ảnh hưởng ra sao, đang làm gì, khi nào cập nhật tiếp. Không hứa mốc chưa chắc chắn.
- Nội bộ và bên ngoài dùng cùng một sự thật, khác nhau ở mức chi tiết; không giảm nhẹ trong bản đối ngoại.
- Sau khi đóng, gửi bản tóm tắt cho khách nếu có ảnh hưởng tới họ (xem `customer-acceptance` với hợp đồng có SLA).

## Quy tắc — sau sự cố
- Postmortem blameless trong 48h cho mọi SEV1/SEV2 (và SEV3 nếu lặp lại): dòng thời gian, tác động định lượng, nguyên nhân gốc theo cơ chế, những gì diễn ra tốt, những gì thiếu, và vì sao phát hiện muộn.
- Mỗi action item có chủ sở hữu, hạn, và ticket thật; action item không có ticket coi như không tồn tại. Supervisor theo dõi tới khi đóng.
- Ưu tiên hành động theo thứ tự: ngăn tái diễn > rút ngắn thời gian phát hiện > rút ngắn thời gian khôi phục > cải thiện tài liệu.
- Sự cố lặp lại cùng nguyên nhân được chuyển thành problem có ngân sách xử lý riêng, không xử lý lặt vặt mãi.
- Mỗi sự cố sinh ra hoặc cập nhật một runbook và, nếu phát hiện muộn, một alert mới (xem `observability`).
- Error budget âm thì đóng băng tính năng mới, chỉ nhận việc ổn định hóa, cho tới khi hồi phục.
- Bài học ghi vào `knowledge`; tuyệt đối không quy trách nhiệm cá nhân trong hồ sơ.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] SEV được đặt đúng theo tác động và ghi thời điểm phát hiện
- [ ] Có chỉ huy sự cố và kênh liên lạc duy nhất
- [ ] Giảm nhẹ được thực hiện trước khi điều tra sâu
- [ ] Người bị ảnh hưởng được thông báo đúng nhịp cam kết
- [ ] Dòng thời gian ghi theo thời gian thực, không dựng lại sau
- [ ] Postmortem blameless trong 48h cho SEV1/SEV2
- [ ] Mỗi action item có owner, hạn và ticket thật
- [ ] Có runbook mới/cập nhật và alert nếu phát hiện muộn
- [ ] Sự cố lặp đã chuyển thành problem có ngân sách

## Ví dụ tốt
SEV2 08:12 — thanh toán chậm với ~30% người dùng. Chỉ huy: release-engineer. 08:18 tắt cờ `new_checkout`, độ trễ trở lại bình thường 08:21. Thông báo khách 08:25. Nguyên nhân gốc: pool kết nối cạn do truy vấn thiếu index sau migration. Postmortem 09/09: 5 action item có ticket; alert "pool utilization > 80%" được thêm vì phát hiện muộn 9 phút; runbook RB-09 cập nhật.

## Ví dụ xấu
"Lỗi nhỏ, không cần ghi." Ba người cùng sửa mỗi người một kiểu, không ai ghi lại; postmortem viết sau hai tuần theo trí nhớ và kết luận "do bạn A bất cẩn"; action item nằm trong tài liệu, không có ticket, không ai làm.
