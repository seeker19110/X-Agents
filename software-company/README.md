# Software Company — Multi-Agent phòng gia công phần mềm

Mô phỏng một công ty gia công phần mềm bằng hệ đa agent event-driven: 7 khối, 18 agent,
mọi trao đổi đi qua topic có key, tri thức chung nằm trên blackboard, con người duyệt ở
3 điểm cố định. Thiết kế kế thừa nguyên tắc của MEP-Agents trong repo này: tính toán
xác định, guardrail có hạn mức, đo token thật, cô lập workspace theo phiên.

## Các khối

| # | Khối | Agent | Vai trò |
|---|------|-------|---------|
| 1 | Nghiên cứu yêu cầu | intake, domain, codebase, tech-scout, synthesizer, risk, clarifier, spec-writer | Biến ý tưởng thô thành PRD có tiêu chí nghiệm thu |
| 2 | Quản lý dự án | delivery-lead | Kiến trúc, chia ticket, điều phối, đóng vòng |
| 3 | Kỹ thuật | backend, frontend, mobile, database | Viết code trên branch riêng theo contract |
| 4 | Chất lượng | reviewer, qa-debugger | Review + security; test + tìm nguyên nhân |
| 5 | Vận hành | release-engineer, support-docs | Merge, CI/CD, deploy; tài liệu, incident |
| 6 | Giám sát | supervisor | Watchdog, ngân sách token, knowledge base |
| 7 | Human gate | (con người) | Duyệt spec, plan, release |

## Luồng chính

```
research-requests → approved-specs → tasks (keyed by ticket) → pull-requests
      → review-results → release-events → incidents → tasks (vòng bảo trì)
+ shared-context (blackboard)   + audit-log (mọi hành động)
```

## Cấu trúc

```
docs/          kiến trúc, tiêu chuẩn, ADR
agents/        system prompt từng agent, nhóm theo khối
skills/        tiêu chuẩn ngành dạng skill file: rule + checklist + ví dụ
gates/         checklist human gate
templates/     PRD, ticket, PR, bug report, postmortem, ADR
topics/        JSON Schema cho từng topic
src/company/   events (pydantic), bus, registry agent, supervisor, gates, graph
tests/         pytest
```

## Chạy

```bash
uv run pytest software-company/tests -q
uv run python -m software_company.demo   # chạy thử một ticket qua toàn bộ vòng
```

## Thứ tự triển khai khuyến nghị

1. delivery-lead + backend + reviewer + qa-debugger + human gate (vòng lõi)
2. Thêm khối nghiên cứu khi yêu cầu đầu vào hay mơ hồ
3. Thêm release-engineer, support-docs khi cần deploy thật
4. Bật supervisor ngay khi chi phí token vượt dự tính

Đọc `docs/architecture.md` trước, sau đó `docs/standards.md`.
