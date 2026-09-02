"""Bổ sung sau rà soát: hạn mức cả dự án, gate quá hạn được escalate, gate nghiệm thu là gate thật."""
from datetime import UTC, datetime, timedelta

import pytest

from company.bus import InMemoryBus
from company.events import Envelope, Task
from company.gate_cli import PersistentGate
from company.gates import GateRequest, HumanGate
from company.supervisor import Supervisor


def _task(tid, project="P1", budget=100_000):
    return Task(ticket_id=tid, project_id=project, requirement_id="R1", assignee="backend", title="x",
                acceptance=["a"], estimate_tokens=10_000, budget_tokens=budget)


def _audit(bus, ticket, tokens, project=None):
    bus.publish(Envelope(topic="audit-log", key="backend", actor="backend",
                         payload={"actor": "backend", "action": "produced", "ticket_id": ticket,
                                  "project_id": project, "tokens": tokens}))


def test_project_budget_cuts_even_when_every_ticket_is_within_budget():
    """Mười ticket đều trong ngân sách riêng vẫn có thể đốt hết tiền của khách."""
    bus = InMemoryBus(); sup = Supervisor(bus, project_budget_tokens=50_000)
    for i in range(5):
        bus.publish(Envelope(topic="tasks", key=f"T{i}", actor="delivery-lead", payload=_task(f"T{i}").model_dump()))
    for i in range(5):
        _audit(bus, f"T{i}", 12_000)
    assert all(b.ratio < 1 for b in sup.budgets.values()), "từng ticket vẫn trong hạn mức"
    cut = [a for a in sup.actions if a.target == "P1" and a.action == "budget_cut"]
    assert cut, "nhưng cả dự án thì vượt và phải bị cắt"
    assert sup.sprint_report()["projects"]["P1"]["used"] == 60_000


def test_project_budget_warns_once():
    bus = InMemoryBus(); sup = Supervisor(bus, project_budget_tokens=100_000)
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=_task("T1").model_dump()))
    _audit(bus, "T1", 85_000)
    _audit(bus, "T1", 1_000)
    warns = [a for a in sup.actions if a.target == "P1" and a.action == "warn"]
    assert len(warns) == 1, "cảnh báo mức dự án chỉ một lần, không spam mỗi lượt"


def test_no_project_budget_means_no_project_actions():
    bus = InMemoryBus(); sup = Supervisor(bus)
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=_task("T1").model_dump()))
    _audit(bus, "T1", 999_999)
    assert not [a for a in sup.actions if a.target == "P1"]


def test_gate_overdue_is_escalated_once():
    bus = InMemoryBus(); sup = Supervisor(bus)
    sup.escalate_gate("PLAN-1", "gate quá hạn 24h")
    sup.escalate_gate("PLAN-1", "gate quá hạn 24h")
    acts = [a for a in sup.actions if a.target == "PLAN-1"]
    assert len(acts) == 1 and acts[0].action == "escalate"


def test_human_gate_lists_overdue_requests():
    gate = HumanGate(timeout=timedelta(hours=24))
    old = GateRequest(kind="plan", subject_id="PLAN-1", checklist=["x"],
                      created_at=datetime.now(UTC) - timedelta(hours=30), created_by="delivery-lead")
    gate.request(old)
    gate.request(GateRequest(kind="plan", subject_id="PLAN-2", checklist=["x"], created_by="delivery-lead"))
    assert [r.subject_id for r in gate.overdue()] == ["PLAN-1"]


def test_acceptance_is_a_real_gate_kind():
    bus = InMemoryBus(); gate = PersistentGate(bus)
    gate.request(GateRequest(kind="acceptance", subject_id="UAT-REL-001", created_by="account-manager",
                             checklist=["uat-script", "signed_by"]))
    assert gate.pending["UAT-REL-001"].kind == "acceptance"
    with pytest.raises(PermissionError):  # four-eyes: người của công ty không tự ký thay khách
        gate.decide("UAT-REL-001", "approve", by="account-manager")
    gate.decide("UAT-REL-001", "approve", by="khach:po")
    assert gate.is_approved("UAT-REL-001")
