---
name: security
standards: [OWASP ASVS, SLSA L3, SBOM SPDX/CycloneDX, Sigstore]
---
# Skill: security

## Tiêu chuẩn tham chiếu
- OWASP ASVS
- SLSA L3
- SBOM SPDX/CycloneDX
- Sigstore

## Quy tắc
- SAST + SCA + secret scan mỗi PR.
- SBOM mỗi build.
- License check.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] 0 High
- [ ] SBOM có
- [ ] Artifact ký

## Ví dụ tốt
Semgrep: 0 High; Trivy: 1 Medium (CVE-... trong lib X, không reachable, ghi nhận).

## Ví dụ xấu
Scan lỗi nhưng chắc không sao.
