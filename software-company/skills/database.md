---
name: database
standards: [3NF, ACID, Migration best practice, PII protection]
---
# Skill: database

## Tiêu chuẩn tham chiếu
- 3NF
- ACID
- Migration best practice
- PII protection

## Quy tắc
- Migration forward+rollback, idempotent.
- Index có lý do đo được.
- PII mã hóa hoặc che; backup có test restore.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Migration up/down sạch
- [ ] RPO/RTO đạt NFR
- [ ] PII được bảo vệ

## Ví dụ tốt
ALTER TABLE ... ADD COLUMN ... NULL; backfill theo batch; sau đó SET NOT NULL.

## Ví dụ xấu
DROP COLUMN ngay trong một migration.
