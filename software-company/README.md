# Software Company — Multi-Agent phòng gia công phần mềm

Mô phỏng một công ty gia công phần mềm bằng hệ đa agent event-driven: 7 khối, 20 agent,
mọi trao đổi đi qua topic có key, tri thức chung nằm trên blackboard, con người duyệt ở
4 điểm cố định. Nguyên tắc: tính toán xác định, guardrail có hạn mức, đo token thật,
cô lập workspace theo ticket, prompt là code. Đây là "công ty AI" đầu tiên trong hub X-Agents.

## Các khối

| # | Khối | Agent | Vai trò |
|---|------|-------|---------|
| 1 | Nghiên cứu yêu cầu | intake, researcher (domain + UX + codebase + tech), synthesizer, risk, clarifier, spec-writer | Biến ý tưởng thô thành PRD có tiêu chí nghiệm thu + UX flow |
| 2 | Quản lý dự án | delivery-lead | Kiến trúc, ước lượng, chia ticket, điều phối, đóng vòng |
| 3 | Kỹ thuật | backend, frontend, mobile, database, platform, data | Code / hạ tầng / dữ liệu trên branch riêng theo contract |
| 4 | Chất lượng | reviewer, qa-debugger, security-engineer | Review; test + tìm nguyên nhân; threat model, DAST, license, PII |
| 5 | Vận hành | release-engineer, support-docs, account-manager | Merge, staging, deploy; tài liệu, incident; SOW, UAT, change request, nghiệm thu |
| 6 | Giám sát | supervisor | Watchdog, ngân sách token, knowledge base, version prompt |
| 7 | Human gate | (con người) | Duyệt spec, plan, release; ký rủi ro/license/PII; khách ký nghiệm thu |

## Luồng chính

```
research-requests → approved-specs → tasks (depends_on/priority) → pull-requests
      → review-results (reviewer + qa [+ security khi risk_tags]) → release-candidates
      → release-events(staging) → review-results(QA hồi quy) → gate 3 → release-events(production)
      → acceptance-results (khách ký) → closed
      → incidents (root_cause_class) → tasks | research-requests;  change-requests → intake/delivery-lead
+ shared-context (blackboard 12 namespace, phân vùng theo dự án)   + audit-log (mọi hành động)
```

## Cấu trúc

```
docs/          kiến trúc, tiêu chuẩn, ADR (0001–0019)
agents/        system prompt từng agent (có version), nhóm theo khối
skills/        45 skill (có version): rule + checklist + ví dụ, theo tiêu chuẩn ngành;
               nạp hai mức — đầy đủ cho agent chủ quản, rút gọn (quy trình + checklist) cho agent tuân thủ (ADR-0008)
gates/         checklist human gate
templates/     PRD, ticket, PR, bug report, postmortem, ADR, threat model, data contract
topics/        18 JSON Schema topic + bảng owner namespace
src/company/   events, bus, sqlite_bus, registry, delivery, supervisor, gates, gate_cli, blackboard (artifact store),
               llm (ModelClient + adapter anthropic/openai/claude-code, tool-use, retry, bảng giá), routing (nhiều gói tài
               khoản, chọn theo tier, xoay khi hết quota — ADR-0019), runner (vòng lặp tool, guard, cắt ngữ cảnh),
               orchestrator (vòng lặp tự động, song song, người can thiệp), workspace (worktree), tools (tool có ranh
               giới tin cậy), web (tool web cho researcher), guard (chống injection), context (hạn mức ngữ cảnh),
               metrics (từ audit-log), evals (ghi/phát lại), graph
evals/         ca eval prompt theo agent (YAML) — đủ 20 agent, mỗi agent ≥ 2 ca; recordings/ = phản hồi model đã ghi
tests/         pytest (bus, registry↔events nhất quán, delivery+gates, supervisor, orchestrator, golden 20 agent)
```

## Chạy

