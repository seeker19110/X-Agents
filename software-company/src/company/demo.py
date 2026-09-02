"""Chạy thử hai ticket qua vòng lõi bằng logic xác định (không gọi LLM).

TCK-1: ticket thường → reviewer + qa pass là đủ.
TCK-2: ticket có risk_tags → phải chờ thêm security-engineer (ADR-0003).
"""
from __future__ import annotations

from .blackboard import Blackboard
from .bus import InMemoryBus
from .delivery import DeliveryLead
from .events import AuditLog, Envelope, PullRequest, ReviewResult, Task
from .gates import GateRequest, HumanGate
from .supervisor import Supervisor


def _pr(bus: InMemoryBus, tid: str, actor: str) -> None:
    bus.publish(Envelope(topic="pull-requests", key=tid, actor=actor, payload=PullRequest(
        ticket_id=tid, branch=f"ticket/{tid}", pr_ref="#1",
        local_checks={"lint": True, "tests": True, "coverage": 0.86}).model_dump()))


def _review(bus: InMemoryBus, tid: str, source: str, actor: str, **kw) -> None:
    bus.publish(Envelope(topic="review-results", key=tid, actor=actor,
                         payload=ReviewResult(ticket_id=tid, source=source, verdict="pass", **kw).model_dump()))


def run() -> None:
    bus = InMemoryBus(); bb = Blackboard(bus); gate = HumanGate(); sup = Supervisor(bus)
    lead = DeliveryLead(bus, gate)
    bb.write("delivery-lead", "architecture", "docs/c4.md", "C4 L1-L2")
    bb.write("delivery-lead", "api-contract", "openapi.yaml", "v1")
    bb.write("security-engineer", "threat-model", "docs/threat-model.md", "v1: T-01..T-06")
    gate.request(GateRequest(kind="plan", subject_id="PLAN-1", checklist=["c4", "contract", "threat-model"],
                             created_by="delivery-lead"))
    gate.decide("PLAN-1", "approve", by="human:pm")

    t1 = Task(ticket_id="TCK-1", project_id="P1", requirement_id="REQ-1", assignee="backend",
              title="GET /orders/{id}", acceptance=["Given ... When ... Then ..."],
              estimate_tokens=6_000, budget_tokens=10_000)
    t2 = Task(ticket_id="TCK-2", project_id="P1", requirement_id="REQ-2", assignee="backend",
              title="POST /payments", acceptance=["Given ... When ... Then ..."],
              estimate_tokens=20_000, budget_tokens=30_000, risk_tags=["payment", "pii"])
    lead.dispatch(t1, "PLAN-1"); lead.dispatch(t2, "PLAN-1")

    bus.publish(Envelope(topic="audit-log", key="backend", actor="backend",
                         payload=AuditLog(actor="backend", action="code", ticket_id="TCK-1", tokens=8_500).model_dump()))
    _pr(bus, "TCK-1", "backend")
    _review(bus, "TCK-1", "reviewer", "reviewer")
    _review(bus, "TCK-1", "qa", "qa-debugger", metrics={"mutation": 0.74})

    _pr(bus, "TCK-2", "backend")
    _review(bus, "TCK-2", "reviewer", "reviewer")
    _review(bus, "TCK-2", "qa", "qa-debugger")
    state_before_security = lead.state["TCK-2"]
    _review(bus, "TCK-2", "security", "security-engineer", metrics={"dast_high": 0, "license_violations": 0})

    print("TCK-1 state:", lead.state["TCK-1"], "| required reviews:", sorted(lead.required_reviews("TCK-1")))
    print("TCK-2 state:", state_before_security, "->", lead.state["TCK-2"],
          "| required reviews:", sorted(lead.required_reviews("TCK-2")))
    print("release candidates:", lead.releases)
    print("gate pending:", list(gate.pending))
    print("supervisor actions:", [(a.target, a.action) for a in sup.actions])
    print("events:", len(bus))


if __name__ == "__main__":
    run()
