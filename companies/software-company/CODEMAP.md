# CODEMAP.md — software-company: muốn đổi X thì sửa ở đâu

## Tài sản prompt (đổi là phải đi 7 bước `../../CONTRIBUTING.md` §3)

| Muốn | Sửa |
|---|---|
| Hành vi một agent: PHẢI / KHÔNG ĐƯỢC / DoD / đầu ra | `agents/<khối>/<id>.md` — sáu file sau ADR-0037: `research/product.md`, `engineering/builder.md`, `quality/qa.md`, `quality/security.md`, `operations/ops.md`, `supervisor/supervisor.md`. Hành vi riêng của một PHA nằm trong tiểu mục `### Pha <tên>` (builder: `### Stack <tên>`) của chính file đó, không phải file khác |
| Agent đọc topic nào, ghi topic nào, tier model, ngân sách, tool | front matter của file agent: `reads`, `writes`, `model_tier`, `budget_tokens_per_task`, `tools`, `skills`, `skills_core` |
| Skill chỉ nạp ở MỘT loại lượt của agent | `phases:` trong front matter agent (ADR-0037); lượt nào chạy pha nào: `phase=` của `Route`, hoặc `stack` của ticket với route sửa code (`orch/routes.py::phase_for`) |
| Đổi tên / id một agent (ADR-0037) | `src/company/roles.py` — NƠI DUY NHẤT id agent là chuỗi trong `src/` (`ROLE.*`, nhãn `SOURCE.*` của review, `LEAD_ACTOR`); mọi route/producer/chủ namespace/`truth.py` console tham chiếu hằng; `tests/test_roles.py` chặn literal viết tay và đối chiếu hai chiều với front matter |
| Quy tắc chuyên môn dùng chung | `skills/<tên>.md` (45 file: tiêu chuẩn + quy trình + quy tắc + checklist + ví dụ tốt/xấu); agent chủ quản nạp đầy đủ, agent tuân thủ nạp rút gọn (ADR-0008) |
| Mẫu tài liệu agent phải viết theo | `templates/*.md` (prd, ticket, pull_request, adr, threat_model, runbook, uat_script…) |
| Ca eval của agent | `evals/<id>.yaml`; bản ghi `evals/recordings/<id>.json`; agent bắt buộc có bản ghi: `evals/recordings/REQUIRED.txt` |
| Miễn trừ assetscan có lý do | `assetscan-waivers.txt` |

## Luồng và hợp đồng

