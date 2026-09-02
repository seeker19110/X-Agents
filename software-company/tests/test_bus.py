import pytest

from company.bus import BusError, InMemoryBus, PermissionDenied
from company.events import Envelope, Task


def test_publish_valid_task():
    bus = InMemoryBus()
    t = Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="backend", title="x", acceptance=["a"])
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=t.model_dump()))
    assert len(bus) == 1

def test_invalid_payload_rejected():
    bus = InMemoryBus()
    with pytest.raises(BusError):
        bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload={"ticket_id": "T1"}))

def test_schema_required_fields():
    bus = InMemoryBus()
    with pytest.raises(BusError):
        bus.publish(Envelope(topic="incidents", key="I1", actor="support-docs", payload={"incident_id": "I1"}))

def test_namespace_owner_enforced():
    bus = InMemoryBus()
    with pytest.raises(PermissionDenied):
        bus.publish(Envelope(topic="shared-context", key="schema", actor="frontend",
                             payload={"namespace": "schema", "version": 1, "content_ref": "x"}))

def test_new_namespaces_writable_by_owner():
    bus = InMemoryBus()
    for actor, ns in (("ux-designer", "design"), ("security-engineer", "threat-model"),
                      ("platform", "infra"), ("data", "analytics")):
        bus.publish(Envelope(topic="shared-context", key=ns, actor=actor,
                             payload={"namespace": ns, "version": 1, "content_ref": "x"}))
    assert len(bus) == 4
    with pytest.raises(PermissionDenied):
        bus.publish(Envelope(topic="shared-context", key="design", actor="frontend",
                             payload={"namespace": "design", "version": 2, "content_ref": "y"}))

def test_task_accepts_new_assignees_and_risk_tags():
    bus = InMemoryBus()
    for who in ("platform", "data"):
        t = Task(ticket_id=f"T-{who}", project_id="P", requirement_id="R1", assignee=who, title="x",
                 acceptance=["a"], risk_tags=["pii"], estimate_tokens=10_000, budget_tokens=15_000)
        bus.publish(Envelope(topic="tasks", key=t.ticket_id, actor="delivery-lead", payload=t.model_dump()))
    assert len(bus) == 2

def test_replay_by_key():
    bus = InMemoryBus()
    for k in ("A", "B", "A"):
        bus.publish(Envelope(topic="audit-log", key=k, actor=k, payload={"actor": k, "action": "x"}))
    assert len(list(bus.replay(key="A"))) == 2
