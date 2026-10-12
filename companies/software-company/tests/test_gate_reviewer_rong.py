"""ADR gốc 0025: phạm vi `rong` của reviewer — phiên chính quyết mọi gate trừ `spec`.

Chủ dự án 2026-09-26: *"tôi muốn phiên chính tự quyết định thay tôi làm hết mọi thứ, trừ duyệt spec ban đầu"*.
Vẫn đi đường chữ ký của ADR gốc 0024 (actor `reviewer:<id>`, không bao giờ `human:*`); chỉ phạm vi đổi, và chỉ khi
`COMPANY_GATE_REVIEWER_SCOPE=rong`. Không đặt thì giữ nguyên S2 (`test_gate_reviewer.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from company import gate_reviewer as gr
from company.bus import InMemoryBus
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.roles import ROLE
from company.sqlite_bus import SQLiteBus
from test_gate_reviewer import DU_AN, LY_DO, TICKET, _gate, _publish_signed

ID = "reviewer:phien-chinh"
LY_DO_REL = "root_cause: qa chặn vì bảng license thiếu gói; decision: approve; hint: chấp nhận finding, giao bản này"


@pytest.fixture
def khoa(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry.json"))
    return gr.new_key(ID, tmp_path / "registry.json", tmp_path / "keys")


@pytest.fixture
def brief(tmp_path) -> Path:
    p = tmp_path / "brief.json"
    p.write_text("{}", encoding="utf-8")
    return p


def _gate_kind(kind: str, subject: str, created_by: str = ROLE.OPS) -> PersistentGate:
    g = PersistentGate(InMemoryBus())
    g.request(GateRequest(kind=kind, subject_id=subject, created_by=created_by, checklist=["x"]))
    return g


@pytest.mark.parametrize(
    ("subject", "checklist"),
    [
        ("REL-004", TICKET),  # escalation release: approve = chấp nhận finding rồi giao
        ("P1", ["debt:D1×3 liên tiếp", "decision:adr|waive", "hint:x"]),  # nợ kiến trúc
        ("T1", TICKET),
        ("P2", DU_AN),
    ],
)
def test_rong_approve_moi_escalation(khoa, brief, subject, checklist):
    g = _gate(subject, checklist)
    gr.decide(g, subject, ID, LY_DO_REL, khoa, brief)
    assert subject not in g.pending and g.history[-1].decided_by == ID


@pytest.mark.parametrize(
    ("kind", "subject", "created_by"),
    [("release", "REL-004", "delivery-lead"), ("acceptance", "UAT-REL-004", ROLE.OPS)],
)
def test_rong_approve_release_va_acceptance(khoa, brief, kind, subject, created_by):
    g = _gate_kind(kind, subject, created_by)
    gr.decide(g, subject, ID, LY_DO_REL, khoa, brief)
    assert subject not in g.pending and g.history[-1].decision == "approve"


def test_rong_reject_duoc(khoa, brief):
    g = _gate("REL-005", TICKET)
    gr.decide(
        g,
        "REL-005",
        ID,
        "root_cause: smoke hỏng thật; decision: reject; hint: sửa endpoint /healthz",
        khoa,
        brief,
        decision="reject",
    )
    assert "REL-005" not in g.pending and g.history[-1].decision == "reject" and g.history[-1].decided_by == ID


def test_rong_khong_tran_mot_lan(khoa, brief):
    g = _gate()
    gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    g.request(GateRequest(kind="escalation", subject_id="T1", created_by=ROLE.SUPERVISOR, checklist=TICKET))
    gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    assert "T1" not in g.pending


def test_rong_van_khong_duyet_spec(khoa, brief):
    """Ngoại lệ duy nhất chủ dự án giữ lại: duyệt spec."""
    g = _gate_kind("spec", "SPEC-P1", ROLE.PRODUCT)
    with pytest.raises(PermissionError, match="spec"):
        gr.decide(g, "SPEC-P1", ID, LY_DO, khoa, brief)
    _publish_signed(g, "SPEC-P1", khoa, principal=ID)
    assert "SPEC-P1" in g.pending, "ghi thẳng bus cũng không qua"


LY_DO_SPEC = "root_cause: PRD đủ NFR có số, out-of-scope rõ; decision: approve; hint: threat model phủ PII trẻ em"


def test_toan_bo_duyet_va_tu_choi_duoc_spec(khoa, brief, monkeypatch):
    """ADR gốc 0033: chủ dự án 2026-10-12 chọn "Bật lâu dài" — phiên chính duyệt cả spec, vẫn dưới chữ ký reviewer."""
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    g = _gate_kind("spec", "SPEC-P1", ROLE.PRODUCT)
    gr.decide(g, "SPEC-P1", ID, LY_DO_SPEC, khoa, brief)
    assert "SPEC-P1" not in g.pending and g.history[-1].decided_by == ID, "không bao giờ human:*"
    g2 = _gate_kind("spec", "SPEC-P2", ROLE.PRODUCT)
    gr.decide(g2, "SPEC-P2", ID, LY_DO_SPEC, khoa, brief, decision="reject")
    assert g2.history[-1].decision == "reject"


def test_toan_bo_gom_moi_viec_cua_rong(khoa, brief, monkeypatch):
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    g = _gate_kind("release", "REL-004", "delivery-lead")
    gr.decide(g, "REL-004", ID, LY_DO_REL, khoa, brief)
    assert "REL-004" not in g.pending


def test_ve_rong_thi_spec_reviewer_da_duyet_khong_duoc_ap(tmp_path, khoa, brief, monkeypatch):
    """Hỏng thì đóng: bỏ `toan-bo` (về `rong`) rồi mở lại tiến trình thì spec reviewer đã duyệt hiện lại chờ người."""
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    db = tmp_path / "c.sqlite"
    g = PersistentGate(SQLiteBus(db))
    g.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by=ROLE.PRODUCT, checklist=["prd"]))
    gr.decide(g, "SPEC-P1", ID, LY_DO_SPEC, khoa, brief)
    g.bus.close()
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    assert "SPEC-P1" in PersistentGate(SQLiteBus(db)).pending


def test_rong_decision_la_thi_khong_tin(khoa):
    g = _gate()
    _publish_signed(g, "T1", khoa, decision="waive", principal=ID)
    assert "T1" in g.pending


def test_tat_pham_vi_rong_thi_quyet_dinh_rong_cu_khong_duoc_ap(tmp_path, khoa, brief, monkeypatch):
    """Hỏng thì đóng, như cờ `COMPANY_GATE_REVIEWER`: bỏ `rong` rồi mở lại tiến trình thì quyết định ngoài S2
    không còn được tin — gate hiện lại chờ người."""
    db = tmp_path / "c.sqlite"
    g = PersistentGate(SQLiteBus(db))
    g.request(GateRequest(kind="escalation", subject_id="REL-004", created_by=ROLE.SUPERVISOR, checklist=TICKET))
    gr.decide(g, "REL-004", ID, LY_DO_REL, khoa, brief)
    g.bus.close()
    monkeypatch.delenv(gr.SCOPE_ENV)
    assert "REL-004" in PersistentGate(SQLiteBus(db)).pending


def test_cli_decision_reject(tmp_path, monkeypatch):
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    reg, keys, db = tmp_path / "r.json", tmp_path / "keys", tmp_path / "c.sqlite"
    monkeypatch.setenv(gr.REGISTRY_ENV, str(reg))
    assert gr.main(["init-key", "--id", "phien-chinh", "--registry", str(reg), "--key-dir", str(keys)]) == 0
    bus = SQLiteBus(db)
    PersistentGate(bus).request(
        GateRequest(kind="escalation", subject_id="REL-005", created_by=ROLE.SUPERVISOR, checklist=TICKET)
    )
    bus.close()
    b = tmp_path / "b.json"
    b.write_text("{}", encoding="utf-8")
    argv = [
        "--db",
        str(db),
        "decide",
        "REL-005",
        "--id",
        "phien-chinh",
        "--decision",
        "reject",
        "--reason",
        "root_cause: x; decision: reject; hint: y",
        "--key",
        str(keys / "phien-chinh.pem"),
        "--brief",
        str(b),
    ]
    assert gr.main(argv) == 0
    lai = PersistentGate(SQLiteBus(db))
    assert "REL-005" not in lai.pending and lai.history[-1].decision == "reject"


# ---------- vòng thật: release rồi nghiệm thu, không người nào ký ----------


def _toi_nghiem_thu_do_reviewer(tmp_path, monkeypatch, khoa, brief):
    from company.gates import AUTOAPPROVE_ENV
    from test_deploy_release_fsm import RUNTIME, _fake_deploy, _orch, _repo
    from test_tu_duyet_e2e import OK_LC, _seed_pr

    monkeypatch.delenv(AUTOAPPROVE_ENV, raising=False)
    _seed_pr(tmp_path, OK_LC)
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.lead.state["T1"] = "approved"
    orch.run()
    gr.decide(orch.gate, "REL-001", ID, LY_DO_REL, khoa, brief)
    orch.run()
    gr.decide(orch.gate, "UAT-REL-001", ID, LY_DO_REL, khoa, brief)
    orch.run()
    return bus, orch


def test_khach_tu_choi_sau_khi_reviewer_nghiem_thu_thi_mo_escalation(tmp_path, monkeypatch, khoa, brief):
    """Chữ ký khách thắng máy, như ADR-0043 §3: không im lặng nuốt khi reviewer đã đóng ticket."""
    from company.events import Envelope
    from test_tu_duyet_e2e import _audits

    bus, orch = _toi_nghiem_thu_do_reviewer(tmp_path, monkeypatch, khoa, brief)
    assert orch.lead.state["T1"] == "closed"
    bus.publish(Envelope(topic="acceptance-results", key="REL-001", actor="ops",
                         payload={"release_id": "REL-001", "project_id": "P", "verdict": "rejected",
                                  "signed_by": "khach:an", "findings": [{"level": "block", "text": "sai màu"}]}))
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "escalation"
    assert [d["release_id"] for d in _audits(bus, "acceptance.overridden")] == ["REL-001"]


def test_rong_duyet_release_roi_nghiem_thu_thi_dong_ticket(tmp_path, monkeypatch, khoa, brief):
    """Không có sàn ADR-0043 (cờ tắt): reviewer duyệt gate `release` → lên production → gate `UAT-*` → reviewer
    duyệt nghiệm thu → ticket `closed`, ghi `acceptance.auto` (dựng lại được khi restart), không ghi thay chữ ký khách."""
    from company.gates import AUTOAPPROVE_ENV
    from test_deploy_release_fsm import RUNTIME, _fake_deploy, _orch, _rel, _repo
    from test_tu_duyet_e2e import OK_LC, _audits, _seed_pr

    monkeypatch.delenv(AUTOAPPROVE_ENV, raising=False)
    _seed_pr(tmp_path, OK_LC)
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.lead.state["T1"] = "approved"
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "release"
    gr.decide(orch.gate, "REL-001", ID, LY_DO_REL, khoa, brief)
    orch.run()
    assert _rel(bus, "production") and _rel(bus, "production")[-1]["status"] == "deployed"
    assert orch.gate.pending["UAT-REL-001"].kind == "acceptance"
    gr.decide(orch.gate, "UAT-REL-001", ID, LY_DO_REL, khoa, brief)
    orch.run()
    assert orch.lead.state["T1"] == "closed"
    assert [d["release_id"] for d in _audits(bus, "acceptance.auto")] == ["REL-001"]
    assert not list(bus.replay(topic="acceptance-results")), "máy không ghi vào topic chữ ký của khách"
