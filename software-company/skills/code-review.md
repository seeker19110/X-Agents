---
name: code-review
standards: [Google Engineering Practices, CWE Top 25]
---
# Skill: code-review

## Tiêu chuẩn tham chiếu
- Google Engineering Practices
- CWE Top 25

## Quy tắc
- Đọc theo thứ tự: đúng → an toàn → bảo trì → hiệu năng → tài liệu.
- Finding có file:line và mức block/warn/nit.
- Không tự sửa.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] 0 block
- [ ] Finding có vị trí
- [ ] Tuân contract

## Ví dụ tốt
[block] src/auth.py:42 – so sánh token bằng ==, dùng hmac.compare_digest.

## Ví dụ xấu
Code này hơi lạ.
