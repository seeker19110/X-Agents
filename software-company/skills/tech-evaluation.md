---
name: tech-evaluation
version: 1
standards: [OSS license compatibility, TCO]
---
# Skill: tech-evaluation

## Tiêu chuẩn tham chiếu
- OSS license compatibility
- TCO

## Quy tắc
- ≥ 2 phương án mỗi nhu cầu.
- So sánh license, maturity, cost, lock-in.
- Ưu tiên cái đã có trong stack nếu đáp ứng.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Có recommended + rationale
- [ ] License tương thích
- [ ] Có chi phí vận hành

## Ví dụ tốt
Auth: Keycloak (Apache-2.0, trưởng thành, tự host) vs Auth0 (SaaS, nhanh, chi phí theo MAU). Chọn Keycloak vì yêu cầu on-prem.

## Ví dụ xấu
Dùng thư viện X vì đang hot.
