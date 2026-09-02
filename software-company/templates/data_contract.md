# Data contract: <tên event/bảng> — v<major.minor>

- Owner (producer): backend|frontend|mobile · Consumer: data, <khác>
- SLA: freshness ≤ <n> phút · completeness ≥ <n>% · retention: <n> ngày
- Phân loại PII: none | personal | sensitive · Giả danh hóa: <cách>

## Schema
| Trường | Kiểu | Bắt buộc | PII | Mô tả |
|---|---|---|---|---|

## Quy tắc thay đổi
- Thêm trường optional: minor. Đổi kiểu / xóa / đổi nghĩa: major + thông báo consumer + song song ≥ 1 sprint.

## Test chất lượng
- [ ] not_null: … - [ ] unique: … - [ ] accepted_values: … - [ ] freshness

## Metric phụ thuộc
| Metric | Định nghĩa (ref) |
|---|---|
