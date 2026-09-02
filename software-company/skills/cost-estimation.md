---
name: cost-estimation
version: 1
standards: [Three-point estimate (PERT), Reference-class forecasting, FinOps unit economics, DORA]
---
# Skill: cost-estimation

## Tiêu chuẩn tham chiếu
- Ước lượng 3 điểm (PERT): (O + 4M + P) / 6
- Reference-class forecasting: so với ticket tương tự đã xong (từ `knowledge`)
- FinOps unit economics: chi phí / ticket, / tính năng, / khách
- DORA: lead time thực tế để hiệu chỉnh

## Quy tắc
- TRƯỚC khi dispatch, mỗi ticket có: `estimate_days`, `estimate_tokens`, `budget_tokens = ceil(estimate_tokens × 1.5)`.
- Ước lượng dựa trên tham chiếu: tìm ≥ 2 ticket tương tự trong `knowledge`; không có thì ghi "chưa có tham chiếu" và dùng PERT.
- Ticket > 1 ngày hoặc > 200k token → chia nhỏ, không dispatch.
- Tổng estimate của sprint ≤ ngân sách dự án human đã duyệt ở Gate 2.
- Sau khi ticket đóng: ghi actual vs estimate vào `knowledge`; sai lệch > 50% → bài học.
- Delivery-lead báo mỗi sprint: estimate/actual theo assignee, DORA 4 chỉ số.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi ticket có estimate_tokens trước dispatch
- [ ] budget ≥ estimate × 1.5
- [ ] Không ticket > 1 ngày / 200k token
- [ ] Tổng sprint ≤ ngân sách duyệt
- [ ] Actual ghi vào knowledge

## Ví dụ tốt
TCK-31 "thêm endpoint GET /orders/{id}": tham chiếu TCK-12, TCK-19 (avg 42k token) → estimate 45k, budget 68k, 0.5d.

## Ví dụ xấu
Mọi ticket budget 120k "cho chắc".
