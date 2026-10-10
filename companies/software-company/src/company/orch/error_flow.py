"""Xử lý lỗi agent sau một lượt: stall, rework, autoretry và escalation cuối.

Các hàm nhận ``o: Orchestrator`` rồi được gán làm method; chuyển nguyên đường xử lý lỗi
ra khỏi ``gates_flow`` để phần quyết định gate còn chỗ cho thay đổi tiếp theo (O4).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..events import Envelope
from ..gate_risk import request_gate
from ..gates import GateRequest
from ..roles import LEAD_ACTOR, ROLE
from .routes import MAX_TURN_CONTINUATIONS, RESEARCH_TOPICS, Route

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def _stall(o: Orchestrator, env: Envelope, agent: str, error: Exception, res: StepResult) -> bool:
    """Agent của chuỗi nghiên cứu lỗi → dự án không có bước kế tiếp. Ghi `project.stalled`, supervisor escalate
    (dự án bị hoãn mọi event), mở gate `escalation` subject=project_id. Ticket có cơ chế retry/blocked riêng.
    Trả True nếu nhánh này đã nhận trách nhiệm xử lý lỗi."""
    if env.topic not in RESEARCH_TOPICS: return False
    pid = str(env.payload.get("project_id") or env.key)
    with o._lock:
        o.stall_count[env.event_id] += 1; n = o.stall_count[env.event_id]
        o.stalled[pid] = {"project_id": pid, "event_id": env.event_id, "topic": env.topic, "agent": agent,
                             "error": str(error)[:300], "attempt": n}
    o._audit("project.stalled", o.stalled[pid], project_id=pid)
    o.supervisor.escalate_gate(pid, f"{agent} lỗi trên {env.topic} (lần {n}): {str(error)[:200]}",
                                  once_key=f"stall:{env.event_id}:{n}")
    if pid not in o.gate.pending:
        request_gate(o.gate, GateRequest(kind="escalation", subject_id=pid, created_by=ROLE.SUPERVISOR,
                                      checklist=["agent_error", "decision:retry|close"]))
    res.actions.append(f"stalled:{pid}:{agent}")
    return True

def _after_error(o: Orchestrator, env: Envelope, agent: str, error: Exception, r: Route, res: StepResult) -> None:
    """Mọi lỗi agent phải có người nhận: `_stall` lo chuỗi nghiên cứu, `_rework_after_error` lo agent sửa code.
    KHÔNG đường nào nhận thì đây là đường cuối — trước đây lỗi rơi vào im lặng: event vẫn bị `_mark` là đã xử
    lý, ticket treo nguyên trạng thái cũ, không gate nào mở, và `status` báo mọi chỉ số XANH trong khi dự án
    đã chết. Đo được khi chạy thật (2026-09-04): ba reviewer của `pull-requests:QLKH-001` cùng lỗi
    (`env.topic` không thuộc RESEARCH_TOPICS nên `_stall` bỏ qua, `r.tools != "rw"` nên `_rework_after_error`
    cũng bỏ qua) → 13 ticket phụ thuộc chờ vĩnh viễn mà không có một tín hiệu nào."""
    handled = o._stall(env, agent, error, res)
    handled = o._rework_after_error(env, r, error) or handled
    if handled: return
    o._mark_unhandled(env, agent, error, res)

def _mark_unhandled(o: Orchestrator, env: Envelope, agent: str, error: object, res: StepResult) -> None:
    """Đường cuối cho MỌI lỗi không nhánh nào nhận: ghi `unhandled` (bền qua `agent_error_unhandled`), supervisor
    escalate → gate `escalation` mở cho người; duyệt gate = chạy lại đúng event này (`_retry_unhandled`).
    Gọi từ `_after_error`, từ `_plan` khi lượt lập kế hoạch lỗi, từ `_threat_model` khi security chặn spec, và
    từ `_defer` khi một event hoãn `transient:` quá trần — bốn chỗ audit 2026-09-23 đo được là kết thúc im lặng."""
    from ..orchestrator import _evidence  # nhập lười, lý do như trong _on_gate_decide
    # `gate.decide` hoãn transient quá trần (`_defer`): `env.key` của audit-log là tên người ký, không phải việc bị bỏ.
    subject = str(_evidence(env.payload)["subject_id"] if env.topic == "audit-log" else env.payload.get("ticket_id") or env.key)
    rec = {"agent": agent, "topic": env.topic, "event_id": env.event_id, "subject": subject, "error": str(error)[:300]}
    with o._lock:
        o.unhandled[subject] = rec
        o.unhandled_count[env.event_id] += 1; n = o.unhandled_count[env.event_id]
    o._audit("agent_error_unhandled", rec, ticket_id=env.payload.get("ticket_id"), project_id=o.project_for(env))
    # Khoá once mang thế hệ `n` như `_stall`: duyệt retry rồi lỗi lại cùng event_id phải mở gate mới, không im lặng.
    o.supervisor.escalate_gate(subject, f"{agent} lỗi trên {env.topic}, không nhánh nào xử lý (lần {n}): {str(error)[:200]}",
                                  once_key=f"unhandled:{env.event_id}:{agent}:{n}")
    res.actions.append(f"unhandled:{subject}:{agent}")

def _rework_after_error(o: Orchestrator, env: Envelope, r: Route, error: Exception) -> bool:
    """Agent kỹ thuật lỗi (không sửa file, JSON hỏng, hết ngân sách lượt...) → ticket không được treo `dispatched`
    mãi: delivery-lead phát lại task retry+1 với hint là lỗi, hết retry → blocked → gate escalation.
    Trả True nếu nhánh này đã nhận trách nhiệm xử lý lỗi."""
    if r.tools != "rw": return False
    tid = str(env.payload.get("ticket_id") or env.key)
    if o.lead.state.get(tid) not in {"dispatched", "in_progress"}: return False
    if _continue_after_turn_cap(o, env, tid, error): return True
    try:
        o.lead.rework(tid, f"lần trước lỗi: {str(error)[:500]}")
    except ValueError as ex:
        o._audit("handler_error", {"agent": LEAD_ACTOR, "error": str(ex)[:300]}, ticket_id=tid)
    return True

def cli_subtype(error: object) -> str:
    """`subtype` của `claude -p` trong PHẦN ĐẦU thông điệp (`LLMError.head`, do adapter viết) — không soi phần chữ
    của model, để model viết "subtype=..." trong câu trả lời dở không đổi được cách xử lý lỗi."""
    m = re.search(r"subtype=([a-z_]+)", str(getattr(error, "head", "") or ""))
    return m.group(1) if m else ""

#: `subtype` của `claude -p` là trục trặc của lượt ép đầu ra, không phải nội dung sai: thử lại đúng một lần trước khi hỏi
#: người. Đo được 2026-09-24 (CAMPUS-UNI/REL-003): ops trên `release-candidates` chết một lần là gate escalation.
AUTORETRY_SUBTYPES = frozenset({"error_max_structured_output_retries"})

def _autoretry_once(o: Orchestrator, env: Envelope, agent: str, error: Exception, res: StepResult) -> bool:
    """Lỗi thuộc `AUTORETRY_SUBTYPES` lần ĐẦU cho (event, agent) → hoãn như `transient:` để nhịp sau chạy lại slot
    này (slot không vào `partial`). Khoá `once` bền qua restart; lần thứ hai đi `_after_error` như mọi lỗi khác."""
    key = f"autoretry:{env.event_id}:{agent}"
    if cli_subtype(error) not in AUTORETRY_SUBTYPES or key in o.once: return False
    o._remember(key)
    o._audit("llm.autoretry", {"agent": agent, "topic": env.topic, "event_id": env.event_id, "error": str(error)[:300]},
             ticket_id=env.payload.get("ticket_id"), project_id=o.project_for(env))
    res.actions.append(f"transient:{agent}:thử lại một lần sau {cli_subtype(error)}"); res.transient = True
    return True

def _continue_after_turn_cap(o: Orchestrator, env: Envelope, tid: str, error: Exception) -> bool:
    """Hết lượt tool mà lượt này CÓ sửa đổi chưa commit → làm tiếp từ WIP, không tính retry, tối đa
    `MAX_TURN_CONTINUATIONS` lần mỗi ticket. Worktree sạch = đi vòng tròn, không phải thiếu lượt → retry như cũ."""
    if cli_subtype(error) != "error_max_turns" or o.turn_continuations[tid] >= MAX_TURN_CONTINUATIONS: return False
    ws = o.workspace(tid)
    if ws is None or not ws.path.exists() or not ws.dirty(): return False
    with o._lock: o.turn_continuations[tid] += 1; n = o.turn_continuations[tid]
    o._audit("ticket.continued", {"ticket_id": tid, "attempt": n, "max": MAX_TURN_CONTINUATIONS, "error": str(error)[:300]},
             ticket_id=tid, project_id=o.project_for(env))
    o.lead.continue_no_retry(tid, f"làm tiếp lần {n}/{MAX_TURN_CONTINUATIONS}: lượt trước hết lượt tool (error_max_turns) "
                                  "giữa chừng; việc dở đã được giữ thành WIP trong worktree — xem git_status/git_diff, "
                                  "làm nốt phần còn thiếu, đừng làm lại từ đầu")
    return True