```bash
cd software-company
uv sync                                   # tạo .venv từ pyproject.toml
uv run pytest -q                          # hoặc: make test
PYTHONPATH=src uv run python -m company.demo   # hoặc: make demo
PYTHONPATH=src uv run python examples/donghanhcungban_demo.py --out sim-out   # mô phỏng cả công ty làm web demo
                                          # donghanhcungban.com trên repo khách tạo tạm (báo cáo: docs/reports/)
uv run ruff check src tests               # hoặc: make lint

# Chạy model thật (provider bất kỳ). Cấu hình: cp llm.example.yaml llm.yaml rồi sửa, hoặc biến môi trường:
#   COMPANY_LLM_PROVIDER=openai COMPANY_LLM_BASE_URL=http://localhost:11434/v1 COMPANY_MODEL_STRONG=qwen2.5-coder:32b
#   COMPANY_LLM_PROVIDER=anthropic COMPANY_MODEL_STRONG=claude-opus-5   (uv sync --extra anthropic)
#   Qua gateway xoay vòng tài khoản Google Antigravity (../gateway: `make login && make start && make setup`
#   ghi sẵn llm.yaml): COMPANY_LLM_PROVIDER=openai COMPANY_LLM_BASE_URL=http://127.0.0.1:8100/v1 COMPANY_LLM_API_KEY=gateway-local
#   Gói Claude Pro/Max trên máy (không key, không tool-use): COMPANY_LLM_PROVIDER=claude-code COMPANY_MODEL_STRONG=claude-opus-5
#   NHIỀU gói cùng lúc (ADR-0019): `backends:` + `routing.prefer` trong llm.yaml — mẫu ở llm.example.yaml; agent có tier
#   strong/standard/light, gói hết quota tự nghỉ. Bảng agent → tier: ../docs/DIEU-PHOI-MODEL.md
PYTHONPATH=src uv run python -m company.runner reviewer review-results input.json --db company.sqlite

# Chạy tự động cả công ty (ADR-0007): orchestrator nối topic → agent → topic, dừng ở human gate / supervisor / khách
PYTHONPATH=src uv run python -m company.orchestrator publish research-requests req.json --actor human:sales
PYTHONPATH=src uv run python -m company.orchestrator run --watch 5     # hoặc: make run  (một lượt: bỏ --watch)
PYTHONPATH=src uv run python -m company.orchestrator run --repo ../khach --base main   # làm THẬT: khối kỹ thuật sửa code
                                                                        # trong worktree ticket/<id>, PR mang lint/test thật;
                                                                        # ticket rẽ từ và merge vào company/integration (--integration)
PYTHONPATH=src uv run python -m company.gate_cli approve SPEC-P1 --by human:po   # gate spec → plan → release
PYTHONPATH=src uv run python -m company.orchestrator publish clarification-answers ans.json --actor human:po
PYTHONPATH=src uv run python -m company.orchestrator decide-change CR-1 accepted --by human:po   # sau khi delivery-lead ước lượng impact
PYTHONPATH=src uv run python -m company.orchestrator run --workers 4 --web   # ticket khác key chạy song song; researcher có web
PYTHONPATH=src uv run python -m company.orchestrator run --batch-release   # gom ticket approved của dự án vào một RC (một staging, một gate 3, một UAT)
PYTHONPATH=src uv run python -m company.orchestrator status              # hàng đợi, hoãn, ticket, gate chờ, blackboard, chi phí
PYTHONPATH=src uv run python -m company.orchestrator report              # estimate vs actual, chi phí USD theo agent/model, hành động supervisor
PYTHONPATH=src uv run python -m company.orchestrator metrics [--prometheus]   # hoặc: make metrics [PROM=1] — gọi/token/USD/thời gian
PYTHONPATH=src uv run python -m company.orchestrator show prd            # toàn văn artifact mới nhất (mirror ở company.artifacts/)
PYTHONPATH=src uv run python -m company.orchestrator comment T1 --by human:lead --text "dùng hàm add có sẵn"   # hint giữa vòng, không tính retry
PYTHONPATH=src uv run python -m company.orchestrator takeover T1 --by human:lead   # người sửa tay trong .worktrees/T1 → lint/test → PR dưới tên người
PYTHONPATH=src uv run python -m company.gate_cli list          # hoặc: make gate
PYTHONPATH=src uv run python -m company.evals reviewer         # hoặc: make eval AGENT=reviewer (model thật)
PYTHONPATH=src uv run python -m company.evals reviewer --record   # make eval-record AGENT=reviewer — sau khi đổi prompt/skill
PYTHONPATH=src uv run python -m company.evals all --replay        # make eval-replay — như CI, không gọi model
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_agents.py   # hoặc: make golden — sau khi cố ý sửa agents/ hoặc skills/
```

## Quy ước bắt buộc
- Ticket phải có `estimate_tokens` trước dispatch; `budget_tokens ≥ estimate × 1.5` (code từ chối nếu không).
- Ticket chạm auth/payment/pii/crypto/upload/admin/external-api gắn `risk_tags` → cần thêm review của security-engineer.
- Sửa prompt/skill → tăng `version`, đi qua PR, có eval (ADR-0004). Golden test (`tests/golden/`) đỏ nếu prompt đổi mà version không tăng; cập nhật bằng `make golden`.
  Rồi `make eval-record AGENT=<id>` bằng model thật và commit `evals/recordings/<id>.json`; CI phát lại và đỏ nếu bản ghi lệch prompt (ADR-0010).
