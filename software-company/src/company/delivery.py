from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .bus import InMemoryBus
from .events import BUDGET_FACTOR, AcceptanceResult, Envelope, ReviewResult, Task, can_transition
from .gates import GateRequest, HumanGate

DONE_STATES = frozenset({"approved", "merged", "released", "closed"})


class DeliveryLead:
    """Logic xác định của delivery-lead: lập lịch theo depends_on/priority, dispatch, gom review, retry,
    release candidate, QA trên staging trước gate 3, merge/release theo release-events, đóng ticket khi khách nghiệm thu.
    LLM chỉ dùng để viết plan/ticket; phần đóng vòng ở đây là code."""
    BASE_REVIEWS: frozenset[str] = frozenset({"reviewer", "qa"})

    def __init__(self, bus: InMemoryBus, gate: HumanGate, max_retries: int = 3,
                 review_timeout: timedelta = timedelta(hours=2)):
        self.bus, self.gate, self.max_retries, self.review_timeout = bus, gate, max_retries, review_timeout
        self.tickets: dict[str, Task] = {}
        self.state: dict[str, str] = {}
        self.plan_of: dict[str, str] = {}
        self.reviews: dict[str, dict[str, ReviewResult]] = defaultdict(dict)
        self.review_since: dict[str, datetime] = {}
        self.releases: list[str] = []
        self.release_tickets: dict[str, list[str]] = {}
        self.release_qa: dict[str, ReviewResult] = {}
        self.acceptance: dict[str, AcceptanceResult] = {}
        self.replaying = False  # True khi dựng lại trạng thái từ log: đổi state nhưng không publish/xin gate lại
        self.handlers = {"review-results": self._on_review, "pull-requests": self._on_pr,
                         "release-events": self._on_release_event, "acceptance-results": self._on_acceptance}
        for topic, fn in self.handlers.items():
            bus.subscribe(topic, fn)

    def _emit(self, env: Envelope) -> None:
        if not self.replaying:
            self.bus.publish(env)

    def replay(self, env: Envelope) -> None:
        """Áp một event cũ vào trạng thái (dùng khi orchestrator mở lại bus bền vững). Lỗi chuyển trạng thái bị bỏ qua
        vì event đã xảy ra rồi; mục tiêu là khôi phục, không phải kiểm tra."""
        fn = self.handlers.get(env.topic)
        if fn is None: return
        prev, self.replaying = self.replaying, True
        try:
            fn(env)
        except (ValueError, PermissionError, KeyError):
            pass
        finally:
            self.replaying = prev

    # ---------- trạng thái ----------

    def _set(self, tid: str, dst: str) -> None:
        src = self.state.get(tid, "draft")
        if not can_transition(src, dst):
            raise ValueError(f"{tid}: không thể {src} → {dst}")
        self.state[tid] = dst

    def required_reviews(self, tid: str) -> set[str]:
        """reviewer + qa luôn; thêm security khi ticket có risk_tags (ADR-0003)."""
        extra = {"security"} if self.tickets[tid].risk_tags else set()
        return set(self.BASE_REVIEWS) | extra

    # ---------- lập lịch và dispatch ----------

    def _deps_done(self, task: Task) -> bool:
        return all(self.state.get(d) in DONE_STATES for d in task.depends_on)

    def _publish_task(self, task: Task) -> None:
        self._set(task.ticket_id, "dispatched")
        self._emit(Envelope(topic="tasks", key=task.ticket_id, actor="delivery-lead", payload=task.model_dump()))

    def dispatch(self, task: Task, plan_id: str) -> Task:
        """Ticket vào hàng chờ nếu phụ thuộc chưa xong; ngược lại publish ngay. Phụ thuộc phải là ticket đã biết."""
        if not self.replaying and not self.gate.is_approved(plan_id):
            raise PermissionError("plan chưa được human gate duyệt")
        if task.estimate_tokens is not None and task.budget_tokens < task.estimate_tokens * BUDGET_FACTOR:
            raise ValueError(f"{task.ticket_id}: budget_tokens {task.budget_tokens} < estimate_tokens × {BUDGET_FACTOR}")
        unknown = [d for d in task.depends_on if d not in self.tickets and d != task.ticket_id]
        if unknown:
            raise ValueError(f"{task.ticket_id}: depends_on ticket chưa biết {unknown}")
        if task.ticket_id in task.depends_on:
            raise ValueError(f"{task.ticket_id}: tự phụ thuộc")
        self.tickets[task.ticket_id] = task; self.plan_of[task.ticket_id] = plan_id
        if self._deps_done(task):
            self._publish_task(task)
        else:
            self._set(task.ticket_id, "waiting")
        return task

    def _flush_waiting(self) -> list[str]:
        """Dispatch các ticket đang chờ mà phụ thuộc đã xong, theo priority (1 cao nhất) rồi thứ tự tạo."""
        ready = [t for t in self.tickets.values() if self.state.get(t.ticket_id) == "waiting" and self._deps_done(t)]
        for t in sorted(ready, key=lambda x: x.priority):
            self._publish_task(t)
        return [t.ticket_id for t in ready]

    def waiting(self) -> dict[str, list[str]]:
        return {tid: [d for d in self.tickets[tid].depends_on if self.state.get(d) not in DONE_STATES]
                for tid, st in self.state.items() if st == "waiting"}

    # ---------- vòng review ----------

    def _on_pr(self, env: Envelope) -> None:
        tid = env.key
        if self.state.get(tid) == "dispatched": self._set(tid, "in_progress")
        self._set(tid, "in_review"); self.reviews[tid] = {}; self.review_since[tid] = env.ts

    def overdue_reviews(self, now: datetime | None = None) -> dict[str, set[str]]:
        """Ticket ở in_review quá review_timeout: trả về nguồn review còn thiếu để supervisor giao lại/escalate."""
        now = now or datetime.now(UTC); out = {}
        for tid, since in self.review_since.items():
            if self.state.get(tid) == "in_review" and now - since > self.review_timeout:
                missing = self.required_reviews(tid) - set(self.reviews[tid])
                if missing: out[tid] = missing
        return out

    def _retry(self, tid: str, hint: str | None) -> None:
        t = self.tickets[tid]
        if t.retry + 1 >= self.max_retries:
            self._set(tid, "blocked"); return
        nt = t.model_copy(update={"retry": t.retry + 1, "hint": hint})
        self.tickets[tid] = nt; self._publish_task(nt)

    def _on_review(self, env: Envelope) -> None:
        r = ReviewResult.model_validate(env.payload)
        if r.ticket_id in self.release_tickets:
            self._on_release_qa(r); return
        tid = r.ticket_id
        self.reviews[tid][r.source] = r
        if not self.required_reviews(tid) <= set(self.reviews[tid]):
            return
        self.review_since.pop(tid, None)
        if all(x.verdict == "pass" for x in self.reviews[tid].values()):
            self._set(tid, "approved")
            self._create_release_candidate([tid])
            self._flush_waiting()
            return
        self._set(tid, "changes_requested")
        hint = next((x.root_cause for x in self.reviews[tid].values() if x.root_cause), None) or \
               "; ".join(f.text for x in self.reviews[tid].values() for f in x.findings if f.level == "block")
        self._retry(tid, hint)

    # ---------- release: RC → staging → QA hồi quy → gate 3 → production → nghiệm thu ----------

    def _create_release_candidate(self, tids: list[str]) -> str:
        rid = f"REL-{len(self.releases)+1:03d}"; self.releases.append(rid); self.release_tickets[rid] = tids
        self._emit(Envelope(topic="release-candidates", key=rid, actor="delivery-lead",
            payload={"release_id": rid, "project_id": self.tickets[tids[0]].project_id, "tickets": tids, "version": "0.0.0"}))
        return rid

    def _on_release_event(self, env: Envelope) -> None:
        p = env.payload; rid = p["release_id"]
        if rid not in self.release_tickets: return
        if p["env"] == "staging" and p["status"] == "deployed":
            for tid in self.release_tickets[rid]:
                if self.state.get(tid) == "approved": self._set(tid, "merged")
        elif p["env"] == "production" and p["status"] == "deployed":
            if not self.gate.is_approved(rid):
                raise PermissionError(f"{rid}: deploy production khi human gate chưa duyệt")
            for tid in self.release_tickets[rid]:
                if self.state.get(tid) == "merged": self._set(tid, "released")
        elif p["status"] in {"rolled_back", "failed"}:
            for tid in self.release_tickets[rid]:
                if self.state.get(tid) in {"merged", "released"}:
                    self._set(tid, "changes_requested"); self._retry(tid, f"{rid} {p['status']} trên {p['env']}")

    def _on_release_qa(self, r: ReviewResult) -> None:
        """QA hồi quy/perf/a11y trên staging (ticket_id = release_id). Pass → mới xin gate 3."""
        rid = r.ticket_id; self.release_qa[rid] = r
        if r.verdict == "pass":
            if not self.replaying:
                self.gate.request(GateRequest(kind="release", subject_id=rid, created_by="delivery-lead",
                                              checklist=["tests", "scan", "regression-staging", "perf", "a11y", "runbook", "rollback"]))
            return
        hint = r.root_cause or "; ".join(f.text for f in r.findings if f.level == "block") or "QA staging fail"
        for tid in self.release_tickets[rid]:
            if self.state.get(tid) == "merged":
                self._set(tid, "changes_requested"); self._retry(tid, hint)

    def _on_acceptance(self, env: Envelope) -> None:
        a = AcceptanceResult.model_validate(env.payload); self.acceptance[a.release_id] = a
        for tid in self.release_tickets.get(a.release_id, []):
            if self.state.get(tid) != "released": continue
            if a.verdict == "accepted":
                self._set(tid, "closed")
            elif a.verdict == "rejected":
                hint = "; ".join(f.text for f in a.findings) or "khách từ chối nghiệm thu"
                self._set(tid, "changes_requested"); self._retry(tid, hint)
            # conditional: giữ released, account-manager mở change-request cho phần còn lại
