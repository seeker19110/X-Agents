# Topics

Mỗi file JSON Schema mô tả envelope + payload của một topic. Bus (`src/company/bus.py`)
validate trước khi ghi. Owner ghi của `shared-context` theo namespace (nguồn sự thật:
`NAMESPACE_OWNERS` trong `src/company/events.py`; test `test_registry` kiểm tra khớp
với front matter agent):

| namespace | owner | nội dung |
|---|---|---|
| prd | spec-writer | PRD đã duyệt |
| glossary | domain | thuật ngữ nghiệp vụ |
| design | ux-designer | user flow, wireframe, design tokens |
| architecture, api-contract (khởi tạo) | delivery-lead | C4, ADR, OpenAPI v1 |
| api-contract (cập nhật) | backend | OpenAPI các version sau |
| schema | database | schema OLTP, migration |
| threat-model | security-engineer | DFD, STRIDE, rủi ro chấp nhận |
| infra | platform | IaC module, môi trường, SLO |
| analytics | data | data contract, định nghĩa metric |
| docs | support-docs | tài liệu người dùng, runbook |
| knowledge | supervisor | bài học, estimate vs actual |

## Quy ước khác trong payload
- `tasks.risk_tags`: có bất kỳ tag nào (auth, payment, pii, crypto, upload, admin, external-api)
  → delivery-lead chờ thêm `review-results` source=security trước khi tạo release candidate.
- `tasks.estimate_tokens` bắt buộc trước dispatch; `budget_tokens ≥ estimate_tokens × 1.5`.
- `review-results.source` ∈ reviewer | qa | security.
