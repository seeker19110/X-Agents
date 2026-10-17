"""ADR-0031: spec ứng dụng thiếu `runtime` hợp lệ thì không mở gate spec — trả về `product` pha `spec` kèm `hint`,
quá `SPEC_RUNTIME_REWORKS` lần thì escalation cấp dự án. Tách khỏi `ticket_fsm` (trần 400 dòng mỗi module `orch/`)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..bus import REVIEWER_PREFIX
from ..events import Envelope
from ..gate_risk import request_gate
from ..gates import GateRequest
from ..roles import ROLE
from .routes import SPEC_REVIEWER_REWORKS, SPEC_RUNTIME_REWORKS, spec_route, spec_runtime_gap

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult

def _spec_source(o: Orchestrator, env: Envelope, project: str) -> Envelope | None:
    """Event nguồn để pha `spec` viết lại một spec: đúng `causation_id` của nó, không có thì `requirements-draft` mới nhất."""
    cause = next((e for t in ("clarification-answers", "requirements-draft", "clarification-questions")
                  for e in o.bus.replay(topic=t) if e.event_id == env.causation_id), None) if env.causation_id else None
    return cause if cause is not None else o.latest("requirements-draft", project)

def _spec_rework(o: Orchestrator, env: Envelope, cause: Envelope, hint: str, res: StepResult) -> None:
    """Gọi lại `product` pha `spec` trên `cause` với `hint` + `previous_spec` — một đường cho cả máy (thiếu runtime,
    ADR-0031) lẫn người (`request_changes` ở gate spec)."""
    prev = {k: env.payload.get(k) for k in ("kind", "runtime", "artifacts")}
    inp = cause.model_copy(update={"payload": {**cause.payload, "hint": hint, "previous_spec": prev}})
    o._recall(ROLE.PRODUCT, cause)  # `partial` đã ghi `product` cho event nguồn: gọi lại là CHỦ Ý
    o._call(ROLE.PRODUCT, inp, spec_route(cause.topic), res)

def reviewer_rework_capped(o: Orchestrator, sid: str, cause: Envelope) -> bool:
    """Đã đủ `SPEC_REVIEWER_REWORKS` lần `reviewer:*` reject gate `sid` kể từ event nguồn `cause` (hub 2026-10-17,
    SPEC-CR-DDCSV-DPIA-003: spec chờ event của chủ dự án, mỗi vòng reject → viết lại tốn ba lượt agent). Đếm từ lịch
    sử gate, không giữ bộ đếm riêng; nguồn mới (câu trả lời mới) có `ts` sau mọi lần reject cũ nên đếm lại từ 0."""
    n = sum(1 for g in o.gate.history if g.subject_id == sid and g.created_at >= cause.ts
            and g.decision == "reject" and (g.decided_by or "").startswith(REVIEWER_PREFIX))
    if n <= SPEC_REVIEWER_REWORKS: return False
    o._audit("spec.rework_capped", {"subject_id": sid, "source_event": cause.event_id, "rejects": n,
                                     "reason": "reviewer reject quá trần trên cùng event nguồn; cần nguồn mới"},
             once=f"spec_capped:{sid}:{cause.event_id}")
    return True

def _runtime_da_duyet(o: Orchestrator, project: str, chain: str) -> str:
    """Runtime của spec gần nhất của dự án đã qua gate `SPEC-<key>` (chuỗi khác `chain`), dạng câu chép được vào
    `hint`. Hub 2026-10-15: product viết spec cho CR mà "không đọc được toàn văn PRD v3 §8b" nên đoán lệnh khởi
    động, trong khi runtime đúng đã qua gate ở CR-DDCSV-INFRA-002. Rỗng khi chưa có."""
    for e in reversed(list(o.bus.replay(topic="approved-specs"))):
        rt = e.payload.get("runtime")
        if (e.key != chain and (e.payload.get("project_id") or e.key) == project and isinstance(rt, dict)
                and o.gate.is_approved(f"SPEC-{e.key}") and spec_runtime_gap(e.payload) is None):
            return (f". Runtime của dự án đã qua gate spec SPEC-{e.key} — chép nguyên văn nếu thay đổi này không đổi"
                    f" cách chạy: {json.dumps(rt, ensure_ascii=False)}")
    return ""

def _spec_runtime_missing(o: Orchestrator, env: Envelope, project: str, gap: str, res: StepResult) -> StepResult:
    """ADR-0031: spec ứng dụng không có `runtime` hợp lệ thì KHÔNG mở gate spec — người ký Gate 1 không được đặt
    trước một PRD mà câu "chạy cho tôi xem" chưa có câu trả lời. Thay vào đó trả về `product` pha `spec` với lý do (`hint`)
    đúng như `request_changes` của người; quá `SPEC_RUNTIME_REWORKS` lần vẫn thiếu → escalation cấp dự án, cùng
    khuôn với kế hoạch bị `_check_plan` từ chối (approve = chạy lại event nguồn, reject = bỏ).
    Khoá theo `event_id` của spec (mỗi lần `product` publish một spec là một event mới, không nuốt lần hai — khuôn 3
    `TRAPS.md`); bộ đếm theo CHUỖI spec (`env.key`: dự án, hoặc mã CR — cùng key với gate `SPEC-<key>`) dựng lại từ
    audit (khuôn 2). Hub 2026-10-15: đếm theo dự án thì lần thiếu đầu của CR thứ hai thành "lần 2" và escalate."""
    chain = env.key
    with o._lock: n = o.spec_runtime_reworks[chain] + 1
    cause = _spec_source(o, env, project)
    rework = cause if cause is not None and n <= SPEC_RUNTIME_REWORKS else None
    if rework is not None:
        hint = f"orchestrator từ chối mở gate spec (lần {n}): {gap}{_runtime_da_duyet(o, project, chain)}"
        _spec_rework(o, env, rework, hint, res)
        if res.transient:  # chưa sửa được lượt nào: hoãn, KHÔNG đếm — bộ đếm dựng lại từ audit ngay dưới (khuôn 2)
            return o._defer_transient(env, res)
    with o._lock: o.spec_runtime_reworks[chain] = n
    o._audit("spec.runtime_missing", {"project_id": project, "chain": chain, "event_id": env.event_id,
                                         "kind": env.payload.get("kind"), "runtime": env.payload.get("runtime"),
                                         "reason": gap, "attempt": n,
                                         "source_event": cause.event_id if cause else None}, project_id=project)
    if rework is not None:
        res.actions.append(f"spec_runtime_missing:{project}:rework:{n}")
        o._mark(env, res); return res
    why = gap if cause is not None else f"{gap}; không có requirements-draft để pha `spec` làm lại"
    o._audit("spec.runtime_escalated", {"project_id": project, "chain": chain, "event_id": env.event_id, "attempts": n,
                                           "reason": why,
                                           "source_event": cause.event_id if cause else None,
                                           "source_topic": cause.topic if cause else None}, project_id=project)
    res.actions.append(f"spec_runtime_missing:{project}:escalated")
    with o._lock: o.stats["errors"] += 1
    o.supervisor.escalate_gate(project, f"spec thiếu runtime sau {n} lần: {gap[:200]}", once_key=f"spec_runtime:{env.event_id}")
    if cause is not None:
        with o._lock:
            o.unhandled[project] = {"agent": ROLE.PRODUCT, "topic": cause.topic, "event_id": cause.event_id,
                                       "subject": project, "chain": chain, "error": f"spec_runtime_missing: {gap[:200]}"}
    if project not in o.gate.pending:
        request_gate(o.gate, GateRequest(kind="escalation", subject_id=project, created_by=ROLE.PRODUCT,
                                      checklist=["spec_runtime", "decision:retry|close"]))
    o._mark(env, res); return res
