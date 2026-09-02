---
name: architecture
standards: [C4 model, arc42, Clean/Hexagonal, DDD, ADR (Nygard)]
---
# Skill: architecture

## Tiêu chuẩn tham chiếu
- C4 model
- arc42
- Clean/Hexagonal
- DDD
- ADR (Nygard)

## Quy tắc
- C4 L1–L2 trước ticket đầu tiên.
- Mọi quyết định quan trọng có ADR với phương án bị loại.
- Ranh giới module theo bounded context.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Có C4
- [ ] Có ADR cho mọi quyết định không hiển nhiên
- [ ] Contract-first

## Ví dụ tốt
ADR-0007: chọn Postgres thay Mongo vì cần giao dịch đa bảng; loại Mongo vì yêu cầu ACID.

## Ví dụ xấu
Dùng Postgres.
