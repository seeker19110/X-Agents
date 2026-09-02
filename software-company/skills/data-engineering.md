---
name: data-engineering
version: 2
standards: [Data contracts, DAMA-DMBOK, dbt conventions, Data quality tests, Event schema versioning, Medallion layering]
---
# Skill: data-engineering

## Tiêu chuẩn tham chiếu
- Data contract: schema + owner + SLA (độ tươi, độ đầy đủ) + version
- DAMA-DMBOK (quản trị dữ liệu, chất lượng, siêu dữ liệu)
- dbt conventions: staging → intermediate → marts (phân tầng thô → chuẩn hóa → phục vụ)
- Data quality tests: freshness, null, unique, accepted values, referential, volume anomaly
- Event schema versioning: thêm trường optional là minor, đổi/xóa là major

## Quy trình (làm đúng thứ tự)
Xác định câu hỏi nghiệp vụ và metric cần trả lời → chốt data contract với producer → nạp thô bất biến (raw, append-only) → chuẩn hóa ở staging → mô hình hóa ở marts → viết dq test cùng lúc với mô hình → sinh lineage và tài liệu từ code → công bố metric vào `analytics` → theo dõi độ tươi và chất lượng sau khi lên.
Không xây dashboard trước khi metric có định nghĩa duy nhất.

## Quy tắc — hợp đồng dữ liệu và schema
- Contract trước code: producer và consumer cùng ký; CI chặn thay đổi phá vỡ contract. Producer đổi schema mà không tăng version là finding block.
- Raw là bất biến và có thể phát lại: giữ nguyên bản gốc kèm thời điểm nạp và nguồn; mọi biến đổi nằm ở tầng sau.
- Event: thêm trường optional là minor; đổi kiểu, đổi nghĩa, xóa trường là major và cần giai đoạn chạy song song hai version.
- Mọi bảng phục vụ (mart) có khóa chính rõ, hạt (grain) ghi trong mô tả, và test unique + not_null trên khóa đó.
- Thời gian: phân biệt event time và ingest time; xử lý dữ liệu đến muộn có quy tắc rõ (cửa sổ trễ, cách backfill).

## Quy tắc — pipeline
- Pipeline idempotent và phát lại được: chạy lại cùng khoảng thời gian cho cùng kết quả; ưu tiên ghi theo phân vùng thay vì cập nhật tại chỗ.
- Fail thì không publish: bảng chỉ đổi khi toàn bộ test pass (ghi vào bảng tạm rồi hoán đổi); không để consumer thấy dữ liệu dở.
- Mỗi bảng có SLA độ tươi và cảnh báo khi trễ; job có timeout, retry, và thông báo có người nhận.
- Backfill là thao tác có kế hoạch: phạm vi, chi phí, ảnh hưởng tới báo cáo, và được ghi lại.
- Chi phí truy vấn có trần: phân vùng và cụm hóa theo cột lọc chính; truy vấn quét toàn bảng trong job hằng ngày là finding.

## Quy tắc — metric, riêng tư, thí nghiệm
- Một metric có đúng một định nghĩa, lưu trong `analytics`, kèm công thức, hạt, bộ lọc, và chủ sở hữu; hai dashboard cho ra hai số khác nhau là sự cố dữ liệu.
- Kho phân tích chỉ nhận PII đã giả danh hóa; khóa nối là hash có muối, muối quản lý như secret; quyền truy cập theo vai trò, không mở toàn bộ (xem `privacy-compliance`).
- A/B test: ghi trước giả thuyết, metric chính, cỡ mẫu, ngày dừng; không "peeking" rồi dừng sớm khi thấy đẹp; báo cáo cả metric bảo vệ (guardrail).
- Lineage sinh từ code (dbt docs hoặc tương đương), không vẽ tay; mỗi metric truy ngược được tới bảng nguồn và cột.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Data contract có version, owner và SLA; CI chặn thay đổi phá vỡ
- [ ] Raw bất biến, phát lại được; pipeline idempotent
- [ ] dq tests (freshness, null, unique, accepted values, referential) pass trước khi publish
- [ ] Mỗi bảng mart có khóa chính, hạt được ghi rõ
- [ ] Metric mới có định nghĩa duy nhất trong `analytics` và có chủ sở hữu
- [ ] PII giả danh hóa; quyền truy cập theo vai trò
- [ ] Lineage sinh được từ code
- [ ] A/B có thiết kế ghi trước, có guardrail metric

## Ví dụ tốt
Event `order_placed` v2 thêm `coupon_code` optional (minor); contract cập nhật, consumer v1 vẫn chạy. `marts.orders_daily` hạt = (ngày, cửa hàng), test `unique(date, store_id)`, freshness ≤ 2h, publish qua bảng tạm rồi hoán đổi; metric `gmv` định nghĩa duy nhất trong `analytics`, lineage sinh từ dbt.

## Ví dụ xấu
Đổi kiểu `amount` từ int sang string trong event mà không tăng version; dashboard doanh thu về 0 và không ai biết cho tới cuối tháng; hai báo cáo cùng tên "doanh thu" cho hai con số khác nhau.
