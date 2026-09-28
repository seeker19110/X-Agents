"""Quyết định gate chỉ đến từ người: `audit-log` là topic mở, nên `gate.decide` phải được kiểm actor của envelope
chứ không chỉ tin `evidence.by` (rà soát bảo mật 2026-09-04)."""
import json

import pytest

from company.bus import InMemoryBus, PermissionDenied
from company.events import AuditLog, Envelope
from company.gate_cli import PersistentGate, trusted_decision
from company.gates import GateRequest, gate_approvers
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main


def _decide_log(bus, actor, by, sid="PLAN-1", decision="approve", enforce=True):
    ev = json.dumps({"subject_id": sid, "decision": decision, "by": by})
    env = Envelope(topic="audit-log", key=actor, actor=actor,
                   payload=AuditLog(actor=by, action="gate.decide", evidence=ev).model_dump())
    if enforce: return bus.publish(env)
    bus._log.append(env); bus._notify(bus._subs, env); return env  # đi vòng qua bus (mô phỏng log bị sửa tay)


def test_agent_khong_ghi_duoc_gate_decide_len_bus():
    bus = InMemoryBus(); gate = PersistentGate(bus)
    gate.request(GateRequest(kind="plan", subject_id="PLAN-1", created_by="delivery-lead", checklist=["tickets"]))
    with pytest.raises(PermissionDenied):
        _decide_log(bus, actor="delivery-lead", by="human:pm")
    assert "PLAN-1" in gate.pending
    assert any(e.payload.get("action") == "publish_denied" for e in bus.replay(topic="audit-log"))


def test_ban_ghi_gate_decide_gia_trong_log_khong_dong_gate():
    """Log đã có một dòng gate.decide mà actor không phải người (hoặc không trùng `by`): replay bỏ qua."""
    bus = InMemoryBus(); gate = PersistentGate(bus)
    gate.request(GateRequest(kind="plan", subject_id="PLAN-1", created_by="delivery-lead", checklist=["tickets"]))
    _decide_log(bus, actor="delivery-lead", by="human:pm", enforce=False)   # agent giả danh
    _decide_log(bus, actor="human:dev", by="human:pm", enforce=False)       # người này ký tên người khác
    assert "PLAN-1" in gate.pending
    assert "PLAN-1" in PersistentGate(bus).pending  # dựng lại từ replay cũng không tin
    gate.decide("PLAN-1", "approve", by="human:pm")
    assert PersistentGate(bus).is_approved("PLAN-1")


def test_trusted_decision_chi_tin_nguoi_hoac_orchestrator_dong_gate_nghiem_thu():
    ok = _decide_log(InMemoryBus(enforce_owners=False), actor="human:pm", by="human:pm")
    assert trusted_decision(ok)["subject_id"] == "PLAN-1"
    uat = _decide_log(InMemoryBus(enforce_owners=False), actor="orchestrator", by="chị Lan (PO)", sid="UAT-REL-1")
    assert trusted_decision(uat)["decision"] == "approve"
    plan_by_orch = _decide_log(InMemoryBus(enforce_owners=False), actor="orchestrator", by="human:pm")
    assert trusted_decision(plan_by_orch) is None  # orchestrator không được duyệt plan/release thay người
    hong = Envelope(topic="audit-log", key="human:pm", actor="human:pm",
                    payload=AuditLog(actor="human:pm", action="gate.decide", evidence="{not json").model_dump())
    assert trusted_decision(hong) is None
    assert trusted_decision(Envelope(topic="audit-log", key="x", actor="human:pm",
                                     payload=AuditLog(actor="human:pm", action="gate.request", evidence="{}").model_dump())) is None


def test_cli_publish_tu_choi_actor_khong_phai_nguoi(tmp_path, capsys):
    db = str(tmp_path / "c.sqlite"); f = tmp_path / "d.json"
    f.write_text(json.dumps({"actor": "x", "action": "gate.decide", "evidence": "{}"}), encoding="utf-8")
    assert orch_main(["--db", db, "publish", "audit-log", str(f), "--actor", "delivery-lead", "--key", "k"]) == 2
    assert "human:" in capsys.readouterr().err


