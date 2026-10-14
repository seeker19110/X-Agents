"""ADR gốc 0038: câu trả lời làm rõ của agent đại diện khách (`reviewer:*`) chỉ được tính khi cờ + `toan-bo` bật.

Cùng chiều tin với change request (ADR gốc 0035, `gate_reviewer.cr_trusted`): bus cho `reviewer:*` ghi
`clarification-answers`, còn tin hay không thì đọc lại cờ mỗi lần — bỏ biến môi trường là câu trả lời của reviewer thôi
được tính khi replay. Tách khỏi `guards.py` vì module đó đứng đúng trần 400 dòng (`test_orch_khuon_loi.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..events import Envelope

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator


def trusted(env: Envelope) -> bool:
    """Câu trả lời này có được tính không: người luôn được; `reviewer:*` chỉ khi cờ + `toan-bo` đang bật."""
    from ..gate_reviewer import cr_trusted  # nhập lười: cùng lý do với `guards._cr_accepted`

    return cr_trusted(env)


def answers_trusted(e: Envelope, o: Orchestrator) -> bool:
    """Như `trusted`, cộng một audit `clarification.untrusted` mỗi event bị bỏ — để người thấy vì sao dự án đứng."""
    from ..gate_reviewer import cr_actor_refusal

    if trusted(e):
        return True
    o._audit(
        "clarification.untrusted",
        {"event_id": e.event_id, "actor": e.actor, "reason": cr_actor_refusal(e.actor)},
        once=f"answers_untrusted:{e.event_id}",
        project_id=e.payload.get("project_id"),
    )
    return False
