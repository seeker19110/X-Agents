# ADR-0005: Runner trung lập provider, bus bền vững SQLite, gate qua audit-log

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
Đến ADR-0004 toàn bộ công ty là tài liệu + logic xác định; chưa agent nào gọi model. Cần một lớp chạy thật nhưng
không được khóa công ty vào một model hay một nhà cung cấp: đội có thể chạy model local (Ollama, vLLM), API thương mại
(Anthropic, OpenAI, Groq...) hoặc đổi model theo tier mà không sửa prompt, skill, schema hay code điều phối.

## Quyết định
1. **Một interface `ModelClient`** (`llm.py`): `complete(system, user, schema, model_tier) → Completion(text, tokens, model)`.
   Runner, eval và mọi code khác chỉ phụ thuộc interface này.
2. **Adapter theo provider, chọn bằng cấu hình** (`llm.yaml` hoặc `COMPANY_LLM_*`): `anthropic` (SDK chính thức),
   `openai` (mọi server OpenAI-compatible, không cần SDK), `fake` (test/eval offline). Thêm provider = thêm một class,
   không chạm runner.
3. **Model theo tier, không theo tên**: front matter agent chỉ nói `strong`/`standard`; tên model nằm trong cấu hình.
4. **Đầu ra ép theo JSON Schema của topic** (`topics/schemas/*.json`), bằng structured output nếu provider hỗ trợ,
   ngược lại lùi về JSON-mode + schema nhúng trong prompt. Bus validate lần nữa; đầu ra sai bị từ chối và ghi audit.
5. **Token là số thật** từ `usage` của provider, ghi vào `audit-log.tokens`; supervisor dùng nó để warn/cut.
6. **Bus bền vững = SQLite** (`sqlite_bus.py`), giữ nguyên interface `InMemoryBus`; ghi đĩa trước khi báo subscriber.
7. **Human gate không có kho riêng**: request/decision là bản ghi `audit-log` (`gate.request`/`gate.decide`);
   `PersistentGate` dựng lại trạng thái từ replay. CLI `company.gate_cli` cho con người duyệt.
8. **Workspace theo ticket = git worktree** (`workspace.py`), lint/test chạy thật, kết quả đưa vào `local_checks`.
9. **Eval prompt** (`evals/<agent>.yaml`, `company.evals`): ca đầu vào + tiêu chí chấm xác định; chạy với provider nào
   cũng được; test suite chạy offline bằng `FakeClient`.

## Hệ quả
- Đổi model/provider là việc cấu hình, không phải PR code; eval chạy lại để so chất lượng giữa model.
- Model không hỗ trợ structured output vẫn dùng được, nhưng tỷ lệ `invalid_output` sẽ cao hơn; supervisor thấy qua audit.
- Runner không retry; retry thuộc delivery-lead (hint) và supervisor (hạn mức) như trước.
- Chưa có: vòng lặp tự động nối topic → agent (hiện chạy từng bước bằng CLI hoặc code), Kafka/Redis, giao diện web cho gate.
