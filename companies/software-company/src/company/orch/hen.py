"""Hẹn của backend cho một lượt agent gặp `TransientError`: mốc "resets 6:30pm" của `claude -p` hết phiên, "thử lại
sau Ns", và ticket nào đang nằm trong hẹn. Tách khỏi `scheduler.py` (trần 400 dòng mỗi module `orch/`) — dùng chung
cho `scheduler` (hoãn event, watchdog, giao lại review), `ticket_fsm` (plan, giả định làm rõ) và `orchestrator._call`.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..routing import reset_clock_seconds, retry_after_seconds

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def moc_reset(e: BaseException) -> float | None:
    """Số giây tới mốc "resets 6:30pm (Asia/Bangkok)" của `claude -p` hết phiên, đọc trên thông điệp ĐẦY ĐỦ — chuỗi
    action `transient:` cắt 120 ký tự làm rơi đúng phần mốc giờ (sự cố hub 2026-10-13)."""
    return reset_clock_seconds(str(e), time.time())


def ghi_transient(res: StepResult, agent: str, e: BaseException) -> None:
    """Một lượt agent hết retry transport: ghi action `transient:` (cắt 120 ký tự cho audit) và mốc reset đọc trên
    thông điệp đầy đủ — `_defer_transient` hoãn theo đó ở cuối `process()`."""
    res.actions.append(f"transient:{agent}:{str(e)[:120]}"); res.transient = True; res.reset_s = moc_reset(e)


def trong_hen(o: Orchestrator) -> set[str]:
    """Ticket có event đang nằm trong hẹn `defer_until` của backend (hết phiên tới mốc reset, "thử lại sau Ns"):
    đang CHỜ có chủ đích — watchdog không đếm im lặng, review quá hạn không giao lại."""
    mono = time.monotonic()
    out: set[str] = set()
    for eid, (env, _) in list(o.deferred.items()):
        cho = env.payload.get("ticket_id") or (env.key if env.topic == "tasks" else None)
        if cho and o.defer_until.get(eid, 0.0) > mono: out.add(str(cho))
    return out


def cho_hen(res: StepResult) -> float | None:
    """Số giây backend hẹn cho một lượt `transient`: "thử lại sau Ns" trong action, hoặc mốc reset phiên
    (`res.reset_s`, đọc trên thông điệp đầy đủ) — lấy mốc xa hơn. None khi backend không hẹn."""
    stuck = next((a for a in res.actions if a.startswith("transient:")), "transient:?")
    wait = retry_after_seconds(stuck)
    return max(wait or 0.0, res.reset_s) if res.reset_s is not None else wait
