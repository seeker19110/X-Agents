"""ADR gốc 0035/0038 mở rộng: ở phạm vi `toan-bo`, reviewer đại diện khách được nhận xét ticket đang chạy (`comment`),
cùng điều kiện với nộp/quyết change request và trả lời câu hỏi làm rõ (`gate_reviewer.cr_actor_refusal`).

Hub thật 2026-10-15 (QLKH-DD-CSV, PLAN-26): ticket DDCSV-95/97 viết verifier chữ ký REL-* theo spec đoán sai định dạng
hub (`escalated_at`, chữ ký base64) — pha spec không đọc được mã hub. Phiên chính có sự thật (gate_reviewer.py) nhưng
`comment` chỉ nhận `human:*`, mà phiên chính không được ký dưới tên người.
"""

from __future__ import annotations

import pytest

from company.bus import InMemoryBus
from company.gate_reviewer import FLAG_ENV, SCOPE_ENV, SCOPE_RONG, SCOPE_TOAN_BO
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _drive_to_spec_gate, handler


def _orch():
    """Dừng khi ticket vừa được giao (`dispatched`): `comment` chỉ áp cho ticket đang chạy."""
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run(max_steps=2)
    return bus, orch


def _dang_chay(orch):
    return next(t for t, st in orch.lead.state.items() if st == "dispatched")


def test_reviewer_toan_bo_nhan_xet_ticket(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(SCOPE_ENV, SCOPE_TOAN_BO)
    bus, orch = _orch()
    tid = _dang_chay(orch)
    t = orch.comment(tid, "reviewer:phien-chinh", "chữ ký hub là hex, mốc T là generation")
    assert t.human_hint == "chữ ký hub là hex, mốc T là generation"
    a = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "reviewer.comment"]
    assert a and a[-1].actor == "reviewer:phien-chinh", "audit ghi đúng tên reviewer, không giả làm người"


@pytest.mark.parametrize("flag,scope", [("1", SCOPE_RONG), ("", SCOPE_TOAN_BO)])
def test_reviewer_ngoai_toan_bo_bi_tu_choi(monkeypatch, flag, scope):
    monkeypatch.setenv(FLAG_ENV, flag)
    monkeypatch.setenv(SCOPE_ENV, scope)
    _, orch = _orch()
    with pytest.raises(ValueError, match="reviewer"):
        orch.comment(_dang_chay(orch), "reviewer:phien-chinh", "x")
