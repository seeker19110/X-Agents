"""ADR-0051: coordinator (`DeliveryLead`) hết retry thì KHÔNG chỉ chặn chờ người — nó nộp một change request
`REPLAN-<ticket>-<thế hệ>` để planner (`product[plan]`) lập lại kế hoạch cho phần việc đó, người quyết qua
`decide-change`. Ý mượn từ Workforce của CAMEL-AI: planner tách khỏi coordinator, coordinator leo thang
retry → replan → người. Người vẫn là người quyết: CR chờ `accepted` của `human:*`, gate escalation vẫn mở song song.

Hai chiều (luật bắt buộc 4): tắt `_request_replan` trong `_retry` → ca 1/2/3 đỏ; bỏ nhánh replan trong `_plan` →
ca 5/6/7 đỏ; bỏ `LEAD_ACTOR` khỏi ACL `change-requests` → ca 4 đỏ."""
from __future__ import annotations

import json

import pytest
from xagents_core.bus import PermissionDenied

from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Envelope, Task
from company.gate_cli import PersistentGate
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.roles import LEAD_ACTOR
from company.sqlite_bus import SQLiteBus
from test_orchestrator import T1, _agent_of, _drive_to_plan, _inp, handler

T1R = {**T1, "ticket_id": "T1R", "title": "GET /orders (lập lại)"}


def _lead(**kw) -> tuple[InMemoryBus, DeliveryLead]:
    bus = InMemoryBus(); lead = DeliveryLead(bus, PersistentGate(bus), **kw)
    lead.plans_ok.add("PLAN-P-1"); return bus, lead


def _task(tid="T1", **kw) -> Task:
    return Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="builder", title="x", acceptance=["a"], **kw)


def _block(lead: DeliveryLead, tid: str = "T1") -> None:
    """`rework` tới hết `max_retries` (3): retry 0→1→2, lần thứ ba chạm trần → blocked."""
    for _ in range(lead.max_retries):
        lead.state[tid] = "dispatched"; lead.rework(tid, "pytest đỏ: 3 failed")
    assert lead.state[tid] == "blocked"


def _crs(bus) -> list[Envelope]:
    return list(bus.replay(topic="change-requests"))


# ---------- coordinator nộp CR replan khi hết retry ----------

def test_het_retry_thi_coordinator_nop_change_request_replan():
    bus, lead = _lead()
    lead.dispatch(_task(), "PLAN-P-1"); lead.dispatch(_task("T2", depends_on=["T1"]), "PLAN-P-1")
    _block(lead)
    crs = _crs(bus)
    assert [e.key for e in crs] == ["REPLAN-T1-1"] and crs[0].actor == LEAD_ACTOR
    p = crs[0].payload
    assert p["decision"] == "pending" and p["project_id"] == "P" and p["requested_by"] == LEAD_ACTOR
    assert p["affects_requirements"] == [], "replan không đổi yêu cầu → `_cr_accepted_direct` → `product[plan]` thẳng"
    assert p["impact"]["kind"] == "replan" and p["impact"]["ticket_id"] == "T1" and p["impact"]["generation"] == 1
    assert p["impact"]["dependents"] == ["T2"] and "pytest đỏ" in p["description"]
    assert lead.replan_open == {"T1": "REPLAN-T1-1"}


def test_block_lan_hai_cung_the_he_khong_nop_cr_trung():
    bus, lead = _lead()
    lead.dispatch(_task(), "PLAN-P-1"); _block(lead)
    lead.reopen("T1", "người mở lại"); _block(lead)
    assert [e.key for e in _crs(bus)] == ["REPLAN-T1-1"], "cùng ticket, cùng thế hệ: một CR, không nộp lại"


def test_ticket_sinh_tu_replan_het_retry_thi_vuot_tran_khong_nop_nua():
    bus, lead = _lead(replan_rounds=1)
    cause = Envelope(topic="change-requests", key="REPLAN-T0-1", actor=LEAD_ACTOR,
                     payload={"change_id": "REPLAN-T0-1", "project_id": "P", "requested_by": LEAD_ACTOR,
                              "description": "x", "decision": "accepted",
                              "impact": {"kind": "replan", "ticket_id": "T0", "generation": 1}})
    lead.dispatch(_task(), "PLAN-P-1", cause=cause); _block(lead)
    assert _crs(bus) == [], "thế hệ 2 > replan_rounds=1: chỉ còn gate escalation cho người"
    assert lead.replan_open == {}


