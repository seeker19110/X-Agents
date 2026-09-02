"""Orchestrator: vòng lặp tự động nối topic → agent → topic (ADR-0007).

Mỗi event trên bus được đối chiếu với bảng ROUTES (rút từ bảng topic trong docs/architecture.md và front matter
`reads`/`writes` của agent): khớp thì gọi `AgentRunner` rồi publish đầu ra; đầu ra lại là event mới → vòng lặp tiếp.
Phần xác định (DeliveryLead, Supervisor, PersistentGate) subscribe bus như trước; orchestrator chỉ điền chỗ trống
"ai chạy tiếp theo" và tôn trọng ba thứ không bao giờ tự đi tiếp:

- Human gate: `approved-specs` chờ gate `spec`; plan của delivery-lead chờ gate `plan`; production chờ gate `release`.
- Supervisor: ticket bị pause/budget_cut/escalate thì mọi event của ticket đó bị hoãn đến khi `resume`.
- Khách: `clarification-answers`, `acceptance-results`, `change-requests.decision` do người publish (CLI `publish`).

Mọi event đã xử lý được đánh dấu bằng `audit-log` (actor=orchestrator, action=orchestrated) nên mở lại bus SQLite là
tiếp tục đúng chỗ; trạng thái delivery-lead/supervisor/gate dựng lại từ replay. Không retry lời gọi model: lỗi ghi
audit rồi đi tiếp, retry thuộc delivery-lead (hint) và supervisor (hạn mức).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .blackboard import Blackboard
from .bus import InMemoryBus
from .delivery import DeliveryLead
from .events import BUDGET_FACTOR, AuditLog, Envelope, Task
from .gate_cli import PersistentGate
from .gates import GateRequest
from .llm import LLMError, ModelClient
from .registry import AgentSpec, load_agents
from .runner import AgentRunner, RunnerError
from .supervisor import Supervisor

ACTOR = "orchestrator"
ENGINEERING = ("backend", "frontend", "mobile", "database", "platform", "data")
PAUSING = frozenset({"pause", "budget_cut", "escalate"})
CONTROL_TOPICS = frozenset({"audit-log", "shared-context", "supervisor-actions"})

When = Callable[[Envelope, "Orchestrator"], bool]


@dataclass(frozen=True)
class Route:
    topic_in: str
    agent: str  # id agent, hoặc "$assignee" = lấy từ payload.assignee (khối kỹ thuật)
    topic_out: str
    when: When | None = None
    target_env: str | None = None  # route release: đầu ra phải có env đúng như yêu cầu

    def agents(self) -> tuple[str, ...]:
        return ENGINEERING if self.agent == "$assignee" else (self.agent,)


def _from(*actors: str) -> When:
    return lambda e, _o: e.actor in actors


def _needs_security(e: Envelope, o: Orchestrator) -> bool:
    tid = e.payload.get("ticket_id") or e.key
    return tid in o.lead.tickets and "security" in o.lead.required_reviews(tid)


def _staging_deployed(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("env") == "staging" and e.payload.get("status") == "deployed"


ROUTES: tuple[Route, ...] = (
    # khối nghiên cứu: intake → researcher → synthesizer → risk → clarifier → (người trả lời) → spec-writer
    Route("research-requests", "intake", "research-findings"),
    Route("research-findings", "researcher", "research-findings", _from("intake")),
    Route("research-findings", "synthesizer", "requirements-draft", _from("researcher")),
    Route("requirements-draft", "risk", "requirements-draft", _from("synthesizer")),
    Route("requirements-draft", "clarifier", "clarification-questions", _from("risk")),
    Route("clarification-answers", "spec-writer", "approved-specs"),
    # kỹ thuật + chất lượng
    Route("tasks", "$assignee", "pull-requests"),
    Route("pull-requests", "reviewer", "review-results"),
    Route("pull-requests", "qa-debugger", "review-results"),
    Route("pull-requests", "security-engineer", "review-results", _needs_security),
    # vận hành: RC → staging → QA hồi quy; production đi qua gate 3 (PROD_ROUTE)
    Route("release-candidates", "release-engineer", "release-events", target_env="staging"),
    Route("release-events", "qa-debugger", "review-results", _staging_deployed),
    Route("external-feedback", "account-manager", "change-requests"),
)
PROD_ROUTE = Route("release-candidates", "release-engineer", "release-events", target_env="production")

# Đầu vào khiến delivery-lead lập kế hoạch (sinh nhiều ticket một lượt) → gate `plan` → dispatch.
PLAN_INPUTS: dict[str, When] = {
    "approved-specs": lambda e, _o: True,
    "incidents": lambda e, _o: e.payload.get("root_cause_class") in {"code", "ops", "design"},
    "change-requests": lambda e, _o: e.payload.get("decision") == "accepted",
}


def check_routes(agents: dict[str, AgentSpec]) -> list[str]:
    """Bảng route phải khớp front matter reads/writes; trả về danh sách vi phạm (rỗng = ổn)."""
    bad = []
    for r in (*ROUTES, PROD_ROUTE):
        for a in r.agents():
            spec = agents[a]
            if r.topic_in not in spec.reads and "*" not in spec.reads: bad.append(f"{a} không đọc {r.topic_in}")
            if r.topic_out not in spec.writes: bad.append(f"{a} không ghi {r.topic_out}")
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
                 max_retries: int = 3):
        self.bus = bus
        self.agents = agents or load_agents()
        bad = check_routes(self.agents)
        if bad: raise ValueError("ROUTES lệch front matter: " + "; ".join(bad))
        self.blackboard = Blackboard(bus)
        self.gate = PersistentGate(bus)
        self.lead = DeliveryLead(bus, self.gate, max_retries=max_retries)
        self.supervisor = Supervisor(bus, max_retries=max_retries)
        self.runner = AgentRunner(bus, client, self.agents, self.blackboard)
        self.processed: set[str] = set()
        self.paused: set[str] = set()
        self.plans: dict[str, dict[str, Any]] = {}
        self.queue: list[Envelope] = []
        self.deferred: dict[str, tuple[Envelope, str]] = {}
        self.reminded: set[str] = set()
        self.stats: Counter[str] = Counter()
        self._rehydrate()
        bus.subscribe("*", self._on_event)

    # ---------- khôi phục từ log ----------

    def _rehydrate(self) -> None:
        for env in self.bus.replay():
            if env.topic == "audit-log":
                a = env.payload; d = _evidence(a)
                if a["actor"] == ACTOR and a["action"] == "orchestrated": self.processed.add(d["event_id"])
                elif a["action"] == "plan.proposed": self.plans[d["plan_id"]] = d
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

    # ---------- vòng lặp ----------

    def run(self, max_steps: int | None = None) -> list[StepResult]:
        """Xử lý hàng đợi đến khi rỗng (hoặc đủ max_steps). Event bị hoãn không làm vòng lặp quay mãi."""
        out: list[StepResult] = []
        while self.queue and (max_steps is None or len(out) < max_steps):
            env = self.queue.pop(0)
            r = self.process(env)
            if r is not None: out.append(r)
        return out

    def tick(self, now=None) -> list[StepResult]:
        """Một nhịp của chế độ watch: nạp event từ tiến trình khác, chạy hàng đợi, nhắc gate/review quá hạn."""
        if hasattr(self.bus, "poll"): self.bus.poll()
        results = self.run()
        remind, overdue = self.gate.due(now)
        for sid in [*remind, *overdue]:
            self._audit(f"gate.{'overdue' if sid in overdue else 'remind'}", {"subject_id": sid}, once=f"gate:{sid}")
        for tid, missing in self.lead.overdue_reviews(now).items():
            self._audit("review.overdue", {"ticket_id": tid, "missing": sorted(missing)}, once=f"review:{tid}", ticket_id=tid)
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
        for r in ROUTES:
            if r.topic_in != env.topic or (r.when and not r.when(env, self)): continue
            agent = env.payload["assignee"] if r.agent == "$assignee" else r.agent
            self._call(agent, env, r, res)
        self._mark(env, res)
        return res

    def _call(self, agent: str, env: Envelope, r: Route, res: StepResult) -> None:
        try:
            out = self._release(agent, env, r) if r.target_env else self.runner.run(agent, env, r.topic_out).output
            res.actions.append(f"{agent}→{r.topic_out}:{out.key}"); self.stats["runs"] += 1
        except (RunnerError, LLMError) as e:  # runner đã ghi audit; không retry (ADR-0005)
            res.actions.append(f"error:{agent}:{str(e)[:120]}"); self.stats["errors"] += 1
        except Exception as e:  # handler xác định (delivery-lead) từ chối chuyển trạng thái: event đã ghi đĩa
            self._audit("handler_error", {"agent": agent, "error": str(e)[:300]}, ticket_id=env.payload.get("ticket_id"))
            res.actions.append(f"handler_error:{agent}:{str(e)[:120]}"); self.stats["errors"] += 1

    def _release(self, agent: str, rc: Envelope, r: Route) -> Envelope:
        """release-engineer nhận RC kèm `target_env`; đầu ra phải đúng env và release_id, nếu không thì coi là invalid."""
        rid = rc.payload["release_id"]
        inp = rc.model_copy(update={"payload": {**rc.payload, "target_env": r.target_env,
                                                "gate_release": self.gate.is_approved(rid)}})
        g = self.runner.generate(agent, inp, r.topic_out)
        p = g.payloads[0]
        if p.get("env") != r.target_env or p.get("release_id") != rid:
            self._audit("invalid_output", {"agent": agent, "expected_env": r.target_env, "got": p.get("env")},
                        actor=agent, tokens=g.tokens)
            raise RunnerError(f"{agent}: đầu ra env={p.get('env')} release_id={p.get('release_id')}, cần {r.target_env}/{rid}")
        return self.runner.publish(agent, rc, r.topic_out, p, key=rid, tokens=g.tokens, model=g.model)

    # ---------- kế hoạch: delivery-lead sinh ticket → gate plan → dispatch ----------

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
        try:
            g = self.runner.generate("delivery-lead", env, "tasks", many=True)
        except (RunnerError, LLMError) as e:
            res.actions.append(f"error:delivery-lead:{str(e)[:120]}"); self.stats["errors"] += 1
            self._mark(env, res); return res
        tickets = [Task.model_validate(p) for p in g.payloads]
        problems = self._check_plan(tickets)
        n = 1 + sum(1 for p in self.plans.values() if p["project_id"] == project)
        plan_id = f"PLAN-{project}-{n}"
        plan = {"plan_id": plan_id, "project_id": project, "source_event": env.event_id, "source_topic": env.topic,
                "tickets": [t.model_dump() for t in tickets], "problems": problems}
        if problems:
            self._audit("plan_rejected", plan, actor="delivery-lead", tokens=g.tokens, project_id=project)
            res.actions.append(f"plan_rejected:{'; '.join(problems)[:120]}"); self.stats["errors"] += 1
        else:
            self.plans[plan_id] = plan
            self._audit("plan.proposed", plan, actor="delivery-lead", tokens=g.tokens, project_id=project)
            self.gate.request(GateRequest(kind="plan", subject_id=plan_id, created_by="delivery-lead",
                                          checklist=["tickets", "estimate_tokens", "risk_tags", "depends_on", "threat-model"]))
            res.actions.append(f"plan:{plan_id}:{len(tickets)} ticket"); self.stats["plans"] += 1
        self._mark(env, res)
        return res

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

    def _on_gate_decide(self, env: Envelope, res: StepResult) -> StepResult:
        d = _evidence(env.payload); sid, decision = d["subject_id"], d["decision"]
        res.actions.append(f"gate:{sid}:{decision}")
        if decision == "approve":
            if sid in self.plans:
                try:
                    res.actions.append("dispatch:" + ",".join(self._dispatch_plan(sid)))
                except (ValueError, PermissionError) as e:
                    self._audit("plan_dispatch_error", {"plan_id": sid, "error": str(e)[:300]}); res.actions.append(f"error:{e}")
            elif sid in self.lead.release_tickets:
                rc = next((e for e in self.bus.replay(topic="release-candidates", key=sid)), None)
                if rc is not None: self._call("release-engineer", rc, PROD_ROUTE, res)
        self._mark(env, res)
        self._retry_deferred()
        return res

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

    def _audit(self, action: str, data: dict[str, Any], actor: str = ACTOR, tokens: int = 0, once: str | None = None,
               ticket_id: str | None = None, project_id: str | None = None) -> None:
        if once:
            if once in self.reminded: return
            self.reminded.add(once)
        a = AuditLog(actor=actor, action=action, tokens=tokens, ticket_id=ticket_id, project_id=project_id,
                     evidence=json.dumps(data, ensure_ascii=False))
        self.bus.publish(Envelope(topic="audit-log", key=actor, actor=actor, payload=a.model_dump()))

    def status(self) -> dict[str, Any]:
        return {"queue": len(self.queue), "deferred": {k: v[1] for k, v in self.deferred.items()},
                "paused": sorted(self.paused), "tickets": dict(self.lead.state), "waiting": self.lead.waiting(),
                "releases": self.lead.releases, "gates_pending": list(self.gate.pending), "plans": list(self.plans),
                "stats": dict(self.stats), "events": len(self.bus)}


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
       python -m company.orchestrator status [--db]"""
    ap = argparse.ArgumentParser(description="Orchestrator: vòng lặp tự động topic → agent → topic")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run"); rn.add_argument("--max-steps", type=int); rn.add_argument("--watch", type=float,
        help="chạy liên tục, mỗi N giây nạp event mới (gate CLI, publish) rồi xử lý")
    pb = sub.add_parser("publish"); pb.add_argument("topic"); pb.add_argument("file", type=Path)
    pb.add_argument("--actor", required=True); pb.add_argument("--key")
    sub.add_parser("status")
    ns = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")  # Windows console cp1252
    from .sqlite_bus import SQLiteBus
    bus = SQLiteBus(ns.db)
    if ns.cmd == "publish":
        payload = json.loads(ns.file.read_text(encoding="utf-8"))
        key = ns.key or payload.get("ticket_id") or payload.get("release_id") or payload.get("project_id") or payload.get("change_id")
        if not key: print("cần --key", file=sys.stderr); return 2
        env = bus.publish(Envelope(topic=ns.topic, key=key, actor=ns.actor, payload=payload))
        print(f"published {env.topic} key={env.key} event={env.event_id}"); return 0
    from .llm import make_client
    orch = Orchestrator(bus, make_client())
    if ns.cmd == "status":
        print(json.dumps(orch.status(), ensure_ascii=False, indent=2)); return 0
    if ns.watch:
        try: orch.watch(interval=ns.watch)
        except KeyboardInterrupt: pass
    else:
        for r in orch.tick() if ns.max_steps is None else orch.run(ns.max_steps): print(_fmt(r))
    print(json.dumps(orch.status(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