| Muốn | Sửa | Test đối chiếu |
|---|---|---|
| Agent nào nhận event nào, điều kiện gì | `ROUTES`, `THREAT_ROUTE`, `PLAN_INPUTS`, `STAGING_ROUTE`/`PROD_ROUTE` trong `src/company/orchestrator.py` | `tests/test_routing.py`; bảng Consumer `docs/architecture.md` |
| Khung event chung (`Envelope`, `AuditLog`, `SharedContext`, `SupervisorAction`, `can_transition`) | `platform/xagents-core/src/xagents_core/events.py` — **LỚP CƠ SỞ** từ K3.5a; `src/company/events.py` kế thừa và thêm trường phạm vi của mình, thu hẹp `topic`/`namespace` về Literal. Model miền, `PAYLOAD_MODELS`, `TRANSITIONS` ở LẠI package | `platform/xagents-core/tests/test_events.py` |
| Thêm/đổi trường của một topic | `topics/schemas/<topic>.json` **và** model trong `src/company/events.py` (`PAYLOAD_MODELS`) | `tests/test_schema_consistency.py` |
| Ai được ghi namespace blackboard nào | `NAMESPACE_OWNERS` trong `events.py`; bảng `topics/README.md` | — |
| Nạp agent/skill từ đĩa (front matter, `phases`, skill rút gọn, cổng chủ quản ADR-0008) | `platform/xagents-core/src/xagents_core/registry.py` từ K3.6a — `src/company/registry.py` chỉ còn `AgentSpec = ` lớp core + ba hàm giữ chữ ký cũ; `ROOT`/`AGENTS_DIR`/`SKILLS_DIR` suy từ `CORE.root` | `platform/xagents-core/tests/test_registry.py`, `tests/test_registry.py` |
| Blackboard (`shared-context`): version, phân vùng dự án, mirror ra file | `platform/xagents-core/src/xagents_core/blackboard.py` từ K3.6b — `src/company/blackboard.py` còn lớp con + bảng `EXT`; `knowledge` là namespace toàn công ty khai ở `CORE.global_namespaces` | `platform/xagents-core/tests/test_blackboard.py`, `tests/test_bus.py`, `tests/test_process_review_fixes.py` |
| Ghi/phát lại eval, cổng bản ghi (`outdated_versions`, `stale_recordings`, `REQUIRED.txt`) | `platform/xagents-core/src/xagents_core/evals.py` từ K3.6c — `src/company/evals.py` giữ `main` (chính sách cổng: `--fail-on-score`, ngưỡng 4L-1a) và `_run_case` (`phase`, ADR-0037) | `platform/xagents-core/tests/test_evals.py`, `tests/test_tools_and_agentic.py` |
| Hình dạng JSON model phải trả (`payload` / `items` / `context_writes`) | `output_schema` + `context_writes_schema` ở `src/company/runner.py` — **`context_writes_schema` là PROMPT, sửa nó là mọi bản ghi eval lệch**; khung ở `platform/xagents-core/src/xagents_core/runner.py` từ K3.6d1 | `platform/xagents-core/tests/test_runner.py`, `tests/test_adr0012.py` |
| Vòng đời một lượt agent (publish, kiểm quyền, ghi blackboard, ghi sổ) | `platform/xagents-core/src/xagents_core/runner.py` `AgentRunner` từ K3.6d2 — `src/company/runner.py` giữ `generate` + vòng lặp tool (chạm prompt), `generate_in_workspace`/`author_tests` (workspace) và sáu hook (`wants_content=True`, `_new_envelope` = `inp.child()`, `_audit_scope`, `_produced_evidence`, `_context_project`, `_extra_audit_on_publish` = sổ `ruling`) | `platform/xagents-core/tests/test_runner.py`, `tests/test_runner_and_persistence.py` |
| Ai được publish topic nào | bảng `TOPIC_PRODUCERS`/`HUMAN_TOPICS` ở `core.py`; cơ chế ở `platform/xagents-core/src/xagents_core/bus.py` `_check_publish` | `tests/test_bus.py`, `platform/xagents-core/tests/test_bus.py` |
| Bus bền vững trên đĩa (ghi, `poll` giữa tiến trình, `replay`, `latest`, `Lease`) | `platform/xagents-core/src/xagents_core/sqlite_bus.py` từ K3.5c — `src/company/sqlite_bus.py` chỉ còn lớp con mỏng ghép bus company + bus đĩa của core; tên file mặc định ở `CORE.db_name` | `platform/xagents-core/tests/test_sqlite_bus.py`, `tests/test_bus.py` |
| Trạng thái ticket và chuyển đổi | `TicketState`, `TRANSITIONS` trong `events.py`; máy trạng thái `src/company/delivery.py` | `tests/test_delivery_and_gates.py` |
| Event nào gọi hàm xử lý nào trong `process()`, trước hay sau vòng `ROUTES` | bảng `TICKET_TRANSITIONS` (`orch/ticket_fsm.py`) / `RELEASE_TRANSITIONS` (`orch/release_fsm.py`) — mỗi nhánh một dòng `Transition`; khung `Transition`/`step()` ở `orch/fsm.py` (ADR-0034). Bảng chỉ chọn hàm, không tự đổi `lead.state` | `tests/test_orch_bang_chuyen.py`, `tests/test_orch_khuon_loi.py` |
| Review nào bắt buộc cho ticket | `DeliveryLead.required_reviews` (`delivery.py`); `RISK_TAGS` trong `events.py` | `tests/test_release_flow.py` |
| Checklist human gate | `gates/checklists.md` → nguồn bằng chứng `src/company/gate_checklists.py` → `make subagents` | `tests/test_gate_brief.py`, `test_subagents.py` |
| Gate: hạn, nhắc, four-eyes, allowlist | Cơ chế chung ở `platform/xagents-core/src/xagents_core/gates.py` + `gate_cli.py` (K3.7); `src/company/gates.py` chỉ còn `GateKind`/`Decision` + `COMPANY_GATE_APPROVERS` (mặc định KHÔNG đặt = chỉ four-eyes như trước), bền qua restart: `gate_cli.PersistentGate` | `tests/test_gate_trust.py`, `platform/xagents-core/tests/test_gates.py`, `platform/xagents-core/tests/test_gate_cli.py` |
| Bậc rủi ro gate + tự động qua (ADR-0011 §4, mặc định TẮT) | `src/company/gate_risk.py` (`RISK_RULES` — hai hàng sàn chất lượng từ ADR-0043, `gate_risk_tier`, `request_gate` thay 12 điểm `gate.request`); cờ `COMPANY_GATE_AUTOAPPROVE` trong `gates.py`; nhánh tin cậy actor `"code"` trong `gate_cli.trusted_autoapprove`/`PersistentGate._trusted`; ACL bus riêng cho actor này ở `bus.py::_extra_publish_checks` | `tests/test_gate_risk.py`, `../../docs/thi-hanh/adr113.md` |
| Lỗi không nhánh nào nhận → gate `escalation` (plan lỗi, threat model `block`, transient quá trần, agent lỗi ngoài stall/rework) | `orch/gates_flow.py::_mark_unhandled` (một cửa, `unhandled` bền qua `agent_error_unhandled`); nơi gọi: `_after_error`, `ticket_fsm._plan`/`_threat_model`, `scheduler._defer` (`transient_limit`, `COMPANY_TRANSIENT_MAX_H`) | `tests/test_tu_van_hanh_khong_ket_im_lang.py` |
| Câu hỏi làm rõ quá hạn → giả định theo `default`, chạy pha `spec` | `orch/ticket_fsm.py::_assume_clarifications` (`clarify_timeout`, `COMPANY_CLARIFY_TIMEOUT_H`), gọi từ `scheduler.tick`; `guards.pending_clarifications`/`assumed_clarifications` (audit `clarification.assumed`) | `tests/test_tu_van_hanh_khong_ket_im_lang.py`, `test_clarification_pending.py` |
| Kế hoạch bị `_check_plan` từ chối → tự trả `product[plan]` sửa `PLAN_REWORKS` lần (kèm `hint`/`previous_plan`) rồi mới `plan_rejected` + gate | `orch/ticket_fsm.py::_plan` (nhánh `problems`, audit `plan.rework`); hằng `PLAN_REWORKS` ở `orch/guards.py`; bộ đếm `plan_reworks` (`orch/state.py`, dựng lại ở `orch/rehydrate.py` từ `plan.rework`+`plan_rejected`, về 0 khi `event.retried`) | `tests/test_plan_tu_sua_truoc_khi_hoi_nguoi.py` |
| `run --watch` khởi động lại hỏng (`execv` ném `OSError`) → chạy tiếp mã cũ, reload tắt, audit `orchestrator.reload_failed` | `orch/cli_cmds.py::run` | `tests/test_auto_reload.py::test_execv_hong_thi_chay_tiep_ma_cu_khong_chet_im_lang` |
| Điều kiện cho phép GIAO ticket (kế hoạch không có gate, ADR-0037) | `_check_plan` trong `orch/ticket_fsm.py` (danh sách `problems`) → `lead.plans_ok` → guard trong `DeliveryLead.dispatch`; dựng lại khi mở bus: `orch/rehydrate.py` nhánh `plan.proposed` | `tests/test_check_plan_adr0037.py`, `tests/test_bo_gate_plan_adr0037.py` |

