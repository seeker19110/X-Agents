---
name: api-contract
version: 2
standards: [OpenAPI 3.1, AsyncAPI 3.0, RFC 9110, RFC 9457, SemVer, JSON Schema 2020-12]
---
# Skill: api-contract

## Tiêu chuẩn tham chiếu
- OpenAPI 3.1 cho API đồng bộ; AsyncAPI 3.0 cho event (xem `event-driven-architecture`)
- RFC 9110 (ngữ nghĩa HTTP: phương thức, mã trạng thái, điều kiện, caching)
- RFC 9457 Problem Details cho mọi lỗi
- SemVer cho version của contract
- JSON Schema 2020-12 cho kiểu dữ liệu; RFC 3339 cho thời gian

## Quy trình (làm đúng thứ tự)
Xác định tài nguyên và ca dùng → viết contract (OpenAPI) và đặt lên blackboard namespace `api-contract` → sinh ví dụ request/response cho mọi mã trạng thái → consumer và producer cùng duyệt → sinh mock từ contract để hai bên làm song song → sinh code/client từ contract → contract test trong CI → chỉ khi đó mới hiện thực logic.
Contract viết trước code. Code không bao giờ là nguồn sự thật của contract.

## Quy tắc — thiết kế
- Tài nguyên là danh từ số nhiều, phân cấp rõ (`/orders/{id}/refunds`); động từ nằm ở phương thức HTTP, không nằm trong URL.
- Dùng đúng ngữ nghĩa: GET an toàn và có thể cache, PUT/DELETE idempotent, POST cho tạo và cho hành động không idempotent (kèm Idempotency-Key, xem `backend`), PATCH có định dạng khai báo rõ (merge-patch hay JSON Patch).
- Mã trạng thái đúng nghĩa: 201 kèm `Location`, 202 cho xử lý bất đồng bộ kèm cách theo dõi, 409 cho xung đột trạng thái, 422 cho lỗi ngữ nghĩa, 429 kèm `Retry-After`.
- Phân trang chuẩn hóa một kiểu cho toàn hệ thống (ưu tiên cursor cho danh sách lớn), kèm `limit` mặc định và tối đa; sắp xếp và lọc khai báo tường minh, không truyền SQL.
- Thời gian là RFC 3339 UTC có offset; tiền tệ là số nguyên đơn vị nhỏ nhất kèm mã ISO 4217; định danh là string, không phơi số tự tăng nếu đoán được là rủi ro.
- Trường mới phải optional; không đổi nghĩa trường cũ; không tái dùng tên đã bỏ. Enum có giá trị dự phòng cho client cũ.

## Quy tắc — lỗi và bảo mật
- Mọi lỗi theo Problem Details: `type` (URI ổn định), `title`, `status`, `detail` (nói được người dùng làm gì tiếp), `instance`, và trường mở rộng như `errors[]` cho lỗi từng field.
- `type` là hợp đồng: client bắt lỗi theo `type`, không theo chuỗi `detail`. Không đưa stack trace, tên bảng, hay dữ liệu nội bộ vào `detail`.
- Contract khai báo authn/authz cho từng operation (scope/role), rate limit, và kích thước tối đa của request.
- Trường nhạy cảm đánh dấu rõ trong schema để hạ nguồn biết che khi log (xem `privacy-compliance`).

## Quy tắc — version và vòng đời
- Breaking change (bỏ/đổi kiểu trường, siết validate, đổi mã trạng thái, đổi ngữ nghĩa) là major và cần đường dẫn/version mới; thêm optional là minor.
- Deprecate có quy trình: đánh dấu trong OpenAPI, trả header `Deprecation` và `Sunset`, thông báo consumer, giữ tối thiểu một chu kỳ phát hành trước khi gỡ.
- Contract test (ví dụ Pact hoặc kiểm schema hai chiều) chạy trong CI; CI chặn merge khi diff contract là breaking mà version không tăng.
- Mỗi operation có ít nhất một ví dụ thành công và một ví dụ lỗi, dùng luôn cho tài liệu và cho mock.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Contract có trước code và nằm trong namespace `api-contract`
- [ ] Mọi operation có schema request/response/error và ví dụ cho từng mã
- [ ] Lỗi theo RFC 9457, có `type` ổn định, không lộ nội bộ
- [ ] Phương thức, mã trạng thái, phân trang đúng chuẩn và nhất quán toàn hệ thống
- [ ] Diff contract được kiểm; breaking change đi kèm tăng major và kế hoạch deprecate
- [ ] Contract test pass trong CI cho mọi consumer đã biết
- [ ] Authn/authz, rate limit, giới hạn kích thước khai báo trong contract

## Ví dụ tốt
`PUT /orders/{id}` → `200 Order` | `409 application/problem+json` với `type: https://api.example.com/problems/order-locked`, `detail: "Đơn đang xử lý, thử lại sau 30 giây"`; thêm trường `coupon_code` optional → 1.3.0; contract test của client web và mobile pass.

## Ví dụ xấu
Trả `200 {error: "something wrong"}`; đổi `amount` từ số sang chuỗi trong bản vá; endpoint `/getOrderById?id=5`; tài liệu viết tay sau khi code xong và đã lệch.
