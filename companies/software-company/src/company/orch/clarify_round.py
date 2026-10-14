"""`round` của `clarification-questions` do CODE đếm trên bus, không do model khai.

Vòng hỏi là IDENTITY CỦA LƯỢT — cùng nhóm "code điền" của `CLAUDE.md` ranh giới 1 với `source` của review
(`review_source.py`): bus biết chắc dự án đã được hỏi mấy lần. Và nó không phải nhãn trang trí: `_answers_incomplete`
(`guards.py`) đọc `round >= MAX_CLARIFY_ROUNDS` để quyết còn được hỏi lại hay phải sang spec.

Đo 2026-10-12 (QLKH-DD-CSV, model thật): lần hỏi ĐẦU TIÊN, `product` khai `round: 2` — vòng hỏi lại bị xoá im
lặng. Chiều ngược lại (khai `1` mãi) thì trả lời thiếu là hỏi lại vô hạn.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..events import Envelope
from .guards import MAX_CLARIFY_ROUNDS
from .routes import Route

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator


def enforce_round(o: Orchestrator, r: Route, p: Mapping[str, Any], env: Envelope, agent: str) -> dict[str, Any]:
    """Ghi đè `round` của một `clarification-questions` bằng số vòng đã hỏi trên bus + 1 (trần `MAX_CLARIFY_ROUNDS`
    theo schema), và để lại vết `clarification.round_overridden` nếu model khai khác. Topic khác: trả nguyên."""
    if r.topic_out != "clarification-questions":
        return dict(p)
    pid = str(p.get("project_id") or env.key)
    # đếm theo key của CHUỖI (đầu ra giữ key event nguồn): CR đổi requirement có chuỗi riêng, khoá bằng mã CR
    da_hoi = sum(1 for _ in o.bus.replay(topic="clarification-questions", key=env.key))
    vong = min(da_hoi + 1, MAX_CLARIFY_ROUNDS)
    if p.get("round") == vong:
        return dict(p)
    o._audit(
        "clarification.round_overridden", {"claimed_round": p.get("round"), "round": vong}, actor=agent, project_id=pid
    )
    return {**p, "round": vong}
