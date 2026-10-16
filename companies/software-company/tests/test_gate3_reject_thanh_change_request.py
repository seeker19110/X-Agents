"""ADR-0058: gate release (Gate 3) bị từ chối → change request `GATE3-<RC>` cho planner.

Hub thật 2026-10-13 (QLKH-DD-CSV): REL-037 và REL-038 bị từ chối cùng gap `release.dashboard-alert`. `_on_gate_decide`
không làm gì với gate release khác `approve`, nên lý do không tới agent nào và RC sau vấp y hệt. Vòng chỉ dừng khi
phiên chính tự nộp CR-DDCSV-OBS-001.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_gate3_production_tam_thoi import _production
from test_orchestrator import _drive_to_plan, handler

LY_DO = (
    "root_cause: infra không nhắc dashboard/alert cho /orders; decision: reject; "
    "hint: thêm dashboard + alert + runbook cho mọi endpoint của api-contract"
)


def _cr_gate3(bus, rid="REL-001"):
    return [e for e in bus.replay(topic="change-requests") if e.key == f"GATE3-{rid}" and e.actor == "delivery-lead"]


def _toi_gate_release(bus):
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "release"
    return orch


def test_reject_gate_release_nop_change_request_cho_planner():
    bus = InMemoryBus()
    orch = _toi_gate_release(bus)
    orch.gate.decide("REL-001", "reject", by="human:release-manager", reason=LY_DO)
    orch.run()

    crs = _cr_gate3(bus)
    assert len(crs) == 1, "từ chối gate release phải thành đúng một change request cho planner"
    p = crs[0].payload
    assert p["decision"] == "pending" and p["requested_by"] == "delivery-lead" and p["project_id"] == "P1"
    assert p["impact"]["kind"] == "release_gate_reject" and p["impact"]["release_id"] == "REL-001"
    assert "dashboard + alert + runbook" in p["description"], "lý do từ chối là danh sách việc — phải tới planner"
    assert _production(bus) == [], "từ chối vẫn là không deploy production"


def test_approve_gate_release_khong_nop_change_request():
    bus = InMemoryBus()
    orch = _toi_gate_release(bus)
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="staging xanh, đủ bằng chứng")
    orch.run()
    assert _cr_gate3(bus) == []


def test_mo_lai_bus_khong_nop_lai_change_request(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = _toi_gate_release(bus)
    orch.gate.decide("REL-001", "reject", by="human:release-manager", reason=LY_DO)
    orch.run()
    assert len(_cr_gate3(bus)) == 1
    bus.close()

    bus2 = SQLiteBus(db)
    Orchestrator(bus2, FakeClient(handler=handler)).tick()
    assert len(_cr_gate3(bus2)) == 1, "replay quyết định cũ không được nộp CR lần hai"
    bus2.close()


# ---------- bổ sung 2026-10-16: lý do dài không bị cắt khỏi CR ----------
# Hub thật (QLKH-DD-CSV REL-109): lý do bác escalation dài ~3300 ký tự, hai nhóm chặn. CR REWORK-REL-109-1 cắt mô
# tả ở 1000 ký tự và impact.reason ở 500 — nhóm chặn 2 (QA đỏ ở tests/dpia) không tới product lẫn agent duyệt CR;
# product đoán sai việc, reviewer:tu-dong giữ CR vì "mô tả bị cắt ở 'N'".


def test_ly_do_dai_toi_planner_nguyen_van_ca_mo_ta_lan_impact():
    bus = InMemoryBus()
    orch = _toi_gate_release(bus)
    duoi = "nhóm chặn 2: sửa tests/dpia/test_matrix.py cho khớp catalog gate"
    ly_do = "root_cause: " + "bằng chứng dài. " * 200 + f"; decision: reject; hint: {duoi}"
    assert len(ly_do) > 3000
    orch.gate.decide("REL-001", "reject", by="human:release-manager", reason=ly_do)
    orch.run()

    p = _cr_gate3(bus)[0].payload
    assert duoi in p["description"], "việc nằm cuối lý do vẫn phải tới planner"
    assert p["impact"]["reason"] == ly_do, "agent duyệt CR đọc impact.reason — không được cụt"
