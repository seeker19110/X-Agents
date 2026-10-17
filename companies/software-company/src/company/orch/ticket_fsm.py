"""Máy trạng thái TICKET: gate spec → threat model → `product` pha `plan` sinh ticket → `_check_plan` → dispatch; event
cũ bị vượt (superseded); ticket vào trạng thái cuối (ADR-0034, tách khỏi orchestrator.py).

Mỗi hàm nhận `o: Orchestrator` làm tham số đầu, gán làm method trên `Orchestrator`
(`_plan = ticket_fsm._plan`, …) — bề mặt gọi cũ không đổi. Nguồn sự thật trạng thái ticket vẫn là
`lead.state` (delivery.py); các hàm ở đây chỉ ĐỌC/ĐỔI trạng thái đó qua `DeliveryLead`, không nhân đôi.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..delivery import HINT_MAX
from ..events import Envelope, Task
from ..gate_risk import request_gate
from ..gates import GateRequest
from ..llm import LLMError, TransientError
from ..roles import PHASE, ROLE, SOURCE
from ..runner import RunnerError
from . import spec_security
from .fsm import Transition
from .gates_flow import _retire_replanned, spec_changes_asked
from .guards import pending_clarifications
from .hen import cho_hen, moc_reset
from .pr_rong import EMPTY_PR
from .routes import ACTIVE_STATES, PLAN_INPUTS, PLAN_REWORKS, spec_route, spec_runtime_gap
from .spec_runtime import _spec_rework, _spec_source, reviewer_rework_capped

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def _superseded(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    """Event `tasks`/`pull-requests`/`test-suites` còn trong hàng đợi (hoãn vì paused/transient, hoặc mở lại bus) mà ticket đã
    đi tiếp thì là hàng cũ: bỏ, audit `<topic>.superseded`, không giao agent.

    - `tasks` chỉ còn giá trị khi ticket vẫn `dispatched` — trạng thái mà chính event đó đặt. Người tiếp quản
      publish PR (ADR-0012 → `in_review`) hay ticket đã approved/blocked thì task này đã bị vượt. Giao nó cho
      backend là backend chạy trên worktree đã commit → "không sửa file nào" ×3 → `blocked` → review PR của
      người bị bỏ vì ticket không còn `in_review`.
    - `pull-requests` chỉ còn giá trị khi là PR MỚI NHẤT của ticket: `_on_pr` đã đặt lại vòng review theo PR
      sau, review PR trước là chấm commit cũ rồi ghi verdict vào vòng của PR mới.
    - `test-suites` chỉ còn giá trị khi ticket còn đang làm (`ACTIVE_STATES`): lượt tranh chấp (PR mang
      `test_dispute` → qa pha `author`) chạy song song với review của chính PR đó; review pass trước thì ticket đã
      approved/merged, giao builder là PR thừa → `_on_pr` ném "không thể approved → in_review" (DDCSV-22, 2026-10-13).
    Đo được (2026-09-04/05): QLKH-004 mở lại 7 lần, 13 lần review block, 10.7M token; sau khi mở lại bus,
    PR tiếp quản 04:10 (đã có 2/3 verdict, hoãn vì qa transient) vẫn nằm hàng đợi cạnh PR tiếp quản mới."""
    tid = str(env.payload.get("ticket_id") or env.key)
    if tid not in o.lead.tickets: return False  # event ngoài delivery-lead (test/relay): không có trạng thái để so
    st = o.lead.state.get(tid)
    if env.topic == "tasks":
        if st == "dispatched": return False
        why = {"state": st, "retry": env.payload.get("retry", 0)}
    elif env.topic == "test-suites":
        if st in ACTIVE_STATES: return False
        why = {"state": st}
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
    """Ghi `ticket.closed` cho ticket vừa vào trạng thái cuối; lead time được đo riêng tại `integration.merged`."""
    for tid, st in list(o.lead.state.items()):
        if st != "closed": continue
        t = o.lead.tickets.get(tid)
        o._audit("ticket.closed", {"ticket_id": tid, "retry": t.retry if t else 0}, once=f"closed:{tid}",
                    ticket_id=tid, project_id=t.project_id if t else None)

def _renumber(o: Orchestrator, tickets: list[Task], project: str) -> None:
    """Mã ticket trùng ticket đã có (đuôi số) → số kế tiếp còn trống cùng tiền tố, `depends_on` trong kế hoạch đi theo.
    Hub 2026-10-14: PLAN-QLKH-DD-CSV-9 bị từ chối vì PLAN-8 vừa lấy DDCSV-46..48 — đầu vào `product[plan]` không mang
    danh sách mã đã cấp nên nó chỉ đoán; cấp mã là việc của code. Kế hoạch tự trùng mã thì để `_check_plan` bắt."""
    ids = [t.ticket_id for t in tickets]
    if len(set(ids)) != len(ids): return
    taken = set(o.lead.tickets) | set(ids)
    mapping: dict[str, str] = {}
    for t in tickets:
        m = re.fullmatch(r"(.*?)(\d+)", t.ticket_id)
        if t.ticket_id not in o.lead.tickets or m is None: continue
        nums = [int(x[1]) for s in taken if (x := re.fullmatch(re.escape(m[1]) + r"(\d+)", s))]
        new = f"{m[1]}{max(nums) + 1:0{len(m[2])}d}"
        mapping[t.ticket_id] = new; t.ticket_id = new; taken.add(new)
    for t in tickets: t.depends_on = [mapping.get(d, d) for d in t.depends_on]
    if mapping: o._audit("plan.renumbered", {"project_id": project, "mapping": mapping}, project_id=project)

TICKET_DA_CO_NOTE = ("Ticket đã có của dự án (chưa closed). Việc đã có ticket đang mở hoặc đã merge thì đừng lập lại — "
                     "nêu mã ticket đó trong ghi chú; mã ticket mới do orchestrator cấp nếu trùng.")


def _ticket_da_co(o: Orchestrator, project: str) -> list[dict[str, str | None]]:
    """Ticket chưa `closed` của dự án cho lượt `product[plan]`. Hub 2026-10-14: PLAN-15 lập lại đúng ba việc PLAN-14
    vừa lập năm phút trước (DDCSV-67/68/69 ≡ 65/66/64) và đoán mã trùng — đầu vào chỉ có change request."""
    # no-ky-thuat: liệt kê mọi ticket chưa closed, ~150 ký tự mỗi dòng, quay lại khi dự án vượt ~300 ticket mở
    return [{"ticket_id": tid, "title": t.title[:140], "state": o.lead.state.get(tid)}
            for tid, t in o.lead.tickets.items()
            if t.project_id == project and o.lead.state.get(tid) != "closed"]


def _plan(o: Orchestrator, env: Envelope, res: StepResult) -> StepResult:
    project = env.payload.get("project_id") or env.key
    if env.topic == "approved-specs":
        sid = f"SPEC-{env.key}"  # key của CHUỖI: dự án, hoặc mã CR đổi requirement (gate + kế hoạch riêng, hub 2026-10-14)
        if sid in o.spec_regate:  # ADR-0059 §2: bản viết lại sau khi security chặn → trình lại gate
            spec_security.regate(o, env, sid)
        if not spec_security.spec_approved_now(o, sid):
            last = next((g for g in reversed(o.gate.history) if g.subject_id == sid), None)
            # ADR-0031 §3: `request_changes` của người = spec-writer viết lại trên event nguồn với lý do làm `hint`.
            # Khoá theo THẾ HỆ gate (`seq`, khuôn 3): event đầu tới sau quyết định (spec cũ đang hoãn) gọi viết lại
            # và ghi khoá; bản viết lại tới sau, thấy khoá, được trình lại gate như một spec mới.
            changes = f"spec.changes:{sid}:{last.seq}" if last is not None and spec_changes_asked(last) else None
            if sid not in o.gate.pending:
                if last is None or (changes is not None and changes in o.once):
                    if (gap := spec_runtime_gap(env.payload)) is not None:
                        return o._spec_runtime_missing(env, project, gap, res)
                    request_gate(o.gate, GateRequest(kind="spec", subject_id=sid, created_by=env.actor,
                                                  checklist=["prd", "acceptance-criteria", "ux-flow", "risks"]))
                elif (changes is not None and (cause := _spec_source(o, env, project)) is not None
                      and not reviewer_rework_capped(o, sid, cause)):
                    _spec_rework(o, env, cause, f"người yêu cầu sửa spec ở gate {sid}: {last.reason}"[:HINT_MAX], res)
                    if res.transient:  # `_act_plan` trả True nên `process()` không tự hoãn: hoãn ở đây, khoá chưa ghi
                        return o._defer_transient(env, res)
                    o._remember(changes)
                    res.actions.append(f"spec_changes:{project}:rework")
                    o._mark(env, res); return res
                else:
                    res.actions.append(f"gate:{sid}:{last.decision}"); o._mark(env, res); return res
            return o._defer(env, res, f"gate:{sid}")
        if not o._threat_model(env, sid, res):
            if res.transient: return o._defer_transient(env, res)  # lượt viết lại (ADR-0059) chưa chạy được
            o._mark(env, res); return res
        live = [pid for pid, p in o.plans.items() if p.get("source_key", p["project_id"]) == env.key and p["source_topic"] == "approved-specs"]
        if live:
            # Spec publish lặp (pha `spec` chạy lại, người publish hai lần) không được sinh plan thứ hai cho cùng
            # dự án: ticket trùng, hai lần giao cho một việc. ADR-0037 bỏ gate plan nên `o.plans` chỉ chứa kế hoạch
            # đã qua `_check_plan` và đã dispatch — có mặt ở đây là đang sống, không cần hỏi gate nữa.
            o._audit("plan.duplicate_spec", {"project_id": project, "event_id": env.event_id, "existing": live}, project_id=project)
            res.actions.append(f"plan_skipped:{','.join(live)}"); o._mark(env, res); return res
    if env.topic == "change-requests": _retire_replanned(o, env, res)  # ADR-0051: CR replan → đóng ticket cũ trước
    cal = o.supervisor.calibration()  # vòng học: bài học estimate-vs-actual quay lại người ước lượng
    extra: dict[str, object] = {"estimate_calibration": cal} if cal else {}
    if (da_co := _ticket_da_co(o, project)):
        extra["ticket_da_co"] = {"ghi_chu": TICKET_DA_CO_NOTE, "items": da_co}
    inp = env.model_copy(update={"payload": {**env.payload, **extra}}) if extra else env
    try:
        g = o.runner.generate(ROLE.PRODUCT, inp, "tasks", many=True, phase=PHASE.PLAN)
    except TransientError as e:
        res.actions.append(f"transient:{ROLE.PRODUCT}:{str(e)[:120]}"); res.reset_s = moc_reset(e)
        with o._lock: o.stats["transient"] += 1
        return o._defer_transient(env, res)
    except (RunnerError, LLMError) as e:
        res.actions.append(f"error:{ROLE.PRODUCT}:{str(e)[:120]}")
        with o._lock: o.stats["errors"] += 1
        o._mark_unhandled(env, ROLE.PRODUCT, e, res)  # trước 2026-09-23: _mark rồi im — dự án chết mà status xanh
        o._mark(env, res); return res
    if g.context_writes:  # C4, API contract lên blackboard TRƯỚC `_check_plan` để nó thấy được (ADR-0037)
        o.runner.write_context(ROLE.PRODUCT, env, g.context_writes)
    tickets = [Task.model_validate(p) for p in g.payloads]
    _renumber(o, tickets, project)
    problems = o._check_plan(tickets, project)
    n = 1 + sum(1 for p in o.plans.values() if p["project_id"] == project)
    plan_id = f"PLAN-{project}-{n}"
    plan = {"plan_id": plan_id, "project_id": project, "source_event": env.event_id, "source_topic": env.topic, "source_key": env.key,
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
        res.actions.append("dispatch:" + ",".join(o._dispatch_plan(plan_id, cause=env)))
        with o._lock: o.stats["plans"] += 1
    o._mark(env, res)
    return res

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
            if (wait := cho_hen(res)) is not None:  # "thử lại sau Ns" hoặc mốc "resets 6:30pm" (hub 2026-10-13)
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
        g = o.runner.generate(ROLE.SECURITY, spec_security.with_gate_decision(o, env, sid), "review-results")
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
        if spec_security.rework_after_block(o, env, sid, p, res):  # ADR-0059: trả về product, trình lại gate
            return False
        # Quá trần / không có event nguồn → hỏi người qua gate: duyệt escalation = chạy lại event spec.
        o._mark_unhandled(env, ROLE.SECURITY, f"security chặn spec: {json.dumps(p.get('findings', []), ensure_ascii=False)[:200]}", res)
        return False
    res.actions.append(f"threat-model:{sid}:{p['verdict']}"); return True

def _dispatch_plan(o: Orchestrator, plan_id: str, replaying: bool = False, cause: Envelope | None = None) -> list[str]:
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
                o.lead.dispatch(t, plan_id, cause); pending.remove(t); done.append(t.ticket_id)
    finally:
        o.lead.replaying = prev
    if plan.get("source_topic") == "change-requests" and (old := o.lead.replan_of.get(str(plan.get("source_key")))):
        o.lead.note_replacement(old, [t["ticket_id"] for t in plan["tickets"]])  # ADR-0051 bổ sung 2026-10-16
    return done


# ---------- bảng chuyển giao (K1.7, orch/fsm.py) — dùng bởi Orchestrator.process() ----------

def _act_superseded(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    return o._superseded(env, res)  # True: event cũ đã bị vượt, _superseded tự _mark — process() dừng ngay


def _rework_no_change(env: Envelope, o: Orchestrator) -> bool:
    """ADR-0057 §1: PR của ticket ĐÃ tích hợp mà nhánh không đi trước nhánh tích hợp = lượt làm lại không đổi code."""
    tid = str(env.payload.get("ticket_id") or env.key)
    return o.lead.state.get(tid) == "in_review" and tid in o.integrated and not o._branch_ahead(tid)


def _act_rework_no_change(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    """Không review lại commit đã tích hợp, không về `approved` (sẽ sinh RC trùng sha): ticket về `merged`, việc lý do
    từ chối đòi thành change request cho planner. Đo được QLKH-DD-CSV 2026-10-13: REL-022…025 cùng sha 4ef9665."""
    tid = str(env.payload.get("ticket_id") or env.key)
    o.lead.mark_done_already_integrated(tid)
    cid = o.lead.request_change_after_noop_rework(tid)
    o._audit("rework.no_change", {"ticket_id": tid, "pr_ref": env.payload.get("pr_ref"), "change_id": cid},
             ticket_id=tid, project_id=o.project_for(env))
    res.actions.append(f"rework_no_change:{tid}")
    o._mark(env, res)
    return True


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
    Transition("superseded", frozenset({"tasks", "pull-requests", "test-suites"}), _act_superseded),
    Transition("rework_no_change", frozenset({"pull-requests"}), _act_rework_no_change, guard=_rework_no_change),
    EMPTY_PR,  # PR 0 file của ticket chưa từng tích hợp → blocked + REPLAN, không review (orch/pr_rong.py)
    Transition("learn_repo", frozenset({"research-requests"}), _act_learn_repo),
    Transition("plan", frozenset(PLAN_INPUTS), _act_plan, guard=lambda env, o: PLAN_INPUTS[env.topic](env, o)),
    Transition("clarification_fallback", frozenset({"clarification-questions"}), _act_clarification_fallback, guard=lambda env, o: not env.payload.get("questions")),
]
