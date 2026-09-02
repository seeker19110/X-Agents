---
name: release
version: 1
standards: [Google SRE, GitOps, Blue-green/Canary, SemVer]
---
# Skill: release

## Tiêu chuẩn tham chiếu
- Google SRE
- GitOps
- Blue-green/Canary
- SemVer

## Quy tắc
- Pipeline tách stage; artifact ký.
- Canary với auto-rollback theo SLO.
- Runbook trước traffic.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi stage pass
- [ ] Rollback < 5 phút thử được
- [ ] SLO giữ trong canary

## Ví dụ tốt
Canary 5% 15 phút, error rate < 0.1% → 50% → 100%.

## Ví dụ xấu
Deploy thẳng 100%.
