"""ADR-0007: orchestrator tự động nối topic → agent → topic; dừng ở human gate / supervisor; khôi phục từ SQLite."""
from __future__ import annotations

import json

import pytest

from company.bus import InMemoryBus
from company.events import Envelope, SupervisorAction
from company.llm import FakeClient
from company.orchestrator import ENGINEERING, PLAN_INPUTS, ROUTES, Orchestrator, check_routes
from company.orchestrator import main as orch_main
from company.registry import load_agents
from company.sqlite_bus import SQLiteBus

T1 = {"ticket_id": "T1", "project_id": "P1", "requirement_id": "REQ-1", "assignee": "backend", "title": "GET /orders",
      "acceptance": ["given/when/then"], "estimate_tokens": 4_000, "budget_tokens": 6_000, "retry": 0}
T2 = {**T1, "ticket_id": "T2", "requirement_id": "REQ-2", "title": "POST /payments", "depends_on": ["T1"],
      "risk_tags": ["payment"], "priority": 1}


def _agent_of(system: str) -> str:
    return system.split("\n", 1)[0].lstrip("# ").strip()


def _inp(user: str) -> dict:
    return json.loads(user.split("```json\n", 1)[1].split("\n```", 1)[0])


def handler(system: str, user: str) -> dict:
    """Mô phỏng mọi agent bằng đầu ra hợp lệ tối thiểu; xác định agent qua tiêu đề system prompt."""
    a, p = _agent_of(system), _inp(user)
    pid = p.get("project_id", "P1")
    if a == "intake": return {"project_id": pid, "kind": "intake", "data": {"goals": ["G1"]}}
    if a == "researcher": return {"project_id": pid, "kind": "researcher", "data": {"domain": {}}}
    if a == "synthesizer": return {"project_id": pid, "kind": "draft", "requirements": []}
    if a == "risk": return {"project_id": pid, "kind": "risk", "risks": ["R1"]}
    if a == "clarifier": return {"project_id": pid, "round": 1, "questions": [{"id": "Q1", "text": "?", "options": ["a"], "default": "a"}]}
    if a == "spec-writer": return {"project_id": pid, "status": "pending_human", "artifacts": ["docs/prd.md"]}
    if a == "delivery-lead": return {"items": [T1, T2]}
    if a in ENGINEERING:
        return {"ticket_id": p["ticket_id"], "branch": f"ticket/{p['ticket_id']}", "pr_ref": "#1", "local_checks": {"lint": True, "tests": True}}
    if a in {"reviewer", "qa-debugger", "security-engineer"}:
        src = {"reviewer": "reviewer", "qa-debugger": "qa", "security-engineer": "security"}[a]
        return {"ticket_id": p.get("ticket_id") or p["release_id"], "source": src, "verdict": "pass"}
    if a == "release-engineer":
        return {"release_id": p["release_id"], "version": "1.0.0", "env": p["target_env"], "status": "deployed"}
    if a == "account-manager":
        return {"change_id": "CR-1", "project_id": pid, "requested_by": p["from"], "description": p["text"], "decision": "pending"}
    raise AssertionError(f"agent không mong đợi: {a}")


def _pub(bus, topic, key, actor, payload):
    return bus.publish(Envelope(topic=topic, key=key, actor=actor, payload=payload))


def _topics(bus):
    return [e.topic for e in bus.replay() if e.topic not in {"audit-log", "shared-context", "supervisor-actions"}]


def _drive_to_plan(bus, orch):
    """research-request → ... → clarification-questions (người trả lời) → approved-specs → gate spec → plan → gate plan."""
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    assert _topics(bus)[-1] == "clarification-questions", "dừng chờ người trả lời"
    _pub(bus, "clarification-answers", "P1", "human:po", {"project_id": "P1", "answers": [{"question_id": "Q1", "answer": "a"}]})
    orch.run()
    assert "SPEC-P1" in orch.gate.pending and next(iter(orch.deferred.values()))[1] == "gate:SPEC-P1"
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    assert not orch.deferred and "PLAN-P1-1" in orch.gate.pending and "PLAN-P1-1" in orch.plans
    assert not orch.lead.tickets, "chưa dispatch khi plan chưa duyệt"


