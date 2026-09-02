---
name: observability
version: 1
standards: [OpenTelemetry, Google SRE SLI/SLO, RED/USE, Structured logging]
---
# Skill: observability

## Tiêu chuẩn tham chiếu
- OpenTelemetry (traces, metrics, logs; semantic conventions)
- Google SRE: SLI/SLO, error budget, alert theo burn rate
- RED (Rate, Errors, Duration) cho service; USE (Utilization, Saturation, Errors) cho tài nguyên
- Structured logging (JSON) có correlation/trace id

## Quy tắc
- Mỗi dịch vụ mới có trước khi nhận traffic: dashboard RED, SLO khai báo trong code, alert theo burn rate có runbook.
- Log: JSON, có trace_id, không PII thô, level đúng; không log trong vòng lặp nóng.
- Trace xuyên biên dịch vụ; sampling khai báo.
- Alert chỉ khi cần người hành động; mỗi alert map về một runbook; alert không có runbook bị xóa.
- Metric có nhãn giới hạn cardinality (không user_id, không request_id).
- Error budget âm → đóng băng tính năng, chỉ nhận ticket ổn định.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Dashboard RED có
- [ ] SLO trong code
- [ ] Alert có runbook
- [ ] Log JSON có trace_id, không PII
- [ ] Cardinality nhãn kiểm soát

## Ví dụ tốt
`orders-api`: SLO 99.9% thành công / 30 ngày; alert burn rate 14.4× trong 1h → page; runbook RB-07.

## Ví dụ xấu
Alert "CPU > 80%" gửi mọi người, không ai biết làm gì.
