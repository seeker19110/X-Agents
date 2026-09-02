---
name: performance-testing
standards: [ISO/IEC 25010 (performance efficiency), k6/Gatling/Locust, RED/USE, Google SRE SLO]
---
# Skill: performance-testing

## Tiêu chuẩn tham chiếu
- ISO/IEC 25010 (performance efficiency)
- k6/Gatling/Locust
- RED/USE
- Google SRE SLO

## Quy tắc
- Mọi NFR hiệu năng có số đo (p95/p99, RPS, error rate) và kịch bản load tương ứng trước khi code.
- Chạy load/stress/soak trên staging với dữ liệu cỡ production; baseline được lưu để so hồi quy.
- Ngưỡng pass = NFR; vượt ngưỡng là finding block trên release candidate, không phải warn.
- Đo bằng công cụ, trích số thật; không suy đoán từ code.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Kịch bản load cho mọi endpoint/màn hình có NFR
- [ ] p95/p99 và error rate đạt NFR trên staging
- [ ] Soak ≥ 1h không rò rỉ bộ nhớ/kết nối
- [ ] Baseline lưu trong `docs`, so với release trước

## Ví dụ tốt
NFR-07 p95 < 300ms @ 200 RPS → k6 script perf/orders_get.js, kết quả p95 = 212ms, lưu baseline.

## Ví dụ xấu
"Chạy thử thấy nhanh" không có số.
