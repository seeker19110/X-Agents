"""Hai tiến trình cùng ký MỘT gate (console + `gate_cli`, hoặc hai người bấm gần nhau) → hai bản `gate.decide`
trên bus. Sổ gate (`PersistentGate.apply`, core) chỉ để bản ĐẦU đóng gate, bản sau bị bỏ qua vì gate không còn
chờ. Orchestrator thì trước đây xử lý MỌI `gate.decide` tin cậy: bản thứ hai tra `history`, thấy gate release đã
duyệt, gọi lại lượt production (`_recall` cho phép chạy lại) — deploy production HAI lần cho một chữ ký, và đếm
`escalation_decided` hai lần. Ghi ở nhật ký 2026-10-02 (O4) từ lượt review #378.
"""

from __future__ import annotations

from company.gate_cli import PersistentGate
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_gate3_production_tam_thoi import _production
from test_orchestrator import _drive_to_plan, handler


def _hai_tien_trinh_cung_ky(db, rid="REL-001"):
    """Hai tiến trình mở bus TRƯỚC khi bên kia ký: cả hai cùng thấy gate đang chờ, cả hai đều ghi được."""
    a, b = SQLiteBus(db), SQLiteBus(db)
    ga, gb = PersistentGate(a), PersistentGate(b)
    assert rid in ga.pending and rid in gb.pending
    ga.decide(rid, "approve", by="human:release-manager", reason="đủ bằng chứng staging, cho lên production")
    gb.decide(rid, "approve", by="human:cto", reason="đồng ý lên production, bấm từ console")
    a.close()
    b.close()


def test_hai_quyet_dinh_cho_mot_gate_release_chi_deploy_production_mot_lan(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "release"

    _hai_tien_trinh_cung_ky(db)
    orch.tick()  # chế độ watch: `poll()` nạp event của tiến trình khác
    assert _production(bus) == ["deployed"], "một gate một chữ ký có hiệu lực: bản ghi thứ hai không deploy lại"
    assert orch.escalation_decided["REL-001"] == 1, "bản thứ hai không đóng gate nào thì không phải một quyết định"
    assert [g.decided_by for g in orch.gate.history if g.subject_id == "REL-001"] == ["human:release-manager"]
    bus.close()

    bus2 = SQLiteBus(db)
    orch2 = Orchestrator(bus2, FakeClient(handler=handler))
    assert orch2.escalation_decided["REL-001"] == 1, "đếm dựng lại từ log phải khớp đếm sống"
    orch2.tick()
    assert _production(bus2) == ["deployed"]
    bus2.close()
