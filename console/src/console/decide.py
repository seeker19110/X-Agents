"""Ghi quyết định gate THẬT qua `HumanGate` của từng công ty.

Console không tự dựng event `gate.decide`: nó mở đúng `PersistentGate` của xưởng tương ứng và gọi `decide(...)`, để
four-eyes (người duyệt khác người tạo), allowlist người duyệt (`STUDIO_GATE_APPROVERS` / `media.yaml`) và bản ghi
`audit-log` đều đi qua đúng đường của repo. Mọi lỗi người dùng thấy được đổi thành `GateError` với thông điệp tiếng
Việt để `server.py` chuyển sang HTTP 4xx.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

from company import gate_cli as company_gate_cli
from company.gates import Decision as CompanyDecision
from company.sqlite_bus import SQLiteBus as CompanyBus
from studio import gate_cli as studio_gate_cli
from studio.gates import Decision as StudioDecision
from studio.gates import gate_approvers
from studio.sqlite_bus import SQLiteBus as StudioBus

COMPANY = "software-company"
STUDIO = "Studio-creators"
XUONG = (COMPANY, STUDIO)


class GateError(Exception):
    """Quyết định gate không thực hiện được (thiếu DB, không có gate chờ, bị four-eyes/allowlist chặn)."""


def _decisions(literal: Any) -> tuple[str, ...]:
    """Verb hợp lệ của một công ty = `Decision` của công ty đó trừ `pending` (không ai "quyết định" là chờ tiếp)."""
    return tuple(d for d in get_args(literal) if d != "pending")


def _studio_gate(bus: Any) -> Any:
    """Gate của xưởng video mang theo allowlist người duyệt như `studio.gate_cli` dựng."""
    try:
        from studio.media import load_media_config
        cfg = load_media_config()
    except Exception:
        cfg = None
    return studio_gate_cli.PersistentGate(bus, approvers=gate_approvers(cfg))


def decide(company_db: Path | None, studio_db: Path | None, *,
           subject_id: str, xuong: str, decision: str, by: str, reason: str) -> dict[str, Any]:
    """Duyệt/từ chối một gate đang chờ. Trả `{"ok", "subject_id", "decision", "event_id"}`.

    `ValueError` khi `xuong` hoặc `decision` sai; `GateError` (thông điệp tiếng Việt) cho mọi lỗi còn lại."""
    if xuong not in XUONG:
        raise ValueError(f"xưởng lạ: {xuong} (chỉ nhận {' | '.join(XUONG)})")
    db = company_db if xuong == COMPANY else studio_db
    allowed = _decisions(CompanyDecision if xuong == COMPANY else StudioDecision)
    if decision not in allowed:
        raise ValueError(f"quyết định lạ: {decision} (chỉ nhận {' | '.join(allowed)})")
    if not subject_id.strip():
        raise ValueError("thiếu subject_id")
    if not by.strip():
        raise ValueError("thiếu người duyệt (`by`)")
    if db is None or not Path(db).exists():
        raise GateError(f"chưa có file DB của {xuong}: {db or '(chưa cấu hình)'}")

    bus = CompanyBus(Path(db)) if xuong == COMPANY else StudioBus(Path(db))
    try:
        gate = company_gate_cli.PersistentGate(bus) if xuong == COMPANY else _studio_gate(bus)
        written: list[Any] = []
        bus.subscribe("audit-log", written.append)  # bắt chính envelope gate.decide mà gate vừa ghi
        try:
            gate.decide(subject_id, decision, by=by, reason=reason)
        except KeyError as e:
            raise GateError(f"không có gate chờ: {subject_id}") from e
        except PermissionError as e:
            raise GateError(str(e)) from e
        event_id = next((e.event_id for e in reversed(written)
                         if e.payload.get("action") == "gate.decide"), None)
        return {"ok": True, "subject_id": subject_id, "decision": decision, "event_id": event_id}
    finally:
        bus.close()
