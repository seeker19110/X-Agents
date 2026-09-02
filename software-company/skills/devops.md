---
name: devops
version: 1
standards: [CIS Benchmarks, NIST SSDF, IaC, OpenTelemetry]
---
# Skill: devops

## Tiêu chuẩn tham chiếu
- CIS Benchmarks
- NIST SSDF
- IaC
- OpenTelemetry

## Quy tắc
- Infra bằng IaC có review.
- Quan sát: metrics, logs, traces, SLI/SLO, error budget.
- Không sửa tay server.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] IaC có PR
- [ ] Alert có runbook
- [ ] Secret trong vault

## Ví dụ tốt
terraform plan trong PR; apply qua pipeline.

## Ví dụ xấu
SSH vào sửa config.