## Bằng chứng do code sinh

| Muốn | Sửa | Test đối chiếu |
|---|---|---|
| Lint/test thật trong worktree ticket, `local_checks` | `TicketWorkspace.run_checks` (`src/company/workspace.py`); lệnh theo stack: `src/company/stacks.py` |
| Sổ Ruling: trường `rulings` mọi topic, audit `ruling`, `Orchestrator.rulings()`, CLI `rulings`, mục trong gate_brief | `events.py` (`Ruling`), 19 schema, `runner.publish`, `orchestrator.py`, `gate_brief.py` — ADR-0030 |
| Smoke sau deploy staging (`runtime` của spec) | `src/company/smoke.py`; hook `Orchestrator._smoke`; `_release_evidence` mang sang production |
| Deploy thật bằng `docker compose` (`deployed` = container đang chạy; `deploy_failed`; `skipped`) | `src/company/deploy.py` (`deploy`, `DeployRecord`, `project_name`, `COMPANY_DEPLOY*`); hook `orch/verify.py::deploy_release` gọi từ `orch/release_fsm.py::_release`; `runtime.deploy` trong `topics/schemas/approved-specs.json` + `smoke.parse_runtime`; `status`/`evidence` trong `topics/schemas/release-events.json`; bậc phễu console `platform/console/src/console/truth.py`; ADR-0039 |
| SBOM + license cho release-check của security (`evidence.supply_chain`, `sbom_ref`) | `src/company/supply_chain.py` (`_READERS`: `uv.lock`, `package-lock.json`, `Cargo.lock`, `go.mod` ở gốc + thư mục con một tầng; `installed_licenses`, `spdx_of`, `evidence`); hook `orch/verify.py::evidence_before`/`evidence_after` (chung với smoke QA hồi quy); ADR-0046 |
| DAST tối thiểu cho release-check (`evidence.dast`: header, trang lỗi, cookie, burst đăng nhập) | `src/company/dast.py` (`login_op` đọc cửa đăng nhập từ `api-contract`, `scan`, `run_dast` qua `smoke.run_smoke(probe=…)`, `evidence`); hook cùng chỗ `orch/verify.py::evidence_before`/`evidence_after`; ADR-0047 |
| Chấm lại release-check của RC cũ với bằng chứng mới | `orch/release_fsm.py::recheck` (route `RELEASE_CHECK_ROUTE` ở `orch/routes.py`); CLI `recheck <REL> --by human:x\|reviewer:y`; ADR-0047 §5 |
| Diff gửi lượt chấm (`qa[review]`, `security`; ưu tiên mã nguồn, cắt có khai) | `TicketWorkspace.diff`, `GENERATED_PATTERNS` (`workspace.py`) |
| Nhãn `source` của `review-results` (ai chấm, theo góc nhìn nào) — CODE điền từ ROUTE, không tin model khai | `orch/review_source.py` (`source_for`, `enforce_source`); audit `review.source_overridden`; `delivery.py::required_reviews` đếm theo nhãn |
| Reviewer gate có chữ ký (ADR gốc 0024; phạm vi `rong` = mọi gate trừ spec, ADR gốc 0025): khoá, registry, phạm vi, trần, nhánh tin cậy | `gate_reviewer.py` (`decide`, `trusted_reviewer`, `refusal`, `scope_rong`, `machine_acceptor`, CLI `init-key`/`decide --decision`); nối vào `gate_cli.PersistentGate._trusted`/`decide_signed`; ACL bus `bus.py::REVIEWER_PREFIX`; resume dưới tên supervisor `roles.resume_actor`; quy trình phiên độc lập `../../.claude/commands/gate-review.md` |
| Bậc rủi ro gate / cổng tự qua khi rủi ro thấp | `gate_risk.py` (`RISK_RULES`, `GateRiskContext`, `context_of`, `request_gate`); cờ `COMPANY_GATE_AUTOAPPROVE` |
| Identity của lượt do ROUTE quyết, không phải model khai: `source`, `ticket_id` (đầu vào thuộc ticket), `action`/`actor` của đầu ra `audit-log`; `_rehydrate` chỉ tin người ghi thật | `orch/review_source.py`; `orchestrator.py` (`output.subject_overridden`, `output.action_overridden`); `orch/routes.py` (`TICKET_TOPICS`, `CR_IMPACT_ACTION`); `orch/rehydrate.py::TRUSTED_WRITERS` | `tests/test_source_tu_route.py`, `test_identity_tu_route.py`, `test_audit_gia_mao.py`, `test_chu_ky_khach_chi_nguoi.py` |
| Sàn chất lượng tự duyệt release/nghiệm thu (ADR-0043): điều kiện sàn, thu bằng chứng, mức nâng theo dự án | `quality_floor.py` (`floor_gaps` thuần, `collect_evidence`, `project_bar`, `parse_bar`); nơi gọi `delivery.py::_quality_evidence`, `orch/gates_flow.py::_open_acceptance_gate`; đóng ticket khi máy nghiệm thu `DeliveryLead.close_accepted` + `acceptance.auto` (`_rehydrate`); `gate_cli --quality-bar` | `tests/test_quality_floor.py`, `test_quality_bar.py`, `test_quality_collect.py`, `test_gate_risk_quality.py`, `test_tu_duyet_e2e.py` |
| Merge vào nhánh tích hợp, xung đột | `Integration.merge`; `orch/release_fsm.py::_integrate`, `orch/worktree_flow.py::integrate_approved`/`merge_ticket` (gán làm method của `Orchestrator`) |
| Repo theo dự án, worktree mỗi ticket, lượt agent kỹ thuật (`engineer`, `author_tests`), `takeover` | `orch/worktree_flow.py` (tách khỏi `orchestrator.py` theo ADR-0034; `_merge_lock` ở lại `Orchestrator.__init__` vì khoá theo tiến trình) |
| Giao hàng: tag `v<version>`, nhánh `company/release`, push, rollback | `Integration.deliver` / `rollback_delivery`; `_deliver` / `_rollback_delivery` (orchestrator); ADR-0027 |
| PR thật cho khách review trước UAT (`--deliver-pr`): mở/dùng lại, không merge; lý do bỏ qua/lỗi | `github_pr.open_pr` (+ `github_slug`, `_gh`); `orch/release_fsm.py::_delivery_pr` → trường `pr` trong `delivery.done`, audit `delivery.pr_*`; `Integration.remote_url/base_branch`; mục `acceptance.pr-giao-hang` (`gate_brief`, `gate_checklists`); ADR-0038 | `tests/test_delivery_real.py` §ADR-0038, `test_gate_brief.py::test_acceptance_pr_giao_hang…` |
| Tool agent được cấp, allowlist `run`, khoá đường dẫn, lọc env | `src/company/tools.py`; `SECRET_ENV`/`clean_env` ở `platform/xagents-core/src/xagents_core/sandbox.py` (K3.2, `workspace.py` nhập lại), `NO_HOOKS` trong `workspace.py` |
| Vùng ghi của `qa[author]` vs `builder` (ADR-0028) | `Stack.test_globs` (`stacks.py`); phân quyền trong `tools.py`; lượt mù ở `runner.py` |
| Chống prompt injection | Bảng mẫu + lọc: `platform/xagents-core/src/xagents_core/guard.py` (K3.4, chung hai công ty). CHÍNH SÁCH của company — topic nào ngoài/dẫn xuất, trường nào không tin cậy — ở `src/company/core.py` (`CORE`); `src/company/guard.py` chỉ còn là shim gắn `CORE`. Gọi từ `runner.py`, `web.py`, `supervisor.py`, `mcp_bridge.py`; `assetscan.py` quét file prompt bằng `guard.COMPILED` | `tests/test_adr0012.py`, `platform/xagents-core/tests/test_guard.py` |
| Hạn mức ngữ cảnh, cắt | `src/company/context.py` |

