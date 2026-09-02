---
name: engineering-common
version: 1
standards: [Twelve-Factor, OWASP ASVS L2, Conventional Commits, Trunk-based + feature flag, OpenTelemetry]
---
# Skill: engineering-common

## Tiêu chuẩn tham chiếu
- Twelve-Factor
- OWASP ASVS L2
- Conventional Commits
- Trunk-based + feature flag
- OpenTelemetry

## Quy tắc
- TDD; test có ý nghĩa, không test để đủ coverage.
- Config qua env; secret qua vault.
- Structured log JSON có correlation ID.
- Không sửa ngoài phạm vi ticket.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Lint pass
- [ ] Coverage nhánh ≥ 80% code mới
- [ ] Không secret trong code
- [ ] Commit message chuẩn

## Ví dụ tốt
feat(orders): add refund endpoint (REQ-014)

Adds idempotent POST /orders/{id}/refund.

## Ví dụ xấu
fix stuff
