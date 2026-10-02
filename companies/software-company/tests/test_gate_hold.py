"""`hold` = "chưa quyết". Console có nút "Giữ" cho MỌI gate, `gate_cli` nhận `hold` cho mọi subject, `checklists.md`
liệt `hold` là một kết quả của gate release — nhưng core đóng gate với bất kỳ quyết định nào, và orchestrator đọc
mọi quyết định khác `approve` như một lời từ chối:

* gate spec / release: gate đóng và không gì mở lại — event `approved-specs` bị đánh dấu xong (`gate:SPEC-P1:hold`),
  release không bao giờ lên production, `gate_cli list` báo "(không có gate chờ)".
* escalation của một release: rơi vào nhánh `else` → `rework_release_tickets` — ticket đã merged bị đá về làm lại.
* escalation của dự án kẹt (`stalled`): `project.closed` — "giữ" thành "huỷ dự án".

Ghi ở nhật ký 2026-10-02 từ lượt review #378. Nay `hold` mở lại đúng gate đó (cùng kind, checklist, người tạo —
four-eyes giữ nguyên) và không thi hành gì; quyết định thật đến sau đi đường cũ.
"""

from __future__ import annotations

import json

from company.bus import InMemoryBus
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_gate3_production_tam_thoi import _production
from test_orchestrator import _drive_to_plan, _drive_to_spec_gate, _pub, handler
from test_release_escalation_orchestrator import _blocked_release


def _audit(bus, action):
    return [e for e in bus.replay(topic="audit-log") if e.payload.get("action") == action]


def _requests(bus, sid):
    return [e for e in _audit(bus, "gate.request") if json.loads(e.payload["evidence"])["subject_id"] == sid]


def test_hold_gate_spec_thi_gate_van_cho_va_duyet_sau_van_lap_ke_hoach():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_spec_gate(bus, orch)
    truoc = orch.gate.pending["SPEC-P1"]
    orch.gate.decide("SPEC-P1", "hold", by="human:po", reason="chờ khách xác nhận phạm vi thanh toán")
    orch.run()

    g = orch.gate.pending.get("SPEC-P1")
    assert g is not None, "giữ = chưa quyết: gate vẫn chờ người, không biến mất khỏi `gate_cli list`"
    assert (g.kind, g.checklist, g.created_by) == (truoc.kind, truoc.checklist, truoc.created_by)
    assert next(iter(orch.deferred.values()))[1] == "gate:SPEC-P1", "event approved-specs không bị nuốt"

    orch.gate.decide("SPEC-P1", "approve", by="human:po", reason="khách đã xác nhận phạm vi")
    orch.run()
    assert "PLAN-P1-1" in orch.plans and orch.lead.tickets, "quyết định thật sau `hold` đi đường cũ"


def test_hold_roi_nguoi_tu_mo_lai_bang_gate_cli_thi_khong_mo_trung(tmp_path):
    """Đường vòng cũ cho gate bị "giữ": `gate_cli request` mở lại bằng tay. Tiến trình kia ghi cả hai trước khi
    orchestrator kịp xử lý `hold` → gate đã chờ, không mở thêm thế hệ thứ ba đè lên gate người vừa mở."""
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_spec_gate(bus, orch)
    khac = SQLiteBus(db)
    gate = PersistentGate(khac)
    gate.decide("SPEC-P1", "hold", by="human:po", reason="chờ khách xác nhận phạm vi thanh toán")
    gate.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by="human:po", checklist=["prd"]))
    khac.close()
    orch.tick()
    assert len(_requests(bus, "SPEC-P1")) == 2 and orch.gate.pending["SPEC-P1"].created_by == "human:po"
    bus.close()


def test_hold_gate_release_thi_khong_deploy_gate_mo_lai_ben_qua_restart(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "release"
    orch.gate.decide("REL-001", "hold", by="human:release-manager", reason="chờ cửa sổ deploy cuối tuần")
    orch.run()
    assert _production(bus) == []
    assert orch.gate.pending["REL-001"].kind == "release"
    bus.close()

    bus2 = SQLiteBus(db)
    orch2 = Orchestrator(bus2, FakeClient(handler=handler))
    orch2.tick()
    assert orch2.gate.pending["REL-001"].kind == "release", "mở lại là bản ghi `gate.request` bền, không chỉ trong RAM"
    assert len(_requests(bus2, "REL-001")) == 2, "restart không mở lại lần nữa"
    orch2.gate.decide("REL-001", "approve", by="human:release-manager", reason="tới cửa sổ deploy, staging vẫn xanh")
    orch2.tick()
    assert _production(bus2) == ["deployed"]
    bus2.close()


def test_hold_escalation_cua_release_khong_da_ticket_ve_lam_lai(tmp_path):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, tid = _blocked_release(orch)
    orch.gate.decide(rid, "hold", by="human:owner", reason="chờ pháp chế trả lời về DPIA rồi mới quyết")
    res = orch.run()

    assert orch.lead.state[tid] == "merged" and orch.lead.tickets[tid].retry == 0, "giữ không phải từ chối"
    assert not any(a.startswith("release_reworked") for r in res for a in r.actions), [r.actions for r in res]
    assert orch.gate.pending[rid].kind == "escalation"
    bus.close()


def test_hold_escalation_du_an_ket_khong_dong_du_an():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient())  # mọi agent lỗi → dự án kẹt ở chuỗi nghiên cứu
    _pub(bus, "research-requests", "P1", "human", {"project_id": "P1", "description": "x"})
    orch.run()
    assert "P1" in orch.stalled
    orch.gate.decide("P1", "hold", by="human:lead", reason="chờ nhà cung cấp model khôi phục rồi thử lại")
    orch.run()

    assert "P1" in orch.stalled and not _audit(bus, "project.closed"), "giữ không phải huỷ dự án"
    assert orch.gate.pending["P1"].kind == "escalation"
