# ADR-0026: Trao đổi delivery bằng policy native, không sao chép authority

Ngày: 2026-09-26. Trạng thái: **Accepted** 2026-09-28; triển khai opt-in trong PR #353.
Chủ dự án giao phiên chính chốt các ADR mà mã đã merge, theo tiêu chí đơn giản + chất lượng.
Quyết định phạm vi được ghi trước khi viết mã trong feature spec của phiên này.
Đây là adapter dữ liệu bổ sung ADR-0018/0021, không thay execution kernel hay gate.

Consumer xuất DeliveryContract.model_json_schema và adopted_source; producer đóng gói
spec/plan theo policy; consumer kiểm pin độc lập, native schema, AC và spec artifact.
Không vendor validator/signature policy, không tự cài profile, không migrate run.
Không làm: vẫn nhập dữ liệu thủ công. Copy runtime: thêm nguồn lệch và quyền không cần thiết.
Chọn adapter offline vì lỗi metadata có đối chứng và ranh giới existing pipeline giữ nguyên.

Chi tiết, alternatives, test và trần: ../reports/2026-09-26-bidirectional-delivery-handoff.md.
Cách dùng: ../integrations/template-handoff.md.
