# CODEMAP.md — muốn đổi X thì sửa ở đâu

Bảng tra cứu, không phải tài liệu đọc từ đầu. Mỗi dòng: **muốn gì → chạm file nào → phải chạy lại gì**. Chi tiết
từng package ở `<pkg>/CODEMAP.md`.

## Toàn hub

| Muốn | Sửa | Rồi chạy |
|---|---|---|
| Thêm phụ thuộc Python | `<pkg>/pyproject.toml` → `uv lock` ở gốc (một lock cho cả năm) | `uv sync`, CI `audit` |
| Thêm job CI | `.github/workflows/ci.yml` + nối vào `needs` của job `quality` | mở PR để chạy thật, đọc thời gian job |
| Đổi quy tắc tiêu đề PR | `.github/workflows/pr-policy.yml` (job `metadata`) | — |
| Đổi bảo vệ nhánh `main` | ruleset trên GitHub **và** file đối chiếu trong `protection-guard` (ci.yml) | job `protection-guard` đối chiếu hai chiều |
| Đổi quy trình git | `docs/QUY-TRINH-GIT.md` | — |
| Thêm bẫy đã mắc | `TRAPS.md` (hub) hoặc `<pkg>/TRAPS.md` | — |
| Ghi việc đã đổi | `CHANGELOG.md` | — |
| Đổi execution harness: run/task DAG, atomic transition/CAS, evidence, journal (ADR-0019) | `platform/xagents-core/src/xagents_core/execution.py` + ADR-0017 | `scripts/dev-task.sh gate core` |
| Đổi Ready/Done/Complete và pin chuẩn template | `companies/software-company/src/company/delivery_contract.py`, `docs/integrations/projects-template.lock.json` | `scripts/dev-task.sh gate company` |
| Đổi cầu nối spec/plan với projects-template (chỉ dữ liệu, không quyền) | `companies/software-company/src/company/template_handoff.py`, `docs/integrations/template-handoff.md`; protocol và policy từ native DeliveryContract | `companies/software-company/tests/test_template_handoff.py`, `scripts/dev-task.sh gate company` |
| Đổi hợp đồng chất lượng sản phẩm/thiết kế và adapter execution | `companies/software-company/src/company/product_quality.py`, `quality_execution.py`, `docs/PRODUCT-EXCELLENCE.md`, ADR-0018 | `scripts/dev-task.sh gate company`, `scripts/dev-task.sh gate core` |
| Đổi cách orchestrator chạy nghiệm thu quality, gap R6 hay khối console | `companies/software-company/src/company/orch/quality_flow.py`, `orch/quality_release.py`, `quality_floor.py` (R6), `gate_cli.py` (`--quality-profile`), `spec_approval.py` (ai đã duyệt spec, cho Ready), `orch/cli.py` (`--quality-trust`), `platform/console/src/console/quality.py`, ADR-0021, ADR-0022 (mở lại khi candidate đổi) | `scripts/dev-task.sh gate company`, `scripts/dev-task.sh gate console` |
| Cấu hình dev server cho browser pane | `.claude/launch.json` | — |
| Thêm slash command cho Claude Code | `.claude/commands/<tên>.md` | `platform/console/tests/test_cong_khung.py` (canh frontmatter + đường dẫn) |
| Đổi lệnh cổng cục bộ | `scripts/dev-task.sh` — phải khớp đúng `.github/workflows/ci.yml`, lệch là cổng cục bộ khác cổng CI | `uv run pytest tests/test_cong_khung.py` (console) |
| Đổi/thêm hàng rào chặn lệnh | `.claude/hooks/*.sh` + nối trong `.claude/settings.json` | `test_cong_khung.py` — hook không có test là cổng không ai biết còn sống không |
| Luật cho agent KHÔNG phải Claude Code | `GEMINI.md` (bản đầy đủ) + `.cursorrules`/`.windsurfrules`/`.clinerules` | — |
| Trợ lý kiểm duyệt `sc-*` | **không sửa tay** — `companies/software-company/agents/`, `skills/`, `gates/checklists.md` → `make subagents` | commit `.claude/agents/` |

