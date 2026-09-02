---
name: backend
version: 2
standards: [RFC 9110, RFC 9457, OWASP API Security Top 10, OWASP ASVS L2, Idempotency, Twelve-Factor]
---
# Skill: backend

## Tiêu chuẩn tham chiếu
- RFC 9110 (ngữ nghĩa HTTP) và RFC 9457 (Problem Details)
- OWASP API Security Top 10 (đặc biệt BOLA/BFLA — phân quyền theo đối tượng và theo chức năng)
- OWASP ASVS L2 (xác thực, phiên, kiểm soát truy cập, mã hóa)
- Idempotency cho mọi thao tác ghi có thể bị lặp
- Twelve-Factor (config qua env, stateless process, log ra stdout)

## Quy trình (làm đúng thứ tự)
Đọc contract đã chốt (`api-contract`) → viết test từ tiêu chí Gherkin → dựng lớp domain thuần (không hạ tầng) → adapter DB/HTTP → validate ở biên và phân quyền theo đối tượng → idempotency và xử lý lỗi → observability (log/metric/trace) → đo truy vấn và tải theo NFR → dọn dẹp và mở PR.
Không viết logic nghiệp vụ trong controller, không viết truy vấn trong domain.

## Quy tắc — đúng đắn và dữ liệu
- Mọi endpoint ghi có Idempotency-Key: lưu khóa cùng kết quả tối thiểu 24h; gọi lại cùng khóa trả nguyên kết quả cũ, không tạo bản ghi thứ hai; khóa trùng với payload khác là 409.
- Ranh giới giao dịch tường minh và ngắn; không gọi mạng bên ngoài bên trong giao dịch DB; ghi DB kèm phát event dùng outbox (xem `event-driven-architecture`).
- Chống mất cập nhật đồng thời: khóa lạc quan (version/ETag + If-Match) hoặc `SELECT ... FOR UPDATE`; không đọc-rồi-ghi trần.
- Truy vấn có giới hạn: không N+1 (đo số truy vấn trong test), không `SELECT *` trên bảng lớn, mọi danh sách có phân trang và trần cứng.
- Tiền là số nguyên đơn vị nhỏ nhất; không dùng float cho tiền; thời gian lưu UTC.
- Tác vụ dài không chạy trong request: đẩy sang hàng đợi, trả 202 kèm cách theo dõi.

## Quy tắc — an toàn
- Validate ở biên theo schema (kiểu, độ dài, phạm vi, định dạng), từ chối trường lạ; không tin bất cứ giá trị nào từ client, kể cả giá và trạng thái — server tính lại từ nguồn.
- Phân quyền theo từng đối tượng, kiểm ngay tại truy vấn (lọc theo tenant/chủ sở hữu), không chỉ kiểm ở tầng route; test phải có ca "người dùng A đọc dữ liệu người dùng B → 404/403".
- Truy vấn tham số hóa; không nối chuỗi SQL/NoSQL/shell; đầu ra escape theo ngữ cảnh.
- Rate limit theo định danh và theo IP, có `Retry-After`; giới hạn kích thước request, độ sâu và độ phức tạp truy vấn (GraphQL), số file upload.
- Secret qua vault/env, không trong code, không trong log; token có hạn ngắn và có cách thu hồi; mật khẩu băm bằng thuật toán chậm (argon2/bcrypt).
- Lỗi trả ra ngoài không lộ nội bộ; chi tiết chỉ nằm trong log gắn trace_id.

## Quy tắc — vận hành
- Log JSON có trace_id và không PII thô; metric RED cho mỗi endpoint; trace xuyên dịch vụ (xem `observability`).
- Mọi lời gọi ra ngoài có timeout, retry có backoff và jitter (chỉ retry thao tác idempotent), circuit breaker, và hành vi suy giảm rõ ràng khi hỏng.
- Healthcheck tách liveness và readiness; readiness phản ánh phụ thuộc thật; tắt máy êm (drain kết nối, không mất job đang chạy).
- Migration DB tách khỏi deploy code và tương thích ngược (xem `database`); code mới phải chạy được với schema cũ trong thời gian chuyển.
- Cấu hình qua env, khác nhau giữa môi trường chỉ là giá trị; feature flag cho tính năng rủi ro, có đường tắt nhanh.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi endpoint ghi idempotent, có test gửi trùng
- [ ] Lỗi theo Problem Details, không lộ thông tin nội bộ
- [ ] Có test phân quyền theo đối tượng (A không đọc/ghi được dữ liệu của B)
- [ ] Validate biên theo schema; server tự tính giá trị nhạy cảm
- [ ] Rate limit và giới hạn kích thước/độ phức tạp request
- [ ] Không N+1; số truy vấn của luồng chính được đo và có trần
- [ ] Mọi lời gọi ngoài có timeout, retry hợp lệ, và hành vi khi hỏng
- [ ] Log JSON có trace_id, không PII; metric RED có sẵn
- [ ] Không secret trong code hoặc log; migration tương thích ngược

## Ví dụ tốt
`POST /orders/{id}/refund` nhận `Idempotency-Key`, lưu kết quả 24h; server tính lại số tiền hoàn từ đơn gốc, bỏ qua `amount` client gửi; truy vấn lọc sẵn `tenant_id`; gửi thất bại vào DLQ; test gồm ca gửi trùng 3 lần chỉ tạo 1 bản ghi và ca người dùng khác tenant nhận 404.

## Ví dụ xấu
`POST /refund` không idempotent nên retry tạo hai lần hoàn tiền; tin `amount` do client gửi; kiểm quyền bằng `if user.is_logged_in`; lỗi trả `500 {"error": str(e)}` kèm câu SQL.
