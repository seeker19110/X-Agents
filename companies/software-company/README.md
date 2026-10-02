# Software Company — Multi-Agent phòng gia công phần mềm

Mô phỏng một công ty gia công phần mềm bằng hệ đa agent event-driven: 6 agent (5 công đoạn + supervisor),
mọi trao đổi đi qua topic có key, tri thức chung nằm trên blackboard, con người duyệt ở
3 điểm cố định (spec, release, nghiệm thu) cộng gate bất thường `escalation`. Nguyên tắc: tính toán xác định,
guardrail có hạn mức, đo token thật, cô lập workspace theo ticket, prompt là code. Đây là "công ty AI" đầu tiên
trong hub X-Agents.

## Năm công đoạn + supervisor (ADR-0037)

Một công đoạn = một agent = một file `agents/<khối>/<id>.md`. Agent nhiều việc thì chia **pha**: skill của pha chỉ
nạp khi lượt đó chạy (`phases:` trong front matter), nên prompt không loãng mà vẫn giữ nguyên văn từng dòng
PHẢI/KHÔNG ĐƯỢC đã trả giá của các vai cũ.

| Khối | Agent | Tier | Pha | Vai trò |
|------|-------|------|-----|---------|
| `research` | `product` | strong | `intake`, `research`, `spec`, `plan` | Yêu cầu thô → 4 mảng nghiên cứu → draft (kèm `risks`) + câu hỏi làm rõ → PRD/Gherkin → C4 + contract + ticket có `stack`/`estimate_tokens`/`risk_tags` |
| `engineering` | `builder` | strong | `backend`, `frontend`, `mobile`, `database`, `platform`, `data` (= `Task.stack`) | Code / hạ tầng / dữ liệu thật trong worktree `ticket/<id>`, PR mang lint/test thật; KHÔNG ghi được file test |
| `quality` | `qa` | standard | `author`, `review` | Viết bộ test MÙ từ acceptance (ADR-0028); đọc diff, chấm PR, chẩn đoán nguyên nhân, hồi quy + perf + a11y trên staging |
| `quality` | `security` | strong | (không pha) | Threat model STRIDE trên spec đã duyệt, review PR có `risk_tags`, DAST/license/PII trên release-candidate |
| `operations` | `ops` | standard | `deploy`, `docs`, `account` | Staging → gate release → production, tag + `company/release`; tài liệu Diátaxis, incident; SOW/UAT, change request |
| `supervisor` | `supervisor` | light | (không pha) | Watchdog, ngân sách token, knowledge base, version prompt — **code**, không phải công đoạn |
| (con người) | human gate | — | — | Duyệt spec, release; khách ký nghiệm thu; gate `escalation` khi kẹt (kế hoạch do `_check_plan` kiểm bằng code, ADR-0037) |

`load_agents()` trả **6** — ADR-0037 nói "5 agent" vì `supervisor` không phải một công đoạn của dây chuyền.

## Luồng chính

```
research-requests → product[intake] → product[research] → product[spec] ⇄ product[intake] (câu hỏi làm rõ)
      → approved-specs → GATE spec → security (threat model) → product[plan] → _check_plan → tasks (depends_on/priority)
      → qa[author] (khi bật --test-author) → builder[stack] → pull-requests
      → review-results (qa[review] + security khi risk_tags) → release-candidates
      → ops[deploy] staging → review-results (qa[review] hồi quy) → GATE release → ops[deploy] production
      → acceptance-results (khách ký ở GATE acceptance) → closed
      → incidents (root_cause_class) → tasks | research-requests;  change-requests → product[plan] | product[intake]
+ shared-context (blackboard 12 namespace, phân vùng theo dự án)   + audit-log (mọi hành động)
```

## Cấu trúc

```
docs/          kiến trúc, tiêu chuẩn, ADR (0001–0047); reports/ = báo cáo mô phỏng (donghanhcungban: client giả + bản relay model thật)
agents/        system prompt 6 agent (có version), nhóm theo khối; agent nhiều việc khai `phases:` — skill của pha
               chỉ nạp ở lượt chạy pha đó (ADR-0037), thân bài có tiểu mục `### Pha <tên>` / `### Stack <tên>`
skills/        45 skill (có version): rule + checklist + ví dụ, theo tiêu chuẩn ngành;
               nạp hai mức — đầy đủ cho agent chủ quản, rút gọn (quy trình + checklist) cho agent tuân thủ (ADR-0008)
gates/         checklist 2 gate công đoạn + nghiệm thu + gate bất thường `escalation` (ticket và cấp dự án); GateKind = spec|release|acceptance|escalation
               — nửa "Người tự kiểm thêm" của mỗi gate được `gate_checklists.py` parse thành trợ lý `sc-gate-<kind>` và hồ sơ `gate_brief`
