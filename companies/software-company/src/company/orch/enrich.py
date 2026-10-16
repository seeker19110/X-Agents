"""Enrich của bảng route: làm giàu payload trước khi giao cho agent (tách khỏi `routes.py`, ADR-0034).

Tách cùng lý do `guards.py`. Ranh giới giữ đúng một chiều: `routes.py` nhập từ đây, đây không nhập `routes.py`.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..events import Envelope
from ..llm import LLMError
from ..roles import FINDING_KIND, ROLE
from ..workspace import WorkspaceError

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator


# Trường bị gỡ khỏi payload trước khi đưa cho test-author (ADR-0028: lượt MÙ). `hint` là phản hồi review vòng
# trước — nó nói về CODE, đọc nó là hết mù.
BLIND_STRIP = frozenset({"hint", "retry", "test_suite", "diff", "chan_doan"})


def _with_draft(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    d = o.latest("requirements-draft", e.key)  # key của CHUỖI: dự án, hoặc mã CR khi CR đổi requirement
    return {"requirements_draft": d.payload} if d else {}


def _with_intake(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """Pha `spec` cần CẢ báo cáo của pha `intake` lẫn báo cáo 4 mục của pha `research` (ADR-0006), nhưng nó chỉ được
    đánh thức bởi báo cáo của pha `research`. Không đính kèm đề bài của pha `intake` thì tiêu chí bắt đầu không bao
    giờ đủ và draft luôn rỗng."""
    key = e.key  # chuỗi của CR khoá bằng mã CR — tra theo project_id là lấy intake CŨ của cả dự án (hub 2026-10-14)
    found = [x for x in o.bus.replay("research-findings", key) if x.payload.get("kind") == FINDING_KIND.INTAKE]
    return {FINDING_KIND.INTAKE: found[-1].payload.get("data")} if found and found[-1].payload.get("data") else {}


def _with_diff(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """Reviewer/QA/security đọc diff thật của branch ticket (khi có repo) thay vì tin `summary` của PR."""
    ws = o.workspace(e.payload.get("ticket_id") or e.key)
    if ws is None or not ws.path.exists(): return {}
    try: return {"diff": ws.diff(), "changed_files": ws.changed_files()}
    except WorkspaceError as ex: return {"diff_error": str(ex)[:300]}


def _with_chan_doan(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """qa-debugger nhận thêm LỊCH SỬ HỎNG của chính ticket này, phạm vi hẹp và chỉ-đọc.

    Agent chỉ thấy PR trước mặt nên mỗi vòng lại chẩn đoán từ đầu, không biết mình đang xem lần thứ mấy. Đo
    được ở lần chạy thật 2026-09-04: QLKH-001 quay 8 vòng với `blocked 3× / reopen 8× / review_block 13×`, và
    179/193 lỗi của cả dự án là CÙNG MỘT sự cố hết quota — không agent nào biết điều đó vì chỉ `supervisor`
    đăng ký đọc `audit-log`.

    Cố ý bơm bản LÁT CẮT THEO TICKET chứ không phải toàn cảnh: khuôn lỗi của dự án khác là nhiễu cho việc chấm
    một PR, và `max_input_chars` của qa-debugger chỉ có 50k. Vẫn chỉ-đọc: agent không được cấp thêm tool nào,
    không sửa được mã công ty — đây là bậc thấp nhất có ích, để kiểm xem nó chẩn đoán có đúng không trước khi
    tính chuyện cho nhiều quyền hơn."""
    tid = str(e.payload.get("ticket_id") or e.key)
    try:
        from ..metrics import diagnose
        d = diagnose(o.bus, top=30)
    except Exception as ex:  # chẩn đoán hỏng không được làm hỏng lượt review
        return {"chan_doan_error": str(ex)[:200]}
    vong = d["ticket_quay_vong"].get(tid)
    khuon = [k for k in d["loi_theo_khuon"] if tid in k["tickets"]][:3]
    if not vong and not khuon: return {}
    return {"chan_doan": {"lich_su_ticket": vong, "khuon_loi_cua_ticket": khuon,
                          "gate_dang_cho": d["gate"]["dang_cho"]}}


def _with_task(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """Assignee nhận lại toàn bộ ticket (acceptance, scope, hint...) kèm bộ test vừa được viết."""
    t = o.latest("tasks", str(e.payload.get("ticket_id") or e.key))
    base = dict(t.payload) if t is not None else {}
    return {**base, "test_suite": {k: e.payload.get(k) for k in ("files", "acceptance_covered", "tests_status", "commit", "notes")},
            "tests_authored_by": ROLE.QA}


DEBATE_ACTOR = "roleplay"  # actor của audit `research.debate`: không phải agent, không có front matter


def _with_debate(e: Envelope, o: Orchestrator) -> dict[str, Any]:
    """ADR-0050: phiên đề xuất/phản biện chạy TRƯỚC lượt research, kết quả vào `debate` của payload. Khoá theo
    event nguồn và đọc từ bus: cùng event xử lý lại (restart, `_recall`) lấy audit `research.debate` cũ, không tốn
    lượt model nữa (khuôn 2 `TRAPS.md`). Lỗi model của phiên không làm hỏng lượt research — nó chỉ thiếu `debate`
    và mang `debate_error`; `TransientError` thì để lan ra cho `_call` hoãn event như mọi lượt khác."""
    rp = o.roleplay
    if rp is None: return {}
    pid = str(e.payload.get("project_id") or e.key)
    for a in o.bus.replay(topic="audit-log"):
        if a.payload.get("action") != "research.debate": continue
        ev = json.loads(a.payload.get("evidence") or "{}")
        if ev.get("source_event") == e.event_id:
            return {"debate": {k: ev.get(k) for k in ("proposals", "objections", "open_questions", "stopped_by", "tokens")}
                    | {"turns": len(ev.get("turns") or [])}}
    try:
        d = rp.run({k: v for k, v in e.payload.items() if k != "project_id"} | {"project_id": pid})
    except LLMError as ex:
        o._audit("research.debate_failed", {"source_event": e.event_id, "error": str(ex)[:300]}, actor=DEBATE_ACTOR,
                 project_id=pid)
        return {"debate_error": f"{type(ex).__name__}: {ex}"[:300]}
    o._audit("research.debate", {**d.as_audit(), "source_event": e.event_id}, actor=DEBATE_ACTOR, tokens=d.tokens,
             cost=d.cost_usd, project_id=pid)
    return {"debate": d.summary()}



def _with_deploy_readiness(e: Envelope, o: Orchestrator) -> dict[str, object]:
    """Sự thật MÁY về việc dựng staging cho lượt `ops` (ADR-0061 bổ sung 2026-10-16) — xem `deploy.readiness`."""
    from ..deploy import readiness
    from ..smoke import parse_runtime
    from .verify import project_spec
    pid = o.project_for(e) or str(e.payload.get("project_id") or "")
    integ, spec = o.integration_for(pid), project_spec(o, pid) if pid else None
    rt = parse_runtime(spec.payload if spec is not None else None)
    return {"deploy_readiness": readiness(integ.path if integ is not None else None, pid, rt)}