## software-company (`company`) — tóm tắt; đầy đủ ở `companies/software-company/CODEMAP.md`

| Muốn | Sửa | Rồi chạy |
|---|---|---|
| Đổi hành vi một agent | `agents/<khối>/<id>.md` (+ `version`) | 7 bước `CONTRIBUTING.md` §3 |
| Đổi quy tắc chuyên môn dùng chung | `skills/<tên>.md` (+ `version`) | như trên |
| Agent nào nhận topic nào | `ROUTES` trong `src/company/orchestrator.py`; front matter `reads`/`writes` | `tests/test_routing.py`, `test_security_review_fixes.py` |
| Thêm/đổi trường event | `topics/schemas/<topic>.json` **và** model Pydantic trong `src/company/events.py` | `tests/test_schema_consistency.py` |
| Checklist gate | `gates/checklists.md` → nguồn bằng chứng trong `src/company/gate_checklists.py` | `make subagents` |
| Template tài liệu agent viết | `templates/<tên>.md` | — |
| Tool agent được cấp / allowlist `run` | `src/company/tools.py` | `tests/test_tools_and_agentic.py` |
| Lệnh lint/test theo stack khách | `src/company/stacks.py` | — |
| Smoke sau deploy staging | `src/company/smoke.py`, hook `_smoke` trong orchestrator | `tests/test_smoke_evidence.py` |
| Giao hàng (tag, nhánh release) | `Integration.deliver` trong `src/company/workspace.py`, `_deliver` orchestrator | `tests/test_delivery_real.py` |
| Ngân sách, watchdog, escalate | `src/company/supervisor.py`; cơ chế chung ở `platform/xagents-core/src/xagents_core/supervisor.py` (K3.7) | `tests/test_supervisor*.py`, `platform/xagents-core/tests/test_supervisor.py` |
| Adapter provider mới | `src/company/llm.py`; chọn theo tier: `routing.py` | `tests/test_llm_errors_and_misc.py` |
| Ca eval | `evals/<agent>.yaml` → `make eval-record AGENT=<id>` | commit `evals/recordings/` |

## gateway — đầy đủ ở `platform/gateway/CODEMAP.md`

| Muốn | Sửa |
|---|---|
| Cooldown, xoay tài khoản, refresh token | `src/gateway/auth.py` |
| Dịch OpenAI ⇄ Google Code Assist, retry, stream | `src/gateway/client.py` |
| Endpoint HTTP, daemon | `src/gateway/server.py` |
| Hàng rào `Host`/`Origin` (chống DNS rebinding + CSRF) | `guard_middleware` trong `src/gateway/server.py`; `tests/test_guard_host_origin.py` |
| CLI `start/stop/status/login/setup/models` | `src/gateway/manage.py`, `__main__.py` |

## console — đầy đủ ở `platform/console/CODEMAP.md`

| Muốn | Sửa |
|---|---|
| Đọc thêm dữ liệu từ bus công ty | `src/console/collect.py` |
| "Sự thật giao hàng" (phễu release, bế tắc im lặng) | `src/console/truth.py` |
| Duyệt gate | `src/console/decide.py` |
| Giao việc mới (form → bus) | `src/console/submit.py` |
| Đổi model/backend từ trang | `src/console/settings.py` |
| Route HTTP, SSE, token phiên | `src/console/server.py` |
| Giao diện | `src/console/static/index.html` (một file, không framework) |
| Hợp đồng nội bộ giữa các lớp | `platform/console/API.md` |

## keeper — đầy đủ ở `companies/keeper/docs/DAC-TA-KEEPER.md`

| Muốn | Sửa |
|---|---|
| Tên công ty, gốc, tên bus | `companies/keeper/src/keeper/core.py` |
| Topic, model payload, chủ namespace | `companies/keeper/src/keeper/events.py` + `companies/keeper/topics/schemas/` |
| Lộ trình BT1–BT8 (BT1–BT7 đã merge; còn canary BT8, chờ người) | `companies/keeper/docs/DAC-TA-KEEPER.md`; trạng thái ở `docs/thi-hanh/keeper.md` §B; bảng module đầy đủ ở `companies/keeper/CODEMAP.md` |
