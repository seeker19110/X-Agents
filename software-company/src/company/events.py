from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Topic = Literal[
    "research-requests", "research-findings", "requirements-draft",
    "clarification-questions", "clarification-answers", "approved-specs",
    "tasks", "pull-requests", "review-results", "release-candidates",
    "release-events", "incidents", "shared-context", "audit-log", "supervisor-actions",
    "change-requests", "acceptance-results", "external-feedback",
]
Assignee = Literal["backend", "frontend", "mobile", "database", "platform", "data"]
Namespace = Literal[
    "prd", "glossary", "design", "architecture", "api-contract", "schema", "threat-model",
    "infra", "analytics", "docs", "knowledge", "contract",
]
ReviewSource = Literal["reviewer", "qa", "security"]

NAMESPACE_OWNERS: dict[str, set[str]] = {
    "prd": {"spec-writer"}, "glossary": {"researcher"}, "design": {"researcher"},
    "architecture": {"delivery-lead"}, "api-contract": {"delivery-lead", "backend"},
    "schema": {"database"}, "threat-model": {"security-engineer"}, "infra": {"platform"},
    "analytics": {"data"}, "docs": {"support-docs"}, "knowledge": {"supervisor"}, "contract": {"account-manager"},
}

# Ticket có bất kỳ tag nào dưới đây bắt buộc thêm review của security-engineer (ADR-0003).
RISK_TAGS = frozenset({"auth", "payment", "pii", "crypto", "upload", "admin", "external-api"})
BUDGET_FACTOR = 1.5  # budget_tokens ≥ estimate_tokens × BUDGET_FACTOR (skill cost-estimation)

class Envelope(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    topic: Topic
    key: str
    actor: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
    estimate_tokens: int | None = None
    budget_tokens: int = 120_000
    risk_tags: list[str] = []
    priority: int = 3  # 1 = cao nhất (WSJF/MoSCoW quy về 1..5); delivery-lead dispatch theo priority rồi thứ tự tạo

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
    source: ReviewSource
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

class ChangeRequest(BaseModel):
    """Khách yêu cầu đổi phạm vi sau khi spec đã duyệt (account-manager tạo). Không sửa spec trực tiếp."""
    change_id: str
    project_id: str
    requested_by: str
    description: str
    affects_requirements: list[str] = []
    impact: dict[str, Any] = {}
    decision: Literal["pending", "accepted", "rejected", "deferred"] = "pending"

class AcceptanceResult(BaseModel):
    """Kết quả nghiệm thu (UAT) của khách trên một release (account-manager ghi nhận)."""
    release_id: str
    project_id: str
    verdict: Literal["accepted", "rejected", "conditional"]
    signed_by: str
    findings: list[Finding] = []
    evidence_ref: str | None = None

class SupervisorAction(BaseModel):
    target: str
    action: Literal["pause", "resume", "escalate", "budget_cut", "warn"]
    reason: str
    evidence: str | None = None

PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "tasks": Task, "pull-requests": PullRequest, "review-results": ReviewResult,
    "shared-context": SharedContext, "audit-log": AuditLog, "supervisor-actions": SupervisorAction,
    "change-requests": ChangeRequest, "acceptance-results": AcceptanceResult,
}

TicketState = Literal["draft", "waiting", "dispatched", "in_progress", "in_review", "changes_requested",
                      "approved", "merged", "released", "closed", "blocked", "escalated"]
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"dispatched", "waiting"}, "waiting": {"dispatched"}, "dispatched": {"in_progress"},
    "in_progress": {"in_review"}, "in_review": {"changes_requested", "approved"}, "changes_requested": {"dispatched"},
    "approved": {"merged", "changes_requested"}, "merged": {"released", "changes_requested"}, "released": {"closed", "changes_requested"},
    "blocked": {"dispatched", "escalated"},
    "escalated": {"dispatched", "closed"}, "closed": set(),
}
def can_transition(src: str, dst: str) -> bool:
    return dst in {"blocked", "escalated"} or dst in TRANSITIONS.get(src, set())
