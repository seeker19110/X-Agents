from __future__ import annotations
from collections import defaultdict
from .bus import InMemoryBus
from .events import Envelope, Task, ReviewResult, can_transition
from .gates import HumanGate, GateRequest

class DeliveryLead:
    """Logic xác định của delivery-lead: dispatch, gom review, retry, release candidate.
    LLM chỉ dùng để viết plan/ticket; phần đóng vòng ở đây là code."""
    def __init__(self, bus: InMemoryBus, gate: HumanGate, max_retries: int = 3):
        self.bus, self.gate, self.max_retries = bus, gate, max_retries
        self.tickets: dict[str, Task] = {}
        self.state: dict[str, str] = {}
        self.reviews: dict[str, dict[str, ReviewResult]] = defaultdict(dict)
        self.releases: list[str] = []
        bus.subscribe("review-results", self._on_review)
        bus.subscribe("pull-requests", self._on_pr)

    def _set(self, tid: str, dst: str) -> None:
        src = self.state.get(tid, "draft")
        if not can_transition(src, dst):
            raise ValueError(f"{tid}: không thể {src} → {dst}")
        self.state[tid] = dst

    def dispatch(self, task: Task, plan_id: str) -> Task:
        if not self.gate.is_approved(plan_id):
            raise PermissionError("plan chưa được human gate duyệt")
        self.tickets[task.ticket_id] = task
        self._set(task.ticket_id, "dispatched")
        self.bus.publish(Envelope(topic="tasks", key=task.ticket_id, actor="delivery-lead", payload=task.model_dump()))
        return task

    def _on_pr(self, env: Envelope) -> None:
        tid = env.key
        if self.state.get(tid) == "dispatched": self._set(tid, "in_progress")
        self._set(tid, "in_review"); self.reviews[tid] = {}

    def _on_review(self, env: Envelope) -> None:
        r = ReviewResult.model_validate(env.payload); tid = r.ticket_id
        self.reviews[tid][r.source] = r
        if len(self.reviews[tid]) < 2:
            return
        if all(x.verdict == "pass" for x in self.reviews[tid].values()):
            self._set(tid, "approved")
            rid = f"REL-{len(self.releases)+1:03d}"; self.releases.append(rid)
            self.bus.publish(Envelope(topic="release-candidates", key=rid, actor="delivery-lead",
                payload={"release_id": rid, "project_id": self.tickets[tid].project_id, "tickets": [tid], "version": "0.0.0"}))
            self.gate.request(GateRequest(kind="release", subject_id=rid, checklist=["tests", "scan", "runbook", "rollback"], created_by="delivery-lead"))
            return
        self._set(tid, "changes_requested")
        t = self.tickets[tid]
        if t.retry + 1 >= self.max_retries:
            self._set(tid, "blocked"); return
        hint = next((x.root_cause for x in self.reviews[tid].values() if x.root_cause), None) or \
               "; ".join(f.text for x in self.reviews[tid].values() for f in x.findings if f.level == "block")
        nt = t.model_copy(update={"retry": t.retry + 1, "hint": hint})
        self.tickets[tid] = nt; self._set(tid, "dispatched")
        self.bus.publish(Envelope(topic="tasks", key=tid, actor="delivery-lead", payload=nt.model_dump()))
