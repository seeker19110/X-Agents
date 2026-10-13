"""ADR gốc 0037: agent duyệt tự động quyết change request do MÁY nộp (`REPLAN-*`, `REWORK-*`, `GATE3-*`).

Ba đường tự sửa (ADR-0051/0057/0058 company) dừng ở `decide-change`; agent duyệt tự động (ADR gốc 0034) chỉ đi qua gate.
Module này cho nó xét thêm CR: chỉ CR của `delivery-lead`, đúng ba loại impact, đã có `change.impact` của product, và chỉ
ở phạm vi `toan-bo` (ngoài phạm vi đó orchestrator không tin quyết định CR của reviewer — `cr_trusted`). Quyết định ghi
qua `publish_decision`, đúng hàm CLI `decide-change` dùng; không quyết được thì `reviewer.cr_hold` cho phiên chính.
"""

from __future__ import annotations

import json
from typing import Any

from .events import AuditLog, Envelope
from .roles import LEAD_ACTOR, ROLE

MACHINE_KINDS = frozenset({"replan", "rework_no_change", "release_gate_reject"})
CR_HOLD_ACTION = "reviewer.cr_hold"
CR_DECISIONS = ("accepted", "rejected", "hold")
CR_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(CR_DECISIONS)},
        "root_cause": {"type": "string"},
        "hint": {"type": "string"},
    },
    "required": ["decision", "root_cause", "hint"],
    "additionalProperties": False,
}


def _ev(env: Envelope) -> dict[str, Any]:
    try:
        d = json.loads(env.payload.get("evidence") or "{}")
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _latest(bus: Any) -> dict[str, Envelope]:
    out: dict[str, Envelope] = {}
    for e in bus.replay(topic="change-requests"):
        out[e.key] = e
    return out


def _impact(bus: Any, cid: str) -> str | None:
    """Impact product đã ghi cho đúng mã CR (audit-log khoá bằng `change_id`, actor `product`), NGUYÊN VĂN, hoặc None.
    Product ghi evidence bằng văn xuôi chứ không phải JSON (hub 2026-10-13): đọc qua `_ev` là thành `{}` rỗng."""
    found = [
        str(e.payload.get("evidence") or "")
        for e in bus.replay(topic="audit-log", key=cid)
        if e.actor == ROLE.PRODUCT and e.payload.get("action") == "change.impact"
    ]
    return found[-1] if found else None


def held(bus: Any) -> dict[str, dict[str, Any]]:
    """CR đã bị agent duyệt giữ: {change_id: evidence của `reviewer.cr_hold` + by}."""
    return {
        str(d.get("change_id")): {**d, "by": e.actor}
        for e in bus.replay(topic="audit-log")
        if e.payload.get("action") == CR_HOLD_ACTION and (d := _ev(e)).get("change_id")
    }


def pending_machine(bus: Any) -> list[str]:
    """Mã CR agent được xét: bản mới nhất `pending`, do `delivery-lead` nộp, loại máy, đã có impact, chưa bị giữ."""
    skip = set(held(bus))
    return [
        cid
        for cid, e in sorted(_latest(bus).items())
        if e.payload.get("decision", "pending") == "pending"
        and e.actor == LEAD_ACTOR
        and (e.payload.get("impact") or {}).get("kind") in MACHINE_KINDS
        and cid not in skip
        and _impact(bus, cid) is not None
    ]


def publish_decision(bus: Any, cid: str, decision: str, by: str, reason: str) -> tuple[Envelope, dict[str, Any]] | None:
    """Đường ghi DUY NHẤT của quyết định CR (CLI `decide-change` và agent duyệt): impact product gộp vào, `decided_by`,
    `reason`; actor là người quyết. None khi không có CR đó."""
    cr = _latest(bus).get(cid)
    if cr is None:
        return None
    impact = next(
        (
            d
            for e in reversed(list(bus.replay(topic="audit-log")))
            if e.payload.get("action") == "change.impact" and (d := _ev(e)).get("change_id") == cid
        ),
        {},
    )
    payload = {
        **cr.payload,
        "decision": decision,
        "impact": {**cr.payload.get("impact", {}), **impact.get("impact", {}), "decided_by": by, "reason": reason},
    }
    return bus.publish(Envelope(topic="change-requests", key=cid, actor=by, payload=payload)), payload


def brief(bus: Any, cid: str) -> str:
    """Hồ sơ cho model: CR, impact + ruling của product, và các CR khác của cùng dự án (để nhận ra CR trùng)."""
    latest = _latest(bus)
    p = latest[cid].payload
    pid = p.get("project_id")
    rulings = [
        _ev(e).get("decision", "")
        for e in bus.replay(topic="audit-log")
        if e.actor == ROLE.PRODUCT and e.payload.get("action") == "ruling" and _ev(e).get("key") == cid
    ]
    khac = [
        f"- {k} [{e.payload.get('decision', 'pending')}] {str(e.payload.get('description', ''))[:200]}"
        for k, e in sorted(latest.items())
        if k != cid and e.payload.get("project_id") == pid
    ]
    return "\n".join(
        [
            f"# CHANGE REQUEST {cid} (dự án {pid}, nộp bởi {latest[cid].actor})",
            "",
            "## Mô tả",
            str(p.get("description", "")),
            "",
            "## Impact của CR",
            json.dumps(p.get("impact", {}), ensure_ascii=False),
            "",
            "## Impact product ước lượng",
            _impact(bus, cid) or "(trống)",
            "",
            "## Ruling của product",
            *(f"- {r}" for r in rulings),
            *([] if rulings else ["- (không có)"]),
            "",
            "## CR khác của dự án",
            *khac,
            *([] if khac else ["- (không có)"]),
        ]
    )


def _hold(bus: Any, cid: str, principal: str, reason: str, usage: dict[str, Any]) -> str:
    data = {"change_id": cid, "reason": reason[:600], **usage}
    bus.publish(
        Envelope(
            topic="audit-log",
            key=principal,
            actor=principal,
            payload=AuditLog(
                actor=principal, action=CR_HOLD_ACTION, evidence=json.dumps(data, ensure_ascii=False)
            ).model_dump(),
        )
    )
    return "hold"


def review_cr(bus: Any, cid: str, client: Any, principal: str, prompt: str) -> str:
    """Một lượt cho một CR: hỏi model, ghi `accepted`/`rejected` qua `publish_decision` hoặc `hold`. Không ném vì model."""
    from .llm import LLMError  # nhập lười: cùng lý do với gate_reviewer.review_one

    user = brief(bus, cid)
    limit = max(200, int(getattr(client, "max_input_chars", 120_000)))
    usage: dict[str, Any] = {}
    try:
        c = client.complete(system=prompt, user=user[:limit], schema=CR_SCHEMA, model_tier="strong")
        usage = {"tokens": c.input_tokens + c.output_tokens, "model": c.model}
        out = c.json()
    except LLMError as e:
        return _hold(bus, cid, principal, f"model lỗi: {e}", usage)
    decision, rc, hint = out.get("decision"), out.get("root_cause"), out.get("hint")
    if decision not in CR_DECISIONS or not isinstance(rc, str) or not isinstance(hint, str):
        return _hold(bus, cid, principal, f"đầu ra không hợp lệ: {json.dumps(out, ensure_ascii=False)[:200]}", usage)
    if decision == "hold":
        return _hold(bus, cid, principal, f"máy giữ: {rc}" + (f"; hint: {hint}" if hint else ""), usage)
    publish_decision(
        bus, cid, decision, principal, f"root_cause: {rc}; decision: {decision}; hint: {hint or 'không cần'}"
    )
    return decision
