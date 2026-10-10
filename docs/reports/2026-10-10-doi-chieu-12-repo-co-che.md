# Đối chiếu 12 repo GitHub về cơ chế vận hành agent — 2026-10-10

Yêu cầu: *"tìm kiếm trên github các repo nổi tiếng có chức năng tương tự và phân tích học hỏi những điểm tốt áp dụng
cho dự án này"*, rồi *"tổng hợp rồi nâng cấp thêm nha"*. "Chức năng tương tự" ở đây là **cơ chế vận hành** của một hệ
nhiều agent làm phần mềm: điều phối, human gate, bền/resume, ngân sách và chi phí, guardrail, review và merge, bộ nhớ,
test offline, sandbox, và bot mở PR bảo trì. Hai báo cáo trước đã phủ phần khác: `2026-09-27-agent-frameworks.md`
(15 framework, đọc README) và `2026-10-10-doi-chieu-tu-van-da-dang.md` (6 repo spec/template). Mười hai repo dưới đây
chưa có trong hai bản đó.

Làm theo `docs/PROMPT-SHEET.md` §H: ba cột **đã có và sâu hơn / đã có nhưng nông hơn / chưa có**; "chưa có" chỉ lấy khi
chỉ ra **sự cố đã xảy ra ở đây**, không có thì xếp "chưa cần" kèm điều kiện quay lại. Không cài gì, không vendor file
nào. Khác bản 2026-10-10 trước (chỉ kết luận), bản này **đi kèm một nâng cấp đã làm** (§3) theo đúng yêu cầu thứ hai.

Cách đọc: ba phiên phụ clone nông vào scratchpad (`repos/`, `repos2/`, `repos3/`), **đọc file, không chạy code nào**
của repo tải về, trích `file:dòng`. Số sao lấy qua WebFetch trang GitHub ngày 2026-10-10 (`gh api` bị 403 qua proxy),
do một model nhỏ tóm tắt — độ tin cậy vừa, chỉ để biết độ phổ biến tương đối. Mọi câu phiên phụ nói về **X-Agents** đều
được đối chiếu lại với mã nguồn ở đây trước khi xếp cột; một câu sai, ghi ở §5.

## 1. Nguồn đã đọc (clone nông, đọc file, không tin README)

