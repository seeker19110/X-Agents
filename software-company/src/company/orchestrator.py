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
delivery-lead/supervisor/gate dựng lại từ replay. Không retry lời gọi model: lỗi ghi audit rồi đi tiếp.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable
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
from .llm import LLMError, ModelClient
from .registry import AgentSpec, load_agents
from .runner import CONTEXT_ONLY, AgentRunner, RunnerError
from .supervisor import Supervisor
from .tools import WorkspaceTools
from .workspace import Integration, TicketWorkspace, WorkspaceError

ACTOR = "orchestrator"
ENGINEERING = ("backend", "frontend", "mobile", "database", "platform", "data")
PAUSING = frozenset({"pause", "budget_cut", "escalate"})
CONTROL_TOPICS = frozenset({"audit-log", "shared-context", "supervisor-actions"})
MAX_CLARIFY_ROUNDS = 2  # khớp `clarification-questions.round` (maximum 2) và prompt clarifier
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
    tools: str | None = None  # "rw": sửa code trong worktree (khối kỹ thuật); "ro": chỉ đọc + chạy test (QA). Cần repo.

    def agents(self) -> tuple[str, ...]:
        return ENGINEERING if self.agent == "$assignee" else (self.agent,)


def _from(*actors: str) -> When:
    return lambda e, _o: e.actor in actors


def _field(name: str, *values: Any) -> When:
    return lambda e, _o: e.payload.get(name) in values


def _needs_security(e: Envelope, o: Orchestrator) -> bool:
    tid = e.payload.get("ticket_id") or e.key
    return tid in o.lead.tickets and "security" in o.lead.required_reviews(tid)


def _release_needs_security(e: Envelope, o: Orchestrator) -> bool:
    return o.lead.release_needs_security(e.payload["release_id"])


def _deployed(env_name: str) -> When:
    return lambda e, _o: e.payload.get("env") == env_name and e.payload.get("status") == "deployed"


def _answers_complete(e: Envelope, o: Orchestrator) -> bool:
    """Người đã trả lời hết câu hỏi của vòng gần nhất (hoặc clarifier đã hết vòng) → đi thẳng spec-writer."""
    q = o.latest("clarification-questions", e.payload.get("project_id") or e.key)
    if q is None: return True
    asked = {str(x.get("id")) for x in q.payload.get("questions", [])}
    answered = {str(a.get("question_id")) for a in e.payload.get("answers", [])}
    return not (asked - answered) or int(q.payload.get("round", 1)) >= MAX_CLARIFY_ROUNDS


def _answers_incomplete(e: Envelope, o: Orchestrator) -> bool:
    return not _answers_complete(e, o)


