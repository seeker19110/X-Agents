"""Lý do "máy giữ" của `reviewer:tu-dong` đến tay phiên chính đủ, không cắt ở 600 ký tự.

Đo hub thật 2026-10-14/15 (QLKH-DD-CSV): ADR gốc 0034 coi lý do giữ là điểm bắt đầu của phiên chính, nhưng `_hold` cắt
còn 600 ký tự — REL-078 ("…CVE-2026-7"), REL-082 ("Hint của lượt đó ghi rõ"), REL-084 ("(2) … QA staging vẫn `block`,
với open_critical=1, HIGH db 16 và HIGH app 8") đều dừng giữa câu, đúng ở điểm nói vì sao giữ. Phiên chính phải đoán
hoặc tự dựng lại hồ sơ.
"""

from __future__ import annotations

from company import cr_reviewer, gate_reviewer
from company.bus import InMemoryBus
from company.gate_cli import PersistentGate
from company.gates import GateRequest

DAI = "máy giữ: " + "lý do dài có điểm mấu chốt ở cuối; " * 80 + "ĐIỂM MẤU CHỐT"


def test_ly_do_giu_gate_dai_hon_600_ky_tu_khong_bi_cat():
    g = PersistentGate(InMemoryBus())
    g.request(GateRequest(kind="release", subject_id="REL-1", created_by="delivery-lead", checklist=["tests"]))
    gate_reviewer._hold(g, g.pending["REL-1"], "reviewer:tu-dong", DAI, {})
    assert gate_reviewer.held(g)["REL-1"]["reason"] == DAI


def test_ly_do_giu_change_request_dai_hon_600_ky_tu_khong_bi_cat():
    bus = InMemoryBus()
    cr_reviewer._hold(bus, "GATE3-REL-1", "reviewer:tu-dong", DAI, {})
    assert cr_reviewer.held(bus)["GATE3-REL-1"]["reason"] == DAI


def test_ly_do_giu_van_co_tran_de_audit_khong_phinh():
    g = PersistentGate(InMemoryBus())
    g.request(GateRequest(kind="release", subject_id="REL-2", created_by="delivery-lead", checklist=["tests"]))
    gate_reviewer._hold(g, g.pending["REL-2"], "reviewer:tu-dong", "x" * 50_000, {})
    assert len(gate_reviewer.held(g)["REL-2"]["reason"]) == gate_reviewer.HOLD_REASON_MAX < 50_000