- PR của khối kỹ thuật chỉ có bằng chứng khi chạy với `--repo`: `local_checks.verified_by=workspace` do code điền từ lint/test thật; không có repo thì `{"unverified": true}`.
- Mỗi PR có rollback plan, observability, license của dependency mới (`templates/pull_request.md`).
- Agent sở hữu namespace phải ghi TOÀN VĂN artifact vào `context_writes[].content` (schema bắt buộc); chỉ có con trỏ thì audit `context_no_content`.
- Điền bảng `prices` trong `llm.yaml` cho model đang dùng; lời gọi không có giá bị đếm ở `unpriced_calls`, không được coi là miễn phí.

## Hiện trạng (2026-09-02)

### Đã có
- Tài liệu: kiến trúc, tiêu chuẩn, ADR 0001–0018; 20 system prompt có version; 45 skill có version; 14 template; checklist 4 gate.
- 18 JSON Schema topic + bảng owner namespace (thêm change-requests, acceptance-results, external-feedback; namespace contract).
- Lõi xác định trong `src/company/`: envelope/payload pydantic, bus có validate schema, registry nạp prompt+skill,
  delivery-lead (lập lịch depends_on/priority, đóng vòng review, retry, budget, staging QA → gate 3 → production → nghiệm thu),
  supervisor (warn/cut/escalate, sprint_report), gates, blackboard, demo.
- **Runner chạy model thật, trung lập provider** (`runner.py`, `llm.py`, ADR-0005): một interface `ModelClient`;
  adapter `anthropic`, `openai` (mọi server OpenAI-compatible: OpenAI, Ollama, Groq, vLLM, LM Studio...), `fake`.
  Provider `openai` cũng nhận [`../gateway`](../gateway/README.md): proxy cục bộ xoay vòng nhiều tài khoản Google
  Antigravity (Gemini/Claude), tự cooldown khi hết quota và trả `usage` thật.
  Model theo tier cấu hình trong `llm.yaml` / `COMPANY_*`, không nằm trong code hay prompt. Đầu ra ép theo JSON Schema
  của topic, bus validate lại, token thật từ `usage` ghi vào `audit-log`.
- **Bus bền vững SQLite** (`sqlite_bus.py`), cùng interface, replay theo topic/key.
- **Human gate CLI** (`gate_cli.py`): request/approve/reject..., quyết định ghi vào `audit-log`, four-eyes.
- **Workspace theo ticket** (`workspace.py`): git worktree `ticket/<id>`, chạy ruff/pytest thật, trả `local_checks`.
- **Eval prompt** (`evals/*.yaml`, `evals.py`): ca đầu vào + tiêu chí chấm; chạy với provider bất kỳ.
- **Orchestrator** (`orchestrator.py`, ADR-0007): vòng lặp tự động theo bảng ROUTES khớp front matter; agent ghi blackboard
  qua `context_writes`; security-engineer làm threat model từ spec đã duyệt trước khi delivery-lead sinh ticket (C4 + contract
  lên blackboard) → gate plan → dispatch; clarifier hết câu hỏi thì spec-writer đi thẳng; change request: delivery-lead ước
  lượng impact → người `decide-change` → accepted đi lập kế hoạch (hoặc intake nếu đổi requirement); nghiệm thu conditional
  → change request; support-docs viết docs sau production, mở incident từ feedback, incident requirement → nghiên cứu lại;
  ticket blocked/escalate → gate `escalation` (approve = mở lại với hint, reject = đóng); agent chuỗi nghiên cứu lỗi → dự án
  `stalled` + gate `escalation` cấp dự án (approve = chạy lại event, reject = đóng dự án); spec-writer đòi có `requirements-draft`; review quá hạn giao lại một lần;
  sau nghiệm thu ghi estimate vs actual vào `knowledge`; đánh dấu đã xử lý trong `audit-log` nên mở lại SQLite là chạy tiếp;
  `--watch` nhận quyết định gate từ tiến trình khác; CLI `run | publish | decide-change | status | report`.
- **Tool có ranh giới tin cậy + vòng lặp tool-use** (`tools.py`, ADR-0010): khối kỹ thuật sửa code thật trong worktree
  `ticket/<id>` (`--repo`); bảng tool tên cố định, không shell, allowlist lệnh, đường dẫn khoá trong worktree, lọc secret;
  tool-use trung lập provider (Anthropic, OpenAI-compatible, Fake). Vòng lặp dừng khi hết lượt hoặc vượt ngân sách token.
