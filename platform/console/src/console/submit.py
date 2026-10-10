"""Giao việc cho công ty THẬT: nạp event do người tạo vào bus SQLite của xưởng tương ứng.

Console không có "đường tắt" nào: nó publish đúng `Envelope` qua đúng `SQLiteBus` của công ty, nên payload
được kiểm theo JSON Schema của topic (`topics/schemas/*.json`) y như CLI `python -m company.orchestrator publish`.
Chỉ nhận những topic do NGƯỜI nạp (`FORMS`); topic của agent hay `audit-log` (quyết định gate) không đi qua đây —
gate có `decide.py` riêng, đúng lớp `HumanGate`.

Mọi lỗi người dùng thấy được đổi thành `ValueError` (tham số sai, 400) hoặc `SubmitError` (bus từ chối, kèm
`http_status`) với thông điệp tiếng Việt để `server.py` trả mã HTTP đúng nghĩa.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from company.bus import BusError as CompanyBusError
from company.events import Envelope as CompanyEnvelope
from company.sqlite_bus import SQLiteBus as CompanyBus

from console.decide import COMPANY, KEEPER, XUONG, actor_problem

# topic người nạp được → trường payload dùng làm `key` của envelope (cùng quy ước với CLI `publish` của công ty:
# software-company lấy project_id).
FORMS: dict[str, dict[str, str]] = {
    COMPANY: {"research-requests": "project_id", "clarification-answers": "project_id"},
    # `maintenance-signals` là topic DUY NHẤT người nạp tay được của `keeper` (`keeper.core.HUMAN_TOPICS`):
    # ticket bảo trì phải đi qua `triager` để có `risk_tier`, nên không có form nào cho `maintenance-tickets`.
    KEEPER: {"maintenance-signals": "subject"},
}


def _bus_for(xuong: str, db: Path) -> tuple[Any, Any, type[Exception]]:
    """(bus bền vững, lớp Envelope, lớp lỗi bus) của đúng xưởng. `keeper` nhập trễ vì `KeeperBus` cần `CORE`
    của nó — một phụ thuộc chỉ có nghĩa khi thật sự nạp việc cho công ty bảo trì."""
    if xuong == COMPANY:
        return CompanyBus(db), CompanyEnvelope, CompanyBusError
    from keeper.bus import KeeperBus
    from keeper.core import CORE as KEEPER_CORE
    from keeper.events import Envelope as KeeperEnvelope
    from xagents_core.bus import BusError as KeeperBusError
    return KeeperBus(KEEPER_CORE, db), KeeperEnvelope, KeeperBusError


class SubmitError(Exception):
    """Bus của công ty từ chối event (payload sai schema, topic không có schema...)."""

    def __init__(self, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.http_status = http_status


def submit(company_db: Path | None, keeper_db: Path | None = None, *,
           xuong: str, topic: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
    """Publish một event do người tạo. Trả `{"ok", "xuong", "topic", "key", "event_id"}`.

    `ValueError` khi `xuong`/`topic`/`payload`/`actor` sai; `SubmitError` khi bus từ chối. File bus chưa có thì
    được tạo (như CLI `publish`): yêu cầu đầu tiên của một công ty chưa chạy lần nào là chuyện bình thường."""
    if xuong not in XUONG:
        raise ValueError(f"xưởng lạ: {xuong} (chỉ nhận {' | '.join(XUONG)})")
    allowed = FORMS[xuong]
    if topic not in allowed:
        raise ValueError(f"topic {topic!r} không nạp tay được cho {xuong} (chỉ nhận {' | '.join(sorted(allowed))})")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("payload phải là một object JSON không rỗng")
    actor = (actor or "").strip()
    if not actor:
        raise ValueError("thiếu người giao việc (`actor`)")
    if (why := actor_problem(actor, "actor")) is not None:
        raise ValueError(why)
    key = str(payload.get(allowed[topic]) or "").strip()
    if not key:
        raise ValueError(f"payload thiếu `{allowed[topic]}` (dùng làm key của {topic})")
    db = {COMPANY: company_db, KEEPER: keeper_db}[xuong]
    if db is None:
        raise ValueError(f"console chạy không có đường dẫn bus của {xuong} "
                         f"(--company-db / --keeper-db)")

    Path(db).parent.mkdir(parents=True, exist_ok=True)
    bus, env_cls, bus_error = _bus_for(xuong, Path(db))
    try:
        env = bus.publish(env_cls(topic=topic, key=key, actor=actor, payload=payload))
    except bus_error as e:
        raise SubmitError(str(e)) from e
    finally:
        bus.close()
    return {"ok": True, "xuong": xuong, "topic": topic, "key": key, "event_id": env.event_id}
