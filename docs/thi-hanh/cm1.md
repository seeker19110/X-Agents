# CAMEL-AI — ba ý đáng mượn, thi hành sâu vào repo

Ngày lập 2026-10-11 · căn cứ `main@db96a3a` (#425) · nhánh `claude/blissful-dirac-if7wwx` · Đề bài của chủ dự án: đánh
giá sâu CAMEL-AI (`camel-ai/camel`, `camel-ai/owl`, `camel-ai/oasis`; Workforce, "Code-as-Prompt", bốn nguyên tắc, OWL
69.09 GAIA, "millions of agents") rồi *"thứ đáng mượn là ba ý tưởng … triển khai tích hợp sâu vào dự án"*.
File này dùng cho phiên `/thi-hanh cm1` và cho người đọc muốn biết ba ý đó rơi vào đâu trong repo.

> Ba con số tiếp thị **không lấy**: 69.09 GAIA là của OWL (một agent khác, một bộ tool khác), "millions of agents" là
> OASIS mô phỏng mạng xã hội, "Code-as-Prompt" là tên gọi cho điều repo đã làm từ ADR-0004 (prompt là code có version).
> Cái đáng lấy là ba **cơ chế**, mỗi cơ chế giải một chỗ hở có bằng chứng ở đây.

## A. Hiện trạng

### A1. Kết luận

- **Ý 1 "tách planner khỏi coordinator"**: repo **đã tách** — `product[plan]` (model) lập kế hoạch, `DeliveryLead` (code)
  điều phối; lời đánh giá "gộp hai vai" sai. Chỗ hở thật nằm ở **nấc leo thang**: coordinator hết retry chỉ có
  `blocked` → gate escalation (reopen/close), không có "cắt lại việc"; QLKH 2026-09-05/06 reopen 7 lần cùng một ticket.
- **Ý 2 role-play trước research**: pha `research` là một lượt model, phản biện duy nhất là mục `risks` do chính pha
  `spec` tự rà (ADR-0050 §Bối cảnh). Repo chưa có hai góc nhìn trước khi PRD được viết.
- **Ý 3 GAIA cho `keeper`**: keeper chỉ đo bằng test nội bộ + eval replay (ADR keeper 0001/0002); không có thước ngoài
  nào để biết "sửa patch xong, năng lực giải việc có tụt không".
- Cả ba đều làm được **không đụng prompt** (`agents/`, `skills/`) nên không cần `make eval-record` model thật trong
  phiên này; phần prompt đọc `debate` để lại thành việc chờ người (C3 theo 7 bước).

### A2. Bảng đối chiếu

| # | CAMEL-AI có gì | Repo có gì | Ở đâu | Mã việc |
|---|---|---|---|---|
| 1 | Workforce: planner tách coordinator; coordinator hết cách thì xin lập lại kế hoạch | Planner/coordinator đã tách; leo thang chỉ retry → người | `orch/ticket_fsm.py::_plan`, `delivery.py::_retry`, `orch/gates_flow.py::_check_escalations` | R1–R4 |
| 2 | — | Đường "CR accepted → planner lập thẳng" đã có và có test | `orch/routes.py::PLAN_INPUTS`, `test_orchestrator.py::test_change_request_impact_then_human_decision_then_plan` | R1 (tái dùng) |
| 3 | — | Máy không ghi `gate.decide` (bus chặn, `_trusted` không tin) — cố ý sau sc-security 2026-09-23 | `bus.py::_extra_publish_checks`, `gate_cli._trusted` | R3 |
| 4 | `RolePlaying`: hai vai luân phiên, `chat_turn_limit`, chỉ user/critic được kết thúc | Một lượt `research`, không phản biện | `orch/routes.py` route research, `agents/research/product.md` | P1–P3 |
| 5 | `RolePlaying` không có hạn mức token | `FakeClient(tokens_per_call)`, `Pricing.cost` sẵn để đặt trần | `llm.py` | P1 |
| 6 | OWL đo GAIA bằng scorer chính thức (`question_scorer`) | Không có thước ngoài; keeper có `Signal`/`RiskRule`/triage sẵn | `keeper/events.py`, `keeper/risk.py` | G1–G3 |

## B. Kế hoạch

| Mã | Việc | Mảng | Hạng mục | Mức | Ưu | Nhược | Khi nào |
|---|---|---|---|---|---|---|---|
| G1 | `keeper.benchmark`: scorer chính thức GAIA, prompt gốc, `load_tasks`, ba solver, `Report`, CLI | keeper | cm1-gaia | C2 | Thước ngoài, offline được (recorded) | Chưa có dữ liệu thật trong repo | xong `4027805` |
| G2 | Sàn `benchmarks/gaia/floor.yaml` (null = đỏ) + `benchmark_signal` → `Signal(kind=benchmark)` + `RiskRule high` | keeper | cm1-gaia | C2 | Tụt điểm đi đúng vòng triage | Sàn phải đo lần đầu bằng model thật | xong `4027805` |
| G3 | ADR keeper 0003, CODEMAP, CLAUDE.md, README keeper 890 test, pragma ledger console | docs | cm1-gaia | C1 | — | — | xong `4027805` |
| P1 | `src/company/roleplay.py`: `RolePlay` hai vai, `turn_limit` + `token_budget`, chỉ critic kết thúc, `Debate.as_audit` | company | cm1-roleplay | C3 | Hai góc nhìn trước PRD, có trần | Thêm 2–4 lượt model mỗi dự án khi bật | xong (commit này) |
| P2 | Enrich `_with_debate` ở route research; `--debate N`/`COMPANY_DEBATE_TURNS`; mặc định tắt; lỗi không chặn research | company | cm1-roleplay | C2 | Không đổi hành vi khi tắt | — | xong (commit này) |
| P3 | ADR-0050, CODEMAP, HUONG-DAN-VAN-HANH, `assetscan` quét `roleplay/` | docs | cm1-roleplay | C1 | — | — | xong (commit này) |
| P4 | `product.md` pha research đọc `debate` (tăng version, golden, **eval-record model thật**, assetscan, assetbudget, subagents) | company | cm1-roleplay | C3 | Debate mới thật sự vào PRD | Cần khoá model thật | **chờ người** |
| R1 | `DeliveryLead._request_replan`: CR `REPLAN-<ticket>-<thế hệ>` khi hết retry; ACL `change-requests` + `LEAD_ACTOR` | company | cm1-replan | C3 | Nấc thứ ba, người vẫn quyết | Thêm một CR mỗi ticket block | xong (commit này) |
| R2 | `_retire_replanned` (từ `_plan`): đóng ticket cũ, audit `ticket.replanned`, rehydrate; checklist `replan:<cid>` | company | cm1-replan | C2 | Trạng thái bền, người thấy ba lựa chọn | Ticket phụ thuộc vẫn blocked + gate riêng | xong (commit này) |
| R3 | `decide-change` ký `reject` gate escalation dưới tên người khi accepted | company | cm1-replan | C2 | Không nới trust của máy | Console chưa có đường quyết CR | xong (commit này) |
| R4 | ADR-0051, CODEMAP, architecture.md, HUONG-DAN-VAN-HANH, golden `gate_brief/escalation.json` | docs | cm1-replan | C1 | — | — | xong (commit này) |
| D1 | File này, 3 dòng CHANGELOG, nhật ký phiên, README số liệu | docs | cm1-docs | C1 | — | — | xong (commit này) |
| G4 | Tải GAIA validation (HF, gated) vào máy có khoá, `python -m keeper.benchmark record` rồi điền `floor.yaml`; job CI tuỳ chọn | keeper | cm1-gaia | C2 | Sàn có số thật | Tốn tiền model thật | **chờ người** |

Thứ tự commit trên nhánh: **cm1-gaia → cm1-roleplay + cm1-replan (+docs)**. Không mở PR (lệnh không yêu cầu).

**Cố ý không làm**: không chép Workforce (coordinator tự cắt ticket — code bịa kế hoạch), không vendor CAMEL (phụ thuộc
nặng, khác ranh giới tool ADR-0010), không lấy số 69.09/“millions” làm mục tiêu, không thêm `decision: replan` vào gate
escalation (lý do ở ADR-0051 §Phương án đã loại).

## C. Gói việc

### cm1-gaia — `4027805`
`companies/keeper/src/keeper/benchmark.py`, `benchmarks/gaia/{README.md,floor.yaml,sample.jsonl}`, `tests/test_benchmark.py`
(37 ca), `events.py` SignalKind `benchmark`, schema `maintenance-signals.json`, `risk.py` `benchmark-regression`,
`docs/adr/0003-thuoc-do-ngoai-theo-khuon-gaia.md`. Cổng keeper xanh 100 %; pragma ledger console 4 → 5.

### cm1-roleplay — ADR-0050
`src/company/roleplay.py`, `roleplay/proposer.md`, `roleplay/critic.md`, `orch/enrich.py::_with_debate`, `orch/routes.py`
(research route `enrich`), `orchestrator.py` (ctor `roleplay=`), `orch/cli.py` (`--debate`), `assetscan.py`,
`tests/test_roleplay.py` (17 ca), `tests/test_ranh_gioi_kieu.py` (trần 31). Hai chiều: 17 đỏ trước, xanh sau.

### cm1-replan — ADR-0051
`delivery.py` (`replan_rounds`, `replan_open`, `replans_filed`, `replan_generation`, `_request_replan`, sổ ở
`_on_change_request`), `core.py` ACL, `orch/gates_flow.py` (`_retire_replanned`, checklist, nhánh `closed:already`),
`orch/ticket_fsm.py::_plan`, `orch/cli_cmds.py::decide_change`, `orch/rehydrate.py`, `tests/test_replan_adr0051.py` (10 ca),
`tests/golden/gate_brief/escalation.json`. Hai chiều: 10 đỏ trước (CR rỗng, `PermissionDenied`, `replan_rounds` lạ), xanh sau.

## D. Điều phối

Phiên chính làm cả ba gói (không subagent — mỗi gói ≤ 2 package, test chạy ≤ 3 phút). Mức: G1/P1/R1 là C3 (ADR trước
code), còn lại C1/C2. Dừng hỏi người đúng hai chỗ, đều đã ghi là "chờ người": P4 (eval-record) và G4 (dữ liệu GAIA).

## F. Lệnh thi hành

```bash
scripts/dev-task.sh gate keeper && scripts/dev-task.sh gate company && scripts/dev-task.sh gate console
cd companies/keeper && uv run python -m keeper.benchmark check --recording <bản ghi.json>     # sàn
cd companies/software-company && uv run python -m company.orchestrator --debate 4 run --watch  # bật role-play
uv run python -m company.orchestrator decide-change REPLAN-T-12-1 accepted --by human:po --reason "cắt sai"
```
