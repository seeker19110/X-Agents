# ADR-0021: Ticket thường chỉ một lượt review ở PR; reviewer và QA dùng tier standard

## Bối cảnh
Mô phỏng donghanhcungban (báo cáo 2026-09-02, mục 7): mỗi ticket 3 lượt review ở PR (reviewer, qa-debugger,
security-engineer), tất cả Opus. Finding của QA ở lượt PR trùng reviewer ở 6/6 ticket (`.pyc` commit nhầm, thiếu
maxLength, thiếu test nhánh) và phần lớn là nit; giá trị riêng của QA nằm ở hồi quy/perf/a11y trên staging.

## Quyết định
1. `required_reviews`: reviewer luôn; qa + security chỉ khi ticket có `risk_tags`. Route qa-debugger trên
   `pull-requests` có điều kiện `_needs_qa`. QA vẫn hồi quy mọi release trên staging (không đổi).
2. Reviewer với ticket thường là lượt kiểm thử duy nhất trước release: prompt yêu cầu chấm test theo Gherkin, ca biên,
   đường lỗi; thiếu là block.
3. `model_tier` của reviewer và qa-debugger: strong → standard. Security-engineer giữ strong (separation of duties,
   ADR-0003).

## Hệ quả
- Ticket thường: 2 lời gọi (engineer + reviewer) thay vì 4; ticket có risk_tags giữ 4.
- Kết hợp ADR-0020, ước tính ticket thường từ ~140k xuống ~45k token, phần lớn là engineer.
- Rủi ro: reviewer standard bỏ sót lỗi tinh → QA staging và gate release là lưới sau. Theo dõi `review_catch_rate`
  trong sprint_report; nếu giảm rõ thì nâng reviewer về strong trước khi mở lại QA ở PR.