## Hợp đồng chất lượng sản phẩm (ADR gốc 0018/0021, `../../docs/PRODUCT-EXCELLENCE.md`)

| Muốn | Sửa | Test đối chiếu |
|---|---|---|
| Profile dự án → hợp đồng check, ký/xác minh biên nhận bằng chứng, chấm | `src/company/product_quality.py` (`ProjectProfile`, `compile_contract`, `sign_evidence`, `verify_receipt`, `assess`; CLI `python -m company.product_quality schema/plan/verify`) — lớp chấm fail-closed, KHÔNG chạy test, KHÔNG thay `HumanGate` | `tests/test_product_quality.py`, `test_receipt_signature.py` |
| Nối hợp đồng vào kernel thi hành (`xagents_core.execution`) | `src/company/quality_execution.py` (`compile_execution`, `evaluate_result` thuần, `commit_quality_result`; CLI `python -m company.quality_execution plan/register/status/commit`) — không scheduler/state machine thứ hai | `tests/test_quality_execution.py`, `test_quality_commit.py` |
| Orchestrator ghim profile lúc ký spec, chiếu `lead.state` sang journal, mở `quality:accept` | `orch/quality_flow.py` (`note_profile`, `sync_quality` gọi ở cuối `scheduler._mark`, `TrustedDriver`, `submit_quality`) — không đụng `TICKET_TRANSITIONS`/`RELEASE_TRANSITIONS` | `tests/test_quality_flow.py`, `test_quality_flow_reopen.py` |
| Gap R6 của sàn chất lượng cho một release (chỉ đọc journal) | `orch/quality_release.py` (`runs_for_release`, `release_quality`) — tách khỏi `quality_flow` vì trần 400 dòng của `orch/` | `tests/test_quality_floor_r6.py` |
| Điều kiện Ready/Done/Complete của hợp đồng giao hàng | `src/company/delivery_contract.py` (`ready_gaps`, `delivery_gaps`, giao thức `ApprovalLookup`; thiếu lookup ⇒ fail-closed) | `tests/test_delivery_contract.py` |
| Ai đã duyệt spec (lookup thật cho pha Ready, đọc bus) | `src/company/spec_approval.py` (`BusApprovalLookup`) — tin `env.actor` của gate `SPEC-<pid>`, không tin lời khai `approved_by` trong profile | `tests/test_spec_approval.py` |
| Cầu nối projects-template (chuẩn bị ≠ duyệt) | `src/company/template_handoff.py` (`prepare_handoff`, `policy_document`; CLI `python -m company.template_handoff policy/prepare`) — không lệnh, không mạng, không ghi file | `tests/test_template_handoff.py` |

