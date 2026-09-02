# ADR-0014: Schema là nguồn sự thật cho event

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0001

## Bối cảnh
Bus chỉ kiểm bằng pydantic (8/18 topic có model) và danh sách `required`. Mọi enum, kiểu dữ liệu và ràng buộc
số trong 18 schema chưa từng được cưỡng chế: `release-events.env="prod"` hay `incidents.severity="SEV9"` đều lọt
qua. Hai nguồn mô tả cùng một event — schema và model — trôi khỏi nhau mà không ai phát hiện.

Truy vết nhân quả cũng phải dựa vào `key` và evidence dạng chuỗi, nên không nối được một chuỗi event về gốc.

## Quyết định
1. Bus validate **đủ** JSON Schema (Draft 2020-12) cho cả payload lẫn envelope, mọi topic. Schema là nguồn sự
   thật; pydantic chỉ là lớp tiện dụng cho code Python, không phải nơi định nghĩa hợp đồng.
2. `Envelope` thêm `schema_version`, `correlation_id`, `causation_id` (và `child()` để nối chuỗi nhân quả).
3. `tests/test_schema_consistency.py` khoá sự khớp: mọi topic có schema; trường pydantic tồn tại trong schema
   đúng tính nullable; `required` của schema là tập con của model; enum sai thật sự bị từ chối.

## Hệ quả
- Thêm hoặc đổi trường thì sửa schema trước, model sau; test consistency đỏ nếu chỉ sửa một bên.
- Đổi không tương thích ngược thì tăng `SCHEMA_VERSION`.
- Truy vết dùng `correlation_id`/`causation_id`, không dùng `key` để đoán quan hệ cha–con.
- Payload cũ vi phạm enum nay bị từ chối ngay tại bus thay vì trôi xuống consumer.
