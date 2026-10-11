# Kiến trúc

## Nguyên tắc

1. **Event-driven, không gọi trực tiếp**: agent chỉ nói chuyện qua topic. Mỗi topic có
   JSON Schema trong `topics/schemas/`, message không hợp lệ bị từ chối ở bus.
2. **Key = ticket ID**: mọi message thuộc một ticket đi cùng partition, giữ thứ tự.
3. **Blackboard có chủ**: `shared-context` chia theo namespace, mỗi namespace chỉ một
   agent được ghi (bảng trong `topics/README.md`). Ai cũng đọc được.
4. **Tính xác định ở đâu có thể**: lint, test, scan, build, đóng vòng review là code trả
   kết quả cứng; LLM chỉ diễn giải và quyết định bước tiếp theo.
5. **Hạn mức mọi nơi**: retry, timeout, token đều có ngưỡng; hết ngưỡng thì escalate
   chứ không âm thầm đi tiếp.
6. **Truy vết**: mọi artifact có `requirement_id` gốc; mọi hành động ghi `audit-log`.
7. **Prompt là code** (ADR-0004): agent/skill có version, đi qua PR, rollback bằng revert.
8. **Ước lượng trước khi làm** (skill cost-estimation): ticket không có `estimate_tokens`
   không được dispatch; budget = estimate × 1.5.
9. **Bảo mật đi trước code** (ADR-0003): threat model trước ticket đầu; ticket có
   `risk_tags` cần review của security, tách khỏi `qa`.

## Topic

Cột Consumer được test đối chiếu với `ROUTES` trong `orchestrator.py` (`tests/test_security_review_fixes.py`): agent có route
phải có mặt; agent được liệt kê mà không có route phải ghi `(chỉ đọc)`.

| Topic | Producer | Consumer | Key |
|-------|----------|----------|-----|
| research-requests | human / ops | product (pha `intake`) | project_id |
| research-findings | product (pha `intake`, `research`) | product (pha `research` khi `kind=intake`, pha `spec` khi `kind=researcher`) | project_id |
| requirements-draft | product (pha `spec`, kèm `risks`) | product (pha `intake`, sinh câu hỏi) | project_id |
| clarification-questions | product (pha `intake`) | human gate | project_id |
| clarification-answers | human gate | product (pha `intake` hỏi lại khi trả lời thiếu; pha `spec` khi đủ) | project_id |
| approved-specs | product (pha `spec`) → human gate `spec` | không có route trong `ROUTES`: security (threat model, `THREAT_ROUTE`), product (pha `plan`, `PLAN_INPUTS`), ops (chỉ đọc) | project_id |
| tasks | code (`delivery.py`, actor `delivery-lead`) từ lượt product[plan] | qa[author] (khi bật, ADR-0028), builder (pha = `stack`) | ticket_id |
| test-suites | qa[author] | builder (pha = `stack`) | ticket_id |
| pull-requests | builder | qa[review], security (khi risk_tags), qa[author] (khi có `test_dispute`) | ticket_id |
| review-results | qa (`source` = reviewer ở PR, qa ở hồi quy staging), security | code (`delivery.py`) gom đủ nguồn rồi mở release | ticket_id (hoặc release_id cho QA staging) |
| release-candidates | code (`delivery.py`, actor `delivery-lead`) | ops, security | release_id |
| release-events | ops (pha `deploy`) | code (`delivery.py`), qa[review] (staging), ops (pha `docs`, production), ops (pha `account`, chỉ đọc), human gate | release_id |
| incidents | ops (pha `docs`) | product (pha `plan` khi root_cause_class code/ops/design), ops (pha `docs`, → research-requests khi requirement) | incident_id |
| external-feedback | human (khách, người dùng) | ops (pha `docs`), ops (pha `account`) | project_id |
| change-requests | ops (pha `account`) | product (pha `plan` khi decision=pending hoặc accepted; pha `intake` khi accepted và đổi yêu cầu) | change_id |
| acceptance-results | ops (pha `account`) | code (`delivery.py`, đóng ticket của release), ops (pha `account`, → change-requests khi verdict conditional) | release_id |
| shared-context | theo namespace | tất cả | namespace |
| audit-log | tất cả | supervisor | actor |
| supervisor-actions | supervisor | tất cả | target |

## Vòng đời một ticket

