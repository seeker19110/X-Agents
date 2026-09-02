---
name: resilience-testing
version: 1
standards: [Principles of Chaos Engineering, Netflix Simian Army, AWS Fault Injection Service, Google DiRT game day, Release It! (bulkhead, circuit breaker)]
---
# Skill: resilience-testing

## Tiêu chuẩn tham chiếu
- Principles of Chaos Engineering: thí nghiệm có giả thuyết trên hệ thống chạy thật, so với trạng thái ổn định
- Netflix Simian Army và AWS Fault Injection Service làm mô hình công cụ chèn lỗi
- Google DiRT: game day định kỳ, diễn tập cả kỹ thuật lẫn quy trình con người
- Release It! (Nygard): bulkhead, circuit breaker, timeout, backpressure là các mẫu chịu lỗi cần kiểm chứng
- Hệ thống chỉ được coi là chịu lỗi khi đã bị làm cho hỏng có kiểm soát, không phải khi thiết kế nói vậy

## Quy trình (làm đúng thứ tự)
Định nghĩa trạng thái ổn định bằng chỉ số đo được (xem `observability`) → nêu giả thuyết dạng "khi X hỏng, chỉ số Y vẫn trong ngưỡng Z" → xác định bán kính ảnh hưởng nhỏ nhất → khai báo tiêu chí dừng khẩn và cách hoàn tác → thông báo trước cho các bên → chạy thí nghiệm trong cửa sổ ngắn có người trực → quan sát và dừng ngay khi chạm ngưỡng → ghi kết quả và mở ticket cho mọi giả thuyết bị bác bỏ → tăng dần bán kính ở lần sau.
Không chạy thí nghiệm khi chưa quan sát được: không có dashboard và alert thì chèn lỗi chỉ là gây sự cố.

## Quy tắc — giả thuyết và bán kính ảnh hưởng
- Mỗi thí nghiệm có đúng một giả thuyết viết trước, có số: ví dụ "khi 30% instance `orders-api` bị kill, tỉ lệ lỗi tại biên < 0.5% và p99 < 900ms".
- Thí nghiệm mà ta đã biết chắc sẽ hỏng thì không chạy: sửa trước rồi mới kiểm chứng.
- Bán kính bắt đầu nhỏ nhất có thể: một instance, một AZ, một tenant nội bộ, hoặc ≤ 1% lưu lượng; chỉ mở rộng sau khi lần trước xanh.
- Thứ tự môi trường: staging có tải mô phỏng → production ngoài giờ cao điểm với bán kính nhỏ → production giờ thường. Không nhảy cóc.
- Chạy production cần: người trực sẵn sàng, kênh liên lạc mở, cờ hoàn tác trong tầm tay, và phê duyệt của chủ sở hữu dịch vụ.
- Không thí nghiệm trên đường dẫn ghi dữ liệu tiền tệ hoặc dữ liệu cá nhân khi chưa chứng minh được là không mất dữ liệu.

## Quy tắc — loại lỗi cần chèn
- Hạ tầng: kill instance/pod, mất một AZ, đầy đĩa, cạn CPU/bộ nhớ, đồng hồ lệch.
- Mạng: thêm độ trễ (ví dụ +200ms, +2s), mất gói 1–5%, chia cắt mạng, DNS hỏng, chứng chỉ TLS hết hạn.
- Phụ thuộc: cơ sở dữ liệu chậm hoặc từ chối kết nối, hàng đợi ứ, dịch vụ bên thứ ba trả 500 hoặc treo tới hết timeout.
- Ứng dụng: trả lỗi có chủ đích, giới hạn tốc độ, làm cạn pool kết nối, gây lệch dữ liệu giữa replica.
- Mỗi thí nghiệm kiểm chứng một cơ chế phòng vệ cụ thể: timeout có thật không, retry có backoff và jitter không, circuit breaker có mở không, bulkhead có cô lập không, có hiện tượng thundering herd không.
- Kiểm cả suy giảm có kiểm soát: khi phụ thuộc không thiết yếu hỏng, chức năng chính vẫn phục vụ được ở mức rút gọn.

## Quy tắc — game day và tiêu chí dừng
- Game day tối thiểu mỗi quý cho dịch vụ tầng 1, có kịch bản viết trước, vai trò như sự cố thật, và tính giờ MTTD/MTTR.
- Game day kiểm cả con người và quy trình: người trực có tìm được runbook không, alert có kêu không, thông báo có đúng nhịp không.
- Tiêu chí dừng khẩn khai báo trước và cưỡng chế được: lỗi tại biên vượt ngưỡng SLO còn lại của error budget, p99 xấu hơn 2×, có dấu hiệu mất hoặc sai dữ liệu, hoặc có người dùng thật khiếu nại.
- Hoàn tác trong ≤ 2 phút, tự động khi chạm ngưỡng, và có nút dừng thủ công cho bất kỳ ai trong phòng.
- Thí nghiệm bác bỏ giả thuyết là kết quả tốt: mở ticket có chủ sở hữu và hạn, chạy lại sau khi sửa để xác nhận.
- Thí nghiệm đã xanh được đưa vào chạy định kỳ tự động để chống hồi quy; không kiểm một lần rồi thôi.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Trạng thái ổn định định nghĩa bằng chỉ số đo được, có dashboard
- [ ] Giả thuyết viết trước, có ngưỡng bằng số
- [ ] Bán kính ảnh hưởng nhỏ nhất và tăng dần theo lần
- [ ] Có phê duyệt của chủ sở hữu dịch vụ khi chạy production
- [ ] Tiêu chí dừng khẩn khai báo trước và tự động cưỡng chế
- [ ] Hoàn tác ≤ 2 phút, có nút dừng thủ công
- [ ] Cơ chế phòng vệ cụ thể (timeout, retry, circuit breaker, bulkhead) được kiểm chứng
- [ ] Game day mỗi quý cho dịch vụ tầng 1, đo MTTD/MTTR
- [ ] Giả thuyết bị bác bỏ có ticket và được chạy lại sau khi sửa

## Ví dụ tốt
Thí nghiệm CE-11: giả thuyết "thêm 2s độ trễ vào `pricing-svc` thì `checkout` vẫn có tỉ lệ thành công ≥ 99.5% nhờ circuit breaker và giá dự phòng". Bán kính 1% lưu lượng, 14:00–14:20 thứ Tư, dừng khẩn khi lỗi > 1%. Kết quả: breaker mở đúng sau 12 giây nhưng retry không có jitter gây tăng vọt tải — giả thuyết bác bỏ một phần, ticket ENG-903, sửa xong chạy lại xanh, thí nghiệm đưa vào lịch hằng tuần. Game day quý III: MTTD 3 phút, MTTR 19 phút, runbook RB-04 thiếu bước tắt cờ nên được cập nhật.

## Ví dụ xấu
"Chaos monkey" bật trên production toàn hệ thống ngay lần đầu, không báo ai, gây SEV1 thật; không có giả thuyết nên kết luận duy nhất là "hình như hệ thống yếu"; không có tiêu chí dừng, mất 40 phút để tắt vì công cụ chạy từ máy cá nhân của một người đang đi ăn trưa; thí nghiệm bác bỏ giả thuyết nhưng chỉ ghi vào slide tổng kết, không có ticket nào được mở.
