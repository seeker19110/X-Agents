from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial

from .bus import InMemoryBus
from .events import BUDGET_FACTOR, AcceptanceResult, AuditLog, Envelope, ReviewResult, Task, can_transition
from .gate_cli import PersistentGate
from .gate_risk import request_gate
from .gates import GateRequest
from .quality_floor import QualityBar, QualityEvidence, ReleaseQuality, collect_evidence, project_bar
from .roles import LEAD_ACTOR, SOURCE

DONE_STATES = frozenset({"approved", "merged", "released", "closed"})


class DeliveryLead:
    """Logic xác định của delivery-lead: lập lịch theo depends_on/priority, dispatch, gom review, retry,
    release candidate, QA trên staging trước gate 3, merge/release theo release-events, đóng ticket khi khách nghiệm thu.
    LLM chỉ dùng để viết plan/ticket; phần đóng vòng ở đây là code."""
    BASE_REVIEWS: frozenset[str] = frozenset({SOURCE.REVIEWER})
    # ADR-0037: `reviewer` và `qa` là hai góc nhìn của CÙNG agent `qa`, và lượt PR của nó chạy cho MỌI ticket
    # (route `pull-requests` → `qa[review]` không còn guard theo `risk_tags`), nên `qa` không còn là review
    # "thêm" của ticket rủi ro — chỉ `security` là. Giữ `qa` ở đây thì ticket có `risk_tags` chờ một nhãn
    # `source: qa` mà lượt PR không bao giờ phát (nó phát `source: reviewer`) và ticket đứng mãi ở `in_review`.
    RISK_REVIEWS: frozenset[str] = frozenset({SOURCE.SECURITY})  # ADR-0021/0037: chỉ khi ticket có risk_tags

    IN_FLIGHT = frozenset({"waiting", "dispatched", "in_progress", "in_review", "changes_requested"})

    def __init__(self, bus: InMemoryBus, gate: PersistentGate, max_retries: int = 3,
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
        # ADR-0037: nguồn sự thật cho phép giao ticket. Trước đây là human gate `plan`; nay là `_check_plan`
        # (orchestrator ghi plan_id vào đây ngay sau khi kiểm không ra problem nào). Vẫn là guard bằng CODE:
        # `dispatch` một plan_id lạ vẫn `PermissionError`, không phải "ai gọi cũng giao".
        self.plans_ok: set[str] = set()
        # ticket_id → event nguồn của kế hoạch (approved-specs/change-request): mọi `tasks` của ticket là con của nó,
        # để `correlation_id` nối từ yêu cầu tới PR thay vì mỗi lần giao là một gốc nhân quả mới (ib1-quansat Q1).
        self.cause: dict[str, Envelope] = {}
        # R6 (ADR gốc 0021 §f): nguồn đọc journal quality theo release, orchestrator gắn (`quality_flow.release_quality`).
        self.quality_source: Callable[[str], ReleaseQuality] | None = None
        self.reviews: dict[str, dict[str, ReviewResult]] = defaultdict(dict)
        self.review_since: dict[str, datetime] = {}
        self.releases: list[str] = []
        self.versions: dict[str, tuple[int, int, int]] = {}  # project_id → SemVer đã phát hành gần nhất
        self.release_tickets: dict[str, list[str]] = {}
        self.void_releases: set[str] = set()  # RC bị huỷ (xung đột tích hợp): ticket của nó phải vào RC mới, không "đã có RC"
        self.abandoned: set[str] = set()  # ticket người từ chối ở gate escalation: KHÔNG thoả depends_on của ticket khác
        self.release_qa: dict[str, ReviewResult] = {}
        self.release_reviews: dict[str, dict[str, ReviewResult]] = defaultdict(dict)
        # release_id → nguồn đã được NGƯỜI chấp nhận dù verdict != pass (finding không có code để sửa: DPIA, license,
        # IaC...). Tách khỏi ticket: trước đây MỌI lần release-review fail đều đá TOÀN BỘ ticket đã merged trong
        # release về changes_requested + đốt retry, kể cả khi finding chẳng liên quan gì tới code của ticket nào.
        # Đo được 2026-09-05: DPIA (RISK-6, không có code sửa được) làm QLKH-010/011/012/014 bị bounce lặp đi lặp
        # lại — dev sửa xong việc thật, code đã đúng, cứ bị hỏi lại vì lý do y hệt không phải của nó.
        self.release_waived: dict[str, set[str]] = defaultdict(set)
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
        if tid in self.abandoned: return False  # đóng vì bị bỏ, không phải vì xong: code của nó không tồn tại
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
        cause = self.cause.get(task.ticket_id)
        make = cause.child if cause is not None else Envelope
        self._emit(make(topic="tasks", key=task.ticket_id, actor=LEAD_ACTOR, payload=task.model_dump()))

    def dispatch(self, task: Task, plan_id: str, cause: Envelope | None = None) -> Task:
        """Ticket vào hàng chờ nếu phụ thuộc chưa xong; ngược lại publish ngay. Phụ thuộc phải là ticket đã biết."""
        if not self.replaying and plan_id not in self.plans_ok:
            raise PermissionError("plan chưa qua _check_plan")
        if task.estimate_tokens is not None and task.budget_tokens < task.estimate_tokens * BUDGET_FACTOR:
            raise ValueError(f"{task.ticket_id}: budget_tokens {task.budget_tokens} < estimate_tokens × {BUDGET_FACTOR}")
        unknown = [d for d in task.depends_on if d not in self.tickets and d != task.ticket_id]
        if unknown:
            raise ValueError(f"{task.ticket_id}: depends_on ticket chưa biết {unknown}")
        if task.ticket_id in task.depends_on:
            raise ValueError(f"{task.ticket_id}: tự phụ thuộc")
        self.tickets[task.ticket_id] = task; self.plan_of[task.ticket_id] = plan_id
        if cause is not None: self.cause[task.ticket_id] = cause
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
        nt = self.tickets[tid].model_copy(update={"hint": hint, "human_hint": hint}); self.tickets[tid] = nt
        if st == "in_review": self._set(tid, "changes_requested")
        elif st != "changes_requested": self.state[tid] = "changes_requested"  # dispatched/in_progress: agent chưa nộp gì
        self.review_since.pop(tid, None)
        self._publish_task(nt); return nt

    def _replay_task(self, env: Envelope) -> None:
        """Task phát lại (retry/rework/hint/reopen) không đi qua handler nào khi chạy thật — delivery-lead tự publish —
        nên trước đây khôi phục từ log không biết ticket đã bị trả về: ticket có đủ review pass cũ lại thành `approved`,
        ticket phụ thuộc được dispatch, nhánh trống sau `fresh()` được "tích hợp". Ở đây: task mới hơn (retry tăng hoặc
        hint đổi) của ticket đã biết → ticket về `dispatched` với task đó, review cũ bỏ."""
        t = Task.tu_log(env.payload)   # đường phát lại: bản ghi có thể mang `assignee` trước PR-5d
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
            self._set(tid, "blocked")
            # `blocked` phải BỀN, không chỉ nằm trong RAM: nó suy ra từ số lần retry chứ không từ event nào, nên
            # mở lại bus là mất. Khi đó ticket quay về `dispatched` (theo event `tasks` cuối), và người duyệt
            # escalation bấm approve thì `_on_escalation_decided` thấy state không phải blocked nên KHÔNG gọi
            # `reopen()` — không có task mới, không ai làm, mà `status` vẫn báo mọi chỉ số xanh.
            # Đo được khi chạy thật (2026-09-04): ticket QLKH-001 blocked lúc 11:17, orchestrator restart lúc
            # 11:29, gate được duyệt cùng lúc đó → `budget.extended` có ghi nhưng không có event `tasks` nào nữa;
            # dự án đứng im 8 phút với `stalled: -`, `blocked: -`, `queue: 0`.
            self._emit(Envelope(topic="audit-log", key=LEAD_ACTOR, actor=LEAD_ACTOR,
                                payload=AuditLog(actor=LEAD_ACTOR, action="ticket.blocked", ticket_id=tid,
                                                 evidence=json.dumps({"ticket_id": tid, "retry": t.retry + 1,
                                                                      "max_retries": self.max_retries},
                                                                     ensure_ascii=False)).model_dump()))
            return
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

    def void_release(self, rid: str) -> None:
        """Orchestrator huỷ RC (xung đột tích hợp, ticket bị trả về). Ticket đã approved trong RC đó không còn được
        coi là "đã có RC": khi gom release chúng phải vào RC kế tiếp, nếu không dự án đứng im không gate nào mở."""
        self.void_releases.add(rid)

    def unreleased(self, project_id: str) -> list[str]:
        """Ticket approved của dự án chưa nằm trong RC nào còn hiệu lực (RC bị huỷ không tính)."""
        in_rc = {t for rid, tids in self.release_tickets.items() if rid not in self.void_releases for t in tids}
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
        self._emit(Envelope(topic="release-candidates", key=rid, actor=LEAD_ACTOR,
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
        # ADR-0039: `deploy_failed` CỐ Ý không nằm trong tập dưới. `failed`/`rolled_back` nói "sản phẩm hỏng" nên
        # ticket quay về `changes_requested` cho kỹ sư làm lại; `deploy_failed` nói "chưa dựng được môi trường
        # chạy" — thường là hạ tầng máy trực (thiếu docker, cổng bận, compose của khách sai) chứ không phải code.
        # Trả 14 ticket về rework vì một cổng bận là đúng hình dạng lỗi mà ADR-0039 sinh ra để chấm dứt. Ticket
        # nằm yên, gate escalation của RC là chỗ người quyết (`verify.deploy_release`).
        elif p["status"] in {"rolled_back", "failed"}:
            for tid in self.release_tickets[rid]:
                if self.state.get(tid) in {"merged", "released"}:
                    self._set(tid, "changes_requested"); self._retry(tid, f"{rid} {p['status']} trên {p['env']}")

    def release_needs_security(self, rid: str) -> bool:
        return any(self.tickets[t].risk_tags for t in self.release_tickets.get(rid, []) if t in self.tickets)

    def _gate_kind_approved(self, subject_id: str, kind: str) -> bool:
        """Như `HumanGate.is_approved` nhưng CÓ phân biệt kind: escalation của một release và gate release (Gate 3)
        của CHÍNH release đó dùng chung `subject_id` (đọc rõ hơn trong `gate_cli`/`gate_brief` là REL-xxx), nên
        `is_approved` gốc (không phân biệt kind) coi duyệt escalation cũng là đã duyệt luôn Gate 3 — chặn gate
        release không bao giờ mở được nữa sau khi escalation được chấp nhận."""
        return any(g.subject_id == subject_id and g.kind == kind and g.decision == "approve" for g in self.gate.history)

    def _quality_evidence(self, kind: str, rid: str) -> tuple[QualityEvidence, QualityBar | None]:
        """ADR-0043: bằng chứng máy + mức nâng của dự án cho gate `kind` của `rid`. Không xác định được dự án →
        mức nâng `None` ⇒ `request_gate` không tự duyệt (thiếu → người)."""
        tickets = self.release_tickets.get(rid, [])
        pid = next((self.tickets[t].project_id for t in tickets if t in self.tickets), None)
        ev = collect_evidence(self.bus, kind, rid, tickets=tickets, needs_security=self.release_needs_security(rid),
                              waived=sorted(self.release_waived.get(rid, set())), history=self.gate.history,
                              quality=partial(self.quality_source, rid) if self.quality_source is not None else None)
        return ev, (project_bar(self.bus, pid) if pid else None)

    def _maybe_open_release_gate(self, rid: str) -> None:
        need = {SOURCE.QA} | ({SOURCE.SECURITY} if self.release_needs_security(rid) else set())
        got = {s for s, x in self.release_reviews[rid].items() if x.verdict == "pass"} | self.release_waived.get(rid, set())
        if need <= got and not self.replaying and rid not in self.gate.pending and not self._gate_kind_approved(rid, "release"):
            # `threat-model` và `architecture` dời từ gate plan cũ (ADR-0037): bỏ gate plan thì hai khoá đó phải
            # còn chỗ để người ký nhìn, và release là gate công đoạn cuối trước khi tiền thật đi ra.
            evidence, bar = self._quality_evidence("release", rid)
            request_gate(self.gate, GateRequest(kind="release", subject_id=rid, created_by=LEAD_ACTOR,
                                          checklist=["tests", "scan", "regression-staging", "perf", "a11y", "runbook",
                                                     "rollback", "threat-model", "architecture"]),
                         evidence=evidence, bar=bar)

    def _on_release_qa(self, r: ReviewResult) -> None:
        """Review trên release (ticket_id = release_id): QA hồi quy/perf/a11y trên staging, và security (DAST/license)
        khi release có ticket risk_tags. Đủ nguồn và tất cả pass (hoặc đã được người chấp nhận, xem `release_waived`)
        → mới xin gate 3. Fail mà chưa được chấp nhận → xin gate escalation cho CHÍNH RELEASE (không đụng ticket nào;
        xem `waive_release_findings`/`rework_release_tickets` — người quyết định có sửa code hay chấp nhận rủi ro)."""
        rid = r.ticket_id; self.release_reviews[rid][r.source] = r
        if r.source == SOURCE.QA: self.release_qa[rid] = r
        if r.verdict != "pass" and r.source not in self.release_waived.get(rid, set()):
            # Bằng chứng (finding của reviewer/qa/security) đã nằm trong topic `review-results`, `gate_brief` đọc
            # trực tiếp từ đó — không cần chép lại vào GateRequest.
            if not self.replaying and rid not in self.gate.pending and not self._gate_kind_approved(rid, "escalation"):
                request_gate(self.gate, GateRequest(kind="escalation", subject_id=rid, created_by=LEAD_ACTOR,
                                              checklist=["root_cause", "decision:reopen|close", "hint"]))
            return
        self._maybe_open_release_gate(rid)

    def waive_release_findings(self, rid: str) -> list[str]:
        """Người duyệt escalation của một RELEASE (không phải ticket riêng): finding không có code để sửa (compliance/
        policy như DPIA) được coi là rủi ro đã chấp nhận. KHÔNG đụng trạng thái ticket nào. Trả về các nguồn vừa được
        chấp nhận (để audit); đủ nguồn (pass + waived) thì mở luôn gate release cho Gate 3."""
        sources = sorted(s for s, x in self.release_reviews.get(rid, {}).items() if x.verdict != "pass")
        for s in sources:
            self.release_waived[rid].add(s)
            self._emit(Envelope(topic="audit-log", key=LEAD_ACTOR, actor=LEAD_ACTOR,
                                payload=AuditLog(actor=LEAD_ACTOR, action="release.finding_waived",
                                                 evidence=json.dumps({"release_id": rid, "source": s},
                                                                     ensure_ascii=False)).model_dump()))
        self._maybe_open_release_gate(rid)
        return sources

    def rework_release_tickets(self, rid: str, hint: str) -> None:
        """Người TỪ CHỐI escalation của release: finding LÀ lỗi code thật, không phải rủi ro chấp nhận được — đá các
        ticket đã merged trong release về changes_requested (hành vi cũ, giờ chỉ chạy khi người quyết định rõ ràng)."""
        for tid in self.release_tickets.get(rid, []):
            if self.state.get(tid) == "merged":
                self._set(tid, "changes_requested"); self._retry(tid, hint)

    def request_changes(self, tid: str, hint: str) -> None:
        """Ticket đã approved nhưng không tích hợp được (xung đột với nhánh tích hợp): làm lại với hint, tính một retry.
        Release candidate đang chứa ticket này do orchestrator huỷ (không đi tiếp). Dùng khi xung đột đã LẶP LẠI quá
        `MAX_CONFLICT_RETRIES` (orchestrator.py) — coi là bế tắc thật, tính vào retry nội dung như trước."""
        self._set(tid, "changes_requested"); self._retry(tid, hint)

    def request_changes_no_retry_bump(self, tid: str, hint: str) -> None:
        """Như `request_changes` nhưng KHÔNG tính vào retry nội dung: dùng khi xung đột merge còn dưới ngưỡng
        `MAX_CONFLICT_RETRIES` — ticket thua cuộc đua merge (ticket khác gộp trước lúc nó đang review) không phải
        lỗi của nó. Không giới hạn số lần: `orchestrator.conflict_retries` (đếm riêng, durable qua `_rehydrate`) mới
        là nơi quyết định khi nào xung đột lặp đủ nhiều để coi là bế tắc thật."""
        self._set(tid, "changes_requested")
        self.tickets[tid] = self.tickets[tid].model_copy(update={"hint": hint}); self._publish_task(self.tickets[tid])

    def continue_no_retry(self, tid: str, hint: str) -> None:
        """Agent hết lượt tool giữa chừng nhưng đã để lại tiến độ trong worktree: phát lại task với hint mới, KHÔNG
        tính retry — thiếu lượt không phải làm sai. Trần số lần do orchestrator giữ (`turn_continuations`)."""
        if self.state.get(tid) not in {"dispatched", "in_progress"}:
            raise ValueError(f"{tid}: làm tiếp chỉ từ dispatched/in_progress (đang {self.state.get(tid)})")
        self.state[tid] = "changes_requested"
        self.tickets[tid] = self.tickets[tid].model_copy(update={"hint": hint}); self._publish_task(self.tickets[tid])

    def blocked(self) -> list[str]:
        return [tid for tid, st in self.state.items() if st == "blocked"]

    def reopen(self, tid: str, hint: str) -> Task:
        """Người duyệt escalation: mở lại ticket blocked/escalated với hint, đếm retry lại từ 0."""
        if self.state.get(tid) not in {"blocked", "escalated"}:
            raise ValueError(f"{tid}: chỉ mở lại ticket blocked/escalated (đang {self.state.get(tid)})")
        nt = self.tickets[tid].model_copy(update={"retry": 0, "hint": hint, "human_hint": hint}); self.tickets[tid] = nt
        self._publish_task(nt); return nt

    def mark_done_already_integrated(self, tid: str) -> None:
        """Ticket mà code ĐÃ nằm trong nhánh tích hợp (orchestrator có `tid` trong `integrated`) nhưng sổ sách còn kẹt
        ở `blocked`/`changes_requested`: đưa thẳng về `merged`, KHÔNG giao lại cho agent.

        Đo được 2026-09-05/06 (QLKH): sau khi review cấp release chặn vì DPIA, các ticket đã merge bị đá về rework;
        agent chạy lại, đúng đắn thấy không còn gì để sửa nên không ghi file nào → `invalid_output` → hết retry →
        `blocked` → escalation → người duyệt → lặp lại. QLKH-010 quay 7 vòng, rồi 011/014 vào đúng vòng đó. Không có
        đường nào nói được "việc này xong rồi": `reopen` bắt làm lại việc đã merge, `close_escalated` thì bỏ ticket và
        chặn ticket phụ thuộc. Đây là đường thứ ba."""
        for dst in ("dispatched", "in_progress", "in_review", "approved", "merged"):
            if self.state.get(tid) == "merged":
                break
            if can_transition(self.state.get(tid, "draft"), dst):
                self._set(tid, dst)
        self.reviews.pop(tid, None); self.review_since.pop(tid, None)
        self._emit(Envelope(topic="audit-log", key=LEAD_ACTOR, actor=LEAD_ACTOR,
                            payload=AuditLog(actor=LEAD_ACTOR, action="ticket.already_integrated", ticket_id=tid,
                                             evidence=json.dumps({"ticket_id": tid, "state": self.state.get(tid)},
                                                                 ensure_ascii=False)).model_dump()))
        self._flush_waiting()

    def close_escalated(self, tid: str) -> list[str]:
        """Người từ chối escalation: ticket đóng không làm nữa. Trả về ticket phụ thuộc bị block theo (xem `abandon`)."""
        self._set(tid, "escalated"); self._set(tid, "closed")
        return self.abandon(tid)

    def abandon(self, tid: str) -> list[str]:
        """Ghi nhận ticket bị bỏ: `closed` nhưng KHÔNG thoả `depends_on` của ai. Ticket đang `waiting` vì nó chuyển
        sang `blocked` (mở gate escalation cho người quyết: bỏ nốt, hay mở lại với hint) thay vì được dispatch trên nền
        thiếu code — "hết ngưỡng thì escalate, không âm thầm đi tiếp". Dùng cả khi dựng lại từ log."""
        self.abandoned.add(tid)
        blocked = [t.ticket_id for t in self.tickets.values()
                   if tid in t.depends_on and self.state.get(t.ticket_id) == "waiting"]
        for dep in blocked: self._set(dep, "blocked")
        return blocked

    def close_accepted(self, rid: str) -> None:
        """ADR-0043 §3: nghiệm thu do MÁY duyệt (gate `UAT-*` qua `trusted_autoapprove`) — đóng ticket `released`
        của release như nhánh `accepted` của `_on_acceptance`, nhưng KHÔNG có `acceptance-results` nào (topic đó là
        chữ ký của khách, máy không ghi vào)."""
        for tid in self.release_tickets.get(rid, []):
            if self.state.get(tid) == "released":
                self._set(tid, "closed")

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