```
product[plan]:      C4 L1–L2 + ADR lên `architecture`, contract lên `api-contract`, rồi chia ticket
delivery.py (CODE): tasks(ticket, assignee=builder, stack, estimate_tokens, risk_tags?) — actor `delivery-lead`
                    là vai của CODE đóng vòng (`roles.LEAD_ACTOR`), không phải agent
qa[author]:         (ADR-0028, khi bật) lượt MÙ từ acceptance → chỉ ghi file test → test-suites(ticket)
                    test ĐỎ ngay sau lượt này là kết quả đúng; xanh ngay → audit tests_green_before_code
builder[stack]:     đọc shared-context → code trên branch cho tới khi test xanh (KHÔNG ghi được file test)
                    → pull-requests(ticket, tests_authored_by, test_dispute?)
qa[author]:         PR có test_dispute → xem diff, sửa test hoặc bác bỏ → test-suites(blind=false)
qa[review]:         review-results(source=reviewer, verdict=pass|block, findings[], root_cause?) — MỌI ticket
security:  review-results(source=security) — chỉ khi ticket có risk_tags
delivery.py:        đủ review bắt buộc và tất cả pass → approved → release-candidates
                    có fail/block → tasks(ticket, retry+1, hint); retry ≥ 3 → blocked
                    ticket có depends_on chưa xong → waiting; tự dispatch theo priority khi phụ thuộc approved
ops[deploy]:        gộp branch → build/test/scan/sign → release-events(env=staging) → ticket merged
qa[review]:         hồi quy + perf + a11y trên staging → review-results(ticket_id=release_id, source=qa)
delivery.py:        QA staging pass → xin human gate release; fail → ticket quay lại với hint
ops[deploy]:        gate release approve → release-events(env=production) → ticket released; rolled_back → ticket quay lại
ops[account]:       UAT với khách → acceptance-results(accepted → closed | rejected → ticket quay lại | conditional)
supervisor:         retry > MAX_RETRY, token > budget, review quá 2h → supervisor-actions(warn, pause, escalate)
                    cùng mã nợ kiến trúc (DEF-xx/SD-xx/debt:) ≥ N review liên tiếp → gate escalation cấp dự án (ADR-0032)
```

Review bắt buộc: `{reviewer}` ∪ `{security nếu risk_tags}` — ADR-0037 gộp reviewer và qa-debugger thành một
lượt `qa[review]` chạy cho mọi PR, nên `qa` không còn là nguồn review "thêm"; code trong
`DeliveryLead.required_reviews`.

## Trạng thái ticket

`draft → (waiting) → dispatched → in_progress → in_review → changes_requested → approved → merged → released → closed`
cộng `blocked` và `escalated` có thể vào từ bất kỳ trạng thái nào.

## Human gate

Hai điểm bắt buộc trên đường công đoạn: `approved-specs` (gate `spec`, kèm điều kiện `runtime` — ADR-0031) và
release production (gate `release`, chỉ sau khi QA staging pass). Điểm thứ ba thuộc về khách: nghiệm thu
(`acceptance-results`, người ký của khách, ops pha `account` ghi nhận). Kế hoạch KHÔNG còn là gate (ADR-0037) —
`_check_plan` chặn bằng code; kẹt ở đâu thì mở gate `escalation`, nên `GateKind` chỉ còn bốn giá trị
`spec|release|acceptance|escalation`. Timeout 24h, supervisor nhắc ở 12h. Không bao giờ tự đi tiếp. Checklist trong
`gates/checklists.md`, tách hai nửa: "Code gửi kèm" (khoá trong `GateRequest.checklist`, hiện ở `gate_cli list`) và "Người tự
kiểm thêm". Nửa sau có **trợ lý kiểm duyệt** (`docs/dac-ta-tro-ly-kiem-duyet.md`): `gate_brief` (code, chỉ đọc) rút bằng chứng
định lượng thành hồ sơ `ok|gap|unknown`; subagent `sc-gate-<kind>` / `sc-<agent>` (sinh từ checklist và prompt agent, chỉ
Read/Grep/Glob) đọc hồ sơ và in bản tóm; người ký bằng `gate_cli` — `trusted_decision` chỉ tin actor là người.

## Thành phần dùng chung (đứng độc lập, không phụ thuộc repo khác)

- **Đo token**: mỗi agent phát `audit-log.tokens`; supervisor cộng dồn theo ticket
  (`Supervisor.budgets`). Không cần thư viện usage bên ngoài.