def _cr_accepted_needs_research(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("decision") == "accepted" and bool(e.payload.get("affects_requirements"))


def _cr_accepted_direct(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("decision") == "accepted" and not e.payload.get("affects_requirements")


def _with_draft(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    d = o.latest("requirements-draft", e.payload.get("project_id") or e.key)
    return {"requirements_draft": d.payload} if d else {}


def _with_diff(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """Reviewer/QA/security đọc diff thật của branch ticket (khi có repo) thay vì tin `summary` của PR."""
    ws = o.workspace(e.payload.get("ticket_id") or e.key)
    if ws is None or not ws.path.exists(): return {}
    try: return {"diff": ws.diff(), "changed_files": ws.changed_files()}
    except WorkspaceError as ex: return {"diff_error": str(ex)[:300]}


ROUTES: tuple[Route, ...] = (
    # khối nghiên cứu: intake → researcher → synthesizer → risk → clarifier → (người trả lời) → spec-writer
    Route("research-requests", "intake", "research-findings"),
    Route("research-findings", "researcher", "research-findings", _from("intake")),
    Route("research-findings", "synthesizer", "requirements-draft", _from("researcher")),
    Route("requirements-draft", "risk", "requirements-draft", _from("synthesizer")),
    Route("requirements-draft", "clarifier", "clarification-questions", _from("risk")),
    # người trả lời thiếu và chưa hết vòng → clarifier hỏi lại đúng phần thiếu; đủ (hoặc hết vòng) → spec-writer
    Route("clarification-answers", "clarifier", "clarification-questions", _answers_incomplete, enrich=_with_draft),
    Route("clarification-answers", "spec-writer", "approved-specs", _answers_complete, enrich=_with_draft),
    # kỹ thuật + chất lượng
    Route("tasks", "$assignee", "pull-requests", tools="rw"),
    Route("pull-requests", "reviewer", "review-results", enrich=_with_diff),
    Route("pull-requests", "qa-debugger", "review-results", enrich=_with_diff, tools="ro"),
    Route("pull-requests", "security-engineer", "review-results", _needs_security, enrich=_with_diff),
    # vận hành: RC → staging (+ security DAST/license khi có risk) → QA hồi quy; production đi qua gate 3 (PROD_ROUTE)
    Route("release-candidates", "release-engineer", "release-events", target_env="staging"),
    Route("release-candidates", "security-engineer", "review-results", _release_needs_security),
    Route("release-events", "qa-debugger", "review-results", _deployed("staging")),
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
    deferred: str | None = None  # lý do hoãn (gate:..., paused:...)


class Orchestrator:
    def __init__(self, bus: InMemoryBus, client: ModelClient, agents: dict[str, AgentSpec] | None = None,
                 max_retries: int = 3, repo: Path | None = None, base: str = "HEAD", max_turns: int = 25,
                 integration: str = "company/integration", project_budget_tokens: int | None = None):
        self.bus = bus
        self.repo, self.max_turns = (Path(repo) if repo else None), max_turns
        if self.repo is not None and not (self.repo / ".git").exists():
            raise ValueError(f"repo không phải git repository: {self.repo}")
        self.integration = Integration(self.repo, integration, base) if self.repo is not None else None
        self.void_releases: set[str] = set()
        self.missing_threat_model: set[str] = set()  # spec chưa có threat model vì security-engineer lỗi
        self.agents = agents or load_agents()
        bad = check_routes(self.agents)
        if bad: raise ValueError("ROUTES lệch front matter: " + "; ".join(bad))
        self.blackboard = Blackboard(bus)
        self.gate = PersistentGate(bus)
        self.lead = DeliveryLead(bus, self.gate, max_retries=max_retries)
        self.supervisor = Supervisor(bus, max_retries=max_retries, project_budget_tokens=project_budget_tokens)
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
        for env in self.bus.replay():
            if env.topic == "audit-log":
                a = env.payload; d = _evidence(a)
                if a["actor"] == ACTOR and a["action"] == "orchestrated": self.processed.add(d["event_id"])
                elif a["actor"] == ACTOR and a["action"] == "once": self.once.add(d["key"])
                elif a["action"] == "plan.proposed": self.plans[d["plan_id"]] = d
                elif a["action"] == "release.void": self.void_releases.add(d["release_id"])
                elif a["action"] == "threat_model.missing": self.missing_threat_model.add(d["subject_id"])
                elif a["action"] == "gate.decide" and d.get("decision") == "approve" and d["subject_id"] in self.plans:
                    self._dispatch_plan(d["subject_id"], replaying=True)
            elif env.topic == "supervisor-actions": self._track_pause(env)
            elif env.topic == "shared-context": self.blackboard._on(env)
            else: self.lead.replay(env)
            self.supervisor.replay(env)
        self.queue = [e for e in self.bus.replay() if self._actionable(e) and e.event_id not in self.processed]

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
            self.queue.append(env)

    def latest(self, topic: str, key: str) -> Envelope | None:
        return next(reversed(list(self.bus.replay(topic=topic, key=key))), None)

    def workspace(self, ticket_id: str) -> TicketWorkspace | None:
        """Worktree của ticket, rẽ từ nhánh tích hợp (tạo nhánh tích hợp nếu chưa có)."""
        if self.repo is None or self.integration is None: return None
        self.integration.ensure()
        return TicketWorkspace(self.repo, ticket_id, base=self.integration.branch)

    # ---------- vòng lặp ----------

    def run(self, max_steps: int | None = None) -> list[StepResult]:
        """Xử lý hàng đợi đến khi rỗng (hoặc đủ max_steps). Event bị hoãn không làm vòng lặp quay mãi."""
        out: list[StepResult] = []
        while self.queue and (max_steps is None or len(out) < max_steps):
            env = self.queue.pop(0)
            r = self.process(env)
            if r is not None: out.append(r)
            self._check_escalations()
        return out

    def tick(self, now: datetime | None = None) -> list[StepResult]:
        """Một nhịp của chế độ watch: nạp event từ tiến trình khác, chạy hàng đợi, nhắc gate quá hạn, giao lại review
        quá hạn, escalate ticket im lặng quá lâu."""
        if hasattr(self.bus, "poll"): self.bus.poll()
        results = self.run()
        remind, overdue = self.gate.due(now)
        for sid in [*remind, *overdue]:
            self._audit(f"gate.{'overdue' if sid in overdue else 'remind'}", {"subject_id": sid}, once=f"gate:{sid}")
        for sid in overdue:  # quá hạn không tự đi tiếp, nhưng cũng không im lặng: supervisor nhận việc
            self.supervisor.escalate_gate(sid, f"gate quá hạn {self.gate.timeout}", once_key=f"gate.escalate:{sid}")
        for tid, missing in self.lead.overdue_reviews(now).items():
            pr = self.latest("pull-requests", tid)
            for src in sorted(missing):
                key = f"review:{tid}:{src}:{self.lead.review_since[tid].isoformat()}"
                if pr is None or key in self.once: continue
                self._remember(key); self._audit("review.reassign", {"ticket_id": tid, "source": src}, ticket_id=tid)
                res = StepResult(pr.event_id, pr.topic, pr.key)
                self._call(REVIEW_AGENT[src], pr, Route("pull-requests", REVIEW_AGENT[src], "review-results"), res)
                results.append(res)
        active = {tid for tid, st in self.lead.state.items() if st in ACTIVE_STATES}
        self.supervisor.check_timeouts(now, active=active)
        results += self.run()
        return results

    def watch(self, interval: float = 5.0, max_ticks: int | None = None) -> None:
        n = 0
        while max_ticks is None or n < max_ticks:
            for r in self.tick(): print(_fmt(r))
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
        if env.topic in PLAN_INPUTS and PLAN_INPUTS[env.topic](env, self):
            return self._plan(env, res)
        if env.topic == "release-candidates" and not self._integrate(env, res):
            self._mark(env, res); return res  # RC huỷ vì xung đột: ticket đã được giao lại, không deploy
        if env.topic == "clarification-questions" and not env.payload.get("questions"):
            # clarifier không còn câu hỏi (hoặc quá round 2 → assumption): spec-writer đi thẳng từ draft sau risk
            draft = self.latest("requirements-draft", env.key)
            if draft is not None:
                self._call("spec-writer", draft, Route("requirements-draft", "spec-writer", "approved-specs"), res)
        for r in ROUTES:
            if r.topic_in != env.topic or (r.when and not r.when(env, self)): continue
            agent = env.payload["assignee"] if r.agent == "$assignee" else r.agent
            self._call(agent, env, r, res)
        if env.topic == "release-events" and _deployed("production")(env, self):
            self._open_acceptance_gate(env.key, res)
        if env.topic == "acceptance-results":
            self._close_acceptance_gate(env, res)
            self._record_lessons(env.payload["release_id"])
        self._mark(env, res)
        return res

    def project_of(self, env: Envelope) -> str | None:
        """Dự án của một event, kể cả khi payload không mang `project_id` (release-events, review-results...):
        tra ngược qua ticket hoặc release. Blackboard phân vùng theo giá trị này (ADR-0012)."""
        if env.payload.get("project_id"): return str(env.payload["project_id"])
        tid = env.payload.get("ticket_id") or (env.key if env.topic in {"tasks", "pull-requests"} else None)
        if tid and tid in self.lead.tickets: return self.lead.tickets[tid].project_id
        rid = env.payload.get("release_id") or (env.key if env.topic in {"release-events", "release-candidates"} else None)
        for t in self.lead.release_tickets.get(str(rid), []):
            if t in self.lead.tickets: return self.lead.tickets[t].project_id
        return None

    def _call(self, agent: str, env: Envelope, r: Route, res: StepResult) -> None:
        try:
            extra = {**(r.enrich(env, self) if r.enrich else {})}
            if not env.payload.get("project_id") and (pid := self.project_of(env)): extra["project_id"] = pid
            inp = env.model_copy(update={"payload": {**env.payload, **extra}}) if extra else env
            if r.target_env:
                out = self._release(agent, env, r); res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            elif r.tools == "rw":
                out = self._engineer(agent, inp, r); res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            elif r.topic_out == CONTEXT_ONLY:
                g = self.runner.run_context(agent, inp)
                res.actions.append(f"{agent}→blackboard:{','.join(w['namespace'] for w in g.context_writes) or '-'}")
            elif r.many:
                g = self.runner.generate(agent, inp, r.topic_out, many=True)
                if g.context_writes: self.runner.write_context(agent, env, g.context_writes)
                for p in g.payloads:
                    self.runner.publish(agent, env, r.topic_out, p, key=key_for(r.topic_out, p, env.key), tokens=g.tokens, model=g.model)
                if not g.payloads: self._audit("produced:nothing", {"agent": agent, "topic": r.topic_out}, actor=agent, tokens=g.tokens)
                res.actions.append(f"{agent}→{r.topic_out}×{len(g.payloads)}")
            else:
                tools = None
                if r.tools == "ro" and (ws := self.workspace(inp.payload.get("ticket_id") or inp.key)) and ws.path.exists():
                    tools = WorkspaceTools(ws, allow_write=False).toolbox()
                g = self.runner.generate(agent, inp, r.topic_out, tools=tools, max_turns=self.max_turns)
                out = self.runner.publish(agent, env, r.topic_out, g.payloads[0], key=key_for(r.topic_out, g.payloads[0], env.key),
                                          tokens=g.tokens, model=g.model, context_writes=g.context_writes)
                res.actions.append(f"{agent}→{r.topic_out}:{out.key}")
            self.stats["runs"] += 1
        except (RunnerError, LLMError) as e:  # runner đã ghi audit; không retry (ADR-0005)
            res.actions.append(f"error:{agent}:{str(e)[:120]}"); self.stats["errors"] += 1
        except Exception as e:  # handler xác định (delivery-lead) từ chối chuyển trạng thái: event đã ghi đĩa
            self._audit("handler_error", {"agent": agent, "error": str(e)[:300]}, ticket_id=env.payload.get("ticket_id"))
            res.actions.append(f"handler_error:{agent}:{str(e)[:120]}"); self.stats["errors"] += 1

    def _integrate(self, rc: Envelope, res: StepResult) -> bool:
        """Merge branch ticket của RC vào nhánh tích hợp. Trả về False nếu RC bị huỷ (xung đột hoặc branch thiếu)."""
        if self.integration is None: return True
        rid = rc.payload["release_id"]
        if rid in self.void_releases: return False
        for tid in rc.payload.get("tickets", []):
            ws = self.workspace(tid)
            if ws is None or not ws.path.exists():
                self._audit("integration.skipped", {"release_id": rid, "ticket_id": tid, "reason": "không có worktree"}, ticket_id=tid)
                continue
            t = self.lead.tickets.get(tid)
            m = self.integration.merge(ws.branch, f"merge({tid}): {t.title if t else tid}\n\nrelease: {rid}")
            if m.ok:
                self._audit("integration.merged", {"release_id": rid, "ticket_id": tid, "sha": m.sha, "branch": self.integration.branch}, ticket_id=tid)
                res.actions.append(f"integrated:{tid}@{m.sha}"); continue
            hint = f"xung đột với nhánh tích hợp {self.integration.branch} ở: {', '.join(m.conflicts or [])}. Làm lại trên nền mới."
            self._audit("release.void", {"release_id": rid, "ticket_id": tid, "conflicts": m.conflicts}, ticket_id=tid)
            self.void_releases.add(rid)
            try:
                ws.fresh()
                self.lead.request_changes(tid, hint)
            except (ValueError, WorkspaceError) as e:
                self._audit("handler_error", {"agent": "delivery-lead", "error": str(e)[:300]}, ticket_id=tid)
            res.actions.append(f"conflict:{tid}"); self.stats["conflicts"] += 1
            return False
        return True

    def _engineer(self, agent: str, task: Envelope, r: Route) -> Envelope:
        """Ticket → PR. Có repo: agent làm trong worktree, bằng chứng do code điền. Không repo: PR đi tiếp nhưng
        `local_checks` của model bị thay bằng `{"unverified": true}` và ghi audit — không có bằng chứng giả."""
        tid = task.payload.get("ticket_id") or task.key
        budget = self.lead.tickets[tid].budget_tokens if tid in self.lead.tickets else task.payload.get("budget_tokens")
        ws = self.workspace(tid)
        if ws is not None:
            g = self.runner.generate_in_workspace(agent, task, ws, budget=budget, max_turns=self.max_turns)
            p = g.payloads[0]
        else:
            g = self.runner.generate(agent, task, r.topic_out)
            p = {**g.payloads[0], "local_checks": {"unverified": True}}
            self._audit("local_checks.unverified", {"ticket_id": tid, "agent": agent, "claimed": g.payloads[0].get("local_checks")},
                        actor=agent, ticket_id=tid)
        return self.runner.publish(agent, task, r.topic_out, p, key=key_for(r.topic_out, p, task.key),
                                   tokens=g.tokens, model=g.model, context_writes=g.context_writes)

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
        return self.runner.publish(agent, rc, r.topic_out, p, key=rid, tokens=g.tokens, model=g.model)

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
        cal = self.supervisor.calibration()  # vòng học: bài học estimate-vs-actual quay lại người ước lượng
        inp = env.model_copy(update={"payload": {**env.payload, "estimate_calibration": cal}}) if cal else env
        try:
            g = self.runner.generate("delivery-lead", inp, "tasks", many=True)
        except (RunnerError, LLMError) as e:
            res.actions.append(f"error:delivery-lead:{str(e)[:120]}"); self.stats["errors"] += 1
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
            self._audit("plan_rejected", plan, actor="delivery-lead", tokens=g.tokens, project_id=project)
            res.actions.append(f"plan_rejected:{'; '.join(problems)[:120]}"); self.stats["errors"] += 1
        else:
            self.plans[plan_id] = plan
            self._audit("plan.proposed", plan, actor="delivery-lead", tokens=g.tokens, project_id=project)
            self.gate.request(GateRequest(kind="plan", subject_id=plan_id, created_by="delivery-lead",
                                          checklist=["tickets", "estimate_tokens", "risk_tags", "depends_on", "threat-model",
                                                     "architecture", "api-contract"]))
            res.actions.append(f"plan:{plan_id}:{len(tickets)} ticket"); self.stats["plans"] += 1
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
                                context_writes=g.context_writes)
            self.stats["runs"] += 1
        except (RunnerError, LLMError) as e:
            # Không chặn kế hoạch (người duyệt gate plan vẫn quyết được), nhưng phải hiện ra: audit riêng +
            # ghi vào chính plan để checklist `threat-model` ở gate không bị tick nhầm là đã có.
            self._audit("threat_model.missing", {"subject_id": sid, "error": str(e)[:300]},
                        project_id=env.payload.get("project_id"))
            self.missing_threat_model.add(sid)
            res.actions.append(f"error:security-engineer:{str(e)[:120]}"); self.stats["errors"] += 1
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
        self._mark(env, res)
        self._retry_deferred()
        return res

    def _check_escalations(self) -> None:
        """Ticket blocked (retry hết) hoặc bị supervisor escalate → gate `escalation` cho người quyết (checklist gate 'bất thường')."""
        for tid in {*self.lead.blocked(), *(t for t in self.paused if t in self.lead.tickets)}:
            if self.lead.state.get(tid) in DONE_STATES: continue  # đã đóng/đã xong: không mở gate nữa
            n = sum(1 for a in self.supervisor.actions if a.target == tid and a.action == "escalate")
            key = f"escalation:{tid}:{n}:{self.lead.state.get(tid)}"  # mỗi lần escalate mới / blocked mới → một gate mới
            if tid in self.gate.pending or key in self.once: continue
            if self.lead.state.get(tid) == "blocked" or n:
                self._remember(key)
                self.gate.request(GateRequest(kind="escalation", subject_id=tid, created_by="supervisor",
                                              checklist=["root_cause", "decision:reopen|close", "hint"]))

    def _on_escalation_decided(self, tid: str, decision: str, by: str, reason: str, res: StepResult) -> None:
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

    # ---------- gate 4: nghiệm thu của khách ----------

    def _open_acceptance_gate(self, rid: str, res: StepResult) -> None:
        """Sau production: mở gate `acceptance` cho khách ký. Là gate thật nên có hạn 24h, có nhắc ở 12h và
        được escalate khi quá hạn — trước đây chỉ là một dòng audit `uat.pending` không ai theo dõi."""
        sid = f"UAT-{rid}"
        if sid in self.gate.pending or self.gate.is_approved(sid) or f"uat:{rid}" in self.once: return
        self._remember(f"uat:{rid}")
        self.gate.request(GateRequest(kind="acceptance", subject_id=sid, created_by="account-manager",
                                      checklist=["uat-script", "acceptance-criteria", "known-issues", "signed_by"]))
        res.actions.append(f"gate:acceptance:{sid}")

    def _close_acceptance_gate(self, env: Envelope, res: StepResult) -> None:
        """Khách ký `acceptance-results` → đóng gate nghiệm thu bằng chính chữ ký đó (four-eyes: người ký của khách
        khác account-manager). Conditional coi như chưa duyệt: gate đóng nhưng phần còn lại đi qua change request."""
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

    # ---------- vòng học ----------

    def _record_lessons(self, rid: str) -> None:
        """Sau nghiệm thu: estimate vs actual mỗi ticket đã closed → supervisor.knowledge + blackboard `knowledge`."""
        for tid in self.lead.release_tickets.get(rid, []):
            if self.lead.state.get(tid) != "closed" or f"lesson:{tid}" in self.once: continue
            self._remember(f"lesson:{tid}")
            t = self.lead.tickets[tid]; b = self.supervisor.budgets.get(tid)
            actual = b.used if b else 0; est = t.estimate_tokens or 0
            lesson = {"ticket_id": tid, "assignee": t.assignee, "estimate_tokens": est, "actual_tokens": actual,
                      "ratio": round(actual / est, 2) if est else None, "retry": t.retry, "risk_tags": t.risk_tags}
            self.supervisor.record_lesson(context=f"{t.project_id}/{tid} {t.title}", problem=f"retry={t.retry}",
                                          solution=t.hint or "", evidence=json.dumps(lesson, ensure_ascii=False))
            self.blackboard.write("supervisor", "knowledge", f"audit-log:lesson:{tid}", json.dumps(lesson, ensure_ascii=False))

    # ---------- hoãn / đánh dấu / audit ----------

    def _defer(self, env: Envelope, res: StepResult, reason: str) -> StepResult:
        self.deferred[env.event_id] = (env, reason); res.deferred = reason; self.stats["deferred"] += 1
        return res

    def _retry_deferred(self) -> None:
        items = list(self.deferred.values()); self.deferred.clear()
        self.queue[:0] = [e for e, _ in items]

    def _mark(self, env: Envelope, res: StepResult) -> None:
        self.processed.add(env.event_id)
        self._audit("orchestrated", {"event_id": env.event_id, "topic": env.topic, "actions": res.actions},
                    ticket_id=env.payload.get("ticket_id") or (env.key if env.topic == "tasks" else None),
                    project_id=env.payload.get("project_id"))

    def _remember(self, key: str) -> None:
        """Ghi nhớ bền vững một việc chỉ làm một lần (khôi phục qua replay)."""
        self.once.add(key); self._audit("once", {"key": key})

    def _audit(self, action: str, data: dict[str, Any], actor: str = ACTOR, tokens: int = 0, once: str | None = None,
               ticket_id: str | None = None, project_id: str | None = None) -> None:
        if once:
            if once in self.once: return
            self._remember(once)
        a = AuditLog(actor=actor, action=action, tokens=tokens, ticket_id=ticket_id, project_id=project_id,
                     evidence=json.dumps(data, ensure_ascii=False))
        self.bus.publish(Envelope(topic="audit-log", key=actor, actor=actor, payload=a.model_dump()))

    def _integration_status(self) -> dict[str, str] | None:
        if self.integration is None or self.repo is None: return None
        if not (self.repo / ".worktrees" / "_integration").exists(): return None
        return {"branch": self.integration.branch, "sha": self.integration.sha()}

    def status(self) -> dict[str, Any]:
        return {"queue": len(self.queue), "deferred": {k: v[1] for k, v in self.deferred.items()},
                "paused": sorted(self.paused), "tickets": dict(self.lead.state), "waiting": self.lead.waiting(),
                "blocked": self.lead.blocked(), "releases": self.lead.releases,
                "gates_pending": {sid: g.kind for sid, g in self.gate.pending.items()}, "plans": list(self.plans),
                "blackboard": self.blackboard.overview(),
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
    """python -m company.orchestrator run [--db] [--max-steps N] [--watch GIÂY]
       python -m company.orchestrator publish <topic> <file.json> --actor human:po [--key K]
       python -m company.orchestrator decide-change <change_id> accepted|rejected|deferred --by human:po
       python -m company.orchestrator status | report [--db]"""
    ap = argparse.ArgumentParser(description="Orchestrator: vòng lặp tự động topic → agent → topic")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    ap.add_argument("--repo", type=Path, help="git repo của khách: khối kỹ thuật sửa code thật trong worktree ticket/<id>")
    ap.add_argument("--base", default="HEAD", help="nhánh/commit gốc để tạo nhánh tích hợp lần đầu (mặc định HEAD)")
    ap.add_argument("--integration", default="company/integration", help="nhánh tích hợp: ticket rẽ từ đây, merge vào đây")
    ap.add_argument("--project-budget", type=int, help="hạn mức token cho CẢ dự án; vượt thì supervisor cắt toàn dự án")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run"); rn.add_argument("--max-steps", type=int); rn.add_argument("--watch", type=float,
        help="chạy liên tục, mỗi N giây nạp event mới (gate CLI, publish) rồi xử lý")
    pb = sub.add_parser("publish"); pb.add_argument("topic"); pb.add_argument("file", type=Path)
    pb.add_argument("--actor", required=True); pb.add_argument("--key")
    dc = sub.add_parser("decide-change", help="khách quyết định change request (sau khi delivery-lead ước lượng impact)")
    dc.add_argument("change_id"); dc.add_argument("decision", choices=["accepted", "rejected", "deferred"])
    dc.add_argument("--by", required=True); dc.add_argument("--reason", default="")
    sub.add_parser("status"); sub.add_parser("report", help="sprint report: estimate vs actual, hành động supervisor")
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
    from .llm import make_client
    orch = Orchestrator(bus, make_client(), repo=ns.repo, base=ns.base, integration=ns.integration,
                        project_budget_tokens=ns.project_budget)
    if ns.cmd == "status":
        print(json.dumps(orch.status(), ensure_ascii=False, indent=2)); return 0
    if ns.cmd == "report":
        print(json.dumps(orch.supervisor.sprint_report(), ensure_ascii=False, indent=2)); return 0
    if ns.watch:
        try: orch.watch(interval=ns.watch)
        except KeyboardInterrupt: pass
    else:
        for r in orch.tick() if ns.max_steps is None else orch.run(ns.max_steps): print(_fmt(r))
    print(json.dumps(orch.status(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
