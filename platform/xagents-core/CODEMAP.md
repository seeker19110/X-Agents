# CODEMAP.md — xagents-core: muốn đổi X thì sửa ở đâu

Module trong `src/xagents_core/` không phân thư mục con; mỗi module có tên trong bảng dưới (cổng
`platform/console/tests/test_cong_tai_lieu.py` đỏ khi thêm module mà quên dòng ở đây). Mỗi module có docstring đầu
file giải thích "vì sao" — CODEMAP này trỏ tới đúng chỗ đọc, không diễn giải lại nội dung docstring.

| Muốn | Sửa | Kiểm |
|---|---|---|
| Bus sự kiện: ACL topic, validate schema, publish | `InMemoryBus` (`bus.py`) — `_extra_publish_checks` là hook mở duy nhất cho luật riêng công ty | `tests/test_bus.py` |
| Bus bền vững trên đĩa | `SQLiteBus` (`sqlite_bus.py`) — `RLock` nguyên tử publish+ghi+notify, `Lease` khoá hai tiến trình | `tests/test_sqlite_bus.py` |
| Vòng lặp gọi model của một agent | `AgentRunner` (`runner.py`) — giữ NGUYÊN VĂN từng byte prompt (khoá bản ghi eval = `hash(system, user)`) | `tests/test_runner.py` |
| Client LLM (Claude CLI, OpenAI-compatible) | `llm.py` — `ClaudeCodeClient`, `OpenAICompatClient`, `LLMError`/`TransientError`, `Completion` | `tests/test_llm.py` |
| Xoay nhiều backend theo tier/quota | `RoutingClient` (`routing.py`) — `routing.prefer[tier]`; quota → `cooldown_s`; lỗi mạng/5xx → `transient_cooldown_s`; lỗi nội dung ném thẳng | `tests/test_routing.py` |
| Chống prompt injection | `guard.py` — cơ chế (mẫu, chuẩn hoá, quét) ở đây; CHÍNH SÁCH theo topic ở `CoreConfig` của công ty | `tests/test_guard.py` |
| Human gate: four-eyes, hạn, allowlist | `GateRequest`/`HumanGate`/`approvers()` (`gates.py`) | `tests/test_gates.py` |
| Gate bền vững + xác thực actor | `PersistentGate`/`trusted_decision` (`gate_cli.py`) — allowlist mặc định TỪ CHỐI, dựa `env.actor` | `tests/test_gate_cli.py` |
| Blackboard (tri thức chung `shared-context`) | `blackboard.py` — giữ version lớn nhất/namespace, phân vùng `project_id` (ADR-0018) | `tests/test_blackboard.py` |
| Cắt ngữ cảnh theo ngân sách token | `context.py` (ADR-0012) — system trừ trước, payload cắt-giữa có nhãn, blackboard water-filling | `tests/test_context.py` |
| Nạp agent/skill từ đĩa | `load_agents`/`load_skill` (`registry.py`) — `check_owners` mặc định `True` (ADR-0008: mọi skill phải có agent nạp) | `tests/test_registry.py` |
| Khung event chung (5 lớp) | `Envelope`/`SharedContext`/`AuditLog`/`SupervisorAction`/`can_transition` (`events.py`) — lớp con công ty thu hẹp Literal | `tests/test_events.py` |
| Nơi core biết một công ty ở đâu | `CoreConfig`/`TopicACL` (`config.py`) — ADR-0001 §2, chỗ DUY NHẤT | `tests/test_config.py` |
| Sandbox tiến trình con | `SubprocessSandbox`/`ContainerSandbox` (`sandbox.py`, ADR-0035/0010) — fail-closed, mạng tắt mặc định | `tests/test_sandbox.py` |
| Span quan sát được | `observe.py` (ADR-0009) — 3 ranh giới: `runner.step`, `llm.complete`, `tool.call`; `sink=None` phải no-op tuyệt đối | `tests/test_observe.py` |
| Dòng thời gian một chủ thể từ audit-log | `trace.py` — `base_row`/`audit_row`/`_gop_lap`/`summarize`/`render`; core không biết tên topic | `tests/test_trace.py` |
| Ghi/phát lại eval prompt | `evals.py` (K3.6c) — `prompt_key`, `RecordingClient`/`ReplayClient`, `stale_recordings` | `tests/test_evals.py` |
| Cơ chế chung supervisor | `Budget`/`_act_once`/`escalate_gate`/`debt_table` (`supervisor.py`, ADR-0032) — `_act` là điểm trừu tượng cho lớp con | `tests/test_supervisor.py` |
| Khung tool có ranh giới tin cậy | `tools.py` (ADR-0007/0010) — tool tự kiểm tham số, lỗi trả CHUỖI cho model | `tests/test_tools.py` |
| Hình dạng chung "việc có ngân sách" | `Budgeted` — `Protocol`, không phải lớp cha (`ticket_model.py`) | — |
| Kernel thi hành bền: contract, DAG, biên nhận bằng chứng, journal | `execution.py` (ADR gốc 0017) — `RunSpec`/`TaskSpec`, `apply_event`, `EvidenceReceipt`, `ExecutionJournal` (SQLite append-only, replay được); không biết company/ticket/gate/model | `tests/test_execution*.py` (4 file: lõi, nguyên tử, khởi tạo, mở lại) |

Ai import gì (đo 2026-09-28, đếm file `*.py` trong `src/` có dòng `from xagents_core`/`import xagents_core`):
`companies/software-company` 27 file, `companies/keeper` 15 file, `platform/console` 3 file, `platform/gateway` 0
file. Sửa bất kỳ module nào ở đây, chạy lại test của **cả hai công ty và console** (`scripts/dev-task.sh gate
all`), không chỉ `platform/xagents-core/tests/`.