templates/     PRD, ticket, PR, bug report, postmortem, ADR, threat model, data contract
topics/        19 JSON Schema topic + bảng owner namespace
src/company/   events, bus, sqlite_bus, registry, delivery, supervisor, gates, gate_cli, blackboard (artifact store),
               llm (ModelClient + adapter anthropic/openai/claude-code/codex/fake, tool-use, retry, bảng giá), routing (nhiều gói tài
               khoản, chọn theo tier, xoay khi hết quota — ADR-0019), runner (vòng lặp tool, guard, cắt ngữ cảnh),
               orchestrator (vòng lặp tự động, song song, người can thiệp), workspace (worktree), tools (tool có ranh
               giới tin cậy), mcp_bridge (cầu MCP đưa tool công ty vào CLI — ADR-0024), probe (CLI chạy được chế độ tool
               nào), web (tool web cho `product` pha research), guard (chống injection), assetscan (quét tài sản prompt), context (hạn mức ngữ cảnh),
               metrics (từ audit-log), sổ Ruling `rulings` (quyết định agent tự đưa ra — ADR-0030), evals (ghi/phát lại), stacks (lint/test theo stack — ADR-0013), smoke (khởi động sản phẩm theo `runtime` của spec, bằng chứng cho `deployed` — ADR-0029; `runtime` là điều kiện cần của Gate 1 — ADR-0031),
               deploy (dựng compose file **của khách** cho `staging`/`production`, `deployed` = `up -d` + `ps` running + smoke, thiếu một phần thì `down` — ADR-0039; nối vào vòng đời release qua `orch/verify.py::deploy_release`, gọi từ `orch/release_fsm.py::_release`),
               subagents (sinh 10 trợ lý kiểm duyệt chỉ-đọc `.claude/agents/sc-*.md` từ agents/ + gates/checklists.md — `make subagents`),
               gate_checklists (parser checklists.md + bảng nguồn bằng chứng §5 đặc tả), gate_brief (hồ sơ bằng chứng chỉ đọc
               cho nửa "người tự kiểm" của một gate — `make gate-brief SUBJECT=…`), demo, graph (cần `uv sync --extra graph`, không tính coverage)
examples/      donghanhcungban_demo.py (mô phỏng cả công ty, --real/--relay/--resume/--auto-escalate), relay_client.py
               yeu-cau-mau-web-app.json (yêu cầu mẫu để publish vào `research-requests`: đủ mục tiêu, người dùng,
               phạm vi + NGOÀI phạm vi, ràng buộc, NFR có số đo, tiêu chí nghiệm thu — bốn mảng pha `intake` cần)
               (ModelClient trao đổi qua file <n>.req.json / <n>.res.json để một phiên Claude Code khác đóng vai model)
evals/         ca eval prompt theo agent (YAML) — đủ 6 agent, mỗi agent ≥ 2 ca (agent nhiều pha: ≥ 2 ca mỗi pha); recordings/ = phản hồi model đã ghi
tests/         pytest 2000 ca / 107 file (bus, registry↔events, delivery+gates, supervisor, orchestrator, release flow, nhánh
               tích hợp, repo theo dự án, giao hàng thật, release tự dừng → gate, routing, runner/persistence, tools/agentic, cầu MCP, probe, assetscan,
               guard/blackboard, schema consistency, golden 6 agent + 4 hồ sơ gate, bộ sinh subagent, hồ sơ gate, deploy compose (runner tiêm được), rà soát bảo mật);
               coverage fail_under=100 (phủ 100% dòng VÀ 100% nhánh, `branch = true` từ 2026-09-13)
```

## Product-quality contract và execution adapter

`product_quality.py` biên dịch profile/Design Brief thành các check theo tính áp dụng và xác minh receipt.
`quality_execution.py` nối vào `xagents_core.execution` (RunSpec/TaskResult/journal), không fork kernel.
Dùng `uv run python -m company.quality_execution plan examples/product-quality-profile.json examples/product-quality-work.json`.
`plan/register/status` là điểm nối kernel, chưa là worker daemon hoặc gate bắt buộc của mọi Orchestrator run.
`commit_quality_result` lưu kết quả/receipt cùng transition CAS (ADR gốc 0019), phục hồi và ACK lại
không chạy lại việc; phải gọi từ coordinator đáng tin, không từ worker trực tiếp.
Sàn tự duyệt `quality_floor` ADR-0043 được giữ nguyên. Xem [`hợp đồng chất lượng`](../../docs/PRODUCT-EXCELLENCE.md)
và [`ADR gốc 0018`](../../docs/adr/0018-product-quality-execution-adapter.md).

## Chạy

```bash
cd companies/software-company
uv sync                                   # tạo .venv từ pyproject.toml
uv run pytest -q                          # hoặc: make test
uv run python -m company.demo   # hoặc: make demo
uv run python examples/donghanhcungban_demo.py --out sim-out   # mô phỏng cả công ty làm web demo
                                          # donghanhcungban.com trên repo khách tạo tạm (báo cáo: docs/reports/)
                                          # --real: gọi model thật theo tier (llm.yaml / COMPANY_*); --relay DIR: model là một
                                          # phiên Claude Code khác trả lời qua file; --resume: chạy tiếp từ sim-out; --auto-escalate
