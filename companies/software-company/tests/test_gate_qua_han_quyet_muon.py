"""Gate quá hạn → supervisor escalate → chủ thể bị dừng (`escalate` thuộc `PAUSING`). Người ký muộn chính gate đó
thì trước đây: production vẫn deploy, nhưng REL vẫn `paused` — event production bị hoãn `paused:REL-001`, nghiệm
thu không bao giờ mở — và ngay sau đó một gate `escalation` mở hỏi người "root_cause / reopen|close" cho đúng việc
người vừa quyết. Ghi ở nhật ký 2026-10-02 (O1) từ lượt review #378.

Quá hạn không chặn quyết định muộn: gate không bao giờ tự đi tiếp, và escalate vì quá hạn là để phá sự im lặng
của người duyệt — chữ ký muộn chính là lời giải. Nên ký muộn = `resume` chủ thể, miễn là lần dừng CUỐI của nó là
do chính gate này quá hạn; bị dừng vì lý do khác sau đó thì vẫn hỏi người như cũ.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_gate3_production_tam_thoi import _production
from test_orchestrator import _drive_to_plan, handler


def _qua_han_roi_ky_muon(bus, orch):
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "release"
    orch.tick(datetime.now(UTC) + timedelta(hours=25))
    assert "REL-001" in orch.paused, "quá hạn → supervisor escalate → chủ thể dừng"


def _ky(orch):
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="muộn nhưng đủ bằng chứng staging")
    orch.tick()


def test_ky_muon_gate_release_qua_han_thi_resume_va_khong_hoi_lai(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _qua_han_roi_ky_muon(bus, orch)
    _ky(orch)
    assert _production(bus) == ["deployed"]
    assert "REL-001" not in orch.paused, "chữ ký muộn là lời giải của escalate vì quá hạn"
    assert "REL-001" not in orch.gate.pending, "không hỏi người lần nữa cho đúng việc người vừa quyết"
    assert not any(why == "paused:REL-001" for _, why in orch.deferred.values()), "event production không bị giam"
    bus.close()

    bus2 = SQLiteBus(db)
    orch2 = Orchestrator(bus2, FakeClient(handler=handler))
    orch2.tick()
    assert "REL-001" not in orch2.paused and "REL-001" not in orch2.gate.pending, "restart dựng lại cùng trạng thái"
    bus2.close()


def test_bi_dung_vi_ly_do_khac_sau_qua_han_thi_van_hoi_nguoi():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _qua_han_roi_ky_muon(bus, orch)
    orch.supervisor._act("REL-001", "pause", "dự án chạm trần ngân sách")
    _ky(orch)
    assert "REL-001" in orch.paused, "lần dừng cuối không phải do gate quá hạn: chữ ký release không gỡ nó"
    assert orch.gate.pending["REL-001"].kind == "escalation"
