---
name: mobile
version: 1
standards: [Apple HIG, Material 3, OWASP MASVS, Store policies]
---
# Skill: mobile

## Tiêu chuẩn tham chiếu
- Apple HIG
- Material 3
- OWASP MASVS
- Store policies

## Quy tắc
- Token trong keychain/keystore.
- Quyền tối thiểu, xin đúng lúc.
- Offline-first có conflict resolution.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] MASVS L1 pass
- [ ] Crash-free ≥ 99.5%
- [ ] Tuân store policy

## Ví dụ tốt
Xin quyền camera khi user bấm chụp, có giải thích.

## Ví dụ xấu
Xin mọi quyền lúc mở app.
