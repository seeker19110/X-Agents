"""Orchestrator: vòng lặp tự động topic → agent → topic (ADR-0007).

Mỗi event trên bus được đối chiếu với bảng ROUTES (rút từ bảng topic trong docs/architecture.md và front matter
`reads`/`writes` của agent): khớp thì gọi `AgentRunner` rồi publish đầu ra; đầu ra lại là event mới → vòng lặp tiếp.
Phần xác định (DeliveryLead, Supervisor, PersistentGate) subscribe bus như trước; orchestrator chỉ điền chỗ trống
"ai chạy tiếp theo" và tôn trọng ba thứ không bao giờ tự đi tiếp:

- Human gate: `approved-specs` chờ gate `spec`; production chờ gate `release`; ticket blocked/escalate chờ gate
  `escalation`. Kế hoạch của delivery-lead KHÔNG chờ ai (ADR-0037): `_check_plan` kiểm bằng code rồi giao ngay.
- Supervisor: ticket bị pause/budget_cut/escalate thì mọi event của ticket đó bị hoãn đến khi `resume`.
- Khách: `clarification-answers`, `acceptance-results`, quyết định `change-requests` do người publish (CLI).

Nhánh tích hợp (ADR-0011): có `repo` thì ticket rẽ từ `company/integration`; khi release-candidate xuất hiện (mọi review
pass) orchestrator merge --no-ff từng branch ticket vào đó rồi mới cho release-engineer chạy. Xung đột → RC bị huỷ
(`release.void`), ticket về `changes_requested` với hint là danh sách file xung đột, worktree tạo lại từ nền mới.

Khối kỹ thuật (ADR-0010): có `repo` thì mỗi ticket chạy trong worktree `ticket/<id>` với tool đọc/ghi/lint/test; PR mang
bằng chứng do code điền (`local_checks.verified_by=workspace`, diff thật cho reviewer/QA/security; QA còn có tool chỉ đọc
để tự chạy test). Không có `repo` thì PR vẫn đi tiếp nhưng `local_checks` bị thay bằng `{"unverified": true}` — không
bao giờ để lời tự khai của model đóng vai bằng chứng.

Agent ghi blackboard qua `context_writes` trong đầu ra (runner kiểm namespace). Mọi event đã xử lý được đánh dấu
bằng `audit-log` (actor=orchestrator, action=orchestrated) nên mở lại bus SQLite là tiếp tục đúng chỗ; trạng thái
delivery-lead/supervisor/gate dựng lại từ replay. Không retry lời gọi model vì lỗi nội dung: lỗi ghi audit rồi đi tiếp.

Hai trạng thái dừng KHÁC NHAU về độ bền, rất dễ nhầm khi vận hành:
- HOÃN (`deferred`, xem `_defer`): KHÔNG gọi `_mark`, nên event không mang dấu `orchestrated`. Mở lại tiến trình
  là hàng đợi nhận lại nó — an toàn khi restart. Backend hẹn "thử lại sau Ns" thì `defer_until` giữ đúng hẹn.
- KẸT (`stalled`, xem `_stall`): event ĐÃ bị `_mark`. Lệnh chạy lại (`_retry_stalled`) bỏ dấu đó trong RAM, nên
  `_rehydrate` phải đối chiếu `project.retried` với `orchestrated` gần nhất mới nhận lại được sau restart.

ADR-0012:
- Lỗi transport (`TransientError`, sau khi `RetryingClient` đã thử lại) không phải lỗi agent: event được HOÃN
  (`transient:<agent>`) và nhịp `tick` sau thử lại; agent đã chạy xong trên cùng event không chạy lại (`partial`).
- `--workers N`: event của các key khác nhau chạy song song trong thread pool; bus giữ RLock nên phần xác định
  (delivery-lead, supervisor, gate) vẫn tuần tự. Event đặc biệt (gate decide, plan, RC, clarifier) luôn chạy một mình.
- researcher có tool đọc repo khách (chỉ đọc, không chạy lệnh) và web (`--web`); blackboard có artifact store
  (`--artifacts`, mặc định `<db>.artifacts/`) mirror toàn văn PRD/C4/OpenAPI/threat model ra file.
- Người can thiệp giữa vòng: `comment` (hint cho ticket đang chạy, không tính retry) và `takeover` (người sửa tay trong
  worktree, code chạy lint/test và publish PR dưới tên người) — không cần đợi gate escalation.

ADR-0027 (`--deliver`): production được duyệt và deploy → tag `v<version>` + fast-forward `company/release` trong repo
khách (`Integration.deliver`); production rolled_back/failed → lùi con trỏ nhánh release về lần giao trước (tag giữ).
`--push-remote` đẩy lên remote của khách; lỗi push chỉ vào audit. `main` của khách vẫn không bị chạm.
"""
from __future__ import annotations