- **Workspace**: mỗi lượt `builder` làm trên branch `ticket/<id>` trong worktree riêng
  (`<repo>/.worktrees/<id>`); qa/security đọc diff thật của branch đó, và có tool chỉ đọc để tự chạy test.
- **Tool có ranh giới tin cậy** (ADR-0010, `tools.py`): bảng tool tên cố định (`read_file`, `write_file`,
  `list_files`, `search`, `run`), không có shell; `run` chỉ nhận tên trong allowlist (`lint`, `test`, `git_status`,
  `git_diff`); đường dẫn khoá trong worktree, không chạm `.git/` hay file bí mật; env lệnh con (lint/test, git, CLI model)
  lọc mọi biến trông như bí mật (`workspace.SECRET_ENV`), git không chạy hook của khách (`NO_HOOKS`).
  Vòng lặp model ↔ tool nằm trong runner (`generate(tools=…)`), dừng khi hết lượt hoặc vượt ngân sách token.
- **Nhánh tích hợp** (ADR-0011): ticket rẽ từ `company/integration`; RC xuất hiện → `merge --no-ff` vào đó trước khi
  ops (pha `deploy`) chạy; xung đột → RC huỷ, ticket làm lại trên nền mới. `main` của khách không bị chạm.
- **Giao hàng** (ADR-0027, `--deliver`): sha nhánh tích hợp lúc deploy staging được ghi `release.staged`; production duyệt +
  deploy → `Integration.deliver`: tag `v<version>` tại sha đó + fast-forward `company/release` (tạo nếu chưa có); tag trùng ở
  sha khác hay nhánh không fast-forward được → audit `delivery.tag_conflict` / `delivery.diverged`, không ghi đè. Rolled_back/
  failed → `rollback_delivery` lùi con trỏ về lần giao trước (chỉ khi nhánh còn trỏ đúng sha đã giao; tag giữ). `--push-remote`
  đẩy lên remote khách (lùi bằng `--force-with-lease`); push lỗi → `delivery.push_failed`, không chặn. `delivered` dựng lại từ
  `delivery.done`/`delivery.rolled_back`.
- **Bằng chứng PR do code điền**: sau vòng tool, runner chạy lint/test thật, commit và ghi đè `branch`, `pr_ref`,
  `local_checks` (`verified_by: workspace`), `impact.files` — model không tự khai được. Không có `--repo` thì
  `local_checks` thành `{"unverified": true}`.
- **Guardrail review**: `DeliveryLead.max_retries` (mặc định 3) là số lần làm một ticket (lần đầu + 2 lần làm lại):
  lead đặt `blocked` khi `retry + 1 ≥ max_retries` nên `retry` không bao giờ tới 3 qua lead. `Supervisor.max_retries`
  (cùng giá trị) là lớp chặn *phía sau*: chỉ bắt `tasks` có `retry ≥ 3` đến từ ngoài lead (publish tay, tiếp quản,
  lead cấu hình khác) — không phải hai guardrail cùng bắt một trường hợp.
- **Ticket bị bỏ** (người `reject` ở gate escalation): `closed` nhưng vào `DeliveryLead.abandoned`, KHÔNG thoả
  `depends_on` của ticket khác; ticket đang `waiting` vì nó chuyển `blocked` (mở gate escalation) thay vì được dispatch
  trên nền thiếu code. Audit `ticket.abandoned`, dựng lại khi mở lại. RC bị huỷ (`release.void`) không giữ ticket:
  khi gom release, ticket approved của RC huỷ vào RC kế tiếp (`DeliveryLead.void_release`).
- **Bus**: `InMemoryBus` cho test/demo (RLock, an toàn nhiều thread); đổi sang Redis Streams/Kafka bằng cách giữ nguyên
  interface `publish/subscribe/replay`.
- **Checkpoint**: LangGraph (tùy chọn, `graph.py`) — checkpointer do người triển khai chọn.
- **Blackboard + artifact store** (ADR-0012, `blackboard.py`): `shared-context.content` mang toàn văn artifact qua bus
  (nguồn sự thật), mirror ra `<db>.artifacts/<namespace>/v<n>.<ext>` + `latest.<ext>`. Agent chủ namespace bị schema
  bắt buộc trả `content`; agent hạ nguồn nhận toàn văn trong prompt (không chỉ `summary`).