def test_cr_duoc_quyet_thi_khong_con_mo_trong_so_lead():
    bus, lead = _lead()
    lead.dispatch(_task(), "PLAN-P-1"); _block(lead)
    cr = _crs(bus)[0]
    bus.publish(cr.model_copy(update={"payload": {**cr.payload, "decision": "rejected"}, "actor": "human:po"}))
    assert lead.replan_open == {} and lead.state["T1"] == "blocked", "từ chối replan: ticket vẫn chờ gate escalation"


def test_acl_change_requests_cho_lead_actor_khong_cho_agent_khac():
    bus = InMemoryBus()
    p = {"change_id": "REPLAN-X-1", "project_id": "P", "requested_by": LEAD_ACTOR, "description": "x",
         "impact": {"kind": "replan", "ticket_id": "X", "generation": 1}}
    bus.publish(Envelope(topic="change-requests", key="REPLAN-X-1", actor=LEAD_ACTOR, payload=p))
    with pytest.raises(PermissionDenied):
        bus.publish(Envelope(topic="change-requests", key="REPLAN-X-2", actor="builder", payload=p))


# ---------- orchestrator: người chấp nhận replan → đóng ticket cũ, đóng gate escalation, kế hoạch mới ----------

BLOCK_T1 = {"on": True}  # ca "người mở lại trước" tắt nó sau khi reopen để T1 chạy qua


def _planner_blocks_t1(system: str, user: str) -> dict:
    """`qa` chặn T1 (khi `BLOCK_T1["on"]`); `product[plan]` nhận CR replan thì trả kế hoạch MỚI (T1R) thay vì [T1, T2]."""
    a, p = _agent_of(system), _inp(user)
    if BLOCK_T1["on"] and a == "qa" and p.get("ticket_id") == "T1" and "`pull-requests`" in user:
        return {"ticket_id": "T1", "source": "reviewer", "verdict": "block", "findings": [{"level": "block", "text": "sai contract"}]}
    if a == "product" and p.get("impact", {}).get("kind") == "replan" and p.get("decision") == "accepted":
        return {"items": [T1R]}
    return handler(system, user)


def _drive_to_blocked(bus, orch) -> None:
    BLOCK_T1["on"] = True
    _drive_to_plan(bus, orch); orch.run()
    assert orch.gate.pending["T1"].kind == "escalation"
    orch.gate.decide("T1", "approve", by="human:pm", reason="cứ làm tiếp"); orch.run()
    assert orch.lead.state["T1"] == "blocked"


def test_replan_chap_nhan_thi_dong_ticket_cu_gate_escalation_va_lap_ke_hoach_moi(tmp_path):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    crs = _crs(bus)
    assert [e.key for e in crs] == ["REPLAN-T1-1"] and crs[-1].payload["decision"] == "pending"
    impact = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "change.impact"]
    assert impact and impact[0].actor == "product", "CR replan đi đúng đường CR thường: planner ước lượng impact"
    assert "replan:REPLAN-T1-1" in orch.gate.pending["T1"].checklist, "gate escalation nhắc người: có đề nghị replan"
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po",
                      "--reason", "ticket cắt sai, lập lại"]) == 0
    orch.tick()  # `tick()` mới `poll()` event của tiến trình khác khi hàng đợi rỗng
    assert orch.lead.state["T1"] == "closed" and "T1" not in orch.gate.pending
    assert "T1" in orch.lead.abandoned and orch.lead.state["T2"] == "blocked", "T2 phụ thuộc T1 cũ: không âm thầm chạy trên nền thiếu"
    rp = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "ticket.replanned"]
    assert rp == [{"ticket_id": "T1", "change_id": "REPLAN-T1-1", "by": "human:po", "dependents_blocked": ["T2"]}]
    assert "PLAN-P1-2" in orch.plans and not orch.plans["PLAN-P1-2"]["problems"]
    assert orch.lead.state["T1R"] in {"dispatched", "in_progress", "in_review", "approved", "merged"}
    assert orch.lead.replan_open == {}
    orch.run(); orch.tick()
    assert orch.lead.state["T1"] == "closed" and [e.key for e in _crs(bus)].count("REPLAN-T1-1") == 2, "không nộp lại, không mở lại"


