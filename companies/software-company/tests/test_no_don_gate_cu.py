"""Nợ kiến trúc chạm nhiều bội số ngưỡng trong lúc gate dự án bận → chỉ mở MỘT gate cho mốc mới nhất (ADR-0032).

Hub thật 2026-10-14 (QLKH-DD-CSV): gate nợ SD-14 (thế hệ 2) chờ từ 02:16 tới 18:12. Trong lúc đó chuỗi `qa` nhắc SD-14
qua ×3, ×6, ×9, ×12 — mỗi mốc một mục `debt_due` đợi vì subject đang bận. Ký xong 18:12 thì ×3 mở ngay 18:13; ký 21:39:07
thì ×9 mở 21:39:11, ký nữa thì ×12 mở 21:39:22: mỗi mốc cũ là một gate, một lượt `reviewer:tu-dong` (~15k token) và
một chữ ký, dù cùng nợ, cùng hồ sơ. Mốc cũ đã bị mốc mới bao trọn — chỉ mốc mới nhất của mỗi (dự án, mã nợ) cần hỏi.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.gates import GateRequest
from test_no_kien_truc_adr0032 import _debt_audits, _dua_toi_ke_hoach, _review


def test_moc_don_trong_luc_ban_chi_mo_mot_gate_cho_moc_moi_nhat():
    bus = InMemoryBus()
    o = _dua_toi_ke_hoach(bus)
    o.gate.request(GateRequest(kind="escalation", subject_id="P1", created_by="supervisor", checklist=["agent_error"]))
    for i in range(9):
        _review(bus, "T1", f"SD-14 DPIA chưa ký ({i})")
    o.run()
    assert [d["times"] for d in o.supervisor.debt_due] == [1, 2, 3], "tiền đề: ba mốc dồn"
    o.gate.decide("P1", "reject", by="human:pm", reason="đóng việc kia")
    o.run()
    assert o.gate.pending["P1"].checklist[0].startswith("debt:SD-14×9"), "mở thẳng mốc mới nhất"
    o.gate.decide("P1", "reject", by="human:cto", reason="chấp nhận treo, DPIA khách ký sau")
    o.run()
    assert "P1" not in o.gate.pending, "mốc ×3/×6 đã bị ×9 bao trọn: không mở lại"
    assert _debt_audits(bus) == ["debt.escalated", "debt.decided"]


def test_moc_moi_sau_khi_quyet_van_mo_gate_moi():
    bus = InMemoryBus()
    o = _dua_toi_ke_hoach(bus)
    for i in range(3):
        _review(bus, "T1", f"SD-14 ({i})")
    o.run()
    o.gate.decide("P1", "reject", by="human:cto", reason="chấp nhận treo")
    o.run()
    for i in range(3):
        _review(bus, "T1", f"SD-14 ({i + 3})")
    o.run()
    assert o.gate.pending["P1"].checklist[0].startswith("debt:SD-14×6"), "nợ tăng tiếp sau quyết định: hỏi lại như cũ"
