---
name: debugging
version: 1
standards: [Scientific debugging]
---
# Skill: debugging

## Tiêu chuẩn tham chiếu
- Scientific debugging

## Quy tắc
- Tái hiện → cô lập → giả thuyết → xác minh.
- Bug report có repro step, expected/actual, mức độ.
- Gợi ý sửa nhưng không sửa.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Có repro
- [ ] Có root cause
- [ ] Có gợi ý

## Ví dụ tốt
Root cause: race giữa 2 worker cùng đọc balance trước khi ghi. Gợi ý: SELECT FOR UPDATE.

## Ví dụ xấu
Đôi khi bị lỗi.
