"""Vòng lặp chính: hàng đợi, nạp event từ bus, chạy lô song song, nhịp watch, hoãn/đánh dấu/audit
(tách khỏi orchestrator.py theo ADR-0034).

Mỗi hàm nhận `o: Orchestrator` làm tham số đầu, gán làm method trên `Orchestrator`
(`run = scheduler.run`, `tick = scheduler.tick`, …) — `self` tự bind qua descriptor của Python nên bề
mặt gọi cũ (`o.run()`, `o.tick()`, `o._audit(...)`) không đổi.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..delivery import DONE_STATES
from ..events import AuditLog, Envelope
from ..routing import retry_after_seconds
from .cli import _fmt, source_fingerprint
from .guards import clarification_warnings
from .quality_flow import note_env, sync_quality
from .routes import ACTIVE_STATES, ACTOR, CONTROL_TOPICS, PAUSING, PLAN_INPUTS, REVIEW_AGENT, review_route

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def _actionable(o: Orchestrator, env: Envelope) -> bool:
    # gate.decide giả (actor không phải người) không chạy. Hỏi `o.gate._trusted` (company) chứ không `trusted_decision`
    # (core): chỉ bản company biết nhánh `trusted_autoapprove` — hỏi core thì quyết định do code tự duyệt (ADR-0043)
    # được ghi vào gate nhưng không bao giờ chạy, release "đã duyệt" mà không lên production.
    if env.topic == "audit-log": return o.gate._trusted(env) is not None
    return env.topic not in CONTROL_TOPICS

def _track_pause(o: Orchestrator, env: Envelope) -> None:
    act, target = env.payload["action"], env.payload["target"]
    if act in PAUSING: o.paused.add(target)
    elif act == "resume": o.paused.discard(target)

def _on_event(o: Orchestrator, env: Envelope) -> None:
    note_env(o, env)  # ADR gốc 0021: profile người ghim từ tiến trình khác (gate CLI) — chỉ ghi nhận, không chạy gì
    if env.topic == "supervisor-actions":
        o._track_pause(env)
        if env.payload["action"] == "resume": o._retry_deferred()
    elif o._actionable(env):
        with o._qlock: o.queue.append(env)

def target(env: Envelope) -> str:
    return str(env.payload.get("ticket_id") or env.key)

def _parallel_ok(o: Orchestrator, env: Envelope) -> bool:
    """Event chạy được cùng lúc với event khác key? Gate decide, lập kế hoạch, RC (merge tích hợp), clarifier
    (rẽ nhánh theo trạng thái) luôn chạy một mình vì chúng đổi trạng thái chung."""
    if env.topic in {"audit-log", "release-candidates", "clarification-questions"}: return False
    if env.topic in PLAN_INPUTS and PLAN_INPUTS[env.topic](env, o): return False
    return True

def _take_batch(o: Orchestrator, n: int) -> list[Envelope]:
    """Lấy tối đa n event có target khác nhau từ đầu hàng đợi (giữ thứ tự trong cùng key)."""
    with o._qlock:
        batch = [o.queue.pop(0)]
        if n <= 1 or not o._parallel_ok(batch[0]):
            return batch
        keys, i = {target(batch[0])}, 0
        while i < len(o.queue) and len(batch) < n:
            e = o.queue[i]; k = target(e)
            if o._parallel_ok(e) and k not in keys: batch.append(o.queue.pop(i)); keys.add(k)
            else: i += 1
        return batch

def run(o: Orchestrator, max_steps: int | None = None, workers: int | None = None) -> list[StepResult]:
    """Xử lý hàng đợi đến khi rỗng (hoặc đủ max_steps). Event bị hoãn không làm vòng lặp quay mãi.
    `workers` > 1: mỗi vòng lấy một lô event khác key và chạy song song (ADR-0012)."""
    workers = workers or o.workers
    out: list[StepResult] = []
    while o.queue and (max_steps is None or len(out) < max_steps):
        # Nạp event của tiến trình khác ở MỌI vòng, không chỉ ở đầu `tick()`: khi công ty tự nuôi hàng đợi (mỗi
        # lượt agent sinh event mới), `run()` không bao giờ cạn và `tick()` không quay lại `poll()` — quyết định
        # gate người ký bằng `gate_cli` nằm trong sqlite hàng chục phút, `gate_cli list` báo trống mà orchestrator
        # vẫn coi gate đang chờ. Đo được 2026-09-06 (QLKH): 4 gate escalation REL-020..023 ký 10:55–11:01, hàng
        # đợi bận liên tục từ 10:50, chưa cái nào được áp sau 12 phút; lead ký 03:06 lúc hàng đợi rỗng thì áp trong 1 s.
        if hasattr(o.bus, "poll"): o.bus.poll()
        # Reload GIỮA hai lô (không lượt model nào đang chạy) chứ không đợi hàng đợi rỗng: công ty bận thì hàng
        # đợi hiếm khi rỗng, bản vá đã merge nằm chờ hàng giờ. Hàng đợi không mất — tiến trình mới dựng lại từ bus.
        o._maybe_reload()
        room = workers if max_steps is None else max(1, min(workers, max_steps - len(out)))
        batch = o._take_batch(room)
        if len(batch) == 1:
            results = [o.process(batch[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="orch") as ex:
                results = list(ex.map(o.process, batch))
        out += [r for r in results if r is not None]
        o._check_escalations()
        o._integrate_pending(out)
    o._check_escalations()  # supervisor escalate ở event cuối hàng đợi: gate vẫn phải mở, không chờ event kế tiếp
    o._integrate_pending(out)
    return out

def _integrate_pending(o: Orchestrator, out: list[StepResult]) -> None:
    """Ticket approved mà chưa lên nhánh tích hợp thì merge ngay, không phụ thuộc vào việc có event nào của nó
    được xử lý: review-results cuối cùng có thể bị hoãn (ticket vừa bị supervisor cắt ngân sách) và từ F15 ticket
    phụ thuộc chỉ bắt đầu sau khi merge — không có bước này dự án đứng im."""
    from ..orchestrator import StepResult  # nhập lười: StepResult định nghĩa sau lúc orchestrator.py nhập module này
    if not o._has_integration(): return
    res = StepResult("integration", "integration", "-")
    o._integrate_approved(res)
    if res.actions: out.append(res)

def _the_he(o: Orchestrator, sid: str) -> str:
    """Thế hệ của gate đang mở cho `sid`: số thứ tự `GateRequest.seq` do `HumanGate.request()` gán. Cùng một
    subject có thể mở gate NHIỀU LẦN trong đời (duyệt → hỏng → mở lại; `escalation` sau `release`), và
    `HumanGate.pending` khoá theo `subject_id` nên gate mới ghi đè gate cũ dưới đúng cái tên đó. Khoá `once`
    chỉ mang `sid` là lần quá hạn của gate THỨ HAI bị lần quá hạn của gate thứ nhất nuốt: không audit
    `gate.overdue`, không escalate — gate bể hạn nằm im y hệt một gate mới (TRAPS §1 khuôn 3).

    Trước 2026-09-09 thế hệ là `created_at.isoformat(microseconds)`, và nó hỏng theo hai đường (chi tiết ở
    `GateRequest.seq`): đồng hồ Windows bước ~15,6 ms nên hai gate mở gần nhau CÙNG dấu thời gian, và phát lại
    thì `created_at` là bây giờ nên khoá đổi sau mỗi restart. Bộ đếm không đọc đồng hồ và phát lại cùng một
    log cho cùng một số.

    Gate đã rời `pending` (vừa được quyết) thì không còn thế hệ để đọc; trả `"-"` để khoá vẫn xác định được,
    không ném."""
    r = o.gate.pending.get(sid)
    return str(r.seq) if r is not None else "-"


def tick(o: Orchestrator, now: datetime | None = None) -> list[StepResult]:
    """Một nhịp của chế độ watch: nạp event từ tiến trình khác, thử lại event hoãn vì lỗi transport, chạy hàng đợi,
    nhắc gate quá hạn, giao lại review quá hạn, escalate ticket im lặng quá lâu."""
    from ..orchestrator import StepResult  # nhập lười, lý do như trong _integrate_pending
    if hasattr(o.bus, "poll"): o.bus.poll()
    o._retry_deferred(only="transient:")
    results = o.run()
    remind, overdue = o.gate.due(now)
    for sid in [*remind, *overdue]:
        # Khoá `once` phải mang cả GIAI ĐOẠN: một gate luôn đi qua `remind` (12h) trước rồi mới tới `overdue`
        # (24h), nên dùng chung `gate:{sid}` là lần nhắc nuốt luôn lần quá hạn — `gate.overdue` không bao giờ
        # vào audit-log. Audit-log là bản ghi bền duy nhất và `metrics` đọc "gate chờ" từ đó, nên một gate bể
        # hạn đọc ra y hệt một gate mới chỉ được nhắc.
        pha = "overdue" if sid in overdue else "remind"
        o._audit(f"gate.{pha}", {"subject_id": sid}, once=f"gate:{sid}:{pha}:{_the_he(o, sid)}")
    for sid in overdue:  # quá hạn không tự đi tiếp, nhưng cũng không im lặng: supervisor nhận việc
        # Khoá chống lặp của supervisor (`_escalated_once`) chỉ sống trong RAM: mở lại bus là escalate lại cùng gate
        # (khuôn 2). `o.once` dựng lại từ audit nên mới là thứ chặn được lần thứ hai.
        key = f"gate.escalate:{sid}:{_the_he(o, sid)}"
        if key in o.once: continue
        o._remember(key)
        o.supervisor.escalate_gate(sid, f"gate quá hạn {o.gate.timeout}", once_key=key)
    for tid, missing in o.lead.overdue_reviews(now).items():
        pr = o.latest("pull-requests", tid)
        since = o.lead.review_since[tid].isoformat()  # đọc trước: _call bên dưới có thể đóng vòng review và xoá nó
        for src in sorted(missing):
            key = f"review:{tid}:{src}:{since}"
            if pr is None or key in o.once: continue
            o._remember(key); o._audit("review.reassign", {"ticket_id": tid, "source": src}, ticket_id=tid)
            res = StepResult(pr.event_id, pr.topic, pr.key)
            o._call(REVIEW_AGENT[src], pr, review_route(REVIEW_AGENT[src]), res)
            results.append(res)
            # Giao lại chỉ một lần (`once`): lượt thứ hai cũng lỗi/quá hạn thì không ai giao nữa và ticket nằm
            # `in_review` mãi. Đưa cho người: supervisor escalate → ticket hoãn, gate `escalation` mở.
            failed = [a for a in res.actions if a.split(":", 1)[0] in {"error", "handler_error", "transient"}]
            if failed:
                o._audit("review.reassign_failed", {"ticket_id": tid, "source": src, "error": failed[0][:300]}, ticket_id=tid)
                o.supervisor.escalate_gate(tid, f"review {src} giao lại vẫn lỗi: {failed[0][:200]}", once_key=f"review.escalate:{key}")
    active = {tid for tid, st in o.lead.state.items() if st in ACTIVE_STATES}
    o.supervisor.check_timeouts(now, active=active)
    results += o._assume_clarifications(now)  # câu hỏi làm rõ quá hạn → giả định theo default, pha spec chạy
    # `flush_releases` (chế độ gom release) trước đây chỉ được gọi ngay lúc MỘT ticket vừa review pass
    # (`_on_review`) hoặc lúc đóng một ticket escalated (`_on_escalation_decided`, reject/rollback) — không có
    # nhịp nào gọi lại sau đó. Ticket approved từ TRƯỚC một lần orchestrator restart (RC không được tạo lại khi
    # replay — đúng chủ đích, xem "F19" ở `DeliveryLead.flush_releases`) hay approved đúng lúc dự án đang có
    # ticket khác in-flight (flush bị chặn, không ai gọi lại khi ticket đó xong) nằm `approved` vĩnh viễn: không
    # ticket nào, không gate nào — `status` báo `queue: 0, blocked: []` xanh hết trong khi việc đã xong không bao
    # giờ được giao. Đo được 2026-09-10 (QLKH): 16 ticket approved đứng im nhiều ngày sau một lần restart.
    for pid in {t.project_id for t in o.lead.tickets.values()}:
        o.lead.flush_releases(pid)
    results += o.run()
    return results

def watch(o: Orchestrator, interval: float = 5.0, max_ticks: int | None = None, reload: bool = False) -> None:
    from ..orchestrator import ReloadRequested  # nhập lười: orchestrator.py nhập module này lúc định nghĩa class,
    # ReloadRequested chưa tồn tại tới khi class đó chạy xong thân — nhập ở đỉnh file gây vòng lặp import.
    """`reload=True`: mã nguồn của công ty (src/company, agents, skills, gates, llm.yaml) đổi trên đĩa → khi hàng
    đợi rỗng và không việc gì đang chạy, ném `ReloadRequested` để `main` khởi động lại tiến trình với mã mới.
    Trước đây mỗi PR merge là người phải taskkill + xoá lock + chạy lại bằng tay (2026-09-06: 4 lần trong một
    buổi); quên xoá lock thì tiến trình mới thoát ngay mà tưởng đã restart."""
    # Bật cờ TRƯỚC nhịp đầu: `run()` kiểm reload giữa hai lô ngay từ tick 1. Đặt sau tick (bản cũ) thì tick đầu
    # không bao giờ ném từ trong run(), nhánh `except ReloadRequested` chỉ chạy được từ tick 2 trở đi.
    o.reload_on_change = reload
    n = 0
    while max_ticks is None or n < max_ticks:
        try:
            for r in o.tick(): print(_fmt(r))
        except ReloadRequested:  # reload giữa hai lô ném từ trong run(): là yêu cầu, không phải lỗi nhịp
            raise
        except Exception as e:  # một nhịp lỗi (bus/git/handler) không được giết vòng watch
            o._audit("tick_error", {"error": f"{type(e).__name__}: {str(e)[:300]}"})
            print(f"tick_error: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        o._maybe_reload()
        n += 1
        if max_ticks is None or n < max_ticks: time.sleep(interval)

def _maybe_reload(o: Orchestrator) -> None:
    from ..orchestrator import ReloadRequested  # nhập lười, lý do như trong watch()
    if not o.reload_on_change: return
    fp = source_fingerprint()
    if fp == o.source_fp: return
    o._audit("orchestrator.reload", {"changed": fp[1], "files": fp[0], "queue": len(o.queue)})
    print(f"mã nguồn đổi ({fp[1]}) — khởi động lại với mã mới", file=sys.stderr)
    raise ReloadRequested(fp[1])

def transient_limit() -> float:
    """Một event hoãn `transient:` (backend chập chờn/hết quota) được thử lại tối đa bao lâu (giây) trước khi
    thành việc của người. `COMPANY_TRANSIENT_MAX_H`, mặc định 2 giờ — đủ hai lượt cooldown quota 1h."""
    return float(os.environ.get("COMPANY_TRANSIENT_MAX_H") or 2) * 3600

def _defer(o: Orchestrator, env: Envelope, res: StepResult, reason: str, wait_s: float | None = None) -> StepResult:
    """`wait_s`: backend nói rõ phải chờ bao lâu → không thử lại trước mốc đó (xem `_retry_deferred`).
    `transient:` quá `transient_limit()` kể từ lần hoãn đầu → không hoãn nữa: `_mark_unhandled` (gate escalation)
    và đánh dấu đã xử lý. Trước 2026-09-23 không có trần: mỗi nhịp thử lại một lần, mãi mãi, không ai được hỏi.
    Mốc đầu chỉ sống trong RAM — restart là đếm lại từ đầu (chấp nhận: restart hiếm hơn nhiều so với 2h)."""
    if reason.startswith("transient:"):
        t0 = o.transient_since.setdefault(env.event_id, time.monotonic())
        if time.monotonic() - t0 > transient_limit():
            with o._lock: o.transient_since.pop(env.event_id, None)
            agent = reason.split(":", 2)[1] if reason.count(":") >= 2 else ACTOR
            o._mark_unhandled(env, agent, f"hoãn transient quá {int(transient_limit())}s: {reason[:200]}", res)
            o._mark(env, res); return res
    with o._lock:
        o.deferred[env.event_id] = (env, reason); res.deferred = reason; o.stats["deferred"] += 1
        if wait_s and wait_s > 0:
            o.defer_until[env.event_id] = time.monotonic() + float(wait_s)
            res.deferred = f"{reason} (chờ {int(wait_s)}s)"
            ghi_hen = True
        else:
            ghi_hen = False
    if ghi_hen:
        # Mốc hẹn phải BỀN và theo GIỜ TƯỜNG. `defer_until` dùng `time.monotonic()` — vô nghĩa ở tiến trình
        # khác — và cả `deferred` lẫn nó đều chỉ sống trong RAM, trong khi `_rehydrate` đẩy mọi event chưa
        # xử lý thẳng vào `o.queue`. Nên restart giữa lúc chờ quota là mất hẹn và đập ngay vào backend
        # đã cạn: vô ích, bẩn audit-log, và có thể bị phạt nặng hơn.
        #
        # Đo được khi chạy thật (2026-09-04 15:46:30): cả hai backend trả 429, hệ thống hoãn 2010s đúng
        # theo hẹn; nhưng `status` từ tiến trình khác đọc ra `deferred: {}` — mốc hẹn không tồn tại ngoài
        # RAM của tiến trình đang chạy.
        o._audit("defer.until", {"event_id": env.event_id, "reason": reason, "wait_s": int(wait_s or 0),
                                    "until": (datetime.now(UTC) + timedelta(seconds=float(wait_s or 0))).isoformat()},
                    ticket_id=env.payload.get("ticket_id"), project_id=env.payload.get("project_id"))
    return res

def _defer_transient(o: Orchestrator, env: Envelope, res: StepResult) -> StepResult:
    """Hoãn event vì một lượt agent gặp `TransientError` (`res.transient`), giữ mốc hẹn của backend ("thử lại sau
    1515s"). Một đường cho `process()` và các hành động tự `_mark` (`_plan`): bên đó `process()` không thấy
    `res.transient` vì hành động đã trả True — tự `_mark` thì event bị coi là xong và dự án đứng im."""
    stuck = next((a for a in res.actions if a.startswith("transient:")), "transient:?")
    return _defer(o, env, res, ":".join(stuck.split(":")[:2]), wait_s=retry_after_seconds(stuck))

def _retry_deferred(o: Orchestrator, only: str | None = None) -> None:
    """Đưa event hoãn về đầu hàng đợi; `only` = tiền tố lý do (vd. "transient:") để chỉ thử lại loại đó.
    Event nào backend đã hẹn giờ (`defer_until`) thì chờ đúng hẹn — hỏi lại sớm hơn chỉ tốn một dòng lỗi."""
    now = time.monotonic()
    with o._lock, o._qlock:
        picked = {k: v for k, v in o.deferred.items()
                  if (only is None or v[1].startswith(only)) and o.defer_until.get(k, 0.0) <= now}
        for k in picked: o.deferred.pop(k); o.defer_until.pop(k, None)
        o.queue[:0] = [e for e, _ in picked.values()]

def _mark(o: Orchestrator, env: Envelope, res: StepResult) -> None:
    with o._lock:
        o.processed.add(env.event_id); o.partial.pop(env.event_id, None); o.transient_since.pop(env.event_id, None)
    o._audit("orchestrated", {"event_id": env.event_id, "topic": env.topic, "actions": res.actions},
                ticket_id=env.payload.get("ticket_id") or (env.key if env.topic == "tasks" else None),
                project_id=env.payload.get("project_id"))
    # ADR gốc 0021 §c: điểm gọi DUY NHẤT của nghiệm thu quality — mọi event xử lý xong đều qua đây. Dự án không
    # có profile ⇒ trả về ngay, không mở journal, không audit (log `orchestrated` giữ nguyên từng byte).
    sync_quality(o)

def _remember(o: Orchestrator, key: str) -> None:
    """Ghi nhớ bền vững một việc chỉ làm một lần (khôi phục qua replay)."""
    with o._lock: o.once.add(key)
    o._audit("once", {"key": key})

def _audit(o: Orchestrator, action: str, data: dict[str, Any], actor: str = ACTOR, tokens: int = 0, once: str | None = None,
           ticket_id: str | None = None, project_id: str | None = None, cost: float = 0.0) -> None:
    if once:
        with o._lock:
            if once in o.once:
                return
            o.once.add(once)
        o._audit("once", {"key": once})
    a = AuditLog(actor=actor, action=action, tokens=tokens, ticket_id=ticket_id, project_id=project_id,
                 evidence=json.dumps(data, ensure_ascii=False), cost_usd=cost)
    o.bus.publish(Envelope(topic="audit-log", key=actor, actor=actor, payload=a.model_dump()))


def _deadlock_warnings(o: Orchestrator) -> list[str]:
    """Còn ticket chưa xong mà KHÔNG đường nào có thể chạy tiếp → nói thẳng ra.

    Mọi trường trong `status()` đều mô tả trạng thái, không trường nào trả lời "có việc gì chạy được không".
    Nên một dự án chết vẫn đọc ra hoàn toàn bình thường: `queue: 0`, `stalled: {}`, `gates_pending: {}` —
    ba chỉ số xanh vì rỗng, mà rỗng ở đây chính là triệu chứng.

    Đo được khi chạy thật (2026-09-04): QLKH-001 `blocked` lúc 13:25 không mở được gate (xem
    `_check_escalations`), 13 ticket phụ thuộc đứng chờ. `status` không có gì bất thường trong 26 phút; chỉ
    vì có người ngồi đọc từng finding mới phát hiện. Đây là lớp phòng thủ cuối: kể cả khi một nhánh cụ thể
    quên mở gate, câu hỏi "còn việc nào chạy được không" vẫn phải được trả lời trung thực.

    `queue` đếm event chưa được đánh dấu `orchestrated`, nên lượt agent đang bay vẫn tính là có việc — cảnh
    báo này không kêu oan khi hệ thống chỉ đang chờ model trả lời."""
    # KHÔNG miễn trừ `o.paused`: pause luôn cần người gỡ, mà người chỉ được hỏi qua gate. Pause mà không
    # có gate nào chính là ca bế tắc cần kêu to nhất — bản đầu của cảnh báo này miễn trừ `paused` nên mù
    # đúng ca đó (`paused=['P1']`, `gates_pending={}`, `warnings=[]`).
    if o.queue or o.deferred or o.gate.pending or o.stalled: return []
    # Pha TRƯỚC ticket: dự án chờ người trả lời câu hỏi làm rõ mà không gate nào hỏi ai. Bản đầu thoát sớm
    # khi `live` rỗng nên mù toàn bộ intake/research/spec (đo 2026-09-22, CAMPUS-UNI: hỏi vòng 1 lúc 13:11,
    # `warnings: []` suốt buổi). Không phải bế tắc — là "chờ người" chưa có gate — nhưng người phải được nói.
    out = clarification_warnings(o.bus)
    live = {t: st for t, st in o.lead.state.items() if st not in DONE_STATES}
    if not live: return out
    return [*out, f"khong co viec nao chay duoc: {len(live)} ticket chua xong "
                  f"({', '.join(f'{t}={st}' for t, st in sorted(live.items())[:5])}"
                  f"{', ...' if len(live) > 5 else ''}) ma queue/gate/deferred/stalled deu rong"]
