# Đặc tả triển khai kịch bản B — PR theo PR

Ngày lập: 2026-09-06 · Đặc tả gốc: `docs/DAC-TA-KICH-BAN-B.md` (mã K0–K9). Mọi `file:dòng` đo tại
`main@d7c8271`; sau mỗi PR merge, dòng sẽ trôi — mã mục và tên hàm là mốc, dòng chỉ để tìm nhanh.

Tài liệu này viết cho **agent thực thi**: mỗi PR là một đơn vị giao được, có tiêu đề, file đụng, thay đổi cụ
thể, test hai chiều, lệnh nghiệm thu, và cạm bẫy đã biết. Cách thực thi một PR: đọc mục, mở worktree
(`git worktree add ../Claude-Agents-wt-<mã> -b <type>/<mã> main`), viết test trước, code, chạy đúng lệnh CI của
package (`uv run ruff check src tests && uv run mypy src/<pkg> --ignore-missing-imports && uv run pytest -q -n auto
--cov`), PR tiêu đề `<type>(<scope>): <mã> — <một câu>`, bật auto-merge, thêm dòng CHANGELOG, cập nhật bảng theo
dõi ở cả hai đặc tả.

Quy ước scope PR (một từ chữ thường): `company`, `studio`, `core`, `console`, `gateway`, `ci`, `docs`.

---

## K0 — Vệ sinh · 1 PR

**PR K0** `chore: K0 — vệ sinh trước kịch bản B`

| File | Thay đổi |
|---|---|
| `docs/DAC-TA-NANG-CAP-2026-09.md` bảng §8 | V1–V5: ghi "xong #98" cho V2, V4, V5; V1 "xong (#94 đã merge)"; V3 "thủ công, không kiểm được từ repo" |
| `README.md:17` | "ADR 0001–0028" → "ADR 0001–0032"; "743 test" → bỏ số (package README đã có test đếm) |
| `companies/software-company/pyproject.toml:4` | "20 agent" → "21 agent" |
| `companies/software-company/README.md:148` | "20 system prompt" → 21 |
| `platform/gateway/.env.example:11-21` | 8100 → 1123 ở 4 chỗ; câu chú thích về Hermes giữ nhưng nói rõ 1123 là mặc định |
| `companies/software-company/docs/adr/0030-*.md`, `0031-*.md:8,38` | `docs/DAC-TA-NANG-CAP-2026-09.md` → `../../../docs/DAC-TA-NANG-CAP-2026-09.md` |
| `docs/adr/README.md` (mới) | 10 dòng: ADR cấp repo cho quyết định chạm ≥ 2 package; mẫu bốn mục Bối cảnh/Quyết định/Hệ quả/Liên quan như ADR-0032 |
| `tests/test_readme_goc.py` (mới, chạy trong job nào? → thêm vào `console-unit` vì console đã path-depend cả hai; hoặc job `docs` mới) | đếm `companies/software-company/docs/adr/*.md` và `agents/*/*.md`, so với regex trong README gốc |

Cạm bẫy: `test_readme_khop_so_lieu_that` (`companies/software-company/tests/test_review_fixes_2026_09.py:391`) đã canh
README package — đừng làm trùng, chỉ canh README gốc.

---

## K1 — Tách máy trạng thái · ADR-0037 + 7 PR

