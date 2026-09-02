# Tiêu chuẩn ngành áp dụng

Bản tóm tắt; chi tiết dạng rule + checklist nằm trong `skills/`.

## Toàn công ty
- ISO/IEC 12207, ISO 9001, CMMI L3 (quy trình)
- ISO/IEC 25010 (8 đặc tính chất lượng; mọi NFR map về đây)
- ISO/IEC 27001, SOC 2 Type II, GDPR, Nghị định 13/2023/NĐ-CP
- Traceability matrix: requirement → ticket → PR → test → release

## Khối 1 – Nghiên cứu yêu cầu
ISO/IEC/IEEE 29148, BABOK v3, INVEST, Gherkin, MoSCoW/WSJF, FMEA, STRIDE sơ bộ, ADR.

## Khối 2 – Delivery lead
PMBOK 7, Scrum Guide 2020, ISO 21502, C4 model, arc42, OpenAPI 3.1/AsyncAPI, SemVer, DORA.

## Khối 3 – Kỹ thuật
Twelve-Factor, OWASP ASVS L2 (L3 tài chính/y tế), Conventional Commits, trunk-based + feature flag, WCAG 2.2 AA.
- Backend: RFC 9110, RFC 9457, idempotency key, OWASP API Top 10
- Frontend: Core Web Vitals (LCP<2.5s, INP<200ms, CLS<0.1), CSP, i18n
- Mobile: HIG, Material 3, OWASP MASVS, crash-free ≥ 99.5%
- Database: 3NF trừ khi có ADR, migration forward+rollback, PII mã hóa, test restore

## Khối 4 – Chất lượng
ISO/IEC/IEEE 29119, ISTQB, OWASP Testing Guide, Google Eng Practices, SLSA L3, CWE Top 25,
SBOM (SPDX/CycloneDX), mutation testing ≥ 70% module lõi, contract testing.

## Khối 5 – Vận hành
Google SRE, ITIL 4, DORA, GitOps, CIS Benchmarks, NIST SSDF, ISO 22301, Diátaxis, Keep a Changelog,
Sigstore, blue-green/canary + auto-rollback theo SLO, blameless postmortem ≤ 48h.

## Khối 6 – Supervisor
NIST AI RMF, ISO/IEC 42001, OWASP Top 10 for LLM, FinOps. Cảnh báo 80% / cắt 100% ngân sách.

## Khối 7 – Human gate
Separation of duties, four-eyes cho production, quyền ký cam kết chỉ ở người.