- **Bằng chứng PR do code điền**: sau vòng tool, runner chạy lint/test thật, commit, ghi đè `branch`/`pr_ref`/
  `local_checks` (`verified_by: workspace`)/`impact.files`; worktree không đổi → PR bị từ chối. Reviewer/security đọc
  `diff` thật; QA có tool chỉ đọc để tự chạy test (trên worktree ticket khi review PR, trên worktree tích hợp khi hồi quy
  staging; có tool mà không chạy gì → audit `review.no_tool_evidence`). Lint/test thật đỏ → PR không publish, ticket
  retry+1 với hint là đầu ra test (`pr.rejected_local_checks`), không tốn lượt reviewer/QA/security. Không có `--repo` → `local_checks = {"unverified": true}` + audit.
- **Eval ghi / phát lại** (`--record` / `--replay`): CI job `eval-replay` chạy từ `evals/recordings/`, đỏ khi bản ghi
  lệch prompt — cổng "đổi prompt phải chạy eval" của ADR-0004 được máy cưỡng chế.
- **Nhánh tích hợp** (ADR-0011): ticket rẽ từ `company/integration` (worktree `.worktrees/_integration`, rẽ từ `--base`
  lần đầu); khi release-candidate xuất hiện, orchestrator `merge --no-ff` từng branch ticket vào đó rồi mới cho
  release-engineer chạy (đầu vào có `integration_sha`); ticket approved được merge ngay (trước khi ticket phụ thuộc
  tạo worktree), RC chỉ merge phần chưa có. Xung đột → RC huỷ (`release.void`), ticket về `changes_requested`
  với hint là file xung đột, worktree tạo lại từ nền mới. `main` của khách không bị chạm.
- **Vòng học đóng**: `Supervisor.calibration()` (median actual/estimate theo assignee, đọc từ bus) đi vào đầu vào của
  delivery-lead mỗi lần lập kế hoạch; `sprint_report` có `rework_rate`, `review_catch_rate`, `prs_unverified`;
  kế hoạch có `depends_on` vòng bị từ chối trước gate.
- **Blackboard có toàn văn + artifact store** (ADR-0012): `shared-context.content` mang cả PRD/C4/OpenAPI/threat model
  qua bus (nguồn sự thật), mirror ra `<db>.artifacts/<namespace>/v<n>.<ext>` + `latest.<ext>` (`--artifacts`, `show`);
  agent hạ nguồn đọc toàn văn trong prompt, agent chủ namespace bị schema ép trả `content`.
- **Ngữ cảnh có hạn mức** (`context.py`): `max_input_chars` (llm.yaml / `COMPANY_MAX_INPUT_CHARS`); payload ưu tiên,
  chuỗi dài nhất cắt giữa có nhãn, blackboard chia water-filling, nhãn cắt chỉ đường dẫn artifact; audit `context_trimmed`.
- **Guard injection theo nguồn** (`guard.py`): regex Anh/Việt; nguồn nội bộ khớp → từ chối; nguồn ngoài (khách, web)
  và trường không tin cậy (`diff`, `text`) → thay bằng `[đã lọc]`, đi tiếp, audit `injection_sanitized`.
- **Retry lỗi transport** (`RetryingClient`): mạng/408/429/5xx thử lại backoff mũ (`retries`, `retry_base`), audit
  `llm_retry`; lỗi nội dung không retry. Hết retry → orchestrator hoãn event (`transient:`), nhịp sau thử lại, agent đã
  xong không chạy lại; `stats.transient` tách khỏi `stats.errors`.
- **Ngân sách tiền**: bảng `prices` (USD/1M token, khớp tiền tố model, giá cache) → `audit-log.cost_usd`; supervisor
  warn/cut theo `Task.budget_usd`, pause cả dự án theo `budget_usd`; `report` có `cost_by_agent`, `cost_by_model`,
  `project_cost_usd`, `unpriced_calls`.
- **Tool cho researcher**: đọc repo khách chỉ đọc (không `run`, không ghi) + `web_search`/`fetch_url` khi `--web`
  (chỉ http/https công khai, chặn host nội bộ, bóc HTML, lọc injection, URL vào audit; `COMPANY_SEARCH_URL` cho SearXNG).
- **Chạy song song** `--workers N` trong một tiến trình: bus có RLock, phần xác định vẫn tuần tự; event đổi trạng thái
  chung (gate, plan, RC, clarifier) chạy một mình.
