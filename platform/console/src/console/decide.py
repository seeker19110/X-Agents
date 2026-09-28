"""Ghi quyết định gate THẬT qua `HumanGate` của từng công ty.

Console không tự dựng event `gate.decide`: nó mở đúng `PersistentGate` của xưởng tương ứng và gọi `decide(...)`, để
four-eyes (người duyệt khác người tạo), allowlist người duyệt và bản ghi `audit-log` đều đi qua đúng đường của repo.
Mọi lỗi người dùng thấy được đổi thành `GateError` với thông điệp tiếng Việt để `server.py` chuyển sang HTTP 4xx.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

from company import gate_cli as company_gate_cli
from company.gates import Decision as CompanyDecision
from company.gates import gate_approvers as company_gate_approvers
from company.sqlite_bus import SQLiteBus as CompanyBus
from xagents_core.bus import is_human

COMPANY = "software-company"
KEEPER = "keeper"
XUONG = (COMPANY, KEEPER)


class GateError(Exception):
    """Quyết định gate không thực hiện được (thiếu DB, không có gate chờ, bị four-eyes/allowlist chặn)."""


def _decisions(literal: Any) -> tuple[str, ...]:
    """Verb hợp lệ của một công ty = `Decision` của công ty đó trừ `pending` (không ai "quyết định" là chờ tiếp)."""
    return tuple(d for d in get_args(literal) if d != "pending")


def _keeper_gate(bus: Any) -> Any:
    """Gate của công ty bảo trì mang allowlist `KEEPER_GATE_APPROVERS` (`keeper.gates.gate_approvers`) — cùng
    đường mà `keeper gate <quyết định>` của người đi qua. Không đặt biến → tập rỗng → chỉ còn four-eyes."""
    from keeper.gates import PersistentGate as KeeperPersistentGate
    from keeper.gates import gate_approvers as keeper_gate_approvers
    return KeeperPersistentGate(bus, approvers=keeper_gate_approvers())


def _company_gate(bus: Any) -> Any:
    """Gate của công ty gia công mang theo allowlist người duyệt (`COMPANY_GATE_APPROVERS`, K3.7)."""
    return company_gate_cli.PersistentGate(bus, approvers=company_gate_approvers())


def _bus(xuong: str, db: Path) -> Any:
    """Bus BỀN VỮNG của đúng xưởng — ghi quyết định thì phải ghi vào file, khác `collect.py` (chỉ đọc)."""
    if xuong == COMPANY:
        return CompanyBus(db)
    from keeper.bus import KeeperBus
    from keeper.core import CORE as KEEPER_CORE
    return KeeperBus(KEEPER_CORE, db)


def decide(company_db: Path | None, keeper_db: Path | None = None, *,
           subject_id: str, xuong: str, decision: str, by: str, reason: str) -> dict[str, Any]:
    """Duyệt/từ chối một gate đang chờ. Trả `{"ok", "subject_id", "decision", "event_id"}`.

    `ValueError` khi `xuong` hoặc `decision` sai; `GateError` (thông điệp tiếng Việt) cho mọi lỗi còn lại."""
    if xuong not in XUONG:
        raise ValueError(f"xưởng lạ: {xuong} (chỉ nhận {' | '.join(XUONG)})")
    from keeper.gates import Decision as KeeperDecision
    db = {COMPANY: company_db, KEEPER: keeper_db}[xuong]
    allowed = _decisions({COMPANY: CompanyDecision, KEEPER: KeeperDecision}[xuong])
    if decision not in allowed:
        raise ValueError(f"quyết định lạ: {decision} (chỉ nhận {' | '.join(allowed)})")
    if not subject_id.strip():
        raise ValueError("thiếu subject_id")
    if not by.strip():
        raise ValueError("thiếu người duyệt (`by`)")
    if not is_human(by):
        # Audit 2026-09-27 (F-A): ô "Bạn là" là chữ tự do. `by` không hình người thì bản ghi hoặc bị ACL bus của
        # company chặn bằng `PermissionDenied` (không phải `PermissionError` ⇒ HTTP 500), hoặc lọt bus (`reviewer:*`,
        # `orchestrator`, mọi tên ở keeper) rồi bị `trusted_decision` bỏ ở mọi tiến trình khác — trả `ok` mà gate
        # vẫn chờ. Reviewer có chữ ký đi `company.gate_reviewer`, không qua console.
        raise ValueError(f"người duyệt {by!r} không phải người (`human` / `human:<tên>`) — "
                         "console chỉ ghi quyết định của người")
    if db is None or not Path(db).exists():
        raise GateError(f"chưa có file DB của {xuong}: {db or '(chưa cấu hình)'}")

    bus = _bus(xuong, Path(db))
    try:
        # ADR gốc 0021 quyết định 2: console không nhận file profile ⇒ dự án đã có profile thì không ký SPEC ở đây.
        if xuong == COMPANY and (why := company_gate_cli.require_profile_for_spec(
                bus, subject_id, decision, has_profile_arg=False)) is not None:
            raise GateError(why)
        gate = {COMPANY: _company_gate, KEEPER: _keeper_gate}[xuong](bus)
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
