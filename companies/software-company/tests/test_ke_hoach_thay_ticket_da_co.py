"""Đầu vào `product[plan]` mang danh sách ticket đã có của dự án — để kế hoạch mới không lập lại việc đang làm.

Hub thật 2026-10-14 (QLKH-DD-CSV): PLAN-14 (REWORK-DDCSV-56-2) lập DDCSV-65/66/64 lúc 04:46; năm phút sau PLAN-15
(REWORK-DDCSV-61-2, cùng gốc CVE image) lập DDCSV-67/68/69 làm đúng ba việc đó — và đặt mã DDCSV-62/63/64 trùng
ticket đã có (`plan.renumbered` phải cấp lại). Đầu vào lượt plan chỉ là change request + `estimate_calibration`:
model không biết dự án đang có ticket nào, nên vừa đoán mã vừa lập lại việc.

Luật: lượt plan nhận `ticket_da_co` = ticket của CÙNG dự án chưa `closed` (mã, tiêu đề, trạng thái), có ghi chú
cho model. Ticket `closed` (bỏ/đã giao xong) và ticket dự án khác không vào.
"""

from __future__ import annotations

from company.events import Task
from test_orchestrator import T1, _agent_of, _inp, _product_phase


def _plan_input(orch) -> dict:
    calls = [
        c
        for c in orch.runner.client.calls
        if _agent_of(c["system"]) == "product" and _product_phase(c["system"]) == "plan"
    ]
    assert calls, "không có lượt product[plan]"
    return _inp(calls[-1]["user"])


def test_luot_plan_nhan_danh_sach_ticket_da_co_cua_du_an():
    co_san = ["DDCSV-44", "DDCSV-45", "DDCSV-46"]
    _, orch = _orch_co_trang_thai(co_san)
    p = _plan_input(orch)
    ds = p["ticket_da_co"]["items"]
    assert {d["ticket_id"]: d["state"] for d in ds} == {"DDCSV-44": "dispatched", "DDCSV-45": "merged"}
    assert all(d["title"] for d in ds)
    assert "đừng lập lại" in p["ticket_da_co"]["ghi_chu"]


def _orch_co_trang_thai(co_san: list[str]):
    from company.bus import InMemoryBus
    from company.llm import FakeClient
    from company.orchestrator import Orchestrator
    from test_cap_lai_ma_ticket_trung import _ke_hoach
    from test_plan_tu_sua_truoc_khi_hoi_nguoi import _toi_plan

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_ke_hoach([{**T1, "ticket_id": "DDCSV-47"}])))
    for tid, st in zip(co_san, ("dispatched", "merged", "closed"), strict=True):
        orch.lead.tickets[tid] = Task.model_validate({**T1, "ticket_id": tid, "title": f"việc {tid}"})
        orch.lead.state[tid] = st
    orch.lead.tickets["X-1"] = Task.model_validate({**T1, "ticket_id": "X-1", "project_id": "KHAC"})
    orch.lead.state["X-1"] = "dispatched"
    _toi_plan(bus, orch)
    return bus, orch