# ---------- bảng route ----------

def test_routes_match_front_matter():
    agents = load_agents()
    assert check_routes(agents) == []
    assert {r.topic_in for r in ROUTES} | set(PLAN_INPUTS) <= {t for a in agents.values() for t in a.reads}


# ---------- vòng đời đầy đủ trong bộ nhớ ----------

def test_full_lifecycle_stops_at_gates_and_humans():
    bus = InMemoryBus(); client = FakeClient(handler=handler); orch = Orchestrator(bus, client)
    _drive_to_plan(bus, orch)
    assert _topics(bus)[:6] == ["research-requests", "research-findings", "research-findings", "requirements-draft",
                                "requirements-draft", "clarification-questions"]

    orch.gate.decide("PLAN-P1-1", "approve", by="human:pm")
    orch.run()
    st = orch.lead.state
    # T1: backend → reviewer+qa pass → approved → REL-001 staging → merged → QA staging pass → gate 3 chờ
    # T2 (phụ thuộc T1, risk_tags): tự dispatch sau T1 approved, cần thêm security → REL-002
    assert st["T1"] == "merged" and st["T2"] == "merged", st
    assert orch.lead.releases == ["REL-001", "REL-002"] and {"REL-001", "REL-002"} <= set(orch.gate.pending)
    reviews = [(e.key, e.payload["source"]) for e in bus.replay(topic="review-results")]
    assert ("T2", "security") in reviews and ("T1", "security") not in reviews
    assert all(e.payload["env"] == "staging" for e in bus.replay(topic="release-events"))

    orch.gate.decide("REL-001", "approve", by="human:release-manager")
    orch.run()
    assert st["T1"] == "released" and st["T2"] == "merged"
    prod = [e for e in bus.replay(topic="release-events") if e.payload["env"] == "production"]
    assert [e.key for e in prod] == ["REL-001"]

    # nghiệm thu là của khách: orchestrator không tự sinh; người publish → ticket closed
    _pub(bus, "acceptance-results", "REL-001", "account-manager",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    assert st["T1"] == "closed"

    audits = [e.payload for e in bus.replay(topic="audit-log")]
    assert all(a["tokens"] == 1300 for a in audits if a["action"].startswith("produced:")), "token thật từ client"
    assert orch.stats["errors"] == 0 and not orch.queue
    tiers = {c["model_tier"] for c in client.calls}
    assert tiers == {"strong", "standard"}, "model theo tier của từng agent"


# ---------- khôi phục từ bus bền vững ----------

def test_resume_from_sqlite_does_not_redo_work(tmp_path):
    db = tmp_path / "c.sqlite"
    bus1 = SQLiteBus(db); c1 = FakeClient(handler=handler); o1 = Orchestrator(bus1, c1)
    _drive_to_plan(bus1, o1)
    o1.gate.decide("PLAN-P1-1", "approve", by="human:pm")
    o1.run(max_steps=2)  # dispatch T1, backend làm PR rồi "tắt máy" (review chưa chạy)
    n_calls, n_events = len(c1.calls), len(bus1)
    assert o1.lead.state["T1"] == "in_review"
    bus1.close()

    bus2 = SQLiteBus(db); c2 = FakeClient(handler=handler); o2 = Orchestrator(bus2, c2)
    assert o2.lead.state == o1.lead.state and o2.lead.tickets.keys() == o1.lead.tickets.keys()
    assert o2.lead.waiting() == {"T2": ["T1"]} and "PLAN-P1-1" in o2.plans and o2.gate.is_approved("PLAN-P1-1")
    assert len(bus2) == n_events, "khôi phục không phát lại event"
    assert [e.event_id for e in o2.queue] == [e.event_id for e in o1.queue]
    o2.run()
    assert o2.lead.state["T1"] == "merged" and o2.lead.state["T2"] == "merged" and o2.stats["errors"] == 0
    # 7 (nghiên cứu+plan) + T1: 3 + REL-001: 2 + T2: 4 (thêm security) + REL-002: 2 = 18, mỗi lời gọi đúng một lần
    assert n_calls + len(c2.calls) == 18


def test_poll_picks_up_gate_decision_from_other_process(tmp_path):
    from company.gate_cli import main as gate_main
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    assert gate_main(["--db", str(db), "approve", "PLAN-P1-1", "--by", "human:pm"]) == 0  # tiến trình khác
    assert "PLAN-P1-1" in orch.gate.pending, "chưa poll thì chưa thấy"
    orch.tick()
    assert orch.gate.is_approved("PLAN-P1-1") and orch.lead.state["T1"] == "merged"


# ---------- supervisor pause / resume ----------

def test_paused_ticket_is_deferred_until_resume():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.gate.decide("PLAN-P1-1", "approve", by="human:pm")
    _pub(bus, "supervisor-actions", "T1", "supervisor", SupervisorAction(target="T1", action="pause", reason="test").model_dump())
    orch.run()
    assert orch.lead.state["T1"] == "dispatched" and next(iter(orch.deferred.values()))[1] == "paused:T1"
    _pub(bus, "supervisor-actions", "T1", "supervisor", SupervisorAction(target="T1", action="resume", reason="ok").model_dump())
    orch.run()
    assert orch.lead.state["T1"] == "merged" and not orch.deferred


# ---------- đầu ra sai bị chặn, không retry ----------

def test_plan_rejected_when_budget_rule_violated():
    def bad(system, user):
        if _agent_of(system) == "delivery-lead": return {"items": [{**T1, "budget_tokens": 4_000}]}
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=bad))
    _pub(bus, "approved-specs", "P1", "spec-writer", {"project_id": "P1", "status": "pending_human", "artifacts": []})
    orch.run(); orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "plan_rejected" in acts and not orch.plans and not orch.gate.pending and not orch.lead.tickets


