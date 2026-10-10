"""Khôi phục trạng thái phiên từ audit-log khi mở lại bus (tách khỏi orchestrator.py, ADR-0034).

`rehydrate(o)` chạy MỘT LẦN trong `Orchestrator.__init__`, cho MỌI tiến trình kể cả lệnh chỉ-đọc (`status`,
`report`, `show`) — không ghi audit ở đây. Thứ tự duyệt log là nguồn sự thật; mỗi nhánh dựng lại đúng một biến
RAM đã mất khi tiến trình trước dừng.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from xagents_core.bus import is_human

from ..events import Envelope
from ..quality_floor import PROFILE_ACTION
from ..roles import LEAD_ACTOR, ROLE
from ..runner import CONTEXT_ONLY
from .quality_flow import note_profile
from .retry_flow import decide_applied
from .routes import ACTOR, ROUTES

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator


_ORCH_ONLY = frozenset({ACTOR})
#: Dấu "chỉ người" (`human:*`) trong `TRUSTED_WRITERS` — bus đã chặn agent ghi action đó, replay kiểm lại.
HUMAN_ONLY = "human:*"
#: Người ghi THẬT của mỗi action mà `rehydrate` dựng lại trạng thái từ đó — đo từ chính các lời gọi `_audit`
#: (`orch/*.py`, `delivery.py`). `env.actor` là thứ bus kiểm; `actor` trong payload là lời khai. `audit-log` là topic
#: mở và route `change-requests → product → audit-log` publish payload của model, nên một dòng đúng tên action mà
#: sai người ghi là lệnh giả: bỏ qua, không dựng gì (sc-security 2026-09-23, ADR-0043 "còn mở"). Action không có
#: trong bảng: chỉ orchestrator. `gate.decide`: bus đã giới hạn actor (người / orchestrator / code), chỉ đếm.
TRUSTED_WRITERS: dict[str, frozenset[str]] = {
    # `plan.proposed`/`plan_rejected`: nay ghi dưới tên `product` (`orch/ticket_fsm.py`), bus cũ (QLKH 2026-09-09,
    # `tests/test_rehydrate_ke_hoach_cu.py`) ghi dưới tên orchestrator — cả hai đều là code, không agent nào giả được.
    "plan.proposed": frozenset({ROLE.PRODUCT, ACTOR}), "plan_rejected": frozenset({ROLE.PRODUCT, ACTOR}),
    "plan.rework": frozenset({ROLE.PRODUCT, ACTOR}),  # cùng chỗ ghi với hai hàng trên (2026-09-23)
    "ticket.blocked": frozenset({LEAD_ACTOR}), "release.finding_waived": frozenset({LEAD_ACTOR}),
    "ticket.already_integrated": frozenset({LEAD_ACTOR, ACTOR}),
    "gate.decide": frozenset({"*"}),
    PROFILE_ACTION: frozenset({HUMAN_ONLY}),  # ADR gốc 0021 §e: profile người ghim kèm chữ ký spec
}


def _trusted_writer(action: Any, actor: str) -> bool:
    allowed = TRUSTED_WRITERS.get(action, _ORCH_ONLY)
    return "*" in allowed or actor in allowed or (HUMAN_ONLY in allowed and is_human(actor))


def rehydrate(o: Orchestrator) -> None:
    from ..orchestrator import _evidence
    # Một lần duyệt log, không hai: `replay()` trên bus bền vững parse lại từng envelope, nên quét đôi là nhân đôi
    # thời gian mở lại một dự án đã chạy lâu.
    log = list(o.bus.replay())
    # Thứ tự trong log của lần `orchestrated` / `project.retried` gần nhất cho từng event: dùng ở cuối hàm
    # để nhận lại lệnh thử-lại chưa kịp chạy (xem chú thích ở đó).
    last_done: dict[str, int] = {}
    last_retry: dict[str, tuple[int, dict[str, Any]]] = {}   # event_id → (thứ tự trong log, bản ghi stalled)
    hen: dict[str, tuple[str, str]] = {}                     # event_id → (mốc hẹn ISO, lý do hoãn)
    quyet: list[tuple[str, str]] = []                        # (event_id của gate.decide, subject_id)
    duyet: list[tuple[str, int, str, int]] = []              # approve gặp `unhandled`: (event_id, thứ tự, subject, số RC)
    bo_idx: dict[str, int] = {}                              # subject → thứ tự `agent_error_unhandled` cuối
    for i, env in enumerate(log):
        if env.topic == "audit-log" and _trusted_writer(env.payload.get("action"), env.actor):
            a = env.payload; d = _evidence(a)
            # `event.retried` (`_retry_unhandled`) cùng họ với `project.retried`: lệnh chạy lại chỉ sống trong RAM,
            # thiếu nó thì restart trước khi event chạy lại là dấu `orchestrated` của LẦN LỖI thắng (audit 2026-09-23).
            if a["action"] in {"project.retried", "event.retried"} and d.get("event_id"):
                last_retry[str(d["event_id"])] = (i, d)
            if a["action"] == "orchestrated":
                o.processed.add(d["event_id"]); last_done[str(d["event_id"])] = i
            elif a["action"] == "once": o.once.add(d["key"])
            elif a["action"] == "plan.proposed":
                # ADR-0037: `plan.proposed` chỉ được ghi khi `_check_plan` không trả problem nào, và lúc đó ticket
                # đã được giao ngay — nên dựng lại trạng thái phải giao lại ở ĐÚNG chỗ này trong log, không chờ
                # một `gate.decide` không bao giờ tới nữa (khuôn 2 `TRAPS.md`: state chỉ sống trong RAM).
                # Giao ở đây cũng đúng thứ tự thời gian hơn nhánh cũ: mọi `tasks`/`ticket.blocked` của kế hoạch
                # này nằm SAU trong log nên vẫn ghi đè được trạng thái `dispatched`/`waiting` dựng ở đây.
                o.plans[d["plan_id"]] = d
                o.lead.plans_ok.add(str(d["plan_id"]))
                o._dispatch_plan(str(d["plan_id"]), replaying=True)
            elif a["action"] == "release.void": o._void(d["release_id"])
            # `release.staged`/`acceptance.auto` dựng lại sha sẽ lên production và ticket đã đóng — sau ADR-0043 không
            # còn người ký chen giữa, nên chỉ tin dòng do CHÍNH orchestrator ghi (`env.actor` do bus kiểm; audit-log
            # là topic mở, agent ghi được action tuỳ ý — sc-security 2026-09-23).
            elif a["action"] == "release.staged": o.release_sha[d["release_id"]] = d["sha"]
            elif a["action"] == PROFILE_ACTION: note_profile(o, d)
            elif a["action"] == "delivery.done": o.delivered[d["release_id"]] = d
            elif a["action"] == "acceptance.auto":  # ADR-0043 §3: nghiệm thu máy không có acceptance-results để replay
                prev_r, o.lead.replaying = o.lead.replaying, True
                try: o.lead.close_accepted(str(d["release_id"]))
                finally: o.lead.replaying = prev_r
            elif a["action"] == "delivery.rolled_back": o.delivered.pop(d["release_id"], None)
            elif a["action"] == "ticket.abandoned":  # khi chạy `close_escalated` đặt `closed`; dựng lại phải giống
                o.lead.state[str(d["ticket_id"])] = "closed"; o.lead.abandon(d["ticket_id"])
            elif a["action"] == "defer.until" and d.get("event_id"):
                hen[str(d["event_id"])] = (str(d.get("until") or ""), str(d.get("reason") or "transient:?"))
            elif a["action"] == "ticket.blocked":
                # xem chú thích ở `DeliveryLead._retry`: không dựng lại `blocked` thì ticket quay về
                # `dispatched` và người duyệt escalation bấm approve cũng không mở lại được nó.
                o.lead.state[str(d["ticket_id"])] = "blocked"
            elif a["action"] == "ticket.already_integrated" and d.get("state"):
                # Đối xứng với `ticket.blocked` ở trên: người đã quyết "việc này xong rồi" (code đã ở nhánh
                # tích hợp, xem `DeliveryLead.mark_done_already_integrated`). Không dựng lại thì mở lại bus là
                # `ticket.blocked` CŨ (nằm trước trong log) thắng, ticket quay về `blocked` và vòng lặp
                # escalation → duyệt → agent không có gì sửa → block mở lại từ đầu.
                o.lead.state[str(d["ticket_id"])] = str(d["state"])
            elif a["action"] == "integration.merged":
                o.integrated.add(d["ticket_id"])
                prev_r, o.lead.replaying = o.lead.replaying, True
                try: o.lead.mark_integrated(d["ticket_id"])
                finally: o.lead.replaying = prev_r
            elif a["action"] == "threat_model.missing": o.missing_threat_model.add(d["subject_id"])
            elif a["action"] == "project.stalled":
                o.stalled[d["project_id"]] = d; o.stall_count[d["event_id"]] += 1
            elif a["action"] in {"project.retried", "project.closed"}: o.stalled.pop(d["project_id"], None)
            elif a["action"] == "agent_error_unhandled" and d.get("subject"):
                o.unhandled[str(d["subject"])] = d; bo_idx[str(d["subject"])] = i
                o.unhandled_count[str(d.get("event_id"))] += 1
            elif a["action"] == "plan_rejected" and d.get("source_event"):
                o.plan_reworks[str(d["source_event"])] += 1
                o.unhandled[str(d["project_id"])] = {"agent": ROLE.PRODUCT, "topic": d.get("source_topic"),
                                                        "event_id": d["source_event"], "subject": str(d["project_id"])}
            elif a["action"] == "spec.runtime_missing": o.spec_runtime_reworks[str(d["project_id"])] += 1
            elif a["action"] == "plan.rework" and d.get("source_event"): o.plan_reworks[str(d["source_event"])] += 1
            elif a["action"] == "spec.runtime_escalated" and d.get("source_event"):
                o.unhandled[str(d["project_id"])] = {"agent": ROLE.PRODUCT, "topic": d.get("source_topic"),
                                                        "event_id": d["source_event"], "subject": str(d["project_id"]),
                                                        "error": f"spec_runtime_missing: {str(d.get('reason', ''))[:200]}"}
            elif a["action"] in {"event.retried", "event.abandoned"}:
                o.unhandled.pop(str(d.get("subject")), None)
                o.spec_runtime_reworks.pop(str(d.get("subject")), None)
                o.plan_reworks.pop(str(d.get("event_id")), None)
            elif a["action"] == "gate.decide" and env.event_id in o.gate.closers:  # như `_on_gate_decide`: bản trùng không tính
                if d.get("subject_id"): quyet.append((env.event_id, str(d["subject_id"])))
                sid = str(d.get("subject_id") or "")
                if d.get("decision") == "approve" and sid in o.unhandled and (
                        sid in o.lead.release_tickets or o.lead.state.get(sid) == "dispatched"):
                    duyet.append((env.event_id, i, sid, len(o.lead.releases)))
            elif a["action"] == "integration.conflict":
                o.conflict_retries[str(d["ticket_id"])] += 1
            elif a["action"] == "ticket.continued":
                o.turn_continuations[str(d["ticket_id"])] += 1
            elif a["action"] == "ticket.reopened":  # người mở lại: đếm lại từ 0 như `retry` (`DeliveryLead.reopen`)
                o.turn_continuations.pop(str(d["ticket_id"]), None); o.conflict_retries.pop(str(d["ticket_id"]), None)
            elif a["action"] == "release.finding_waived":
                o.lead.release_waived[str(d["release_id"])].add(str(d["source"]))
            elif a["action"] == "debt.escalated": o.debt_gate[str(d["project_id"])] = d
            elif a["action"] == "debt.decided": o.debt_gate.pop(str(d["project_id"]), None)
        elif env.topic == "supervisor-actions": o._track_pause(env)
        elif env.topic == "shared-context": o.blackboard._on(env)
        else:
            if env.topic == "research-requests": o._learn_repo(env, replaying=True)
            o.lead.replay(env)
        if env.actor in o.agents and env.causation_id:
            # Đầu ra agent đã publish cho event chưa được đánh dấu xong (crash giữa hai route): agent đó KHÔNG chạy
            # lại khi mở lại — tốn token và sinh PR/review trùng. `partial` được dựng lại từ causation_id.
            o.partial.setdefault(env.causation_id, set()).add(f"{env.actor}:{env.topic}")  # slot = "<agent>:<topic_out>" (PR-5b)
        o.supervisor.replay(env)
    # Lệnh thử-lại chỉ sống trong RAM: `_retry_stalled` bỏ dấu `processed` rồi đẩy event vào `o.queue`.
    # Restart giữa lúc đó là mất trắng — event vẫn mang dấu `orchestrated` của LẦN LỖI, nên hàng đợi dựng lại
    # loại nó ra và dự án nằm im vĩnh viễn dù người đã bấm duyệt. Đo được khi chạy thật (2026-09-04): duyệt
    # gate escalation lúc 06:51:31, restart lúc 06:51:45, sau đó không một dòng `orchestrated` nào nữa.
    # Ai đã bảo "chạy lại" mà event chưa được xử lý lại thì phải bỏ dấu để hàng đợi nhận lại — TRỪ khi việc
    # đó đã có người khác làm xong trong lúc chờ (xem `_retry_con_can`).
    for idx, sid in _duyet_chua_chay_lai(o, duyet, bo_idx):
        rec = o.unhandled.pop(sid); last_retry[str(rec["event_id"])] = (idx, rec)
    reopened = {eid for eid, (idx, rec) in last_retry.items()
                if idx > last_done.get(eid, -1) and o._retry_con_can(log, idx, rec)}
    # KHÔNG audit ở đây: `_rehydrate` chạy trong MỌI tiến trình, kể cả lệnh chỉ-đọc (`status`, `report`,
    # `show`, console). Ghi bus từ đường đọc là mỗi lần xem trạng thái lại thêm một dòng rác — chính tôi
    # đã mắc và thấy nó trong log. Việc mở lại sẽ tự hiện ra ở dòng `orchestrated` khi event thật sự chạy.
    o.processed -= reopened
    # Chỉ đếm quyết định ĐÃ xử lý: decide còn trong hàng đợi sẽ được `_on_gate_decide` đếm khi chạy — đếm cả hai
    # nơi là bộ đếm sống lệch bộ đếm dựng lại, restart sau đó sinh khoá escalation trùng khoá cũ và gate bị nuốt
    # (CAMPUS-UNI/TCK-001, 2026-09-24). Decide đã ÁP rồi bị hoãn transient (`DECIDE_APPLIED`) cũng đã đếm: lần xử lý
    # lại chỉ gọi lại lượt agent, không đếm nữa.
    for eid, sid in quyet:
        if eid in o.processed or decide_applied(o.once, eid) is not None: o.escalation_decided[sid] += 1
    o.partial = {k: v for k, v in o.partial.items() if k not in o.processed}
    o.queue = [e for e in log if o._actionable(e) and e.event_id not in o.processed]
    o._nap_lai_hen(hen)



def _nap_lai_hen(o: Orchestrator, hen: dict[str, tuple[str, str]]) -> None:
    """Event còn hẹn chờ thì vào `deferred`, KHÔNG vào hàng đợi chạy ngay.

    Không có bước này thì bản ghi `defer.until` chỉ là một dòng log đẹp: `_rehydrate` vẫn đẩy event vào
    `o.queue` và nhịp chạy đầu tiên gọi thẳng backend đang cạn quota.

    Mốc hẹn lưu theo GIỜ TƯỜNG nên quy được về `monotonic` của tiến trình này; hẹn đã qua thì bỏ, để event
    chạy bình thường. Event đã xong không nằm trong hàng đợi nên hẹn cũ của nó vô hại."""
    if not hen: return
    gio, mono = datetime.now(UTC), time.monotonic()
    giu: list[Envelope] = []
    for e in o.queue:
        moc, ly_do = hen.get(e.event_id, ("", ""))
        con = 0.0
        if moc:
            try: con = (datetime.fromisoformat(moc) - gio).total_seconds()
            except ValueError: con = 0.0          # mốc hỏng: thà chạy còn hơn kẹt vĩnh viễn
        if con > 0:
            o.deferred[e.event_id] = (e, ly_do or "transient:?")
            o.defer_until[e.event_id] = mono + con
        else:
            giu.append(e)
    o.queue = giu



def _duyet_chua_chay_lai(o: Orchestrator, duyet: list[tuple[str, int, str, int]],
                         bo_idx: dict[str, int]) -> list[tuple[int, str]]:
    """Duyệt escalation của release / ticket `dispatched` mà event bị bỏ (`unhandled`) KHÔNG được chạy lại: code
    trước #354 bỏ sót, gate đã đóng nên không còn gì mở lại được. Coi lần duyệt đó là lệnh chạy lại chưa kịp chạy
    (đúng việc `_retry_unhandled` làm từ #354), để `reopened` đưa event vào lại hàng đợi. Đo được
    2026-09-26 (CAMPUS-UNI/REL-007): duyệt 15:44, lượt QA hồi quy bị bỏ 13:42 nằm im, không gate, không watchdog.
    Chỉ tính quyết định đã xử lý, và bản ghi lỗi có TRƯỚC nó (lỗi mới sau lần chạy lại thì đã có gate mới).

    Lần duyệt đã bị dự án đi qua thì không còn là lệnh: release mà sau đó đã có RC mới (REL-003 duyệt 2026-09-24,
    sau đó REL-004/005/007 — phát lại là deploy RC cũ đè staging), ticket không còn `dispatched` (đã đóng, mở lại)."""
    ra: list[tuple[int, str]] = []
    for eid, idx, sid, n in duyet:
        rec = o.unhandled.get(sid)
        if eid not in o.processed or rec is None or bo_idx.get(sid, -1) > idx: continue
        # no-ky-thuat: RC mới của BẤT KỲ dự án nào cũng chặn, công ty nhiều dự án thì lần duyệt cũ nằm lại chờ người, quay lại khi chạy song song hai dự án
        # `abandoned`: dựng lại từ log, `DeliveryLead.abandon` không đặt `closed` — ticket bị từ chối vẫn `dispatched`
        dang_giao = o.lead.state.get(sid) == "dispatched" and sid not in o.lead.abandoned
        if (len(o.lead.releases) > n) if sid in o.lead.release_tickets else not dang_giao: continue
        ra.append((idx, sid))
    return ra


def _retry_con_can(o: Orchestrator, log: list[Envelope], idx: int, rec: dict[str, Any]) -> bool:
    """Lệnh chạy lại còn ý nghĩa không, hay việc đã có người khác làm xong trong lúc chờ?

    Lệnh chạy lại chỉ sống trong RAM nên có thể nằm chờ rất lâu (người duyệt gate xong, tiến trình chết,
    hết hạn mức model...). Trong lúc đó dự án vẫn có thể đi tiếp bằng đường khác. Chạy lại một việc đã xong
    là đốt một lượt model đắt tiền để sinh ra bản trùng. Đo được khi chạy thật (2026-09-04): lệnh chạy lại
    ghi lúc 07:00:48, `spec-writer` sau đó thành công ba lần (08:15, 08:22, 08:28), nhưng lệnh cũ vẫn nổ
    lúc 09:54:42 và tiêu 317 giây `claude-opus-5` chỉ để hệ thống báo `plan.duplicate_spec` ở bước sau.

    Cách nhận biết: tra ROUTES xem event đó lẽ ra sinh ra topic nào; nếu topic đó đã có event mới cho cùng
    khoá SAU thời điểm ra lệnh, thì việc đã xong."""
    outs = {r.topic_out for r in ROUTES
            if r.topic_in == rec.get("topic") and r.agent == rec.get("agent")}
    outs.discard(CONTEXT_ONLY)
    if not outs: return True          # không suy ra được route → giữ nguyên hành vi cũ, thà chạy lại còn hơn kẹt
    # `project.retried` mang `project_id`; `unhandled`/`event.retried` chỉ mang `subject` (O6: thiếu vế này là khoá `""`).
    key = str(rec.get("project_id") or rec.get("subject") or "")
    return not any(e.topic in outs and e.key == key for e in log[idx + 1:])