| Repo | Commit | License | Sao | Phần đọc |
|---|---|---|---|---|
| `geekan/MetaGPT` | `11cdf466` | MIT | 70,8k | `roles/role.py`, `team.py`, `utils/common.py` (serialize khi crash), `utils/cost_manager.py`, `actions/run_code.py`, `actions/write_code_review.py`, `exp_pool/`, `tests/conftest.py`, `tests/metagpt/serialize_deserialize/test_team.py` |
| `OpenBMB/ChatDev` (main = "2.0 DevAll") | `4fb2db0e` | Apache-2.0 | 34,5k | `yaml_instance/ChatDev_v1.yaml`, `workflow/cycle_manager.py`, `runtime/node/executor/human_executor.py`, `server/services/session_store.py`, `utils/token_tracker.py` |
| `OpenBMB/ChatDev` nhánh `chatdev1.0` | `31fd9944` | Apache-2.0 | — | `chatdev/chat_chain.py`, `composed_phase.py`, `chat_env.py` (`exist_bugs`), `phase.py`, `statistics.py`, `ecl/memory.py`, `CompanyConfig/Default/PhaseConfig.json` |
| `Pythagora-io/gpt-pilot` | `9b763fda` | **FSL-1.1-MIT (không phải OSI)** | 33,6k | `core/agents/orchestrator.py`, `executor.py`, `code_monkey.py`, `core/state/state_manager.py`, `core/proc/process_manager.py`, `core/db/models/{exec_log,llm_request}.py`, `tests/state/test_state_manager.py` |
| `VRSEN/agency-swarm` | `973286cb` | MIT | 4,6k | `agency/core.py`, `tools/send_message.py`, `agent/execution_guardrails.py`, `utils/usage_tracking.py`, `tests/deterministic_model.py`, `hooks.py` |
| `crewAIInc/crewAI` | `6b93fa0e` | MIT | 59,5k | `crew.py`, `task.py` (guardrail), `agents/crew_agent_executor.py`, `flow/human_feedback.py`, `flow/persistence/sqlite.py`, `state/checkpoint_*.py`, `utilities/rpm_controller.py`, `memory/unified_memory.py`, `lib/conftest.py` |
| `ag2ai/ag2` | `197d35a5` | Apache-2.0 | 5,0k | `agent.py`, `history.py`, `_replay.py`, `hitl.py`, `events/base.py`, `observers/{token_monitor,loop_detector}.py`, `policies/alert.py`, `testing.py`, `tools/sandbox/` |
| `ruvnet/claude-flow` | `ca74bd4f` | MIT | 74,3k | `v3/@claude-flow/cli/src/services/{global-ai-budget,checkpoint-gate,harness-verify,harness-replay,headless-worker-executor}.ts`, `mcp-tools/tool-loop-guardrail.ts`, `security/src/{tool-output-guardrail,safe-executor}.ts`, `security/src/policy/engine.ts`, `swarm/src/queen-coordinator.ts` |
| `langgenius/dify` | `2ac4c221` | Apache-2.0 có sửa | 158,1k | sparse `api/core/{workflow,app,agent}`, `api/tasks/human_input_timeout_tasks.py`, `api/services/human_input_service.py`, `core/workflow/nodes/human_input/entities.py`, `core/app/workflow/layers/*.py`, test `test_parallel_human_input_join_resume.py` |
| `BerriAI/litellm` | `7ff50106` | MIT trừ `enterprise/` | 60,9k | `litellm/router.py` (fallback), `router_strategy/{lowest_latency,least_busy,lowest_cost,lowest_tpm_rpm_v2}.py`, `router_utils/cooldown_handlers.py`, `cooldown_cache.py`, `cost_calculator.py`, `litellm_core_utils/get_model_cost_map.py`, `proxy/auth/auth_checks.py`, `proxy/health_check.py` |
| `langfuse/langfuse` | `35d16971` | MIT trừ `ee/` | 35,6k | `packages/shared/clickhouse/migrations/canonical/0001_traces.up.sql`, `0003_scores.up.sql`, `prisma/schema.prisma` (Model/Price/ScoreConfig/Prompt), `server/ingestion/modelMatch.ts`, `worker/src/services/IngestionService/index.ts`, `validateAndInflateScore.ts`, `utils/updatePromptLabels.ts` |
| `renovatebot/renovate` | `3fc4836a` | **AGPL-3.0** | 22,7k | `lib/workers/repository/process/limits.ts`, `process/lookup/filter-checks.ts`, `update/branch/{index,automerge,schedule,status-checks,reuse}.ts`, `update/pr/automerge.ts`, `dependency-dashboard.ts`, `util/merge-confidence/index.ts`, `config/presets/internal/*.ts` |
| `OpenHands/OpenHands` | HEAD `e0a26af8`; tag `0.62.0` = `7fbb48c` | MIT | 90,5k | HEAD chỉ còn frontend (`README.md:165-170`); resolver đọc ở tag: `openhands/resolver/{issue_resolver,send_pull_request,resolver_output}.py`, `interfaces/issue_definitions.py` |
| `OpenHands/software-agent-sdk` | `e2bac66b` | MIT | chưa đo | `openhands/sdk/security/{confirmation_policy,risk,analyzer,llm_analyzer}.py`, `defense_in_depth/pattern.py`, `ensemble.py`, `agent/agent.py`, `conversation/impl/local_conversation.py`, `openhands-workspace/.../docker/workspace.py` |
| `OpenHands/automation` | `7cda26ab` | MIT | chưa đo | `event_schemas/github.py`, `trigger_matcher.py` |

Hai license cần nhớ: gpt-pilot (FSL) và renovate (AGPL) — **chỉ lấy ý, không chép mã**. Mục §3a lấy ý của renovate
và viết lại từ đầu theo khuôn `budget.py` của repo này; không dòng nào dịch từ `limits.ts`.

## 2. Cột 1 — đã có ở đây và sâu hơn (không lấy)

