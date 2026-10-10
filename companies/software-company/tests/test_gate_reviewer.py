"""ADR gốc 0024: người duyệt gate không phải người — actor `reviewer:<id>`, tin theo chữ ký Ed25519, phạm vi hẹp.

Phạm vi (S2, chủ dự án giao phiên chính chọn 2026-09-26): chỉ `approve` gate `escalation` có checklist
`decision:reopen|close` (ticket) hoặc `decision:retry|close` (dự án), subject không phải release; mỗi subject
một lần. Mọi thứ khác (spec, release, nợ kiến trúc, reject/close) vẫn chờ người.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from company import gate_reviewer as gr
from company.bus import InMemoryBus, PermissionDenied
from company.events import AuditLog, Envelope
from company.gate_cli import PersistentGate
from company.gate_cli import main as gate_main
from company.gates import GateRequest
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.roles import ROLE
from company.runner import RunnerError
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _drive_to_plan, handler
from test_tools_and_agentic import _init_repo

ID = "reviewer:doc-lap"
LY_DO = "root_cause: builder hết lượt tool hai lần, WIP còn nguyên; decision: reopen; hint: làm tiếp từ WIP"
TICKET = ["root_cause", "decision:reopen|close", "hint"]
DU_AN = ["agent_error", "decision:retry|close"]


@pytest.fixture
def khoa(tmp_path, monkeypatch) -> Path:
    """Khoá reviewer mới + registry trong tmp; cờ bật. Trả đường dẫn khoá bí mật."""
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry.json"))
    return gr.new_key(ID, tmp_path / "registry.json", tmp_path / "keys")


@pytest.fixture
def brief(tmp_path) -> Path:
    p = tmp_path / "brief.json"
    p.write_text('{"subject_id": "T1"}', encoding="utf-8")
    return p


def _gate(subject: str = "T1", checklist: list[str] | None = None) -> PersistentGate:
    g = PersistentGate(InMemoryBus())
    g.request(
        GateRequest(
            kind="escalation",
            subject_id=subject,
            created_by=ROLE.SUPERVISOR,
            checklist=TICKET if checklist is None else checklist,
        )
    )
    return g


def _publish_signed(
    gate: PersistentGate,
    subject: str,
    key: Path,
    *,
    reason: str = LY_DO,
    decision: str = "approve",
    generation: str | None = None,
    principal: str = ID,
) -> None:
    """Ghi thẳng một `gate.decide` đã ký, BỎ QUA kiểm phạm vi của `decide()` — mô phỏng người có khoá tự ghi bus."""
    req = gate.pending[subject]
    extra = gr.sign_decision(
        subject, decision, principal, reason, generation or gr.generation_of(req), "0" * 64, gr.load_private_key(key)
    )
    data = {"subject_id": subject, "decision": decision, "by": principal, "reason": reason, **extra}
    a = AuditLog(actor=principal, action="gate.decide", evidence=json.dumps(data, ensure_ascii=False))
    gate.bus.publish(Envelope(topic="audit-log", key=principal, actor=principal, payload=a.model_dump()))


# ---------- đường chính ----------


def test_reviewer_co_chu_ky_dong_gate_escalation_ticket(khoa, brief):
    g = _gate()
    gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    assert "T1" not in g.pending and g.history[-1].decided_by == ID
    assert g.reviewer_signed_pending() == {}, "cờ bật và quyết định đã áp thì không gắn nhãn chờ"
    ev = json.loads(
        next(e for e in g.bus.replay(topic="audit-log") if e.payload["action"] == "gate.decide").payload["evidence"]
    )
    assert ev["brief_sha256"] == hashlib.sha256(brief.read_bytes()).hexdigest() and len(ev["signature"]) == 128


def test_tat_co_van_nhin_thay_chu_ky_reviewer_nhung_gate_khong_duoc_ap(khoa, monkeypatch):
    g = _gate()
    _publish_signed(g, "T1", khoa)
    monkeypatch.delenv(gr.FLAG_ENV)
    reader = PersistentGate(g.bus)
    assert "T1" in reader.pending
    assert reader.reviewer_signed_pending() == {"T1": {"decision": "approve", "by": ID}}
    orch = Orchestrator(g.bus, FakeClient(handler=handler))
    assert orch.status()["gates_reviewer_signed_unapplied"] == {"T1": {"decision": "approve", "by": ID}}
    from company.metrics import collect
    assert collect(g.bus)["gates"]["pending"] == 1
    assert collect(g.bus)["gates"]["reviewer_signed_unapplied"] == 1
    assert collect(g.bus)["gates"]["awaiting_human"] == 0
    assert collect(g.bus)["gates"]["wait_seconds_avg"] is None


def test_gate_cli_list_hien_reviewer_da_ky_khi_co_tat(tmp_path, khoa, monkeypatch, capsys):
    db = tmp_path / "company.sqlite"
    gate = PersistentGate(SQLiteBus(db))
    gate.request(GateRequest(kind="escalation", subject_id="T1", created_by=ROLE.SUPERVISOR, checklist=TICKET))
    _publish_signed(gate, "T1", khoa)
    monkeypatch.delenv(gr.FLAG_ENV)
    assert gate_main(["--db", str(db), "list"]) == 0
    assert "đã ký bởi reviewer:doc-lap; cờ tắt" in capsys.readouterr().out


def test_man_doc_nhin_thay_chu_ky_khi_ca_pham_vi_rong_da_tat(khoa, monkeypatch):
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    gate = _gate("REL-1", checklist=["release"])
    _publish_signed(gate, "REL-1", khoa)
    monkeypatch.delenv(gr.FLAG_ENV)
    monkeypatch.delenv(gr.SCOPE_ENV)
    reader = PersistentGate(gate.bus)
    assert "REL-1" in reader.pending
    assert reader.reviewer_signed_pending() == {"REL-1": {"decision": "approve", "by": ID}}


def test_reviewer_mo_lai_ticket_that_va_ben_qua_restart(tmp_path, khoa, brief, monkeypatch):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=handler), repo=_init_repo(tmp_path / "repo"), base="main")
    monkeypatch.setattr(
        orch.runner, "generate_in_workspace", lambda *a, **k: (_ for _ in ()).throw(RunnerError("hỏng"))
    )
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.lead.state["T1"] == "blocked" and orch.gate.pending["T1"].kind == "escalation"
    gr.decide(orch.gate, "T1", ID, LY_DO, khoa, brief)
    orch.run()
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert any(t["hint"] == LY_DO and t["retry"] == 0 for t in tasks), "approve = mở lại kèm hint, đếm retry từ 0"
    resume = [e for e in bus.replay(topic="supervisor-actions") if e.key == "T1"]
    assert resume and resume[-1].actor == ROLE.SUPERVISOR, (
        "resume không phát dưới tên reviewer (topic chỉ của supervisor/người)"
    )
    bus.close()
    # builder giả vẫn hỏng → ticket bị chặn LẦN HAI: gate mới về người, reviewer không được duyệt tiếp (trần 1 lần)
    lai = Orchestrator(SQLiteBus(db), FakeClient(handler=handler), repo=tmp_path / "repo", base="main")
    assert any(h.subject_id == "T1" and h.decided_by == ID for h in lai.gate.history), "quyết định bền qua restart"
    assert lai.gate.pending["T1"].kind == "escalation"
    with pytest.raises(PermissionError, match="đã duyệt"):
        gr.decide(lai.gate, "T1", ID, LY_DO, khoa, brief)


def test_reviewer_chay_lai_event_du_an(khoa, brief):
    g = _gate("P1", DU_AN)
    gr.decide(g, "P1", ID, "root_cause: plan hỏng cấu trúc; decision: retry; hint: chạy lại event nguồn", khoa, brief)
    assert "P1" not in g.pending


# ---------- chữ ký ----------


def test_chu_ky_khong_khop_noi_dung_thi_gate_van_cho(khoa):
    g = _gate()
    req = g.pending["T1"]
    extra = gr.sign_decision("T1", "approve", ID, LY_DO, gr.generation_of(req), "0" * 64, gr.load_private_key(khoa))
    data = {"subject_id": "T1", "decision": "approve", "by": ID, "reason": LY_DO + " (sửa sau khi ký)", **extra}
    a = AuditLog(actor=ID, action="gate.decide", evidence=json.dumps(data, ensure_ascii=False))
    g.bus.publish(Envelope(topic="audit-log", key=ID, actor=ID, payload=a.model_dump()))
    assert "T1" in g.pending


def test_reviewer_ky_duoi_ten_nguoi_thi_khong_tin(khoa):
    """Chữ ký hợp lệ của reviewer nhưng `by="human:client"`: áp vào thì lịch sử gate ghi NGƯỜI đã duyệt — đóng vai
    người bằng đường khác. `by` phải trùng actor của envelope."""
    g = _gate()
    req = g.pending["T1"]
    extra = gr.sign_decision(
        "T1", "approve", "human:client", LY_DO, gr.generation_of(req), "0" * 64, gr.load_private_key(khoa)
    )
    data = {"subject_id": "T1", "decision": "approve", "by": "human:client", "reason": LY_DO, **extra}
    a = AuditLog(actor=ID, action="gate.decide", evidence=json.dumps(data, ensure_ascii=False))
    g.bus.publish(Envelope(topic="audit-log", key=ID, actor=ID, payload=a.model_dump()))
    assert "T1" in g.pending


def test_khong_co_chu_ky_thi_gate_van_cho(khoa):
    g = _gate()
    data = {"subject_id": "T1", "decision": "approve", "by": ID, "reason": LY_DO}
    a = AuditLog(actor=ID, action="gate.decide", evidence=json.dumps(data, ensure_ascii=False))
    g.bus.publish(Envelope(topic="audit-log", key=ID, actor=ID, payload=a.model_dump()))
    assert "T1" in g.pending


def test_khoa_khong_co_trong_registry_thi_gate_van_cho(khoa, tmp_path):
    g = _gate()
    la = gr.new_key("reviewer:la", tmp_path / "registry-khac.json", tmp_path / "keys-khac")  # registry khác
    _publish_signed(g, "T1", la, principal="reviewer:la")
    assert "T1" in g.pending


def test_khoa_het_han_thi_gate_van_cho(tmp_path, monkeypatch, brief):
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    reg = tmp_path / "r.json"
    monkeypatch.setenv(gr.REGISTRY_ENV, str(reg))
    k = gr.new_key(ID, reg, tmp_path / "keys", now=datetime.now(UTC) - timedelta(days=120), days=90)
    g = _gate()
    _publish_signed(g, "T1", k)
    assert "T1" in g.pending


def test_chu_ky_cua_the_he_cu_khong_dung_lai_duoc_cho_gate_moi(khoa):
    g = _gate()
    _publish_signed(g, "T1", khoa, generation="2026-01-01T00:00:00+00:00")
    assert "T1" in g.pending


# ---------- phạm vi ----------


@pytest.mark.parametrize(
    ("subject", "checklist"),
    [
        ("REL-001", TICKET),  # escalation release: approve = waive finding
        ("P1", ["debt:D1×3 liên tiếp", "decision:adr|waive", "hint:x"]),  # nợ kiến trúc: approve = chấp nhận treo
    ],
)
def test_ngoai_pham_vi_thi_khong_ky_va_khong_tin(khoa, brief, subject, checklist):
    g = _gate(subject, checklist)
    with pytest.raises(PermissionError, match="ngoài phạm vi"):
        gr.decide(g, subject, ID, LY_DO, khoa, brief)
    _publish_signed(g, subject, khoa)
    assert subject in g.pending, "ghi thẳng bus cũng không qua"


def test_gate_khong_phai_escalation_thi_khong_tin(khoa, brief):
    g = PersistentGate(InMemoryBus())
    g.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by=ROLE.PRODUCT, checklist=["x"]))
    with pytest.raises(PermissionError, match="ngoài phạm vi"):
        gr.decide(g, "SPEC-P1", ID, LY_DO, khoa, brief)
    _publish_signed(g, "SPEC-P1", khoa)
    assert "SPEC-P1" in g.pending


def test_reject_khong_phai_viec_cua_reviewer(khoa):
    g = _gate()
    _publish_signed(g, "T1", khoa, decision="reject")
    assert "T1" in g.pending


def test_moi_subject_mot_lan_lan_sau_ve_nguoi(khoa, brief):
    g = _gate()
    gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    g.request(GateRequest(kind="escalation", subject_id="T1", created_by=ROLE.SUPERVISOR, checklist=TICKET))
    with pytest.raises(PermissionError, match="đã duyệt"):
        gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    _publish_signed(g, "T1", khoa)
    assert "T1" in g.pending


def test_ly_do_thieu_root_cause_decision_hint_thi_khong_ky(khoa, brief):
    g = _gate()
    with pytest.raises(ValueError, match="root_cause"):
        gr.decide(g, "T1", ID, "ok duyệt", khoa, brief)
    assert "T1" in g.pending


def test_co_tat_thi_khong_ky_va_khong_tin(khoa, brief, monkeypatch):
    g = _gate()
    monkeypatch.delenv(gr.FLAG_ENV)
    with pytest.raises(PermissionError, match=gr.FLAG_ENV):
        gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    _publish_signed(g, "T1", khoa)
    assert "T1" in g.pending


def test_actor_phai_mang_tien_to_reviewer(khoa, brief):
    with pytest.raises(ValueError, match="reviewer:"):
        gr.decide(_gate(), "T1", "human:client", LY_DO, khoa, brief)


# ---------- bus ----------


def test_bus_cho_reviewer_ghi_gate_decide_nhung_van_chan_agent():
    bus = InMemoryBus()
    ev = json.dumps({"subject_id": "T1", "decision": "approve", "by": ID})
    bus.publish(
        Envelope(
            topic="audit-log",
            key=ID,
            actor=ID,
            payload=AuditLog(actor=ID, action="gate.decide", evidence=ev).model_dump(),
        )
    )
    with pytest.raises(PermissionDenied):
        bus.publish(
            Envelope(
                topic="audit-log",
                key="builder",
                actor="builder",
                payload=AuditLog(actor="builder", action="gate.decide", evidence=ev).model_dump(),
            )
        )


# ---------- CLI ----------


def test_cli_init_key_roi_decide_tren_bus_that(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    reg, keys, db = tmp_path / "r.json", tmp_path / "keys", tmp_path / "c.sqlite"
    monkeypatch.setenv(gr.REGISTRY_ENV, str(reg))
    assert gr.main(["init-key", "--id", "doc-lap", "--registry", str(reg), "--key-dir", str(keys)]) == 0
    assert (keys / "doc-lap.pem").exists() and ID in json.loads(reg.read_text(encoding="utf-8"))
    bus = SQLiteBus(db)
    PersistentGate(bus).request(
        GateRequest(kind="escalation", subject_id="T1", created_by=ROLE.SUPERVISOR, checklist=TICKET)
    )
    bus.close()
    b = tmp_path / "b.json"
    b.write_text("{}", encoding="utf-8")
    assert (
        gr.main(
            [
                "--db",
                str(db),
                "decide",
                "T1",
                "--id",
                "doc-lap",
                "--reason",
                LY_DO,
                "--key",
                str(keys / "doc-lap.pem"),
                "--brief",
                str(b),
            ]
        )
        == 0
    )
    assert "T1" not in PersistentGate(SQLiteBus(db)).pending
    assert (
        gr.main(
            [
                "--db",
                str(db),
                "decide",
                "T1",
                "--id",
                "doc-lap",
                "--reason",
                LY_DO,
                "--key",
                str(keys / "doc-lap.pem"),
                "--brief",
                str(b),
            ]
        )
        == 1
    ), "gate không còn chờ → exit 1"
    assert "T1" in capsys.readouterr().err


def test_cli_decide_khong_tao_bus_moi_khi_sai_duong_dan(tmp_path, monkeypatch, capsys):
    """Họ lỗi B3 (audit 2026-09-27, F-B): `decide` chỉ quyết gate trên bus ĐÃ CÓ. Trước bản vá, `--db` trỏ chỗ chưa có
    file (mặc định `company.sqlite` theo cwd) thì `SQLiteBus` tạo một bus rỗng ở đó rồi mới từ chối — file lạ ấy
    làm `gate_cli list` chạy sau ở cùng thư mục in "không có gate chờ" thay vì báo sai thư mục."""
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    db, b = tmp_path / "company.sqlite", tmp_path / "b.json"
    b.write_text("{}", encoding="utf-8")
    argv = ["--db", str(db), "decide", "T1", "--id", "doc-lap", "--reason", LY_DO, "--brief", str(b)]
    assert gr.main(argv) == 2
    assert not db.exists()
    assert "chưa có file bus" in capsys.readouterr().err


# ---------- đường hỏng: không tin, không ghi ----------


def test_ten_reviewer_khong_hop_le(tmp_path):
    with pytest.raises(ValueError, match="không hợp lệ"):
        gr.new_key("reviewer:Có Dấu", tmp_path / "r.json", tmp_path / "k")


def test_registry_hong_thi_khong_tin_ai(khoa, tmp_path, monkeypatch):
    g = _gate()
    hong = tmp_path / "hong.json"
    hong.write_text("{không phải json", encoding="utf-8")
    monkeypatch.setenv(gr.REGISTRY_ENV, str(hong))
    _publish_signed(g, "T1", khoa)
    assert "T1" in g.pending and gr.load_registry(hong) == {}


def test_khoa_khong_phai_ed25519(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    p = tmp_path / "ec.pem"
    p.write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    with pytest.raises(ValueError, match="Ed25519"):
        gr.load_private_key(p)


def test_evidence_hong_thi_khong_tin(khoa):
    g = _gate()
    a = AuditLog(actor=ID, action="gate.decide", evidence="{hỏng")
    env = Envelope(topic="audit-log", key=ID, actor=ID, payload=a.model_dump())
    assert gr.trusted_reviewer(env, g.pending["T1"], g.history) is None


def test_decide_tu_kiem_truoc_khi_ghi_registry_lech_thi_khong_ghi(khoa, brief, tmp_path, monkeypatch):
    """CLI và orchestrator đọc hai registry khác nhau: ghi thì gate đóng ở CLI mà vẫn chờ ở orchestrator."""
    g = _gate()
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry-trong.json"))
    with pytest.raises(PermissionError, match="không qua registry"):
        gr.decide(g, "T1", ID, LY_DO, khoa, brief)
    assert "T1" in g.pending
    assert not [e for e in g.bus.replay(topic="audit-log") if e.payload["action"] == "gate.decide"]


def test_chay_duoc_bang_python_m(monkeypatch, capsys):
    """`python -m company.gate_reviewer` là đường người trực gõ (`docs/TRUC-VA-DUNG-KHAN.md`) — chạy qua runpy để
    dòng `__main__` thực sự thực thi, như `test_coverage_100.py::test_dunder_main_goi_main_va_thoat`."""
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["gate_reviewer", "--help"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("company.gate_reviewer", run_name="__main__")
    assert e.value.code == 0 and "init-key" in capsys.readouterr().out


@pytest.mark.parametrize("noi_dung", ["{không phải json", "[]"])
def test_new_key_khong_ghi_de_registry_hong(tmp_path, noi_dung):
    """Audit 2026-10-10: `new_key` nuốt `ValueError` khi registry không phải JSON và GHI ĐÈ file bằng registry chỉ
    có khoá mới — mọi reviewer đã đăng ký mất im lặng. Chỉ file CHƯA CÓ mới được tạo mới; file hỏng phải ném lỗi
    và giữ nguyên nội dung (`load_registry` lười là để không tin ai, không phải để xoá sổ)."""
    reg = tmp_path / "registry.json"
    reg.write_text(noi_dung, encoding="utf-8")
    with pytest.raises(ValueError, match=r"registry .* hỏng, không ghi đè"):
        gr.new_key("reviewer:b", reg, tmp_path / "keys")
    assert reg.read_text(encoding="utf-8") == noi_dung, "registry hỏng phải được giữ nguyên để người xem"
    assert not (tmp_path / "keys").exists(), "không được sinh khoá bí mật khi registry không nhận được nó"