uv run ruff check src tests && uv run mypy src/company --ignore-missing-imports   # make lint (make fix = ruff --fix; make types = mypy)
uv run pytest -q --cov --cov-report=term  # make cov — ngưỡng fail_under = 100 (phủ 100% dòng VÀ 100% nhánh)

# Chạy model thật (provider bất kỳ). Cấu hình: cp llm.example.yaml llm.yaml rồi sửa, hoặc biến môi trường:
#   COMPANY_LLM_PROVIDER=openai COMPANY_LLM_BASE_URL=http://localhost:11434/v1 COMPANY_MODEL_STRONG=qwen2.5-coder:32b
#   COMPANY_LLM_PROVIDER=anthropic COMPANY_MODEL_STRONG=claude-opus-5   (uv sync --extra anthropic)
#   Qua gateway xoay vòng tài khoản Google Antigravity (../../platform/gateway: `make login && make start && make setup`
#   ghi sẵn llm.yaml): COMPANY_LLM_PROVIDER=openai COMPANY_LLM_BASE_URL=http://127.0.0.1:1123/v1 COMPANY_LLM_API_KEY=gateway-local
#   Gói Claude Pro/Max trên máy (không key): COMPANY_LLM_PROVIDER=claude-code COMPANY_MODEL_STRONG=claude-opus-5
#     mặc định không tool-use; muốn cả khối kỹ thuật chạy bằng gói này thì đặt `mcp_tools: true` (ADR-0024, giữ nguyên
#     sandbox tools.py) hoặc `cli_tools: true` (ADR-0023, CLI tự cầm tool) trong llm.yaml. Hồ sơ sẵn: `make llm`.
#     `make probe` gọi CLI thật một lượt và nói máy này dùng được chế độ nào (mcp | cli | none)
#   Gói ChatGPT Plus/Pro qua Codex CLI (không key, không tool-use): COMPANY_LLM_PROVIDER=codex COMPANY_MODEL_STRONG=gpt-5.6-terra
#   NHIỀU gói cùng lúc (ADR-0019): `backends:` + `routing.prefer` trong llm.yaml — mẫu ở llm.example.yaml; agent có tier
#   strong/standard/light, gói hết quota tự nghỉ (routing.cooldown_s, transient_cooldown_s). Mỗi backend: name, provider,
#   models{strong,standard,light}, base_url, api_key | api_key_env, config_dir (CLAUDE_CONFIG_DIR / CODEX_HOME — nhiều tài
#   khoản cùng gói), binary, effort, max_tokens, extra, supports_tools. COMPANY_LLM_BACKENDS=a,b lọc và sắp lại backend.
#   Biến môi trường khác: COMPANY_LLM_RETRIES, COMPANY_MAX_INPUT_CHARS, COMPANY_BUDGET_USD, COMPANY_SEARCH_URL.
#   Bảng agent → tier: ../../docs/DIEU-PHOI-MODEL.md
uv run python -m company.runner qa review-results input.json --db company.sqlite [--artifacts DIR]

# Chạy tự động cả công ty (ADR-0007): orchestrator nối topic → agent → topic, dừng ở human gate / supervisor / khách
uv run python -m company.orchestrator publish research-requests req.json --actor human:sales
uv run python -m company.orchestrator run --watch 5     # hoặc: make watch (một lượt: make run; --max-steps N giới hạn số bước)
#   cờ chung đặt trước subcommand: --db company.sqlite --repo --base --integration --artifacts --workers --web --batch-release --test-author
uv run python -m company.orchestrator run --repo ../khach --base main   # làm THẬT: khối kỹ thuật sửa code
#   --repo là MẶC ĐỊNH; từng dự án tự chỉ repo riêng bằng `repo`/`base` trong research-requests (ADR-0025) — một tiến
#   trình phục vụ nhiều khách, mỗi khách một repo; console giao việc kèm "nơi lưu dự án"
                                                                        # trong worktree ticket/<id>, PR mang lint/test thật;
                                                                        # ticket rẽ từ và merge vào company/integration (--integration)
