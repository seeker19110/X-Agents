"""Máy trạng thái TICKET: gate spec → threat model → `product` pha `plan` sinh ticket → `_check_plan` → dispatch; event
cũ bị vượt (superseded); ticket vào trạng thái cuối (ADR-0034, tách khỏi orchestrator.py).

Mỗi hàm nhận `o: Orchestrator` làm tham số đầu, gán làm method trên `Orchestrator`
(`_plan = ticket_fsm._plan`, …) — bề mặt gọi cũ không đổi. Nguồn sự thật trạng thái ticket vẫn là
`lead.state` (delivery.py); các hàm ở đây chỉ ĐỌC/ĐỔI trạng thái đó qua `DeliveryLead`, không nhân đôi.
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..events import Envelope, Task
from ..gate_risk import request_gate
from ..gates import GateRequest
from ..llm import LLMError, TransientError
from ..roles import PHASE, ROLE, SOURCE
from ..routing import retry_after_seconds
from ..runner import RunnerError
from .fsm import Transition
from .guards import pending_clarifications
from .routes import PLAN_INPUTS, PLAN_REWORKS, SPEC_RUNTIME_REWORKS, spec_route, spec_runtime_gap

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def _superseded(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    """Event `tasks`/`pull-requests` còn trong hàng đợi (hoãn vì paused/transient, hoặc mở lại bus) mà ticket đã
    đi tiếp thì là hàng cũ: bỏ, audit `<topic>.superseded`, không giao agent.

    - `tasks` chỉ còn giá trị khi ticket vẫn `dispatched` — trạng thái mà chính event đó đặt. Người tiếp quản
      publish PR (ADR-0012 → `in_review`) hay ticket đã approved/blocked thì task này đã bị vượt. Giao nó cho
      backend là backend chạy trên worktree đã commit → "không sửa file nào" ×3 → `blocked` → review PR của
      người bị bỏ vì ticket không còn `in_review`.
    - `pull-requests` chỉ còn giá trị khi là PR MỚI NHẤT của ticket: `_on_pr` đã đặt lại vòng review theo PR
      sau, review PR trước là chấm commit cũ rồi ghi verdict vào vòng của PR mới.
    Đo được (2026-09-04/05): QLKH-004 mở lại 7 lần, 13 lần review block, 10.7M token; sau khi mở lại bus,
    PR tiếp quản 04:10 (đã có 2/3 verdict, hoãn vì qa transient) vẫn nằm hàng đợi cạnh PR tiếp quản mới."""
    tid = str(env.payload.get("ticket_id") or env.key)
    if tid not in o.lead.tickets: return False  # event ngoài delivery-lead (test/relay): không có trạng thái để so
    st = o.lead.state.get(tid)
    if env.topic == "tasks":
        if st == "dispatched": return False
        why = {"state": st, "retry": env.payload.get("retry", 0)}
    else:
        newest = o.latest("pull-requests", tid)
        if newest is None or newest.event_id == env.event_id: return False
        why = {"state": st, "pr_ref": env.payload.get("pr_ref"), "newest_pr_ref": newest.payload.get("pr_ref")}
    o._audit(f"{env.topic}.superseded", {"ticket_id": tid, "event_id": env.event_id, **why},
                ticket_id=tid, project_id=o.project_for(env))
    res.actions.append(f"superseded:{tid}:{env.topic}")
    o._mark(env, res)
    return True

def _note_closed(o: Orchestrator) -> None:
    """Ghi `ticket.closed` cho ticket vừa vào trạng thái cuối. `metrics.collect` tính lead time (tasks đầu → closed)
    từ chính action này; không ai phát thì `ticket_lead_seconds` luôn rỗng và gauge Prometheus không bao giờ hiện."""
    for tid, st in list(o.lead.state.items()):
        if st != "closed": continue
        t = o.lead.tickets.get(tid)
        o._audit("ticket.closed", {"ticket_id": tid, "retry": t.retry if t else 0}, once=f"closed:{tid}",
                    ticket_id=tid, project_id=t.project_id if t else None)

def _plan(o: Orchestrator, env: Envelope, res: StepResult) -> StepResult:
    project = env.payload.get("project_id") or env.key
    if env.topic == "approved-specs":
        sid = f"SPEC-{project}"
        if not o.gate.is_approved(sid):
            last = next((g for g in reversed(o.gate.history) if g.subject_id == sid), None)
            # ADR-0031 §3: `request_changes` của người = spec-writer viết lại trên event nguồn với lý do làm `hint`.
            # Khoá theo THẾ HỆ gate (`seq`, khuôn 3): event đầu tới sau quyết định (spec cũ đang hoãn) gọi viết lại
            # và ghi khoá; bản viết lại tới sau, thấy khoá, được trình lại gate như một spec mới.
            changes = f"spec.changes:{sid}:{last.seq}" if last is not None and last.decision == "request_changes" else None
            if sid not in o.gate.pending:
                if last is None or (changes is not None and changes in o.once):
                    if (gap := spec_runtime_gap(env.payload)) is not None:
                        return o._spec_runtime_missing(env, project, gap, res)
                    request_gate(o.gate, GateRequest(kind="spec", subject_id=sid, created_by=env.actor,
                                                  checklist=["prd", "acceptance-criteria", "ux-flow", "risks"]))
                elif changes is not None and (cause := _spec_source(o, env, project)) is not None:
                    _spec_rework(o, env, cause, f"người yêu cầu sửa spec ở gate {sid}: {last.reason}"[:500], res)
                    if res.transient:  # `_act_plan` trả True nên `process()` không tự hoãn: hoãn ở đây, khoá chưa ghi
                        return o._defer_transient(env, res)
                    o._remember(changes)
                    res.actions.append(f"spec_changes:{project}:rework")
                    o._mark(env, res); return res
                else:
                    res.actions.append(f"gate:{sid}:{last.decision}"); o._mark(env, res); return res
            return o._defer(env, res, f"gate:{sid}")
        if not o._threat_model(env, sid, res):
            o._mark(env, res); return res
        live = [pid for pid, p in o.plans.items() if p["project_id"] == project and p["source_topic"] == "approved-specs"]
        if live:
            # Spec publish lặp (pha `spec` chạy lại, người publish hai lần) không được sinh plan thứ hai cho cùng
            # dự án: ticket trùng, hai lần giao cho một việc. ADR-0037 bỏ gate plan nên `o.plans` chỉ chứa kế hoạch
            # đã qua `_check_plan` và đã dispatch — có mặt ở đây là đang sống, không cần hỏi gate nữa.
            o._audit("plan.duplicate_spec", {"project_id": project, "event_id": env.event_id, "existing": live}, project_id=project)
            res.actions.append(f"plan_skipped:{','.join(live)}"); o._mark(env, res); return res
    cal = o.supervisor.calibration()  # vòng học: bài học estimate-vs-actual quay lại người ước lượng
    inp = env.model_copy(update={"payload": {**env.payload, "estimate_calibration": cal}}) if cal else env
    try:
        g = o.runner.generate(ROLE.PRODUCT, inp, "tasks", many=True, phase=PHASE.PLAN)
    except TransientError as e:
        res.actions.append(f"transient:{ROLE.PRODUCT}:{str(e)[:120]}")
        with o._lock: o.stats["transient"] += 1
        return o._defer(env, res, f"transient:{ROLE.PRODUCT}")
    except (RunnerError, LLMError) as e:
        res.actions.append(f"error:{ROLE.PRODUCT}:{str(e)[:120]}")
        with o._lock: o.stats["errors"] += 1
        o._mark_unhandled(env, ROLE.PRODUCT, e, res)  # trước 2026-09-23: _mark rồi im — dự án chết mà status xanh
        o._mark(env, res); return res
    if g.context_writes:  # C4, API contract lên blackboard TRƯỚC `_check_plan` để nó thấy được (ADR-0037)
        o.runner.write_context(ROLE.PRODUCT, env, g.context_writes)
    tickets = [Task.model_validate(p) for p in g.payloads]
    problems = o._check_plan(tickets, project)
    n = 1 + sum(1 for p in o.plans.values() if p["project_id"] == project)
    plan_id = f"PLAN-{project}-{n}"
    plan = {"plan_id": plan_id, "project_id": project, "source_event": env.event_id, "source_topic": env.topic,
            "tickets": [t.model_dump() for t in tickets], "problems": problems,
            "threat_model": "missing" if f"SPEC-{project}" in o.missing_threat_model else "ok"}
    if problems:
        with o._lock:
            o.plan_reworks[env.event_id] += 1; attempt = o.plan_reworks[env.event_id]
        if attempt <= PLAN_REWORKS:
            # Từ chối của `_check_plan` là danh sách lỗi cấu trúc máy đọc được — trả thẳng cho `product[plan]`
            # sửa (cùng khuôn `hint` của `_spec_runtime_missing`) thay vì bắt người gõ "retry". Không ghi
            # `plan_rejected` (đó là dấu "đã hỏi người" mà `_rehydrate` dựng `unhandled` từ nó).
            o._audit("plan.rework", {**plan, "attempt": attempt}, actor=ROLE.PRODUCT, tokens=g.tokens,
                     cost=g.cost_usd, project_id=project)
            res.actions.append(f"plan_rework:{plan_id}:{attempt}")
            hint = f"orchestrator từ chối kế hoạch {plan_id} (lần {attempt}): {'; '.join(problems)}"
            prev = {"plan_id": plan_id, "problems": problems, "tickets": [t.ticket_id for t in tickets]}
            inp = env.model_copy(update={"payload": {**env.payload, "hint": hint, "previous_plan": prev}})
            return o._plan(inp, res)
        o._audit("plan_rejected", plan, actor=ROLE.PRODUCT, tokens=g.tokens, cost=g.cost_usd, project_id=project)
        res.actions.append(f"plan_rejected:{'; '.join(problems)[:120]}")
        with o._lock: o.stats["errors"] += 1
        # Kế hoạch bị từ chối là ngõ cụt: không ticket nào được tạo, không gate nào mở, và không có cơ chế
        # tự lập lại. Trước đây dự án đứng im ở đây mà `status` vẫn báo mọi chỉ số xanh (đo được với dự án
        # DHCB: `tickets: []` → "kế hoạch rỗng" → im lặng vĩnh viễn). Phải hiện ra cho người quyết.
        o.supervisor.escalate_gate(project, f"kế hoạch {plan_id} bị từ chối: {'; '.join(problems)[:200]}",
                                      once_key=f"plan_rejected:{env.event_id}")
        # Duyệt escalation này = lập lại kế hoạch: ghi vào `unhandled` để `_retry_unhandled` chạy lại đúng event
        # nguồn (change-request / approved-specs). Trước đây duyệt rơi xuống nhánh ticket → "reopen" một ticket
        # không tồn tại, không gì xảy ra. Đo được 2026-09-06 (CR-STAGE-001, PLAN-QLKH-5 rỗng): duyệt xong hàng
        # đợi rỗng, phải phát lại decide-change bằng tay.
        with o._lock:
            o.unhandled[project] = {"agent": ROLE.PRODUCT, "topic": env.topic, "event_id": env.event_id,
                                       "subject": project, "error": f"plan_rejected: {'; '.join(problems)[:200]}"}
        if project not in o.gate.pending:
            request_gate(o.gate, GateRequest(kind="escalation", subject_id=project, created_by=ROLE.PRODUCT,
                                          checklist=["plan_problems", "decision:retry|close"]))
    else:
        o.plans[plan_id] = plan
        o._audit("plan.proposed", plan, actor=ROLE.PRODUCT, tokens=g.tokens, cost=g.cost_usd, project_id=project)
        # ADR-0037: không còn gate plan. `_check_plan` vừa chạy XONG và không trả problem nào — đó là nguồn sự thật
        # duy nhất cho phép giao ticket, nên ghi vào `lead.plans_ok` (guard trong `DeliveryLead.dispatch`) rồi giao
        # ngay. Người vẫn ký hai đầu: gate spec trước đó, gate release sau đó.
        o.lead.plans_ok.add(plan_id)
        res.actions.append(f"plan:{plan_id}:{len(tickets)} ticket")
        res.actions.append("dispatch:" + ",".join(o._dispatch_plan(plan_id)))
        with o._lock: o.stats["plans"] += 1
    o._mark(env, res)
    return res

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

def _spec_runtime_missing(o: Orchestrator, env: Envelope, project: str, gap: str, res: StepResult) -> StepResult:
    """ADR-0031: spec ứng dụng không có `runtime` hợp lệ thì KHÔNG mở gate spec — người ký Gate 1 không được đặt
    trước một PRD mà câu "chạy cho tôi xem" chưa có câu trả lời. Thay vào đó trả về `product` pha `spec` với lý do (`hint`)
    đúng như `request_changes` của người; quá `SPEC_RUNTIME_REWORKS` lần vẫn thiếu → escalation cấp dự án, cùng
    khuôn với kế hoạch bị `_check_plan` từ chối (approve = chạy lại event nguồn, reject = bỏ).
    Khoá theo `event_id` của spec (mỗi lần `product` publish một spec là một event mới, không nuốt lần hai — khuôn 3
    `TRAPS.md`); bộ đếm theo dự án dựng lại từ audit (khuôn 2)."""
    with o._lock: n = o.spec_runtime_reworks[project] + 1
    cause = _spec_source(o, env, project)
    rework = cause if cause is not None and n <= SPEC_RUNTIME_REWORKS else None
    if rework is not None:
        _spec_rework(o, env, rework, f"orchestrator từ chối mở gate spec (lần {n}): {gap}", res)
        if res.transient:  # chưa sửa được lượt nào: hoãn, KHÔNG đếm — bộ đếm dựng lại từ audit ngay dưới (khuôn 2)
            return o._defer_transient(env, res)
    with o._lock: o.spec_runtime_reworks[project] = n
    o._audit("spec.runtime_missing", {"project_id": project, "event_id": env.event_id, "kind": env.payload.get("kind"),
                                         "runtime": env.payload.get("runtime"), "reason": gap, "attempt": n,
                                         "source_event": cause.event_id if cause else None}, project_id=project)
    if rework is not None:
        res.actions.append(f"spec_runtime_missing:{project}:rework:{n}")
        o._mark(env, res); return res
    why = gap if cause is not None else f"{gap}; không có requirements-draft để pha `spec` làm lại"
    o._audit("spec.runtime_escalated", {"project_id": project, "event_id": env.event_id, "attempts": n, "reason": why,
                                           "source_event": cause.event_id if cause else None,
                                           "source_topic": cause.topic if cause else None}, project_id=project)
    res.actions.append(f"spec_runtime_missing:{project}:escalated")
    with o._lock: o.stats["errors"] += 1
    o.supervisor.escalate_gate(project, f"spec thiếu runtime sau {n} lần: {gap[:200]}", once_key=f"spec_runtime:{env.event_id}")
    if cause is not None:
        with o._lock:
            o.unhandled[project] = {"agent": ROLE.PRODUCT, "topic": cause.topic, "event_id": cause.event_id,
                                       "subject": project, "error": f"spec_runtime_missing: {gap[:200]}"}
    if project not in o.gate.pending:
        request_gate(o.gate, GateRequest(kind="escalation", subject_id=project, created_by=ROLE.PRODUCT,
                                      checklist=["spec_runtime", "decision:retry|close"]))
    o._mark(env, res); return res

def clarify_timeout() -> timedelta:
    """Người im lặng bao lâu thì orchestrator tự lấy `default` của từng câu hỏi làm câu trả lời. Đọc mỗi lần gọi
    để `COMPANY_CLARIFY_TIMEOUT_H` đổi được giữa chừng (như `COMPANY_GATE_AUTOAPPROVE`). Mặc định 24 giờ."""
    return timedelta(hours=float(os.environ.get("COMPANY_CLARIFY_TIMEOUT_H") or 24))

def _assume_clarifications(o: Orchestrator, now: datetime | None = None) -> list[StepResult]:
    """Câu hỏi làm rõ không ai trả lời quá `clarify_timeout()` → ghi `clarification.assumed` (câu nào, default nào)
    rồi chạy pha `spec` từ `requirements-draft` với `assumed_answers` — cùng đường `_act_clarification_fallback`
    (vòng ≥ 2 đã là "assumption" theo thiết kế). Người vẫn ký gate `spec`, nên giả định không đi xa hơn một PRD
    chờ người đọc. Trước 2026-09-23 dự án đứng vô hạn, chỉ hiện ở `status.clarifications_pending`."""
    now = now or datetime.now(UTC)
    from ..orchestrator import StepResult  # nhập lười, như scheduler._integrate_pending
    out: list[StepResult] = []
    for pid, p in pending_clarifications(o.bus).items():
        if now - datetime.fromisoformat(p["since"]) <= clarify_timeout(): continue
        if o.defer_until.get(f"assume:{pid}", 0.0) > time.monotonic(): continue  # backend đã hẹn giờ, chưa tới
        draft = o.latest("requirements-draft", pid)
        if draft is None: continue  # không có draft thì không có gì để viết spec; `_spec_ready` đã audit `spec_writer.no_draft`
        assumed = [{"question_id": q["id"], "answer": q["default"], "text": q["text"]} for q in p["questions"]]
        res = StepResult(draft.event_id, draft.topic, draft.key)
        inp = draft.model_copy(update={"payload": {**draft.payload, "assumed_answers": assumed}})
        o._call(ROLE.PRODUCT, inp, spec_route("requirements-draft"), res)
        if res.transient:
            # Sổ giả định ghi TRƯỚC lời gọi thì vòng câu hỏi rời `pending_clarifications` mà spec chưa viết: không
            # nhịp nào thử lại, `status` nói không chờ ai — dự án đứng im. Chưa ghi sổ thì nhịp sau thử lại, giữ
            # mốc hẹn của backend như `_defer` (key riêng: `_retry_deferred` chỉ đọc key có trong `deferred`).
            stuck = next(a for a in res.actions if a.startswith("transient:"))
            if (wait := retry_after_seconds(stuck)) is not None:
                with o._lock: o.defer_until[f"assume:{pid}"] = time.monotonic() + wait
        else:
            o._audit("clarification.assumed", {"project_id": pid, "event_id": p["event_id"], "round": p["round"],
                                               "since": p["since"], "assumed": assumed}, project_id=pid)
        out.append(res)
    return out

def _threat_model(o: Orchestrator, env: Envelope, sid: str, res: StepResult) -> bool:
    """Agent `security` đọc spec đã duyệt: threat model v1 lên blackboard + review-results key=SPEC-*.
    Verdict block → không lập kế hoạch; mở gate escalation (người sửa spec rồi duyệt, hoặc publish lại). Trả về True nếu được đi tiếp."""
    prior = o.latest("review-results", sid)
    if prior is not None and prior.payload.get("verdict") != "block":
        return True
    try:
        g = o.runner.generate(ROLE.SECURITY, env, "review-results")
        p = {**g.payloads[0], "ticket_id": sid, "source": SOURCE.SECURITY}
        o.runner.publish(ROLE.SECURITY, env, "review-results", p, key=sid, tokens=g.tokens, model=g.model,
                            context_writes=g.context_writes, generated=g)
        with o._lock: o.stats["runs"] += 1
    except TransientError as e:
        res.actions.append(f"transient:{ROLE.SECURITY}:{str(e)[:120]}")
        with o._lock: o.stats["transient"] += 1
        return True  # threat model không chặn plan; lần lập kế hoạch sau (nếu có) sẽ thử lại
    except (RunnerError, LLMError) as e:
        # Đánh dấu vào `missing_threat_model`: từ ADR-0037 PR-1 đây LÀ một `problems` của `_check_plan`, nên kế
        # hoạch bị `plan_rejected` + escalation chứ không lặng lẽ đi tiếp với một mục checklist tick nhầm.
        o._audit("threat_model.missing", {"subject_id": sid, "error": str(e)[:300]},
                    project_id=env.payload.get("project_id"))
        with o._lock: o.missing_threat_model.add(sid)
        res.actions.append(f"error:{ROLE.SECURITY}:{str(e)[:120]}")
        with o._lock: o.stats["errors"] += 1
        return True
    if p["verdict"] == "block":
        o._audit("spec_blocked_by_security", {"subject_id": sid, "findings": p.get("findings", [])}, project_id=env.payload.get("project_id"))
        res.actions.append(f"spec_blocked:{sid}")
        # Hỏi người qua gate thay vì chỉ audit: duyệt escalation = chạy lại event spec (threat model chấm lại).
        o._mark_unhandled(env, ROLE.SECURITY, f"security chặn spec: {json.dumps(p.get('findings', []), ensure_ascii=False)[:200]}", res)
        return False
    res.actions.append(f"threat-model:{sid}:{p['verdict']}"); return True

def _dispatch_plan(o: Orchestrator, plan_id: str, replaying: bool = False) -> list[str]:
    plan = o.plans[plan_id]
    # Phát lại đọc bản ghi CŨ (`Task.tu_log` khoan dung với từ vựng trước PR-5d); kế hoạch MỚI do model
    # vừa sinh thì vẫn nghiêm ngặt — khoan dung ở đó là để lọt một `assignee` sai vào hàng đợi.
    build = Task.tu_log if replaying else Task.model_validate
    pending = [build(t) for t in plan["tickets"] if t["ticket_id"] not in o.lead.tickets]
    done: list[str] = []
    prev, o.lead.replaying = o.lead.replaying, replaying
    try:
        while pending:
            ready = [t for t in pending if all(d in o.lead.tickets for d in t.depends_on)]
            if not ready: raise ValueError(f"{plan_id}: depends_on vòng hoặc chưa biết: {[t.ticket_id for t in pending]}")
            for t in sorted(ready, key=lambda x: x.priority):
                o.lead.dispatch(t, plan_id); pending.remove(t); done.append(t.ticket_id)
    finally:
        o.lead.replaying = prev
    return done


# ---------- bảng chuyển giao (K1.7, orch/fsm.py) — dùng bởi Orchestrator.process() ----------

def _act_superseded(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    return o._superseded(env, res)  # True: event cũ đã bị vượt, _superseded tự _mark — process() dừng ngay


def _act_learn_repo(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    o._learn_repo(env)  # repo riêng của dự án (ADR-0025), trước khi intake chạy — không dừng process()
    return False


def _act_plan(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    o._plan(env, res)  # _plan tự _mark và trả res; process() luôn dừng ở đây khi PLAN_INPUTS khớp
    return True


def _act_clarification_fallback(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    """Pha `intake` không còn câu hỏi nào (hoặc quá round 2 → assumption): đi thẳng pha `spec` từ bản draft."""
    draft = o.latest("requirements-draft", env.key)
    if draft is not None:
        o._call(ROLE.PRODUCT, draft, spec_route("requirements-draft"), res)
    return False


TICKET_TRANSITIONS: list[Transition] = [
    Transition("superseded", frozenset({"tasks", "pull-requests"}), _act_superseded),
    Transition("learn_repo", frozenset({"research-requests"}), _act_learn_repo),
    Transition("plan", frozenset(PLAN_INPUTS), _act_plan,
               guard=lambda env, o: PLAN_INPUTS[env.topic](env, o)),
    Transition("clarification_fallback", frozenset({"clarification-questions"}), _act_clarification_fallback,
               guard=lambda env, o: not env.payload.get("questions")),
]
