"""ADR-0059: security chặn spec ở threat model → `product` viết lại với finding làm `hint`, bản viết lại trình lại gate
spec; quá `SPEC_SECURITY_REWORKS` lần thì escalation như cũ. Tách khỏi `ticket_fsm` (trần 400 dòng mỗi module `orch/`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..delivery import HINT_MAX
from ..events import Envelope
from ..gate_risk import request_gate
from ..gates import GateRequest
from .spec_runtime import _spec_rework, _spec_source

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult

SPEC_SECURITY_REWORKS = 2  # số lần security chặn spec được tự trả về product trước khi hỏi người


def spec_approved_now(o: Orchestrator, sid: str) -> bool:
    """Gate spec tính theo thế hệ MỚI NHẤT: không thế hệ nào đang chờ và thế hệ gần nhất là `approve`.
    `GateQueue.is_approved` ("từng có một lần approve") để bản viết lại bị reject ở gate trình lại vẫn đi tiếp."""
    if sid in o.gate.pending:
        return False
    last = next((g for g in reversed(o.gate.history) if g.subject_id == sid), None)
    return last is not None and last.decision == "approve"


def with_gate_decision(o: Orchestrator, env: Envelope, sid: str) -> Envelope:
    """Đầu vào lượt threat model mang chữ ký gate spec MỚI NHẤT (ai, quyết gì, lý do) do CODE điền từ `gate.history`.
    Hub thật 2026-10-17 (SPEC-CR-DDCSV-DPIA-004): chủ dự án đã ký gate chấp nhận RK-DPIA4-01, security vẫn chặn vì rủi ro
    "chưa accepted cho tới khi có gate.decide do chủ dự án ký" — agent không đọc được gate, chủ dự án bị đòi ký lại."""
    g = next((g for g in reversed(o.gate.history) if g.subject_id == sid and g.decision != "pending"), None)
    if g is None:
        return env
    d = {"subject_id": sid, "decision": g.decision, "by": g.decided_by, "reason": g.reason, "verified_by": "orchestrator"}
    return env.model_copy(update={"payload": {**env.payload, "spec_gate_decision": d}})


def _hint(n: int, review: Mapping[str, object]) -> str:
    fs = review.get("findings")
    findings = [f for f in fs if isinstance(f, Mapping)] if isinstance(fs, list) else []
    lines = [
        f"- [{f.get('level')}] {f.get('location', '')}: {f.get('text', '')}"
        for f in findings
        if f.get("level") in {"block", "warn"}
    ]
    return (
        f"security chặn spec ở threat model (lần {n}). Viết lại spec gỡ MỌI finding block và xử lý từng warn "
        "(Must kèm Gherkin, hoặc rủi ro chấp nhận có tên trong ADR); giữ nguyên phần không bị nêu:\n" + "\n".join(lines)
    )[:HINT_MAX]


def rework_after_block(o: Orchestrator, env: Envelope, sid: str, review: Mapping[str, object], res: StepResult) -> bool:
    """Trả spec về `product` nếu chuỗi còn lượt và có event nguồn. True = đã nhận xử lý (kể cả hoãn transient,
    `res.transient` bật — chưa đếm); False = đi đường cũ (escalation)."""
    chain = env.key
    with o._lock:
        n = o.spec_security_reworks[chain] + 1
    cause = _spec_source(o, env, str(env.payload.get("project_id") or env.key)) if n <= SPEC_SECURITY_REWORKS else None
    if cause is None:
        return False
    _spec_rework(o, env, cause, _hint(n, review), res)
    if res.transient:
        return True
    with o._lock:
        o.spec_security_reworks[chain] = n
        o.spec_regate.add(sid)
    o._audit(
        "spec.security_rework",
        {
            "project_id": env.payload.get("project_id"),
            "chain": chain,
            "subject_id": sid,
            "attempt": n,
            "event_id": env.event_id,
            "source_event": cause.event_id,
        },
        project_id=env.payload.get("project_id"),
    )
    res.actions.append(f"spec_security:{chain}:rework:{n}")
    return True


def regate(o: Orchestrator, env: Envelope, sid: str) -> None:
    """Spec kế tiếp của chuỗi vừa bị trả về: mở thế hệ gate spec mới cho bản viết lại (ADR-0059 §2)."""
    with o._lock:
        o.spec_regate.discard(sid)
    o._audit(
        "spec.regate",
        {"project_id": env.payload.get("project_id"), "chain": env.key, "subject_id": sid, "event_id": env.event_id},
        project_id=env.payload.get("project_id"),
    )
    request_gate(
        o.gate,
        GateRequest(
            kind="spec",
            subject_id=sid,
            created_by=env.actor,
            checklist=["prd", "acceptance-criteria", "ux-flow", "risks"],
        ),
    )
