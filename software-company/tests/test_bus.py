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

def test_replay_by_key():
    bus = InMemoryBus()
    for k in ("A", "B", "A"):
        bus.publish(Envelope(topic="audit-log", key=k, actor=k, payload={"actor": k, "action": "x"}))
    assert len(list(bus.replay(key="A"))) == 2