- **Ngữ cảnh có hạn mức** (`context.py`): `max_input_chars` (mặc định 120 000, `llm.yaml`/`COMPANY_MAX_INPUT_CHARS`).
  Payload ưu tiên trước blackboard; chuỗi dài nhất bị cắt giữa có nhãn khi vượt; blackboard chia water-filling giữa
  các namespace. Audit `context_trimmed` khi có cắt. Lượt có tool đọc đủ phần bị cắt bằng `read_artifact` (ADR-0049).
- **Kết quả tool cũng là dữ liệu ngoài** (`guard.sanitize_tool_output`): `read_file`/`search`/`run` trả nội dung repo
  khách, nên đi qua đúng bộ lọc injection như web trước khi vào ngữ cảnh (cả vòng tool của runner lẫn cầu MCP); đoạn
  khớp bị thay nhãn và ghi audit `injection_sanitized`.
- **Tool web** thêm allowlist cổng (80/443, đổi bằng `COMPANY_WEB_PORTS`), tin endpoint tìm kiếm theo `host:port` chứ
  không theo host trần, và có hạn TỔNG thời gian tải (`TOTAL_TIMEOUT`) để server nhỏ giọt không giữ tool mãi.
- **Guard injection theo nguồn** (`guard.py`): payload từ agent nội bộ khớp mẫu → từ chối chạy; payload từ khách/người
  dùng/web hoặc trường không tin cậy (`diff`, `text`...) → thay đoạn khớp bằng nhãn, đi tiếp (`injection_sanitized`).
- **Retry lỗi transport** (`llm.py` `RetryingClient`): adapter phân loại lỗi mạng/429/5xx là `TransientError`, thử lại
  với backoff mũ; hết retry thì orchestrator hoãn event thay vì tính lỗi agent.
- **Ngân sách tiền**: `Pricing` (bảng `prices` trong `llm.yaml`) quy mỗi lượt gọi ra `audit-log.cost_usd`; supervisor
  cắt theo `Task.budget_usd` và pause cả dự án theo `budget_usd`.
- **Metrics** (`metrics.py`): tổng hợp từ `audit-log` theo agent/model/ticket/dự án, không cần hạ tầng ngoài; xuất
  Prometheus text qua `orchestrator metrics --prometheus`.

## Orchestrator (ADR-0007, ADR-0012)

`company.orchestrator` là vòng lặp nối các dòng trong bảng topic ở trên: mỗi event → tra `ROUTES` → gọi runner →
publish → event mới. Bảng route phải khớp front matter `reads`/`writes` (kiểm lúc khởi tạo). Hai chỗ vòng lặp dừng và
chờ người trên đường công đoạn: gate `spec` (`SPEC-<project>`) và gate `release` (`REL-xxx`, production); thứ ba là
chữ ký của khách ở gate `acceptance` (`UAT-<release_id>`). Kế hoạch KHÔNG có gate (ADR-0037): sau khi `product`
pha `plan` sinh ticket, `_check_plan` kiểm bằng code (kích thước ticket, estimate/budget, `risk_tags`, `depends_on`, threat
model, `architecture`/`api-contract` trên blackboard) — sạch thì `_dispatch_plan` giao ngay trong cùng lượt, có
`problems` thì `plan_rejected` + gate `escalation` cấp dự án. Guard vẫn nằm ở code: `DeliveryLead.dispatch` chỉ
nhận `plan_id` đã vào `lead.plans_ok`. Ticket bị supervisor pause/budget_cut/
escalate thì event của nó bị hoãn đến `resume`; sự kiện gặp lỗi transport (`TransientError`, sau khi đã hết retry)
cũng bị hoãn (`transient:`), tự thử lại mỗi `tick`. Đầu vào của người (`clarification-answers`, `acceptance-results`,
`change-requests` decision, `external-feedback`) đi qua `orchestrator publish` / `decide-change`; `comment`/`takeover`
cho người can thiệp trực tiếp vào một ticket đang chạy mà không cần đợi gate. Agent ghi blackboard bằng `context_writes`
(kèm toàn văn) trong đầu ra; threat model đi trước ticket đầu; ticket blocked hoặc bị escalate mở gate `escalation`
(approve = mở lại với hint, reject = đóng). `--workers N` chạy event của các ticket độc lập song song trong một tiến
trình (bus có lock; event đổi trạng thái chung luôn chạy một mình). Mỗi event xử lý xong ghi `audit-log`
action=orchestrated; mở lại bus SQLite thì replay dựng lại trạng thái và xếp hàng phần chưa xử lý.
