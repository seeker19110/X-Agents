import pytest
from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Envelope, PullRequest, ReviewResult, Task
from company.gates import GateRequest, HumanGate


def _setup():
    bus = InMemoryBus(); gate = HumanGate(); lead = DeliveryLead(bus, gate)
    gate.request(GateRequest(kind="plan", subject_id="PLAN", checklist=[], created_by="delivery-lead"))
    return bus, gate, lead

def _task(): return Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="backend", title="x", acceptance=["a"])
def _pr(bus): bus.publish(Envelope(topic="pull-requests", key="T1", actor="backend", payload=PullRequest(ticket_id="T1", branch="b", pr_ref="#1", local_checks={"lint": True}).model_dump()))
def _rev(bus, src, verdict, rc=None): bus.publish(Envelope(topic="review-results", key="T1", actor=src, payload=ReviewResult(ticket_id="T1", source=src, verdict=verdict, root_cause=rc).model_dump()))

def test_cannot_dispatch_without_plan_approval():
    _, _, lead = _setup()
    with pytest.raises(PermissionError):
        lead.dispatch(_task(), "PLAN")

def test_four_eyes():
    _, gate, _ = _setup()
    with pytest.raises(PermissionError):
        gate.decide("PLAN", "approve", by="delivery-lead")

def test_happy_path_to_release_gate():
    bus, gate, lead = _setup(); gate.decide("PLAN", "approve", by="human")
    lead.dispatch(_task(), "PLAN"); _pr(bus); _rev(bus, "reviewer", "pass"); _rev(bus, "qa", "pass")
    assert lead.state["T1"] == "approved" and lead.releases == ["REL-001"] and "REL-001" in gate.pending

def test_fail_retries_with_hint_then_blocks():
    bus, gate, lead = _setup(); gate.decide("PLAN", "approve", by="human")
    lead.dispatch(_task(), "PLAN")
    for i in range(2):
        _pr(bus); _rev(bus, "reviewer", "pass"); _rev(bus, "qa", "fail", rc=f"bug{i}")
    assert lead.state["T1"] == "dispatched" and lead.tickets["T1"].retry == 2 and lead.tickets["T1"].hint == "bug1"
    _pr(bus); _rev(bus, "reviewer", "pass"); _rev(bus, "qa", "fail", rc="bug2")
    assert lead.state["T1"] == "blocked"

def test_gate_timeouts():
    from datetime import datetime, timedelta, timezone
    gate = HumanGate(); gate.request(GateRequest(kind="spec", subject_id="S", checklist=[]))
    now = datetime.now(timezone.utc)
    assert gate.due(now + timedelta(hours=13)) == (["S"], [])
    assert gate.due(now + timedelta(hours=25)) == ([], ["S"])
