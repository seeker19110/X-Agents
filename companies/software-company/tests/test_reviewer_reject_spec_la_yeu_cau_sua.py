"""`reject` của `reviewer:*` ở gate spec = yêu cầu sửa (product viết lại với lý do làm hint), không phải ngõ cụt.

Hub thật 2026-10-14 (QLKH-DD-CSV): `reviewer:tu-dong` reject SPEC-CR-DDCSV-INFRA-002 lúc 10:09 với hint cụ thể (thiếu
`runtime.deploy`, thiếu mục ngoài phạm vi, NFR thiếu ngưỡng). Reviewer chỉ được approve/reject (`gate_reviewer.refusal`),
và ADR gốc 0033 dặn "thiếu thứ chặn tiêu chí nghiệm thu → reject với hint cụ thể" — ý là sửa rồi trình lại. Nhưng
`_plan` chỉ coi `request_changes` là viết lại; `reject` làm event spec được đánh dấu xong và mọi spec sau của cùng
chuỗi bị bỏ qua (`gate:SPEC-…:reject`) — CR kẹt vĩnh viễn.

Luật: `reject` do `reviewer:*` ký ở gate spec chạy đúng đường `request_changes` (ADR-0031 §3). `reject` của người giữ
nghĩa cũ: dừng.
"""

from __future__ import annotations

import pytest

from company import gate_reviewer as gr
from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _agent_of, _drive_to_spec_gate, _product_phase, handler

LY_DO = "root_cause: thiếu runtime.deploy; decision: reject; hint: khai deploy docker-compose.yml"
ID = "reviewer:tu-dong"


@pytest.fixture
def khoa(tmp_path, monkeypatch):
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry.json"))
    brief = tmp_path / "brief.json"
    brief.write_text("{}", encoding="utf-8")
    return gr.new_key(ID, tmp_path / "registry.json", tmp_path / "keys"), brief


def _orch():
    goi: list[str] = []

    def spy(system, user):
        if _agent_of(system) == "product" and _product_phase(system) == "spec":
            goi.append(user)
        return handler(system, user)

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=spy))
    _drive_to_spec_gate(bus, orch)
    return orch, goi


def test_reviewer_reject_spec_goi_lai_product_va_trinh_lai_gate(khoa):
    orch, goi = _orch()
    n0 = len(goi)
    gr.decide(orch.gate, "SPEC-P1", ID, LY_DO, khoa[0], khoa[1], decision="reject")
    orch.run()
    assert len(goi) == n0 + 1 and "thiếu runtime.deploy" in goi[-1], "lý do của reviewer tới product làm hint"
    assert "SPEC-P1" in orch.gate.pending, "spec viết lại được trình lại gate"


def test_nguoi_reject_spec_van_la_dung():
    orch, goi = _orch()
    n0 = len(goi)
    orch.gate.decide("SPEC-P1", "reject", by="human:po", reason="dự án huỷ")
    orch.run()
    assert len(goi) == n0 and "SPEC-P1" not in orch.gate.pending and not orch.plans
