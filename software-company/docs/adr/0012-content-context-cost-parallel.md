# ADR-0012: Blackboard có toàn văn, ngữ cảnh có hạn mức, retry transport, ngân sách tiền, tool nghiên cứu, chạy song song, metrics, người can thiệp giữa vòng

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
Sau ADR-0011 công ty chạy được trọn vòng trên repo thật, nhưng một khảo sát lại toàn bộ chỉ ra tám khoảng trống:

1. **Blackboard chỉ là con trỏ rỗng.** `shared-context` giữ `content_ref` + `summary`; PRD, C4, OpenAPI, threat model
   không được viết ra đâu cả. Backend, reviewer, QA chỉ thấy vài dòng tóm tắt do model tự viết. Chuỗi "spec → plan →
   code" đúng về hình thức, sai về nội dung.
2. **Không quản lý cửa sổ ngữ cảnh.** Prompt = toàn bộ payload + toàn bộ blackboard + diff 20k ký tự, không giới hạn.
3. **Chống injection mỏng** (5 chuỗi cố định) và sai chính sách: phản hồi của khách chứa lệnh thì bị từ chối xử lý,
   trong khi đó chính là việc phải làm.
4. **Không retry lỗi tạm thời.** 429/5xx/mất mạng bị tính là lỗi agent, đốt lượt retry của ticket, đẩy lên gate oan.
5. **Chỉ đo token, không đo tiền.** Token của model mạnh và model rẻ khác giá nhiều lần.
6. **Khối nghiên cứu không có tool**: researcher "nghiên cứu codebase" mà không đọc được repo, "nghiên cứu công nghệ"
   mà không có web.
7. **Tuần tự một tiến trình** dù ticket độc lập; **quan sát chỉ có audit-log** thô.
8. **Người chỉ can thiệp được ở gate**: không chèn nhận xét vào ticket đang chạy, không sửa tay rồi cho chạy tiếp.

## Quyết định
1. **Blackboard mang toàn văn** (`events.SharedContext.content`, `blackboard.py`). Bus vẫn là nguồn sự thật (replay dựng
   lại được); artifact store `<db>.artifacts/<namespace>/v<n>.<ext>` + `latest.<ext>` là bản mirror cho người đọc/diff
   (`--artifacts`, `orchestrator show <namespace>`). Agent sở hữu namespace phải trả `context_writes[].content`
   (schema structured output bắt buộc `content`); thiếu thì vẫn ghi con trỏ nhưng audit `context_no_content`.
   Agent hạ nguồn nhận `content` thật trong prompt.
2. **Ngữ cảnh có hạn mức** (`context.py`, `max_input_chars` trong llm.yaml / `COMPANY_MAX_INPUT_CHARS`, mặc định
   120 000 ký tự). Thứ tự: system prompt cố định → payload ưu tiên (chuỗi dài nhất bị cắt giữa, giữ đầu/cuối, có nhãn)
   → blackboard chia water-filling (namespace ngắn giữ nguyên, phần thừa nhường namespace dài; nhãn cắt chỉ đường dẫn
   artifact để đọc thêm). Có cắt → audit `context_trimmed` kèm số liệu.
3. **Guard injection theo nguồn** (`guard.py`): regex đa ngôn ngữ (bỏ qua hướng dẫn, đổi vai, giả khung hội thoại, đòi
   lộ prompt, ra lệnh tool). Nguồn nội bộ (agent phát) khớp → từ chối như trước. Nguồn ngoài (khách, người dùng, web)
   và trường không tin cậy (`diff`, `text`...) → thay đoạn khớp bằng `[đã lọc: nghi prompt injection]`, đi tiếp, audit
   `injection_sanitized`. Nội dung web luôn qua bộ lọc và mang nhãn "DỮ LIỆU KHÔNG TIN CẬY".
4. **Retry lỗi transport, không retry lỗi nội dung** (`llm.py`). Adapter phân loại `TransientError` (mạng, 408/409/425/
   429/5xx/529); `RetryingClient` thử lại với backoff mũ + jitter (`retries`, `retry_base`); runner audit `llm_retry`.
   Hết retry → orchestrator **hoãn** event (`transient:<agent>`), nhịp `tick` sau thử lại, agent đã xong trên cùng
   event không chạy lại (`partial`), `stats.transient` tách khỏi `stats.errors`.
