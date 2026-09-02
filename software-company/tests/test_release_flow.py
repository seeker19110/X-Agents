"""ADR-0006: lập lịch theo depends_on/priority, staging QA trước gate 3, merge/release theo release-events,
nghiệm thu khách đóng ticket, review quá hạn, sprint report."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import AcceptanceResult, AuditLog, Envelope, PullRequest, ReviewResult, Task
from company.gates import GateRequest, HumanGate
from company.supervisor import Supervisor


def _setup():
    bus = InMemoryBus(); gate = HumanGate(); lead = DeliveryLead(bus, gate)
    gate.request(GateRequest(kind="plan", subject_id="PLAN", checklist=[], created_by="delivery-lead"))
    gate.decide("PLAN", "approve", by="human")
    return bus, gate, lead


def _task(tid="T1", **kw):
    return Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="backend", title=tid, acceptance=["a"], **kw)


def _pr(bus, tid="T1"):
    bus.publish(Envelope(topic="pull-requests", key=tid, actor="backend",
                         payload=PullRequest(ticket_id=tid, branch="b", pr_ref="#1", local_checks={"lint": True}).model_dump()))


def _rev(bus, tid, src, verdict="pass", **kw):
    bus.publish(Envelope(topic="review-results", key=tid, actor=src,
                         payload=ReviewResult(ticket_id=tid, source=src, verdict=verdict, **kw).model_dump()))


def _approve_ticket(bus, tid="T1"):
    _pr(bus, tid); _rev(bus, tid, "reviewer"); _rev(bus, tid, "qa")


def _release_event(bus, rid, env, status):
    bus.publish(Envelope(topic="release-events", key=rid, actor="release-engineer",
                         payload={"release_id": rid, "version": "1.0.0", "env": env, "status": status}))


# ---------- depends_on / priority ----------

def test_dependent_ticket_waits_then_dispatches_by_priority():
    bus, _, lead = _setup()
    lead.dispatch(_task("T1"), "PLAN")
    lead.dispatch(_task("T2", depends_on=["T1"], priority=2), "PLAN")
    lead.dispatch(_task("T3", depends_on=["T1"], priority=1), "PLAN")
    assert lead.state["T2"] == "waiting" and lead.state["T3"] == "waiting" and lead.waiting() == {"T2": ["T1"], "T3": ["T1"]}
    assert [e.key for e in bus.replay(topic="tasks")] == ["T1"]
    _approve_ticket(bus, "T1")
    assert lead.state["T1"] == "approved" and lead.state["T2"] == "dispatched" and lead.state["T3"] == "dispatched"
    assert [e.key for e in bus.replay(topic="tasks")] == ["T1", "T3", "T2"], "priority 1 đi trước"


def test_unknown_or_self_dependency_rejected():
    _, _, lead = _setup()
    with pytest.raises(ValueError, match="chưa biết"):
        lead.dispatch(_task("T2", depends_on=["T9"]), "PLAN")
    with pytest.raises(ValueError, match="tự phụ thuộc"):
        lead.dispatch(_task("T3", depends_on=["T3"]), "PLAN")


# ---------- release: staging → QA → gate 3 → production → nghiệm thu ----------

def test_release_requires_staging_qa_before_gate_and_human_before_production():
    bus, gate, lead = _setup()
    lead.dispatch(_task(), "PLAN"); _approve_ticket(bus)
    rid = lead.releases[0]
    assert "REL-001" not in gate.pending
    _release_event(bus, rid, "staging", "deployed")
    assert lead.state["T1"] == "merged"
    _rev(bus, rid, "qa", "pass", metrics={"p95_ms": 210})
    assert rid in gate.pending and "regression-staging" in gate.pending[rid].checklist
    with pytest.raises(PermissionError, match="human gate"):
        _release_event(bus, rid, "production", "deployed")
    gate.decide(rid, "approve", by="human:release-manager")
    _release_event(bus, rid, "production", "deployed")
    assert lead.state["T1"] == "released"


def test_staging_qa_fail_sends_tickets_back_with_hint():
    bus, gate, lead = _setup()
    lead.dispatch(_task(), "PLAN"); _approve_ticket(bus); rid = lead.releases[0]
    _release_event(bus, rid, "staging", "deployed")
    _rev(bus, rid, "qa", "fail", findings=[{"level": "block", "text": "p95 480ms > NFR 300ms"}])
    assert rid not in gate.pending
    assert lead.state["T1"] == "dispatched" and lead.tickets["T1"].retry == 1 and "p95" in lead.tickets["T1"].hint


def test_production_rollback_reopens_tickets():
    bus, gate, lead = _setup()
    lead.dispatch(_task(), "PLAN"); _approve_ticket(bus); rid = lead.releases[0]
    _release_event(bus, rid, "staging", "deployed"); _rev(bus, rid, "qa"); gate.decide(rid, "approve", by="human")
    _release_event(bus, rid, "production", "deployed")
    _release_event(bus, rid, "production", "rolled_back")
    assert lead.state["T1"] == "dispatched" and "rolled_back" in lead.tickets["T1"].hint


def _to_production(bus, gate, lead, tid="T1"):
    lead.dispatch(_task(tid), "PLAN"); _approve_ticket(bus, tid); rid = lead.releases[-1]
    _release_event(bus, rid, "staging", "deployed"); _rev(bus, rid, "qa"); gate.decide(rid, "approve", by="human")
    _release_event(bus, rid, "production", "deployed")
    return rid


def test_customer_acceptance_closes_or_reopens():
    bus, gate, lead = _setup()
    rid = _to_production(bus, gate, lead)
    bus.publish(Envelope(topic="acceptance-results", key=rid, actor="account-manager", payload=AcceptanceResult(
        release_id=rid, project_id="P", verdict="accepted", signed_by="customer:ceo").model_dump()))
    assert lead.state["T1"] == "closed"

    bus2, gate2, lead2 = _setup()
    rid2 = _to_production(bus2, gate2, lead2)
    bus2.publish(Envelope(topic="acceptance-results", key=rid2, actor="account-manager", payload=AcceptanceResult(
        release_id=rid2, project_id="P", verdict="rejected", signed_by="customer:ceo",
        findings=[{"level": "block", "text": "Xuất báo cáo sai múi giờ (REQ-1)"}]).model_dump()))
    assert lead2.state["T1"] == "dispatched" and "múi giờ" in lead2.tickets["T1"].hint


def test_acceptance_result_schema_requires_customer_signature():
    bus = InMemoryBus()
    from company.bus import BusError
    with pytest.raises(BusError):
        bus.publish(Envelope(topic="acceptance-results", key="R", actor="account-manager",
                             payload={"release_id": "R", "project_id": "P", "verdict": "accepted"}))


def test_change_request_topic_validates():
    bus = InMemoryBus()
    bus.publish(Envelope(topic="change-requests", key="CR-1", actor="account-manager", payload={
        "change_id": "CR-1", "project_id": "P", "requested_by": "customer:po", "description": "thêm xuất Excel",
        "impact": {"estimate_days": 1.5, "estimate_tokens": 40_000}}))
    assert len(bus) == 1


# ---------- review quá hạn ----------

def test_overdue_reviews_lists_missing_sources():
    bus, _, lead = _setup()
    lead.dispatch(_task(risk_tags=["auth"]), "PLAN"); _pr(bus); _rev(bus, "T1", "reviewer")
    now = lead.review_since["T1"]
    assert lead.overdue_reviews(now + timedelta(hours=1)) == {}
    assert lead.overdue_reviews(now + timedelta(hours=3)) == {"T1": {"qa", "security"}}


# ---------- sprint report ----------

def test_sprint_report_estimate_vs_actual():
    bus = InMemoryBus(); sup = Supervisor(bus)
    t = _task(estimate_tokens=10_000, budget_tokens=15_000)
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=t.model_dump()))
    bus.publish(Envelope(topic="audit-log", key="backend", actor="backend",
                         payload=AuditLog(actor="backend", action="code", ticket_id="T1", tokens=12_500).model_dump()))
    r = sup.sprint_report()
    assert r["tickets"]["T1"]["actual_tokens"] == 12_500 and r["tickets"]["T1"]["ratio"] == 1.25
    assert r["actions"] == {"warn": 1}


def test_transitions_include_merged_and_waiting():
    from company.events import can_transition
    assert can_transition("approved", "merged") and can_transition("merged", "released") and can_transition("released", "closed")
    assert can_transition("draft", "waiting") and can_transition("waiting", "dispatched")
    assert not can_transition("approved", "released"), "phải qua merged (staging)"
    assert datetime.now(UTC) is not None
