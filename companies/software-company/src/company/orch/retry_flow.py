"""Chạy lại việc đã dừng (ADR-0034; tách khỏi `gates_flow.py` khi module đó chạm trần 400 dòng của
`test_orch_khuon_loi.py`): event dự án kẹt (`stalled`) hay lỗi không nhánh nào nhận (`unhandled`) mà người cho chạy
lại, và `gate.decide` đã áp tác dụng nhưng lượt agent nó gọi bị hoãn transient (`DECIDE_APPLIED`).

Cùng khuôn với `gates_flow`: mỗi hàm nhận `o: Orchestrator` làm tham số đầu.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from ..gates import GateKind
from ..roles import ROLE
from .routes import PROD_ROUTE, REVIEW_AGENT, review_route

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


#: Khoá `once` cho một `gate.decide` đã áp tác dụng mà lượt agent nó gọi bị hoãn transient: `decide.applied:<event_id>:<kind>`.
#: Lần xử lý lại chỉ gọi lại lượt agent (`_retry_decide_calls`), không đếm lại, không áp lại tác dụng. Bền qua restart
#: (`once` dựng lại từ audit) vì `_rehydrate` đẩy event chưa `processed` vào hàng đợi và đếm theo khoá này.
DECIDE_APPLIED = "decide.applied"


def decide_applied(once: set[str], event_id: str) -> str | None:
    """Loại gate gắn lúc `gate.decide` này bị hoãn; `None` = chưa áp lần nào."""
    return next((k for k in (*get_args(GateKind), "None") if f"{DECIDE_APPLIED}:{event_id}:{k}" in once), None)


def _deploy_production(o: Orchestrator, rid: str, res: StepResult) -> None:
    """Gate 3 đã ký → lượt ops production trên RC mới nhất của release."""
    if rid in o.lead.release_tickets:
        rc = o.latest("release-candidates", rid)
        if rc is not None:
            o._recall(ROLE.OPS, rc)  # ký lại gate release phải chạy lại được lượt production
            o._call(ROLE.OPS, rc, PROD_ROUTE, res)

def _retry_decide_calls(o: Orchestrator, kind: str, sid: str, by: str, reason: str, res: StepResult) -> None:
    """Xử lý lại `gate.decide` đã áp (khoá `DECIDE_APPLIED`): chỉ gọi lại lượt agent của quyết định — đúng ba chỗ có
    `_call` dưới nhánh `approve` — không cấp ngân sách, reopen, waive hay `resume` lần hai."""
    if kind != "escalation":
        _deploy_production(o, sid, res)
    elif sid in o.lead.release_tickets:
        o._rerun_release(sid, by, reason, res)
    else:
        _rerun_missing_reviews(o, sid, by, res)

def _rerun_missing_reviews(o: Orchestrator, tid: str, by: str, res: StepResult) -> None:
    """Gọi lại đúng nguồn review còn thiếu trên PR mới nhất; `partial` giữ cho reviewer/qa đã chấm không chạy lại."""
    if o.lead.state.get(tid) == "in_review" and (pr := o.latest("pull-requests", tid)) is not None:
        for src in sorted(o.lead.required_reviews(tid) - set(o.lead.reviews.get(tid, {}))):
            o._audit("review.rerun", {"ticket_id": tid, "source": src, "by": by}, ticket_id=tid,
                        project_id=o.project_for(pr))
            o._call(REVIEW_AGENT[src], pr, review_route(REVIEW_AGENT[src]), res)

def _retry_stalled(o: Orchestrator, pid: str, by: str, reason: str) -> bool:
    """Người duyệt gate escalation của dự án: chạy lại event đã lỗi (bỏ dấu đã xử lý, đưa về đầu hàng đợi)."""
    st = o.stalled.get(pid)
    if st is None: return False
    env = next((e for e in o.bus.replay(topic=st["topic"], key=pid) if e.event_id == st["event_id"]), None)
    if env is None: return False
    with o._lock:
        o.processed.discard(env.event_id); o.partial.pop(env.event_id, None); o.stalled.pop(pid, None)
    o._audit("project.retried", {**st, "by": by, "reason": reason}, project_id=pid)
    with o._qlock: o.queue.insert(0, env)
    return True

def _retry_unhandled(o: Orchestrator, subject: str, by: str, reason: str) -> bool:
    """Như `_retry_stalled` nhưng cho event bất kỳ mà agent lỗi không nhánh nào nhận (`unhandled`)."""
    rec = o.unhandled.get(subject)
    if rec is None: return False
    env = next((e for e in o.bus.replay(topic=str(rec["topic"])) if e.event_id == rec["event_id"]), None)
    if env is None: return False
    with o._lock:
        o.processed.discard(env.event_id); o.partial.pop(env.event_id, None); o.unhandled.pop(subject, None)
        o.spec_runtime_reworks.pop(subject, None)  # người cho chạy lại → spec-writer được thêm một lượt sửa tự động
        o.plan_reworks.pop(str(rec["event_id"]), None)  # ... và `product[plan]` được thêm `PLAN_REWORKS` lượt
    o._audit("event.retried", {**rec, "subject": subject, "by": by, "reason": reason[:300]}, project_id=o.project_for(env))
    with o._qlock: o.queue.insert(0, env)
    return True
