"""Agent lỗi trên event KHÔNG phải ticket (change-request...) → escalation → duyệt phải chạy LẠI event đó.

Trước đây `_on_escalation_decided` rơi xuống nhánh ticket: "reopen" một ticket không tồn tại, event không bao giờ
chạy lại, hàng đợi rỗng. Đo được 2026-09-06 (CR-DEV-001): delivery-lead lỗi error_max_structured_output_retries,
duyệt escalation xong không có gì xảy ra, phải phát lại CR bằng tay.
"""
from __future__ import annotations

from company.bus import InMemoryBus
from company.events import Envelope
from company.llm import FakeClient, LLMError
from company.orch.routes import PLAN_REWORKS
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _inp, _product_phase, handler

CR = {"change_id": "CR-1", "project_id": "P1", "requested_by": "human:po", "description": "đổi phạm vi", "decision": "pending"}


def _flaky_lead(fail_times: int):
    n = {"k": 0}
    def h(system, user):
        a, p = _agent_of(system), _inp(user)
        if a == "product" and _product_phase(system) == "plan" and p.get("decision") == "pending":
            n["k"] += 1
            if n["k"] <= fail_times: raise LLMError("claude -p thoát mã 1 (error_max_structured_output_retries)")
        return handler(system, user)
    return h


def _impacts(bus):
    return [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "change.impact"]


def test_duyet_escalation_cua_change_request_loi_thi_chay_lai_event():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=_flaky_lead(1)))
    bus.publish(Envelope(topic="change-requests", key="CR-1", actor="human:po", payload=CR)); orch.run()
    assert not _impacts(bus) and orch.unhandled["CR-1"]["agent"] == "product"
    assert orch.gate.pending["CR-1"].kind == "escalation"
    orch.gate.decide("CR-1", "approve", by="human:lead", reason="lỗi model, thử lại"); orch.run()
    assert len(_impacts(bus)) == 1, "duyệt = event chạy lại và lần này `product` ước lượng được"
    assert "CR-1" not in orch.unhandled and not orch.queue
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "event.retried" in acts


def test_tu_choi_thi_bo_event_khong_chay_lai():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=_flaky_lead(9)))
    bus.publish(Envelope(topic="change-requests", key="CR-1", actor="human:po", payload=CR)); orch.run()
    orch.gate.decide("CR-1", "reject", by="human:lead", reason="CR sai"); orch.run()
    assert "CR-1" not in orch.unhandled and not _impacts(bus)
    assert "event.abandoned" in [e.payload["action"] for e in bus.replay(topic="audit-log")]


def test_mo_lai_bus_van_nho_event_loi_va_thu_lai_duoc(tmp_path):
    h = _flaky_lead(1)
    bus = SQLiteBus(tmp_path / "c.sqlite"); orch = Orchestrator(bus, FakeClient(handler=h))
    bus.publish(Envelope(topic="change-requests", key="CR-1", actor="human:po", payload=CR)); orch.run()
    bus.close()
    bus2 = SQLiteBus(tmp_path / "c.sqlite"); orch2 = Orchestrator(bus2, FakeClient(handler=h))
    assert "CR-1" in orch2.unhandled, "trạng thái không chỉ sống trong RAM"
    orch2.gate.decide("CR-1", "approve", by="human:lead", reason="thử lại sau restart"); orch2.run()
    assert len(_impacts(bus2)) == 1
    bus2.close()
    bus3 = SQLiteBus(tmp_path / "c.sqlite"); orch3 = Orchestrator(bus3, FakeClient(handler=h))
    assert "CR-1" not in orch3.unhandled, "event.retried đã xoá khỏi sổ"


def test_retry_unhandled_khong_co_gi_de_chay():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    assert orch._retry_unhandled("CR-404", "human:lead", "x") is False
    orch.unhandled["CR-9"] = {"topic": "change-requests", "event_id": "khong-co", "agent": "product"}
    assert orch._retry_unhandled("CR-9", "human:lead", "x") is False


def _lead_empty_plan_once():
    """Rỗng đủ số lượt máy tự sửa (`PLAN_REWORKS`) rồi thêm một lần nữa → mới tới `plan_rejected` + gate; lần kế
    tiếp (sau khi người duyệt retry) mới hợp lệ. Tên giữ nguyên: "once" là một lần TỚI NGƯỜI."""
    n = {"k": 0}
    def h(system, user):
        a, p = _agent_of(system), _inp(user)
        if a == "product" and _product_phase(system) == "plan" and p.get("decision") != "pending":
            n["k"] += 1
            if n["k"] <= 1 + PLAN_REWORKS: return {"items": []}  # kế hoạch rỗng → tự sửa hết lượt → plan_rejected
        return handler(system, user)
    return h


