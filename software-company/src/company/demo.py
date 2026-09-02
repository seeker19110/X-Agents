"""Chạy thử một ticket qua toàn bộ vòng lõi bằng logic xác định (không gọi LLM)."""
from __future__ import annotations
from .bus import InMemoryBus
from .blackboard import Blackboard
from .events import Envelope, Task, PullRequest, ReviewResult, AuditLog
from .gates import HumanGate, GateRequest
from .supervisor import Supervisor
from .delivery import DeliveryLead

def run() -> None:
    bus = InMemoryBus(); bb = Blackboard(bus); gate = HumanGate(); sup = Supervisor(bus)
    lead = DeliveryLead(bus, gate)
    bb.write("delivery-lead", "architecture", "docs/c4.md", "C4 L1-L2")
    bb.write("delivery-lead", "api-contract", "openapi.yaml", "v1")
    gate.request(GateRequest(kind="plan", subject_id="PLAN-1", checklist=["c4", "contract"], created_by="delivery-lead"))
    gate.decide("PLAN-1", "approve", by="human:pm")
    t = Task(ticket_id="TCK-1", project_id="P1", requirement_id="REQ-1", assignee="backend",
             title="POST /orders", acceptance=["Given ... When ... Then ..."], budget_tokens=10_000)
    lead.dispatch(t, "PLAN-1")
    bus.publish(Envelope(topic="audit-log", key="backend", actor="backend", payload=AuditLog(actor="backend", action="code", ticket_id="TCK-1", tokens=8_500).model_dump()))
    bus.publish(Envelope(topic="pull-requests", key="TCK-1", actor="backend", payload=PullRequest(ticket_id="TCK-1", branch="ticket/TCK-1", pr_ref="#1", local_checks={"lint": True, "tests": True, "coverage": 0.86}).model_dump()))
    bus.publish(Envelope(topic="review-results", key="TCK-1", actor="reviewer", payload=ReviewResult(ticket_id="TCK-1", source="reviewer", verdict="pass").model_dump()))
    bus.publish(Envelope(topic="review-results", key="TCK-1", actor="qa-debugger", payload=ReviewResult(ticket_id="TCK-1", source="qa", verdict="pass", metrics={"mutation": 0.74}).model_dump()))
    print("ticket state:", lead.state["TCK-1"])
    print("release candidates:", lead.releases)
    print("gate pending:", list(gate.pending))
    print("supervisor actions:", [(a.target, a.action) for a in sup.actions])
    print("events:", len(bus))

if __name__ == "__main__":
    run()
