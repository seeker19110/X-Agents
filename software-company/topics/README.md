# Topics

Mỗi file JSON Schema mô tả envelope + payload của một topic. Bus (`src/company/bus.py`)
validate trước khi ghi. Owner ghi của `shared-context` theo namespace (nguồn sự thật:
`NAMESPACE_OWNERS` trong `src/company/events.py`; test `test_registry` kiểm tra khớp
với front matter agent):

| namespace | owner | nội dung |
|---|---|---|
| prd | spec-writer | PRD đã duyệt |
| glossary, design | researcher | thuật ngữ nghiệp vụ; user flow, wireframe, design tokens (ADR-0006) |
| architecture, api-contract (khởi tạo) | delivery-lead | C4, ADR, OpenAPI v1 |
| api-contract (cập nhật) | backend | OpenAPI các version sau |
| schema | database | schema OLTP, migration |
| threat-model | security-engineer | DFD, STRIDE, rủi ro chấp nhận |
| infra | platform | IaC module, môi trường, SLO |
| analytics | data | data contract, định nghĩa metric |
| docs | support-docs | tài liệu người dùng, runbook |
| knowledge | supervisor | bài học, estimate vs actual |
| contract | account-manager | SOW, tiêu chí nghiệm thu, kịch bản UAT |

## Quy ước khác trong payload
- `tasks.risk_tags`: có bất kỳ tag nào (auth, payment, pii, crypto, upload, admin, external-api)
  → delivery-lead chờ thêm `review-results` source=security trước khi tạo release candidate.
- `tasks.estimate_tokens` bắt buộc trước dispatch; `budget_tokens ≥ estimate_tokens × 1.5`.
- `review-results.source` ∈ reviewer | qa | security. `ticket_id` = release_id khi là QA hồi quy trên staging.
- `tasks.depends_on` + `tasks.priority` (1 cao nhất): delivery-lead giữ ticket ở `waiting` đến khi phụ thuộc approved.
- `incidents.root_cause_class` ∈ requirement | design | code | ops | external quyết định incident quay về đâu.
- `change-requests` chỉ thành ticket khi `decision=accepted`; `acceptance-results.signed_by` là người của khách.
