---
name: data-engineering
version: 1
standards: [Data contracts, DAMA-DMBOK, dbt conventions, Great Expectations / dq tests, Event schema versioning]
---
# Skill: data-engineering

## Tiêu chuẩn tham chiếu
- Data contract (schema + owner + SLA + version)
- DAMA-DMBOK (quản trị dữ liệu)
- dbt conventions (staging → intermediate → marts)
- Data quality tests (freshness, null, unique, accepted values, referential)
- Event schema versioning (thêm trường = minor, đổi/xóa = major)

## Quy tắc
- Contract trước code: producer và consumer ký contract, CI chặn thay đổi phá vỡ.
- Một metric = một định nghĩa; lưu trong `analytics`, có test.
- Pipeline idempotent, replay được; fail thì không publish bảng.
- Kho phân tích chỉ nhận PII đã giả danh hóa; khóa nối là hash có muối.
- A/B: giả thuyết, metric chính, cỡ mẫu, ngày dừng ghi trước; không "peeking".
- Lineage sinh từ code (dbt docs hoặc tương đương).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Contract có version và owner
- [ ] dq tests pass
- [ ] Metric mới có định nghĩa duy nhất
- [ ] PII giả danh hóa
- [ ] Lineage sinh được

## Ví dụ tốt
Event `order_placed` v2 thêm `coupon_code` (minor); contract cập nhật; test not_null(order_id), unique(order_id); marts.orders_daily rebuild.

## Ví dụ xấu
Đổi kiểu `amount` từ int sang string trong event mà không tăng version; dashboard doanh thu về 0.