uv run python -m company.gate_cli approve SPEC-P1 --by human:po   # gate spec → (kế hoạch tự đi) → release → acceptance
#   quyết định: approve | request_changes | reject | hold | rollback; `request KIND SUBJECT --by --checklist` mở gate tay
uv run python -m company.gate_brief REL-001 [--repo ../khach]   # hoặc: make gate-brief SUBJECT=REL-001 — hồ sơ bằng chứng CHỈ ĐỌC
#   cho nửa "người tự kiểm thêm" của gate (SQLite mode=ro, verdict chỉ ok|gap|unknown, không khuyến nghị); `--all` mọi gate chờ;
#   ghi <db>.artifacts/<project>/gate-brief/<subject>.{md,json}. Trong Claude Code: `/gate-brief REL-001` gọi thêm trợ lý
#   `sc-gate-<kind>` + `sc-<agent>` (chỉ Read/Grep/Glob) đọc hồ sơ và in bản tóm; người vẫn tự ký bằng gate_cli
uv run python -m company.orchestrator --repo ../khach --deliver [--push-remote origin] [--release-branch company/release] [--deliver-pr] run --watch 5
#   ADR-0027: production duyệt + deploy → tag v<version> tại sha đã QA trên staging + fast-forward nhánh `company/release`
#   trong repo khách; rolled_back → lùi con trỏ (tag giữ); push lỗi chỉ vào audit `delivery.push_failed`; `main` khách không bị chạm
#   ADR-0038: `--deliver-pr` (cần --push-remote trỏ remote GitHub + `gh auth login`) → sau khi push, mở PR thật
#   `company/release → <--base>` để khách review bằng UI quen thuộc trước khi ký UAT; mở không merge, PR đang mở thì dùng lại;
#   kết quả ở `delivery.done.pr` + audit `delivery.pr_opened|pr_reused|pr_skipped|pr_failed`; gh lỗi không chặn bản giao
uv run python -m company.orchestrator publish clarification-answers ans.json --actor human:po
uv run python -m company.orchestrator decide-change CR-1 accepted --by human:po   # sau khi `product` pha plan ước lượng impact
uv run python -m company.orchestrator run --workers 4 --web   # ticket khác key chạy song song; `product` pha research có web
uv run python -m company.orchestrator --repo ../khach --test-author run
#   ADR-0028: `qa` pha author viết bộ test từ acceptance TRƯỚC (lượt mù, chỉ ghi được file test), rồi `builder` viết code
#   cho tới khi xanh mà KHÔNG ghi/xoá được file test. Thêm một lượt model mỗi ticket. Stack không phân vùng được vùng
#   test (UNKNOWN) → ticket đi đường cũ và PR mang `tests_authored_by: assignee` để lượt review biết bộ test không độc lập
uv run python -m company.orchestrator run --batch-release   # gom ticket approved của dự án vào một RC (một staging, một gate release, một UAT)
uv run python -m company.orchestrator status              # hàng đợi, hoãn, ticket, gate chờ, blackboard, chi phí,
                                                                        # backend nào sẵn sàng/đang nghỉ (routing.status) — make status
