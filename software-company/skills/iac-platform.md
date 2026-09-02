---
name: iac-platform
standards: [Terraform/OpenTofu, CIS Benchmarks, OPA/Conftest, AWS/GCP/Azure Well-Architected, Kubernetes hardening NSA/CISA]
---
# Skill: iac-platform

## Tiêu chuẩn tham chiếu
- Terraform/OpenTofu module conventions
- CIS Benchmarks (cloud + k8s)
- OPA/Conftest policy-as-code
- Well-Architected Framework (5–6 pillar)
- NSA/CISA Kubernetes Hardening Guide

## Quy tắc
- Mọi tài nguyên qua IaC; `plan` trong PR, `apply` qua pipeline, state remote + lock + mã hóa.
- Một module, ba môi trường (dev/stage/prod), khác nhau chỉ ở biến.
- Least privilege: không IAM `*`, không public bucket, không 0.0.0.0/0 vào port quản trị; policy chặn tự động.
- Mã hóa at-rest và in-transit mặc định; KMS key có rotation.
- Tag bắt buộc: project, env, owner, cost-center; drift detection hàng ngày.
- k8s: resource request/limit, non-root, read-only FS, network policy, PodDisruptionBudget cho dịch vụ có SLO.
- Rollback IaC = revert + apply; thử trước khi lên prod.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Plan không destroy ngoài ý muốn
- [ ] Policy pass
- [ ] Không secret trong code/state
- [ ] Tag đủ
- [ ] Chi phí ước tính trong PR

## Ví dụ tốt
PR thêm RDS: module dùng chung, encrypted, private subnet, backup 7 ngày, chi phí ~$58/tháng, plan: 4 add 0 destroy.

## Ví dụ xấu
Tạo bucket public bằng console để test rồi quên.