| Nguồn | Ý chính của họ | Ở đây | Vì sao không lấy |
|---|---|---|---|
| Dify `HumanInput.timeout` 36 giờ + Celery quét form hết hạn (`tasks/human_input_timeout_tasks.py:56-96`); crewAI `pending_feedback` không timeout (`flow/async_feedback/`); MetaGPT/ChatDev/gpt-pilot đọc `input()` không hạn; AG2 mặc định ném `HumanInputNotProvidedError` (`hitl.py:74-77`) | Gate người có hạn chót, quá hạn thì máy tự lên tiếng | `HumanGate(timeout=24h, remind_at=12h)` (`xagents_core/gates.py:71-73`), `overdue()`/`due()` tách nhắc và quá hạn (`gates.py:97-106`), `SupervisorBase.escalate_gate` chống lặp theo **thế hệ** gate (`supervisor.py:91-97`), `GateRequest.seq` thay `created_at` vì đồng hồ Windows 15,6 ms (`platform/xagents-core/CLAUDE.md` điều 2) | Đã có cả ba tầng nhắc → quá hạn → escalate, có chống lặp bền. Dify chỉ có một tầng hết hạn. Phiên phụ nói "X-Agents chưa có thời hạn" — sai, §5 |
| MetaGPT `NoMoneyException` kiểm mỗi vòng (`team.py:92-100`); crewAI chỉ đếm token, không USD (`types/usage_metrics.py:32-57`); AG2 `TokenMonitor` → alert → `HaltEvent` dừng mềm (`policies/alert.py:67-85`, `agent.py:2025-2070`); claude-flow lấy USD từ envelope `claude --print` (`headless-worker-executor.ts:604-626`) | Trần token/tiền cho một đơn vị việc, cắt khi vượt | `Budget` so **`output_used`** với trần, không so tổng token (đo 2026-09-04: ticket output 18 868 nhưng tổng 734 862 — so tổng thì cắt oan, `supervisor.py:47-62`); `limit_usd`/`ratio_usd` song song; `WARN_AT, CUT_AT = 0.8, 1.0` (`supervisor.py:68`); `_act_once` mỗi ngưỡng phát đúng một lần | Ở đây phân biệt token đầu ra và tổng token từ một sự cố đo được; ba repo kia không phân biệt. Dừng mềm kiểu AG2 đã có dạng `SupervisorAction` qua bus |
| crewAI vượt `max_iter` → một lời gọi ép trả lời cuối (`utilities/agent_utils.py:366-388`); AG2 `LoopDetector` (`observers/loop_detector.py:16-65`); claude-flow `tool-loop-guardrail` cùng lệnh fail 3 → warn, 5 → block (`tool-loop-guardrail.ts:26-27`) | Vòng tool không được chạy vô hạn | Company runner `NO_PROGRESS_WARN, NO_PROGRESS_STOP = 3, 5` (`company/runner.py:58`), tỉa `role=tool` cũ trước khi gửi (`:322-326`), cảnh báo rồi cắt (`:368-381`), ép "DUY NHẤT JSON cuối cùng" (`:405`) | Cùng ngưỡng 3/5 và cùng cách ép câu trả lời cuối; ở đây thêm tỉa ngữ cảnh (ADR-0007) |
| MetaGPT `RunCode` để LLM tóm tắt stdout/stderr thành PASS/FAIL (`actions/run_code.py:41-43, 134-146`); ChatDev `exist_bugs` đọc `returncode` **trước** khi poll, "không có Traceback" = chạy được (`chatdev/chat_env.py:107-151`), review dừng khi model tự viết `<INFO> Finished` (`composed_phase.py:213-214`); gpt-pilot `if True or llm_response.success` (`core/agents/executor.py:132-133`), tự chấp nhận sau 3 lần (`code_monkey.py:28-32, 210`); OpenHands `guess_success` hỏi LLM chấm patch của chính nó (`issue_definitions.py:45-64`) | Ai quyết "code chạy được" | Luật cấm 8; keeper I2 `evidence.require_two_way()` ném `EvidenceError` nếu `before.exit_code == 0` hay `after != 0`; `verified_by=workspace\|orchestrator`; gpt-pilot `ExecLog` (cmd/cwd/status/stdout) tương đương `evidence.check_report()` của keeper | Cả bốn repo để model hoặc `if True` tuyên bố pass. Đây là chỗ X-Agents khác biệt nhất, không có gì để lấy |
| MetaGPT xoá message vừa quan sát khi crash để resume quan sát lại (`utils/common.py:689-705`) + 3 test recover (`test_team.py:73-147`); gpt-pilot `ProjectState` bất biến mỗi bước, `load_project(step_index)` (`state_manager.py:272-300, 433-473`); crewAI `flow_states` append-only (`flow/persistence/sqlite.py:111-129`); ChatDev 2.0 session store là dict RAM (`server/services/session_store.py:70-74`) | Trạng thái bền, tua lại được | Bus SQLite + ExecutionJournal replay; supervisor là "hàm thuần của bus, đếm lại khi replay — không có gì chỉ sống trong RAM" (`supervisor.py:74-76`); khuôn 2 `TRAPS.md`; test gián đoạn/resume hiện có | Cùng mức với MetaGPT/gpt-pilot, hơn ChatDev/agency-swarm. Mảnh duy nhất chưa có là đóng tool-call mồ côi của AG2 → §4 |
| OpenHands `SecurityRisk` enum có thứ tự + `ConfirmRisky(threshold)` (`security/confirmation_policy.py:27-61`), `EnsembleSecurityAnalyzer` lấy max (`ensemble.py:78-101`); nhưng `LLMSecurityAnalyzer` để **model tự khai** `security_risk` (`llm_analyzer.py:20-29`) | Phân bậc rủi ro để quyết cần người hay không | Keeper `RISK_RULES` bảng tra theo tên hàng, khớp hàng đầu tiên, mọi `high` đứng trước `low` (`keeper/risk.py:66-78`); bậc tính từ **trường của Signal** (kind, semver_jump, path), không hỏi model; test `rules_without` bỏ đúng một hàng rồi đo lại | Cùng ý "enum có thứ tự + chính sách một hàm", nhưng ở đây model không bao giờ tự chấm rủi ro cho hành động của nó |
| OpenHands resolver áp patch bằng parser tự viết (`send_pull_request.py:29-75`), chỉ mở PR khi `success=true` do LLM chấm (`:512-525`) | Gác cổng trước khi mở PR | Keeper ADR 0002: so cây worktree sắp push với `patch_id` **đã đo** (`orchestrator.py:48`), `push_branch` đẩy đúng `sha` đã kiểm chứ không đẩy theo tên nhánh (`publish.py:49`); CLI thoát 4 khi lệch | Cổng của họ là lời model; cổng ở đây là băm nội dung |
| Renovate đếm PR/giờ lỗi → trả **0** (`process/limits.ts:36-41`); LiteLLM cooldown `except Exception: return True` im lặng (`cooldown_handlers.py:268-271`), giá mặc định 5.0 cho model lạ (`lowest_cost.py:259-262`); claude-flow checkpoint lỗi → chạy **không guard**, `degraded:true` (`checkpoint-gate.ts:183-235`) | Không biết thì làm gì | Keeper `_parse_list_strict`: `None` = không biết ≠ `[]` (`github.py:220-235`), `BudgetContext` coi `None` là KHÔNG QUA (`budget.py` docstring); ADR-0010 `ContainerSandbox` fail-closed, không tụt về subprocess; claude-flow `harness-verify` "verifier vắng = SKIPPED ≠ PASS" (`harness-verify.ts:9-16`) là cùng tinh thần luật cấm 8 | Ba trong bốn repo fail-open ở đúng chỗ X-Agents fail-closed. Giữ nguyên |
| MetaGPT cache phản hồi tự lớn khi test pass, không strict (`tests/conftest.py:62-77`); crewAI vcr cassette, CI `record_mode=none` (`lib/conftest.py:444-459`); agency-swarm model giả xác định (`tests/deterministic_model.py:34-41`); AG2 `TestClient` kịch bản (`testing.py:48-97`); claude-flow `harness-frozen-eval` ghim sha256 (`harness-frozen-eval.ts:25-28`) | Test không gọi model trả phí | Provider `fake` (luật cấm 4); `evals --replay --strict` (`company/evals.py:219`) với `thresholds.yaml` + `REQUIRED.txt` (`xagents_core/evals.py:399-430`); `tests/golden/` sinh bằng `make golden`; ECC vendor ghim sha256 (`docs/integrations/ecc.lock.json`) | Đã có đủ ba kiểu: model giả, phát lại nghiêm ngặt có ngưỡng, golden. MetaGPT thiếu strict, crewAI/AG2 thiếu ngưỡng |
| claude-flow policy engine: approval có issuer, cấm tự duyệt, `maxUses`, revoke (`security/src/policy/engine.ts:110-132, 239`); Dify form token theo kênh (`human_input_policy.py:19-95`) | Ai được duyệt, chống tự duyệt | `trusted_decision` chỉ tin `env.actor` của bus, không tin `evidence.by` (`gate_cli.py:33`, `platform/xagents-core/CLAUDE.md` điều 1 — lỗ "tin lời khai trong evidence" từng vá 2 lần); four-eyes `created_by != by` chặn từ `request()` (`gates.py:80-86`); `approvers` + `APPROVERS_SOURCE` | Cùng mức; ở đây có thêm bài học cụ thể đã vá hai lần |
| LiteLLM ba danh sách fallback theo lớp lỗi (`router.py:7740-7795`), cooldown theo mã (`cooldown_handlers.py:225-271`), `Retry-After` chuẩn; claude-flow `GlobalAiBudget` **tạm dừng cả máy** N phút khi regex thấy 429/quota (`global-ai-budget.ts:100-102, 200-213`) | Xoay backend theo loại lỗi, nghỉ khi hết quota | Core `routing.py` ba lớp quota/missing/auth (`:136-150`), lỗi vận chuyển nghỉ luỹ thừa theo `transient_streak` (`:234-236`), mọi backend nghỉ → `TransientError` để orchestrator hoãn event; gateway `_should_fail_over` (`client.py:93-98`), `cooldown_hint` đọc "Resets in 7m29s" trong **thân** lỗi vì Code Assist không gửi `Retry-After` (`client.py:100-130`), cooldown **theo từng tài khoản** (`auth.py:424-437`), không retry trong gateway (ADR gateway 0001 §4) | Ở đây đọc được gợi ý hồi quota mà LiteLLM không đọc; nghỉ theo tài khoản thay vì dừng cả máy như claude-flow. Thứ LiteLLM có mà đây chưa là cooldown theo **tỉ lệ fail** → §4 |
| claude-flow `tool-output-guardrail.ts` thư viện regex injection xếp theo severity, hành động `allow\|flag\|redact\|reject` (`:36-177`); OpenHands `PatternSecurityAnalyzer` (`defense_in_depth/pattern.py:63-110`); MetaGPT, ChatDev, crewAI, AG2, Dify **không có** ranh giới tin cậy cho output model/tool | Chống prompt injection từ tool và topic ngoài | `guard.py`: `scan`/`sanitize_tool_output`/`guard_payload` (`:118-178`), chính sách theo topic ở `CoreConfig` của công ty, `compile_patterns(extra)` nối mẫu thêm; `is_external(topic, actor)` | Cơ chế đã có và tách hai lớp (mẫu vs chính sách). Họ chỉ nhiều mẫu hơn; thêm mẫu khi có ca lọt (§4), không nhập cả thư viện |

