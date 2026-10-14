"""Spec của một change request đổi requirement có gate spec và kế hoạch RIÊNG, không bị coi là spec trùng của dự án.

Hub thật 2026-10-14 (QLKH-DD-CSV): CR-DDCSV-INFRA-002 đi hết intake → research → draft → câu hỏi làm rõ → spec
(`approved-specs` key=CR-DDCSV-INFRA-002, `change_id` có, `project_id`=QLKH-DD-CSV). `_plan` lấy gate
`SPEC-<project>` — đã duyệt từ 2026-10-12 — nên bỏ qua gate, rồi thấy dự án đã có kế hoạch từ `approved-specs`
(PLAN-QLKH-DD-CSV-1) và ghi `plan.duplicate_spec` → `plan_skipped`. Spec của CR không bao giờ được duyệt, không bao
giờ thành ticket.

Luật: spec theo key của CHUỖI — gate `SPEC-<key>`, và "spec trùng" chỉ khi đã có kế hoạch từ spec của CÙNG key.
Dự án thường key = project_id nên không đổi gì.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _drive_to_plan, _pub, handler


def _audits(bus, action):
    return [e for e in bus.replay(topic="audit-log") if e.payload.get("action") == action]


def _spec_cr(bus, key="CR-1"):
    base = dict(bus.latest("approved-specs", "P1").payload)
    _pub(bus, "approved-specs", key, "product", {**base, "change_id": key, "status": "pending_human"})


def test_spec_cua_cr_mo_gate_rieng_roi_lap_ke_hoach_rieng():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    n = len(orch.plans)
    _spec_cr(bus)
    orch.run()
    assert not _audits(bus, "plan.duplicate_spec"), "spec của CR không phải spec trùng của dự án"
    assert "SPEC-CR-1" in orch.gate.pending and orch.gate.pending["SPEC-CR-1"].kind == "spec"
    orch.gate.decide("SPEC-CR-1", "approve", by="human:po")
    orch.run()
    moi = [p for p in orch.plans.values() if p.get("source_key") == "CR-1"]
    assert len(orch.plans) == n + 1 and len(moi) == 1 and moi[0]["project_id"] == "P1"


def test_spec_du_an_publish_lai_van_la_trung():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    base = dict(bus.latest("approved-specs", "P1").payload)
    _pub(bus, "approved-specs", "P1", "product", base)
    orch.run()
    assert _audits(bus, "plan.duplicate_spec"), "spec lặp của chính dự án vẫn bị chặn như cũ"


def test_ho_so_gate_spec_cua_cr_tim_ra_du_an():
    from company import gate_brief as GB

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    _spec_cr(bus)
    orch.run()
    assert GB.build(orch, "SPEC-CR-1")["project_id"] == "P1", "PRD/threat model nằm ở namespace của dự án, không của mã CR"


def _muc(b, mid):
    return next(x for x in b["self_check"] if x["id"] == mid)


def test_ho_so_gate_spec_cua_cr_doc_runtime_va_cau_hoi_cua_chinh_chuoi():
    """Hub thật 2026-10-14: product khai `runtime.deploy` trong cả bốn spec của CR-DDCSV-INFRA-002 (key = mã CR), nhưng
    hồ sơ đọc `approved-specs` key = project_id — spec gốc 2026-10-12, không có deploy — nên `reviewer:tu-dong` reject
    ba lần vì "thiếu runtime" mà product không thể sửa."""
    from company import gate_brief as GB

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    base = dict(bus.latest("approved-specs", "P1").payload)
    rt = {"command": "python -m cr.server --port {port}", "port": 0, "health": "/healthz", "expect_status": 200,
          "timeout_s": 60, "deploy": "docker-compose.yml"}
    _pub(bus, "clarification-questions", "CR-1", "product",
         {"project_id": "P1", "round": 1, "questions": [{"id": "CQ-CR-1", "text": "image db build ở đâu?",
                                                          "options": ["cục bộ", "registry"], "default": "cục bộ"}]})
    _pub(bus, "approved-specs", "CR-1", "product", {**base, "change_id": "CR-1", "runtime": rt, "status": "pending_human"})
    orch.run()
    b = GB.build(orch, "SPEC-CR-1")
    run = _muc(b, "spec.runtime")
    assert any("cr.server" in f for f in run["facts"]), "runtime đọc từ spec của chuỗi CR, không từ spec gốc của dự án"
    assert run["sources"][0]["key"] == "CR-1"
    hoi = _muc(b, "spec.cau-hoi-mo")
    assert hoi["verdict"] == "gap" and "CQ-CR-1" in " ".join(hoi["facts"]), "câu hỏi của chuỗi CR, không của dự án"
    assert hoi["facts"][0].startswith("1 câu hỏi"), "câu hỏi của dự án gốc không lẫn vào chuỗi CR"
