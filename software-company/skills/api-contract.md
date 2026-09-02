---
name: api-contract
standards: [OpenAPI 3.1, AsyncAPI, RFC 9110, RFC 9457, SemVer]
---
# Skill: api-contract

## Tiêu chuẩn tham chiếu
- OpenAPI 3.1
- AsyncAPI
- RFC 9110
- RFC 9457
- SemVer

## Quy tắc
- Contract viết trước code, đặt trên blackboard namespace api-contract.
- Lỗi theo Problem Details.
- Breaking change = major version.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi endpoint có schema request/response/error
- [ ] Có ví dụ
- [ ] Versioned

## Ví dụ tốt
PUT /orders/{id} → 200 Order | 404 application/problem+json

## Ví dụ xấu
Trả {error: 'something wrong'}.
