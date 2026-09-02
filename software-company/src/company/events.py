from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

Topic = Literal[
    "research-requests", "research-findings", "requirements-draft",
    "clarification-questions", "clarification-answers", "approved-specs",
    "tasks", "pull-requests", "review-results", "release-candidates",
    "release-events", "incidents", "shared-context", "audit-log", "supervisor-actions",
]
Assignee = Literal["backend", "frontend", "mobile", "database"]
Namespace = Literal["prd", "glossary", "architecture", "api-contract", "schema", "docs", "knowledge"]

NAMESPACE_OWNERS: dict[str, set[str]] = {
    "prd": {"spec-writer"}, "glossary": {"domain"}, "architecture": {"delivery-lead"},
    "api-contract": {"delivery-lead", "backend"}, "schema": {"database"},
    "docs": {"support-docs"}, "knowledge": {"supervisor"},
}

class Envelope(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    topic: Topic
    key: str
    actor: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any]

class Task(BaseModel):
    ticket_id: str
    project_id: str
    requirement_id: str
    assignee: Assignee
    title: str
    acceptance: list[str]
    scope: list[str] = []
    estimate_days: float = 0.5
    depends_on: list[str] = []
    retry: int = 0
    hint: str | None = None
    budget_tokens: int = 120_000

class PullRequest(BaseModel):
    ticket_id: str
    branch: str
    pr_ref: str
    summary: str = ""
    impact: dict[str, Any] = {}
    local_checks: dict[str, Any]

class Finding(BaseModel):
    level: Literal["block", "warn", "nit"]
    text: str
    location: str | None = None

class ReviewResult(BaseModel):
    ticket_id: str
    source: Literal["reviewer", "qa"]
    verdict: Literal["pass", "block", "fail"]
    findings: list[Finding] = []
    root_cause: str | None = None
    bug_reports: list[str] = []
    metrics: dict[str, Any] = {}

class SharedContext(BaseModel):
    namespace: Namespace
    version: int
    content_ref: str
    summary: str = ""

class AuditLog(BaseModel):
    actor: str
    action: str
    ticket_id: str | None = None
    project_id: str | None = None
    evidence: str | None = None
    tokens: int = 0

class SupervisorAction(BaseModel):
    target: str
    action: Literal["pause", "resume", "escalate", "budget_cut", "warn"]
    reason: str
    evidence: str | None = None

PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "tasks": Task, "pull-requests": PullRequest, "review-results": ReviewResult,
    "shared-context": SharedContext, "audit-log": AuditLog, "supervisor-actions": SupervisorAction,
}

TicketState = Literal["draft", "dispatched", "in_progress", "in_review", "changes_requested",
                      "approved", "released", "closed", "blocked", "escalated"]
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"dispatched"}, "dispatched": {"in_progress"}, "in_progress": {"in_review"},
    "in_review": {"changes_requested", "approved"}, "changes_requested": {"dispatched"},
    "approved": {"released"}, "released": {"closed"}, "blocked": {"dispatched", "escalated"},
    "escalated": {"dispatched", "closed"}, "closed": set(),
}
def can_transition(src: str, dst: str) -> bool:
    return dst in {"blocked", "escalated"} or dst in TRANSITIONS.get(src, set())
