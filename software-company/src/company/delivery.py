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
    BASE_REVIEWS: frozenset[str] = frozenset({"reviewer"})
    RISK_REVIEWS: frozenset[str] = frozenset({"qa", "security"})  # ADR-0021: chỉ khi ticket có risk_tags

    IN_FLIGHT = frozenset({"waiting", "dispatched", "in_progress", "in_review", "changes_requested"})

    def __init__(self, bus: InMemoryBus, gate: HumanGate, max_retries: int = 3,
                 review_timeout: timedelta = timedelta(hours=2), batch_releases: bool = False):
        self.bus, self.gate, self.max_retries, self.review_timeout = bus, gate, max_retries, review_timeout
        # batch_releases: gom mọi ticket approved của dự án vào MỘT RC khi không còn ticket nào đang chạy (thay vì mỗi
        # ticket một release → mỗi ticket một lần staging, một gate 3, một UAT). Ticket blocked/escalated chờ người,
        # không giữ release của người khác.
        self.batch_releases = batch_releases
        # F15: có nhánh tích hợp thì ticket phụ thuộc chỉ bắt đầu khi dependency đã MERGE vào đó (orchestrator báo qua
        # `mark_integrated`); `approved` chưa đủ — merge có thể xung đột và ticket sau sẽ làm trên nền thiếu code.
        self.require_integration = False
        self.integrated: set[str] = set()
        self.tickets: dict[str, Task] = {}
        self.state: dict[str, str] = {}
        self.plan_of: dict[str, str] = {}
        self.reviews: dict[str, dict[str, ReviewResult]] = defaultdict(dict)
        self.review_since: dict[str, datetime] = {}
        self.releases: list[str] = []
        self.versions: dict[str, tuple[int, int, int]] = {}  # project_id → SemVer đã phát hành gần nhất
        self.release_tickets: dict[str, list[str]] = {}
        self.release_qa: dict[str, ReviewResult] = {}
        self.release_reviews: dict[str, dict[str, ReviewResult]] = defaultdict(dict)
        self.acceptance: dict[str, AcceptanceResult] = {}
        self.replaying = False  # True khi dựng lại trạng thái từ log: đổi state nhưng không publish/xin gate lại
        self.handlers = {"review-results": self._on_review, "pull-requests": self._on_pr,
                         "release-candidates": self._on_release_candidate,
                         "release-events": self._on_release_event, "acceptance-results": self._on_acceptance,
                         "change-requests": self._on_change_request}
        for topic, fn in self.handlers.items():
            bus.subscribe(topic, fn)

    def _emit(self, env: Envelope) -> None:
        if not self.replaying:
            self.bus.publish(env)

    def replay(self, env: Envelope) -> None:
        """Áp một event cũ vào trạng thái (dùng khi orchestrator mở lại bus bền vững). Lỗi chuyển trạng thái bị bỏ qua
        vì event đã xảy ra rồi; mục tiêu là khôi phục, không phải kiểm tra."""
        fn = self._replay_task if env.topic == "tasks" else self.handlers.get(env.topic)
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
        """reviewer luôn; qa + security khi ticket có risk_tags (ADR-0003, ADR-0021). Ticket thường: reviewer kiêm
        chấm test ở lượt PR, QA vẫn hồi quy toàn bộ trên staging (release-events) — bớt một lời gọi mỗi ticket."""
        extra = set(self.RISK_REVIEWS) if self.tickets[tid].risk_tags else set()
        return set(self.BASE_REVIEWS) | extra

    # ---------- lập lịch và dispatch ----------

    def _deps_done(self, task: Task) -> bool:
        return all(self._dep_done(d) for d in task.depends_on)

    def _dep_done(self, tid: str) -> bool:
        st = self.state.get(tid)
        if st not in DONE_STATES: return False
        return not self.require_integration or tid in self.integrated or st in {"merged", "released", "closed"}

    def mark_integrated(self, tid: str) -> list[str]:
        """Orchestrator gọi sau khi merge branch ticket vào nhánh tích hợp thành công: ticket phụ thuộc đang `waiting`
        được dispatch (trả về danh sách). Khi khôi phục từ log (`replaying`) chỉ ghi nhận, không publish."""
        self.integrated.add(tid)
        return self._flush_waiting()

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
        return {tid: [d for d in self.tickets[tid].depends_on if not self._dep_done(d)]
                for tid, st in self.state.items() if st == "waiting"}

    # ---------- vòng review ----------

    def _on_pr(self, env: Envelope) -> None:
        """PR mới cho ticket. Ticket đã ở `in_review` (người tiếp quản theo ADR-0012, hoặc agent nộp lại vì event được
        xử lý lại) thì PR này THAY PR cũ và vòng review làm lại từ đầu — không phải lỗi chuyển trạng thái."""
        tid = env.key
        if self.state.get(tid) == "in_review":
            self.reviews[tid] = {}; self.review_since[tid] = env.ts; return
        if self.state.get(tid) == "dispatched": self._set(tid, "in_progress")
        self._set(tid, "in_review"); self.reviews[tid] = {}; self.review_since[tid] = env.ts

    def human_hint(self, tid: str, hint: str) -> Task:
        """Người can thiệp giữa vòng (ADR-0012): ticket đang `in_review` (PR chờ/đang review) → về `changes_requested`
        rồi phát lại task với hint; `dispatched`/`in_progress` (agent lỗi, chưa có PR) → phát lại với hint. Không tính
        retry — đây là hướng dẫn thêm, không phải thất bại của agent. Ticket blocked/escalated đi qua gate escalation."""
        st = self.state.get(tid)
        if tid not in self.tickets or st not in {"in_review", "dispatched", "in_progress", "changes_requested"}:
            raise ValueError(f"{tid}: không can thiệp được ở trạng thái {st} (blocked/escalated → gate escalation)")
        nt = self.tickets[tid].model_copy(update={"hint": hint}); self.tickets[tid] = nt
        if st == "in_review": self._set(tid, "changes_requested")
        elif st != "changes_requested": self.state[tid] = "changes_requested"  # dispatched/in_progress: agent chưa nộp gì
        self.review_since.pop(tid, None)
        self._publish_task(nt); return nt

    def _replay_task(self, env: Envelope) -> None:
        """Task phát lại (retry/rework/hint/reopen) không đi qua handler nào khi chạy thật — delivery-lead tự publish —
        nên trước đây khôi phục từ log không biết ticket đã bị trả về: ticket có đủ review pass cũ lại thành `approved`,
        ticket phụ thuộc được dispatch, nhánh trống sau `fresh()` được "tích hợp". Ở đây: task mới hơn (retry tăng hoặc
        hint đổi) của ticket đã biết → ticket về `dispatched` với task đó, review cũ bỏ."""
        t = Task.model_validate(env.payload)
        old = self.tickets.get(t.ticket_id)
        if old is None or (t.retry <= old.retry and t.hint == old.hint): return
        self.tickets[t.ticket_id] = t; self.state[t.ticket_id] = "dispatched"
        self.reviews[t.ticket_id] = {}; self.review_since.pop(t.ticket_id, None)

    def rework(self, tid: str, hint: str) -> None:
        """PR bị code từ chối trước review (lint/test thật fail): ticket về `changes_requested` rồi retry+1 kèm hint là
        đầu ra test, không đi qua reviewer/QA/security chỉ để nghe lại điều máy đã biết. Hết retry → blocked."""
        if self.state.get(tid) not in {"dispatched", "in_progress"}:
            raise ValueError(f"{tid}: rework chỉ từ dispatched/in_progress (đang {self.state.get(tid)})")
        self.state[tid] = "changes_requested"
        self._retry(tid, hint)

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
        if tid not in self.tickets: return  # review cho spec (threat model SPEC-*) hoặc ticket lạ: không phải vòng ticket
        if self.state.get(tid) != "in_review":
            # Review đến trễ (người review chậm, hoặc bị giao lại) khi ticket đã rời vòng review — đã approved, đã
            # changes_requested vì một nguồn khác, hoặc đã đóng. Bỏ qua: gộp vào sẽ ép một chuyển trạng thái không hợp lệ.
            return
        self.reviews[tid][r.source] = r
        if not self.required_reviews(tid) <= set(self.reviews[tid]):
            return
        self.review_since.pop(tid, None)
        if all(x.verdict == "pass" for x in self.reviews[tid].values()):
            self._set(tid, "approved")
            # F19: khi khôi phục từ log không tạo RC — RC thật nằm trong `release-candidates` và được replay
            # (`_on_release_candidate`); tạo lại ở đây sẽ sinh REL-* thừa với danh sách ticket khác lần chạy thật.
            if self.replaying: pass
            elif self.batch_releases: self.flush_releases(self.tickets[tid].project_id)
            else: self._create_release_candidate([tid])
            self._flush_waiting()
            return
        self._set(tid, "changes_requested")
        hint = next((x.root_cause for x in self.reviews[tid].values() if x.root_cause), None) or \
               "; ".join(f.text for x in self.reviews[tid].values() for f in x.findings if f.level == "block")
        self._retry(tid, hint)

    # ---------- release: RC → staging → QA hồi quy → gate 3 → production → nghiệm thu ----------

    def next_version(self, project_id: str, tids: list[str]) -> str:
        """SemVer suy ra từ nội dung release, không phải hằng số. Ticket chạm auth/payment/crypto hoặc đổi
        `api-contract` là thay đổi có thể phá vỡ tương thích → tăng MINOR ở 0.x (chưa GA thì MINOR mang vai trò MAJOR);
        còn lại là PATCH. Người phát hành vẫn có quyền đặt lại, đây chỉ là giá trị mặc định có căn cứ."""
        cur = self.versions.get(project_id, (0, 1, 0))
        breaking = any(set(self.tickets[t].risk_tags) & {"auth", "payment", "crypto"} for t in tids if t in self.tickets)
        major, minor, patch = cur
        nxt = (major, minor + 1, 0) if breaking else (major, minor, patch + 1)
        self.versions[project_id] = nxt
        return ".".join(str(x) for x in nxt)

    def unreleased(self, project_id: str) -> list[str]:
        """Ticket approved của dự án chưa nằm trong RC nào."""
        in_rc = {t for tids in self.release_tickets.values() for t in tids}
        return [tid for tid, t in self.tickets.items()
                if t.project_id == project_id and self.state.get(tid) == "approved" and tid not in in_rc]

    def flush_releases(self, project_id: str) -> str | None:
        """Chế độ gom release: tạo RC cho mọi ticket approved chưa release của dự án khi không còn ticket nào đang chạy.
        Gọi lại khi trạng thái đổi (ticket approved, blocked, đóng sau escalation)."""
        if self.replaying: return None  # F19: RC được dựng lại từ log, không tạo mới
        pending = self.unreleased(project_id)
        if not pending: return None
        if any(t.project_id == project_id and self.state.get(tid) in self.IN_FLIGHT for tid, t in self.tickets.items()):
            return None
        return self._create_release_candidate(sorted(pending, key=lambda x: list(self.tickets).index(x)))

    def _create_release_candidate(self, tids: list[str]) -> str:
        rid = f"REL-{len(self.releases)+1:03d}"; self.releases.append(rid); self.release_tickets[rid] = tids
        project = self.tickets[tids[0]].project_id
        self._emit(Envelope(topic="release-candidates", key=rid, actor="delivery-lead",
            payload={"release_id": rid, "project_id": project, "tickets": tids,
                     "version": self.next_version(project, tids)}))
        return rid

    def _on_release_candidate(self, env: Envelope) -> None:
        """RC do chính delivery-lead phát (đã ghi nhận trong `_create_release_candidate`) → bỏ qua. Khi replay từ log,
        đây là nguồn duy nhất dựng lại `releases`/`release_tickets`/`versions` (F19), đúng id và đúng danh sách ticket
        của lần chạy thật."""
        p = env.payload; rid = p["release_id"]
        if rid in self.release_tickets: return
        self.releases.append(rid); self.release_tickets[rid] = list(p["tickets"])
        try:
            v = tuple(int(x) for x in str(p.get("version", "")).split("."))
        except ValueError:
            return
        if len(v) == 3: self.versions[p["project_id"]] = v  # type: ignore[assignment]

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

    def release_needs_security(self, rid: str) -> bool:
        return any(self.tickets[t].risk_tags for t in self.release_tickets.get(rid, []) if t in self.tickets)

    def _on_release_qa(self, r: ReviewResult) -> None:
        """Review trên release (ticket_id = release_id): QA hồi quy/perf/a11y trên staging, và security (DAST/license)
        khi release có ticket risk_tags. Đủ nguồn và tất cả pass → mới xin gate 3."""
        rid = r.ticket_id; self.release_reviews[rid][r.source] = r
        if r.source == "qa": self.release_qa[rid] = r
        if r.verdict != "pass":
            hint = r.root_cause or "; ".join(f.text for f in r.findings if f.level == "block") or f"{r.source} trên release fail"
            for tid in self.release_tickets[rid]:
                if self.state.get(tid) == "merged":
                    self._set(tid, "changes_requested"); self._retry(tid, hint)
            return
        need = {"qa"} | ({"security"} if self.release_needs_security(rid) else set())
        got = {s for s, x in self.release_reviews[rid].items() if x.verdict == "pass"}
        if need <= got and not self.replaying and rid not in self.gate.pending and not self.gate.is_approved(rid):
            self.gate.request(GateRequest(kind="release", subject_id=rid, created_by="delivery-lead",
                                          checklist=["tests", "scan", "regression-staging", "perf", "a11y", "runbook", "rollback"]))

    def request_changes(self, tid: str, hint: str) -> None:
        """Ticket đã approved nhưng không tích hợp được (xung đột với nhánh tích hợp): làm lại với hint, tính một retry.
        Release candidate đang chứa ticket này do orchestrator huỷ (không đi tiếp)."""
        self._set(tid, "changes_requested"); self._retry(tid, hint)

    def blocked(self) -> list[str]:
        return [tid for tid, st in self.state.items() if st == "blocked"]

    def reopen(self, tid: str, hint: str) -> Task:
        """Người duyệt escalation: mở lại ticket blocked/escalated với hint, đếm retry lại từ 0."""
        if self.state.get(tid) not in {"blocked", "escalated"}:
            raise ValueError(f"{tid}: chỉ mở lại ticket blocked/escalated (đang {self.state.get(tid)})")
        nt = self.tickets[tid].model_copy(update={"retry": 0, "hint": hint}); self.tickets[tid] = nt
        self._publish_task(nt); return nt

    def close_escalated(self, tid: str) -> None:
        """Người từ chối escalation: ticket đóng không làm nữa."""
        self._set(tid, "escalated"); self._set(tid, "closed")

    def _on_acceptance(self, env: Envelope) -> None:
        a = AcceptanceResult.model_validate(env.payload); self.acceptance[a.release_id] = a
        for tid in self.release_tickets.get(a.release_id, []):
            if self.state.get(tid) != "released": continue
            if a.verdict == "accepted":
                self._set(tid, "closed")
            elif a.verdict == "rejected":
                hint = "; ".join(f.text for f in a.findings) or "khách từ chối nghiệm thu"
                self._set(tid, "changes_requested"); self._retry(tid, hint)
            # conditional: giữ released cho tới khi change-request cho phần còn lại được quyết (`_on_change_request`)

    def _on_change_request(self, env: Envelope) -> None:
        """Change request sinh từ nghiệm thu conditional mang `release_id`. Khi khách đã quyết (accepted → phần còn lại
        đi lập kế hoạch riêng; rejected/deferred → không làm nữa) thì release đó coi như đã nghiệm thu: ticket đóng.
        Trước đây ticket giữ `released` mãi, dự án không bao giờ hết việc."""
        p = env.payload
        rid = p.get("release_id")
        if p.get("decision", "pending") == "pending" or not rid: return
        a = self.acceptance.get(str(rid))
        if a is None or a.verdict != "conditional": return
        for tid in self.release_tickets.get(str(rid), []):
            if self.state.get(tid) == "released": self._set(tid, "closed")
