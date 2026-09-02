---
name: event-driven-architecture
standards: [AsyncAPI 3.0, CloudEvents, Enterprise Integration Patterns, Outbox pattern, Idempotent consumer]
---
# Skill: event-driven-architecture

## Tiêu chuẩn tham chiếu
- AsyncAPI 3.0
- CloudEvents
- Enterprise Integration Patterns
- Outbox pattern
- Idempotent consumer

## Quy tắc
- Mọi event có schema versioned (AsyncAPI), key phân vùng rõ, ngữ nghĩa at-least-once; consumer idempotent.
- Ghi DB và phát event trong cùng giao dịch qua outbox; không dual-write.
- Có dead-letter, retry có backoff, và cách replay theo key; không mất thứ tự trong một key.
- Saga/compensation cho giao dịch nhiều dịch vụ; không 2PC.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Event có schema + version trong contract
- [ ] Consumer idempotent (test gửi trùng)
- [ ] Outbox hoặc tương đương
- [ ] DLQ và runbook replay

## Ví dụ tốt
OrderPaid v2 thêm trường optional, consumer v1 vẫn đọc được; test gửi trùng 3 lần chỉ ghi 1 bản.

## Ví dụ xấu
Publish event sau khi commit DB bằng hai lệnh rời, mất event khi crash giữa chừng.