def test_subagent_actor_khong_dong_duoc_gate():
    """I2 (đặc tả trợ lý kiểm duyệt §8.4): kể cả khi một trợ lý `sc-*` có cách ghi được `gate.decide` lên bus, quyết
    định đó không được tin — gate vẫn `pending`. Trợ lý chuẩn bị bằng chứng, người ký."""
    bus = InMemoryBus(); gate = PersistentGate(bus)
    gate.request(GateRequest(kind="escalation", subject_id="T1", created_by="supervisor", checklist=["hint"]))
    with pytest.raises(PermissionDenied):  # đường thẳng: bus chặn ngay
        _decide_log(bus, actor="sc-qa-debugger", by="sc-qa-debugger", sid="T1")
    for actor, by in (("sc-qa-debugger", "sc-qa-debugger"), ("sc-gate-escalation", "human:lead")):
        env = _decide_log(bus, actor=actor, by=by, sid="T1", enforce=False)  # đường vòng: log bị chèn tay
        assert trusted_decision(env) is None
    assert "T1" in gate.pending and "T1" in PersistentGate(bus).pending
    gate.decide("T1", "approve", by="human:lead", reason="mock thiếu header X-Idempotency-Key")
    assert PersistentGate(bus).is_approved("T1")


# ---------- K3.7: allowlist người duyệt của company (MẶC ĐỊNH TẮT) ----------

def test_company_gate_approvers_mac_dinh_rong_khong_doi_hanh_vi(monkeypatch):
    """Biến KHÔNG đặt = hành vi trước K3.7 y nguyên: chỉ four-eyes, ai (khác người tạo) cũng duyệt được.

    Đây là ca chống hồi quy của chính việc thêm tính năng: allowlist là thứ MỚI với company, nên nếu nó bật
    theo mặc định thì mọi gate đang chờ ở một dự án thật sẽ đột nhiên không ai ký được."""
    monkeypatch.delenv("COMPANY_GATE_APPROVERS", raising=False)
    assert gate_approvers() == frozenset()
    bus = InMemoryBus(); gate = PersistentGate(bus, approvers=gate_approvers())
    gate.request(GateRequest(kind="spec", subject_id="SPEC-1", created_by="delivery-lead", checklist=["c1"]))
    assert gate.decide("SPEC-1", "approve", by="human:khong-co-trong-danh-sach").decision == "approve"
    assert PersistentGate(bus).is_approved("SPEC-1")


def test_company_gate_approvers_bat_thi_ep_four_eyes(monkeypatch):
    """Đặt biến → chỉ người trong danh sách ký được; người ngoài bị từ chối bằng PermissionError, gate vẫn chờ."""
    monkeypatch.setenv("COMPANY_GATE_APPROVERS", "human:pm, human:cto")
    assert gate_approvers() == frozenset({"human:pm", "human:cto"})
    bus = InMemoryBus(); gate = PersistentGate(bus, approvers=gate_approvers())
    gate.request(GateRequest(kind="spec", subject_id="SPEC-2", created_by="delivery-lead", checklist=["c1"]))
    with pytest.raises(PermissionError, match="COMPANY_GATE_APPROVERS"):
        gate.decide("SPEC-2", "approve", by="human:nguoi-la")
    assert "SPEC-2" in gate.pending
    gate.decide("SPEC-2", "approve", by="human:pm")
    assert PersistentGate(bus).is_approved("SPEC-2")   # replay không kiểm lại danh sách (có thể đã đổi)


def test_company_gate_approvers_bat_khong_chan_nghiem_thu_khach(monkeypatch):
    """`sc-security` (K3.7): bật `COMPANY_GATE_APPROVERS` không được làm gate `UAT-*` (nghiệm thu) hết đóng được
    — chữ ký khách (`signed_by` trong `acceptance-results`) là chuỗi tự do, không phải id một người duyệt nội
    bộ, nên `_close_acceptance_gate` phải gọi `enforce=False`. Trước bản vá: `enforce` mặc định `True` khiến
    `PermissionError` bị `_close_acceptance_gate` nuốt thành `handler_error`, ticket đóng băng vĩnh viễn dù
    `acceptance-results` đã "đã ký"."""
    from test_orchestrator import _drive_to_plan, _pub, handler

    monkeypatch.setenv("COMPANY_GATE_APPROVERS", "human:po,human:release-manager")
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.run()
    rid = orch.lead.releases[0]
    orch.gate.decide(rid, "approve", by="human:release-manager")
    orch.run()

    _pub(bus, "acceptance-results", rid, "ops",
         {"release_id": rid, "project_id": "P1", "verdict": "accepted", "signed_by": "customer:khong-trong-danh-sach"})
    orch.run()
    assert orch.lead.state["T1"] == "closed", "chữ ký khách không nằm trong allowlist người duyệt nội bộ vẫn phải đóng được nghiệm thu"
    assert not any(a.get("action") == "handler_error" for a in (e.payload for e in bus.replay(topic="audit-log")))