## Model và chi phí

| Muốn | Sửa |
|---|---|
| Adapter provider (anthropic / openai / claude-code / codex / fake), retry, bảng giá | `src/company/llm.py` |
| Chọn backend theo tier, xoay khi hết quota, `prefer` | `platform/xagents-core/src/xagents_core/routing.py` (K3.3d — `src/company/routing.py` chỉ còn là shim); cấu hình `llm.yaml` (`llm.example.yaml`, `llm.claude-gateway.yaml`) |
| Tool của công ty vào `claude -p` qua MCP | `src/company/mcp_bridge.py` (ADR-0024); dò chế độ: `probe.py` |
| Ngân sách ticket/dự án, watchdog, pause/escalate, bài học | `src/company/supervisor.py` (kế thừa `xagents_core.supervisor.SupervisorBase` — `sprint_report()` Ở LẠI đây, nó nói về ticket); `BUDGET_FACTOR` trong `events.py` |
| Nợ kiến trúc treo: mã nợ `DEBT_RE`, đếm liên tiếp theo nguồn, bảng `debt_table`; gate cấp dự án `_check_debt`; ngưỡng `debt_reviews` | `supervisor.py`, `orchestrator.py`, `llm.py` (`LLMConfig.debt_reviews`) — ADR-0032 |
| Số liệu từ audit-log | `src/company/metrics.py` |
| Dòng thời gian một ticket/release/dự án (`orchestrator trace <id> [--json]`) | `src/company/trace.py` giữ `resolve`/`_belongs`/`_domain` riêng company; cấu trúc dòng, đọc `audit-log`, tổng kết, cách in ở `platform/xagents-core/src/xagents_core/trace.py` từ 4L-7; test `tests/test_trace.py`, `platform/xagents-core/tests/test_trace.py` |

