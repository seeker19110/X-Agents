"""Orchestrator: vòng lặp tự động topic → agent → topic (ADR-0007).

Mỗi event trên bus được đối chiếu với bảng ROUTES (rút từ bảng topic trong docs/architecture.md và front matter
`reads`/`writes` của agent): khớp thì gọi `AgentRunner` rồi publish đầu ra; đầu ra lại là event mới → vòng lặp tiếp.
Phần xác định (DeliveryLead, Supervisor, PersistentGate) subscribe bus như trước; orchestrator chỉ điền chỗ trống
"ai chạy tiếp theo" và tôn trọng ba thứ không bao giờ tự đi tiếp:

- Human gate: `approved-specs` chờ gate `spec`; plan của delivery-lead chờ gate `plan`; production chờ gate `release`;
  ticket blocked/escalate chờ gate `escalation`.
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

ADR-0012:
- Lỗi transport (`TransientError`, sau khi `RetryingClient` đã thử lại) không phải lỗi agent: event được HOÃN
  (`transient:<agent>`) và nhịp `tick` sau thử lại; agent đã chạy xong trên cùng event không chạy lại (`partial`).
- `--workers N`: event của các key khác nhau chạy song song trong thread pool; bus giữ RLock nên phần xác định
  (delivery-lead, supervisor, gate) vẫn tuần tự. Event đặc biệt (gate decide, plan, RC, clarifier) luôn chạy một mình.
- researcher có tool đọc repo khách (chỉ đọc, không chạy lệnh) và web (`--web`); blackboard có artifact store
  (`--artifacts`, mặc định `<db>.artifacts/`) mirror toàn văn PRD/C4/OpenAPI/threat model ra file.
- Người can thiệp giữa vòng: `comment` (hint cho ticket đang chạy, không tính retry) và `takeover` (người sửa tay trong
  worktree, code chạy lint/test và publish PR dưới tên người) — không cần đợi gate escalation.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .blackboard import Blackboard
from .bus import InMemoryBus
from .delivery import DONE_STATES, DeliveryLead
from .events import BUDGET_FACTOR, AuditLog, Envelope, Task
from .gate_cli import PersistentGate
from .gates import Decision, GateRequest
from .llm import LLMError, ModelClient, TransientError
from .registry import AgentSpec, load_agents
from .runner import CONTEXT_ONLY, AgentRunner, RunnerError, artifact_store
from .supervisor import Supervisor
from .tools import ToolBox, WorkspaceTools
from .web import WebTools, research_toolbox
from .workspace import Integration, TicketWorkspace, WorkspaceError, _git

ACTOR = "orchestrator"
MAX_CLARIFY_ROUNDS = 2  # khớp `clarification-questions.round` (maximum 2) và prompt clarifier
ENGINEERING = ("backend", "frontend", "mobile", "database", "platform", "data")
PAUSING = frozenset({"pause", "budget_cut", "escalate"})
# Chuỗi nghiên cứu chạy theo key=project, không có ticket/retry/blocked: một agent lỗi là cả dự án đứng mà không ai
# thấy. Lỗi ở các topic này mở gate `escalation` cấp dự án (approve = chạy lại event, reject = đóng dự án).
RESEARCH_TOPICS = frozenset({"research-requests", "research-findings", "requirements-draft", "clarification-answers"})
CONTROL_TOPICS = frozenset({"audit-log", "shared-context", "supervisor-actions"})
REVIEW_AGENT = {"reviewer": "reviewer", "qa": "qa-debugger", "security": "security-engineer"}
KEY_FIELD = {"tasks": "ticket_id", "pull-requests": "ticket_id", "review-results": "ticket_id", "incidents": "incident_id",
             "change-requests": "change_id", "release-candidates": "release_id", "release-events": "release_id",
             "acceptance-results": "release_id"}  # topic khác (project_id) giữ key của event nguồn


def key_for(topic: str, payload: dict[str, Any], default: str) -> str:
    return str(payload.get(KEY_FIELD.get(topic, ""), "") or default)
ACTIVE_STATES = frozenset({"dispatched", "in_progress", "in_review"})

When = Callable[[Envelope, "Orchestrator"], bool]
Enrich = Callable[[Envelope, "Orchestrator"], dict[str, Any]]


@dataclass(frozen=True)
class Route:
    topic_in: str
    agent: str  # id agent, hoặc "$assignee" = lấy từ payload.assignee (khối kỹ thuật)
    topic_out: str  # topic, hoặc CONTEXT_ONLY = chỉ ghi blackboard
    when: When | None = None
    target_env: str | None = None  # route release: đầu ra phải có env đúng như yêu cầu
    many: bool = False  # 0..n payload một lượt (agent được quyền "không có gì để phát")
    enrich: Enrich | None = None  # thêm dữ liệu vào payload đầu vào (vd. bản draft mới nhất cho spec-writer)
    tools: str | None = None  # "rw": sửa code trong worktree (kỹ thuật); "ro": chỉ đọc + chạy test (QA); "research": đọc repo khách + web

    def agents(self) -> tuple[str, ...]:
        return ENGINEERING if self.agent == "$assignee" else (self.agent,)


def _from(*actors: str) -> When:
    return lambda e, _o: e.actor in actors


def _field(name: str, *values: Any) -> When:
    return lambda e, _o: e.payload.get(name) in values


def _needs_security(e: Envelope, o: Orchestrator) -> bool:
    tid = e.payload.get("ticket_id") or e.key
    return tid in o.lead.tickets and "security" in o.lead.required_reviews(tid)


def _needs_qa(e: Envelope, o: Orchestrator) -> bool:
    """ADR-0021: QA ở lượt PR chỉ cho ticket có risk_tags; ticket thường reviewer kiêm chấm test."""
    tid = e.payload.get("ticket_id") or e.key
    return tid in o.lead.tickets and "qa" in o.lead.required_reviews(tid)


def _release_needs_security(e: Envelope, o: Orchestrator) -> bool:
    return o.lead.release_needs_security(e.payload["release_id"])


def _deployed(env_name: str) -> When:
    return lambda e, _o: e.payload.get("env") == env_name and e.payload.get("status") == "deployed"


def _answers_complete(e: Envelope, o: Orchestrator) -> bool:
    """Người đã trả lời hết câu hỏi của vòng gần nhất (hoặc clarifier đã hết vòng) → đi thẳng spec-writer.
    Thiếu câu trả lời mà vẫn viết spec thì spec dựa trên giả định người chưa xác nhận."""
    q = o.latest("clarification-questions", e.payload.get("project_id") or e.key)
    if q is None: return True
    asked = {str(x.get("id")) for x in q.payload.get("questions", [])}
    answered = {str(a.get("question_id")) for a in e.payload.get("answers", [])}
    return not (asked - answered) or int(q.payload.get("round", 1)) >= MAX_CLARIFY_ROUNDS


def _answers_incomplete(e: Envelope, o: Orchestrator) -> bool:
    return not _answers_complete(e, o)


def _spec_ready(e: Envelope, o: Orchestrator) -> bool:
    """Spec-writer chỉ chạy khi đã trả lời hết câu hỏi VÀ dự án có `requirements-draft`. Trước đây câu trả lời gửi cho
    một dự án chưa có bản nháp (chuỗi nghiên cứu chết, hoặc gửi nhầm dự án) vẫn sinh PRD từ đầu vào trống."""
    if not _answers_complete(e, o): return False
    pid = str(e.payload.get("project_id") or e.key)
    if o.latest("requirements-draft", pid) is not None: return True
    o._audit("spec_writer.no_draft", {"project_id": pid, "event_id": e.event_id,
                                      "reason": "clarification-answers nhưng dự án chưa có requirements-draft"},
             once=f"no_draft:{e.event_id}", project_id=pid)
    return False


def _cr_accepted_needs_research(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("decision") == "accepted" and bool(e.payload.get("affects_requirements"))


def _cr_accepted_direct(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("decision") == "accepted" and not e.payload.get("affects_requirements")


def _with_draft(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    d = o.latest("requirements-draft", e.payload.get("project_id") or e.key)
    return {"requirements_draft": d.payload} if d else {}


def _with_intake(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """Synthesizer cần CẢ báo cáo intake lẫn báo cáo 4 mục của researcher (ADR-0006), nhưng nó chỉ được đánh thức bởi
    báo cáo của researcher. Không đính kèm đề bài của intake thì tiêu chí bắt đầu không bao giờ đủ và draft luôn rỗng."""
    key = e.payload.get("project_id") or e.key
    found = [x for x in o.bus.replay("research-findings", key) if x.payload.get("kind") == "intake"]
    return {"intake": found[-1].payload.get("data")} if found and found[-1].payload.get("data") else {}


def _with_diff(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """Reviewer/QA/security đọc diff thật của branch ticket (khi có repo) thay vì tin `summary` của PR."""
    ws = o.workspace(e.payload.get("ticket_id") or e.key)
    if ws is None or not ws.path.exists(): return {}
    try: return {"diff": ws.diff(), "changed_files": ws.changed_files()}
    except WorkspaceError as ex: return {"diff_error": str(ex)[:300]}


ROUTES: tuple[Route, ...] = (
    # khối nghiên cứu: intake → researcher → synthesizer → risk → clarifier → (người trả lời) → spec-writer
    Route("research-requests", "intake", "research-findings"),
    Route("research-findings", "researcher", "research-findings", _from("intake"), tools="research"),
    Route("research-findings", "synthesizer", "requirements-draft", _from("researcher"), enrich=_with_intake),
    Route("requirements-draft", "risk", "requirements-draft", _from("synthesizer")),
    Route("requirements-draft", "clarifier", "clarification-questions", _from("risk")),
    Route("clarification-answers", "clarifier", "clarification-questions", _answers_incomplete, enrich=_with_draft),
    Route("clarification-answers", "spec-writer", "approved-specs", _spec_ready, enrich=_with_draft),
    # kỹ thuật + chất lượng
    Route("tasks", "$assignee", "pull-requests", tools="rw"),
    Route("pull-requests", "reviewer", "review-results", enrich=_with_diff),
    Route("pull-requests", "qa-debugger", "review-results", _needs_qa, enrich=_with_diff, tools="ro"),
    Route("pull-requests", "security-engineer", "review-results", _needs_security, enrich=_with_diff),
    # vận hành: RC → staging (+ security DAST/license khi có risk) → QA hồi quy; production đi qua gate 3 (PROD_ROUTE)
    Route("release-candidates", "release-engineer", "release-events", target_env="staging"),
    Route("release-candidates", "security-engineer", "review-results", _release_needs_security),
    Route("release-events", "qa-debugger", "review-results", _deployed("staging"), tools="ro"),  # tool trên worktree tích hợp
    Route("release-events", "support-docs", CONTEXT_ONLY, _deployed("production")),  # docs, release notes, runbook
    # khách và hậu release
    Route("external-feedback", "account-manager", "change-requests"),
    Route("external-feedback", "support-docs", "incidents", many=True),
    Route("incidents", "support-docs", "research-requests", _field("root_cause_class", "requirement"), many=True),
    Route("acceptance-results", "account-manager", "change-requests", _field("verdict", "conditional"), many=True),
    Route("change-requests", "delivery-lead", "audit-log", _field("decision", "pending")),  # ước lượng impact → người quyết
    Route("change-requests", "intake", "research-findings", _cr_accepted_needs_research),
)
PROD_ROUTE = Route("release-candidates", "release-engineer", "release-events", target_env="production")
THREAT_ROUTE = Route("approved-specs", "security-engineer", "review-results")  # threat model trước ticket đầu (ADR-0003)

# Đầu vào khiến delivery-lead lập kế hoạch (sinh nhiều ticket một lượt) → gate `plan` → dispatch.
PLAN_INPUTS: dict[str, When] = {
    "approved-specs": lambda e, _o: True,
    "incidents": _field("root_cause_class", "code", "ops", "design"),
    "change-requests": _cr_accepted_direct,
}


def check_routes(agents: dict[str, AgentSpec]) -> list[str]:
    """Bảng route phải khớp front matter reads/writes; trả về danh sách vi phạm (rỗng = ổn)."""
    bad = []
    for r in (*ROUTES, PROD_ROUTE, THREAT_ROUTE):
        for a in r.agents():
            spec = agents[a]
            if r.topic_in not in spec.reads and "*" not in spec.reads: bad.append(f"{a} không đọc {r.topic_in}")
            if r.topic_out == CONTEXT_ONLY:
                if not spec.namespaces_write: bad.append(f"{a} không có namespace để ghi blackboard")
            elif r.topic_out not in spec.writes: bad.append(f"{a} không ghi {r.topic_out}")
    lead = agents["delivery-lead"]
    bad += [f"delivery-lead không đọc {t}" for t in PLAN_INPUTS if t not in lead.reads]
    return bad


@dataclass
class StepResult:
    event_id: str
    topic: str
    key: str
    actions: list[str] = field(default_factory=list)
    deferred: str | None = None  # lý do hoãn (gate:..., paused:..., transient:...)
    transient: bool = False      # một agent gặp lỗi transport sau khi đã retry → event sẽ được thử lại ở nhịp sau


class Orchestrator:
    def __init__(self, bus: InMemoryBus, client: ModelClient, agents: dict[str, AgentSpec] | None = None,
                 max_retries: int = 3, repo: Path | None = None, base: str = "HEAD", max_turns: int = 25,
                 batch_releases: bool = False,
                 integration: str = "company/integration", workers: int = 1, web: WebTools | bool = False,
                 artifacts: Path | None = None, project_budget_usd: float | None = None):
        self.bus = bus
        self.repo, self.max_turns = (Path(repo) if repo else None), max_turns
        self.workers = max(1, int(workers))
        self.web = web if isinstance(web, WebTools) else (WebTools() if web else None)
        self._lock = threading.RLock()   # trạng thái orchestrator (processed, deferred, once, stats) — KHÔNG publish khi đang giữ
        self._qlock = threading.RLock()  # hàng đợi; _on_event (chạy dưới lock của bus) chỉ chạm lock này
        self._ws_lock = threading.RLock()
        self.partial: dict[str, set[str]] = {}  # event_id → agent đã chạy xong (để không chạy lại khi event bị hoãn transient)
        if self.repo is not None and not (self.repo / ".git").exists():
            raise ValueError(f"repo không phải git repository: {self.repo}")
        self.integration = Integration(self.repo, integration, base) if self.repo is not None else None
        self.void_releases: set[str] = set()
        self.integrated: set[str] = set()  # ticket đã merge vào nhánh tích hợp (khi approved, không đợi RC)
        self.missing_threat_model: set[str] = set()  # spec chưa có threat model vì security-engineer lỗi
        self.stalled: dict[str, dict[str, Any]] = {}  # project_id → {event_id, agent, topic, error}: dự án kẹt chờ người
        self.stall_count: Counter[str] = Counter()  # event_id → số lần kẹt (mỗi lần một gate mới, không im lặng lần hai)
        self.agents = agents or load_agents()
        bad = check_routes(self.agents)
        if bad: raise ValueError("ROUTES lệch front matter: " + "; ".join(bad))
        self.blackboard = Blackboard(bus, store=artifacts)
        self.gate = PersistentGate(bus)
        self.lead = DeliveryLead(bus, self.gate, max_retries=max_retries, batch_releases=batch_releases)
        self.lead.require_integration = self.integration is not None
        budget_usd = project_budget_usd if project_budget_usd is not None else getattr(client, "budget_usd", None)
        self.supervisor = Supervisor(bus, max_retries=max_retries, project_budget_usd=budget_usd)
        self.runner = AgentRunner(bus, client, self.agents, self.blackboard)
        self.processed: set[str] = set()
        self.paused: set[str] = set()
        self.plans: dict[str, dict[str, Any]] = {}
        self.queue: list[Envelope] = []
        self.deferred: dict[str, tuple[Envelope, str]] = {}
        self.once: set[str] = set()  # nhắc nhở / hành động chỉ làm một lần (gate.remind, review.reassign, lesson...)
        self.stats: Counter[str] = Counter()
        self._rehydrate()
        bus.subscribe("*", self._on_event)

    # ---------- khôi phục từ log ----------

    def _rehydrate(self) -> None:
        # Một lần duyệt log, không hai: `replay()` trên bus bền vững parse lại từng envelope, nên quét đôi là nhân đôi
        # thời gian mở lại một dự án đã chạy lâu.
        log = list(self.bus.replay())
        for env in log:
            if env.topic == "audit-log":
                a = env.payload; d = _evidence(a)
                if a["actor"] == ACTOR and a["action"] == "orchestrated": self.processed.add(d["event_id"])
                elif a["actor"] == ACTOR and a["action"] == "once": self.once.add(d["key"])
                elif a["action"] == "plan.proposed": self.plans[d["plan_id"]] = d
                elif a["action"] == "release.void": self.void_releases.add(d["release_id"])
                elif a["action"] == "integration.merged":
                    self.integrated.add(d["ticket_id"])
                    prev_r, self.lead.replaying = self.lead.replaying, True
                    try: self.lead.mark_integrated(d["ticket_id"])
                    finally: self.lead.replaying = prev_r
                elif a["action"] == "threat_model.missing": self.missing_threat_model.add(d["subject_id"])
                elif a["action"] == "project.stalled":
                    self.stalled[d["project_id"]] = d; self.stall_count[d["event_id"]] += 1
                elif a["action"] in {"project.retried", "project.closed"}: self.stalled.pop(d["project_id"], None)
                elif a["action"] == "gate.decide" and d.get("decision") == "approve" and d["subject_id"] in self.plans:
                    self._dispatch_plan(d["subject_id"], replaying=True)
            elif env.topic == "supervisor-actions": self._track_pause(env)
            elif env.topic == "shared-context": self.blackboard._on(env)
            else: self.lead.replay(env)
            self.supervisor.replay(env)
        self.queue = [e for e in log if self._actionable(e) and e.event_id not in self.processed]

    def _actionable(self, env: Envelope) -> bool:
        if env.topic == "audit-log": return env.payload.get("action") == "gate.decide"
        return env.topic not in CONTROL_TOPICS

    def _track_pause(self, env: Envelope) -> None:
        act, target = env.payload["action"], env.payload["target"]
        if act in PAUSING: self.paused.add(target)
        elif act == "resume": self.paused.discard(target)

    def _on_event(self, env: Envelope) -> None:
        if env.topic == "supervisor-actions":
            self._track_pause(env)
            if env.payload["action"] == "resume": self._retry_deferred()
        elif self._actionable(env):
            with self._qlock: self.queue.append(env)

    def latest(self, topic: str, key: str) -> Envelope | None:
        return self.bus.latest(topic, key)

    def workspace(self, ticket_id: str) -> TicketWorkspace | None:
        """Worktree của ticket, rẽ từ nhánh tích hợp (tạo nhánh tích hợp nếu chưa có)."""
        if self.repo is None or self.integration is None: return None
        with self._ws_lock: self.integration.ensure()  # nhiều worker cùng tạo nhánh tích hợp lần đầu → tuần tự
        return TicketWorkspace(self.repo, ticket_id, base=self.integration.branch)

    # ---------- vòng lặp ----------

    @staticmethod
    def _target(env: Envelope) -> str:
        return str(env.payload.get("ticket_id") or env.key)

    def _parallel_ok(self, env: Envelope) -> bool:
        """Event chạy được cùng lúc với event khác key? Gate decide, lập kế hoạch, RC (merge tích hợp), clarifier
        (rẽ nhánh theo trạng thái) luôn chạy một mình vì chúng đổi trạng thái chung."""
        if env.topic in {"audit-log", "release-candidates", "clarification-questions"}: return False
        if env.topic in PLAN_INPUTS and PLAN_INPUTS[env.topic](env, self): return False
        return True

    def _take_batch(self, n: int) -> list[Envelope]:
        """Lấy tối đa n event có target khác nhau từ đầu hàng đợi (giữ thứ tự trong cùng key)."""
        with self._qlock:
            batch = [self.queue.pop(0)]
            if n <= 1 or not self._parallel_ok(batch[0]): return batch
            keys, i = {self._target(batch[0])}, 0
            while i < len(self.queue) and len(batch) < n:
                e = self.queue[i]; k = self._target(e)
                if self._parallel_ok(e) and k not in keys: batch.append(self.queue.pop(i)); keys.add(k)
                else: i += 1
            return batch

    def run(self, max_steps: int | None = None, workers: int | None = None) -> list[StepResult]:
        """Xử lý hàng đợi đến khi rỗng (hoặc đủ max_steps). Event bị hoãn không làm vòng lặp quay mãi.
        `workers` > 1: mỗi vòng lấy một lô event khác key và chạy song song (ADR-0012)."""
        workers = workers or self.workers
        out: list[StepResult] = []
        while self.queue and (max_steps is None or len(out) < max_steps):
            room = workers if max_steps is None else max(1, min(workers, max_steps - len(out)))
            batch = self._take_batch(room)
            if len(batch) == 1:
                results = [self.process(batch[0])]
            else:
                with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="orch") as ex:
                    results = list(ex.map(self.process, batch))
            out += [r for r in results if r is not None]
            self._check_escalations()
            self._integrate_pending(out)
        self._check_escalations()  # supervisor escalate ở event cuối hàng đợi: gate vẫn phải mở, không chờ event kế tiếp
        self._integrate_pending(out)
        return out

    def _integrate_pending(self, out: list[StepResult]) -> None:
        """Ticket approved mà chưa lên nhánh tích hợp thì merge ngay, không phụ thuộc vào việc có event nào của nó
        được xử lý: review-results cuối cùng có thể bị hoãn (ticket vừa bị supervisor cắt ngân sách) và từ F15 ticket
        phụ thuộc chỉ bắt đầu sau khi merge — không có bước này dự án đứng im."""
        if self.integration is None: return
        res = StepResult("integration", "integration", "-")
        self._integrate_approved(res)
        if res.actions: out.append(res)

    def tick(self, now: datetime | None = None) -> list[StepResult]:
        """Một nhịp của chế độ watch: nạp event từ tiến trình khác, thử lại event hoãn vì lỗi transport, chạy hàng đợi,
        nhắc gate quá hạn, giao lại review quá hạn, escalate ticket im lặng quá lâu."""
        if hasattr(self.bus, "poll"): self.bus.poll()
        self._retry_deferred(only="transient:")
        results = self.run()
        remind, overdue = self.gate.due(now)
        for sid in [*remind, *overdue]:
            self._audit(f"gate.{'overdue' if sid in overdue else 'remind'}", {"subject_id": sid}, once=f"gate:{sid}")
        for sid in overdue:  # quá hạn không tự đi tiếp, nhưng cũng không im lặng: supervisor nhận việc
            self.supervisor.escalate_gate(sid, f"gate quá hạn {self.gate.timeout}", once_key=f"gate.escalate:{sid}")
        for tid, missing in self.lead.overdue_reviews(now).items():
            pr = self.latest("pull-requests", tid)
            since = self.lead.review_since[tid].isoformat()  # đọc trước: _call bên dưới có thể đóng vòng review và xoá nó
            for src in sorted(missing):
                key = f"review:{tid}:{src}:{since}"
                if pr is None or key in self.once: continue
                self._remember(key); self._audit("review.reassign", {"ticket_id": tid, "source": src}, ticket_id=tid)
                res = StepResult(pr.event_id, pr.topic, pr.key)
                self._call(REVIEW_AGENT[src], pr, Route("pull-requests", REVIEW_AGENT[src], "review-results"), res)
                results.append(res)
                # Giao lại chỉ một lần (`once`): lượt thứ hai cũng lỗi/quá hạn thì không ai giao nữa và ticket nằm
                # `in_review` mãi. Đưa cho người: supervisor escalate → ticket hoãn, gate `escalation` mở.
                failed = [a for a in res.actions if a.split(":", 1)[0] in {"error", "handler_error", "transient"}]
                if failed:
                    self._audit("review.reassign_failed", {"ticket_id": tid, "source": src, "error": failed[0][:300]}, ticket_id=tid)
                    self.supervisor.escalate_gate(tid, f"review {src} giao lại vẫn lỗi: {failed[0][:200]}", once_key=f"review.escalate:{key}")
        active = {tid for tid, st in self.lead.state.items() if st in ACTIVE_STATES}
        self.supervisor.check_timeouts(now, active=active)
        results += self.run()
        return results

    def watch(self, interval: float = 5.0, max_ticks: int | None = None) -> None:
        n = 0
        while max_ticks is None or n < max_ticks:
            try:
                for r in self.tick(): print(_fmt(r))
            except Exception as e:  # một nhịp lỗi (bus/git/handler) không được giết vòng watch
                self._audit("tick_error", {"error": f"{type(e).__name__}: {str(e)[:300]}"})
                print(f"tick_error: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            n += 1
            if max_ticks is None or n < max_ticks: time.sleep(interval)

    def process(self, env: Envelope) -> StepResult | None:
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
        if env.topic in PLAN_INPUTS and PLAN_INPUTS[env.topic](env, self):
            return self._plan(env, res)
        if env.topic == "release-candidates" and not self._integrate(env, res):
            self._mark(env, res); return res  # RC huỷ vì xung đột: ticket đã được giao lại, không deploy
        if env.topic == "clarification-questions" and not env.payload.get("questions"):
            # clarifier không còn câu hỏi (hoặc quá round 2 → assumption): spec-writer đi thẳng từ draft sau risk
            draft = self.latest("requirements-draft", env.key)
            if draft is not None:
                self._call("spec-writer", draft, Route("requirements-draft", "spec-writer", "approved-specs"), res)
        if env.topic in {"tasks", "review-results"}:
            # Ticket approved lên nhánh tích hợp TRƯỚC khi ticket phụ thuộc (đã được delivery-lead dispatch ngay lúc
            # approve, nên đứng trước review-results trong hàng đợi) tạo worktree.
            self._integrate_approved(res)
        for r in ROUTES:
            if r.topic_in != env.topic or (r.when and not r.when(env, self)): continue
            agent = env.payload["assignee"] if r.agent == "$assignee" else r.agent
            self._call(agent, env, r, res)
        if env.topic == "release-events" and _deployed("production")(env, self):
            self._open_acceptance_gate(env.key, res)
        if env.topic == "acceptance-results":
            self._close_acceptance_gate(env, res)
            self._record_lessons(env.payload["release_id"])
        self._note_closed()
        if res.transient:  # một agent chưa chạy được vì transport: giữ event lại, nhịp sau thử tiếp (agent xong rồi không chạy lại)
            stuck = next((a for a in res.actions if a.startswith("transient:")), "transient:?")
            return self._defer(env, res, ":".join(stuck.split(":")[:2]))
        self._mark(env, res)
        return res

    def _note_closed(self) -> None:
        """Ghi `ticket.closed` cho ticket vừa vào trạng thái cuối. `metrics.collect` tính lead time (tasks đầu → closed)
        từ chính action này; không ai phát thì `ticket_lead_seconds` luôn rỗng và gauge Prometheus không bao giờ hiện."""
        for tid, st in list(self.lead.state.items()):
            if st != "closed": continue
            t = self.lead.tickets.get(tid)
            self._audit("ticket.closed", {"ticket_id": tid, "retry": t.retry if t else 0}, once=f"closed:{tid}",
                        ticket_id=tid, project_id=t.project_id if t else None)

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
        with self._lock:
            if agent in self.partial.get(env.event_id, set()): return  # đã chạy xong ở lần xử lý trước (event bị hoãn transient)
        try:
            extra = dict(r.enrich(env, self)) if r.enrich else {}
            if (pid := self.project_for(env)) and not env.payload.get("project_id"): extra["project_id"] = pid
            inp = env.model_copy(update={"payload": {**env.payload, **extra}}) if extra else env
            if r.target_env:
                out = self._release(agent, env, r); res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            elif r.tools == "rw":
                pr = self._engineer(agent, inp, r)
                res.actions.append(f"{agent}→{r.topic_out}:{pr.key}" if pr is not None else f"{agent}→rework:{inp.key}")
            elif r.topic_out == CONTEXT_ONLY:
                g = self.runner.run_context(agent, inp)
                res.actions.append(f"{agent}→blackboard:{','.join(w['namespace'] for w in g.context_writes) or '-'}")
            elif r.many:
                g = self.runner.generate(agent, inp, r.topic_out, many=True)
                if g.context_writes: self.runner.write_context(agent, env, g.context_writes)
                if env.topic == "acceptance-results":  # CR từ nghiệm thu conditional phải truy được release (đóng ticket khi quyết)
                    g.payloads = [{**p, "release_id": env.key} for p in g.payloads]
                for i, p in enumerate(g.payloads):  # token/tiền tính một lần cho cả lượt, không nhân theo số payload
                    self.runner.publish(agent, env, r.topic_out, p, key=key_for(r.topic_out, p, env.key),
                                        tokens=g.tokens if i == 0 else 0, model=g.model, generated=g if i == 0 else None)
                if not g.payloads:
                    self._audit("produced:nothing", {"agent": agent, "topic": r.topic_out, **json.loads(g.evidence())},
                                actor=agent, tokens=g.tokens, cost=g.cost_usd)
                res.actions.append(f"{agent}→{r.topic_out}×{len(g.payloads)}")
            else:
                tools = None
                if r.tools == "ro":
                    tools = self._read_only_tools(inp)
                elif r.tools == "research":
                    tools = research_toolbox(self.repo, self.web)
                g = self.runner.generate(agent, inp, r.topic_out, tools=tools, max_turns=self.max_turns)
                if r.tools == "ro" and tools is not None and not g.tool_calls:
                    # Có tool mà không chạy gì: verdict chỉ là lời khai. Không chặn (người đọc review vẫn quyết), nhưng phải hiện.
                    self._audit("review.no_tool_evidence", {"agent": agent, "topic": env.topic, "key": env.key},
                                actor=agent, ticket_id=inp.payload.get("ticket_id"), project_id=self.project_for(env))
                out = self.runner.publish(agent, env, r.topic_out, g.payloads[0], key=key_for(r.topic_out, g.payloads[0], env.key),
                                          tokens=g.tokens, model=g.model, context_writes=g.context_writes, generated=g)
                res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            with self._lock:
                self.stats["runs"] += 1; self.partial.setdefault(env.event_id, set()).add(agent)
        except TransientError as e:  # hết retry transport: không phải lỗi agent — hoãn event, nhịp sau thử lại
            res.actions.append(f"transient:{agent}:{str(e)[:120]}"); res.transient = True
            with self._lock: self.stats["transient"] += 1
        except (RunnerError, LLMError) as e:  # runner đã ghi audit; không retry lời gọi (ADR-0005)
            res.actions.append(f"error:{agent}:{str(e)[:120]}")
            with self._lock: self.stats["errors"] += 1; self.partial.setdefault(env.event_id, set()).add(agent)
            self._stall(env, agent, e, res)
            self._rework_after_error(env, r, e)
        except Exception as e:  # handler xác định (delivery-lead) từ chối chuyển trạng thái: event đã ghi đĩa
            self._audit("handler_error", {"agent": agent, "error": str(e)[:300]}, ticket_id=env.payload.get("ticket_id"))
            res.actions.append(f"handler_error:{agent}:{str(e)[:120]}")
            with self._lock: self.stats["errors"] += 1; self.partial.setdefault(env.event_id, set()).add(agent)
            self._stall(env, agent, e, res)
            self._rework_after_error(env, r, e)  # WorkspaceError (git/commit) cũng không được để ticket treo `dispatched`

    def _rework_after_error(self, env: Envelope, r: Route, error: Exception) -> None:
        """Agent kỹ thuật lỗi (không sửa file, JSON hỏng, hết ngân sách lượt...) → ticket không được treo `dispatched`
        mãi: delivery-lead phát lại task retry+1 với hint là lỗi, hết retry → blocked → gate escalation."""
        if r.tools != "rw": return
        tid = str(env.payload.get("ticket_id") or env.key)
        if self.lead.state.get(tid) not in {"dispatched", "in_progress"}: return
        try:
            self.lead.rework(tid, f"lần trước lỗi: {str(error)[:500]}")
        except ValueError as ex:
            self._audit("handler_error", {"agent": "delivery-lead", "error": str(ex)[:300]}, ticket_id=tid)

    def _stall(self, env: Envelope, agent: str, error: Exception, res: StepResult) -> None:
        """Agent của chuỗi nghiên cứu lỗi → dự án không có bước kế tiếp. Ghi `project.stalled`, supervisor escalate
        (dự án bị hoãn mọi event), mở gate `escalation` subject=project_id. Ticket có cơ chế retry/blocked riêng."""
        if env.topic not in RESEARCH_TOPICS: return
        pid = str(env.payload.get("project_id") or env.key)
        with self._lock:
            self.stall_count[env.event_id] += 1; n = self.stall_count[env.event_id]
            self.stalled[pid] = {"project_id": pid, "event_id": env.event_id, "topic": env.topic, "agent": agent,
                                 "error": str(error)[:300], "attempt": n}
        self._audit("project.stalled", self.stalled[pid], project_id=pid)
        self.supervisor.escalate_gate(pid, f"{agent} lỗi trên {env.topic} (lần {n}): {str(error)[:200]}",
                                      once_key=f"stall:{env.event_id}:{n}")
        if pid not in self.gate.pending:
            self.gate.request(GateRequest(kind="escalation", subject_id=pid, created_by="supervisor",
                                          checklist=["agent_error", "decision:retry|close"]))
        res.actions.append(f"stalled:{pid}:{agent}")

    def _retry_stalled(self, pid: str, by: str, reason: str) -> bool:
        """Người duyệt gate escalation của dự án: chạy lại event đã lỗi (bỏ dấu đã xử lý, đưa về đầu hàng đợi)."""
        st = self.stalled.get(pid)
        if st is None: return False
        env = next((e for e in self.bus.replay(topic=st["topic"], key=pid) if e.event_id == st["event_id"]), None)
        if env is None: return False
        with self._lock:
            self.processed.discard(env.event_id); self.partial.pop(env.event_id, None); self.stalled.pop(pid, None)
        self._audit("project.retried", {**st, "by": by, "reason": reason}, project_id=pid)
        with self._qlock: self.queue.insert(0, env)
        return True

    def _integrate_approved(self, res: StepResult) -> None:
        """Ticket vừa approved → merge ngay vào nhánh tích hợp, không đợi RC. Ticket phụ thuộc rẽ nhánh từ nhánh tích hợp,
        nên nếu chỉ merge lúc release (nhất là khi gom release) thì ticket sau không thấy code của ticket trước:
        DHCB-5 import `dhcb.layout` của DHCB-2 và đỏ ngay dù DHCB-2 đã approved."""
        if self.integration is None: return
        for tid, st in list(self.lead.state.items()):
            if st != "approved" or tid in self.integrated: continue
            self._merge_ticket(tid, res, release_id=None)

    def _merge_ticket(self, tid: str, res: StepResult, release_id: str | None) -> bool:
        """merge --no-ff branch ticket vào nhánh tích hợp. Xung đột → ticket về changes_requested với hint là file xung
        đột, worktree tạo lại từ nền mới; trả về False."""
        assert self.integration is not None
        ws = self.workspace(tid)
        if ws is None or not ws.path.exists():
            self._audit("integration.skipped", {"release_id": release_id, "ticket_id": tid, "reason": "không có worktree"}, ticket_id=tid)
            return True
        t = self.lead.tickets.get(tid)
        before = self.integration.sha()
        m = self.integration.merge(ws.branch, f"merge({tid}): {t.title if t else tid}" + (f"\n\nrelease: {release_id}" if release_id else ""))
        if m.ok and m.sha == before:
            # Branch không có gì mới so với nhánh tích hợp (vd. vừa `fresh()` sau xung đột, chưa có PR mới): không phải
            # "đã tích hợp" — đánh dấu thế là mất code của lần làm lại về sau.
            self._audit("integration.noop", {"release_id": release_id, "ticket_id": tid, "sha": before}, ticket_id=tid)
            res.actions.append(f"integration_noop:{tid}"); return True
        if m.ok:
            with self._lock: self.integrated.add(tid)
            self._audit("integration.merged", {"release_id": release_id, "ticket_id": tid, "sha": m.sha, "branch": self.integration.branch}, ticket_id=tid)
            res.actions.append(f"integrated:{tid}@{m.sha}")
            started = self.lead.mark_integrated(tid)  # F15: ticket phụ thuộc bắt đầu trên nền đã có code này
            if started: res.actions.append("dispatch:" + ",".join(started))
            return True
        hint = f"xung đột với nhánh tích hợp {self.integration.branch} ở: {', '.join(m.conflicts or [])}. Làm lại trên nền mới."
        self._audit("integration.conflict", {"release_id": release_id, "ticket_id": tid, "conflicts": m.conflicts}, ticket_id=tid)
        try:
            ws.fresh()
            self.lead.request_changes(tid, hint)
        except (ValueError, WorkspaceError) as e:
            self._audit("handler_error", {"agent": "delivery-lead", "error": str(e)[:300]}, ticket_id=tid)
        res.actions.append(f"conflict:{tid}")
        with self._lock: self.stats["conflicts"] += 1
        return False

    def _integrate(self, rc: Envelope, res: StepResult) -> bool:
        """Mọi ticket của RC phải nằm trên nhánh tích hợp (thường đã merge lúc approved). Trả về False nếu RC bị huỷ."""
        if self.integration is None: return True
        rid = rc.payload["release_id"]
        if rid in self.void_releases: return False
        for tid in rc.payload.get("tickets", []):
            if tid in self.integrated: continue
            if self.lead.state.get(tid) not in {"approved", "merged"}:  # đã bị trả về (xung đột lúc approved): RC vô nghĩa
                self._audit("release.void", {"release_id": rid, "ticket_id": tid, "reason": f"ticket đang {self.lead.state.get(tid)}"}, ticket_id=tid)
                self.void_releases.add(rid); res.actions.append(f"void:{rid}")
                return False
            if not self._merge_ticket(tid, res, release_id=rid):
                self._audit("release.void", {"release_id": rid, "ticket_id": tid}, ticket_id=tid)
                self.void_releases.add(rid)
                return False
        return True

    def _read_only_tools(self, inp: Envelope) -> ToolBox | None:
        """Tool chỉ đọc cho QA: worktree của ticket (review PR) hoặc worktree tích hợp (hồi quy sau khi deploy staging —
        release không có ticket riêng, nhưng code vừa deploy chính là nhánh tích hợp). Không có repo → không tool."""
        if self.repo is None or self.integration is None: return None
        tid = inp.payload.get("ticket_id") or (inp.key if inp.topic in {"tasks", "pull-requests"} else None)
        if tid and (ws := self.workspace(str(tid))) is not None and ws.path.exists():
            return WorkspaceTools(ws, allow_write=False).toolbox()
        if inp.payload.get("release_id") and self.integration.path.exists():
            return WorkspaceTools(self.integration.path, allow_write=False).toolbox()
        return None

    def _engineer(self, agent: str, task: Envelope, r: Route) -> Envelope | None:
        """Ticket → PR. Có repo: agent làm trong worktree, bằng chứng do code điền. Không repo: PR đi tiếp nhưng
        `local_checks` của model bị thay bằng `{"unverified": true}` và ghi audit — không có bằng chứng giả."""
        tid = task.payload.get("ticket_id") or task.key
        budget = self.lead.tickets[tid].budget_tokens if tid in self.lead.tickets else task.payload.get("budget_tokens")
        if (b := self.supervisor.budgets.get(tid)) is not None:
            # Lần làm lại chỉ còn phần ngân sách chưa đốt (supervisor cộng dồn theo audit, kể cả phần đã cấp thêm)
            budget = max(b.limit - b.used, 0)
        ws = self.workspace(tid)
        if ws is not None:
            g = self.runner.generate_in_workspace(agent, task, ws, budget=budget, max_turns=self.max_turns)
            p = g.payloads[0]
            lc = p["local_checks"]
            if lc.get("lint") is False or lc.get("tests") is False:
                # Máy đã biết PR đỏ: không đưa qua reviewer/QA/security (tốn ba lượt để nghe lại), trả thẳng về ticket.
                bad = [k for k in ("lint", "tests") if lc.get(k) is False]
                hint = f"{'/'.join(bad)} local fail (retry {task.payload.get('retry', 0)}):\n" + \
                       "\n".join((lc.get({"lint": "lint_output", "tests": "test_output"}[k]) or "")[-1500:] for k in bad)
                self._audit("pr.rejected_local_checks", {"ticket_id": tid, "agent": agent, "failed": bad, "commit": p.get("pr_ref"),
                                                         "files": p.get("impact", {}).get("files", [])},
                            actor=agent, tokens=g.tokens, cost=g.cost_usd, ticket_id=tid, project_id=task.payload.get("project_id"))
                if tid in self.lead.tickets: self.lead.rework(tid, hint)
                return None
        else:
            g = self.runner.generate(agent, task, r.topic_out)
            p = {**g.payloads[0], "local_checks": {"unverified": True}}
            self._audit("local_checks.unverified", {"ticket_id": tid, "agent": agent, "claimed": g.payloads[0].get("local_checks")},
                        actor=agent, ticket_id=tid)
        return self.runner.publish(agent, task, r.topic_out, p, key=key_for(r.topic_out, p, task.key),
                                   tokens=g.tokens, model=g.model, context_writes=g.context_writes, generated=g)

    def _release(self, agent: str, rc: Envelope, r: Route) -> Envelope:
        """release-engineer nhận RC kèm `target_env`; đầu ra phải đúng env và release_id, nếu không thì coi là invalid."""
        rid = rc.payload["release_id"]
        extra = {"integration_branch": self.integration.branch, "integration_sha": self.integration.sha()} if self.integration else {}
        inp = rc.model_copy(update={"payload": {**rc.payload, "target_env": r.target_env,
                                                "gate_release": self.gate.is_approved(rid), **extra}})
        g = self.runner.generate(agent, inp, r.topic_out)
        p = g.payloads[0]
        if p.get("env") != r.target_env or p.get("release_id") != rid:
            self._audit("invalid_output", {"agent": agent, "expected_env": r.target_env, "got": p.get("env")},
                        actor=agent, tokens=g.tokens)
            raise RunnerError(f"{agent}: đầu ra env={p.get('env')} release_id={p.get('release_id')}, cần {r.target_env}/{rid}")
        if (want := rc.payload.get("version")) and p.get("version") != want:
            # Phiên bản là của RC (delivery-lead suy từ nội dung release), không phải lời khai của model.
            self._audit("release.version_overridden", {"release_id": rid, "claimed": p.get("version"), "version": want}, actor=agent)
            p = {**p, "version": want}
        return self.runner.publish(agent, rc, r.topic_out, p, key=rid, tokens=g.tokens, model=g.model, generated=g)

    # ---------- kế hoạch: gate spec → threat model → delivery-lead sinh ticket → gate plan → dispatch ----------

    def _plan(self, env: Envelope, res: StepResult) -> StepResult:
        project = env.payload.get("project_id") or env.key
        if env.topic == "approved-specs":
            sid = f"SPEC-{project}"
            if not self.gate.is_approved(sid):
                decided = [g for g in self.gate.history if g.subject_id == sid]
                if sid not in self.gate.pending and not decided:
                    self.gate.request(GateRequest(kind="spec", subject_id=sid, created_by=env.actor,
                                                  checklist=["prd", "acceptance-criteria", "ux-flow", "risks"]))
                if decided and sid not in self.gate.pending:
                    res.actions.append(f"gate:{sid}:{decided[-1].decision}"); self._mark(env, res); return res
                return self._defer(env, res, f"gate:{sid}")
            if not self._threat_model(env, sid, res):
                self._mark(env, res); return res
            live = [pid for pid, p in self.plans.items() if p["project_id"] == project and p["source_topic"] == "approved-specs"
                    and (pid in self.gate.pending or self.gate.is_approved(pid))]
            if live:
                # Spec publish lặp (spec-writer chạy lại, người publish hai lần) không được sinh plan thứ hai cho cùng
                # dự án: ticket trùng, hai gate plan cho một việc. Muốn lập lại thì reject plan cũ trước.
                self._audit("plan.duplicate_spec", {"project_id": project, "event_id": env.event_id, "existing": live}, project_id=project)
                res.actions.append(f"plan_skipped:{','.join(live)}"); self._mark(env, res); return res
        cal = self.supervisor.calibration()  # vòng học: bài học estimate-vs-actual quay lại người ước lượng
        inp = env.model_copy(update={"payload": {**env.payload, "estimate_calibration": cal}}) if cal else env
        try:
            g = self.runner.generate("delivery-lead", inp, "tasks", many=True)
        except TransientError as e:
            res.actions.append(f"transient:delivery-lead:{str(e)[:120]}")
            with self._lock: self.stats["transient"] += 1
            return self._defer(env, res, "transient:delivery-lead")
        except (RunnerError, LLMError) as e:
            res.actions.append(f"error:delivery-lead:{str(e)[:120]}")
            with self._lock: self.stats["errors"] += 1
            self._mark(env, res); return res
        if g.context_writes:  # C4, API contract lên blackboard TRƯỚC khi xin gate plan để người duyệt đọc được
            self.runner.write_context("delivery-lead", env, g.context_writes)
        tickets = [Task.model_validate(p) for p in g.payloads]
        problems = self._check_plan(tickets)
        n = 1 + sum(1 for p in self.plans.values() if p["project_id"] == project)
        plan_id = f"PLAN-{project}-{n}"
        plan = {"plan_id": plan_id, "project_id": project, "source_event": env.event_id, "source_topic": env.topic,
                "tickets": [t.model_dump() for t in tickets], "problems": problems,
                "threat_model": "missing" if f"SPEC-{project}" in self.missing_threat_model else "ok"}
        if problems:
            self._audit("plan_rejected", plan, actor="delivery-lead", tokens=g.tokens, cost=g.cost_usd, project_id=project)
            res.actions.append(f"plan_rejected:{'; '.join(problems)[:120]}")
            with self._lock: self.stats["errors"] += 1
        else:
            self.plans[plan_id] = plan
            self._audit("plan.proposed", plan, actor="delivery-lead", tokens=g.tokens, cost=g.cost_usd, project_id=project)
            self.gate.request(GateRequest(kind="plan", subject_id=plan_id, created_by="delivery-lead",
                                          checklist=["tickets", "estimate_tokens", "risk_tags", "depends_on", "threat-model",
                                                     "architecture", "api-contract"]))
            res.actions.append(f"plan:{plan_id}:{len(tickets)} ticket")
            with self._lock: self.stats["plans"] += 1
        self._mark(env, res)
        return res

    def _threat_model(self, env: Envelope, sid: str, res: StepResult) -> bool:
        """Security-engineer đọc spec đã duyệt: threat model v1 lên blackboard + review-results key=SPEC-*.
        Verdict block → không lập kế hoạch (người sửa spec rồi publish lại). Trả về True nếu được đi tiếp."""
        prior = self.latest("review-results", sid)
        if prior is not None and prior.payload.get("verdict") != "block":
            return True
        try:
            g = self.runner.generate("security-engineer", env, "review-results")
            p = {**g.payloads[0], "ticket_id": sid, "source": "security"}
            self.runner.publish("security-engineer", env, "review-results", p, key=sid, tokens=g.tokens, model=g.model,
                                context_writes=g.context_writes, generated=g)
            with self._lock: self.stats["runs"] += 1
        except TransientError as e:
            res.actions.append(f"transient:security-engineer:{str(e)[:120]}")
            with self._lock: self.stats["transient"] += 1
            return True  # threat model không chặn plan; lần lập kế hoạch sau (nếu có) sẽ thử lại
        except (RunnerError, LLMError) as e:
            # Không chặn kế hoạch (người duyệt gate plan vẫn quyết được), nhưng phải hiện ra: audit riêng + đánh dấu
            # vào plan để mục `threat-model` trong checklist gate không bị tick nhầm là đã có.
            self._audit("threat_model.missing", {"subject_id": sid, "error": str(e)[:300]},
                        project_id=env.payload.get("project_id"))
            with self._lock: self.missing_threat_model.add(sid)
            res.actions.append(f"error:security-engineer:{str(e)[:120]}")
            with self._lock: self.stats["errors"] += 1
            return True
        if p["verdict"] == "block":
            self._audit("spec_blocked_by_security", {"subject_id": sid, "findings": p.get("findings", [])}, project_id=env.payload.get("project_id"))
            res.actions.append(f"spec_blocked:{sid}"); return False
        res.actions.append(f"threat-model:{sid}:{p['verdict']}"); return True

    def _check_plan(self, tickets: list[Task]) -> list[str]:
        ids = {t.ticket_id for t in tickets}; known = ids | set(self.lead.tickets)
        problems = ["kế hoạch rỗng"] if not tickets else []
        if len(ids) != len(tickets): problems.append("ticket_id trùng")
        for t in tickets:
            if t.ticket_id in self.lead.tickets: problems.append(f"{t.ticket_id} đã tồn tại")
            if t.estimate_tokens is None: problems.append(f"{t.ticket_id} thiếu estimate_tokens")
            elif t.budget_tokens < t.estimate_tokens * BUDGET_FACTOR: problems.append(f"{t.ticket_id} budget < estimate×{BUDGET_FACTOR}")
            if not t.acceptance: problems.append(f"{t.ticket_id} thiếu acceptance")
            unknown = [d for d in t.depends_on if d not in known]
            if unknown or t.ticket_id in t.depends_on: problems.append(f"{t.ticket_id} depends_on sai {unknown or 'chính nó'}")
        cyc = _cycle({t.ticket_id: [d for d in t.depends_on if d in ids] for t in tickets})
        if cyc: problems.append("depends_on vòng: " + " → ".join(cyc))
        return problems

    def _dispatch_plan(self, plan_id: str, replaying: bool = False) -> list[str]:
        plan = self.plans[plan_id]
        pending = [Task.model_validate(t) for t in plan["tickets"] if t["ticket_id"] not in self.lead.tickets]
        done: list[str] = []
        prev, self.lead.replaying = self.lead.replaying, replaying
        try:
            while pending:
                ready = [t for t in pending if all(d in self.lead.tickets for d in t.depends_on)]
                if not ready: raise ValueError(f"{plan_id}: depends_on vòng hoặc chưa biết: {[t.ticket_id for t in pending]}")
                for t in sorted(ready, key=lambda x: x.priority):
                    self.lead.dispatch(t, plan_id); pending.remove(t); done.append(t.ticket_id)
        finally:
            self.lead.replaying = prev
        return done

    # ---------- gate decide: plan → dispatch; release → production; escalation → mở lại / đóng ----------

    def _on_gate_decide(self, env: Envelope, res: StepResult) -> StepResult:
        d = _evidence(env.payload); sid, decision, by = d["subject_id"], d["decision"], d.get("by", "human")
        kind = next((g.kind for g in reversed(self.gate.history) if g.subject_id == sid), None)
        res.actions.append(f"gate:{kind}:{sid}:{decision}")
        if kind == "escalation":
            self._on_escalation_decided(sid, decision, by, d.get("reason", ""), res)
        elif decision == "approve":
            if sid in self.plans:
                try:
                    res.actions.append("dispatch:" + ",".join(self._dispatch_plan(sid)))
                except (ValueError, PermissionError) as e:
                    self._audit("plan_dispatch_error", {"plan_id": sid, "error": str(e)[:300]}); res.actions.append(f"error:{e}")
            elif sid in self.lead.release_tickets:
                rc = self.latest("release-candidates", sid)
                if rc is not None: self._call("release-engineer", rc, PROD_ROUTE, res)
        self._note_closed()
        self._mark(env, res)
        self._retry_deferred()
        return res

    def _check_escalations(self) -> None:
        """Ticket blocked (retry hết) hoặc bị supervisor escalate → gate `escalation` cho người quyết (checklist gate 'bất thường')."""
        for tid in {*self.lead.blocked(), *(t for t in self.paused if t in self.lead.tickets)}:
            if self.lead.state.get(tid) in DONE_STATES: continue  # đã đóng/đã xong: không mở gate nữa
            # budget_cut cũng là "dừng chờ người" (approve = cấp thêm ngân sách): không có gate thì ticket treo im lặng.
            n = sum(1 for a in self.supervisor.actions if a.target == tid and a.action in {"escalate", "budget_cut"})
            key = f"escalation:{tid}:{n}:{self.lead.state.get(tid)}"  # mỗi lần escalate/cắt mới / blocked mới → một gate mới
            if tid in self.gate.pending or key in self.once: continue
            if self.lead.state.get(tid) == "blocked" or n:
                self._remember(key)
                self.gate.request(GateRequest(kind="escalation", subject_id=tid, created_by="supervisor",
                                              checklist=["root_cause", "decision:reopen|close", "hint"]))

    def _on_escalation_decided(self, tid: str, decision: str, by: str, reason: str, res: StepResult) -> None:
        if tid in self.stalled:  # escalation cấp dự án (chuỗi nghiên cứu lỗi): retry event hoặc đóng dự án
            if decision == "approve":
                self.bus.publish(Envelope(topic="supervisor-actions", key=tid, actor=by,
                                          payload={"target": tid, "action": "resume", "reason": f"escalation approve: {reason}"[:300]}))
                res.actions.append(f"retry:{tid}" if self._retry_stalled(tid, by, reason) else f"retry_failed:{tid}")
            else:
                st = self.stalled.pop(tid, {})
                self._audit("project.closed", {**st, "project_id": tid, "by": by, "reason": reason}, project_id=tid)
                res.actions.append(f"closed:{tid}")
            return
        if decision == "approve":  # mở lại với hint = lý do người duyệt, cấp thêm một ngân sách ticket
            b = self.supervisor.budgets.get(tid); t = self.lead.tickets.get(tid)
            if b and t:
                b.limit = max(b.limit, b.used) + t.budget_tokens
                self._audit("budget.extended", {"ticket_id": tid, "limit": b.limit, "by": by}, ticket_id=tid)
            if self.lead.state.get(tid) in {"blocked", "escalated"}:
                self.lead.reopen(tid, hint=reason or "người duyệt mở lại sau escalation")
            self.bus.publish(Envelope(topic="supervisor-actions", key=tid, actor=by,
                                      payload={"target": tid, "action": "resume", "reason": f"escalation approve: {reason}"[:300]}))
            res.actions.append(f"reopen:{tid}")
        elif decision in {"reject", "rollback"} and tid in self.lead.tickets:
            self.lead.close_escalated(tid); res.actions.append(f"closed:{tid}")
            if self.lead.batch_releases:  # ticket đóng không còn giữ release của các ticket đã approved
                self.lead.flush_releases(self.lead.tickets[tid].project_id)

    # ---------- vòng học ----------

    def _open_acceptance_gate(self, rid: str, res: StepResult) -> None:
        """Sau production: mở gate `acceptance` cho khách ký (ADR-0017). Là gate thật nên có hạn 24h, có nhắc ở 12h
        và được escalate khi quá hạn — trước đây chỉ là một dòng audit `uat.pending` không ai theo dõi."""
        sid = f"UAT-{rid}"
        if sid in self.gate.pending or self.gate.is_approved(sid) or f"uat:{rid}" in self.once: return
        self._remember(f"uat:{rid}")
        self.gate.request(GateRequest(kind="acceptance", subject_id=sid, created_by="account-manager",
                                      checklist=["uat-script", "acceptance-criteria", "known-issues", "signed_by"]))
        res.actions.append(f"gate:acceptance:{sid}")

    def _close_acceptance_gate(self, env: Envelope, res: StepResult) -> None:
        """Khách ký `acceptance-results` → đóng gate nghiệm thu bằng chính chữ ký đó. Four-eyes bảo đảm người ký của
        khách khác account-manager. Conditional đóng ở dạng request_changes; phần còn lại đi qua change request."""
        rid = env.payload.get("release_id"); sid = f"UAT-{rid}"
        if sid not in self.gate.pending: return
        verdict = env.payload.get("verdict")
        decision: Decision = {"accepted": "approve", "rejected": "reject"}.get(str(verdict), "request_changes")  # type: ignore[assignment]
        by = str(env.payload.get("signed_by") or env.actor)
        try:
            self.gate.decide(sid, decision, by=by, reason=f"acceptance-results: {verdict}")
            res.actions.append(f"gate:acceptance:{sid}:{decision}")
        except (KeyError, PermissionError) as e:
            self._audit("handler_error", {"agent": "account-manager", "error": str(e)[:300]})

    def _record_lessons(self, rid: str) -> None:
        """Sau nghiệm thu: estimate vs actual mỗi ticket đã closed → supervisor.knowledge + blackboard `knowledge`."""
        for tid in self.lead.release_tickets.get(rid, []):
            if self.lead.state.get(tid) != "closed" or f"lesson:{tid}" in self.once: continue
            self._remember(f"lesson:{tid}")
            t = self.lead.tickets[tid]; b = self.supervisor.budgets.get(tid)
            actual = b.used if b else 0; est = t.estimate_tokens or 0
            lesson = {"ticket_id": tid, "assignee": t.assignee, "estimate_tokens": est, "actual_tokens": actual,
                      "review_tokens": b.review_used if b else 0,
                      "ratio": round(actual / est, 2) if est else None, "retry": t.retry, "risk_tags": t.risk_tags}
            self.supervisor.record_lesson(context=f"{t.project_id}/{tid} {t.title}", problem=f"retry={t.retry}",
                                          solution=t.hint or "", evidence=json.dumps(lesson, ensure_ascii=False))
            self.blackboard.write("supervisor", "knowledge", f"audit-log:lesson:{tid}", json.dumps(lesson, ensure_ascii=False))

    # ---------- người can thiệp giữa vòng (ADR-0012) ----------

    def comment(self, ticket_id: str, by: str, text: str) -> Task:
        """Nhận xét của người cho ticket đang chạy: ghi audit `human.comment` và phát lại task với hint = nhận xét
        (delivery-lead không tính retry). Ticket blocked/escalated dùng gate escalation."""
        if not by.split(":", 1)[0] == "human": raise ValueError("by phải là human:<tên>")
        t = self.lead.tickets.get(ticket_id)
        if t is None: raise ValueError(f"không có ticket {ticket_id}")
        self._audit("human.comment", {"ticket_id": ticket_id, "by": by, "text": text[:2000], "state": self.lead.state.get(ticket_id)},
                    actor=by, ticket_id=ticket_id, project_id=t.project_id)
        return self.lead.human_hint(ticket_id, text)

    def takeover(self, ticket_id: str, by: str, message: str | None = None) -> Envelope:
        """Người sửa tay trong worktree `ticket/<id>` rồi giao lại: CODE chạy lint/test thật, commit (nếu còn thay đổi chưa
        commit), publish `pull-requests` dưới tên người với `local_checks.verified_by=workspace`; reviewer/QA/security review
        như PR của agent. Ticket đang `in_review` thì PR này thay PR của agent (vòng review làm lại)."""
        if not by.split(":", 1)[0] == "human": raise ValueError("by phải là human:<tên>")
        t = self.lead.tickets.get(ticket_id); st = self.lead.state.get(ticket_id)
        if t is None: raise ValueError(f"không có ticket {ticket_id}")
        if st not in {"dispatched", "in_progress", "in_review"}:
            raise ValueError(f"{ticket_id}: chỉ tiếp quản ticket dispatched/in_review (đang {st})")
        ws = self.workspace(ticket_id)
        if ws is None or not ws.path.exists():
            raise ValueError(f"{ticket_id}: không có worktree (cần --repo; worktree ở <repo>/.worktrees/{ticket_id})")
        if not ws.has_changes(): raise ValueError(f"{ticket_id}: worktree không có thay đổi so với nhánh tích hợp")
        checks = ws.run_checks()
        sha = ws.commit_all(message or f"feat({ticket_id}): {by} tiếp quản — {t.title}"[:72]) if _git(ws.path, "status", "--porcelain") \
            else _git(ws.path, "rev-parse", "--short", "HEAD")
        files = ws.changed_files()
        p = {"ticket_id": ticket_id, "branch": ws.branch, "pr_ref": sha, "summary": message or f"{by} tiếp quản ticket",
             "impact": {"files": files}, "local_checks": {**checks, "verified_by": "workspace"}}
        self._audit("human.takeover", {"ticket_id": ticket_id, "by": by, "commit": sha, "files": files,
                                       "lint": checks["lint"], "tests": checks["tests"]}, actor=by, ticket_id=ticket_id, project_id=t.project_id)
        return self.bus.publish(Envelope(topic="pull-requests", key=ticket_id, actor=by, payload=p))

    # ---------- hoãn / đánh dấu / audit ----------

    def _defer(self, env: Envelope, res: StepResult, reason: str) -> StepResult:
        with self._lock:
            self.deferred[env.event_id] = (env, reason); res.deferred = reason; self.stats["deferred"] += 1
        return res

    def _retry_deferred(self, only: str | None = None) -> None:
        """Đưa event hoãn về đầu hàng đợi; `only` = tiền tố lý do (vd. "transient:") để chỉ thử lại loại đó."""
        with self._lock, self._qlock:
            picked = {k: v for k, v in self.deferred.items() if only is None or v[1].startswith(only)}
            for k in picked: self.deferred.pop(k)
            self.queue[:0] = [e for e, _ in picked.values()]

    def _mark(self, env: Envelope, res: StepResult) -> None:
        with self._lock:
            self.processed.add(env.event_id); self.partial.pop(env.event_id, None)
        self._audit("orchestrated", {"event_id": env.event_id, "topic": env.topic, "actions": res.actions},
                    ticket_id=env.payload.get("ticket_id") or (env.key if env.topic == "tasks" else None),
                    project_id=env.payload.get("project_id"))

    def _remember(self, key: str) -> None:
        """Ghi nhớ bền vững một việc chỉ làm một lần (khôi phục qua replay)."""
        with self._lock: self.once.add(key)
        self._audit("once", {"key": key})

    def _audit(self, action: str, data: dict[str, Any], actor: str = ACTOR, tokens: int = 0, once: str | None = None,
               ticket_id: str | None = None, project_id: str | None = None, cost: float = 0.0) -> None:
        if once:
            with self._lock:
                if once in self.once: return
                self.once.add(once)
            self._audit("once", {"key": once})
        a = AuditLog(actor=actor, action=action, tokens=tokens, ticket_id=ticket_id, project_id=project_id,
                     evidence=json.dumps(data, ensure_ascii=False), cost_usd=cost)
        self.bus.publish(Envelope(topic="audit-log", key=actor, actor=actor, payload=a.model_dump()))

    def _integration_status(self) -> dict[str, str] | None:
        if self.integration is None or self.repo is None: return None
        if not (self.repo / ".worktrees" / "_integration").exists(): return None
        return {"branch": self.integration.branch, "sha": self.integration.sha()}

    def status(self) -> dict[str, Any]:
        return {"queue": len(self.queue), "deferred": {k: v[1] for k, v in self.deferred.items()},
                "paused": sorted(self.paused), "tickets": dict(self.lead.state), "waiting": self.lead.waiting(),
                "blocked": self.lead.blocked(), "releases": self.lead.releases,
                "stalled": {pid: f"{st['agent']} lỗi trên {st['topic']}: {st['error'][:120]}" for pid, st in self.stalled.items()},
                "gates_pending": {sid: g.kind for sid, g in self.gate.pending.items()}, "plans": list(self.plans),
                "blackboard": {key: {"v": sc.version, "ref": sc.content_ref, "chars": len(sc.content or ""),
                                     "file": str(p) if (p := self.blackboard.path(sc.namespace,
                                                                                  project_id=sc.project_id)) else None}
                               for key, sc in self.blackboard.all().items()},
                "workers": self.workers, "web": self.web is not None,
                "cost_usd": self.supervisor.sprint_report()["cost_usd_total"],
                "integration": self._integration_status(), "void_releases": sorted(self.void_releases),
                "stats": dict(self.stats), "events": len(self.bus)}


def _cycle(graph: dict[str, list[str]]) -> list[str]:
    """Một chu trình trong đồ thị phụ thuộc (rỗng nếu không có) — bắt ở bước lập kế hoạch, trước gate, không để tới dispatch."""
    state: dict[str, int] = {}; stack: list[str] = []
    def visit(n: str) -> list[str]:
        state[n] = 1; stack.append(n)
        for m in graph.get(n, []):
            if state.get(m) == 1: return [*stack[stack.index(m):], m]
            if m not in state and (c := visit(m)): return c
        stack.pop(); state[n] = 2; return []
    for n in graph:
        if n not in state and (c := visit(n)): return c
    return []


def _evidence(a: dict[str, Any]) -> dict[str, Any]:
    try:
        d = json.loads(a.get("evidence") or "{}")
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def _fmt(r: StepResult) -> str:
    tail = f"  hoãn: {r.deferred}" if r.deferred else "  " + "; ".join(r.actions)
    return f"{r.topic:<22} {r.key:<14}{tail}"


def main(argv: list[str] | None = None) -> int:
    """python -m company.orchestrator run [--db] [--max-steps N] [--watch GIÂY] [--workers N] [--web]
       python -m company.orchestrator publish <topic> <file.json> --actor human:po [--key K]
       python -m company.orchestrator decide-change <change_id> accepted|rejected|deferred --by human:po
       python -m company.orchestrator comment <ticket> --by human:x --text "..."   # hint giữa vòng, không tính retry
       python -m company.orchestrator takeover <ticket> --by human:x [--message]   # người sửa tay trong worktree rồi giao lại
       python -m company.orchestrator status | report | metrics [--prometheus] | show <namespace> [--db]"""
    ap = argparse.ArgumentParser(description="Orchestrator: vòng lặp tự động topic → agent → topic")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    ap.add_argument("--repo", type=Path, help="git repo của khách: khối kỹ thuật sửa code thật trong worktree ticket/<id>")
    ap.add_argument("--base", default="HEAD", help="nhánh/commit gốc để tạo nhánh tích hợp lần đầu (mặc định HEAD)")
    ap.add_argument("--integration", default="company/integration", help="nhánh tích hợp: ticket rẽ từ đây, merge vào đây")
    ap.add_argument("--artifacts", type=Path, help="artifact store của blackboard (mặc định <db>.artifacts/)")
    ap.add_argument("--workers", type=int, default=1, help="số event khác key chạy song song (mặc định 1)")
    ap.add_argument("--web", action="store_true", help="cho researcher tool web_search/fetch_url (mạng ra ngoài)")
    ap.add_argument("--batch-release", action="store_true",
                    help="gom mọi ticket approved của dự án vào một RC khi không còn ticket đang chạy (mặc định: mỗi ticket một RC)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run"); rn.add_argument("--max-steps", type=int); rn.add_argument("--watch", type=float,
        help="chạy liên tục, mỗi N giây nạp event mới (gate CLI, publish) rồi xử lý")
    pb = sub.add_parser("publish"); pb.add_argument("topic"); pb.add_argument("file", type=Path)
    pb.add_argument("--actor", required=True); pb.add_argument("--key")
    dc = sub.add_parser("decide-change", help="khách quyết định change request (sau khi delivery-lead ước lượng impact)")
    dc.add_argument("change_id"); dc.add_argument("decision", choices=["accepted", "rejected", "deferred"])
    dc.add_argument("--by", required=True); dc.add_argument("--reason", default="")
    cm = sub.add_parser("comment", help="người nhận xét ticket đang chạy: phát lại task với hint, không tính retry")
    cm.add_argument("ticket_id"); cm.add_argument("--by", required=True); cm.add_argument("--text", required=True)
    tk = sub.add_parser("takeover", help="người đã sửa tay trong worktree ticket: chạy lint/test, commit, publish PR dưới tên người")
    tk.add_argument("ticket_id"); tk.add_argument("--by", required=True); tk.add_argument("--message")
    sub.add_parser("status"); sub.add_parser("report", help="sprint report: estimate vs actual, chi phí, hành động supervisor")
    mt = sub.add_parser("metrics", help="metrics từ audit-log: gọi/token/USD/thời gian theo agent, model, ticket; gate chờ")
    mt.add_argument("--prometheus", action="store_true", help="xuất text exposition format cho Prometheus")
    sh = sub.add_parser("show", help="in toàn văn artifact mới nhất của một namespace blackboard"); sh.add_argument("namespace")
    sh.add_argument("--project", help="dự án của artifact (ADR-0018); bỏ qua nếu chỉ có một dự án dùng namespace đó")
    ns = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows console cp1252
        if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8")
    from .sqlite_bus import SQLiteBus
    bus = SQLiteBus(ns.db)
    if ns.cmd == "publish":
        payload = json.loads(ns.file.read_text(encoding="utf-8"))
        key = ns.key or payload.get("ticket_id") or payload.get("release_id") or payload.get("project_id") or payload.get("change_id")
        if not key: print("cần --key", file=sys.stderr); return 2
        env = bus.publish(Envelope(topic=ns.topic, key=key, actor=ns.actor, payload=payload))
        print(f"published {env.topic} key={env.key} event={env.event_id}"); return 0
    if ns.cmd == "decide-change":
        cr = next(reversed(list(bus.replay(topic="change-requests", key=ns.change_id))), None)
        if cr is None: print(f"không có change-request {ns.change_id}", file=sys.stderr); return 2
        impact = next((_evidence(e.payload) for e in reversed(list(bus.replay(topic="audit-log")))
                       if e.payload.get("action") == "change.impact" and _evidence(e.payload).get("change_id") == ns.change_id), {})
        payload = {**cr.payload, "decision": ns.decision, "impact": {**cr.payload.get("impact", {}), **impact.get("impact", {}),
                                                                       "decided_by": ns.by, "reason": ns.reason}}
        env = bus.publish(Envelope(topic="change-requests", key=ns.change_id, actor=ns.by, payload=payload))
        print(f"{ns.change_id}: {ns.decision} by {ns.by} event={env.event_id}"); return 0
    if ns.cmd == "metrics":
        from .metrics import collect, prometheus
        m = collect(bus)
        print(prometheus(m) if ns.prometheus else json.dumps(m, ensure_ascii=False, indent=2)); return 0
    from .llm import FakeClient, make_client
    # Chỉ `run` gọi model; status/report/show/comment/takeover là việc của người và của code, không được đòi SDK/API key.
    orch = Orchestrator(bus, make_client() if ns.cmd == "run" else FakeClient(), repo=ns.repo, base=ns.base, integration=ns.integration, workers=ns.workers,
                        web=ns.web, batch_releases=ns.batch_release, artifacts=ns.artifacts or artifact_store(ns.db))
    if ns.cmd == "status":
        print(json.dumps(orch.status(), ensure_ascii=False, indent=2)); return 0
    if ns.cmd == "report":
        print(json.dumps(orch.supervisor.sprint_report(), ensure_ascii=False, indent=2)); return 0
    if ns.cmd == "show":
        sc = orch.blackboard.read(ns.namespace, ns.project)
        if sc is None and ns.project is None:
            # Blackboard phân vùng theo dự án: không nêu --project thì chỉ đoán được khi đúng một dự án có namespace này.
            found = [c for (pid, nsp), c in orch.blackboard._latest.items() if nsp == ns.namespace]
            if len(found) == 1: sc = found[0]
            elif len(found) > 1:
                projects = ", ".join(sorted(str(c.project_id) for c in found))
                print(f"{ns.namespace} có ở nhiều dự án ({projects}); nêu --project", file=sys.stderr); return 2
        if sc is None: print(f"chưa có namespace {ns.namespace}", file=sys.stderr); return 2
        scope = f" [{sc.project_id}]" if sc.project_id else ""
        print(f"# {ns.namespace} v{sc.version}{scope} — {sc.content_ref}\n# {sc.summary}\n")
        print(sc.content if sc.content is not None else "(chỉ có con trỏ, không có toàn văn)"); return 0
    if ns.cmd in {"comment", "takeover"}:
        try:
            if ns.cmd == "comment":
                t = orch.comment(ns.ticket_id, ns.by, ns.text); print(f"{t.ticket_id}: phát lại với hint (retry={t.retry})")
            else:
                env = orch.takeover(ns.ticket_id, ns.by, ns.message)
                print(f"{env.key}: PR {env.payload['pr_ref']} của {ns.by}, lint={env.payload['local_checks']['lint']} "
                      f"tests={env.payload['local_checks']['tests']} event={env.event_id}")
        except (ValueError, WorkspaceError) as e:
            print(str(e), file=sys.stderr); return 2
        return 0
    if ns.watch:
        try: orch.watch(interval=ns.watch)
        except KeyboardInterrupt: pass
    else:
        for r in orch.tick() if ns.max_steps is None else orch.run(ns.max_steps): print(_fmt(r))
    print(json.dumps(orch.status(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
