---
name: backend
version: 1
standards: [RFC 9110, RFC 9457, OWASP API Top 10, Idempotency]
---
# Skill: backend

## Tiêu chuẩn tham chiếu
- RFC 9110
- RFC 9457
- OWASP API Top 10
- Idempotency

## Quy tắc
- Idempotency key cho mọi endpoint ghi.
- Validation ở biên; rate limit.
- Pagination/filter chuẩn.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Endpoint ghi idempotent
- [ ] Lỗi theo Problem Details
- [ ] Có rate limit

## Ví dụ tốt
Header Idempotency-Key; lưu kết quả 24h; trùng key trả lại kết quả cũ.

## Ví dụ xấu
POST không idempotent, retry tạo 2 đơn.
