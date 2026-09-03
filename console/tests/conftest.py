"""Fixture dựng DB thật: publish event thật qua bus/Envelope/payload model của hai công ty, không viết SQL tay.

Gate được tạo bằng bản ghi `audit-log` `gate.request` y như `PersistentGate.request` ghi — chỉ khác ở chỗ test đặt
`ts` để thử ngưỡng tuổi gate (`created_at` khi replay chính là `ts` của event).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from company.events import AuditLog as CompanyAudit
from company.events import Envelope as CompanyEnvelope
from company.events import PullRequest, ReviewResult, Task
from company.sqlite_bus import SQLiteBus as CompanySQLiteBus
from studio.events import AuditLog as StudioAudit
from studio.events import Envelope as StudioEnvelope
from studio.events import PerformanceSnapshot, VideoBrief
from studio.sqlite_bus import SQLiteBus as StudioSQLiteBus

NOW = datetime.now(UTC)


def gate_request(bus, envelope_cls, audit_cls, *, kind: str, subject_id: str, checklist: list[str],
                 created_by: str, age_hours: float = 0.0, **extra) -> None:
    """Một `gate.request` như PersistentGate ghi, với tuổi tuỳ chọn."""
    data = {"kind": kind, "subject_id": subject_id, "checklist": checklist, "created_by": created_by, **extra}
    payload = audit_cls(actor=created_by, action="gate.request", evidence=json.dumps(data, ensure_ascii=False))
    bus.publish(envelope_cls(topic="audit-log", key=created_by, actor=created_by, ts=NOW - timedelta(hours=age_hours),
                             payload=payload.model_dump()))


def gate_decide(bus, envelope_cls, audit_cls, *, subject_id: str, decision: str, by: str, reason: str = "") -> None:
    data = {"subject_id": subject_id, "decision": decision, "by": by, "reason": reason}
    payload = audit_cls(actor=by, action="gate.decide", evidence=json.dumps(data, ensure_ascii=False))
    bus.publish(envelope_cls(topic="audit-log", key=by, actor=by, payload=payload.model_dump()))


def _produced(bus, envelope_cls, audit_cls, *, actor: str, topic_out: str, tokens: int, cost: float = 0.0,
              age_days: int = 0, **ids) -> None:
    fields = {"actor": actor, "action": f"produced:{topic_out}", "tokens": tokens,
              "evidence": json.dumps({"model": "fake-1", "turns": 1, "tool_calls": 2}), **ids}
    if "cost_usd" in audit_cls.model_fields: fields["cost_usd"] = cost
    bus.publish(envelope_cls(topic="audit-log", key=actor, actor=actor, ts=NOW - timedelta(days=age_days),
                             payload=audit_cls(**fields).model_dump()))


def build_company_db(path: Path) -> Path:
    """Một ticket đi tới in_review + PR + review block, một gate `plan` 30 giờ và một gate `spec` đã quyết."""
    bus = CompanySQLiteBus(path)
    task = Task(ticket_id="TCK-112", project_id="P1", requirement_id="R1", assignee="backend",
                title="API đăng nhập", acceptance=["ok"], estimate_tokens=78_000, budget_tokens=120_000)
    bus.publish(CompanyEnvelope(topic="tasks", key="TCK-112", actor="delivery-lead", payload=task.model_dump()))
    pr = PullRequest(ticket_id="TCK-112", branch="ticket/TCK-112", pr_ref="PR-1", summary="thêm login",
                     local_checks={"lint": True, "tests": True, "verified_by": "workspace"})
    bus.publish(CompanyEnvelope(topic="pull-requests", key="TCK-112", actor="backend", payload=pr.model_dump()))
    review = ReviewResult(ticket_id="TCK-112", source="reviewer", verdict="block",
                          findings=[{"level": "block", "text": "thiếu kiểm tra quyền"}], root_cause="thiếu authz")
    bus.publish(CompanyEnvelope(topic="review-results", key="TCK-112", actor="reviewer", payload=review.model_dump()))
    _produced(bus, CompanyEnvelope, CompanyAudit, actor="backend", topic_out="pull-requests", tokens=8_420, cost=0.21,
              ticket_id="TCK-112", project_id="P1")
    _produced(bus, CompanyEnvelope, CompanyAudit, actor="reviewer", topic_out="review-results", tokens=2_100, cost=0.05,
              age_days=3, ticket_id="TCK-112", project_id="P1")
    gate_request(bus, CompanyEnvelope, CompanyAudit, kind="plan", subject_id="PLAN-1",
                 checklist=["c4", "review:reviewer:block"], created_by="delivery-lead", age_hours=30)
    gate_request(bus, CompanyEnvelope, CompanyAudit, kind="spec", subject_id="SPEC-1", checklist=["prd"],
                 created_by="spec-writer", age_hours=1)
    gate_decide(bus, CompanyEnvelope, CompanyAudit, subject_id="SPEC-1", decision="approve", by="human:pm")
    bus.close()
    return path


def build_studio_db(path: Path) -> Path:
    """Một video đã briefed + số liệu hiệu suất, một gate `publish` 13 giờ (warn) và một gate `plan` 2 giờ (calm)."""
    bus = StudioSQLiteBus(path)
    brief = VideoBrief(video_id="vid-042", channel_id="ch1", working_title="Ống kính 50mm", pillar="review",
                       angle="thực tế", audience="người mới", estimate_tokens=90_000, budget_tokens=150_000)
    bus.publish(StudioEnvelope(topic="video-briefs", key="vid-042", actor="channel-strategist", payload=brief.model_dump()))
    snap = PerformanceSnapshot(video_id="vid-042", channel_id="ch1", views=7_840, impressions=41_200, ctr=0.19,
                               avg_view_duration_s=284.0, retention_curve=[{"t": 0, "pct": 100}, {"t": 15, "pct": 88}])
    bus.publish(StudioEnvelope(topic="performance-snapshots", key="vid-042", actor="human",
                               payload=json.loads(snap.model_dump_json())))
    _produced(bus, StudioEnvelope, StudioAudit, actor="script-writer", topic_out="scripts", tokens=12_000,
              video_id="vid-042")
    gate_request(bus, StudioEnvelope, StudioAudit, kind="publish", subject_id="PUB-vid-042",
                 checklist=["review:fact:pass", "thumbnail"], created_by="publisher", age_hours=13,
                 triggered_by="human:owner")
    gate_request(bus, StudioEnvelope, StudioAudit, kind="plan", subject_id="PLAN-ch1", checklist=["pillar"],
                 created_by="channel-strategist", age_hours=2)
    bus.close()
    return path


@pytest.fixture
def company_db(tmp_path: Path) -> Path:
    return build_company_db(tmp_path / "company.sqlite")


@pytest.fixture
def studio_db(tmp_path: Path) -> Path:
    return build_studio_db(tmp_path / "studio.sqlite")


@pytest.fixture
def no_gateway(monkeypatch: pytest.MonkeyPatch) -> str:
    """Gateway không tồn tại: cổng đóng, `collect` phải trả `backends: []` và `sources.gateway.ok = False`."""
    return "http://127.0.0.1:9"
