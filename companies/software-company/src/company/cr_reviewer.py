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
#: Trần lý do "máy giữ" ghi vào audit (gate lẫn CR). Lý do giữ là điểm bắt đầu của phiên chính (ADR gốc 0034); trần cũ
#: 600 cắt giữa câu ở REL-078/082/084 (hub 2026-10-14/15). Vẫn có trần để một đầu ra hỏng không phình audit-log.
HOLD_REASON_MAX = 8000
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


def _cr_khac(cid: str, e: Envelope) -> str:
    """Một CR khác của dự án trong hồ sơ. CR còn sống (không `rejected`) in đủ mô tả và lý do quyết: hub 2026-10-14,
    REWORK-DDCSV-56-2 và 61-2 cùng gốc CVE image đều được accepted vì 200 ký tự đầu chỉ là "Ticket X bị trả về làm
    lại…" — gốc chung và "đã lập 3 ticket vá image" của CR kia không tới mắt agent duyệt. CR đã bác giữ một dòng."""
    decision = e.payload.get("decision", "pending")
    desc = str(e.payload.get("description", ""))
    if decision == "rejected":
        return f"- {cid} [{decision}] {desc[:200]}"
    reason = str((e.payload.get("impact") or {}).get("reason", ""))
    return f"- {cid} [{decision}] {desc[:1500]}" + (f"\n  lý do quyết: {reason[:800]}" if reason else "")


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
    khac = [_cr_khac(k, e) for k, e in sorted(latest.items()) if k != cid and e.payload.get("project_id") == pid]
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
    data = {"change_id": cid, "reason": reason[:HOLD_REASON_MAX], **usage}
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
    """Một lượt cho một CR: hỏi model, ghi `accepted`/`rejected` qua `publish_decision` hoặc `hold`. Chỉ ném
    `TransientError` (cùng lý do với `gate_reviewer.review_one`)."""
    from .llm import LLMError, TransientError  # nhập lười: cùng lý do với gate_reviewer.review_one

    user = brief(bus, cid)
    limit = max(200, int(getattr(client, "max_input_chars", 120_000)))
    usage: dict[str, Any] = {}
    try:
        c = client.complete(system=prompt, user=user[:limit], schema=CR_SCHEMA, model_tier="strong")
        usage = {"tokens": c.input_tokens + c.output_tokens, "model": c.model}
        out = c.json()
    except TransientError:
        raise
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
