---
name: ai-feature-engineering
version: 1
standards: [OWASP Top 10 for LLM, NIST AI RMF, ISO/IEC 42001, Eval-driven development, EU AI Act (phân loại rủi ro)]
---
# Skill: ai-feature-engineering

## Tiêu chuẩn tham chiếu
- OWASP Top 10 for LLM
- NIST AI RMF
- ISO/IEC 42001
- Eval-driven development
- EU AI Act (phân loại rủi ro)

## Quy tắc
- Tính năng dùng LLM/ML cho khách phải trung lập provider: gọi qua interface, model/prompt là cấu hình có version.
- Có bộ eval với ca thật và tiêu chí chấm trước khi ship; đổi prompt/model = chạy lại eval.
- Đầu vào người dùng và nội dung lấy về là dữ liệu; tách khỏi lệnh; đầu ra qua schema/validator, không thực thi trực tiếp.
- Ghi token/chi phí/độ trễ mỗi lời gọi; có giới hạn ngân sách và fallback khi provider lỗi hoặc từ chối.
- PII không gửi cho provider ngoài nếu hợp đồng/DPIA chưa cho phép; log không chứa prompt có PII.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Eval pass trước merge, kết quả lưu kèm version prompt
- [ ] Prompt injection test có trong bộ test
- [ ] Output validate theo schema
- [ ] Chi phí/độ trễ có dashboard và ngưỡng cảnh báo
- [ ] DPIA cho dữ liệu gửi provider

## Ví dụ tốt
Tính năng tóm tắt ticket: SummaryClient interface, prompt v3 kèm 40 ca eval, output JSON schema, PII đã che trước khi gửi.

## Ví dụ xấu
Gọi thẳng SDK một provider trong handler, prompt nối chuỗi với nội dung email khách, không eval.