**Trạng thái (2026-09-07)**: **đóng K1** ở mức chức năng (7 PR thật thay vì gộp 1, ADR thực tế đánh số 0034,
không phải 0037 — số 0035–0036 chưa dùng ở nhánh này). Đã tách `orch/routes.py` (K1.2), `orch/verify.py` +
`orch/cli.py` (K1.1) (#115); `OrchState` dataclass + 24 property alias (K1.3 phần state, #117);
`worktree_flow.py` (K1.4, #120); `scheduler.py` — vòng lặp chính (K1.5, #122); `gates_flow.py` (K1.6, #123);
`ticket_fsm.py`/`release_fsm.py` di chuyển thuần (#124) rồi `orch/fsm.py` (`Transition`/`step()`) +
`TICKET_TRANSITIONS`/`RELEASE_TRANSITIONS` làm bảng dữ liệu thật, `process()` thành dispatcher thuần, cộng
`tests/test_orch_bang_chuyen.py` + `tests/test_orch_khuon_loi.py` (K1.7, #125) — sửa luôn bug `once=
"no-test-author:{tid}"` thiếu thế hệ, phát hiện khi viết test khuôn 3.
`orchestrator.py` 2269 → 491 dòng. **Còn dở, cố ý để phiên sau quyết định**: K1.8 (đích ≤ 300 dòng) CHƯA đạt —
phần còn lại (`_call`/`__init__`/`status`) ngoài phạm vi mọi PR K1.x đã duyệt; ba khoá `once` khác
(`gate.escalate:{sid}`, `smoke.unverified:{rid}`, `delivery.skipped:{rid}`) chưa được kiểm có thiếu thế hệ như
`no-test-author` hay không (K1.4 gốc đặc tả); K1.5 (guard `smoke.unverified` theo `kind=application`+`legacy`)
chưa làm. Không có PR nào chạm `orchestrator.py`/`orch/` cùng lúc — mỗi PR một phiên, đo hai chiều đủ.

### ADR-0037 (viết trước, PR `docs(company): ADR-0037 tách máy trạng thái`)

Bối cảnh: 22/30 PR gần nhất cùng họ; §1 bản đồ file (110 hàm, 10 nhóm). Quyết định: gói `orch/`, `OrchCtx`
Protocol, `OrchState` dataclass có metadata `rehydrate`, bảng chuyển trạng thái tra cứu, re-export. Hệ quả:
luật PR K8.3. Liên quan: ADR-0007, 0011, 0027, TRAPS §1.

### Interface chung (đặt trong PR K1.1, dùng suốt)

```python
# src/company/orch/ctx.py
class OrchCtx(Protocol):
    bus: Bus; lead: DeliveryLead; gate: PersistentGate; supervisor: Supervisor
    state: "OrchState"; runner: AgentRunner; blackboard: Blackboard
    repo: Path | None; test_author: bool; deliver: bool
    def latest(self, topic: str, key: str) -> Envelope | None: ...
    def workspace(self, project_id: str) -> Workspace: ...
    def _audit(self, kind: str, **fields) -> None: ...
    def _remember(self, key: str) -> bool: ...        # once, trả False nếu đã có
    def _defer(self, env: Envelope, until: float, why: str) -> None: ...
    def _call(self, route: Route, env: Envelope) -> StepResult: ...
```

```python
# src/company/orch/state.py
@dataclass
class OrchState:
    processed: set[str] = field(default_factory=set, metadata={"rehydrate": "audit:orchestrated - audit:reopened"})
    once: set[str] = field(default_factory=set, metadata={"rehydrate": "audit:once"})
    queue: list[Envelope] = field(default_factory=list, metadata={"rehydrate": "log chưa processed"})
    deferred: list[tuple[float, Envelope]] = field(default_factory=list, metadata={"rehydrate": "audit:defer.until qua _nap_lai_hen"})
    stats: Counter = field(default_factory=Counter, metadata={"rehydrate": "RAM-only: thống kê phiên"})
    ...  # 30 trường theo §2 bản đồ; MỖI trường có metadata["rehydrate"]
```

Test bất biến (K1.2): `for f in fields(OrchState): assert f.metadata.get("rehydrate")`. Đây là chốt khuôn 2.

```python
# src/company/orch/fsm.py
@dataclass(frozen=True)
class Transition:
    src: str | None            # None = "bất kỳ"
    event: str                 # topic hoặc audit kind
    guard: Callable[[OrchCtx, Envelope], bool] | None
    dst: str
    action: Callable[[OrchCtx, Envelope], None] | None
def step(table: list[Transition], ctx, state, env) -> Transition | None   # tra tuần tự, trả None nếu không khớp
```

### PR K1.1 `refactor(company): K1 — tách cli.py và verify.py khỏi orchestrator`

- Tạo `orch/__init__.py`, `orch/ctx.py`, `orch/cli.py` (nhận `main` `orchestrator.py:2101-2263`, `_fmt:2096`,
  `_reexec:2264`, `source_fingerprint:385`), `orch/verify.py` (nhận `_smoke:1293`, `_regression_run:1326`,
  `_verdict_with_run:1352`, `_release_evidence:1236` — thành hàm module nhận `ctx`).
- `main` tách thành `_cmd_run/_cmd_status/_cmd_trace/...` mỗi hàm ≤ 30 dòng; `main` chỉ dựng parser + dispatch.
- `orchestrator.py`: `from .orch.cli import main, source_fingerprint` (re-export), method `_smoke = verify.smoke`
  (gán mỏng để test gọi `o._smoke(...)` vẫn chạy).
- Test: không đổi test cũ; thêm `tests/test_orch_cli.py` gọi từng `_cmd_*` với bus tmp.
- Nghiệm thu: `wc -l orchestrator.py` giảm ~330; `pytest -n auto --cov` 100%.

### PR K1.2 `refactor(company): K1 — routes.py thuần`

- Chuyển `orchestrator.py:78-365` (hằng, `Route`, `_from/_field/_needs_*/_dict_of/_deployed/_answers_*/
  _spec_ready/_cr_*/spec_runtime_gap/_with_*/_test_scope_ok/_can_author_tests/_no_test_author/_has_dispute/
  _with_task/ROUTES/PROD_ROUTE/THREAT_ROUTE/PLAN_INPUTS/check_routes`) sang `orch/routes.py`.
- Guard nhận `o: OrchCtx` thay vì `Orchestrator` — chữ ký không đổi, chỉ đổi annotation.
- `_with_diff:231`, `_with_chan_doan:239`, `_with_task:292` phụ thuộc worktree → ở lại `routes.py` nhưng gọi
  `o.workspace(...)` qua ctx.
- `orchestrator.py`: `from .orch.routes import *` + `__all__` liệt kê tên public.
- Test `test_routes_match_front_matter` (`tests/test_orchestrator.py:96`) không đổi.
- Cạm bẫy: `_no_test_author:284` dùng `o._remember(f"no-test-author:{tid}")` — **thêm thế hệ tại đây** (K1.4):
  `f"no-test-author:{tid}:{o.lead.retries.get(tid, 0)}"`. Test hai chiều: ticket rework lần 2 không có test-author
  → audit `no_test_author` ghi lần hai.

### PR K1.3 `refactor(company): K1 — OrchState + rehydrate.py`

- `orch/state.py` như trên; `Orchestrator.__init__:400-484` dựng `self.state = OrchState()`; **giữ property
  alias** `self.processed → self.state.processed` v.v. cho 30 tên (một vòng `for name in fields(OrchState):
  setattr(type(self), name, property(...))` hoặc viết tay) để 28 file test không đổi.
- `orch/rehydrate.py`: `rehydrate(ctx) -> None` nhận `_rehydrate:485-576`, `_nap_lai_hen:577`,
  `_retry_con_can:601`, `_evidence:2088`. Thứ tự replay giữ nguyên (audit trước, lead/supervisor sau — chú thích
  `orchestrator.py:1565`).
- Test: `test_moi_trang_thai_nghiep_vu_song_sot_qua_restart:579` phải đỏ nếu bỏ một dòng rehydrate của bất kỳ
  trường nào — thêm test tham số hoá theo `fields(OrchState)` với `rehydrate != RAM-only`: ghi audit tương ứng
  vào bus, mở lại, khẳng định trường không rỗng.
- Cạm bẫy: `deferred`/`defer_until:460,463` hiện chỉ khôi phục một phần; ghi metadata thật thà
  `"audit:defer.until (một phần: mất event chưa có audit)"` và mở issue, không giả vờ.

### PR K1.4 `refactor(company): K1 — worktree_flow.py`

- Nhận `_integrate_approved:1073`, `_branch_ahead:1087`, `_merge_ticket:1096`, `_merge_ticket_locked:1102`,
  `_read_only_tools:1167`, `_author_tests:1179`, `_engineer:1198`, `_learn_repo:621`, `integration_for:644`…
  `_has_integration:661`, `comment:1835`, `takeover:1845`.
- `_integrate_approved` được gọi từ `process:844`, `run:739`, `_integrate:1157` — để nó ở `worktree_flow` và
  ba nơi gọi qua `ctx`; **không** nhân bản.
- `_merge_lock:417` đi theo vào module (module-level `RLock` hoặc trong `OrchState` với metadata RAM-only).

### PR K1.5 `refactor(company): K1 — scheduler.py`

- Nhận `_actionable:664`, `_track_pause:668`, `_on_event:673`, `_target:693`, `_parallel_ok:696`,
  `_take_batch:703`, `run:715`, `_integrate_pending:744`, `tick:753`, `watch:790`, `_maybe_reload:811`,
  `_defer:1947`, `_retry_deferred:1971`, `_mark:1981`, `_remember:1988`, `_audit:1993`.
- `tick:753` hiện trộn nhắc gate (`766-768`) và giao lại review (`773-784`) — hai đoạn đó sang `gates_flow`
  (PR K1.6) dưới tên `remind_gates(ctx)` và `redispatch_reviews(ctx)`; `tick` gọi hai hàm.
- K1.4 khoá `gate.escalate:{sid}` → `gate.escalate:{sid}:{overdue_count}` với `overdue_count` đếm số lần
  `gate.overdue` của sid trong audit (dựng lại từ audit → thêm trường `overdue_count: Counter` vào `OrchState`).

### PR K1.6 `refactor(company): K1 — gates_flow.py`

- Nhận `_on_gate_decide:1561`, `_check_escalations:1587`, `_check_debt:1622`, `_on_escalation_decided:1644`,
  `_open_acceptance_gate:1795`, `_close_acceptance_gate:1805`, `_stall:1029`, `_after_error:998`,
  `_rework_after_error:1016`, `_retry_stalled:1048`, `_retry_unhandled:1060`, `_record_lessons:1819`.
- Cạm bẫy ghi ở bản đồ: `escalation_decided` tăng ở `_on_gate_decide:1568` và đọc ở `_check_escalations:1614`
  — cả hai cùng module, giữ nguyên thứ tự; `unhandled` ghi từ ba nơi (`1441` plan reject ở ticket_fsm, `1492`
  spec runtime ở ticket_fsm, `1010` ở gates_flow) — ghi qua một hàm `mark_unhandled(ctx, event_id, agent, why)`
  trong `state.py` để không lệch.

### PR K1.7 `refactor(company): K1 — ticket_fsm.py + release_fsm.py với bảng chuyển trạng thái`

- `ticket_fsm.py`: `_plan:1383`, `_check_plan:1529`, `_dispatch_plan:1544`, `_superseded:870`,
  `_note_closed:898`, `_spec_runtime_missing:1457`, `_threat_model:1499`; bảng `TICKET_TRANSITIONS` 13 dòng
  theo §4 bản đồ (nguồn sự thật trạng thái vẫn là `lead.state` trong `delivery.py` — bảng ở đây là **driver**,
  không nhân đôi state).
- `release_fsm.py`: `_release:1249`, `_integrate:1146`, `_void:1163`, `_check_paused_releases:1889`,
  `_superseded_release:1906`, `_release_paused:1915`, `_recall:1923`, `_rerun_release:1931`, `redeploy:1868`,
  `_deliver:1735`, `_rollback_delivery:1770`; bảng `RELEASE_TRANSITIONS` 12 dòng.
- K1.5 tại `release_fsm.release()`: sau `verify.smoke` trả `unverified` → đọc spec `kind` (đã có
  `_verdict_with_run:1352` làm tương tự cho regression) và cờ `legacy` từ `research-requests.payload`; không
  thoả → đi nhánh `smoke fail:1317`. Khoá `smoke.unverified:{rid}:{env.event_id}`, `delivery.skipped:{rid}:{env.event_id}`.
- `process:819` còn lại là: tra `ROUTES` → gọi `ticket_fsm.step` hoặc `release_fsm.step` → `_call`.
- Test bảng `tests/test_orch_bang_chuyen.py`: tham số hoá theo từng `Transition`, dựng bus tối thiểu, khẳng định
  `dst`; thêm 3 cặp cấm (`integrated` + `tasks` cũ, `void` + `release-events`, plan pending + `tasks`) → không
  exception, có audit `superseded`/`ignored`.
- `tests/test_orch_khuon_loi.py` (K1.6 của đặc tả): 5 test theo khuôn; khuôn 3 là test grep:
  `re.findall(r'_remember\(f?"([^"]+)"', src)` → mỗi khoá ≥ 2 thành phần `{}` hoặc nằm trong danh sách miễn có
  lý do (`uat:{rid}`, `lesson:{tid}`, `closed:{tid}`).
- Nghiệm thu cuối K1: `wc -l orchestrator.py` ≤ 300; `test_kich_thuoc_module_orch` (≤ 400/module).

---

## K2 — Sandbox · ADR-0035 + 3 PR

### ADR-0035 `docs(company): ADR-0035 sandbox tiến trình`

Bối cảnh: bảng 9 điểm gọi subprocess (§1 báo cáo sandbox); `run_smoke` chạy lệnh từ spec do model viết;
`SECURITY.md:51-57` tự nhận "sandbox là đường dẫn + env, không phải tiến trình". Quyết định: interface
`Sandbox`, hai backend, `auto`, fail-closed, git ở lại subprocess (lý do: git đã vô hiệu hook, argv hard-code,
và cần credential push của người vận hành). Hệ quả: audit `sandbox=`, console cảnh báo.

### PR K2.1 `feat(company): K2 — sandbox.py với SubprocessSandbox và ContainerSandbox`

```python
# src/company/sandbox.py  (~150 dòng)
@dataclass(frozen=True)
class RunSpec:
    argv: list[str]; cwd: Path; env: dict[str, str]; timeout: float
    network: bool = False; port: int | None = None; max_output: int = 6000
@dataclass(frozen=True)
class Result:
    exit_code: int | None; stdout: str; stderr: str; timed_out: bool; sandbox: str
class Handle(Protocol):           # cho smoke
    def poll(self) -> int | None: ...
    def kill(self) -> None: ...
    def stderr_tail(self, n: int) -> str: ...
class Sandbox(Protocol):
    name: str
    def run(self, spec: RunSpec) -> Result: ...
    def spawn(self, spec: RunSpec) -> Handle: ...
class SubprocessSandbox: ...      # gói nguyên tools.py:253 / workspace.py:125 / smoke.py:107
class ContainerSandbox:
    def __init__(self, runtime: str, image: str, cpus: str = "2", memory: str = "2g", runner=subprocess.run): ...
    def _argv(self, spec) -> list[str]:
        base = [self.runtime, "run", "--rm", "--pids-limit", "256", "--cpus", self.cpus, "--memory", self.memory,
                "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{spec.cwd}:/w:rw", "-w", "/w", "--env-file", "-"]
        base += ["--network", "bridge", "-p", f"127.0.0.1:{spec.port}:{spec.port}"] if spec.network else ["--network", "none"]
        return [*base, self.image, *spec.argv]
def sandbox_from_config(cfg: LLMConfig, which=shutil.which) -> Sandbox:
    mode = os.environ.get("COMPANY_SANDBOX") or cfg.sandbox or "auto"
    ...  # auto → container nếu which(runtime) else subprocess; "container" thiếu binary → SandboxError
```

- `llm.py` `LLMConfig` thêm `sandbox`, `sandbox_image`, `sandbox_runtime` (+ env `COMPANY_SANDBOX*`, đọc ở
  `llm.py:259-275`); `llm.example.yaml` thêm ba dòng có chú thích.
- Container luôn chạy `-u uid:gid` của người vận hành (ADR gốc 0031 bỏ nhánh Windows `:no-uid`).
- Test `tests/test_sandbox.py`: bộ hợp đồng chạy cho cả hai backend (backend container dùng `runner=` giả trả
  `CompletedProcess`); khẳng định argv; fail-closed; env đã qua `clean_env` (không key nào khớp `SECRET_ENV`).

### PR K2.2 `feat(company): K2 — tools.run, workspace lint/test, smoke đi qua Sandbox; audit sandbox=`

- `tools.py:245-257`: `WorkspaceTools.__init__` nhận `sandbox: Sandbox`; `run` dựng `RunSpec` và gọi
  `sandbox.run`; `ToolBox.call:86` ghi `"sandbox": result.sandbox` vào `calls`.
- `workspace.py:125` `TicketWorkspace._run`: cùng cách; `local_checks` thêm `sandbox`.
- `smoke.py:96-137`: `Popen` → `sandbox.spawn(RunSpec(network=True, port=port))`; vòng poll giữ nguyên;
  `out["sandbox"]`. Với container, URL probe vẫn `127.0.0.1:<port>` nhờ `-p`.
- `runner.py:380,421`, `orchestrator.py` (`_read_only_tools`, `_engineer`, `_author_tests` — sau K1 ở
  `worktree_flow`): truyền `ctx.sandbox` (dựng một lần trong `Orchestrator.__init__` từ `sandbox_from_config`).
- Schema: `topics/schemas/pull-requests.json` `local_checks` thêm `sandbox: {type: string}` optional;
  `release-events.json` `smoke` thêm `sandbox`. Schema đổi nhưng **không đổi prompt** (agent không điền trường
  này) → không cần eval-record; kiểm bằng `make golden` không diff.
- `SECURITY.md`, `companies/software-company/README.md:270-278` cập nhật.
- Test hai chiều: `test_smoke_evidence.py` thêm ca sandbox giả ghi `sandbox` vào evidence; ca `container` thiếu
  binary → `SandboxError` nổi lên thành `smoke.failed` với `reason` rõ (khuôn 1).

### PR K2.3 `feat(studio): K2 — CommandTTS, ffmpeg, qc qua Sandbox; clean_env; timeout`

- Trước K3: copy `sandbox.py` sang `studio/sandbox.py` **có ghi chú "bản tạm, xoá ở K3.2"**; sau K3 thì import.
- `media.py:614-622` `CommandTTS`: env → `clean_env()` (studio chưa có `clean_env` → lấy từ company
  `workspace.clean_env`, hoặc đưa vào `sandbox.py`); đi qua `sandbox.run`.
- `media.py:787` `FFmpegVideo._run`: thêm `timeout` (mặc định 600 s, cấu hình `media.yaml render.timeout_s`);
  qua sandbox với `-v <output_dir>:/w`.
- `qc.py:52`: qua sandbox (chỉ đọc: `-v :ro`).
- Audit `render.*` thêm `sandbox`.
- Console K2.7: `collect.py` đọc audit `sandbox` 24h + `sources.company.sandbox_available` (`shutil.which("docker")`
  trên máy console) → tile cảnh báo; test render.

---

## K3 — `xagents-core` · ADR gốc 0001 + 8 PR

### ADR gốc `docs/adr/0001-loi-chung-xagents-core.md`

Bối cảnh: 0 import chéo, ~1.200 dòng trùng nguyên văn, fix `claude -p` chỉ vá một bên, studio thiếu 16 module.
Quyết định: package thứ năm, `CoreConfig` tham số hoá, shim, thứ tự 7 bước, company là gốc, studio được nâng.
Hệ quả: một chỗ sửa bug; studio đổi hành vi (hoãn thay vì dừng); shim tồn tại tới chân trời 3.

### Cấu trúc package

```
platform/xagents-core/
  pyproject.toml        # name = "xagents-core", packages = ["src/xagents_core"], deps: jsonschema, pydantic, pyyaml
                        # [tool.mypy] strict = true ; [tool.coverage.report] fail_under = 100 ; ruff như bốn package
  src/xagents_core/
    __init__.py         # __version__
    config.py           # CoreConfig
    context.py  tools.py  llm.py  routing.py  guard.py  events.py  bus.py  sqlite_bus.py
    registry.py  blackboard.py  runner.py  evals.py  gates.py  gate_cli.py  supervisor.py  sandbox.py
  tests/
```

```python
# src/xagents_core/config.py
@dataclass(frozen=True)
class TopicACL:
    producers: Mapping[str, frozenset[str]]; human_topics: frozenset[str]; open_topics: frozenset[str]
    engineering_actors: frozenset[str]; review_producers: frozenset[str]
@dataclass(frozen=True)
class CoreConfig:
    prefix: str                       # "COMPANY" | "STUDIO" — tiền tố env, thông điệp lỗi, tên tool MCP
    root: Path                        # gốc package công ty: llm.yaml, agents/, skills/, topics/schemas, evals/
    db_name: str                      # "company.sqlite"
    payload_models: Mapping[str, type[BaseModel]]
    namespace_owners: Mapping[str, str]
    transitions: Mapping[str, frozenset[str]]
    topic_acl: TopicACL
    external_topics: frozenset[str]; derived_topics: frozenset[str]
    approvers_env: str                # f"{prefix}_GATE_APPROVERS"
    @property
    def config_file(self): return self.root / "llm.yaml"
    @property
    def schema_dir(self): return self.root / "topics" / "schemas"
```

Mỗi công ty: `src/company/core.py` dựng `CORE = CoreConfig(prefix="COMPANY", root=Path(__file__).resolve().parents[2], ...)`.
Shim mẫu:

```python
# src/company/routing.py  (sau K3.3)
"""Shim: giữ tên `company.routing` cho platform/console/test. Xoá ở chân trời 3 (xem docs/DAC-TA-KICH-BAN-B.md K3.a)."""
from xagents_core.routing import *  # noqa: F401,F403
from xagents_core.routing import __all__  # noqa: F401
```

Với module cần `CORE` (llm, bus, registry, evals…): shim là hàm bọc mỏng — ví dụ `company/llm.py`:
`make_client = functools.partial(xagents_core.llm.make_client, core=CORE)`; `load_config = partial(...)`. Test
package đang gọi `company.llm.load_config()` không đổi.

### PR K3.0 `build(core): K3.0 — khung xagents-core, CI core-static/core-unit, ruleset`

- Root `pyproject.toml`: `members += ["xagents-core"]`, `[tool.uv.sources] xagents-core = {workspace = true}`;
  `uv lock`.
- `companies/software-company/pyproject.toml`, `Studio-creators/pyproject.toml`: `dependencies += ["xagents-core"]` +
  sources. **Bẫy**: tên phân phối studio là `video-creators`.
- `ci.yml`: hai job theo khuôn `console-static`/`console-unit` (dòng ~300), `working-directory: xagents-core`;
  `quality.needs += [core-static, core-unit]`; `.github/rulesets/main.json` thêm 2 context (nếu required check
  là `quality` tổng thì chỉ cần `needs`; đọc `protection-guard:325-376` để chắc).
- `Makefile` gốc: fan-out thêm `xagents-core`.
- `platform/xagents-core/tests/test_smoke.py`: import package, `__version__`.
- Nghiệm thu: `quality` xanh, `protection-guard` xanh.

### PR K3.1 `refactor(core): K3.1 — context.py`

- Move `company/context.py` (126) + `tests/test_context*.py` → core; shim; `studio/runner.py` gọi `fit` như
  `company/runner.py:33` (đây là thay đổi hành vi nhỏ của studio: cắt ngữ cảnh — ghi CHANGELOG studio).

### PR K3.2 `refactor(core): K3.2 — ToolBox khung`

- Core `tools.py`: `ToolError, ToolSpec, ToolCall, ToolBox` (từ `company/tools.py`), thêm `urls()` từ studio,
  `dump_calls` từ company. `tools_prompt` ở lại hai bên.
- `company/tools.py`: `WorkspaceTools(ToolBox)` import từ core; `studio/tools.py`: `WebTools` tương tự.
- Đồng thời chuyển `sandbox.py` (K2) sang core; xoá bản tạm studio.

### PR K3.3 `refactor(core): K3.3 — llm.py + routing.py (một PR, có chu trình import)`

- Gốc là `company/llm.py` (1.128) + `company/routing.py` (196). Tham số hoá:
  - `ROOT/CONFIG_FILE:48-49` → `core.root`, `core.config_file`.
  - Env `llm.py:259-275`: `f"{core.prefix}_LLM_PROVIDER"` v.v. Hàm `env_name(core, "LLM_PROVIDER")`.
  - Chuỗi lỗi `llm.py:203`: `f"... ({core.prefix}_MODEL_{tier.upper()} hoặc llm.yaml)"` — test company assert
    `COMPANY_MODEL_` vẫn qua.
  - `MCP_TOOL_NOTE:764` `mcp__company__` → `f"mcp__{core.prefix.lower()}__"`.
  - `cli_env:804` keep-prefix lấy từ `core.prefix`.
  - `ModelClient.complete(..., workdir: Path | None = None)` — studio adapter bỏ qua.
  - `anthropic_input_tokens` thống nhất 3-tuple; studio caller (`studio/llm.py:231`) sửa.
  - Studio-only giữ: `CLI_WEB_TOOLS`, `CLI_TOOL_TURNS = 8` → thành `CoreConfig.cli_extra_tools`, `cli_tool_turns`.
- `studio/llm.py`, `studio/routing.py` → shim; **xoá** `TRANSIENT_PATTERNS/is_transient_error`
  (`studio/routing.py:30,57`); studio `orchestrator` bắt `TransientError` → hoãn (copy đoạn tương ứng của
  company `_call:919` nhánh `except TransientError`), sửa `Studio-creators/TRAPS.md` mục "LLMError dừng orchestrator".
- Test: `platform/xagents-core/tests/test_llm.py`, `test_routing.py` nhận phần trung lập; test hai package giữ phần assert
  chuỗi/prefix; thêm test studio `test_transient_hoan_khong_dung`.
- **K5 mở khoá sau PR này.**

> **Trạng thái: K3.3 XONG** (a #150 · c1 #152 · c2 #173 · c3 bước 1 #174 · c3 bước 2 #175 · **d #176**). K3.3 không đi
> một PR như đặc tả viết mà tách năm bước theo *mức rủi ro* — lý do và số đo `difflib` từng bước ghi ở
> `platform/xagents-core/src/xagents_core/llm.py` (docstring) và `docs/sessions/2026-09-08.md`.
>
> Hai chỗ đặc tả trên **đã lỗi thời, giữ nguyên làm biên bản**: (a) "một PR, có chu trình import" — thực tế
> năm PR, không gặp chu trình nào vì `routing` chỉ nhập từ `llm`/`tools` chứ không ngược lại; (b) bốn adapter
> và `Completion` lệch quá xa để tham số hoá như mục "Tham số hoá" hình dung — `MCP` ở lại company, `complete()`
> của `ClaudeCodeClient` ở lại mỗi công ty. **K5 nay mở khoá.**

### PR K3.4 `refactor(core): K3.4 — guard.py`

- `EXTERNAL_TOPICS/DERIVED_TOPICS:51-54` → `core.external_topics/derived_topics`.
- Xoá `studio/runner.py:29-81` + dòng 265; runner studio gọi `guard.guard_payload`/`sanitize_tool_output`.
- `assetscan.py` (company) import guard qua shim — job `asset-scan` không đổi.

> **Trạng thái: XONG (#177).** Ba gạch trên viết K3.4 như một lần chuyển mã; **thực tế nó là hợp nhất HAI
> CHIỀU**. Studio không có `guard.py` — nó có một bộ mẫu *khác* nằm lẫn trong `runner.py`, và đo chéo 23 câu thử
> cho thấy **mỗi bên đều có lỗ**: company trượt 4 mẫu studio bắt được, studio trượt 8 mẫu company bắt được. Nên
> "lấy bản company" là làm mất bốn thứ ở cả hai bên. Ba quyết định hợp nhất, mỗi cái kèm số đo, ghi ở docstring
> `platform/xagents-core/src/xagents_core/guard.py`; đáng nhớ nhất là mẫu tiếng Việt được **viết lại tốt hơn cả hai bản
> cũ** (bản company trượt "bỏ qua mọi hướng dẫn", bản studio báo nhầm "tôi quên hướng dẫn cài đặt rồi").
>
> Hai điểm khác lời đặc tả: (a) `CoreConfig` cần **hai trường mới** ngoài hai trường đã đặt trước —
> `untrusted_fields` (danh sách trường là của từng công ty vì topic hai bên khác nhau) và
> `extra_injection_patterns` (mẫu riêng); (b) `assetscan.py` không "import guard qua shim" mà đọc bảng mẫu ĐÃ
> BIÊN DỊCH — trước đây qua tên riêng tư `guard._COMPILED`, nay là `guard.COMPILED` công khai.

### PR K3.5 `refactor(core): K3.5 — events chung + bus + sqlite_bus (rủi ro cao nhất)`

- Core `events.py`: `Envelope` (bản company: `schema_version`, `correlation_id`, `causation_id`,
  `model_post_init`, `child`), `SharedContext`, `AuditLog`, `SupervisorAction`, `can_transition(src, dst,
  transitions)`. `Topic`/`Namespace` Literal, mô hình miền, `PAYLOAD_MODELS`, `NAMESPACE_OWNERS`, `TRANSITIONS`,
  `RISK_TAGS`, `BUDGET_FACTOR` ở lại từng package và **đưa vào `CORE`**.
- Core `bus.py` = bản company (validator, ACL qua `core.topic_acl`, `nullable_fields`, `latest`,
  `_notify_safely`); `SCHEMA_DIR:14` → `core.schema_dir`.
- Core `sqlite_bus.py` = bản company (Lease, `latest`, `close`); `"company.sqlite":26` → `core.db_name`;
  `BUSY_TIMEOUT_S` của studio thành hằng chung.
- Studio: `Envelope` cũ 6 trường → dùng core; ba trường mới có default (`schema_version=1`,
  `correlation_id=None`, `causation_id=None`). **Fixture** `Studio-creators/tests/fixtures/studio-0.1.0.sqlite`
  ghi bằng bản trước PR này; test mở được, replay được.
- Console: 0 dòng (import `company.bus`, `studio.bus` qua shim; `studio.bus` nay có `latest()` → `decide.py`
  không cần đổi nhưng có thể đơn giản hoá sau).
- Nghiệm thu: `make demo` hai công ty; `console` test xanh; chạy thật company ≥ 5 ngày trước K3.6.

> **Trạng thái: K3.5 TÁCH BA BƯỚC; bước a XONG (#178).** Lý do tách: đo `difflib` cho thấy ba module lệch rất
> khác nhau — `sqlite_bus` 0.44, `events` 0.14, **`bus` 0.06**. Ở mức 0.06 hai file gần như không có gì chung;
> gộp cả ba vào một PR là đúng thứ K3.3a đã học được là không nên.
>
> - **K3.5a — `events` chung: XONG (#178).** `Envelope`, `SharedContext`, `AuditLog`, `SupervisorAction`,
>   `can_transition` lên core. **Không phải như đặc tả hình dung**: chúng lên dưới dạng **LỚP CƠ SỞ**, mỗi công
>   ty kế thừa (tiền lệ `LLMConfig` ở K3.3b). Lý do đo được: chỗ lệch không phải "một bên thiếu" mà là *trường
>   phạm vi của từng miền* — `AuditLog` company có `ticket_id`/`project_id`, studio có `video_id`/`channel_id`;
>   đưa cả bốn lên core là bắt company mang một trường nó không bao giờ ghi. Cùng lý do, `topic`/`namespace` ở
>   core là `str`, lớp con thu hẹp về Literal của mình nên kiểm tra topic KHÔNG mất, chỉ chuyển xuống nơi biết
>   đủ để làm việc ấy.
> - **K3.5b — `bus`: XONG (#179).** Cơ chế lên core **toàn bộ**; thứ mỗi công ty đưa vào là DỮ LIỆU
>   (`CoreConfig.topic_acl`/`payload_models`/`namespace_owners`). Khác K3.5a: ở đây `difflib` 0.06 KHÔNG nghĩa
>   là hai bus khác bản chất, mà là bus studio 61 dòng chưa làm phần lớn việc bus company 206 dòng đã làm —
>   lệch vì MỘT BÊN THIẾU, nên hợp nhất là đúng, không phải gộp hai miền.
>   Ba điểm lệch so với đặc tả: (1) **`topic_acl` của studio ĐO chứ không suy** — front matter `writes` thiếu
>   năm actor là CODE (`renderer`, `desk`, `orchestrator`, `adapter:youtube`, `chapters`); đo 76 cặp
>   `(actor, topic)` kèm khung ngăn xếp, 26 cặp production thành bảng, 14 cặp test-only sửa fixture chứ không
>   mở lối. (2) **Console KHÔNG phải 0 dòng**: câu lỗi thiếu trường của studio nay là câu `jsonschema` giống
>   company, 1 dòng test đổi. (3) **Bật validate envelope làm lộ 19 schema studio lỗi thời từ K3.5a** — chúng
>   `additionalProperties: false` mà chưa biết ba trường K3.5a thêm vào; K3.5a không thấy được vì studio khi ấy
>   chưa validate envelope. `_extra_publish_checks` là điểm mở duy nhất, cho luật `gate.decide` riêng của company.
> - **K3.5c — `sqlite_bus`: XONG (#187).** Bước DUY NHẤT của K3.5 mà "lấy bản company" là mô tả đúng:
>   `difflib` 0.442, cùng `_DDL`, cùng cách nạp `_log`, cùng `INSERT`, cùng `replay`; sáu hàm chỉ company có
>   (`latest`, `_persist_only`, `__del__`, `_alive`, `Lease.acquire/release`) là company đi xa hơn trên cùng
>   con đường, không phải hai miền khác nhau. Ba quyết định hợp nhất ở docstring core; đáng nhớ nhất là
>   `check_same_thread=False`: bản studio thiếu cờ ấy, và nó chưa nổ chỉ vì runner studio chạy một thread.
>   Hai điểm khác lời đặc tả: (a) `"company.sqlite":26` → `core.db_name` đúng như đặc tả, nhưng `BUSY_TIMEOUT_S`
>   **thay luôn `timeout=30` của company** chứ không chỉ "thành hằng chung" — hai bên cùng một con số, một bên
>   có tên; (b) thứ tự tham số `InMemoryBus.__init__` của CẢ HAI công ty phải đổi thành `(cfg, enforce_owners)`:
>   `SQLiteBus` kế thừa cả bus công ty lẫn `SQLiteBus` core, nên `super().__init__(cfg, ...)` đi qua lớp công ty
>   theo MRO và thứ tự cũ làm `cfg` rơi vào `enforce_owners` **im lặng**. Đặc tả không lường được điều này vì
>   nó viết K3.5 như một PR gộp, nơi bus công ty không còn là lớp cha thứ hai.
>
> Hai điểm khác lời đặc tả ở bước a: (a) `can_transition` **không** chỉ là `dst in transitions[src]` — cả hai
> công ty có cửa thoát `dst in {"blocked","escalated"}`, và quên nó làm **12 ca của company đỏ**; nay nó là
> tham số `always=` chứ không viết cứng tên trạng thái của một công ty vào core. (b) Fixture
> `studio-0.1.0.sqlite` **không** commit dưới dạng file nhị phân: `AGENTS.md` luật 3 cấm `*.sqlite*` và
> `.gitignore` chặn thật, nên "định dạng cũ" được dựng bằng SQL + JSON ngay trong test — không có blob trong
> git, và hình dạng cũ đọc được bằng mắt.

### PR K3.6 `refactor(core): K3.6 — registry, blackboard, runner, evals`

- `registry`: `ROOT:10` → `core.root`; `load_agents(check_owners=True)` mặc định, studio truyền `False` nếu cần.
- `blackboard`: bản company (mirror, project scope); studio `write(Namespace)` → `str`, test studio sửa kiểu.
- `runner`: bản company; hook `toolbox_for(spec, ctx) -> ToolBox` do package cung cấp (`WorkspaceTools` vs
  `default_toolbox`); `MAX_TOOL_TURNS` studio → `CoreConfig.max_tool_turns`.
- `evals`: bản company (`RecordingClient` chốt version ở `__init__:69`, `save` merge `:80-96`); `EVALS_DIR` →
  `core.root/"evals"`; giữ `if not c.tool_calls` của studio khi ghi.
- Studio recording không cần ghi lại (format giống nhau, `prompt_version` đã khớp).

> **Trạng thái: K3.6 TÁCH BỐN BƯỚC; bước a XONG (#188).** Lý do tách giống hệt K3.5: đo `difflib` trước khi làm
> cho thấy bốn module lệch rất khác nhau — `evals` **0.556**, `registry` **0.429**, `blackboard` **0.092**,
> `runner` **0.036** (631 dòng company vs 336 studio, 13 hàm chỉ company có). Gộp cả bốn vào một PR là đổi
> registry + blackboard + vòng lặp tool + đường ghi eval cùng lúc, đúng thứ K3.3a và K3.5 đã học được là không nên.
>
> - **K3.6a — `registry`: XONG (#188).** Hình dạng lệch ở đây là hình dạng THỨ TƯ, chưa gặp trong K3.3–K3.5:
>   **một bên là TẬP CON của bên kia**. Ba hàm chỉ company có (`_load_phases`, `owned_skills`, `reads_full`)
>   đều là *thêm vào*, không phải *khác đi*; phần còn lại của studio giống company gần như từng ký tự. Nên core
>   = bản company đúng như đặc tả, và studio chỉ khai thêm cái nó có riêng.
>   Đặc tả gạch đầu dòng `registry` đúng cả hai vế, nhưng vế thứ hai **cần một con số nó không có**: "studio
>   truyền `False` nếu cần" — đo ra là **có cần**, vì `skills/` của studio hiện có ba skill không agent nào nạp
>   đầy đủ (`content-policy`, `cost-estimation`, `finops`). Đó là nợ có thật của studio, không phải khẩu vị API;
>   có một ca ghi lại đúng ba tên ấy và sẽ đỏ khi nợ được trả.
>   Một điểm đặc tả không nhắc: **`spec_cls`**. Studio có trường `tools` (ADR-0007 của studio) mà core không
>   được biết, nên `load_agents` phải dựng ĐÚNG lớp `AgentSpec` của công ty — dựng bằng lớp core là làm rơi
>   trường ấy im lặng, cùng cái bẫy `envelope_cls` ở K3.5b.
> - **K3.6b — `blackboard`: XONG (#189).** Hình dạng lệch **giống K3.5b** (một bên thiếu), nên cách xử lý cũng
>   giống: core giữ toàn bộ cơ chế, công ty đưa vào dữ liệu (`cfg.global_namespaces`, `EXT`) và lớp
>   (`envelope_cls`/`context_cls`). Đặc tả viết đúng cả hai gạch (`blackboard`: bản company; studio
>   `write(Namespace)` → `str`), nhưng bỏ sót một hệ quả: **`project_id` và `content` phải lên core cùng nó**.
>   K3.5a đã xếp hai trường ấy vào "thứ company thêm" khi chỉ nhìn model; nhìn từ blackboard thì chúng LÀ hai
>   cơ chế của blackboard (phân vùng ADR-0018, toàn văn ADR-0012). Ca canh của K3.5a không bị nới lỏng mà đổi
>   thành cấm theo từng lớp — `project_id` vẫn cấm trên `AuditLog`, chỉ mở trên `SharedContext`.
>   Điểm thứ hai đặc tả không lường: `scope_of`/`context_key` của company **thôi là hàm module** (chúng đọc
>   `global_namespaces`, nay ở `CoreConfig`), nên một ca test vá hàm module phải đổi sang vá phương thức —
>   không đổi thì ca ấy vẫn xanh mà không còn đo gì.
> - **K3.6c — `evals`: XONG (#191).** Đặc tả viết "bản company (`RecordingClient` chốt version ở `__init__:69`,
>   `save` merge `:80-96`); giữ `if not c.tool_calls` của studio khi ghi" — **đúng cả ba vế**, đây là gạch đầu
>   dòng chính xác nhất của cả K3. Nhưng nó bỏ sót một thứ lớn hơn: `main` và `CaseResult` không phải cơ chế
>   mà là **CHÍNH SÁCH CỔNG**, và hai công ty quyết định "cái gì làm CI đỏ" khác nhau (company tách điểm chấm
>   khỏi cổng bản ghi; studio đỏ khi bất kỳ ca nào không chạy được). Lấy `main` của company là âm thầm nới
>   lỏng cổng của studio — nên `main` ở lại từng công ty, và `CaseResult` mang HAI trường có tên
>   (`broken_recording`, `errored`) thay vì một cờ.
>   `EVALS_DIR → core.root/"evals"` làm đúng như đặc tả, nhưng phải đi **qua biến module** chứ không tính từ
>   `self.root`: 20 chỗ test dùng `monkeypatch.setattr(evals, "RECORDINGS_DIR", …)` làm seam, và tính từ
>   `self.root` là seam ấy im lặng hết tác dụng. Cùng khuôn với `scope_of` ở K3.6b.
> - **K3.6d — TÁCH ĐÔI; CẢ HAI XONG (d1 #194, d2 #195).** Lý do tách không phải độ lệch mã mà là **bản ghi eval**: khoá bản
>   ghi là `hash(system_prompt, user_message)` và `user_message` do `build_user_message` sinh ra. Đo trực
>   tiếp — thêm MỘT DẤU CÁCH vào prompt studio thì `evals all --replay` báo lệch toàn bộ. Hợp nhất bất kỳ CHỮ
>   nào trong prompt đòi `make eval-record` bằng model thật cho 20 agent (7 bước `CONTRIBUTING.md` §3, cần API
>   key) — không phải việc của một PR chuyển mã.
>   **d1 (xong)**: `RunnerError`, `RunResult`, `Generated`, `payload_schema`, `output_schema` — mọi chuỗi
>   prompt giữ nguyên từng byte, nghiệm thu bằng `evals all --replay` hai công ty 0 FAIL.
>   `context_writes_schema` ở lại từng công ty (company đòi `content` ADR-0012, studio không), nên
>   `output_schema` NHẬN nó làm tham số.
>   **d2 (XONG, #195) — K3.6 kết thúc ở đây.** Nguyên tắc gắt hơn mọi bước trước: *cơ chế lên core, **hành vi
>   quan sát được của mỗi công ty giữ nguyên từng byte***. Lên core: `__init__`, `_audit`, `run`,
>   `run_context`, `write_context`, `publish`. Ở lại: `generate` + vòng lặp tool (chạm prompt),
>   `generate_in_workspace`/`author_tests` (phụ thuộc `workspace.py`), `_filter_comments` (studio).
>   Đặc tả viết "`runner`: bản company". Làm đúng chữ ấy thì studio đổi hành vi ở HAI chỗ mà không ai thấy:
>   (a) `write_context` audit `context_no_content` **mỗi lần ghi** (studio không có `content` trong hợp đồng
>   đầu ra); (b) `publish` nối chuỗi nhân quả bằng `inp.child()`, tức **đổi nội dung event trên bus**. Cả hai
>   giải bằng **tham số** (`wants_content`, hook `_new_envelope`) nên không bên nào mất gì. Hai hook nữa cùng
>   loại: `_audit_scope` (trường phạm vi `AuditLog`, khuôn K3.5a) và `_produced_evidence`.
>   Đặc tả đoán sai một chi tiết: **`MAX_TOOL_TURNS` không cần lên `CoreConfig`** — vòng lặp tool ở lại từng
>   công ty vì nó dựng `tools_prompt`, nên hằng ấy ở lại cùng nó. `toolbox_for(spec, ctx)` cũng vậy: studio đã
>   có `toolbox_factory` từ trước, company cấp tool theo đường khác, không cần hook chung ở core.
>   **Đo hai chiều để lộ một lỗ hổng của chính bộ test**: hai đột biến (`wants_content=True`, ép `child()`)
>   làm ba ca core đỏ nhưng **cả 557 ca studio vẫn xanh** — nghĩa là "dọn" hai hook ấy đi thì studio hỏng âm
>   thầm. Đã thêm `Studio-creators/tests/test_runner_core.py` chốt ba hành vi; đo lại thì studio đỏ đúng chỗ.

### PR K3.7 `refactor(core): K3.7 — gates, gate_cli, supervisor hợp nhất hai chiều`

- `gates`: `overdue()` (company) + `gate_approvers/enforce` (studio); `APPROVERS_ENV` → `core.approvers_env`.
- `gate_cli`: `SYSTEM_GATE_ACTOR`, `trusted_decision`, `decide(actor=)` (company) + `format_checklist`,
  `rollback_target` (studio; `rollback_target(bus, vid)` là miền video → ở lại `studio/gate_cli.py` như hàm thêm).
- `supervisor`: bản company (debt, USD, `escalate_gate`, `sprint_report`) + `_act_once`, `report()` studio;
  `Task`/`VideoBrief` → `core.ticket_model` (chỉ dùng để đọc `budget_tokens`, `project_id` — định nghĩa Protocol
  `Budgeted` thay vì model cụ thể).
- Company nhận four-eyes `enforce` — **đổi hành vi**: gate company nay đọc `COMPANY_GATE_APPROVERS`; mặc định
  rỗng = không ép (giữ hành vi cũ); ghi `docs/TRUC-VA-DUNG-KHAN.md` §2 "người trực không tự duyệt" nay có
  code ép khi khai biến.
- Sau PR: `ARCHITECTURE.md`, `CODEMAP.md` gốc + hai package cập nhật; `make test` gốc chạy 5 package.

---

## K4 — Bus phiên bản, đọc lười · ADR gốc 0002 + 2 PR

### PR K4.1 `feat(core): K4.1 — PRAGMA user_version + migration`

```python
SCHEMA_VERSION = 1
_MIGRATIONS: dict[int, list[str]] = {}          # {1: ["ALTER TABLE ...", ...]} khi lên 2
def _open_schema(db):
    ver = db.execute("PRAGMA user_version").fetchone()[0]
    if ver == 0:
        db.executescript(_DDL); db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    elif ver > SCHEMA_VERSION:
        raise BusError(f"file bus phiên bản {ver} mới hơn code ({SCHEMA_VERSION}); nâng cấp code trước")
    else:
        for v in range(ver, SCHEMA_VERSION):
            with db: [db.execute(s) for s in _MIGRATIONS[v + 1]]; db.execute(f"PRAGMA user_version={v + 1}")
```

- Bẫy: file cũ đã có bảng nhưng `user_version=0` → nhánh `ver == 0` chạy `IF NOT EXISTS`, vô hại, rồi đóng dấu 1.
- Test: version 0 có dữ liệu → 1 giữ dữ liệu; version 99 → lỗi; migration giả `{2: ["ALTER TABLE events ADD
  COLUMN x"]}` với `SCHEMA_VERSION=2` monkeypatch → cột xuất hiện; migration lỗi giữa chừng → `user_version`
  không đổi.
- `orchestrator status` in `bus_schema_version`.

### PR K4.2 `perf(core): K4.2 — mở bus không nạp toàn log; replay lười; index topic`

- Bỏ `sqlite_bus.py:38-40`; `_seq = SELECT COALESCE(MAX(seq),0)`; `__len__` override `COUNT(*)`; `_seen` bỏ,
  `publish` bắt `sqlite3.IntegrityError` → bỏ qua trùng (giữ ngữ nghĩa cũ), `poll` lọc theo `seq`.
- `replay()` trả generator từ cursor; rà `grep -rn "replay(" software-company Studio-creators console` — nơi
  index hoặc `len()` bọc `list(...)`: đã biết `blackboard.py:113`, `metrics.py:46,168`, `collect.py:552`
  (`len(v.envelopes)` → dùng `len(bus)`), `gate_brief.py:212-556`.
- `gate_brief`: một `_ReplayCache` theo topic dựng đầu `build()`; index `ix_events_topic`.
- Test hiệu năng: tạo 100k event trong tmp, mở bus, `perf_counter` < 1 s (ngưỡng nới cho CI), và `len(bus)`
  đúng; `pytest -m perf` để không chạy mỗi lần nếu chậm.

---

## K5 — Eval ghi từ CI · 1 PR

### PR K5 `ci: K5 — workflow eval-record bằng API key trong Secrets`

`.github/workflows/eval-record.yml`:

```yaml
name: eval-record
on:
  workflow_dispatch:
    inputs:
      package: {type: choice, options: [software-company, Studio-creators], required: true}
      agents:  {type: string, default: all}
      provider: {type: choice, options: [anthropic, openai], default: anthropic}
jobs:
  record:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    permissions: {contents: write, pull-requests: write}
    env:
      PREFIX: ${{ inputs.package == 'software-company' && 'COMPANY' || 'STUDIO' }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --locked
      - name: Ghi eval
        working-directory: ${{ inputs.package }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          export ${PREFIX}_LLM_PROVIDER=${{ inputs.provider }}
          export ${PREFIX}_MODEL_STRONG=${{ vars.EVAL_MODEL_STRONG }} ${PREFIX}_MODEL_STANDARD=${{ vars.EVAL_MODEL_STANDARD }} ${PREFIX}_MODEL_LIGHT=${{ vars.EVAL_MODEL_LIGHT }}
          [ "${{ inputs.provider }}" = openai ] && export ${PREFIX}_LLM_API_KEY="$OPENAI_API_KEY" ${PREFIX}_LLM_BASE_URL=https://api.openai.com/v1
          uv run python -m $([ "$PREFIX" = COMPANY ] && echo company || echo studio).evals ${{ inputs.agents }} --record --jobs 3 | tee -a "$GITHUB_STEP_SUMMARY"
      - uses: peter-evans/create-pull-request@v7
        with:
          branch: chore/eval-record-${{ github.run_id }}
          title: "chore(${{ inputs.package == 'software-company' && 'company' || 'studio' }}): ghi lại eval ${{ inputs.agents }}"
          labels: no-changelog
          commit-message: "chore: ghi lại eval ${{ inputs.agents }} bằng ${{ inputs.provider }} (workflow ${{ github.run_id }})"
```

- `evals.py` thêm `--jobs N` (`ThreadPoolExecutor` theo agent; mỗi agent một `RecordingClient` riêng; `save`
  merge nên an toàn). `evals.py:279-280` dựng client trong worker.
- Model đặt ở repo **Variables** (`EVAL_MODEL_*`), key ở **Secrets**; tài liệu ghi cách đặt.
- `CONTRIBUTING.md` §3 bước eval-record: "hoặc Actions → eval-record → chọn package/agent". `TRAPS.md` company
  mục ~2,5 phút/agent thêm "workflow chạy 3 luồng".
- Nghiệm thu: chạy với `agents=clarifier`, PR tự mở, `evals all --replay --strict` xanh trên PR đó.

---

## K6 — mypy strict · 3 PR nhỏ rải theo K1/K3

- K6.1 nằm trong PR K3.0 (`strict = true` core).
- K6.2 `chore(company): K6.2 — disallow_untyped_defs cho orch/`: `[[tool.mypy.overrides]] module =
  "company.orch.*"`; sửa annotation phát sinh; CI static.
- K6.3 `refactor(company): K6.3 — StepResult/Generated/RunResult có kiểu ở ranh giới`: `StepResult` thành
  dataclass có trường rõ; đếm `dict[str, Any]` trước/sau trong thân PR.

---

## K7 — Console · 4 PR

### PR K7.1 `refactor(console): K7.1 — tách index.html thành ES module`

- `static/js/util.js` (`fold/hl/sortRows` 765-802), `api.js` (`api` 815, `BLANK` 825), `stream.js`
  (`load/stream/parseFrame/connect/accept/offer/applyPending` 864-960), `router.js` (`readHash/writeHash/
  showView/applyRoute` 995-1037), `drawer.js` (`openGate/openTicket/openVideo/openRelease` 1302-1624),
  `render.js` (`renderQueue/renderBoards/renderTables/renderProductFunnel/renderTiles/renderStreams/render`
  1241-1777), `charts.js` (`costChart/retChart/agentChart` 1701-1763), `main.js` (khởi động, dòng 1826 và
  listener cấp cao).
- `index.html`: `<script type="module" src="/static/js/main.js">`; giữ `"use strict"` không cần (module mặc
  định strict).
- `server.py` `_CONTENT_TYPES` đã có `.js` → kiểm `text/javascript`; `sw.js` cache list thêm các file mới.
- Test: `test_static_js_phuc_vu_dung_content_type`; test hiện có render HTML (`test_redesign.py`) đọc DOM bằng
  string — nếu test đang tìm hàm JS trong `index.html` thì chuyển sang tìm trong `static/js/*.js`.

### PR K7.2 `refactor(console): K7.2 — /api/boot thay inline window.__CONSOLE__`

- `server.py:557` `_serve_index` bỏ chèn script; thêm `GET /api/boot` (không token) trả `{views, allow_*}`
  **không** trả token; token lấy từ `#token=` một lần rồi `history.replaceState` xoá (hoặc giữ cách in
  terminal + ô dán token). Quyết định trong PR: chọn cách ít đổi hành vi nhất = terminal in URL có `#token=`,
  client đọc và xoá khỏi hash.
- Sau đó thêm CSP `default-src 'self'` vì không còn inline.

### PR K7.3 `feat(console): K7.3 — danh tính người duyệt gắn token`

- `__main__.py`: `--approver human:<tên>` (action append). Với mỗi approver sinh một token
  (`generate_token`:93), ghi `platform/console/.console-token-<tên>` 0600, in URL riêng từng người.
- `server.py`: `_authorized:258` trả **tên** thay vì bool (`None` nếu sai); `_api_decide:455-464` điền
  `by = self.identity` và **bỏ** `by` từ body; không `--approver` → token duy nhất → `identity=None` → dùng body
  như cũ và `collect()` gắn cờ `anonymous_decide=True` → banner.
- `decide.py:45-58` không đổi.
- Test hai chiều: token A + body `by=human:B` → audit `human:A`; four-eyes hai token qua, cùng token bị
  `gate_approvers` chặn (studio đã có; company có sau K3.7 — trước đó test chỉ với studio).
- `docs/HUONG-DAN-VAN-HANH.md` mục console: cách chạy nhiều người.

### PR K7.4 `test(console): K7.4 — contract test với schema hai công ty`

- `tests/test_hop_dong_schema.py`: nạp `companies/software-company/topics/schemas/*.json` và `Studio-creators/...`;
  bảng `FIELDS_READ = {("pull-requests", "local_checks.verified_by"), ...}` liệt kê mọi đường trường mà
  `collect.py`, `truth.py`, `brief.py` đọc (rút từ code, ~40 mục); khẳng định mỗi đường tồn tại trong schema
  (`properties` lồng). Hai chiều: monkeypatch xoá một `properties` → test đỏ.
- `API.md` cắt phần shape, giữ bảng route, trỏ sang test.
- C9 (màn video) mở sau PR này, file `static/js/video.js`.

---

## K8 — Tài liệu và luật PR · 2 PR

### PR K8.a `docs(gateway): K8.1–K8.2 — rủi ro tài khoản, ADR-0004, make llm một tài khoản`

- `platform/gateway/README.md`: §"Rủi ro tài khoản" ngay sau lệnh `make login` (3 đoạn: điều khoản, hậu quả, trách
  nhiệm); `platform/gateway/docs/adr/0004-ranh-gioi-dieu-khoan.md`.
- `companies/software-company/Makefile`, `Studio-creators/Makefile` target `llm`: nếu `PROFILE` không đặt → chép
  `llm.example.yaml`; `PROFILE=claude-gateway` mới chép hồ sơ gateway; README gốc dòng 55-57 sửa.
- K8.6 gateway `stop` (`manage.py:60-71`): Windows `tasklist /FI "PID eq <pid>" /FO CSV`, macOS `ps -o command= -p`;
  test mock ba nền tảng.

### PR K8.b `ci: K8.3–K8.4 — luật ADR-0037 và cảnh báo session log`

- `pr-policy.yml` sau bước checkout:

```yaml
- name: fix chạm orchestrator phải dẫn ADR-0037
  env: {TITLE: "${{ github.event.pull_request.title }}", BODY: "${{ github.event.pull_request.body }}", BASE: "${{ github.event.pull_request.base.ref }}"}
  run: |
    printf '%s' "$TITLE" | grep -Eq '^fix\(' || exit 0
    git diff --name-only "origin/$BASE...HEAD" | grep -Eq '^companies/software-company/src/company/(orchestrator\.py|orch/)' || exit 0
    printf '%s' "$BODY" | grep -q 'ADR-0037' || { echo "PR fix sửa máy trạng thái: thân PR phải dẫn ADR-0037 (và nói fix này thuộc bảng chuyển nào)." >&2; exit 1; }
- name: Ngày merge nên có docs/sessions/<ngày>.md (cảnh báo)
  run: |
    d=$(date -u +%F); [ -f "docs/sessions/$d.md" ] || echo "::warning::Chưa có docs/sessions/$d.md (AGENTS.md luật bắt buộc 9)"
```

- Bước ADR chỉ **bật sau khi ADR-0037 merge** (PR này merge sau ADR).
- `docs/HUONG-DAN-VAN-HANH.md` mục "Ngày đầu của người thứ hai" (K8.5): 30 phút, 12 lệnh, kết thúc bằng duyệt
  một gate trên `make demo` với `--approver`.

---

## K9 — Chạy thật · 0 PR code, 4 báo cáo

| Mã | Chuẩn bị | Trong lúc chạy ghi lại | Báo cáo |
|---|---|---|---|
| K9.1 (B8) | máy có docker, `sandbox: auto`, dự án mẫu 2 (gợi ý: "sổ tay thu chi" UI React + API FastAPI + SQLite) | số takeover, token theo tier, thời gian mỗi gate, `sandbox` trong mọi evidence | `docs/reports/<ngày>-du-an-mau-2.md` |
| K9.2 (S7) | `media.yaml` provider thật (TTS `gemini` hoặc `command` Piper, ảnh `gemini`), kênh YouTube thử | chi phí media, số vòng sửa cảnh, thời gian render, finding QC | `docs/reports/<ngày>-video-that-dau-tien.md` |
| K9.3 (T3) | người chưa mở repo, máy sạch, chỉ `docs/HUONG-DAN-VAN-HANH.md` | mỗi chỗ vấp: phút thứ mấy, đọc gì, hiểu gì, sai ở đâu | `docs/reports/<ngày>-nguoi-thu-hai.md`; mỗi chỗ vấp → TRAPS hoặc sửa tài liệu trong tuần |
| K9.4 (T4) | Secrets/Variables đặt xong | thời gian workflow, số ca điểm rớt | dòng CHANGELOG + PR tự mở merge |

---

## Phụ lục A — Lệnh nghiệm thu gom theo epic

```bash
# K1
wc -l companies/software-company/src/company/orchestrator.py                       # ≤ 300
cd software-company && uv run pytest -q -n auto --cov tests/test_orch_bang_chuyen.py tests/test_orch_khuon_loi.py
# K2
grep -rn "subprocess\." companies/software-company/src/company/{tools,workspace,smoke}.py   # chỉ hàm git
COMPANY_SANDBOX=container uv run python -m company.orchestrator status              # lỗi rõ nếu thiếu docker
# K3
grep -c "from xagents_core" Studio-creators/src/studio/*.py                          # > 0
wc -l companies/software-company/src/company/{bus,sqlite_bus,llm,routing,runner,guard,context,evals}.py  # mỗi ≤ 3 (+docstring)
make test                                                                             # 5 package
# K4
cd software-company && uv run python -m company.orchestrator status | grep bus_schema_version
# K5
gh workflow run eval-record -f package=software-company -f agents=clarifier
# K7
wc -l platform/console/src/console/static/js/*.js                                             # mỗi ≤ 400
```

## Phụ lục B — Phân phiên song song

| Phiên | Làm | Không chạm |
|---|---|---|
| 1 | K0 → ADR-0037 → K1.1…K1.7 → K6.2 | `tools.py`, `smoke.py`, console |
| 2 | ADR-0035 → K2.1 → K2.2 → K2.3 → (chờ K1 xong) ADR core → K3.0 → K3.1… | `orchestrator.py` (K2.2 phần truyền `sandbox` xuống làm **sau** K1.4 merge, hoặc phiên 1 làm hộ) |
| 3 | K8.a → K7.1 → K7.2 → K7.3 → K7.4 → K8.b (sau ADR-0037) | company/studio src |

K3.3 trở đi chỉ một phiên; K4, K5 có thể là phiên 3 sau khi K7 xong.