def test_release_engineer_wrong_env_is_invalid_output():
    def sneaky(system, user):
        if _agent_of(system) == "release-engineer":
            return {**handler(system, user), "env": "production"}
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=sneaky))
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert not list(bus.replay(topic="release-events")), "không deploy production khi chưa qua gate"
    assert orch.lead.state["T1"] == "approved" and orch.stats["errors"] >= 1
    assert any(e.payload["action"] == "invalid_output" for e in bus.replay(topic="audit-log"))


def test_model_error_is_audited_and_loop_continues():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient())  # hết câu trả lời → LLMError
    _pub(bus, "research-requests", "P1", "human", {"project_id": "P1", "description": "x"})
    res = orch.run()
    assert res[0].actions[0].startswith("error:intake") and orch.stats["errors"] == 1 and not orch.queue
    assert [e.payload["action"] for e in bus.replay(topic="audit-log")] == ["llm_error", "orchestrated"]


# ---------- CLI ----------

def test_cli_publish_and_status(tmp_path, capsys, monkeypatch):
    db = str(tmp_path / "c.sqlite"); f = tmp_path / "req.json"
    f.write_text(json.dumps({"project_id": "P1", "description": "app"}), encoding="utf-8")
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    assert orch_main(["--db", db, "publish", "research-requests", str(f), "--actor", "human:sales"]) == 0
    assert "published research-requests key=P1" in capsys.readouterr().out
    assert orch_main(["--db", db, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["queue"] == 1
    assert orch_main(["--db", db, "run", "--max-steps", "1"]) == 0  # FakeClient rỗng → lỗi được ghi, không crash
    out = capsys.readouterr().out
    assert "error:intake" in out and '"errors": 1' in out


def test_orchestrator_rejects_inconsistent_routes():
    agents = load_agents(); agents["intake"].reads = ["clarification-answers"]
    with pytest.raises(ValueError, match="ROUTES lệch"):
        Orchestrator(InMemoryBus(), FakeClient(), agents=agents)