uv run python -m company.orchestrator report              # estimate vs actual, chi phí USD theo agent/model, hành động supervisor — make report
uv run python -m company.orchestrator metrics [--prometheus]   # hoặc: make metrics [PROM=1] — gọi/token/USD/thời gian
uv run python -m company.orchestrator show prd            # toàn văn artifact mới nhất (mirror ở company.artifacts/)
uv run python -m company.orchestrator comment T1 --by human:lead --text "dùng hàm add có sẵn"   # hint giữa vòng, không tính retry
uv run python -m company.orchestrator takeover T1 --by human:lead   # người sửa tay trong .worktrees/T1 → lint/test → PR dưới tên người
uv run python -m company.gate_cli list          # hoặc: make gate
uv run python -m company.evals qa               # hoặc: make eval AGENT=qa (provider theo llm.yaml / COMPANY_*)
uv run python -m company.evals qa --record         # make eval-record AGENT=qa — sau khi đổi prompt/skill
uv run python -m company.evals all --replay --strict   # make eval-replay — như CI, không gọi model; --strict đỏ khi agent trong REQUIRED.txt thiếu bản ghi
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_agents.py   # hoặc: make golden — sau khi cố ý sửa agents/ hoặc skills/
```

## Quy ước bắt buộc
- Ticket phải có `estimate_tokens` trước dispatch; `budget_tokens ≥ estimate × 1.5` (code từ chối nếu không).
- Ticket chạm auth/payment/pii/crypto/upload/admin/external-api gắn `risk_tags` → cần thêm review của security.
- Sửa prompt/skill → tăng `version`, đi qua PR, có eval (ADR-0004). Golden test (`tests/golden/`) đỏ nếu prompt đổi mà version không tăng; cập nhật bằng `make golden`.
  Rồi `make eval-record AGENT=<id>` bằng model thật và commit `evals/recordings/<id>.json`; CI phát lại và đỏ nếu bản ghi lệch prompt (ADR-0010).
- PR của khối kỹ thuật chỉ có bằng chứng khi chạy với `--repo`: `local_checks.verified_by=workspace` do code điền từ lint/test thật; không có repo thì `{"unverified": true}`.
- Mỗi PR có rollback plan, observability, license của dependency mới (`templates/pull_request.md`).
- Agent sở hữu namespace phải ghi TOÀN VĂN artifact vào `context_writes[].content` (schema bắt buộc); chỉ có con trỏ thì audit `context_no_content`.
- Điền bảng `prices` trong `llm.yaml` cho model đang dùng; lời gọi không có giá bị đếm ở `unpriced_calls`, không được coi là miễn phí.

## Hiện trạng (2026-09-08)

### Đã có
- Tài liệu: kiến trúc, tiêu chuẩn, ADR 0001–0047; 6 system prompt có version (5 công đoạn + supervisor, ADR-0037); 45 skill có version; 14 template; checklist 3 gate + escalation.
- 19 JSON Schema topic + bảng owner namespace (thêm change-requests, acceptance-results, external-feedback; namespace contract).
- Lõi xác định trong `src/company/`: envelope/payload pydantic, bus có validate schema, registry nạp prompt+skill,
  `delivery.py` (lập lịch depends_on/priority, đóng vòng review, retry, budget, staging QA → gate release → production → nghiệm thu;
  actor `delivery-lead` là CODE phát event, không phải agent — `roles.LEAD_ACTOR`),
  supervisor (warn/cut/escalate, sprint_report), gates, blackboard, demo.
- **Runner chạy model thật, trung lập provider** (`runner.py`, `llm.py`, ADR-0005): một interface `ModelClient`;
  adapter `anthropic`, `openai` (mọi server OpenAI-compatible: OpenAI, Ollama, Groq, vLLM, LM Studio...), `claude-code`
  (CLI `claude -p`, gói Claude Pro/Max, `config_dir` → `CLAUDE_CONFIG_DIR`, `effort` → `--effort` — ADR-0026), `codex` (CLI `codex exec --json`, gói ChatGPT
  Plus/Pro, `config_dir` → `CODEX_HOME`, `effort` → `model_reasoning_effort`, tự tìm binary trong `%LOCALAPPDATA%/OpenAI/Codex/bin`), `fake`.
  Hai provider CLI không có tool-use nên `supports_tools=false` mặc định: router bỏ qua chúng cho agent cần tool.
  Provider `openai` cũng nhận [`../../platform/gateway`](../../platform/gateway/README.md): proxy cục bộ xoay vòng nhiều tài khoản Google
  Antigravity (Gemini/Claude), tự cooldown khi hết quota và trả `usage` thật.
  Model theo tier cấu hình trong `llm.yaml` / `COMPANY_*`, không nằm trong code hay prompt. Đầu ra ép theo JSON Schema
  của topic, bus validate lại, token thật từ `usage` ghi vào `audit-log`.
- **Bus bền vững SQLite** (`sqlite_bus.py`), cùng interface, replay theo topic/key.
- **Human gate CLI** (`gate_cli.py`): `list`, `request`, và 5 quyết định `approve | request_changes | reject | hold | rollback`;
  quyết định ghi vào `audit-log`, four-eyes; hạn 24h, nhắc 12h.
- **Workspace theo ticket** (`workspace.py`): git worktree `ticket/<id>`, chạy ruff/pytest thật, trả `local_checks`.
- **Eval prompt** (`evals/*.yaml`, `evals.py`): ca đầu vào + tiêu chí chấm; chạy với provider bất kỳ.
- **Orchestrator** (`orchestrator.py`, ADR-0007): vòng lặp tự động theo bảng ROUTES khớp front matter; agent ghi blackboard
  qua `context_writes`; security làm threat model từ spec đã duyệt trước khi `product` pha plan sinh ticket (C4 + contract
  lên blackboard) → `_check_plan` → dispatch NGAY (ADR-0037: không còn gate plan); hết câu hỏi làm rõ thì pha spec đi thẳng ra
  `approved-specs`; change request: `product` pha plan ước
  lượng impact → người `decide-change` → accepted đi lập kế hoạch (hoặc pha intake nếu đổi requirement); nghiệm thu conditional
  → change request; `ops` pha docs viết docs sau production, mở incident từ feedback, incident requirement → nghiên cứu lại;
  ticket blocked/escalate → gate `escalation` (approve = mở lại với hint, reject = đóng); agent chuỗi nghiên cứu lỗi → dự án
  `stalled` + gate `escalation` cấp dự án (approve = chạy lại event, reject = đóng dự án); pha spec đòi có `requirements-draft`; review quá hạn giao lại một lần;
  sau nghiệm thu ghi estimate vs actual vào `knowledge`; đánh dấu đã xử lý trong `audit-log` nên mở lại SQLite là chạy tiếp;
  `--watch` nhận quyết định gate từ tiến trình khác; CLI `run | publish | decide-change | comment | takeover | status | report
  | metrics | show`.
- **Tool có ranh giới tin cậy + vòng lặp tool-use** (`tools.py`, ADR-0010): khối kỹ thuật sửa code thật trong worktree
  `ticket/<id>` (`--repo`); bảng tool tên cố định, không shell, allowlist lệnh, đường dẫn khoá trong worktree, lọc secret;
  tool-use trung lập provider (Anthropic, OpenAI-compatible, Fake). Vòng lặp dừng khi hết lượt hoặc vượt ngân sách token.
- **Bằng chứng PR do code điền**: sau vòng tool, runner chạy lint/test thật, commit, ghi đè `branch`/`pr_ref`/
  `local_checks` (`verified_by: workspace`)/`impact.files`; worktree không đổi → PR bị từ chối. Reviewer/security đọc
  `diff` thật; QA có tool chỉ đọc để tự chạy test (trên worktree ticket khi review PR, trên worktree tích hợp khi hồi quy
  staging; có tool mà không chạy gì → audit `review.no_tool_evidence`). Lint/test thật đỏ → PR không publish, ticket
  retry+1 với hint là đầu ra test (`pr.rejected_local_checks`), không tốn lượt qa/security. Không có `--repo` → `local_checks = {"unverified": true}` + audit.
- **Eval ghi / phát lại** (`--record` / `--replay`): CI job `eval-replay` chạy từ `evals/recordings/`, đỏ khi bản ghi
  lệch prompt — cổng "đổi prompt phải chạy eval" của ADR-0004 được máy cưỡng chế.
- **Nhánh tích hợp** (ADR-0011): ticket rẽ từ `company/integration` (worktree `.worktrees/_integration`, rẽ từ `--base`
  lần đầu); khi release-candidate xuất hiện, orchestrator `merge --no-ff` từng branch ticket vào đó rồi mới cho
  `ops` pha deploy chạy (đầu vào có `integration_sha`); ticket approved được merge ngay mỗi vòng `run()`; ticket phụ thuộc chỉ bắt đầu
  khi dependency đã merge (không phải lúc approved); rác lint/test (`__pycache__`, `.pyc`, `.ruff_cache`…) không bao giờ vào
  commit của ticket; RC chỉ merge phần chưa có. Xung đột → RC huỷ (`release.void`), ticket về `changes_requested`
  với hint là file xung đột, worktree tạo lại từ nền mới. `main` của khách không bị chạm.
- **Vòng học đóng**: `Supervisor.calibration()` (median actual/estimate theo assignee, đọc từ bus) đi vào đầu vào của
  `product` pha plan mỗi lần lập kế hoạch; `sprint_report` có `rework_rate`, `review_catch_rate`, `prs_unverified`;
  kế hoạch có `depends_on` vòng bị từ chối trước gate.
- **Blackboard có toàn văn + artifact store** (ADR-0012): `shared-context.content` mang cả PRD/C4/OpenAPI/threat model
  qua bus (nguồn sự thật), mirror ra `<db>.artifacts/<namespace>/v<n>.<ext>` + `latest.<ext>` (`--artifacts`, `show`);
  agent hạ nguồn đọc toàn văn trong prompt, agent chủ namespace bị schema ép trả `content`.
- **Ngữ cảnh có hạn mức** (`context.py`): `max_input_chars` (llm.yaml / `COMPANY_MAX_INPUT_CHARS`); payload ưu tiên,
  chuỗi dài nhất cắt giữa có nhãn, blackboard chia water-filling, nhãn cắt chỉ đường dẫn artifact; audit `context_trimmed`.
- **Quét tài sản prompt** (`assetscan.py`, ADR-0022, `make assetscan`): cổng CI cho chính `agents/ skills/
  templates/ gates/ topics/` — injection (dùng lại `guard.PATTERNS`), ký tự vô hình/bidi, `curl … | sh` và
  `rm -rf /`, khóa lộ; cảnh báo URL ngoài allowlist. Miễn trừ có lý do ở `assetscan-waivers.txt`. `make assetbudget`
  báo prompt tĩnh của agent so với `budget_tokens_per_task` (>50% là đỏ, skill khai mà thiếu file cũng đỏ).
- **Guard injection theo nguồn** (`guard.py`): regex Anh/Việt; nguồn nội bộ khớp → từ chối; nguồn ngoài (khách, web)
  và trường không tin cậy (`diff`, `text`) → thay bằng `[đã lọc]`, đi tiếp, audit `injection_sanitized`.
- **Retry lỗi transport** (`RetryingClient`): mạng/408/429/5xx thử lại backoff mũ (`retries`, `retry_base`), audit
  `llm_retry`; lỗi nội dung không retry. Hết retry → orchestrator hoãn event (`transient:`), nhịp sau thử lại, agent đã
  xong không chạy lại; `stats.transient` tách khỏi `stats.errors`.
- **Ngân sách tiền**: bảng `prices` (USD/1M token, khớp tiền tố model, giá cache) → `audit-log.cost_usd`; supervisor
  warn/cut theo `Task.budget_usd`, pause cả dự án theo `budget_usd`; `report` có `cost_by_agent`, `cost_by_model`,
  `project_cost_usd`, `unpriced_calls`.
- **Tool cho `product` pha research**: đọc repo khách chỉ đọc (không `run`, không ghi) + `web_search`/`fetch_url` khi `--web`
  (chỉ http/https công khai, chặn host nội bộ, bóc HTML, lọc injection, URL vào audit; `COMPANY_SEARCH_URL` cho SearXNG).
- **Chạy song song** `--workers N` trong một tiến trình: bus có RLock, phần xác định vẫn tuần tự; event đổi trạng thái
  chung (gate, kế hoạch, RC, câu hỏi làm rõ) chạy một mình.
- **Metrics** (`metrics.py`, `orchestrator metrics [--prometheus]`): gọi/token/USD/thời gian/cache/tool theo agent, model,
  ticket, dự án; sự kiện sức khoẻ; thời gian chờ gate; lead time ticket; xuất Prometheus text.
- **Trace** (`trace.py`, `orchestrator trace <TICKET|REL-xxx|PROJECT> [--json]`): dòng thời gian một chủ thể từ lượt intake
  tới deploy — mỗi mốc: thời điểm, chờ từ mốc trước, topic/audit action, agent, tier/model, token/USD, tool đã gọi, gate
  mở/quyết (ai, lý do), retry. Chỉ đọc; chủ thể không có → exit 1 (đặc tả nâng cấp B7).
- **Người can thiệp giữa vòng**: `comment` (hint cho ticket đang chạy, không tính retry), `takeover` (người sửa tay trong
  worktree, code chạy lint/test, PR dưới tên người thay PR của agent, review làm lại). Event `tasks` còn trong hàng đợi
  mà ticket không còn `dispatched` (đã `in_review` vì PR của người, hoặc approved/blocked) bị bỏ với audit
  `task.superseded` — không giao backend chạy lại trên worktree đã commit rồi "không sửa gì" ×3 → blocked.
- **Ngân sách review tách khỏi ngân sách ticket** (F16, commit e26139b): token của qa/security
  (`Supervisor.REVIEW_ACTORS`) ghi vào `Budget.review_used`, có trong `sprint_report`/lesson (`review_tokens`), không kích
  hoạt warn/cut của engineer. **Replay dựng RC từ log** (F19): `delivery.py` subscribe `release-candidates`, mở lại bus thì
  `releases`/`release_tickets`/`versions` dựng từ event thật; không tạo lại RC khi `replaying`.
- **Mô phỏng cả công ty** (`examples/donghanhcungban_demo.py`, báo cáo `docs/reports/`): repo khách tạo tạm, chạy trọn vòng
  research → ticket → code → review → release → nghiệm thu bằng client giả, model thật (`--real`) hoặc relay qua file
  (`--relay DIR`, `examples/relay_client.py`: một phiên Claude Code khác trả lời `<n>.req.json`); `--resume` chạy tiếp.
  Phát hiện F13–F19 từ mô phỏng đều đã sửa (bảng trong báo cáo).
- Test: 2000 ca pytest gồm golden 6 agent (`tests/golden/`), runner với client giả, bus SQLite, gate, worktree, tool boundary,
  vòng tool, orchestrator với repo git thật, eval ghi/phát lại, adapter tool-use (server HTTP giả), guard, cắt ngữ cảnh,
  artifact store, retry, bảng giá, tool web (fetcher giả), song song, metrics, comment/takeover, routing nhiều backend,
  release flow và replay; ruff + mypy sạch, coverage 100% (`fail_under = 100`; `graph.py` không tính).
- **Schema là nguồn sự thật**: bus validate đủ JSON Schema (enum, type, ràng buộc) cho cả payload và envelope;
  envelope có `schema_version`, `correlation_id`, `causation_id`. `tests/test_schema_consistency.py` khoá schema ↔ model.
- **Blackboard phân vùng theo dự án** (ADR-0018): artifact thuộc một `project_id`, chỉ `knowledge` là chung.
- **Lint/test theo stack** (ADR-0013): Python, Node, Go, Rust, Gradle, Maven; stack lạ thì `local_checks` nói rõ
  không kiểm được thay vì báo pass giả.
- **Cổng eval có răng**: CI chạy `--replay --strict`; agent trong `evals/recordings/REQUIRED.txt` thiếu bản ghi
  hoặc bản ghi ở phiên bản prompt cũ thì đỏ.
- **Ba human gate là gate thật**: spec, release và nghiệm thu của khách (`acceptance`, ADR-0017) — cùng hạn 24h,
  nhắc ở 12h, four-eyes, và quá hạn thì supervisor escalate chứ không im lặng. Kế hoạch KHÔNG có gate (ADR-0037):
  `_check_plan` chặn bằng code rồi giao ticket ngay; có `problems` thì `plan_rejected` + gate `escalation`.
- **Cắt blackboard theo vai trò + trần prompt theo agent** (ADR-0020): `context_namespace_read` / `max_input_chars` trong
  front matter; runner cắt payload/blackboard theo `context.py` nên qa/security không còn nhận toàn văn blackboard.
- **Lỗi tạm thời của provider** (429, 5xx, đứt mạng) được thử lại có backoff; `Refused` và 4xx thì không. Anthropic
  có timeout nên một request treo không giữ luôn cả orchestrator.
- **Trợ lý kiểm duyệt có hồ sơ bằng chứng** (`docs/dac-ta-tro-ly-kiem-duyet.md`, đủ 6 PR): 10 subagent Claude Code chỉ đọc
  (`sc-<agent>` theo góc nhìn từng agent + `sc-gate-<kind>` theo từng gate, sinh một chiều từ `agents/` và
  `gates/checklists.md`, CI `subagents-check` chặn trôi, `assetscan` quét như tài sản prompt); `gate_brief` rút bằng chứng
  ĐỊNH LƯỢNG cho nửa "người tự kiểm thêm" của gate (NFR có số đo, out-of-scope, câu hỏi mở, ước lượng vs knowledge, ngân sách,
  endpoint ↔ infra, changelog/NOTICE trên diff nhánh tích hợp, môi trường UAT, finding ↔ requirement_id; gate escalation: lịch sử
  thất bại, hint đã dùng và hint lặp, ngân sách còn, worktree) — verdict chỉ `ok|gap|unknown`, mở SQLite `mode=ro`, trích ≤ 200 ký
  tự mỗi nguồn; `/gate-brief <subject>` gộp hồ sơ + subagent thành một bản tóm; trợ lý không bao giờ ký (`trusted_decision`
  chỉ tin actor là người — test hồi quy).
- **Giao hàng thật** (ADR-0027, `--deliver`): production được duyệt và deploy → tag chú thích `v<version>` tại đúng sha nhánh
  tích hợp lúc deploy staging (audit `release.staged`, không phải đầu nhánh đã đi tiếp) + fast-forward `company/release`;
  rolled_back/failed → lùi con trỏ về lần giao trước, không lùi đè release sau (`superseded`); tag đã có ở sha khác không bị ghi
  đè (`delivery.tag_conflict`), nhánh bị đụng tay không bị ép (`delivery.diverged`); `--push-remote` đẩy lên remote khách với
  `--force-with-lease` khi lùi, lỗi push chỉ vào audit; bền qua restart; `status.delivery`. `main` của khách vẫn không bị chạm.

### Chưa có
- **Deploy hạ tầng thật**: phần git của giao hàng đã thật (tag + `company/release`, ADR-0027) và `deployed` ở staging
  phải qua smoke do orchestrator tự chạy (ADR-0029), nhưng `ops` pha deploy vẫn mô tả deploy chứ chưa chạy container/k8s/CI-CD cho sản phẩm khách; đưa `company/release` vào `main` là quy trình PR của
  khách. Xung đột giải quyết bằng làm lại trên nền mới, chưa rebase tự động. **Kafka/Redis** thay SQLite khi chạy nhiều
  máy (song song mới ở mức thread trong một tiến trình).
- **Sandbox container mặc định bật**: ba điểm chạy mã của khách (tool `run`, lint/test, lệnh khởi động smoke) đã
  đi qua `Sandbox` (ADR-0035) và `COMPANY_SANDBOX=container` cho mạng tắt + hạn mức, nhưng mặc định `auto` nên
  máy không có docker vẫn chạy `subprocess` — vẫn là mã của khách chạy bằng quyền người vận hành và thấy `HOME`.
  `git` và CLI model không đi qua sandbox (lý do ở `../../SECURITY.md`). Guard injection là lưới chắn theo mẫu,
  không phải hàng rào.
- **Thông báo** (email/chat/webhook) khi gate mở hay quá hạn; **giao diện UAT cho khách**; console chưa hiện hồ sơ
  `gate_brief` cạnh nút duyệt (mới có ở CLI và `/gate-brief`).

### Bước tiếp theo
1. Chạy `make eval-record AGENT=<id>` cho 6 agent với model thật, commit bản ghi để CI eval có răng.
2. Deploy hạ tầng thật cho sản phẩm khách (`ops` pha deploy chạy CI/CD, container) nối tiếp tag/nhánh release của ADR-0027.
3. Adapter bus Redis Streams/Kafka giữ interface hiện tại (kể cả `poll`) để chạy nhiều tiến trình.
4. Console hiện hồ sơ `gate_brief` cạnh nút duyệt; thông báo webhook khi gate mở/quá hạn; giao diện UAT cho khách.

## Thứ tự triển khai khuyến nghị

1. `product` pha plan + `builder` (stack backend) + `qa` pha review + human gate (vòng lõi)
2. `security` (threat model) ngay khi có ticket auth/payment/pii; `ops` pha account ngay khi có khách thật
3. Bật đủ chuỗi nghiên cứu của `product` (intake → research → spec) khi yêu cầu đầu vào hay mơ hồ
4. `builder` stack platform + `ops` pha deploy/docs khi cần deploy thật; stack data khi cần analytics
5. Bật supervisor ngay khi chi phí token vượt dự tính

Đọc `docs/architecture.md` trước, sau đó `docs/standards.md` và `docs/adr/`.

`delivery_contract.py` tiếp thu Ready/Done/Complete và gate no-op-safe từ projects-template,
opt-in qua `ProjectProfile.delivery`; nguồn được ghim, không copy dispatcher hoặc sửa journal.
Xem `docs/adr/0045-selective-template-delivery.md`; file ví dụ là fixture, không approval thật.

`template_handoff.py` xuất policy/schema native và kiểm bundle do projects-template tạo.
Đây chỉ là chuẩn bị dữ liệu, không approval, không thực thi gate, không thay run đã đăng ký.
Xem [hướng dẫn hai chiều](../../docs/integrations/template-handoff.md) và `tests/test_template_handoff.py`.