def test_duyet_escalation_plan_rong_thi_lap_lai_ke_hoach():
    """`plan_rejected` mở gate escalation subject=project; duyệt phải chạy lại event nguồn để delivery-lead lập lại —
    trước đây rơi xuống nhánh ticket ("reopen" ticket ma), không gì xảy ra (CR-STAGE-001, 2026-09-06)."""
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=_lead_empty_plan_once()))
    bus.publish(Envelope(topic="research-requests", key="P1", actor="human:sales", payload={"project_id": "P1", "description": "app"}))
    orch.run()
    bus.publish(Envelope(topic="clarification-answers", key="P1", actor="human:po",
                         payload={"project_id": "P1", "answers": [{"question_id": "Q1", "answer": "a"}]}))
    orch.run(); orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    assert orch.gate.pending["P1"].kind == "escalation" and "P1" in orch.unhandled and not orch.plans
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "plan_rejected" in acts
    orch.gate.decide("P1", "approve", by="human:lead", reason="lập lại"); orch.run()
    assert "PLAN-P1-1" in orch.plans and orch.lead.tickets, "duyệt = `product` lập lại và ticket được giao ngay (ADR-0037)"
    assert "P1" not in orch.unhandled


def test_mo_lai_bus_van_nho_plan_rejected(tmp_path):
    bus = SQLiteBus(tmp_path / "c.sqlite"); orch = Orchestrator(bus, FakeClient(handler=_lead_empty_plan_once()))
    bus.publish(Envelope(topic="research-requests", key="P1", actor="human:sales", payload={"project_id": "P1", "description": "app"}))
    orch.run()
    bus.publish(Envelope(topic="clarification-answers", key="P1", actor="human:po",
                         payload={"project_id": "P1", "answers": [{"question_id": "Q1", "answer": "a"}]}))
    orch.run(); orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    assert "P1" in orch.unhandled
    bus.close(); bus2 = SQLiteBus(tmp_path / "c.sqlite"); orch2 = Orchestrator(bus2, FakeClient(handler=handler))
    assert orch2.unhandled["P1"]["topic"] == "approved-specs"


def test_duyet_roi_restart_truoc_khi_chay_lai_van_chay_lai_event(tmp_path):
    """Audit 2026-09-23: `_retry_unhandled` chỉ đẩy event vào hàng đợi RAM; restart trước khi nó chạy lại thì dấu
    `orchestrated` của LẦN LỖI thắng và event bị bỏ im lặng. Anh em `_retry_stalled` đã vá (`project.retried`)."""
    h = _flaky_lead(1)
    bus = SQLiteBus(tmp_path / "c.sqlite"); orch = Orchestrator(bus, FakeClient(handler=h))
    bus.publish(Envelope(topic="change-requests", key="CR-1", actor="human:po", payload=CR)); orch.run()
    orch.gate.decide("CR-1", "approve", by="human:lead", reason="lỗi model, thử lại")
    orch.run(max_steps=1)          # xử lý đúng `gate.decide` → ghi `event.retried`, chưa kịp chạy lại thì chết
    assert "event.retried" in [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert not _impacts(bus), "chưa kịp chạy lại trước khi chết"
    bus.close()
    bus2 = SQLiteBus(tmp_path / "c.sqlite"); orch2 = Orchestrator(bus2, FakeClient(handler=h))
    assert [e.topic for e in orch2.queue] == ["change-requests"], "lệnh chạy lại phải sống qua restart"
    orch2.run()
    assert len(_impacts(bus2)) == 1
    bus2.close()


def test_loi_lan_hai_sau_khi_duyet_van_mo_gate_moi():
    """Audit 2026-10-10 (`TRAPS.md` §1 khuôn 3): `_mark_unhandled` dùng khoá once `unhandled:{event_id}:{agent}`
    không có thế hệ. Duyệt retry → event chạy lại → agent lỗi LẦN HAI với cùng event_id → supervisor im lặng và
    không gate nào mở: `unhandled` ghi CR-1 nhưng `gate.pending` rỗng, người trực không thấy gì. Anh em `_stall`
    (`stall:{event_id}:{n}`) và `escalation_decided` đã vá cùng khuôn."""
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=_flaky_lead(2)))
    bus.publish(Envelope(topic="change-requests", key="CR-1", actor="human:po", payload=CR)); orch.run()
    assert orch.gate.pending["CR-1"].kind == "escalation"
    orch.gate.decide("CR-1", "approve", by="human:lead", reason="lỗi model, thử lại"); orch.run()
    assert not _impacts(bus) and "CR-1" in orch.unhandled, "lần hai vẫn lỗi"
    assert "CR-1" in orch.gate.pending and orch.gate.pending["CR-1"].kind == "escalation", \
        "lỗi lần hai của cùng event phải mở gate mới, không im lặng vì khoá once của lần một"
    orch.gate.decide("CR-1", "approve", by="human:lead", reason="thử lại lần ba"); orch.run()
    assert len(_impacts(bus)) == 1 and "CR-1" not in orch.unhandled
