"""ADR-0051 bổ sung 2026-10-16: ticket bị `blocked` vì phụ thuộc một ticket đã bị REPLAN thay — mở lại (escalation
`approve`) thì phụ thuộc đó trỏ sang ticket của kế hoạch thay thế, và ticket CHỜ (`waiting`) tới khi phụ thuộc xong
thay vì được giao ngay trên nền thiếu code.

Hub thật (QLKH-DD-CSV, 2026-10-15): REPLAN-DDCSV-106-1 thay DDCSV-106 bằng DDCSV-117; DDCSV-112 (phụ thuộc 110, 106)
và DDCSV-115 (106, 111) bị `blocked`. `reopen` cũ giao ngay bỏ qua mọi phụ thuộc (110, 111 còn chưa xong), `close` bỏ
việc thật của CR đã accepted — `reviewer:tu-dong` giữ cả hai gate vì không lựa chọn nào đúng.

Hai chiều (luật bắt buộc 4): bỏ phần đổi phụ thuộc trong `DeliveryLead.reopen` → 4/4 ca đỏ; bỏ nhánh chờ → ca 1, 3,
4 đỏ; bỏ nhánh `ticket.reopened` → `waiting` ở `rehydrate` → ca 4 đỏ."""

from __future__ import annotations

import json

from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Task
from company.gate_cli import PersistentGate
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _inp
from test_replan_adr0051 import _drive_to_blocked, _planner_blocks_t1


def _lead() -> DeliveryLead:
    lead = DeliveryLead(InMemoryBus(), PersistentGate(InMemoryBus()))
    lead.plans_ok.update({"PLAN-P-1", "PLAN-P-2"})
    return lead


def _task(tid: str, deps: list[str] | None = None) -> Task:
    return Task(
        ticket_id=tid,
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title=tid,
        acceptance=["a"],
        depends_on=deps or [],
    )


def _merge(lead: DeliveryLead, tid: str) -> None:
    for dst in ("in_progress", "in_review", "approved"):
        lead._set(tid, dst)
    lead.mark_integrated(tid)


def test_mo_lai_ticket_phu_thuoc_ticket_bi_thay_thi_tro_sang_ticket_thay_the_va_cho():
    lead = _lead()
    lead.dispatch(_task("A"), "PLAN-P-1")
    lead.dispatch(_task("OLD"), "PLAN-P-1")
    lead.dispatch(_task("D", ["A", "OLD"]), "PLAN-P-1")
    assert lead.close_escalated("OLD") == ["D"] and lead.state["D"] == "blocked"
    lead.dispatch(_task("NEW"), "PLAN-P-2")
    lead.note_replacement("OLD", ["NEW"])
    nt = lead.reopen("D", "mở lại sau replan")
    assert nt.depends_on == ["A", "NEW"], "phụ thuộc ticket bị thay → ticket thay thế, giữ phụ thuộc khác"
    assert lead.state["D"] == "waiting", "A, NEW chưa xong: chờ, không giao trên nền thiếu code"
    _merge(lead, "A")
    assert lead.state["D"] == "waiting"
    _merge(lead, "NEW")
    assert lead.state["D"] == "dispatched"


def test_mo_lai_ticket_phu_thuoc_ticket_bi_bo_khong_co_thay_the_thi_bo_phu_thuoc_do():
    """Hành vi cũ giữ nguyên khi không có kế hoạch thay thế: người `approve` = chạy không cần ticket đã bỏ."""
    lead = _lead()
    lead.dispatch(_task("OLD"), "PLAN-P-1")
    lead.dispatch(_task("D", ["OLD"]), "PLAN-P-1")
    lead.close_escalated("OLD")
    nt = lead.reopen("D", "chạy không cần OLD")
    assert nt.depends_on == [] and lead.state["D"] == "dispatched"


def _blocks_t1r_too(system: str, user: str) -> dict:
    """Như `_planner_blocks_t1`, thêm `qa` chặn T1R: ticket thay thế CHƯA xong lúc người mở lại T2."""
    if _agent_of(system) == "qa" and _inp(user).get("ticket_id") == "T1R" and "`pull-requests`" in user:
        return {"ticket_id": "T1R", "source": "reviewer", "verdict": "block", "findings": [{"level": "block", "text": "chưa xong"}]}
    return _planner_blocks_t1(system, user)


def _replan_then_reopen_t2(tmp_path) -> tuple[SQLiteBus, Orchestrator]:
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=_blocks_t1r_too))
    _drive_to_blocked(bus, orch)
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po"]) == 0
    orch.tick()
    assert orch.lead.state["T2"] == "blocked" and orch.lead.replaced_by == {"T1": ["T1R"]}
    assert orch.lead.state["T1R"] not in {"approved", "merged"}
    orch.gate.decide("T2", "approve", by="human:pm", reason="mở lại sau replan"); orch.run()
    return bus, orch


def test_escalation_approve_ticket_phu_thuoc_sau_replan_cho_ticket_thay_the(tmp_path):
    bus, orch = _replan_then_reopen_t2(tmp_path)
    assert orch.lead.tickets["T2"].depends_on == ["T1R"] and orch.lead.state["T2"] == "waiting"
    ev = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "ticket.reopened"]
    assert ev[-1] == {"ticket_id": "T2", "by": "human:pm", "depends_on": ["T1R"], "state": "waiting"}


def test_ticket_mo_lai_dang_cho_song_sot_qua_restart(tmp_path):
    _replan_then_reopen_t2(tmp_path)
    o2 = Orchestrator(SQLiteBus(tmp_path / "c.sqlite"), FakeClient(handler=_blocks_t1r_too))
    assert o2.lead.replaced_by == {"T1": ["T1R"]}
    assert o2.lead.tickets["T2"].depends_on == ["T1R"] and o2.lead.state["T2"] == "waiting"
