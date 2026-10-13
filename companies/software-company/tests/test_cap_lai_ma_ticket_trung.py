"""Kế hoạch thứ hai của cùng dự án dùng lại mã ticket đã có → orchestrator cấp mã kế tiếp, không từ chối cả kế hoạch.

Hub thật 2026-10-14 (QLKH-DD-CSV): PLAN-QLKH-DD-CSV-8 (CR-DDCSV-SEC-003) tạo DDCSV-44..50 lúc 17:44:51. Ba phút sau
`product[plan]` cho REPLAN-DDCSV-35-1 đề xuất DDCSV-46/47/48, và PLAN-QLKH-DD-CSV-9
bị `plan_rejected` ("DDCSV-46 đã tồn tại; …"). Đầu vào `product[plan]` không mang danh sách mã đã cấp nên mã nó
chọn chỉ là đoán. Impact của product đã ghi đúng điều nó giả định: "Orchestrator cấp ID thật
khi dispatch". Mã ticket là định danh của code, không phải phán đoán của model — cấp mã là việc của code.

Luật: mã trùng ticket đã có và có đuôi số → đổi sang số kế tiếp còn trống của cùng tiền tố (giữ độ rộng số), sửa
`depends_on` trong cùng kế hoạch theo, ghi audit `plan.renumbered`. Mã không có đuôi số, hay kế hoạch tự trùng mã
với chính nó, vẫn bị `_check_plan` từ chối như cũ.
"""

from __future__ import annotations

import json

from company.bus import InMemoryBus
from company.events import Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import T1, _agent_of, _inp, _product_phase, handler
from test_plan_tu_sua_truoc_khi_hoi_nguoi import _audits, _toi_plan


def _ke_hoach(items: list[dict]):
    def h(system, user):
        if (
            _agent_of(system) == "product"
            and _product_phase(system) == "plan"
            and _inp(user).get("decision") != "pending"
        ):
            return {**handler(system, user), "items": items}  # giữ `context_writes` C4 của kế hoạch mẫu
        return handler(system, user)

    return h


def _orch(items: list[dict], co_san: list[str]) -> tuple[InMemoryBus, Orchestrator]:
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_ke_hoach(items)))
    for tid in co_san:  # ticket của kế hoạch chạy trước (PLAN-8 trên hub)
        orch.lead.tickets[tid] = Task.model_validate({**T1, "ticket_id": tid})
    _toi_plan(bus, orch)
    return bus, orch


def test_ma_trung_ticket_da_co_thi_cap_ma_ke_tiep_va_sua_depends_on():
    items = [
        {**T1, "ticket_id": "DDCSV-46"},
        {**T1, "ticket_id": "DDCSV-47", "requirement_id": "REQ-2", "depends_on": ["DDCSV-46"]},
        {**T1, "ticket_id": "DDCSV-53", "requirement_id": "REQ-3", "depends_on": ["DDCSV-47", "DDCSV-45"]},
    ]
    bus, orch = _orch(items, [f"DDCSV-{n}" for n in range(44, 51)])
    assert not _audits(bus, "plan_rejected") and not _audits(bus, "plan.rework"), "trùng mã không phải lỗi của kế hoạch"
    assert "PLAN-P1-1" in orch.plans
    moi = {t["ticket_id"]: t for t in orch.plans["PLAN-P1-1"]["tickets"]}
    assert set(moi) == {"DDCSV-54", "DDCSV-55", "DDCSV-53"}, "số kế tiếp sau mọi mã đã dùng, kể cả mã trong kế hoạch"
    assert moi["DDCSV-55"]["depends_on"] == ["DDCSV-54"], "phụ thuộc trong kế hoạch đi theo mã mới"
    assert moi["DDCSV-53"]["depends_on"] == ["DDCSV-55", "DDCSV-45"], "phụ thuộc ra ngoài kế hoạch giữ nguyên"
    assert {"DDCSV-54", "DDCSV-55", "DDCSV-53"} <= set(orch.lead.tickets)
    doi = _audits(bus, "plan.renumbered")
    assert len(doi) == 1 and doi[0]["mapping"] == {"DDCSV-46": "DDCSV-54", "DDCSV-47": "DDCSV-55"}


def test_giu_do_rong_so_khi_cap_lai():
    _, orch = _orch([{**T1, "ticket_id": "T-009"}], ["T-009"])
    assert [t["ticket_id"] for t in orch.plans["PLAN-P1-1"]["tickets"]] == ["T-010"]


def test_ma_khong_co_duoi_so_van_bi_tu_choi():
    bus, orch = _orch([{**T1, "ticket_id": "ABC"}], ["ABC"])
    assert not orch.plans and not _audits(bus, "plan.renumbered")
    assert any("ABC đã tồn tại" in p for r in _audits(bus, "plan_rejected") for p in r["problems"])


def test_ke_hoach_tu_trung_ma_thi_khong_cap_lai_de_check_plan_bat():
    bus, orch = _orch([{**T1, "ticket_id": "T1"}, {**T1, "ticket_id": "T1"}], ["T1"])
    assert not orch.plans and not _audits(bus, "plan.renumbered"), "cấp lại sẽ giấu lỗi `ticket_id trùng` của product"
    assert any("ticket_id trùng" in r["problems"] for r in _audits(bus, "plan_rejected"))


def test_khong_trung_thi_khong_ghi_audit():
    bus, orch = _orch([{**T1, "ticket_id": "T7"}], ["T1"])
    assert [t["ticket_id"] for t in orch.plans["PLAN-P1-1"]["tickets"]] == ["T7"]
    assert not _audits(bus, "plan.renumbered")


def test_audit_mang_project_id():
    bus, _ = _orch([{**T1, "ticket_id": "T1"}], ["T1"])
    e = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "plan.renumbered"]
    assert len(e) == 1 and e[0].payload.get("project_id") == "P1"
    assert json.loads(e[0].payload["evidence"])["mapping"] == {"T1": "T2"}
