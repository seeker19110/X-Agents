# ADR-0019: Điều phối model theo gói tài khoản subscription, tier `light`

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
ADR-0005 làm công ty trung lập provider nhưng vẫn giả định **một** provider tại một thời điểm và trả tiền theo token.
Chủ dự án vận hành bằng các gói đăng ký đang có (Claude Pro/Max qua CLI, Google Antigravity qua `../gateway`, model
local), mỗi gói có hạn mức riêng và hết vào lúc khác nhau. Cần: (1) chạy được nhiều gói cùng lúc, tự chuyển khi một
gói hết hạn mức; (2) chia việc theo mức độ để gói mạnh không bị tiêu vào việc cơ học; (3) không đổi prompt, skill,
runner hay orchestrator.

## Quyết định
1. **Backend = gói tài khoản.** `llm.yaml` có `backends:` — danh sách cấu hình con (provider, models theo tier,
   base_url, api_key/api_key_env, effort, extra); khoá dùng chung (retries, prices, max_input_chars, budget_usd) thừa kế
   từ cấp trên. `COMPANY_LLM_BACKENDS=a,b` lọc/sắp lại khi chạy. Không có `backends:` → hành vi cũ, một backend.
2. **`RoutingClient` (`routing.py`)** bọc mọi backend thành một `ModelClient`: chọn theo `routing.prefer[tier]` rồi
   thứ tự khai báo; hết quota → nghỉ `cooldown_s` hoặc đúng Retry-After, đi backend kế; lỗi vận chuyển → nghỉ
   `transient_cooldown_s`; lỗi nội dung và từ chối → ném ra, không xoay. Mọi backend nghỉ → `TransientError` "thử lại
   sau Ns" để orchestrator hoãn event (ADR-0012), không tính lỗi agent. Ghi chú xoay đi qua `drain_retries()` → audit
   `llm_retry`.
3. **Provider `claude-code`**: CLI `claude -p --output-format json` như một backend không key; không hỗ trợ tool-use
   nên `RoutingClient` bỏ qua nó khi request có `tools` (khối kỹ thuật đi backend khác).
4. **Tier thứ ba `light`** cho việc cơ học/ngắn; `model_for` lùi light → standard → strong. Bảng agent → tier và lý do
   là `../../docs/DIEU-PHOI-MODEL.md` (nguồn sự thật chung của hub). Đổi tier chỉ cần `make golden`, không tăng
   `version` vì prompt không đổi.
5. **Xếp lại tier** theo tiêu chí độ sâu suy luận / hậu quả sai và lớp bắt lỗi phía sau / tần suất: intake, clarifier,
   supervisor → `light`; researcher, release-engineer, account-manager → `standard`; còn lại giữ.

## Hệ quả
- Chạy được bằng gói đăng ký, không cần key API; hết hạn mức một gói không dừng công ty.
- Trạng thái nghỉ của backend nằm trong tiến trình (orchestrator chạy dài); khởi động lại là thử lại từ đầu — chấp
  nhận vì backend hết quota sẽ báo lại ngay và bị nghỉ tiếp.
- Ghi bản ghi eval bằng gói nào thì `models` trong bản ghi ghi tên model đó; so sánh chất lượng giữa gói là việc của
  `evals` như trước.
- Bảng giá `prices` cần dòng giá 0 cho model của gói subscription để `report` không đếm là `unpriced`.