def test_vai_ngoai_allowlist_khong_mo_duoc_gate(tmp_path, capsys):
    """ADR-0008: `gate.request` là việc hợp lệ của AGENT, nhưng chỉ của bốn vai thật sự mở gate. `builder` mở
    gate được nghĩa là bất kỳ agent nào cũng dựng được gate ma, hoặc dựng gate mang tên vai khác."""
    from company.roles import ROLE

    bus = InMemoryBus(); gate = PersistentGate(bus)
    with pytest.raises(PermissionError):
        gate.request(GateRequest(kind="spec", subject_id="SPEC-X", checklist=["prd"], created_by=ROLE.BUILDER))
    assert gate.pending == {}
    gate.request(GateRequest(kind="spec", subject_id="SPEC-P1", checklist=["prd"], created_by=ROLE.PRODUCT))
    assert list(PersistentGate(bus).pending) == ["SPEC-P1"]   # tiến trình khác dựng lại: chỉ gate hợp lệ


def test_cli_request_bao_loi_quyen_thay_vi_traceback(tmp_path, capsys):
    from company.gate_cli import main as gate_main

    db = str(tmp_path / "c.sqlite")
    rc = gate_main(["--db", db, "request", "spec", "SPEC-X", "--by", "builder", "--checklist", "prd"])
    assert rc == 3 and "không có quyền tạo gate" in capsys.readouterr().err


@pytest.mark.parametrize("by", ["reviewer:x", "orchestrator", "pm"])
def test_cli_quyet_gate_voi_by_khong_phai_nguoi_bao_loi_va_gate_van_cho(tmp_path, capsys, by):
    """`gate_cli <quyết định> --by` là đường của NGƯỜI (audit 2026-09-27, F-A). Trước bản vá: `reviewer:x` (không
    chữ ký) và `orchestrator` (gate không phải `UAT-*`) in "approve by …" rồi thoát 0, nhưng mọi tiến trình khác
    bỏ bản ghi (`_trusted` → None) nên gate vẫn chờ; `pm` (quên tiền tố `human:`) nổ traceback `PermissionDenied`
    từ ACL bus. Keeper CLI chặn đúng chỗ này từ đầu (`keeper/cli.py` `_gate`)."""
    from company.gate_cli import main as gate_main
    from company.sqlite_bus import SQLiteBus

    db = tmp_path / "c.sqlite"
    assert gate_main(["--db", str(db), "request", "release", "REL-1", "--by", "delivery-lead", "--checklist", "t"]) == 0
    assert gate_main(["--db", str(db), "approve", "REL-1", "--by", by, "--reason", "ok"]) == 3
    assert "không phải người" in capsys.readouterr().err
    bus = SQLiteBus(db)
    try:
        assert "REL-1" in PersistentGate(bus).pending
        assert not any(e.payload.get("action") == "gate.decide" for e in bus.replay(topic="audit-log"))
    finally:
        bus.close()


def test_cli_four_eyes_van_ap_khi_nguoi_tu_duyet_gate_minh_mo(tmp_path, capsys):
    """Sau chốt F-A, `by` tới được `gate.decide` luôn là người — four-eyes của người vẫn trả 3 kèm lý do."""
    from company.gate_cli import main as gate_main

    db = str(tmp_path / "c.sqlite")
    assert gate_main(["--db", db, "request", "release", "REL-1", "--by", "human:lead", "--checklist", "t"]) == 0
    assert gate_main(["--db", db, "approve", "REL-1", "--by", "human:lead", "--reason", "tự duyệt"]) == 3
    assert "four-eyes" in capsys.readouterr().err


def test_gate_cu_do_vai_truoc_adr_0037_tao_van_dung_lai_duoc():
    """Đo trên `company.sqlite` thật (18293 event, 2026-09-09): 33 gate `gate.request` mang actor cũ
    `release-engineer`/`account-manager`/`spec-writer`. Allowlist ADR-0008 mà bỏ nhóm này thì mỗi lần mở bus,
    console và `gate_cli list` mất trắng 33 gate lịch sử — im lặng, không lỗi nào báo."""
    from company.roles import LEGACY_GATE_ACTORS

    bus = InMemoryBus(); gate = PersistentGate(bus)
    for i, actor in enumerate(sorted(LEGACY_GATE_ACTORS)):
        gate.request(GateRequest(kind="escalation", subject_id=f"OLD-{i}", checklist=["c"], created_by=actor))
    assert len(PersistentGate(bus).pending) == len(LEGACY_GATE_ACTORS)