def test_replan_bi_tu_choi_thi_ticket_cu_van_cho_gate_escalation(tmp_path):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "rejected", "--by", "human:po"]) == 0
    orch.tick()
    assert orch.lead.state["T1"] == "blocked" and orch.gate.pending["T1"].kind == "escalation"
    assert "PLAN-P1-2" not in orch.plans and orch.lead.replan_open == {}
    orch.gate.decide("T1", "reject", by="human:pm", reason="bỏ ticket"); orch.run()
    assert orch.lead.state["T1"] == "closed"


def test_replan_song_sot_qua_restart(tmp_path):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po"]) == 0
    orch.tick()
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=_planner_blocks_t1))
    assert o2.lead.state["T1"] == "closed" and "T1" in o2.lead.abandoned and "T1" not in o2.gate.pending
    assert o2.lead.state["T2"] == "blocked" and "T1R" in o2.lead.tickets and o2.lead.replan_open == {}
    o2.run(); o2.tick()
    assert [e.key for e in _crs(bus)].count("REPLAN-T1-1") == 2, "mở lại bus không nộp CR lần nữa"


def test_replan_cua_ticket_da_duoc_nguoi_mo_lai_truoc_do_khong_dong_ticket_dang_chay(tmp_path):
    """Người duyệt escalation `approve` (mở lại T1) TRƯỚC rồi mới `accepted` CR replan: T1 đang chạy lại, không
    phải blocked — orchestrator không đóng nó, chỉ ghi nhận và vẫn lập kế hoạch mới (người đã quyết hai lần, lần
    sau thắng về kế hoạch, nhưng không có ticket nào bị đóng sau lưng)."""
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    BLOCK_T1["on"] = False  # lần chạy lại qua review
    orch.gate.decide("T1", "approve", by="human:pm", reason="thử lại lần nữa"); orch.run()
    assert orch.lead.state["T1"] not in {"blocked", "closed"} and "T1" not in orch.gate.pending
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po"]) == 0
    orch.tick()
    assert not any(e.payload["action"] == "ticket.replanned" for e in bus.replay(topic="audit-log"))
    assert "PLAN-P1-2" in orch.plans and "T1" not in orch.lead.abandoned and "T1R" in orch.lead.tickets  # T1 xong việc thật, không bị bỏ


def test_decide_change_replan_accepted_dong_gate_escalation_duoi_chu_ky_nguoi(tmp_path, capsys):
    """Máy không ghi `gate.decide` (bus chặn, `_trusted` không tin khi replay) → CLI `decide-change` ký luôn gate
    escalation của ticket cũ dưới tên NGƯỜI vừa chấp nhận replan; từ chối/hoãn CR thì gate giữ nguyên."""
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "deferred", "--by", "human:po"]) == 0
    assert "T1" in orch.gate.pending and not [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.decide"
                                             and '"subject_id": "T1"' in e.payload["evidence"] and e.actor == "human:po"], "deferred: không đụng gate"
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po", "--reason", "cắt lại"]) == 0
    out = capsys.readouterr().out
    assert "gate escalation T1: reject by human:po" in out
    decides = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log")
               if e.payload["action"] == "gate.decide" and e.actor == "human:po"]
    assert decides and decides[-1]["subject_id"] == "T1" and decides[-1]["decision"] == "reject" and "REPLAN-T1-1" in decides[-1]["reason"]
    orch.tick()
    assert "T1" not in orch.gate.pending and orch.lead.state["T1"] == "closed"
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po"]) == 0, "gate đã đóng: không ký lần hai, không lỗi"
