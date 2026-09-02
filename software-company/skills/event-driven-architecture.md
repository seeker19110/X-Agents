---
name: event-driven-architecture
version: 2
standards: [AsyncAPI 3.0, CloudEvents, Enterprise Integration Patterns, Outbox pattern, Idempotent consumer, Saga]
---
# Skill: event-driven-architecture

## Tiêu chuẩn tham chiếu
- AsyncAPI 3.0 để mô tả kênh, message, và schema
- CloudEvents cho phần bao chuẩn (id, source, type, time, subject)
- Enterprise Integration Patterns (kênh, bộ định tuyến, bộ chuyển đổi, DLQ)
- Outbox pattern cho ghi DB và phát event trong một giao dịch
- Idempotent consumer và at-least-once làm giả định mặc định
- Saga / compensation cho giao dịch nhiều dịch vụ

## Quy trình (làm đúng thứ tự)
Xác định sự kiện nghiệp vụ (việc đã xảy ra) → đặt tên ở thì quá khứ và định nghĩa schema trong contract → chọn khóa phân vùng theo thực thể cần giữ thứ tự → chốt ngữ nghĩa giao hàng và cách khử trùng lặp ở consumer → thiết kế outbox ở producer → DLQ, retry, cách phát lại → test gửi trùng và test sai thứ tự → giám sát độ trễ tiêu thụ (lag) và DLQ.
Chọn event chỉ khi cần tách nhịp hoặc nhiều người tiêu thụ; gọi đồng bộ vẫn tốt hơn cho luồng cần trả lời ngay.

## Quy tắc — event và schema
- Event mô tả việc đã xảy ra (`OrderPaid`), không mô tả mệnh lệnh (`SendEmail`); mệnh lệnh thì dùng command có người nhận xác định.
- Mỗi event có schema versioned trong contract, id duy nhất, thời điểm xảy ra, nguồn, và khóa thực thể; thêm trường optional là minor, đổi/xóa là major.
- Giai đoạn chuyển version: producer phát cả hai, consumer cũ vẫn đọc được, gỡ version cũ sau khi không còn ai đọc — có số liệu chứng minh.
- Chọn giữa event mỏng (chỉ id, consumer tự gọi lại) và event dày (mang đủ dữ liệu): ghi rõ lựa chọn và lý do; đừng nửa vời khiến consumer vừa phải đọc vừa phải gọi.
- Không đưa PII không cần thiết vào event; event thường được lưu lâu và nhân bản nhiều nơi (xem `privacy-compliance`).

## Quy tắc — giao hàng và tính đúng đắn
- Giả định at-least-once: consumer phải idempotent, khử trùng lặp theo id event hoặc theo khóa nghiệp vụ, và có test gửi trùng.
- Ghi DB và phát event trong cùng giao dịch qua outbox; không dual-write (ghi DB rồi gọi broker bằng hai lệnh rời).
- Thứ tự chỉ được đảm bảo trong một khóa phân vùng; thiết kế phải chịu được sai thứ tự giữa các khóa, và consumer bỏ qua event cũ hơn trạng thái hiện có.
- Retry có backoff và jitter, số lần hữu hạn; hết thì vào DLQ kèm nguyên nhân, không loop vô hạn làm nghẽn phân vùng.
- Poison message không được chặn cả kênh: tách riêng, cảnh báo, và có runbook phát lại theo khóa hoặc theo khoảng thời gian.
- Giao dịch nhiều dịch vụ dùng saga với bước bù trừ khai báo rõ; không 2PC. Mỗi bước bù trừ phải idempotent và có test.

## Quy tắc — vận hành
- Giám sát: độ trễ tiêu thụ (consumer lag), tuổi event cũ nhất chưa xử lý, kích thước DLQ, tỉ lệ lỗi theo loại event; alert có runbook (xem `observability`).
- Phát lại (replay) là năng lực có sẵn và đã diễn tập, không phải việc ứng biến lúc sự cố; ghi rõ phát lại có gây tác dụng phụ nào không.
- Lưu giữ (retention) của kênh khai báo rõ và đủ dài để phát lại theo nhu cầu nghiệp vụ.
- Consumer mới không được làm chậm producer; áp dụng backpressure hoặc kênh riêng cho consumer chậm.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mỗi event có schema và version trong contract, tên ở thì quá khứ
- [ ] Khóa phân vùng khai báo rõ, giả định thứ tự được nêu
- [ ] Consumer idempotent, có test gửi trùng và test sai thứ tự
- [ ] Producer dùng outbox hoặc cơ chế tương đương; không dual-write
- [ ] Retry có giới hạn, có DLQ và runbook phát lại
- [ ] Saga có bước bù trừ, mỗi bước idempotent và được test
- [ ] Giám sát lag và DLQ có alert kèm runbook
- [ ] Event không mang PII không cần thiết; retention khai báo

## Ví dụ tốt
`OrderPaid` v2 thêm `coupon_code` optional; consumer v1 vẫn đọc được. Producer ghi bảng `outbox` trong cùng giao dịch với đơn hàng; bộ phát đọc outbox và publish. Consumer khử trùng lặp theo `event_id`, test gửi 3 lần chỉ ghi 1 bản; sai thứ tự thì bỏ qua event có `version` nhỏ hơn. Alert khi lag > 5 phút, runbook RB-11 mô tả cách phát lại theo `order_id`.

## Ví dụ xấu
Commit DB xong rồi gọi broker ở lệnh kế tiếp, crash giữa chừng làm mất event; consumer cộng tiền mỗi lần nhận nên retry thành cộng hai lần; một message hỏng khiến toàn bộ phân vùng dừng suốt đêm vì retry vô hạn.