import json
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .blackboard import Blackboard
from .bus import InMemoryBus
from .delivery import DeliveryLead
from .delivery_contract import ApprovalLookup
from .deploy import deploy
from .events import Envelope
from .gate_cli import PersistentGate
from .gates import gate_approvers
from .llm import LLMError, ModelClient, TransientError
from .orch import (
    error_flow,
    fsm,
    gates_flow,
    guards,
    rehydrate,
    release_fsm,
    retry_flow,
    scheduler,
    ticket_fsm,
    verify,
    worktree_flow,
)
from .orch.cli import main, source_fingerprint
from .orch.enrich import _with_chan_doan as _with_chan_doan
from .orch.enrich import _with_diff as _with_diff
from .orch.guards import _can_author_tests as _can_author_tests
from .orch.guards import _cycle as _cycle
from .orch.guards import _has_dispute as _has_dispute
from .orch.guards import _test_scope_ok as _test_scope_ok
from .orch.guards import pending_clarifications
from .orch.quality_flow import QualityPin, TrustedDriver
from .orch.quality_release import release_quality
from .orch.review_source import enforce_source as enforce_source

# Không dùng trong file này nhưng là hợp đồng công khai của module (gate_brief.py, test) — giữ re-export tường
# minh bằng alias cùng tên để ruff không coi là import thừa.
from .orch.routes import BLIND_STRIP as BLIND_STRIP
from .orch.routes import (
    CR_IMPACT_ACTION,
    KEY_FIELD,
    ROUTES,
    TICKET_TOPICS,
    Route,
    check_routes,
    key_for,
    phase_for,
)
from .orch.routes import MAX_CONFLICT_RETRIES as MAX_CONFLICT_RETRIES
from .orch.routes import PLAN_INPUTS as PLAN_INPUTS
from .orch.routes import SPEC_RUNTIME_REWORKS as SPEC_RUNTIME_REWORKS
from .orch.routes import THREAT_ROUTE as THREAT_ROUTE
from .orch.routes import spec_runtime_gap as spec_runtime_gap
from .orch.state import OrchState, install_aliases
from .registry import AgentSpec, load_agents
from .roles import ENGINEERING as ENGINEERING
from .runner import CONTEXT_ONLY, AgentRunner, RunnerError
from .sandbox import Sandbox, SubprocessSandbox
from .supervisor import Supervisor
from .web import WebTools, research_toolbox
from .workspace import Integration


@dataclass
class StepResult:
    event_id: str
    topic: str
    key: str
    actions: list[str] = field(default_factory=list)
    deferred: str | None = None  # lý do hoãn (gate:..., paused:..., transient:...)
    transient: bool = False      # một agent gặp lỗi transport sau khi đã retry → event sẽ được thử lại ở nhịp sau


class ReloadRequested(Exception):
    """Vòng watch xin khởi động lại tiến trình vì mã nguồn đã đổi (xem `Orchestrator.watch`)."""


