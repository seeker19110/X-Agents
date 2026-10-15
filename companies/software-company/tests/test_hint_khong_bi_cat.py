"""Lý do của người duyệt tới agent NGUYÊN VẸN, không cắt ở 500/1000 ký tự.

Hub thật 2026-10-15 (QLKH-DD-CSV): `reviewer:phien-chinh` reject SPEC-CR-DDCSV-DPIA-001 và SPEC-CR-DDCSV-SEC-006 với
hint 6 mục (a)–(f), mỗi lý do ~2.500 ký tự. `_plan` cắt `f"người yêu cầu sửa spec ở gate …: {reason}"[:500]` nên
product chỉ nhận được mục (1); PRD viết lại tự ghi "hint bị cắt, chỉ sửa mục (1)" (CF-S-12) và gate lại bị trả
về. Cùng họ: CR máy nộp `REWORK-*`/`REPLAN-*` mang lý do từ chối của người trong `description[:1000]` và
`impact.hint[:500]` — planner đọc nửa câu.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.delivery import HINT_MAX, DeliveryLead
from company.events import Task
from company.gate_cli import PersistentGate
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _agent_of, _drive_to_spec_gate, _product_phase, handler

DUOI = "ĐUÔI-HINT-(f)"
DAI = "root_cause: " + "x" * 2400 + "; decision: reject; hint: (a) … " + DUOI


def test_ly_do_request_changes_o_gate_spec_toi_product_nguyen_ven():
    goi: list[str] = []

    def spy(system, user):
        if _agent_of(system) == "product" and _product_phase(system) == "spec":
            goi.append(user)
        return handler(system, user)

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=spy))
    _drive_to_spec_gate(bus, orch)
    n0 = len(goi)
    orch.gate.decide("SPEC-P1", "request_changes", by="human:po", reason=DAI)
    orch.run()
    assert len(goi) == n0 + 1 and DUOI in goi[-1], "mục cuối của hint phải tới product"


def _lead_voi(hint: str):
    bus = InMemoryBus()
    lead = DeliveryLead(bus, PersistentGate(bus))
    lead.plans_ok.add("PLAN")
    lead.dispatch(
        Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="builder", title="T1", acceptance=["a"]),
        "PLAN",
    )
    lead.tickets["T1"] = lead.tickets["T1"].model_copy(update={"hint": hint})
    return bus, lead


def test_cr_rework_mang_du_ly_do_tu_choi():
    bus, lead = _lead_voi(DAI)
    cid = lead.request_change_after_noop_rework("T1")
    cr = bus.latest("change-requests", cid).payload
    assert DUOI in cr["description"] and DUOI in cr["impact"]["hint"]


def test_cr_replan_mang_du_loi_cuoi():
    bus, lead = _lead_voi("")
    lead._request_replan(lead.tickets["T1"], DAI, "hết lượt")
    cr = bus.latest("change-requests", "REPLAN-T1-1").payload
    assert DUOI in cr["description"] and DUOI in cr["impact"]["hint"]


def test_tran_van_chan_payload_phinh():
    bus, lead = _lead_voi("y" * (HINT_MAX * 3))
    cid = lead.request_change_after_noop_rework("T1")
    cr = bus.latest("change-requests", cid).payload
    assert len(cr["impact"]["hint"]) == HINT_MAX and len(cr["description"]) <= HINT_MAX + 1000
