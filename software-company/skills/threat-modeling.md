---
name: threat-modeling
standards: [STRIDE, CVSS 4.0, OWASP ASVS, MITRE ATT&CK, OWASP SAMM]
---
# Skill: threat-modeling

## Tiêu chuẩn tham chiếu
- STRIDE trên data-flow diagram (DFD) có trust boundary
- CVSS 4.0 để chấm mức
- OWASP ASVS (L2 mặc định, L3 tài chính/y tế)
- MITRE ATT&CK để mô tả kịch bản
- OWASP SAMM để đo độ chín

## Quy tắc
- Threat model trước ticket đầu tiên; cập nhật khi đổi kiến trúc, thêm tích hợp ngoài, thêm PII.
- DFD tối thiểu: actor, process, data store, external entity, trust boundary.
- Mỗi threat: id, STRIDE category, asset, CVSS, mitigation, owner, trạng thái (open / mitigated / accepted-with-ADR).
- Threat High/Critical không có mitigation → không qua Gate 2.
- Rủi ro chấp nhận phải có ADR và người ký (human).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] DFD có trust boundary
- [ ] Mọi threat có owner
- [ ] High/Critical có mitigation hoặc ADR
- [ ] Threat model có version trong `threat-model`
- [ ] Ticket risk_tags map về threat id

## Ví dụ tốt
T-04 Tampering: client sửa giá trong request → mitigation: server tính lại giá từ catalog, test T-04 trong CI; owner backend; TCK-12.

## Ví dụ xấu
"Hệ thống dùng HTTPS nên an toàn."