class Orchestrator:
    if TYPE_CHECKING:
        # Bí danh do `install_aliases` gắn lúc chạy (ADR-0034). mypy không thấy property gắn động nên
        # khai báo lại kiểu ở đây; nguồn sự thật vẫn là `OrchState`, và `test_orch_state_rehydrate`
        # bắt lỗi nếu hai danh sách lệch nhau.
        processed: set[str]
        queue: list[Envelope]
        partial: dict[str, set[str]]
        deferred: dict[str, tuple[Envelope, str]]
        defer_until: dict[str, float]
        once: set[str]
        plans: dict[str, dict[str, Any]]
        integrated: set[str]
        conflict_retries: Counter[str]
        turn_continuations: Counter[str]
        missing_threat_model: set[str]
        spec_runtime_reworks: Counter[str]
        plan_reworks: Counter[str]
        release_sha: dict[str, str]
        delivered: dict[str, dict[str, Any]]
        void_releases: set[str]
        quality_profiles: dict[str, QualityPin]
        # run_id → attempt: đã hỏng ở driver/commit (chờ người/candidate mới); đã kết thúc ở candidate hiện tại.
        _quality_stuck: dict[str, str]
        _quality_done: dict[str, str]
        stalled: dict[str, dict[str, Any]]
        stall_count: Counter[str]
        unhandled: dict[str, dict[str, Any]]
        escalation_decided: Counter[str]
        debt_gate: dict[str, dict[str, Any]]
        paused: set[str]
        project_repos: dict[str, Integration]
        bad_repos: set[str]
        stats: Counter[str]
        transient_since: dict[str, float]
        reload_on_change: bool

    def __init__(self, bus: InMemoryBus, client: ModelClient, agents: dict[str, AgentSpec] | None = None,
                 max_retries: int = 3, repo: Path | None = None, base: str = "HEAD", max_turns: int = 25,
                 batch_releases: bool = False,
                 integration: str = "company/integration", workers: int = 1, web: WebTools | bool = False,
                 artifacts: Path | None = None, project_budget_usd: float | None = None,
                 deliver: bool = False, push_remote: str | None = None, release_branch: str = "company/release",
                 test_author: bool = False, sandbox: Sandbox | None = None, deliver_pr: bool = False,
                 deploy_fn: Any = None, quality_driver: TrustedDriver | None = None,
                 quality_trust: Path | None = None, quality_lookup: ApprovalLookup | None = None):
        self.bus = bus
        self.quality_driver, self.quality_lookup = quality_driver, quality_lookup  # ADR gốc 0021; mặc định None → CLI commit
        self.quality_trust, self._quality_lock = (Path(quality_trust) if quality_trust else None), threading.RLock()
        self._quality_stuck, self._quality_done = {}, {}  # RAM, run_id → attempt (orch/quality_flow.py)
        # ADR-0039 (D1b): dựng môi trường chạy thật của khách bằng `docker compose`. Tiêm được vì máy CI không có
        # docker daemon và ma trận còn `windows-latest` — test truyền `partial(deploy, run=…, which=…)` để đo cả
        # bốn nhánh kết luận mà không cần container thật. Mặc định là `deploy()` thật; nó tự đọc `COMPANY_DEPLOY`
        # và trả `skipped` khi máy không có runtime, nên repo đang chạy không đổi hành vi.
        self.deploy_fn: Any = deploy_fn if deploy_fn is not None else deploy
        # ADR-0035 (K2.4): sandbox chạy MỌI lệnh có đối số hoặc nội dung do model/repo khách sinh — lint/test của
        # `run_checks`, tool `run` của model, lệnh khởi động trong `run_smoke`. Mặc định `SubprocessSandbox`
        # (= hành vi trước ADR) chứ KHÔNG phải `sandbox_from_config`: `Orchestrator` được dựng thẳng trong hàng
        # trăm test, và `auto` sẽ chọn container ngay khi máy có docker — CI ubuntu có. Tiến trình thật đọc cấu
        # hình ở `orch/cli.py` cho đúng hai lệnh chạy model (`run`, `redeploy`) rồi truyền xuống đây.
        self.sandbox: Sandbox = sandbox if sandbox is not None else SubprocessSandbox()
        # ADR-0028: bật vai viết test độc lập. Mặc định TẮT — nó thêm một lượt model mỗi ticket, nên phải là
        # lựa chọn có ý thức của người vận hành, không phải thứ tự bật lên sau một lần `git pull`.
        self.test_author = bool(test_author)
        self.repo, self.max_turns = (Path(repo) if repo else None), max_turns
        self.workers = max(1, int(workers))
        self.web = web if isinstance(web, WebTools) else (WebTools() if web else None)
        self._lock = threading.RLock()   # trạng thái orchestrator (processed, deferred, once, stats) — KHÔNG publish khi đang giữ
        self._qlock = threading.RLock()  # hàng đợi; _on_event (chạy dưới lock của bus) chỉ chạm lock này
        self._ws_lock = threading.RLock()
        self._merge_lock = threading.RLock()  # merge vào nhánh tích hợp chạy một mình (ADR-0012 §7), kể cả khi --workers>1
        self.state = OrchState()
        if self.repo is not None and not (self.repo / ".git").exists():
            raise ValueError(f"repo không phải git repository: {self.repo}")
        # `--repo` là repo MẶC ĐỊNH của tiến trình. Từng dự án có thể chỉ repo riêng ngay trong `research-requests`
        # (payload.repo, payload.base — ADR-0025): học từ log lúc mở lại và từ event lúc chạy, ticket của dự án nào
        # làm trong worktree của repo đó. Repo sai (không có .git) → audit một lần, dự án rơi về mặc định.
        self.deliver, self.push_remote, self.release_branch = bool(deliver), push_remote, release_branch
        # ADR-0038: sau khi giao (tag + nhánh đã push), mở PR thật `release_branch → base` trên GitHub của khách để
        # khách review trước khi ký UAT. Mặc định TẮT: nó tạo một thứ nhìn thấy được ngoài worktree.
        self.deliver_pr = bool(deliver_pr)
        self.integration = Integration(self.repo, integration, base, release_branch) if self.repo is not None else None
        self.base, self.integration_branch = base, integration
        self.source_fp = source_fingerprint()  # mã nguồn lúc khởi động — `watch(reload=True)` so với đây
        self.agents = agents or load_agents()
        bad = check_routes(self.agents)
        if bad: raise ValueError("ROUTES lệch front matter: " + "; ".join(bad))
        self.blackboard = Blackboard(bus, store=artifacts)
        self.gate = PersistentGate(bus, approvers=gate_approvers())
        self.lead = DeliveryLead(bus, self.gate, max_retries=max_retries, batch_releases=batch_releases)
        self.lead.require_integration = self.integration is not None
        self.lead.quality_source = partial(release_quality, self)  # R6 (ADR gốc 0021 §f): chỉ đọc journal
        budget_usd = project_budget_usd if project_budget_usd is not None else getattr(client, "budget_usd", None)
        # ADR-0032: ngưỡng "nợ kiến trúc treo" cấu hình cùng chỗ với trần ngân sách (llm.yaml `debt_reviews`).
        self.supervisor = Supervisor(bus, max_retries=max_retries, project_budget_usd=budget_usd,
                                     debt_threshold=int(getattr(client, "debt_reviews", None) or 3))
        self.runner = AgentRunner(bus, client, self.agents, self.blackboard, lesson_provider=self._lessons_for_input)
        self._rehydrate()
        bus.subscribe("*", self._on_event)

    def _lessons_for_input(self, inp: Envelope) -> list[dict[str, Any]]:
        tid = str(inp.payload.get("ticket_id") or inp.key)
        ticket = self.lead.tickets.get(tid)
        return self.supervisor.lessons_for(ticket) if ticket is not None else []

    # ---------- khôi phục từ log ----------

    _rehydrate = rehydrate.rehydrate
    _nap_lai_hen = rehydrate._nap_lai_hen
    _retry_con_can = rehydrate._retry_con_can


    # ---------- worktree, repo theo dự án, gộp nhánh tích hợp (ADR-0034: orch/worktree_flow.py) ----------

    _learn_repo = worktree_flow.learn_repo
    integration_for = worktree_flow.integration_for
    _project_of_ticket = worktree_flow.project_of_ticket
    _integration_of_ticket = worktree_flow.integration_of_ticket
    _has_integration = worktree_flow.has_integration
    workspace = worktree_flow.workspace
    _integrate_approved = worktree_flow.integrate_approved
    _branch_ahead = worktree_flow.branch_ahead
    _merge_ticket = worktree_flow.merge_ticket
    _merge_ticket_locked = worktree_flow.merge_ticket_locked
    _read_only_tools = worktree_flow.read_only_tools
    _author_tests = worktree_flow.author_tests
    _engineer = worktree_flow.engineer
    comment = worktree_flow.comment
    takeover = worktree_flow.takeover


    def _integration_of_release(self, env: Envelope) -> Integration | None:
        """RC / release-event → dự án qua ticket đầu tiên của nó (mọi ticket một RC cùng dự án)."""
        tickets = env.payload.get("tickets") or []
        return self._integration_of_ticket(str(tickets[0])) if tickets else self.integration_for(self.project_for(env))


    def latest(self, topic: str, key: str) -> Envelope | None:
        return self.bus.latest(topic, key)

    # ---------- vòng lặp chính, hoãn/đánh dấu/audit (ADR-0034: orch/scheduler.py) ----------

    _actionable = scheduler._actionable
    _track_pause = scheduler._track_pause
    _on_event = scheduler._on_event
    _target = staticmethod(scheduler.target)
    _parallel_ok = scheduler._parallel_ok
    _take_batch = scheduler._take_batch
    run = scheduler.run
    _integrate_pending = scheduler._integrate_pending
    tick = scheduler.tick
    watch = scheduler.watch
    _maybe_reload = scheduler._maybe_reload
    _defer = scheduler._defer
    _defer_transient = scheduler._defer_transient
    _retry_deferred = scheduler._retry_deferred
    _mark = scheduler._mark
    _remember = scheduler._remember
    _audit = scheduler._audit
    _resume_overdue = scheduler._resume_overdue


    def process(self, env: Envelope) -> StepResult | None:
        """Dispatcher thuần (ADR-0034, K1.7): tra `ticket_fsm.TICKET_TRANSITIONS`/`release_fsm.RELEASE_TRANSITIONS`
        (bảng dữ liệu, xem `orch/fsm.py`) → `ROUTES` (agent nào chạy) → `_call`. Thứ tự bảng == thứ tự các
        nhánh cũ; `phase="pre"/"post"` giữ đúng vị trí trước/sau vòng `ROUTES` (vd. `_integrate_approved` phải
        chạy trước khi `ROUTES` giao việc cho ticket phụ thuộc)."""
        if env.event_id in self.processed: return None
        res = StepResult(env.event_id, env.topic, env.key)
        if env.topic == "audit-log":
            return self._on_gate_decide(env, res)
        target = env.payload.get("ticket_id") or env.key
        if target in self.paused:
            return self._defer(env, res, f"paused:{target}")
        pid = env.payload.get("project_id")
        if pid and pid in self.paused:  # supervisor pause cả dự án (vượt ngân sách tiền)
            return self._defer(env, res, f"paused:{pid}")
        if fsm.step(ticket_fsm.TICKET_TRANSITIONS, self, env, res): return res
        if fsm.step(release_fsm.RELEASE_TRANSITIONS, self, env, res, phase="pre"): return res
        for r in ROUTES:
            if r.topic_in != env.topic or (r.when and not r.when(env, self)): continue
            self._call(r.agent, env, r, res)
        fsm.step(release_fsm.RELEASE_TRANSITIONS, self, env, res, phase="post")
        self._note_closed()
        if res.transient:  # một agent chưa chạy được vì transport: giữ event lại, nhịp sau thử tiếp (agent xong rồi không chạy lại)
            # Backend đã nói rõ phải chờ bao lâu ("mọi backend đều đang nghỉ, thử lại sau 1515s") — tôn trọng nó.
            # Trước đây mọi nhịp tick đều hỏi lại: đo được 60 bản ghi `llm_error`/phút liên tục trong lúc pool
            # hết quota (2026-09-04), và `_rehydrate` replay TOÀN BỘ log nên bus phình làm mọi lần mở lại chậm dần.
            return self._defer_transient(env, res)
        self._mark(env, res)
        return res

    # ---------- máy trạng thái TICKET (ADR-0034: orch/ticket_fsm.py) ----------

    _superseded = ticket_fsm._superseded
    _note_closed = ticket_fsm._note_closed
    _plan = ticket_fsm._plan
    _spec_runtime_missing = ticket_fsm._spec_runtime_missing
    _threat_model = ticket_fsm._threat_model
    _assume_clarifications = ticket_fsm._assume_clarifications
    _check_plan = guards._check_plan  # tách sang orch/guards.py (2026-09-22): ticket_fsm.py chạm trần 400 dòng
    _dispatch_plan = ticket_fsm._dispatch_plan

    # ---------- máy trạng thái RELEASE (ADR-0034: orch/release_fsm.py) ----------

    _integrate = release_fsm._integrate
    _void = release_fsm._void
    _release = release_fsm._release
    _deliver = release_fsm._deliver
    _rollback_delivery = release_fsm._rollback_delivery
    redeploy = release_fsm.redeploy
    recheck = release_fsm.recheck
    _check_paused_releases = release_fsm._check_paused_releases
    _superseded_release = release_fsm._superseded_release
    _release_paused = release_fsm._release_paused
    _recall = release_fsm._recall
    _rerun_release = release_fsm._rerun_release

    def project_for(self, env: Envelope) -> str | None:
        """Dự án của một event, kể cả khi payload không nói: release và ticket đều truy ngược được về dự án.
        Cần cho blackboard phân vùng (ADR-0018) — không có nó thì release notes của khách A ghi vào phạm vi chung."""
        if pid := env.payload.get("project_id"): return str(pid)
        tid = env.payload.get("ticket_id") or (env.key if env.topic in {"tasks", "pull-requests"} else None)
        rid = env.payload.get("release_id") or (env.key if env.topic in {"release-events", "release-candidates",
                                                                        "acceptance-results"} else None)
        if rid and not tid:
            tid = next(iter(self.lead.release_tickets.get(str(rid), [])), None)
        t = self.lead.tickets.get(str(tid)) if tid else None
        return t.project_id if t else None

    def _call(self, agent: str, env: Envelope, r: Route, res: StepResult) -> None:
        # ADR-0037 PR-5b: khoá theo AGENT không đủ khi một agent gộp (`ops`) có HAI route khác nhau khớp CÙNG MỘT
        # event — route thứ hai bị route thứ nhất "nuốt" dù `topic_out` khác hẳn. Khoá thêm theo `topic_out` để
        # hai route của cùng agent trên cùng event chạy độc lập, giữ nguyên ý nghĩa cũ khi agent không gộp.
        slot = f"{agent}:{r.topic_out}"
        with self._lock:
            if slot in self.partial.get(env.event_id, set()):
                return  # đã chạy xong ở lần xử lý trước (event bị hoãn transient)
        try:
            extra = dict(r.enrich(env, self)) if r.enrich else {}
            if (pid := self.project_for(env)) and not env.payload.get("project_id"): extra["project_id"] = pid
            inp = env.model_copy(update={"payload": {**env.payload, **extra}}) if extra else env
            phase = phase_for(r, self.runner.agents[agent], inp)  # ADR-0037
            if r.target_env:
                out = self._release(agent, inp, r); res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            elif r.tools == "tests":
                ts = self._author_tests(agent, inp, r, phase)
                res.actions.append(f"{agent}→{r.topic_out}:{ts.key}" if ts is not None else f"{agent}→bỏ:{inp.key}")
            elif r.tools == "rw":
                pr = self._engineer(agent, inp, r, phase)
                res.actions.append(f"{agent}→{r.topic_out}:{pr.key}" if pr is not None else f"{agent}→rework:{inp.key}")
            elif r.topic_out == CONTEXT_ONLY:
                g = self.runner.run_context(agent, inp, phase=phase)
                res.actions.append(f"{agent}→blackboard:{','.join(w['namespace'] for w in g.context_writes) or '-'}")
            elif r.many:
                g = self.runner.generate(agent, inp, r.topic_out, many=True, phase=phase)
                if g.context_writes: self.runner.write_context(agent, inp, g.context_writes)  # inp mang project_id (ADR-0018)
                if env.topic == "acceptance-results":  # CR từ nghiệm thu conditional phải truy được release (đóng ticket khi quyết)
                    g.payloads = [{**p, "release_id": env.key} for p in g.payloads]
                for i, p in enumerate(g.payloads):  # token/tiền tính một lần cho cả lượt, không nhân theo số payload
                    self.runner.publish(agent, inp, r.topic_out, p, key=key_for(r.topic_out, p, env.key),
                                        tokens=g.tokens if i == 0 else 0, model=g.model, generated=g if i == 0 else None)
                if not g.payloads:
                    self._audit("produced:nothing", {"agent": agent, "topic": r.topic_out, **json.loads(g.evidence())},
                                actor=agent, tokens=g.tokens, cost=g.cost_usd)
                res.actions.append(f"{agent}→{r.topic_out}×{len(g.payloads)}")
            else:
                tools = None
                inp, bang_chung = self._evidence_before(r, inp)  # ADR-0029/0046: bằng chứng MÁY chạy trước lượt chấm
                if r.tools == "ro":
                    tools = self._read_only_tools(inp)
                elif r.tools == "research":
                    integ = self.integration_for(self.project_for(env))  # researcher đọc đúng codebase của dự án
                    tools = research_toolbox(integ.repo if integ is not None else None, self.web)
                g = self.runner.generate(agent, inp, r.topic_out, tools=tools, max_turns=self.max_turns, phase=phase)
                if r.tools == "ro" and tools is not None and not g.tool_calls:
                    # Có tool mà không chạy gì: verdict chỉ là lời khai. Không chặn (người đọc review vẫn quyết), nhưng phải hiện.
                    self._audit("review.no_tool_evidence", {"agent": agent, "topic": env.topic, "key": env.key},
                                actor=agent, ticket_id=inp.payload.get("ticket_id"), project_id=self.project_for(env))
                p = g.payloads[0]
                p = enforce_source(self, r, p, env, agent)  # nhãn `source` từ ROUTE, không từ lời khai model
                if r.topic_out == "audit-log" and (p.get("action") != CR_IMPACT_ACTION or p.get("actor") != agent):
                    # Đầu ra `audit-log` của model chỉ được là ước lượng impact của change request: `action` và
                    # `actor` là identity của lượt, không phải lời khai — `audit-log` là topic mở và `_rehydrate`
                    # dựng trạng thái theo tên action (sc-security 2026-09-23).
                    self._audit("output.action_overridden", {"claimed_action": p.get("action"), "claimed_actor": p.get("actor"),
                                                             "action": CR_IMPACT_ACTION}, actor=agent, project_id=self.project_for(env))
                    p = {**p, "action": CR_IMPACT_ACTION, "actor": agent}
                if env.topic in TICKET_TOPICS and (tid := env.payload.get("ticket_id")) \
                        and KEY_FIELD.get(r.topic_out) == "ticket_id" and p.get("ticket_id") != tid:
                    # Đầu vào thuộc về MỘT ticket (task/PR/bộ test) thì đầu ra cũng của ticket đó: `ticket_id` là
                    # identity của lượt mà ROUTE biết chắc, không phải lời khai. Không ghi đè thì QA duyệt PR của T1
                    # ghi được review cho `REL-x` hay ticket khác (sc-security 2026-09-23, lỗ để ngỏ ở ADR-0043).
                    self._audit("output.subject_overridden", {"topic": r.topic_out, "ticket_id": tid,
                                                              "claimed_ticket_id": p.get("ticket_id")},
                                actor=agent, ticket_id=tid, project_id=self.project_for(env))
                    p = {**p, "ticket_id": tid}
                if r.topic_out == "review-results" and env.topic in {"release-candidates", "release-events"}                         and (rid := env.payload.get("release_id")) and p.get("ticket_id") != rid:
                    # Review trên RELEASE (release-check của security, QA hồi quy trên staging): subject là release_id
                    # của ROUTE, không phải lời khai của model — cùng nguyên tắc với `env`/`release_id` trong
                    # `_release`. Model hay điền ticket đầu tiên của RC vào `ticket_id`: review rơi vào ticket ĐÃ
                    # approved (vô nghĩa), `release_reviews[rid]` thiếu nguồn → Gate 3 không mở, escalation cũng
                    # không → RC chết im. Đo được 2026-09-06 (QLKH REL-024): security block ghi ticket_id=
                    # TCK-CR-OPS-001-04, không gate nào mở, `status` xanh.
                    self._audit("review.subject_overridden", {"release_id": rid, "claimed_ticket_id": p.get("ticket_id"),
                                                              "source": p.get("source")}, actor=agent, project_id=self.project_for(env))
                    p = {**p, "ticket_id": rid}
                p = self._evidence_after(agent, inp, p, bang_chung)
                out = self.runner.publish(agent, inp, r.topic_out, p, key=key_for(r.topic_out, p, env.key),
                                          tokens=g.tokens, model=g.model, context_writes=g.context_writes, generated=g)
                res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            with self._lock:
                self.stats["runs"] += 1; self.partial.setdefault(env.event_id, set()).add(slot)
        except TransientError as e:  # hết retry transport: không phải lỗi agent — hoãn event, nhịp sau thử lại
            res.actions.append(f"transient:{agent}:{str(e)[:120]}"); res.transient = True
            with self._lock: self.stats["transient"] += 1
        except (RunnerError, LLMError) as e:  # runner đã ghi audit; không retry lời gọi (ADR-0005)
            if self._autoretry_once(env, agent, e, res): return  # trừ lỗi ép schema của CLI: thử lại một lần
            res.actions.append(f"error:{agent}:{str(e)[:120]}")
            with self._lock: self.stats["errors"] += 1; self.partial.setdefault(env.event_id, set()).add(slot)
            self._after_error(env, agent, e, r, res)
        except Exception as e:  # handler xác định (delivery-lead) từ chối chuyển trạng thái: event đã ghi đĩa
            self._audit("handler_error", {"agent": agent, "error": str(e)[:300]}, ticket_id=env.payload.get("ticket_id"))
            res.actions.append(f"handler_error:{agent}:{str(e)[:120]}")
            with self._lock: self.stats["errors"] += 1; self.partial.setdefault(env.event_id, set()).add(slot)
            self._after_error(env, agent, e, r, res)

    # ---------- lỗi agent và quyết định gate (ADR-0034: orch/error_flow.py, gates_flow.py) ----------

    _after_error = error_flow._after_error
    _autoretry_once = error_flow._autoretry_once
    _mark_unhandled = error_flow._mark_unhandled
    _rework_after_error = error_flow._rework_after_error
    _stall = error_flow._stall
    _retry_stalled = retry_flow._retry_stalled
    _retry_unhandled = retry_flow._retry_unhandled
    _on_gate_decide = gates_flow._on_gate_decide
    _check_escalations = gates_flow._check_escalations
    _check_debt = gates_flow._check_debt
    _on_escalation_decided = gates_flow._on_escalation_decided
    _open_acceptance_gate = gates_flow._open_acceptance_gate
    _close_acceptance_gate = gates_flow._close_acceptance_gate
    _record_lessons = gates_flow._record_lessons
    _record_lesson = gates_flow._record_lesson


    _release_evidence = verify.release_evidence


    _smoke = verify.smoke
    _deploy_release = verify.deploy_release
    _regression_run = verify.regression_run
    _verdict_with_run = verify.verdict_with_run
    _evidence_before = verify.evidence_before
    _evidence_after = verify.evidence_after


    def _integration_status(self) -> dict[str, Any] | None:
        """Nhánh tích hợp mặc định (`--repo`) + của từng dự án có repo riêng; None khi chưa có worktree tích hợp nào."""
        def one(integ: Integration) -> dict[str, str] | None:
            if not integ.path.exists(): return None
            return {"branch": integ.branch, "sha": integ.sha(), "repo": str(integ.repo)}
        default = one(self.integration) if self.integration is not None else None
        projects = {pid: st for pid, integ in self.project_repos.items() if (st := one(integ)) is not None}
        if default is None and not projects: return None
        out: dict[str, Any] = dict(default or {})
        if projects: out["projects"] = projects
        return out

    _deadlock_warnings = scheduler._deadlock_warnings  # ADR-0034: logic ở orch/scheduler.py

    def rulings(self, project_id: str | None = None, ticket_id: str | None = None) -> list[dict[str, Any]]:
        """Sổ Ruling (ADR-0030): mọi quyết định agent tự đưa ra, đọc từ audit `ruling` — không giữ trong RAM nên không
        có gì để mất khi mở lại bus. Lọc theo dự án hoặc ticket; mỗi mục mang actor, thời điểm, decision/why/cost."""
        out: list[dict[str, Any]] = []
        for e in self.bus.replay(topic="audit-log"):
            a = e.payload
            if a.get("action") != "ruling": continue
            if project_id and a.get("project_id") != project_id: continue
            if ticket_id and a.get("ticket_id") != ticket_id: continue
            d = _evidence(a)
            out.append({"at": e.ts.isoformat(timespec="seconds"), "by": a.get("actor"), "ticket_id": a.get("ticket_id"),
                        "project_id": a.get("project_id"), **d})
        return out

    def status(self) -> dict[str, Any]:
        return {"warnings": self._deadlock_warnings(), "rulings": len(self.rulings()),
                "queue": len(self.queue), "deferred": {k: v[1] for k, v in self.deferred.items()},
                "paused": sorted(self.paused), "tickets": dict(self.lead.state), "waiting": self.lead.waiting(),
                "blocked": self.lead.blocked(), "releases": self.lead.releases,
                "stalled": {pid: f"{st['agent']} lỗi trên {st['topic']}: {st['error'][:120]}" for pid, st in self.stalled.items()},
                "architecture_debt": self.supervisor.debt_table(),  # ADR-0032
                "gates_pending": {sid: g.kind for sid, g in self.gate.pending.items()}, "plans": list(self.plans),
                "gates_reviewer_signed_unapplied": self.gate.reviewer_signed_pending(),
                "clarifications_pending": pending_clarifications(self.bus),
                "blackboard": {key: {"v": sc.version, "ref": sc.content_ref, "chars": len(sc.content or ""),
                                     "file": str(p) if (p := self.blackboard.path(sc.namespace,
                                                                                  project_id=sc.project_id)) else None}
                               for key, sc in self.blackboard.all().items()},
                "workers": self.workers, "web": self.web is not None,
                "cost_usd": self.supervisor.sprint_report()["cost_usd_total"],
                "integration": self._integration_status(), "void_releases": sorted(self.void_releases),
                "delivery": {rid: {k: d.get(k) for k in ("version", "tag", "short", "branch", "problems", "pushed", "pr")}
                             for rid, d in sorted(self.delivered.items())},
                "stats": dict(self.stats), "events": len(self.bus)}


def _evidence(a: dict[str, Any]) -> dict[str, Any]:
    try:
        d = json.loads(a.get("evidence") or "{}")
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


install_aliases(Orchestrator)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
