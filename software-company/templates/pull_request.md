## Ticket
TCK-<id> (REQ-xx) · risk_tags: [] · threat_refs: []
## Thay đổi
## Cách test
## Ảnh hưởng (contract, schema, hiệu năng, chi phí)
## Rollback plan
- Cách: revert PR | feature flag `<tên>` off | migration down `<id>`
- Thời gian dự kiến: < 5 phút · Dữ liệu mất/không mất:
## Observability
- Metric/log/alert mới hoặc thay đổi: … · Dashboard: … · Runbook: …
## Dependency mới
| Tên | Version | License (SPDX) |
|---|---|---|
## Bảo mật / PII
- Chạm PII: có/không · Trường mới: … · Mitigation threat: T-xx
## Checklist
- [ ] Lint pass  - [ ] Test pass  - [ ] Coverage đạt  - [ ] Không secret  - [ ] Docs cập nhật
- [ ] Rollback thử được  - [ ] License dependency hợp lệ  - [ ] Log không PII  - [ ] Feature flag nếu thay đổi hành vi
