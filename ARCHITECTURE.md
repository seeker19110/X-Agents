# ARCHITECTURE.md — bản đồ hệ thống X-Agents

Đọc để biết **thứ gì nằm ở đâu và vì sao**. Chi tiết từng package: `<pkg>/ARCHITECTURE.md`. Muốn đổi một thứ cụ
thể: `CODEMAP.md`.

## Bức tranh lớn

```
                       ┌──────────────── platform/console/ (127.0.0.1:8200) ────────────────┐
                       │  đọc bus SQLite chỉ-đọc của công ty; duyệt gate qua       │
                       │  đúng HumanGate; giao việc qua đúng bus + schema           │
                       └────────────────────────────┬───────────────────────────────┘
                                                     │
                       ┌─────────────────────────────▼─────────────────────────┐
                       │ companies/software-company/  (package company)                  │
                       │ 6 agent · 45 skill · 19 topic                        │
                       │ 3 human gate + escalation                             │
                       │ code thật trên git worktree của khách                 │
                       └────────────────────────────┬───────────────────────────┘
                                                     ▼
                    platform/xagents-core/  (package xagents_core)
                    lõi chung: bus, llm, runner, guard, gate, execution state/journal, trace, metrics, context, sandbox
                                   ▲
                    ┌──────────────┴───────────┐
                    │  llm.yaml: backends      │
        claude-code CLI · codex CLI · platform/gateway/ (127.0.0.1:1123, xoay tài khoản Google) · model local · API
```

Bố cục thư mục (ADR-0011) tách theo vai trò: `platform/` (`xagents-core`, `gateway`, `console`) là hạ tầng dùng
chung không thuộc công ty nào; `companies/` (`software-company`, `keeper`) là các công ty có agent, topic, gate và
khách riêng. `gateway` và `console` KHÔNG nằm trong một công ty vì cả hai phục vụ nhiều hơn một công ty.

Năm package là năm thành viên của một **uv workspace** — một `.venv`, một `uv.lock`. Không có `[project.scripts]`:
mọi entry point là `python -m <package>.<module>`. Repo khách nằm **ngoài** repo này (`--repo <đường dẫn>`).

## Kiến trúc chung của một "công ty"

```
topic (JSON Schema, có key) ──► registry: agent nào nhận topic nào
        │                              │
        ▼                              ▼
   sqlite_bus ◄──── orchestrator ──► runner (vòng lặp tool, guard, cắt ngữ cảnh) ──► routing → llm (adapter từng gói)
        │                 │
        │                 ├── human gate: chờ người duyệt (gate_cli / console)
        │                 └── supervisor: watchdog, ngân sách token, bài học
        ▼
   blackboard (artifact store, namespace theo owner) + audit-log (token thật, chi phí USD)
```

Năm nguyên tắc, mỗi cái có chỗ cắm trong code:

| Nguyên tắc | Nghĩa là | Ở đâu |
|---|---|---|
| **Model quyết định – code hành động** | tính toán, kiểm định, render, deploy, đăng… là code xác định; model chỉ trả JSON | `tools.py`, `workspace.py`, `smoke.py` (company) |
| **Prompt là code** | agent/skill có `version`, golden test, eval ghi/phát lại chạy trong CI không gọi model | `agents/*.md` front matter, `tests/golden/`, `evals/recordings/` |
| **Guardrail có hạn mức** | ngân sách token, retry, timeout đều có ngưỡng; hết ngưỡng → escalate, không đi tiếp | `supervisor.py`, `guard.py`, `context.py` |
| **Self-hosted, resume được** | bus SQLite + execution journal; dừng và chạy tiếp, state dựng lại từ log thay vì context | `sqlite_bus.py`, `execution.py`, `_rehydrate` trong orchestrator |
| **Trung lập provider** | đổi model bằng `llm.yaml`/env, không đổi code hay prompt | `llm.py`, `routing.py`, `docs/DIEU-PHOI-MODEL.md` |

## Ranh giới tin cậy (quan trọng nhất để không tự lừa mình)

Mọi trường mang nghĩa "đã làm được" phải do **code** điền, không phải model:

- PR: `local_checks.verified_by=workspace` — lint/test chạy thật trong worktree (ADR-0010, ADR-0013).
- Release: `release-events.smoke.verified_by=orchestrator` — sản phẩm được khởi động thật, gọi một request thật
  (ADR-0029).
- Identity của event (`env`, `release_id`, `ticket_id`) lấy từ ROUTE, model lệch thì `*_overridden` (#72, #75).

**Không chốt duyệt mức tool — có chủ đích**: thay bằng "không cấp tool thì không có hành động" (`allow_write/allow_run/write_scope`, sandbox, bốn gate công đoạn). Chi tiết: `docs/KIEN-TRUC-4-LOP.md` §A1 mục 4 (A1.4).

Còn lại là lời khai — hữu ích, nhưng chỉ ký gate trên bằng chứng.

## Human gate

| Công ty | Gate | Gác cái gì |
|---|---|---|
| software-company | `spec` → `release` → `acceptance` (+ `escalation`) | PRD; production; khách ký UAT (kế hoạch ticket do `_check_plan` chặn bằng code, không còn gate `plan` từ ADR-0037) |
| keeper | `patch` (BT7 đã merge: `KeeperOrchestrator.ensure_gate` là nơi gọi duy nhất; `release`/`escalation` khai trong `GateKind` nhưng chưa nơi nào mở; chưa qua chu kỳ thật — chờ canary BT8) | patch rủi ro cao: semver major, chạm `xagents-core`/`agents`/`.github`, security ≥ high |

Gate là thật: hạn 24h, nhắc 12h, quá hạn escalate, four-eyes (người duyệt ≠ người tạo; allowlist người duyệt
`COMPANY_GATE_APPROVERS` mặc định tắt). Mỗi gate của software-company có trợ lý kiểm duyệt
chỉ đọc `sc-gate-<kind>` và hồ sơ bằng chứng `gate_brief`.

## CI (`.github/workflows/`)

Bốn workflow. Required check của `main` (`.github/rulesets/main.json`) là **`quality`** và **`metadata`** — tên bất
biến, đổi tên là khoá cửa merge. Trên máy, `scripts/dev-task.sh gate <gói>` chạy đúng lệnh của cặp job
`*-static`/`*-unit` của gói đó. Mục này có cổng (`platform/console/tests/test_cong_tai_lieu.py`): thêm workflow hay
job mà không kể ở đây là `console-unit` đỏ.

**`ci.yml`** — mỗi PR và mỗi push `main`; 19 job, `quality` (`if: always()`) gom 18 job còn lại. Ma trận `*-unit`
và `unit`: ubuntu 3.11 + 3.13, windows 3.13; `core-static`/`keeper-static`: ubuntu + windows.

| Gói | Job | Chạy gì |
|---|---|---|
| software-company | `static`, `unit`, `eval-replay`, `asset-scan` | ruff + mypy · pytest `-n auto` coverage 100 · `company.evals all --selftest` rồi `--replay --strict` · `assetscan scan` + `budget` (ADR-0022) |
| gateway | `gateway-static`, `gateway-unit` | ruff + mypy · pytest coverage 100 |
| console | `console-static`, `console-unit` | ruff + mypy · pytest coverage 100 — gồm cả các cổng của repo (`tests/test_cong_*.py`, `test_readme_goc.py`) |
| xagents-core | `core-static`, `core-unit` | ruff + mypy (`strict = true` trong `pyproject.toml`) · pytest coverage 100 |
| keeper | `keeper-static`, `keeper-unit`, `keeper-eval-replay`, `drift-check` | ruff + mypy · pytest coverage 100 · `keeper.evals all --replay --strict` · `keeper.cli drift --repo .` (ba phép so cục bộ: `sc-*` và golden lệch `version` nguồn, CHANGELOG còn chỗ trống số PR kiểu `(#PENDING)`) |
| hai công ty | `golden-check` | golden agent sinh lại phải khớp bản đã commit (ma trận `software-company`, `keeper`); riêng software-company: `company.subagents check` (`.claude/agents/sc-*` khớp nguồn) |
| phiên Claude Code | `vendor-check` | `make vendor-check` → `scripts/vendor_skills.py check` cho mỗi lock có `select`: tải nông nguồn tại commit ghim, sinh lại rồi so `.claude/*/<tiền tố>*` + lock (ADR gốc 0028, 0030; cần github.com) |
| toàn repo | `audit`, `protection-guard`, `quality` | pip-audit (một `uv.lock`) + gitleaks cả lịch sử · ruleset trong file ↔ ruleset thật, hai chiều · gom kết quả |

**`pr-policy.yml`** — mỗi PR (kể cả sửa thân PR, gắn/gỡ nhãn); job `metadata`: tiêu đề Conventional Commits, scope
một từ chữ thường · PR thêm ít nhất một dòng vào `CHANGELOG.md`, không bắt `(#<số PR>)`
(`scripts/pr_changelog_check.py`; nhãn `no-changelog` để miễn) · PR `fix(` chạm `orchestrator.py`/`orch/` phải dẫn ADR-0034 · mục Definition of Done và
BÁO CÁO XÁC THỰC không còn `- [ ]` (`scripts/pr_dod_check.py`; ô ghi `(sau merge)` được miễn) · thiếu
`docs/sessions/<hôm nay>.md` chỉ cảnh báo.

**`dependency-review.yml`** — mỗi PR; job `dependency-review` chặn phụ thuộc mới có lỗ hổng mức `high` trở lên.
Không phải required check.

**`eval-record.yml`** — chạy tay (`workflow_dispatch`); job `record` ghi lại eval của `company` bằng model THẬT (tốn
tiền) rồi mở PR với bản ghi mới — đường thay cho `make eval-record` khi máy không có khoá API.

## Thuật ngữ ngành ↔ cơ chế ở repo

Repo đặt tên theo việc nó làm, không theo từ vựng tiếp thị; bảng này để một phiên mới đọc "RAG", "memory", "MCP",
"guardrails" là biết cơ chế tương ứng nằm ở đâu, và biết thứ nào **cố ý không có** (đừng đề xuất lại mà không đọc ADR
đã loại). Căn cứ: `docs/reports/2026-10-10-doi-chieu-ba-infographic.md` (24 thuật ngữ + 6 định nghĩa agent, 2026-10-10).
Đường dẫn viết tắt: `core/` = `platform/xagents-core/src/xagents_core/`, `co/` = `companies/software-company/src/company/`.

| Thuật ngữ ngành | Cơ chế ở repo | Ở đâu | Mức |
|---|---|---|---|
| LLM | client theo provider (Anthropic SDK, OpenAI-compatible qua gateway, `claude -p`) + `RoutingClient` xoay backend theo tier | `core/llm.py`, `core/routing.py:200-203`, `platform/gateway/` | có |
| SLM (model nhỏ cho việc nhỏ) | tier `light` (`claude-haiku-4-5`, `gemini-3.8-flash-low`) | `core/llm.py:361-367`; `co/llm.claude-gateway.yaml` | cấu hình có, **chưa agent runtime nào dùng** (`docs/thi-hanh/ib1.md` L1) |
| Prompt | "prompt là code": `agents/*.md` + `skills/*.md` → `AgentSpec.system_prompt(pha)`; golden + bản ghi eval khoá nội dung | `core/registry.py:106-122`; `CONTRIBUTING.md` §3 | có |
| Tokens | ngân sách token **đầu ra** theo ticket/dự án (80 % cảnh báo, 100 % cắt); đầu vào đo bằng **ký tự** (`chars/3.2` ước lượng, đối chiếu `token_estimate` mỗi lượt) | `co/supervisor.py:33-38,143-186`; `core/context.py:28,36-44`; `co/runner.py:515-517` | có |
| Context window | `context.fit` (system trừ trước, payload cắt giữa có nhãn, blackboard water-filling theo namespace), `max_input_chars` theo vai (ADR-0020), `_prune` tool cũ (ADR 0007); phiên Claude Code: auto-compact | `core/context.py:140-240`; `docs/AUTO-COMPACT.md` | có |
| RAG | **không có, cố ý** — bơm toàn văn blackboard + cắt theo mục + tool đọc; điều kiện mở lại: tệp bài học vượt ngân sách ngữ cảnh | `docs/adr/0003-doi-chieu-ruflo.md:64-66`; `docs/adr/0004-doi-chieu-agent-memory.md:58-59`; `docs/reports/2026-10-10-doi-chieu-12-repo-co-che.md:126` | cố ý không |
| Chunking | cắt PRD theo mục `##` có ưu tiên (nghiệm thu > user story > NFR), `cut_middle` 70/30 | `co/prd_context.py:9-49` (ADR gốc 0029); `core/context.py:47-53` | có (theo luật, không theo mô hình) |
| Embeddings / Vector DB | không có (như RAG) | như trên | cố ý không |
| Hybrid search | chỉ keyword: tool `search` regex trong worktree, `web_search` | `co/tools.py:189-200`; `co/web.py:253-260` | một phần |
| Reranking | xếp hạng theo luật: ưu tiên mục PRD; `lessons_for` lọc theo assignee / `risk_tags` / retry, 5 bản mới nhất | `co/prd_context.py`; `co/supervisor.py:217-222` | có (theo luật) |
| Tool calling | `ToolBox`/`ToolSpec` trung lập provider, vòng tool `_tool_loop`, quyền tool theo route (`rw`/`tests`/`ro`/`research`), sandbox fail-closed | `core/tools.py:47-52`; `co/runner.py:309-434`; `co/orch/routes.py:176-196`; `core/sandbox.py` | có |
| Function calling | adapter theo provider: Anthropic `tool_use`, OpenAI `tools[{type:function}]`, Gemini `functionDeclarations` qua gateway | `core/llm.py:735-760,993-995`; `platform/gateway/src/gateway/client.py:510-526` | có |
| Memory | ngắn hạn = `msgs` một vòng tool; làm việc = blackboard theo dự án (bản mới nhất mỗi namespace, mirror ra `<db>.artifacts/`); dài hạn = bus SQLite append-only + namespace `knowledge` + execution journal | `core/blackboard.py`; `core/sqlite_bus.py`; `core/execution.py`; `co/orch/gates_flow.py:293-305` | có; bài học chỉ số, chưa có lời (`ib1` A3) |
| AI Agent | `AgentSpec` (vai, skill, tool, namespace, ngân sách) + `AgentRunner` | `core/registry.py`; `core/runner.py`; `co/runner.py` | có |
| Agentic workflow | máy trạng thái ticket `Orchestrator` + `ROUTES` (ADR công ty 0034); `/thi-hanh` cho phiên người lái | `co/orchestrator.py:366-431`; `co/orch/routes.py:157-204`; `docs/KHUON-THI-HANH.md` | có |
| Agentic AI (tự chủ hướng mục tiêu) | tự chủ **có trần**: model quyết định – code hành động; human gate `spec → release → acceptance`; ngân sách; sandbox | `core/gates.py:64-108`; §"Ranh giới tin cậy" ở trên | có, giới hạn cố ý |
| Multi-agent system | 6 agent company + 10 agent keeper; **manager là code** (orchestrator), không phải agent LLM; bus topic có JSON Schema + ACL; shared memory = blackboard | `co/roles.py:31-53`; `companies/keeper/src/keeper/core.py:30-38`; `core/bus.py:49,74-75` | có |
| Planner | pha `plan` của `product` + `_check_plan` bác kế hoạch theo luật (estimate, budget ×1,5, acceptance, 1 ngày/200k, risk_tags, phụ thuộc vòng), `PLAN_REWORKS=1` rồi escalation | `co/orch/guards.py:312-360`; `co/orch/ticket_fsm.py:102-165` | có |
| Evaluator | human gate + checklist; `evals --replay --strict` + sàn điểm; reviewer ký Ed25519 (ADR gốc 0024/0025); `quality_execution`/`quality_floor` (ADR công ty 0018/0043); smoke do orchestrator chạy | `companies/software-company/gates/checklists.md`; `co/evals.py:219-221`; `co/gate_reviewer.py`; `co/quality_floor.py:102-147` | có |
| Guardrails | `guard.py` (injection: nội bộ từ chối, ngoài lọc), ACL topic/namespace, sandbox mạng tắt, ngân sách, `assetscan`/`assetbudget` (ADR công ty 0022), gitleaks; phiên người lái: `.claude/hooks/` | `core/guard.py`; `co/assetscan.py`; `AGENTS.md` §"Hàng rào thi hành" | có; không lọc PII đầu ra (chưa có sự cố) |
| Observability | `audit-log` có cấu trúc, `metrics --prometheus`, `trace <id>`, console SSE, execution journal; span `observe.py` có cơ chế | `co/metrics.py`; `co/trace.py`; `core/observe.py` | một phần: `runner.sink = None` chưa nối, `correlation_id` đứt hai chỗ (`ib1` Q1–Q2) |
| MCP | cầu MCP **nội bộ** (`ProxyServer` stdio JSON-RPC 2.0, `2025-06-18`) đưa tool công ty vào `claude -p`; `--restricted` không tắt nó | `co/mcp_bridge.py`; `co/llm.py:472-505`; ADR công ty 0024 | có (nội bộ); không có server cho bên ngoài |
| A2A | không có; bus nội bộ thay thế | `docs/reports/2026-09-27-agent-frameworks.md:40` | cố ý hoãn |
| Skills (ảnh 3) | 45 skill công ty nạp vào system prompt theo `skills`/`skills_core`/`phases`; `.claude/skills` chỉ cho phiên người lái (`ecc-*`, `mp-*` vendor ghim commit) — agent công ty chạy `--restricted` nên **không thấy** | `core/registry.py:136-160`; `docs/adr/0028-*.md`, `docs/adr/0030-*.md` | có, hai lớp tách biệt |
| Single-agent (ảnh 3) | một ticket một agent mỗi pha, tool + memory theo route | `co/orch/routes.py` | có |
| Agentic RAG (ảnh 3) | agent tự quyết đọc gì bằng `read_file`/`search`/`web_search`/`fetch_url`; không retriever; **chưa** đọc được artifact blackboard bị cắt | `co/tools.py:231-250`; `co/web.py:284-292` | một phần (`ib1` A1) |

## Lịch sử repo (đọc `git log` cho đúng)

Repo này bắt đầu là fork của `humanlayer/12-factor-agents` (khoảng 200 commit "Update factor-…", "wip on wtg"…), rồi
chứa dự án MEP-Agents/CAD (08/2026, có hai lần revert chéo). **Đầu thực của X-Agents là `2438d2f` (2026-09-02, "Add
software-company AI agent framework")**; `d4abda1` cùng ngày gỡ MEP-Agents. Muốn xem lịch sử có nghĩa:
`git log 2438d2f..main`. Không rewrite lịch sử cũ — chỉ cần biết mốc.

## Tài liệu nguồn

| Câu hỏi | Đọc |
|---|---|
| Cài và vận hành từng bước | `docs/HUONG-DAN-VAN-HANH.md` |
| Model nào cho agent nào, xoay quota ra sao | `docs/DIEU-PHOI-MODEL.md` |
| Dừng khẩn, lịch trực, thứ chưa có | `docs/TRUC-VA-DUNG-KHAN.md` |
| Git: nhánh, PR, CI, worktree | `docs/QUY-TRINH-GIT.md` |
| Sửa agent/skill phải chạy lại gì | `CONTRIBUTING.md` |
| Thi hành một đề bài lớn từ đặc tả tới PR merge, một lệnh | `docs/KHUON-THI-HANH.md`, `/thi-hanh` |
| Bốn lớp Prompt/Agent/Loop/Graph: hiện trạng, tám việc, gói việc, điều phối subagent, khuôn công ty mới | `docs/KIEN-TRUC-4-LOP.md` |
| Bảo mật: bí mật, phòng thủ, báo lỗi | `SECURITY.md` |
| Vì sao quyết định thế này | Bốn dãy ADR, mỗi dãy đánh số riêng từ 0001, không tiền tố: `docs/adr/` gốc (0001–0028, quyết định cấp repo/quy trình), `companies/software-company/docs/adr/` (0001–0047), `platform/console/docs/adr/` (0001–0004), `platform/gateway/docs/adr/` (0001–0004) |
