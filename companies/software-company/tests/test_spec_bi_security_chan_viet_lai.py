"""ADR-0059: security chặn spec ở bước threat model → product viết lại spec với finding làm `hint`, bản viết lại
trình lại gate spec; quá `SPEC_SECURITY_REWORKS` lần mới escalation.

Hub thật 2026-10-15 (QLKH-DD-CSV): SPEC-CR-DDCSV-SEC-006 và SPEC-CR-DDCSV-DPIA-001 qua gate rồi bị security block
(threat-model v138/v139). Đường duy nhất là escalation `reopen|close`: duyệt = security chấm lại ĐÚNG spec cũ (block
y hệt), đóng = bỏ CR. Phiên chính phải đóng hai chuỗi và nộp CR mới chép tay finding.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient, TransientError
from company.orchestrator import Orchestrator
from test_orchestrator import _agent_of, _drive_to_spec_gate, _inp, handler

BLOCK = {
    "ticket_id": "SPEC-P1",
    "source": "security",
    "verdict": "block",
    "findings": [
        {"level": "block", "location": "PRD §6.3", "text": "chữ ký không phủ nội dung SD-14"},
        {"level": "warn", "location": "keys/", "text": "gốc tin cậy nằm trong repo"},
    ],
}


def _orch(chan: dict):
    seen: list[dict] = []

    def h(system, user):
        inp = _inp(user)
        if _agent_of(system) == "product" and inp.get("hint"):
            seen.append(inp)
        if _agent_of(system) == "security" and "artifacts" in inp and chan["block"] > 0:
            chan["block"] -= 1
            return BLOCK
        return handler(system, user)

    bus = InMemoryBus()
    return bus, Orchestrator(bus, FakeClient(handler=h)), seen


def _actions(bus):
    return [e.payload["action"] for e in bus.replay(topic="audit-log")]


def test_block_tra_ve_product_kem_finding_roi_trinh_lai_gate():
    bus, orch, seen = _orch({"block": 1})
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    assert "spec.security_rework" in _actions(bus)
    assert (
        seen
        and "chữ ký không phủ nội dung SD-14" in seen[-1]["hint"]
        and "gốc tin cậy nằm trong repo" in seen[-1]["hint"]
    )
    assert len(list(bus.replay(topic="approved-specs"))) == 2, "product phải viết lại spec"
    g = orch.gate.pending.get("SPEC-P1")
    assert g is not None and g.kind == "spec", f"bản viết lại phải trình lại gate spec, gate: {list(orch.gate.pending)}"
    assert not orch.plans and "P1" not in orch.gate.pending, "không escalation, không lập kế hoạch trước khi duyệt lại"
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    assert orch.plans, "duyệt lại → threat model chấm bản mới → lập kế hoạch"


def test_reject_o_gate_trinh_lai_thi_khong_lap_ke_hoach():
    bus, orch, _ = _orch({"block": 1})
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    orch.gate.decide("SPEC-P1", "reject", by="human:po", reason="bản viết lại bỏ mất yêu cầu")
    orch.run()
    assert not orch.plans, "quyết định MỚI NHẤT của gate là reject — lần approve cũ không còn hiệu lực"


def test_qua_tran_viet_lai_thi_escalation():
    bus, orch, _ = _orch({"block": 99})
    _drive_to_spec_gate(bus, orch)
    for _ in range(3):
        if "SPEC-P1" in orch.gate.pending:
            orch.gate.decide("SPEC-P1", "approve", by="human:po")
        orch.run()
    assert _actions(bus).count("spec.security_rework") == 2
    assert "spec_blocked_by_security" in _actions(bus)
    r = orch.gate.pending.get("P1")
    assert r is not None and r.kind == "escalation" and not orch.plans


def test_cung_finding_lap_lai_khong_de_escalation_len_gate_spec():
    """Supervisor escalate khi cùng lỗi lặp ≥ 2 lần theo key review-results. Key của threat model là `SPEC-<key>` —
    trùng subject gate spec, nên escalation đó ĐÈ thế hệ gate spec đang chờ. Chuỗi spec đã có trần riêng (ADR-0059)."""
    bus, orch, _ = _orch({"block": 2})
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    g = orch.gate.pending.get("SPEC-P1")
    assert g is not None and g.kind == "spec", f"lần chặn thứ 2 phải trình lại gate spec, không escalation: {g}"
    esc = [
        e
        for e in bus.replay(topic="audit-log")
        if e.payload["action"] == "gate.request"
        and '"escalation"' in e.payload["evidence"]
        and '"SPEC-P1"' in e.payload["evidence"]
    ]
    assert not esc, "không gate escalation nào mang subject của gate spec"


def test_dung_lai_tu_audit_sau_khi_khoi_dong_lai():
    bus, orch, _ = _orch({"block": 1})
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    again = Orchestrator(bus, FakeClient(handler=handler))
    assert again.spec_security_reworks["P1"] == 1 and not again.spec_regate
    assert "SPEC-P1" in again.gate.pending


def test_luot_viet_lai_transient_thi_hoan_khong_dem():
    chan = {"block": 1, "tam": 1}

    def h(system, user):
        inp = _inp(user)
        if _agent_of(system) == "product" and inp.get("hint") and chan["tam"] > 0:
            chan["tam"] -= 1
            raise TransientError("quota")
        if _agent_of(system) == "security" and "artifacts" in inp and chan["block"] > 0:
            chan["block"] -= 1
            return BLOCK
        return handler(system, user)

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    assert "spec.security_rework" not in _actions(bus) and orch.spec_security_reworks["P1"] == 0
    assert any(r.startswith("transient:") for _, r in orch.deferred.values()), (
        "lượt viết lại lỗi tạm thì hoãn event spec"
    )


def test_threat_model_thay_chu_ky_gate_spec_moi_nhat():
    """Hub thật 2026-10-17 (SPEC-CR-DDCSV-DPIA-004): chủ dự án tự ký gate spec (`human:liend`) chấp nhận rủi ro
    RK-DPIA4-01, rồi security chặn spec vì rủi ro đó "chưa accepted cho tới khi có event gate.decide do chủ dự án ký"
    — chữ ký đã có, nhưng đầu vào lượt threat model không mang nó. Product viết lại, trình lại gate, chủ dự án phải ký
    lại một thứ đã ký. Code điền chữ ký (ai, quyết gì, lý do) từ `gate.history` vào đầu vào, `verified_by=orchestrator`."""
    seen: list[dict] = []

    def h(system, user):
        inp = _inp(user)
        if _agent_of(system) == "security" and "artifacts" in inp:
            seen.append(inp)
        return handler(system, user)

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po", reason="chấp nhận RK-01 cho dữ liệu giả")
    orch.run()
    assert seen, "threat model phải chạy sau khi duyệt"
    d = seen[-1].get("spec_gate_decision")
    assert d is not None, f"đầu vào threat model không mang chữ ký gate spec: {sorted(seen[-1])}"
    assert d["subject_id"] == "SPEC-P1" and d["decision"] == "approve" and d["by"] == "human:po"
    assert d["reason"] == "chấp nhận RK-01 cho dữ liệu giả" and d["verified_by"] == "orchestrator"
