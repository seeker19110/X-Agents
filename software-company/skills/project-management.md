---
name: project-management
standards: [PMBOK 7, Scrum Guide 2020, DORA]
---
# Skill: project-management

## Tiêu chuẩn tham chiếu
- PMBOK 7
- Scrum Guide 2020
- DORA

## Quy tắc
- Ticket ≤ 1 ngày công agent.
- Ticket có requirement_id, acceptance, estimate, depends_on.
- Đo 4 chỉ số DORA mỗi sprint.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Không ticket mồ côi
- [ ] Có critical path
- [ ] DORA được ghi

## Ví dụ tốt
TCK-42 ← REQ-014: thêm index và cache cho search. Est 0.5d. Depends: TCK-41.

## Ví dụ xấu
Làm phần search.
