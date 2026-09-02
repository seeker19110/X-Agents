# Tiêu chuẩn ngành áp dụng

Bản tóm tắt; chi tiết dạng rule + checklist nằm trong `skills/`.

## Toàn công ty
- ISO/IEC 12207, ISO 9001, CMMI L3 (quy trình)
- ISO/IEC 25010 (8 đặc tính chất lượng; mọi NFR map về đây)
- ISO/IEC 27001, ISO/IEC 27701, SOC 2 Type II, GDPR, Nghị định 13/2023/NĐ-CP
- OpenChain ISO/IEC 5230, SPDX (license, SBOM)
- Traceability matrix: requirement → ticket → PR → test → release
- Prompt là code (ADR-0004): version, review, eval, rollback
- Ước lượng trước dispatch (skill cost-estimation): estimate_tokens, budget = estimate × 1.5

## Khối 1 – Nghiên cứu yêu cầu
ISO/IEC/IEEE 29148, BABOK v3, INVEST, Gherkin, MoSCoW/WSJF, FMEA, STRIDE sơ bộ, ADR.
- UX (ux-designer): ISO 9241-210, WCAG 2.2 AA, Nielsen heuristics, design tokens W3C; mọi màn hình đủ 4 trạng thái.

## Khối 2 – Delivery lead
PMBOK 7, Scrum Guide 2020, ISO 21502, C4 model, arc42, OpenAPI 3.1/AsyncAPI, SemVer, DORA, PERT/reference-class.

## Khối 3 – Kỹ thuật
Twelve-Factor, OWASP ASVS L2 (L3 tài chính/y tế), Conventional Commits, trunk-based + feature flag, WCAG 2.2 AA.
- Backend: RFC 9110, RFC 9457, idempotency key, OWASP API Top 10
- Frontend: Core Web Vitals (LCP<2.5s, INP<200ms, CLS<0.1), CSP, i18n; giao diện từ namespace `design`
- Mobile: HIG, Material 3, OWASP MASVS, crash-free ≥ 99.5%
- Database: 3NF trừ khi có ADR, migration forward+rollback, PII mã hóa, test restore
- Platform: Terraform/OpenTofu, CIS Benchmarks, OPA policy-as-code, Well-Architected, NSA/CISA k8s hardening; plan trong PR, apply qua pipeline
- Data: data contract, DAMA-DMBOK, dbt conventions, dq tests, event schema versioning; PII giả danh hóa trước kho phân tích

## Khối 4 – Chất lượng
ISO/IEC/IEEE 29119, ISTQB, OWASP Testing Guide, Google Eng Practices, SLSA L3, CWE Top 25,
SBOM (SPDX/CycloneDX), mutation testing ≥ 70% module lõi, contract testing.
- Security-engineer: STRIDE trên DFD, CVSS 4.0, OWASP SAMM, DAST trước release, DPIA (GDPR Art. 35, NĐ13), license policy (cấm GPL/AGPL/SSPL trừ ADR).
- Separation of duties: reviewer ≠ security-engineer; ticket có `risk_tags` cần cả hai.

## Khối 5 – Vận hành
Google SRE, ITIL 4, DORA, GitOps, CIS Benchmarks, NIST SSDF, ISO 22301, Diátaxis, Keep a Changelog,
Sigstore, blue-green/canary + auto-rollback theo SLO, blameless postmortem ≤ 48h.
- Observability: OpenTelemetry, RED/USE, SLO trong code, alert theo burn rate có runbook, log JSON không PII.

## Khối 6 – Supervisor
NIST AI RMF, ISO/IEC 42001, OWASP Top 10 for LLM, FinOps. Cảnh báo 80% / cắt 100% ngân sách.
Theo dõi version prompt gây lỗi lặp; ghi estimate vs actual vào `knowledge`.

## Khối 7 – Human gate
Separation of duties, four-eyes cho production, quyền ký cam kết (rủi ro chấp nhận, license ngoại lệ, chuyển dữ liệu xuyên biên giới) chỉ ở người.
