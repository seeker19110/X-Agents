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


# ---------- F4/F7/F9 (báo cáo mô phỏng donghanhcungban 2026-09-02) ----------

def _lifecycle_to_production(handler_fn, **kw):
    from company.bus import InMemoryBus
    from company.llm import FakeClient
    from company.orchestrator import Orchestrator
    from test_orchestrator import _drive_to_plan
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler_fn), **kw)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    for rid in list(orch.gate.pending):
        if rid.startswith("REL"): orch.gate.decide(rid, "approve", by="human:release-manager")
    orch.run()
    return bus, orch


def test_conditional_acceptance_closes_tickets_once_change_request_is_decided():
    """F4: nghiệm thu conditional → CR; khách quyết CR (kể cả deferred) → ticket của release đó đóng, không `released` mãi."""
    from company.events import Envelope
    from test_orchestrator import handler
    bus, orch = _lifecycle_to_production(handler)
    assert orch.lead.state["T1"] == "released"
    bus.publish(Envelope(topic="acceptance-results", key="REL-001", actor="account-manager", payload={
        "release_id": "REL-001", "project_id": "P1", "verdict": "conditional", "signed_by": "customer:po",
        "findings": [{"level": "nit", "text": "thiếu trang tin"}]}))
    orch.run()
    cr = bus.latest("change-requests", "CR-UAT-1")
    assert cr is not None and cr.payload["release_id"] == "REL-001" and orch.lead.state["T1"] == "released"
    bus.publish(Envelope(topic="change-requests", key="CR-UAT-1", actor="human:po", payload={**cr.payload, "decision": "deferred"}))
    orch.run()
    assert orch.lead.state["T1"] == "closed"
    assert any(e.payload["action"] == "ticket.closed" for e in bus.replay(topic="audit-log"))


def test_batch_releases_groups_approved_tickets_into_one_rc():
    """F7: --batch-release: T1 approved nhưng T2 (phụ thuộc T1) còn chạy → chưa RC; T2 approved → một RC cho cả hai."""
    from test_orchestrator import handler
    bus, orch = _lifecycle_to_production(handler, batch_releases=True)
    assert orch.lead.releases == ["REL-001"] and orch.lead.release_tickets["REL-001"] == ["T1", "T2"]
    rcs = [e.payload for e in bus.replay(topic="release-candidates")]
    assert len(rcs) == 1 and rcs[0]["tickets"] == ["T1", "T2"]
    assert [e.payload["env"] for e in bus.replay(topic="release-events")] == ["staging", "production"], "một lần staging, một lần production"
    assert orch.lead.state == {"T1": "released", "T2": "released"}


def test_batch_releases_do_not_wait_for_blocked_ticket():
    from company.bus import InMemoryBus
    from company.llm import FakeClient
    from company.orchestrator import Orchestrator
    from test_orchestrator import _agent_of, _drive_to_plan, _inp, handler
    def failing(system, user):
        if _agent_of(system) == "reviewer" and _inp(user)["ticket_id"] == "T2":
            return {"ticket_id": "T2", "source": "reviewer", "verdict": "block", "findings": [{"level": "block", "text": "sai"}]}
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=failing), batch_releases=True)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    # T2 bị supervisor cắt ngân sách (review block lặp) → paused + gate escalation; T1 approved chưa release vì T2 còn in_review
    assert orch.lead.state["T1"] == "approved" and not orch.lead.releases and orch.gate.pending["T2"].kind == "escalation"
    orch.gate.decide("T2", "reject", by="human:pm", reason="bỏ T2"); orch.run()
    assert orch.lead.state["T2"] == "closed" and orch.lead.release_tickets == {"REL-001": ["T1"]}


def test_release_engineer_cannot_override_rc_version():
    """F9: version của release-events lấy từ RC; model khai khác thì bị ghi đè + audit."""
    from test_orchestrator import _agent_of, handler
    def liar(system, user):
        out = handler(system, user)
        if _agent_of(system) == "release-engineer": out["version"] = "9.9.9"
        return out
    bus, _ = _lifecycle_to_production(liar)
    evs = [e.payload for e in bus.replay(topic="release-events")]
    rc = {e.key: e.payload["version"] for e in bus.replay(topic="release-candidates")}
    assert evs and all(e["version"] == rc[e["release_id"]] for e in evs) and "9.9.9" not in {e["version"] for e in evs}
    n = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.version_overridden")
    assert n == len(evs)


# ---------- F19: khôi phục từ log ở chế độ gom release ----------

def _replay_into(bus, tasks, **kw):
    """Như orchestrator mở lại bus: ticket dựng lại từ plan (dispatch ở chế độ replaying), rồi áp từng event trong log."""
    lead2 = DeliveryLead(InMemoryBus(), HumanGate(), **kw)
    lead2.replaying = True
    try:
        for t in tasks: lead2.dispatch(t, "PLAN")
    finally:
        lead2.replaying = False
    for env in bus.replay(): lead2.replay(env)
    return lead2


def test_replay_batch_releases_rebuilds_rc_from_log_instead_of_recreating():
    """Lần chạy thật: T1, T2 approved → MỘT RC REL-001 gom cả hai. Trước đây replay chạy lại flush_releases theo thứ tự
    review trong log → REL-001=[T1], REL-002=[T2]... và release-events của REL-001 áp sai ticket (T2 kẹt `approved`)."""
    bus, _, lead = _setup(); lead.batch_releases = True
    tasks = [_task("T1"), _task("T2")]
    for t in tasks: lead.dispatch(t, "PLAN")
    _approve_ticket(bus, "T1")
    assert lead.releases == [], "T2 còn chạy → chưa gom"
    _approve_ticket(bus, "T2")
    assert lead.releases == ["REL-001"] and lead.release_tickets["REL-001"] == ["T1", "T2"]
    _release_event(bus, "REL-001", "staging", "deployed")
    assert lead.state == {"T1": "merged", "T2": "merged"}

    lead2 = _replay_into(bus, tasks, batch_releases=True)
    assert lead2.releases == ["REL-001"]
    assert lead2.release_tickets == {"REL-001": ["T1", "T2"]}
    assert lead2.versions == lead.versions
    assert lead2.state == {"T1": "merged", "T2": "merged"}
    assert [e.key for e in bus.replay(topic="release-candidates")] == ["REL-001"], "replay không phát RC mới"


def test_replay_per_ticket_releases_keeps_ids_from_log():
    bus, _, lead = _setup()
    tasks = [_task("T1"), _task("T2")]
    for t in tasks: lead.dispatch(t, "PLAN")
    _approve_ticket(bus, "T2"); _approve_ticket(bus, "T1")
    assert lead.release_tickets == {"REL-001": ["T2"], "REL-002": ["T1"]}
    lead2 = _replay_into(bus, tasks)
    assert lead2.release_tickets == lead.release_tickets and lead2.releases == lead.releases
