# Software Company — Multi-Agent phòng gia công phần mềm

Mô phỏng một công ty gia công phần mềm bằng hệ đa agent event-driven: 7 khối, 20 agent,
mọi trao đổi đi qua topic có key, tri thức chung nằm trên blackboard, con người duyệt ở
3 điểm cố định. Nguyên tắc: tính toán xác định, guardrail có hạn mức, đo token thật,
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
+ shared-context (blackboard 11 namespace)   + audit-log (mọi hành động)
```

## Cấu trúc

```
docs/          kiến trúc, tiêu chuẩn, ADR (0001–0006)
agents/        system prompt từng agent (có version), nhóm theo khối
skills/        35 skill: rule + checklist + ví dụ, theo tiêu chuẩn ngành
gates/         checklist human gate
templates/     PRD, ticket, PR, bug report, postmortem, ADR, threat model, data contract
topics/        18 JSON Schema topic + bảng owner namespace
src/company/   events, bus, sqlite_bus, registry, delivery, supervisor, gates, gate_cli, blackboard,
               llm (ModelClient + adapter), runner, workspace, evals, graph
evals/         ca eval prompt theo agent (YAML)
tests/         pytest (bus, registry↔events nhất quán, delivery+gates, supervisor, golden 22 agent)
```

## Chạy

```bash
cd software-company
uv sync                                   # tạo .venv từ pyproject.toml
uv run pytest -q                          # hoặc: make test
PYTHONPATH=src uv run python -m company.demo   # hoặc: make demo
uv run ruff check src tests               # hoặc: make lint

# Chạy model thật (provider bất kỳ). Cấu hình: cp llm.example.yaml llm.yaml rồi sửa, hoặc biến môi trường:
#   COMPANY_LLM_PROVIDER=openai COMPANY_LLM_BASE_URL=http://localhost:11434/v1 COMPANY_MODEL_STRONG=qwen2.5-coder:32b
#   COMPANY_LLM_PROVIDER=anthropic COMPANY_MODEL_STRONG=claude-opus-5   (uv sync --extra anthropic)
PYTHONPATH=src uv run python -m company.runner reviewer review-results input.json --db company.sqlite
PYTHONPATH=src uv run python -m company.gate_cli list          # hoặc: make gate
PYTHONPATH=src uv run python -m company.evals reviewer         # hoặc: make eval AGENT=reviewer
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_agents.py   # hoặc: make golden — sau khi cố ý sửa agents/ hoặc skills/
```

## Quy ước bắt buộc
- Ticket phải có `estimate_tokens` trước dispatch; `budget_tokens ≥ estimate × 1.5` (code từ chối nếu không).
- Ticket chạm auth/payment/pii/crypto/upload/admin/external-api gắn `risk_tags` → cần thêm review của security-engineer.
- Sửa prompt/skill → tăng `version`, đi qua PR, có eval (ADR-0004). Golden test (`tests/golden/`) đỏ nếu prompt đổi mà version không tăng; cập nhật bằng `make golden`.
- Mỗi PR có rollback plan, observability, license của dependency mới (`templates/pull_request.md`).

## Hiện trạng (2026-09-02)

### Đã có
- Tài liệu: kiến trúc, tiêu chuẩn, ADR 0001–0006; 20 system prompt có version; 35 skill; 8 template; checklist 4 gate.
- 18 JSON Schema topic + bảng owner namespace (thêm change-requests, acceptance-results, external-feedback; namespace contract).
- Lõi xác định trong `src/company/`: envelope/payload pydantic, bus có validate schema, registry nạp prompt+skill,
  delivery-lead (lập lịch depends_on/priority, đóng vòng review, retry, budget, staging QA → gate 3 → production → nghiệm thu),
  supervisor (warn/cut/escalate, sprint_report), gates, blackboard, demo.
- **Runner chạy model thật, trung lập provider** (`runner.py`, `llm.py`, ADR-0005): một interface `ModelClient`;
  adapter `anthropic`, `openai` (mọi server OpenAI-compatible: OpenAI, Ollama, Groq, vLLM, LM Studio...), `fake`.
  Model theo tier cấu hình trong `llm.yaml` / `COMPANY_*`, không nằm trong code hay prompt. Đầu ra ép theo JSON Schema
  của topic, bus validate lại, token thật từ `usage` ghi vào `audit-log`.
- **Bus bền vững SQLite** (`sqlite_bus.py`), cùng interface, replay theo topic/key.
- **Human gate CLI** (`gate_cli.py`): request/approve/reject..., quyết định ghi vào `audit-log`, four-eyes.
- **Workspace theo ticket** (`workspace.py`): git worktree `ticket/<id>`, chạy ruff/pytest thật, trả `local_checks`.
- **Eval prompt** (`evals/*.yaml`, `evals.py`): ca đầu vào + tiêu chí chấm; chạy với provider bất kỳ.
- Test: pytest gồm golden 20 agent (`tests/golden/`), runner với client giả, bus SQLite, gate, worktree, eval offline; ruff sạch.

### Chưa có
- **Vòng lặp tự động**: chưa có orchestrator nối topic → agent liên tục; hiện chạy từng bước bằng `company.runner`
  hoặc code. Bước kế tiếp là `company.orchestrator` subscribe bus và gọi runner theo `reads` của từng agent.
- **Tool cho agent ngoài lint/test**: chưa có tool đọc/sửa file, tìm kiếm code, gọi API cho khối kỹ thuật; agent mới
  sinh JSON, chưa tự viết code vào worktree.
- **CI/CD, deploy thật** cho release-engineer/platform; **Kafka/Redis** thay SQLite khi chạy nhiều máy.
- **Giao diện gate** ngoài CLI; thông báo (email/chat) khi gate quá hạn.
- **Eval mới phủ reviewer, qa-debugger, researcher, account-manager**; cần ca eval cho 16 agent còn lại và chạy khi `version` tăng (CI).
- **Giao diện UAT cho khách**: nghiệm thu hiện qua account-manager ghi `acceptance-results` bằng CLI/code.

### Bước tiếp theo
1. `company.orchestrator`: vòng lặp subscribe → chọn agent theo `reads` → runner → publish; dừng khi supervisor pause.
2. Tool thực thi cho khối kỹ thuật (đọc/sửa file trong worktree, chạy lệnh có allowlist), nối vào runner qua tool-use.
3. Eval cho các agent còn lại; chạy eval trong CI khi prompt/skill đổi version.
4. Adapter bus Redis Streams/Kafka giữ interface hiện tại; giao diện web cho human gate.
5. Sau vòng lõi: security-engineer khi có `risk_tags`, khối nghiên cứu, platform/release/support-docs, supervisor.

## Thứ tự triển khai khuyến nghị

1. delivery-lead + backend + reviewer + qa-debugger + human gate (vòng lõi)
2. security-engineer (threat model) ngay khi có ticket auth/payment/pii; account-manager ngay khi có khách thật
3. Thêm khối nghiên cứu (intake + researcher + synthesizer...) khi yêu cầu đầu vào hay mơ hồ
4. platform + release-engineer + support-docs khi cần deploy thật; data khi cần analytics
5. Bật supervisor ngay khi chi phí token vượt dự tính

Đọc `docs/architecture.md` trước, sau đó `docs/standards.md` và `docs/adr/`.
