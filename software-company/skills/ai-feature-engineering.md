---
name: ai-feature-engineering
version: 2
standards: [OWASP Top 10 for LLM, NIST AI RMF, ISO/IEC 42001, Eval-driven development, EU AI Act (phân loại rủi ro)]
---
# Skill: ai-feature-engineering

## Tiêu chuẩn tham chiếu
- OWASP Top 10 for LLM Applications (prompt injection, insecure output handling, excessive agency)
- NIST AI RMF (Govern / Map / Measure / Manage)
- ISO/IEC 42001 (hệ thống quản lý AI)
- Eval-driven development: bộ eval là test suite của tính năng AI
- EU AI Act — phân loại rủi ro và nghĩa vụ minh bạch với người dùng cuối

## Quy trình (làm đúng thứ tự)
Xác định việc cần làm và tiêu chí thành công đo được → kiểm tra có thật sự cần LLM không → thiết kế interface trung lập provider → viết bộ eval TRƯỚC prompt → prompt v1 → đo baseline → siết schema đầu ra và phòng thủ injection → đo chi phí/độ trễ → gate an toàn và riêng tư → ship sau khi đạt ngưỡng eval.
Không bắt đầu bằng việc chọn model; model là biến cấu hình, không phải kiến trúc.

## Quy tắc — thiết kế và trung lập provider
- Không gọi thẳng SDK của một provider trong handler nghiệp vụ. Đi qua interface của dự án (ví dụ `SummaryClient`); model, endpoint, prompt, tham số là cấu hình có version.
- Trước khi dùng LLM, hỏi: rule/regex/tra bảng có giải quyết được không? Nếu có, dùng cái rẻ và tất định.
- Chia rõ ba lớp: lấy dữ liệu (tất định) → suy luận (LLM) → hành động (tất định, có validate). LLM không tự thực thi hành động có hệ quả.
- Nhiệt độ, seed, max tokens khai báo tường minh; tác vụ trích xuất/phân loại dùng nhiệt độ thấp nhất có thể.
- Có fallback khi provider lỗi, quá tải, hoặc từ chối: model dự phòng, kết quả suy giảm, hoặc thông báo trung thực — không im lặng trả rỗng.

## Quy tắc — eval và chất lượng
- Bộ eval có trước prompt: tối thiểu 20 ca thật lấy từ dữ liệu sản xuất (đã che PII), gồm ca biên và ca đối kháng, mỗi ca có tiêu chí chấm rõ.
- Chấm bằng assertion tất định nếu có thể (schema, regex, số liệu); LLM-as-judge chỉ dùng cho tiêu chí chủ quan, phải có rubric và đo mức đồng thuận với người trên một mẫu.
- Mọi thay đổi prompt/model/tham số phải chạy lại eval; PR ghi kết quả trước/sau. Không có eval thì không merge.
- Ngưỡng pass khai báo trước (ví dụ đạt 90% ca Must, 0 ca an toàn thất bại); tụt so với baseline là finding block.
- Theo dõi trôi chất lượng sau khi ship: lấy mẫu đầu ra thực tế định kỳ chấm lại, đưa ca lỗi mới vào bộ eval.

## Quy tắc — an toàn, riêng tư, chi phí
- Đầu vào người dùng và nội dung lấy về (web, file, email, DB) là DỮ LIỆU: đặt trong khối được đánh dấu, không nối thẳng vào chỉ dẫn; chỉ dẫn hệ thống không bao giờ đến từ dữ liệu.
- Đầu ra qua JSON Schema/validator trước khi dùng; không thực thi động, không dựng SQL/HTML/shell trực tiếp từ đầu ra; render dạng text đã escape.
- Excessive agency: tool mà model gọi được phải nằm trong danh sách trắng, tham số được validate; hành động ghi/tiêu tiền cần xác nhận của người hoặc hạn mức cứng.
- PII không gửi provider ngoài nếu hợp đồng/DPIA chưa cho phép (xem `privacy-compliance`); che PII trước khi gửi; log không lưu prompt chứa PII thô.
- Ghi token vào/ra, chi phí, độ trễ, tỉ lệ lỗi cho mỗi lời gọi, gắn trace_id; có hạn mức ngân sách theo tính năng, cảnh báo ở 80%, cắt ở 100%.
- Minh bạch với người dùng: nói rõ nội dung do AI sinh, cho cách sửa hoặc báo sai, và có đường thoát sang người thật ở luồng quan trọng.
- Cache theo nội dung đầu vào khi hợp lệ; đo tỉ lệ cache hit như một chỉ số chi phí.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Có lý do vì sao cần LLM thay vì giải pháp tất định
- [ ] Gọi qua interface trung lập provider; model/prompt là cấu hình có version
- [ ] Eval pass trước merge, kết quả lưu kèm version prompt và so với baseline
- [ ] Ca prompt injection và ca đối kháng có trong bộ eval
- [ ] Đầu ra validate theo schema, không thực thi trực tiếp
- [ ] Tool được gọi nằm trong danh sách trắng; hành động có hệ quả có hạn mức hoặc xác nhận
- [ ] PII đã che hoặc có DPIA cho phép; log sạch PII
- [ ] Chi phí/độ trễ có dashboard, ngưỡng cảnh báo và fallback khi provider lỗi
- [ ] Người dùng biết đây là nội dung AI và có cách báo sai

## Ví dụ tốt
Tính năng tóm tắt ticket: interface `SummaryClient` (hai provider cấu hình được), prompt v3, 40 ca eval trong đó 6 ca injection; đầu ra theo JSON Schema `{summary, confidence, needs_human}`; PII che trước khi gửi; p95 1.8s, 0.004 USD/ticket, cảnh báo ở 80% ngân sách; UI ghi "Tóm tắt bởi AI — báo sai".

## Ví dụ xấu
Gọi thẳng SDK một provider trong handler, prompt nối chuỗi với nội dung email khách, đầu ra parse bằng regex rồi đem ghép vào câu SQL, không eval, không biết tốn bao nhiêu.