## 3. Cột 2 — đã có nhưng nông hơn: ĐÃ LẤY trong thay đổi này

### 3a. Hạn mức PR/tuần của keeper chỉ đếm PR của keeper — từ Renovate `getPrHourlyCount`

**Sự cố đã xảy ra.** Canary keeper 2026-10-05 (`docs/reports/2026-10-05-keeper-canary-urllib3.md:29-30`): hạn mức mặc
định `KEEPER_MAX_PR_PER_WEEK=5` **cạn khi keeper chưa mở PR nào**, vì `budget_context` đếm *mọi* PR của repo merge
trong 7 ngày (28 lúc đó, phần lớn của người và dependabot). Chủ repo phải nâng tay lên 30 để một bản vá bảo mật đi qua.

**Đo lại 2026-10-10 trên `seeker19110/X-Agents`** (GitHub search, chỉ đọc):

| Câu hỏi | Kết quả |
|---|---|
| `is:merged merged:>=2026-10-03` | 30 PR — **đúng bằng** `--limit` mặc định 30 của `gh pr list`; trong đó 1 PR của keeper (#395) |
| `is:merged head:chore/keeper-` | đúng #395 → `head:` khớp **tiền tố** nhánh |
| `is:merged head:dependabot` | 6 PR `dependabot/uv/*` → xác nhận lần nữa `head:` là tiền tố |

Hai lỗi chồng nhau: đếm sai tập (mọi PR thay vì PR keeper) và trần mặc định 30 dòng của `gh` đúng bằng số PR tuần
này — hỏi cả repo rồi lọc sau thì PR keeper nằm ngoài 30 dòng đầu sẽ **không được đếm**, tức fail-open cho hạn mức.

**Renovate làm gì** (`lib/workers/repository/process/limits.ts:13-33`, chỉ đọc ý): lọc PR theo `branchPrefix` của
chính nó rồi mới đếm; PR vì vulnerability alert được miễn hạn mức (`update/branch/index.ts:269, 282, 1034`); đếm lỗi
thì trả 0 (`limits.ts:36-41`). Lấy ý thứ nhất; **không** lấy fail-open; ý thứ hai xếp §4 kèm điều kiện.

**Đã đổi** (nhánh `claude/blissful-bardeen-xb8nex`):

- `keeper/budget.py`: `is_keeper_pr(pr)` = `pr.headRefName.startswith(worktree.BRANCH_PREFIX)` (`"chore/keeper-"`,
  đúng cách `KeeperWorktree.branch` đặt tên và `publish.push_branch` đẩy); `budget_context` đếm
  `sum(1 for pr in merged if is_keeper_pr(pr))`. Không nhìn tiêu đề: `fix(keeper)` là PR của người viết *về* keeper.
- `keeper/github.py`: `merged_prs` hỏi `--search "merged:>=<since> head:chore/keeper-" --limit 500`; hằng
  `MERGED_PR_LIMIT = 500` mang marker `no-ky-thuat` (trần 500 PR keeper/tuần, quay lại khi `KEEPER_MAX_PR_PER_WEEK`
  đặt trên 500). Lọc ở **cả hai** tầng: reader hỏi hẹp để không bị trần cắt; `budget` lọc lại để luật đúng với mọi
  `GitHubLike` (fake trong test, reader khác).
- Tài liệu cùng PR: `companies/keeper/docs/DAC-TA-KEEPER.md` §6 (công thức `can_open_pr`), `CODEMAP.md`, `README.md`,
  `TRAPS.md` (hàng mới), `docs/HUONG-DAN-VAN-HANH.md`, `CHANGELOG.md`.

**Đo hai chiều** (luật bắt buộc 4):

| Test | Đỏ trước (chưa có code) | Xanh sau |
|---|---|---|
| `test_budget.py::test_han_muc_tuan_chi_dem_pr_nhanh_keeper` | `AssertionError: 4 != 1` (đếm cả 3 PR người/dependabot) | pass |
| `test_budget.py::test_nhan_dien_pr_keeper_theo_tien_to_nhanh` (4 ca: `chore/keeper-bump-urllib3` ✓, `chore/keeper` ✗, `fix/keeper-mau` ✗, `""` ✗) | `ImportError: is_keeper_pr` | pass |
| `test_github.py::test_merged_prs_chi_hoi_nhanh_keeper_va_nang_tran_30_dong` | `ImportError: MERGED_PR_LIMIT` | pass |

Hai file: **6 failed → 88 passed**. Cổng `scripts/dev-task.sh gate keeper`: ruff sạch, mypy 29 file, pytest
**841 passed, phủ 100 %** (2 122 câu lệnh, 540 nhánh, 0 thiếu). Bất biến I3 (`no-open-pr`, luôn hỏi GitHub, `None` =
không qua) **không đổi**.

Không có mục 3b: mọi ý còn lại hoặc đã có sâu hơn (§2) hoặc chưa có sự cố tương ứng (§4).

## 4. Cột 3 — chưa có, hoặc nông hơn nhưng chưa có sự cố → "chưa cần" kèm điều kiện quay lại

| Thứ | Vì sao chưa cần | Quay lại khi |
|---|---|---|
| Renovate miễn PR bảo mật khỏi hạn mức (`update/branch/index.ts:269, 282, 1034`, ngân sách riêng `global/limits.ts:93`) | Canary 2026-10-05 bị chặn vì **đếm sai tập** (đã sửa §3a), không phải vì keeper tự mở quá nhiều; keeper merge 1 PR/tuần | Keeper đã merge ≥ `KEEPER_MAX_PR_PER_WEEK` PR trong tuần **và** một ticket `kind=security`, `severity ≥ high` bị `budget` chặn → miễn **chỉ** hàng `weekly-quota` (`checks_without("weekly-quota")`) cho đúng bậc đó; **không bao giờ** miễn `no-open-pr` (I3). Ai được khai "bảo mật" → §6 |
| Renovate rebase khi `behind-base-branch` và **không** automerge nếu nhánh có commit người (`update/branch/reuse.ts:45-51`, `update/pr/automerge.ts:96-102`) — ứng viên tín hiệu `pr-behind-base` cho keeper `health` | Hai lần nền cũ (#246 ngày 2026-09-09, #398 hôm nay: `audit` đỏ vì lock cũ) đều bị bắt **trước** merge; `main` chưa từng đỏ vì nền cũ. Ruleset `strict_required_status_checks_policy: false` (`.github/rulesets/main.json:41`) nên `mergeStateStatus` không phản ánh "tụt nền" một cách tin được — tín hiệu dựng trên nó sẽ nói dối | Một PR xanh trên nền cũ merge xong làm `main` đỏ; hoặc chủ repo quyết **giữ** strict=false (§6) → thêm `health.pr_behind_base_signals` đọc `gh pr view --json mergeStateStatus,baseRefOid` so với `main` |
| Renovate `minimumReleaseAge` + trạng thái "pending" là **commit status vàng** (`process/lookup/filter-checks.ts:170-201`, `update/branch/status-checks.ts:70-112`) | Chưa có bản bump nào merge rồi bị yank/regress; PR bảo mật (#395) càng không nên chờ | Một bump dependency đã merge bị yank hay regress trong vòng N ngày → `Signal.release_age_days` + một hàng `RISK_RULES` ("quá mới" = `medium`), không chặn bảo mật |
| Renovate dependency dashboard = issue có checkbox (`dependency-dashboard.ts:70-80, 501-602`) | Console đã hiện gate và trạng thái keeper; chưa lần nào người vận hành hỏi "keeper đang chờ gì" mà không trả lời được | Hai lần người vận hành hỏi mà console thiếu → một issue sinh từ `order_queue`, ghi qua `publish.py` (I1: `github.py` vẫn chỉ đọc) |
| Renovate merge confidence (`util/merge-confidence/index.ts:16-35`) | Phụ thuộc SaaS Mend, self-host chỉ ra `neutral`; trái nguyên tắc trung lập provider | Không quay lại dạng SaaS. Nếu cần, tính từ lịch sử CI của chính repo |
| LiteLLM cooldown theo **tỉ lệ fail** (>50 % với ≥ 5 request, 100 % với ≥ 1000/phút; `cooldown_handlers.py:378-480`, hằng `constants.py:119-125`) | Gateway nghỉ theo mã lỗi + gợi ý hồi; core có `transient_streak` luỹ thừa (`routing.py:234-236`). Chưa đo được tài khoản nào xen kẽ 200/5xx làm pool giật | `Backend.failures/calls` (`routing.py:160-162` đã đếm) của một backend vượt 50 % trong một cửa sổ mà cooldown theo mã không bắt → thêm hàng tỉ lệ vào `Router`, có ngưỡng tối thiểu số request như họ |
| LiteLLM chọn deployment = lọc tpm/rpm → sort latency → `random.choice` trong buffer (`lowest_latency.py:475-496`) | Gateway xoay theo **tính sẵn sàng** của tài khoản; chưa có sự cố một tài khoản chậm làm nghẽn | p95 của một tài khoản ≥ 2× trung vị pool trong `/auth/status` |
| LiteLLM bảng giá fetch + backup cục bộ + cờ ép offline (`get_model_cost_map.py:621-700`); Langfuse `Model.match_pattern` regex + `start_date` + giá riêng theo project (`modelMatch.ts:266-300`) | Giá ở đây là bảng tĩnh theo gói (`docs/DIEU-PHOI-MODEL.md`); chưa có sự cố tính sai tiền vì giá đổi | Một lần đổi giá của provider lọt quá một kỳ thanh toán, hoặc model lạ được tính 0 USD mà không cảnh báo (kiểm `cost_usd` với model ngoài bảng trước) |
| Langfuse giữ cả `provided_*` (khai) lẫn `*_details` (tính) trên cùng một hàng (`0001_traces.up.sql:16-23`) | Audit-log lấy usage thật từ `usageMetadata` (hợp đồng gateway điều 1); không có giá trị "khai" thứ hai để so | Có provider không trả usage và phải ước lượng (`CHARS_PER_TOKEN` 3,2) → lưu cả ước lượng lẫn thật |
| Langfuse `ScoreConfig` ép khoảng/categories lúc ingest (`validateAndInflateScore.ts:35-58, 205-250`) | Eval đã có `thresholds.yaml` theo agent + `REQUIRED.txt`; chưa có hai bản ghi dùng hai thang cho cùng một số đo | Hai recording cùng số đo khác thang → schema cho score trong `evals.py` |
| Langfuse prompt = version bất biến + label di chuyển (`updatePromptLabels.ts:17-44`) | Prompt là code: `version` trong `agents/*.md` + golden + eval record; `main` chính là label | Cần chạy hai version prompt song song trong sản xuất (A/B) |
| MetaGPT xoá message vừa quan sát khi crash (`utils/common.py:689-705`); AG2 `close_unanswered_tool_calls` + `replayable_span` khi resume/compaction (`history.py:69-121`, `_replay.py:157-189`) | Vòng tool của runner chạy trọn trong **một** event, publish ở cuối; crash giữa vòng thì event được xử lý lại từ đầu — chưa có ca provider từ chối lịch sử vì `tool_call` mồ côi | Vòng tool thành resume được giữa chừng (cần ADR), hoặc một provider trả lỗi vì `tool_call` chưa có `tool_result` trong lịch sử gửi lại |
| AG2 cờ `__transient__`/`__conversational__` trên event (`events/base.py:244-256`) | Bus tách theo **topic** + ACL; `context.py` (ADR-0012) cắt theo namespace blackboard; chưa có ca telemetry lọt vào prompt | `context.py` cần loại event quan sát khỏi prompt mà không phân biệt được bằng topic |
| crewAI guardrail retry, lỗi đưa lại vào context, đếm riêng từng guardrail (`task.py:1343-1395`); `HallucinationGuardrail` chấm bằng LLM | Runner **cố ý** không retry lỗi nội dung — retry là hint của delivery-lead + hạn mức của supervisor (`company/runner.py:4-6`) | Audit-log cho thấy ≥ N ticket đỏ ở lần đầu vì lỗi schema và vòng hint tốn hơn retry tại chỗ (đo trước) |
| crewAI xếp hạng bộ nhớ importance × recency decay (`unified_memory.py:108-114`); MetaGPT exp_pool chỉ tái dùng khi khớp hệt và điểm 10 (`perfect_judges/simple.py:13-27`); ChatDev ECL embedding (`ecl/memory.py:135-230`) | Bài học tại mốc merge đã có (ADR-0048, #389); báo cáo 2026-09-27 đã hoãn Mem0/vector memory tới khi có retention/xoá/quyền | Tệp bài học vượt ngân sách ngữ cảnh (`make assetbudget`) → cần xếp hạng; không thêm vector store trước đó |
| claude-flow thư viện regex injection cho output tool (`tool-output-guardrail.ts:36-177`); OpenHands `PatternSecurityAnalyzer` detector id (`defense_in_depth/pattern.py:63-110`) | `guard.py` có mẫu + `compile_patterns(extra)`; chưa có ca chuỗi injection lọt `scan()` | Một bản ghi eval/replay cho thấy chuỗi lọt → thêm **đúng mẫu đó** + test, không nhập cả thư viện |
| claude-flow consensus `bft\|raft\|quorum` (`hive-mind-tools.ts:81-110`, `consensus/raft.ts:67-69`), "Queen" phân tích task bằng `includes('security')` (`queen-coordinator.ts:861-865`) | Trái "model quyết định – code hành động"; Raft giữa các agent LLM không có mô hình lỗi tương ứng ở đây | Không quay lại trừ khi orchestrator chạy nhiều máy |
| gpt-pilot người xác nhận và sửa từng lệnh shell (`core/agents/executor.py:79-102`); OpenHands `ConfirmRisky` từng hành động | **Cố ý không làm**: "không chốt duyệt mức tool — có chủ đích" (`docs/KIEN-TRUC-4-LOP.md:21`), ADR-0037 vừa gỡ nghẽn chốt; không cấp tool thì không có hành động | Một tool đã cấp gây hành động không đảo ngược ngoài worktree dù có sandbox → ADR mới, không vá tại chỗ |
| claude-flow receipt JSONL cho mọi quyết định ngân sách (`global-ai-budget.ts:17, 213`) | Gateway ghi cooldown qua `logger.warning` (`auth.py:437`); chưa có lần nào người hỏi "vì sao tài khoản này nghỉ" mà log đã trôi | Một lần không truy được lý do cooldown → topic/receipt có cấu trúc, không đổi hành vi xoay |
| OpenHands K8s warm pool, gVisor/Kata (`agent_sandbox/README.md:1-12`); Docker chỉ image dựng sẵn (`docker/workspace.py:53-60`) | ADR-0010 `ContainerSandbox` một máy, fail-closed; chưa đo được khởi động sandbox là nút nghẽn | Thời gian dựng sandbox đo được vượt ngưỡng của ticket, hoặc khách đa tenant |
| OpenHands `automation` trigger JMESPath trên webhook (`trigger_matcher.py:10-13`) | Keeper `watch` poll theo `--interval`; chưa có repo khách nào lệch SLA vì poll | Poll bỏ lỡ SLA hoặc ăn quota API (`gh` rate-limit remaining đo được) |
| Dify kiến trúc Layer cắm vào engine (`workflow_entry.py:170-186`); phân biệt `node_timeout`/`global_timeout` cho HITL (`human_input_timeout_tasks.py:56-96`) | Core đã tách `observe.py` sink / bus / supervisor; refactor không sự cố vi phạm luật cấm 7. Một `timeout` cho mỗi `HumanGate` đủ cho một công ty | Công ty thứ ba phải fork vòng orchestrator để thay persistence; hoặc hai loại gate (spec vs release) cần hạn chót khác nhau → `GateRequest.timeout` |

## 5. Đính chính lời khai của phiên phụ (đã đối chiếu mã)

- **"Human gate của X-Agents chưa có thời hạn" — SAI.** `HumanGate.__init__(timeout=24h, remind_at=12h)`
  (`gates.py:71-73`), `overdue()`/`due()` (`gates.py:97-106`), `SupervisorBase.escalate_gate` (`supervisor.py:91-97`).
  Nhờ đó mục Dify HITL rơi về cột 1, không phải cột 2. Đây đúng là lý do §H bắt đối chiếu lại mọi câu về "ở đây".
- **Số sao** là tóm tắt của model nhỏ từ trang GitHub (API bị 403 qua proxy): chỉ dùng để xếp "nổi tiếng", không dùng
  để kết luận gì khác.
- **OpenHands HEAD không còn Python** (`README.md:165-170`): resolver chỉ còn ở tag `0.62.0`, confirmation mode và
  security analyzer nằm ở repo `software-agent-sdk`. Mọi trích dẫn OpenHands trong bản này là tag hoặc SDK.
- **ChatDev `main` là nền tảng workflow YAML** ("2.0 DevAll"); "công ty phần mềm" chỉ còn ở nhánh `chatdev1.0`, nhánh
  đó **không có thư mục test**.
- **Dify không chứa graph engine**: `api/pyproject.toml:48` ghim `graphon==0.7.0` bên ngoài — "engine của Dify" không
  audit được trong repo đó.
- **AG2 đã viết lại hoàn toàn** (package `ag2/`, không còn `autogen/`): kiến thức GroupChat cũ không áp.
- Phần "neural/ReasoningBank" của claude-flow phiên phụ ghi rõ ngoài phạm vi kiểm chứng — không tính vào cột nào.

## 6. Việc cần người quyết (không tự làm trong PR này)

1. **Ruleset `main`, `strict_required_status_checks_policy: false`** (`.github/rulesets/main.json:41`). Bật strict là
   cách GitHub chặn merge PR tụt nền — sửa tận gốc cho hàng "pr-behind-base" ở §4 — nhưng mỗi PR tụt nền sẽ phải
   "Update branch" rồi chạy lại CI. Phiên không có quyền sửa ruleset (nhật ký 2026-10-10 mục `protection-guard`).
2. **Gateway #4** (`docs/sessions/2026-09-23.md:39-42`): ba danh sách fallback theo lớp lỗi của LiteLLM khớp đúng đề
   xuất cũ (model anh em trả 4xx không-quota → coi là không dùng được, cooldown theo gợi ý model chính, xoay tài khoản,
   giữ 429 làm lỗi cuối). `test_sibling_fallback_fails_without_cooldown_raises` (`gateway/tests/test_client_coverage.py:341`)
   khoá hành vi hiện tại có chủ đích — cần người chốt chính sách trước khi đụng code.
3. **Ai được khai "bảo mật" để miễn hạn mức tuần** (§4 hàng 1) khi điều kiện quay lại xảy ra: hôm nay `kind=security`
   và `severity` đến từ nguồn tín hiệu (scout/pip-audit), không từ model — tự miễn hay vẫn cần người?

## 7. Thay đổi trong PR này

Mã: `companies/keeper/src/keeper/{budget,github}.py`; test: `companies/keeper/tests/{test_budget,test_github}.py`.
Tài liệu cùng PR: `companies/keeper/docs/DAC-TA-KEEPER.md`, `companies/keeper/{CODEMAP,README,TRAPS}.md`,
`docs/HUONG-DAN-VAN-HANH.md`, `CHANGELOG.md`, báo cáo này, `docs/sessions/2026-10-10.md`. Không vendor file nào từ
15 nguồn; không cài dependency; không đụng `agents/`/`skills/` nên `evals`/`subagents`/`assetscan` là `n-a`.
