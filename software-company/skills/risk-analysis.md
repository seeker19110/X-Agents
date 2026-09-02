---
name: risk-analysis
version: 1
standards: [FMEA, STRIDE, ISO 31000]
---
# Skill: risk-analysis

## Tiêu chuẩn tham chiếu
- FMEA
- STRIDE
- ISO 31000

## Quy tắc
- RPN = severity × occurrence × detection.
- Mọi rủi ro High có mitigation và owner.
- Threat model STRIDE cho mọi luồng dữ liệu nhạy cảm.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Không rủi ro High thiếu mitigation
- [ ] Có đề xuất cắt/hoãn rõ ràng
- [ ] Có owner

## Ví dụ tốt
RISK-3 (Security, High): token lưu localStorage → XSS đánh cắp. Mitigation: httpOnly cookie + CSP. Owner: frontend.

## Ví dụ xấu
Có thể có rủi ro bảo mật.
