"""Bộ đếm "spec thiếu runtime" (ADR-0031) tính theo CHUỖI spec, không theo dự án.

Hub thật 2026-10-15 (QLKH-DD-CSV): hai change request CR-DDCSV-DPIA-001 và CR-DDCSV-SEC-006 cùng ra spec trong một
phút, cả hai thiếu `runtime.deploy`. Spec của CR DPIA được trả về product (lần 1); spec của CR SEC — lần ĐẦU của chuỗi
nó — bị tính là lần 2 của dự án nên đi thẳng tới escalation cấp dự án, và escalation đó tạm dừng luôn bản viết lại của
CR DPIA (`paused:QLKH-DD-CSV`). Gate spec mở theo `SPEC-<key>` (key của chuỗi), nên lượt sửa tự động cũng phải tính
theo key đó.

Cả hai spec còn đoán `runtime.command` vì product "không đọc được toàn văn PRD v3 §8b", trong khi dự án đã có runtime
qua gate spec (CR-DDCSV-INFRA-002). Lời trả về product phải mang runtime đã duyệt đó để nó chép, không đoán.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_gate_spec_runtime import RUNTIME, _handler_with, _spec, _to_spec
from test_orchestrator import _pub

DEPLOY = {**RUNTIME, "deploy": "docker-compose.yml", "dependencies": ["PostgreSQL 16"]}


def _spec_fn(p, n):
    """Dự án P1 có runtime ngay; spec của CR thiếu runtime tới khi được trả về kèm `hint`."""
    cid = p.get("change_id")
    if cid is None:
        return _spec("P1", kind="application", runtime=RUNTIME)
    return _spec("P1", kind="application", change_id=cid, **({"runtime": DEPLOY} if "hint" in p else {}))


def _cr_answers(bus, cid):
    draft = dict(bus.latest("requirements-draft", "P1").payload)
    _pub(bus, "requirements-draft", cid, "product", {**draft, "change_id": cid})
    _pub(
        bus,
        "clarification-answers",
        cid,
        "human:po",
        {"project_id": "P1", "change_id": cid, "answers": [{"question_id": f"Q-{cid}", "answer": "a"}]},
    )


def _du_an_da_duyet(spec_fn=_spec_fn):
    h, seen = _handler_with(spec_fn)
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    return bus, orch, seen


def _acts(bus, action):
    return [e for e in bus.replay(topic="audit-log") if e.payload.get("action") == action]


def test_hai_cr_cung_thieu_runtime_moi_chuoi_duoc_mot_luot_sua():
    bus, orch, _seen = _du_an_da_duyet()
    _cr_answers(bus, "CR-A")
    _cr_answers(bus, "CR-B")
    orch.run()
    assert not _acts(bus, "spec.runtime_escalated"), "lần đầu của chuỗi CR-B không phải lần hai của dự án"
    assert "P1" not in orch.gate.pending
    assert "SPEC-CR-A" in orch.gate.pending and "SPEC-CR-B" in orch.gate.pending
    assert orch.spec_runtime_reworks["CR-A"] == 1 and orch.spec_runtime_reworks["CR-B"] == 1


def test_chuoi_cr_van_escalate_khi_chinh_no_thieu_hai_lan():
    def fn(p, n):
        cid = p.get("change_id")
        return (
            _spec("P1", kind="application", runtime=RUNTIME)
            if cid is None
            else _spec("P1", kind="application", change_id=cid)
        )

    bus, orch, _seen = _du_an_da_duyet(fn)
    _cr_answers(bus, "CR-A")
    orch.run()
    esc = _acts(bus, "spec.runtime_escalated")
    assert len(esc) == 1 and "P1" in orch.gate.pending and orch.spec_runtime_reworks["CR-A"] == 2
    assert orch.unhandled["P1"]["chain"] == "CR-A"


def test_loi_tra_ve_mang_runtime_da_duyet_cua_du_an():
    bus, orch, seen = _du_an_da_duyet()
    _cr_answers(bus, "CR-A")
    orch.run()
    hint = next(p["hint"] for p in seen if p.get("change_id") == "CR-A" and "hint" in p)
    assert "SPEC-P1" in hint and RUNTIME["command"] in hint, "product phải chép runtime đã qua gate, không đoán"


def test_khong_co_runtime_da_duyet_thi_loi_tra_ve_nhu_cu():
    h, seen = _handler_with(
        lambda p, n: _spec("P1", kind="application", **({"runtime": RUNTIME} if "hint" in p else {}))
    )
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert "đã qua gate spec" not in seen[1]["hint"]


def test_duyet_escalation_cua_chuoi_cr_tra_lai_luot_sua_cho_dung_chuoi(tmp_path):
    def fn(p, n):
        cid = p.get("change_id")
        if cid is None:
            return _spec("P1", kind="application", runtime=RUNTIME)
        return _spec("P1", kind="application", change_id=cid, **({"runtime": DEPLOY} if n >= 5 else {}))

    h, _seen = _handler_with(fn)
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    _cr_answers(bus, "CR-A")
    orch.run()
    assert "P1" in orch.gate.pending and orch.spec_runtime_reworks["CR-A"] == 2
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=h))
    assert o2.spec_runtime_reworks["CR-A"] == 2 and o2.unhandled["P1"]["chain"] == "CR-A", (
        "dựng lại từ audit theo chuỗi"
    )
    o2.gate.decide("P1", "approve", by="human:po", reason="chạy lại chuỗi CR-A")
    o2.run()
    assert "SPEC-CR-A" in o2.gate.pending, "chạy lại: lần thiếu đầu được sửa tự động như chuỗi mới"
    o3 = Orchestrator(SQLiteBus(db), FakeClient(handler=h))
    assert o3.spec_runtime_reworks["CR-A"] == o2.spec_runtime_reworks["CR-A"] == 1
