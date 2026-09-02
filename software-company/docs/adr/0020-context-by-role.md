# ADR-0020: Blackboard theo vai trò và trần prompt theo agent

## Bối cảnh
Mô phỏng donghanhcungban với model thật (báo cáo 2026-09-02, mục 7): mỗi lời gọi mang toàn văn blackboard (~75k ký tự:
PRD 25k, threat model 29k, architecture, docs, api-contract) cộng system prompt 14–37k ký tự. Một ticket = 1 lượt engineer
+ 3 lượt review, mỗi lượt review ~35k token, trong đó ~25k là blackboard mà reviewer/QA gần như không dùng
(reviewer chấm diff theo PRD và contract; QA không cần threat model; security không cần docs). Thực tế 95–170k token/ticket
so với ước lượng 30–55k.

## Quyết định
1. Front matter agent có `context_namespace_read: [..]`. Chỉ namespace trong danh sách (cộng namespace agent sở hữu)
   mang `content` toàn văn; namespace khác chỉ còn `summary`, `content_ref`, `content_omitted`. Không khai báo (`None`)
   = đọc mọi thứ như trước. Agent có tool đọc repo vẫn mở được tệp artifact qua `path` khi cần.
2. Front matter có `max_input_chars`, trần riêng thấp hơn (không vượt) trần toàn cục của llm.yaml: review/QA/ops thấp (30–70k), engineer 100k,
   research/spec/delivery-lead giữ trần chung. `context.fit` cắt có nhãn như cũ.

## Hệ quả
- Lượt review giảm ~60% ký tự đầu vào; ước tính ticket 4 lượt từ ~140k xuống ~70k token.
- Agent thiếu ngữ cảnh sẽ thấy `content_omitted` và biết phải hỏi qua topic hoặc đọc tệp, không đoán.
- Việc tiếp: đặt blackboard vào phần được cache (system block) khi chạy API thật; gộp reviewer + QA khi ticket không
  có `risk_tags`; hạ tier reviewer/QA.
