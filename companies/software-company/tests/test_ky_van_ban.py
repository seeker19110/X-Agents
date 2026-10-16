"""ADR-0063: gate ký văn bản khách — reviewer ký số một văn bản của khách bằng gate có chữ ký, rồi xuất đúng byte đã ký.

Hub thật (QLKH-DD-CSV, 2026-10-16): gate DPIA của khách đòi bản ghi `gate.decide` ký Ed25519 với subject `DPIA-SD-14`,
`by = reviewer:phien-chinh`. Hub không có đường hợp lệ: reviewer không mở được gate (`REQUEST_ACTORS`), four-eyes cấm tự
mở tự ký, `reviewer:tu-dong` sẽ ký trước với sai principal, orchestrator coi duyệt là mở lại ticket, không có lệnh xuất.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from company import gate_reviewer as gr
from company import ky_van_ban as kv
from company.bus import InMemoryBus
from company.events import AuditLog, Envelope
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.roles import LEAD_ACTOR
from company.sqlite_bus import SQLiteBus
from test_orchestrator import handler

ID = "reviewer:phien-chinh"
KHAC = "reviewer:tu-dong"
SUBJECT = "DPIA-SD-14"
REASON = (
    "root_cause: chủ dự án uỷ quyền; decision: approve; hint: SD-14.md sha256=" + "a" * 64 + " @ commit " + "b" * 40
)


@pytest.fixture
def khoa(tmp_path, monkeypatch) -> dict[str, Path]:
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    reg = tmp_path / "registry.json"
    monkeypatch.setenv(gr.REGISTRY_ENV, str(reg))
    return {p: gr.new_key(p, reg, tmp_path / "keys") for p in (ID, KHAC)}


@pytest.fixture
def brief(tmp_path) -> Path:
    p = tmp_path / "SD-14.gate_brief.json"
    p.write_bytes(b'{"sd14_path": "docs/dpia/SD-14.md", "sd14_sha256": "' + b"a" * 64 + b'"}')
    return p


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------- xin gate ký ----------


def test_xin_gate_ky_do_coordinator_mo_mang_dau_nguoi_ky_va_ho_so(khoa, brief):
    g = PersistentGate(InMemoryBus())
    req = kv.request(g, SUBJECT, ID, brief)
    assert req.kind == "escalation" and req.created_by == LEAD_ACTOR, "four-eyes: người mở khác người ký"
    assert kv.signer_of(req) == ID and kv.brief_of(req) == _sha(brief)
    xin = [e for e in g.bus.replay(topic="audit-log") if e.payload["action"] == kv.REQUESTED]
    assert len(xin) == 1 and xin[0].actor == ID, "audit nói đúng ai xin"


@pytest.mark.parametrize("subject", ["dpia-sd-14", "REL-111", "SPEC-CR-X", "UAT-REL-1", "DPIA"])
def test_subject_khong_hop_le_thi_khong_mo(khoa, brief, subject):
    with pytest.raises(ValueError):
        kv.request(PersistentGate(InMemoryBus()), subject, ID, brief)


def test_khong_phai_reviewer_hoac_ngoai_pham_vi_thi_khong_mo(khoa, brief, monkeypatch):
    g = PersistentGate(InMemoryBus())
    with pytest.raises(PermissionError):
        kv.request(g, SUBJECT, "human:chu", brief)
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    with pytest.raises(PermissionError):
        kv.request(g, SUBJECT, ID, brief)
    assert not g.pending


def test_gate_dang_cho_thi_khong_mo_trung(khoa, brief):
    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    with pytest.raises(ValueError, match="đang chờ"):
        kv.request(g, SUBJECT, ID, brief)


# ---------- ký: đúng người, đúng hồ sơ ----------


def test_chi_dung_nguoi_ky_dung_ho_so(khoa, brief, tmp_path):
    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    with pytest.raises(PermissionError, match="chỉ dành cho"):
        gr.decide(g, SUBJECT, KHAC, REASON, khoa[KHAC], brief)
    khac = tmp_path / "khac.json"
    khac.write_text("{}", encoding="utf-8")
    with pytest.raises(PermissionError, match="khác hồ sơ"):
        gr.decide(g, SUBJECT, ID, REASON, khoa[ID], khac)
    gr.decide(g, SUBJECT, ID, REASON, khoa[ID], brief)
    assert SUBJECT not in g.pending and g.history[-1].decided_by == ID


def test_ban_ghi_tu_viet_sai_nguoi_ky_khong_duoc_tin(khoa, brief):
    from test_gate_reviewer import _publish_signed

    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    _publish_signed(g, SUBJECT, khoa[KHAC], reason=REASON, principal=KHAC)
    assert SUBJECT in g.pending, "chiều tin kiểm lại dấu ky:/brief:"
    assert (
        gr.trusted_reviewer(
            next(e for e in g.bus.replay(topic="audit-log") if e.payload["action"] == "gate.decide"),
            g.pending[SUBJECT],
            g.history,
        )
        is None
    )


def test_tu_dong_bo_qua_moi_gate_ky(khoa, brief, tmp_path):
    db = tmp_path / "c.sqlite"
    g = PersistentGate(SQLiteBus(db))
    kv.request(g, SUBJECT, ID, brief)
    g.bus.close()
    goi: list[str] = []
    done = gr.run_tick(
        db, KHAC, khoa[KHAC], FakeClient(handler=handler), brief_fn=lambda orch, sid: goi.append(sid) or ("", brief)
    )
    assert done == [] and goi == [], "gate ký của phiên chính không phải việc của tu-dong"


# ---------- orchestrator: không mở lại gì ----------


def test_duyet_gate_ky_chi_ghi_audit_khong_mo_lai_ticket(khoa, brief):
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    kv.request(orch.gate, SUBJECT, ID, brief)
    gr.decide(orch.gate, SUBJECT, ID, REASON, khoa[ID], brief)
    orch.run()
    acts = [
        a
        for e in bus.replay(topic="audit-log")
        if e.payload["action"] == "orchestrated"
        for a in json.loads(e.payload["evidence"])["actions"]
    ]
    assert f"sign:{SUBJECT}:approve" in acts and not any(a.startswith("reopen:") for a in acts)
    ky = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == kv.DECIDED]
    assert ky and ky[0]["subject_id"] == SUBJECT and ky[0]["by"] == ID


# ---------- xuất đúng byte đã ký ----------


def test_xuat_phong_bi_va_khoa_kiem_lai_duoc_nhu_repo_khach(khoa, brief, tmp_path):
    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    gr.decide(g, SUBJECT, ID, REASON, khoa[ID], brief)
    sig, keys = kv.export(g.bus, g, SUBJECT, tmp_path / "out" / "SD-14.signature.json", tmp_path / "out" / "keys")
    env = json.loads(sig.read_text(encoding="utf-8"))
    assert set(env) == {"record", "signatures"} and len(env["signatures"]) == 1
    record = base64.b64decode(env["record"], validate=True)
    kid = env["signatures"][0]["key_id"]
    pub = base64.b64decode((keys / f"{kid}.pub").read_text(encoding="ascii").strip(), validate=True)
    assert len(pub) == 32 and hashlib.sha256(pub).hexdigest() == kid
    Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(env["signatures"][0]["signature"]), record)
    fields = json.loads(record)
    assert set(fields) == set(gr._SIGNED) and fields["subject_id"] == SUBJECT and fields["by"] == ID
    assert fields["decision"] == "approve" and fields["brief_sha256"] == _sha(brief) and fields["reason"] == REASON


def test_khong_co_ban_ghi_dang_tin_thi_khong_xuat(khoa, brief, tmp_path):
    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    with pytest.raises(LookupError):
        kv.export(g.bus, g, SUBJECT, tmp_path / "s.json", tmp_path / "keys")
    assert not (tmp_path / "s.json").exists()


def test_cli_xin_roi_xuat(khoa, brief, tmp_path, capsys):
    db = tmp_path / "c.sqlite"
    assert kv.main(["--db", str(db), "request", SUBJECT, "--by", ID, "--brief", str(brief)]) == 0
    assert (
        kv.main(
            ["--db", str(db), "export", SUBJECT, "--signature", str(tmp_path / "s.json"), "--keys", str(tmp_path / "k")]
        )
        == 1
    ), "chưa ký thì thoát 1"
    g = PersistentGate(SQLiteBus(db))
    gr.decide(g, SUBJECT, ID, REASON, khoa[ID], brief)
    g.bus.close()
    assert (
        kv.main(
            ["--db", str(db), "export", SUBJECT, "--signature", str(tmp_path / "s.json"), "--keys", str(tmp_path / "k")]
        )
        == 0
    )
    assert (tmp_path / "s.json").exists() and capsys.readouterr().out.count(SUBJECT) >= 2
    assert kv.main(["--db", str(db), "request", "rel-x", "--by", ID, "--brief", str(brief)]) == 2


def test_ve_pham_vi_rong_thi_gate_ky_khong_ky_duoc(khoa, brief, monkeypatch):
    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    with pytest.raises(PermissionError, match="toan-bo"):
        gr.decide(g, SUBJECT, ID, REASON, khoa[ID], brief)


def test_trung_subject_gate_khac_thi_khong_mo(khoa, brief):
    g = PersistentGate(InMemoryBus())
    g.request(
        GateRequest(
            kind="escalation",
            subject_id="DDCSV-140",
            created_by=LEAD_ACTOR,
            checklist=["root_cause", "decision:reopen|close", "hint"],
        )
    )
    g.decide("DDCSV-140", "approve", "human:chu", "root_cause: x; decision: reopen; hint: y")
    with pytest.raises(ValueError, match="trùng"):
        kv.request(g, "DDCSV-140", ID, brief)


def test_audit_hong_khong_lam_vo_viec_xuat(khoa, brief, tmp_path):
    g = PersistentGate(InMemoryBus())
    kv.request(g, SUBJECT, ID, brief)
    gr.decide(g, SUBJECT, ID, REASON, khoa[ID], brief)
    for ev in ("không phải json", "[1]"):
        g.bus.publish(
            Envelope(
                topic="audit-log",
                key=ID,
                actor=ID,
                payload=AuditLog(actor=ID, action="gate.decide", evidence=ev).model_dump(),
            )
        )
    sig, _ = kv.export(g.bus, g, SUBJECT, tmp_path / "s.json", tmp_path / "keys")
    assert sig.exists()


def test_dunder_main(monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["ky_van_ban", "--help"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("company.ky_van_ban", run_name="__main__")
    assert e.value.code == 0
