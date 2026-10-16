# ADR-0060: vượt ngân sách đầu ra khi phiên agent ĐÃ XONG → giữ kết quả, để supervisor cắt và hỏi người

## Bối cảnh
`AgentRunner._loop` đo ngân sách theo token ĐẦU RA (`budget`, ghi chú 2026-09-04 trong `runner.py`): vượt thì ghi
`budget_exhausted` và ném `RunnerError` — kết quả của lượt bị bỏ, ticket tính một lần thử (`stop_kind`), việc dở
trong worktree được giữ thành WIP cho lượt sau.

Hàng rào đó đúng khi runner tự cầm vòng tool (gateway, mode `mcp` do runner điều khiển từng lượt): dừng ở lượt vượt
là ngăn được chi tiêu tiếp. Nhưng với backend chạy cả phiên agent trong MỘT lời gọi (`claude -p`, ADR-0023: tool
chạy bên trong tiến trình CLI, trả lời cuối ở lượt 1 với `tool_calls` rỗng), runner chỉ biết số output SAU KHI phiên
đã chạy xong. Token đã tiêu hết; bỏ kết quả không tiết kiệm được gì, chỉ buộc thêm một phiên mới đọc lại toàn bộ
ngữ cảnh.

Hub thật (QLKH-DD-CSV, 2026-10-12 → 16): 24 lượt `budget_exhausted` của builder, tổng **60,1M token**, không lượt nào
ra kết quả. Ví dụ DDCSV-117: output 79 191 > 75 000 (vượt 5,6 %), bỏ 4,2M token; DDCSV-103 vượt hai lần liên tiếp,
bỏ 7,7M. Audit `budget_exhausted` ghi `output_tokens = 0`, nên supervisor không thấy ticket chạm trần — ticket chỉ
bị giao lại, không ai được hỏi.

## Quyết định
1. **Phiên đã xong thì giữ kết quả.** Vượt `budget` ở lượt mà model trả lời CUỐI (không còn `tool_calls`): runner
   ghi audit `budget_overrun` (`output`, `budget`, `turn`; không mang token — token nằm ở audit `produced:*` của
   chính lượt này, không đếm hai lần) rồi đi tiếp như lượt bình thường: kiểm schema, publish.
2. **Còn định gọi tool thì vẫn dừng.** Vượt ở lượt model còn `tool_calls` → `budget_exhausted` + `RunnerError` như
   cũ: dừng lúc đó còn ngăn được chi tiêu.
3. **Ngữ nghĩa trần không đổi.** Audit `produced:*` mang output thật → `Supervisor._check_ticket` thấy `ratio ≥ 1` →
   `budget_cut` → ticket tạm dừng, gate `escalation` mở (đường sẵn có, `stop_kind` "budget": không tính retry).
   Người/reviewer duyệt = cấp thêm ngân sách (`budget.extended`) và kết quả đã có đi tiếp review; từ chối = đóng.
   Một lần quyết gate thay cho một phiên chạy lại.

## Phương án đã loại
- **Hệ số dung sai (nhận nếu output ≤ k × budget).** Thêm một con số phải chỉnh mà vẫn bỏ kết quả ở k + ε; trần
  của ticket đã có biên (`budget_tokens ≥ estimate × BUDGET_FACTOR`). Hỏi người qua `budget_cut` giữ một nguồn sự thật.
- **Truyền trần output cho `claude -p`.** CLI không có cờ trần token đầu ra theo phiên; `max_turns` đã là hàng rào số lượt.
- **Bỏ trần với backend CLI.** Mất tín hiệu "ticket ước lượng sai" mà `budget_cut` đang mang tới người.

## Hệ quả
- Lượt vượt trần ở phiên đã xong không còn bị giao lại; ticket dừng ở gate escalation với PR đã có. Hàng đợi chậm
  thêm một lần quyết gate (`reviewer:tu-dong` ký trước, ADR gốc 0034).
- `budget_exhausted` từ nay chỉ còn ở vòng tool do runner cầm.
- Test: `tests/test_ngan_sach_phien_da_xong.py` (hai chiều).