5. **Ngân sách tiền** (`Pricing`, `AuditLog.cost_usd`, `Task.budget_usd`, `Supervisor.project_budget_usd`). Bảng
   `prices` trong llm.yaml (USD/1M token, khớp tiền tố tên model, có giá cache). Mỗi lượt sản xuất ghi `cost_usd`;
   supervisor warn 80% / cắt 100% theo ticket (USD) và **pause cả dự án** khi chạm `budget_usd`; orchestrator hoãn
   mọi event của dự án bị pause. Lời gọi không có giá đếm ở `unpriced_calls` — không ai được tưởng là miễn phí.
   `sprint_report` thêm `cost_by_agent`, `cost_by_model`, `project_cost_usd`.
6. **Tool cho researcher** (`web.py`, route `tools="research"`): `WorkspaceTools` chỉ đọc trên repo khách (`--repo`),
   không `run`, không ghi; `web_search` + `fetch_url` khi `--web` (tắt mặc định — mạng ra ngoài là quyết định của người
   vận hành). Chỉ http/https công khai, chặn host nội bộ/loopback, cắt 2 MB, bóc HTML; máy tìm kiếm cấu hình qua
   `COMPANY_SEARCH_URL` (SearXNG hay endpoint JSON bất kỳ), mặc định DuckDuckGo HTML. Mọi URL đã lấy vào audit
   `tools_used.urls` để truy nguồn.
7. **Chạy song song trong một tiến trình** (`--workers N`): bus giữ RLock (SQLite `check_same_thread=False`), phần xác
   định (delivery-lead, supervisor, gate) vẫn tuần tự trong subscriber; orchestrator lấy lô event khác key chạy trong
   thread pool. Event đổi trạng thái chung (gate decide, lập kế hoạch, RC/merge tích hợp, clarifier) luôn chạy một mình.
   Bus nhiều tiến trình (Redis/Kafka) vẫn để sau; interface không đổi.
8. **Metrics từ bus** (`metrics.py`, `orchestrator metrics [--prometheus]`): gọi/token/USD/thời gian/cache hit/tool theo
   agent, model, ticket, dự án; sự kiện sức khoẻ; thời gian chờ gate; lead time ticket. Xuất Prometheus text để nối
   dashboard sẵn có. Nguồn là evidence JSON của audit `produced:*` (model, duration_ms, cache_hit, turns, tool_calls).
9. **Người can thiệp giữa vòng**: `orchestrator comment <ticket> --by human:x --text` → delivery-lead phát lại task
   với hint, **không tính retry**; `orchestrator takeover <ticket> --by human:x` → người đã sửa tay trong worktree
   `ticket/<id>`, code chạy lint/test thật, commit, publish `pull-requests` dưới tên người (`verified_by: workspace`);
   ticket đang `in_review` thì PR của người thay PR của agent và vòng review làm lại. Không cần đợi gate escalation.

## Hệ quả
- Prompt của agent không đổi (golden giữ nguyên): yêu cầu `content`, mô tả tool, nhãn cắt đều nằm ở user message do
  runner ghép. Bản ghi eval (khi có) sẽ lệch vì user message đổi — đúng như ADR-0010 đòi hỏi.
- Chi phí token tăng ở agent hạ nguồn vì nhận toàn văn artifact; đổi lại code viết theo PRD/contract thật. Hạn mức
  `max_input_chars` là van điều tiết.
- `--workers` > 1 làm xung đột tích hợp (ADR-0011) dễ xảy ra hơn; chiến lược "làm lại trên nền mới" giữ nguyên.
- Chưa có: bản ghi eval bằng model thật (cần người có model chạy `make eval-record`); sandbox tiến trình cho `run`;
  giao diện gate ngoài CLI và thông báo; bus nhiều tiến trình; release-engineer đẩy nhánh tích hợp lên `main`.