## Vận hành và giao diện người

| Muốn | Sửa |
|---|---|
| Lệnh CLI orchestrator (`run`, `status`, `diagnose`, `publish`, `redeploy`, `recheck`, `takeover`…) | cờ và subcommand: `_parser()` trong `src/company/orch/cli.py`; **thân từng lệnh**: `src/company/orch/cli_cmds.py` (`BUS_CMDS` chỉ cần bus, `ORCH_CMDS` cần `Orchestrator`) — thêm lệnh mới là thêm parser + một hàm + một dòng bảng; tự khởi động lại khi mã đổi: `run --watch` |
| Hồ sơ bằng chứng gate (`make gate-brief`, `/gate-brief`) | `src/company/gate_brief.py`; slash command `../../.claude/commands/gate-brief.md` |
| Trợ lý kiểm duyệt `sc-*` | `src/company/subagents.py` sinh từ agents + skills + checklists — không sửa tay đầu ra |
| Quét tài sản prompt, ngân sách prompt tĩnh | `src/company/assetscan.py` (ADR-0022) |
| Tool web cho `product` pha research | `src/company/web.py` |
| Mô phỏng cả công ty offline | `src/company/demo.py`, `examples/donghanhcungban_demo.py`, `examples/relay_client.py` |
| Nối agent thành đồ thị LangGraph (tùy chọn) | `src/company/graph.py` (`research_order`, `build_graph`) — extra `[graph]`; không nơi nào trong `src/` gọi, `omit` khỏi coverage vì CI không cài `langgraph` |
| Yêu cầu mẫu để publish | `examples/yeu-cau-mau-web-app.json` |

## Tài liệu phải sửa kèm

| Khi | Sửa |
|---|---|
| Thêm file test / ADR | `README.md` mục "Cấu trúc" (số ca/file test, `ADR (0001–00xx)`) — `tests/test_review_fixes_2026_09.py::test_readme_khop_so_lieu_that` |
| Thêm route / agent | bảng Consumer `docs/architecture.md` — `tests/test_security_review_fixes.py` |
| Thêm guard / enrich cho một route | `orch/guards.py` (vị từ "event này có đi đường này không") hoặc `orch/enrich.py` (làm giàu payload) — KHÔNG thêm vào `orch/routes.py`: nó chỉ giữ bảng + `Route` và nhập một chiều từ hai module kia, nên thêm guard không phải sửa bảng và ngược lại. Cả ba dưới trần 400 dòng của `tests/test_orch_khuon_loi.py` |
| Đổi kiến trúc | `docs/adr/00xx-*.md` + link trong PR |
| Sự cố vận hành đáng kể | `docs/reports/<ngày>-<slug>.md` + mục trong `TRAPS.md` |