- **Metrics** (`metrics.py`, `orchestrator metrics [--prometheus]`): gọi/token/USD/thời gian/cache/tool theo agent, model,
  ticket, dự án; sự kiện sức khoẻ; thời gian chờ gate; lead time ticket; xuất Prometheus text.
- **Người can thiệp giữa vòng**: `comment` (hint cho ticket đang chạy, không tính retry), `takeover` (người sửa tay trong
  worktree, code chạy lint/test, PR dưới tên người thay PR của agent, review làm lại).
- Test: pytest gồm golden 20 agent (`tests/golden/`), runner với client giả, bus SQLite, gate, worktree, tool boundary,
  vòng tool, orchestrator với repo git thật, eval ghi/phát lại, adapter tool-use (server HTTP giả), guard, cắt ngữ cảnh,
- **Schema là nguồn sự thật**: bus validate đủ JSON Schema (enum, type, ràng buộc) cho cả payload và envelope;
  envelope có `schema_version`, `correlation_id`, `causation_id`. `tests/test_schema_consistency.py` khoá schema ↔ model.
- **Blackboard phân vùng theo dự án** (ADR-0018): artifact thuộc một `project_id`, chỉ `knowledge` là chung.
- **Lint/test theo stack** (ADR-0013): Python, Node, Go, Rust, Gradle, Maven; stack lạ thì `local_checks` nói rõ
  không kiểm được thay vì báo pass giả.
- **Cổng eval có răng**: CI chạy `--replay --strict`; agent trong `evals/recordings/REQUIRED.txt` thiếu bản ghi
  hoặc bản ghi ở phiên bản prompt cũ thì đỏ.
- **Bốn human gate là gate thật**: spec, plan, release và nghiệm thu của khách (`acceptance`, ADR-0017) — cùng hạn 24h,
  nhắc ở 12h, four-eyes, và quá hạn thì supervisor escalate chứ không im lặng.
- **Lỗi tạm thời của provider** (429, 5xx, đứt mạng) được thử lại có backoff; `Refused` và 4xx thì không. Anthropic
  có timeout nên một request treo không giữ luôn cả orchestrator.
  artifact store, retry, bảng giá, tool web (fetcher giả), song song, metrics, comment/takeover; ruff sạch.

### Chưa có
- **Bản ghi eval bằng model thật**: cơ chế và cổng `--strict` đã có (`evals/recordings/REQUIRED.txt`), nhưng
  `evals/recordings/` còn trống nên danh sách bắt buộc chưa có tên nào. Chạy `make eval-record` rồi thêm id vào file.
- **Deploy thật**: release-engineer vẫn mô phỏng; chưa đẩy `company/integration` lên `main`/tag phiên bản; xung đột
  giải quyết bằng làm lại trên nền mới, chưa rebase tự động. Chưa dựng **CI/CD cho sản phẩm của khách** (CI của chính
  repo này thì có). **Kafka/Redis** thay SQLite khi chạy nhiều máy (song song mới ở mức thread trong một tiến trình).
- **Sandbox tiến trình** cho `run` (container/seccomp): hiện chỉ allowlist lệnh + khoá đường dẫn + lọc env. Guard
  injection là lưới chắn theo mẫu, không phải hàng rào — xem `SECURITY.md`.
- **Giao diện gate** ngoài CLI; thông báo (email/chat) khi gate quá hạn; **giao diện UAT cho khách**.

### Bước tiếp theo
1. Chạy `make eval-record AGENT=<id>` cho 20 agent với model thật, commit bản ghi để CI eval có răng.
2. Release-engineer thật: đẩy `company/integration` lên `main` + tag khi gate release duyệt; CI/CD.
3. Sandbox container cho `run`; adapter bus Redis Streams/Kafka giữ interface hiện tại (kể cả `poll`) để chạy nhiều tiến trình.
4. Giao diện web cho human gate + thông báo; giao diện UAT cho khách.

## Thứ tự triển khai khuyến nghị

1. delivery-lead + backend + reviewer + qa-debugger + human gate (vòng lõi)
2. security-engineer (threat model) ngay khi có ticket auth/payment/pii; account-manager ngay khi có khách thật
3. Thêm khối nghiên cứu (intake + researcher + synthesizer...) khi yêu cầu đầu vào hay mơ hồ
4. platform + release-engineer + support-docs khi cần deploy thật; data khi cần analytics
5. Bật supervisor ngay khi chi phí token vượt dự tính

Đọc `docs/architecture.md` trước, sau đó `docs/standards.md` và `docs/adr/`.
