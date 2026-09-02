# Software Company — Multi-Agent phòng gia công phần mềm

Mô phỏng một công ty gia công phần mềm bằng hệ đa agent event-driven: 7 khối, 22 agent,
mọi trao đổi đi qua topic có key, tri thức chung nằm trên blackboard, con người duyệt ở
3 điểm cố định. Nguyên tắc: tính toán xác định, guardrail có hạn mức, đo token thật,
cô lập workspace theo ticket, prompt là code. Đây là "công ty AI" đầu tiên trong hub X-Agents.

## Các khối

| # | Khối | Agent | Vai trò |
|---|------|-------|---------|
| 1 | Nghiên cứu yêu cầu | intake, domain, ux-designer, codebase, tech-scout, synthesizer, risk, clarifier, spec-writer | Biến ý tưởng thô thành PRD có tiêu chí nghiệm thu + UX flow |
| 2 | Quản lý dự án | delivery-lead | Kiến trúc, ước lượng, chia ticket, điều phối, đóng vòng |
| 3 | Kỹ thuật | backend, frontend, mobile, database, platform, data | Code / hạ tầng / dữ liệu trên branch riêng theo contract |
| 4 | Chất lượng | reviewer, qa-debugger, security-engineer | Review; test + tìm nguyên nhân; threat model, DAST, license, PII |
| 5 | Vận hành | release-engineer, support-docs | Merge, CI/CD, deploy; tài liệu, incident |
| 6 | Giám sát | supervisor | Watchdog, ngân sách token, knowledge base, version prompt |
| 7 | Human gate | (con người) | Duyệt spec, plan, release; ký rủi ro/license/PII |

## Luồng chính

```
research-requests → approved-specs → tasks (keyed by ticket) → pull-requests
      → review-results (reviewer + qa [+ security khi risk_tags]) → release-events
      → incidents → tasks (vòng bảo trì)
+ shared-context (blackboard 11 namespace)   + audit-log (mọi hành động)
```

## Cấu trúc

```
docs/          kiến trúc, tiêu chuẩn, ADR (0001–0004)
agents/        system prompt từng agent (có version), nhóm theo khối
skills/        29 skill: rule + checklist + ví dụ, theo tiêu chuẩn ngành
gates/         checklist human gate
templates/     PRD, ticket, PR, bug report, postmortem, ADR, threat model, data contract
topics/        JSON Schema cho từng topic + bảng owner namespace
src/company/   events (pydantic), bus, registry, delivery, supervisor, gates, graph
tests/         pytest (bus, registry↔events nhất quán, delivery+gates, supervisor)
```

## Chạy

```bash
cd software-company
uv sync                                   # tạo .venv từ pyproject.toml
uv run pytest -q                          # hoặc: make test
PYTHONPATH=src uv run python -m company.demo   # hoặc: make demo
uv run ruff check src tests               # hoặc: make lint
```

## Quy ước bắt buộc
- Ticket phải có `estimate_tokens` trước dispatch; `budget_tokens ≥ estimate × 1.5` (code từ chối nếu không).
- Ticket chạm auth/payment/pii/crypto/upload/admin/external-api gắn `risk_tags` → cần thêm review của security-engineer.
- Sửa prompt/skill → tăng `version`, đi qua PR, có eval (ADR-0004).
- Mỗi PR có rollback plan, observability, license của dependency mới (`templates/pull_request.md`).

## Thứ tự triển khai khuyến nghị

1. delivery-lead + backend + reviewer + qa-debugger + human gate (vòng lõi)
2. security-engineer (threat model) ngay khi có ticket auth/payment/pii
3. Thêm khối nghiên cứu (kể cả ux-designer) khi yêu cầu đầu vào hay mơ hồ
4. platform + release-engineer + support-docs khi cần deploy thật; data khi cần analytics
5. Bật supervisor ngay khi chi phí token vượt dự tính

Đọc `docs/architecture.md` trước, sau đó `docs/standards.md` và `docs/adr/`.
