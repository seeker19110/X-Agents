---
name: codebase-analysis
version: 1
standards: [C4 model, SBOM]
---
# Skill: codebase-analysis

## Tiêu chuẩn tham chiếu
- C4 model
- SBOM

## Quy tắc
- Dùng tool quét dependency và call graph; không đọc tay toàn bộ.
- Impact map theo file path cụ thể.
- Nợ kỹ thuật chỉ ghi khi chặn yêu cầu.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] impact_map phủ mọi goal
- [ ] Mọi dep có license
- [ ] Không suy đoán module không tồn tại

## Ví dụ tốt
GOAL-2 chạm src/orders/service.py, src/orders/models.py; cần migration.

## Ví dụ xấu
Chắc chỗ nào đó trong module orders.
