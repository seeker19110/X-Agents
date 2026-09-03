"""Các điểm nâng cấp sau rà soát: bus kiểm producer theo topic, env lọc khoá cho lint/test, lỗi chung ở khối kỹ thuật
vẫn rework, worktree bẩn được dọn trước khi làm lại, token đốt trước lỗi transport không mất, supervisor báo ngưỡng
một lần, OpenAI-compat chỉ tắt tính năng khi 400 nói đúng tính năng, SQLite bus không bỏ sót event tiến trình khác,
watch không chết vì một nhịp lỗi, retry nhận ngân sách còn lại, tool bỏ symlink và chặn cờ trong `paths`."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import pytest

from company.bus import HUMAN_TOPICS, TOPIC_PRODUCERS, InMemoryBus, PermissionDenied, producer_allowed
from company.events import AuditLog, Envelope, Task
from company.llm import Completion, FakeClient, LLMConfig, LLMError, OpenAICompatClient, TransientError
from company.orchestrator import Orchestrator
from company.registry import load_agents
from company.runner import AgentRunner, RunnerError
from company.sqlite_bus import SQLiteBus
from company.supervisor import Supervisor
from company.tools import ToolCall, WorkspaceTools
from company.workspace import TicketWorkspace, WorkspaceError, clean_env
from test_orchestrator import T1, _drive_to_plan, handler
from test_tools_and_agentic import _init_repo, _task_env, _tc


def _audits(bus, action):
    return [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == action]


# ---------- 1. bus kiểm producer theo topic ----------

def test_bus_rejects_human_on_agent_topic_and_audits():
    bus = InMemoryBus()
    with pytest.raises(PermissionDenied, match="không được phát topic tasks"):
        bus.publish(Envelope(topic="tasks", key="T1", actor="human:po", payload=T1))
    denied = _audits(bus, "publish_denied")
    assert len(denied) == 1 and json.loads(denied[0]["evidence"])["actor"] == "human:po"
    assert not list(bus.replay(topic="tasks")), "event bị từ chối không vào log"


def test_bus_rejects_agent_outside_declared_writes():
    bus = InMemoryBus()
    with pytest.raises(PermissionDenied, match="backend không được phát topic tasks"):
        bus.publish(Envelope(topic="tasks", key="T1", actor="backend", payload=T1))
    with pytest.raises(PermissionDenied):
        bus.publish(Envelope(topic="release-events", key="R", actor="backend",
                             payload={"release_id": "R", "env": "staging", "status": "deployed", "version": "1.0.0"}))
    # producer đúng và người trên topic đầu vào của khách thì đi qua
    bus.publish(Envelope(topic="clarification-answers", key="P", actor="human:po", payload={"project_id": "P", "answers": []}))
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=T1))
    assert InMemoryBus(enforce_owners=False).publish(Envelope(topic="tasks", key="T1", actor="human", payload=T1))


def test_topic_producers_match_agent_front_matter():
    """Bảng producer của bus phải khớp `writes` của agent: agent khai topic nào thì bus phải cho phát topic đó."""
    schemas = InMemoryBus()._schemas
    for aid, spec in load_agents().items():
        for topic in spec.writes:
            if topic not in schemas: continue  # tên không phải topic bus (vd. knowledge-base của supervisor)
            assert producer_allowed(topic, aid), f"{aid} khai writes {topic} nhưng bus chặn"
    assert HUMAN_TOPICS <= set(TOPIC_PRODUCERS), "topic của người cũng phải có trong bảng"


# ---------- 2. run_checks không đưa khoá API vào lệnh con ----------

def test_workspace_checks_run_with_clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret"); monkeypatch.setenv("PLAIN_VAR", "ok")
    assert "OPENAI_API_KEY" not in clean_env() and clean_env()["PLAIN_VAR"] == "ok"
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1"); ws.create()
    r = ws._run("python", "-c", "import os; print(sorted(k for k in os.environ if 'API_KEY' in k))")
    assert r.ok and r.output.strip() == "[]", "lint/test của khách không thấy khoá API"


# ---------- 3. lỗi chung (WorkspaceError) ở khối kỹ thuật vẫn rework ----------

def test_generic_error_in_engineering_triggers_rework(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler), repo=repo, base="main")
    monkeypatch.setattr(orch.runner, "generate_in_workspace",
                        lambda *a, **k: (_ for _ in ()).throw(WorkspaceError("git commit: index.lock")))
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.lead.state["T1"] == "blocked", "không treo dispatched: retry tới blocked → gate escalation"
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert [t["retry"] for t in tasks] == [0, 1, 2] and all("index.lock" in t["hint"] for t in tasks[1:])
    assert _audits(bus, "handler_error") and orch.gate.pending["T1"].kind == "escalation"


# ---------- 4. worktree bẩn từ lần chạy trước được dọn ----------

def test_generate_in_workspace_resets_dirty_worktree(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1"); ws.create()
    (ws.path / "rac.py").write_text("x = 1\n", encoding="utf-8")           # lần trước lỗi giữa chừng để lại
    (ws.path / "mod.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")  # sửa dở file tracked
    assert ws.dirty()
    client = FakeClient(handler=lambda s, u: {"ticket_id": "T1", "branch": "x", "pr_ref": "x", "summary": "ok", "local_checks": {}},
                        tool_handler=lambda m, t: [_tc("write_file", path="f.py", content="def f():\n    return 1\n")]
                        if not any(x["role"] == "assistant" for x in m) else [])
    bus = InMemoryBus(); g = AgentRunner(bus, client).generate_in_workspace("backend", _task_env(), ws)
    assert g.payloads[0]["impact"]["files"] == ["f.py"], "rác của lần trước không vào PR"
    assert not (ws.path / "rac.py").exists() and g.payloads[0]["local_checks"]["tests"] is True
    assert _audits(bus, "workspace_reset")
    assert ws.reset() is False, "worktree sạch thì không có gì để dọn"


# ---------- 5. token đốt trước TransientError không mất ----------

class _FlakyClient(FakeClient):
    """Lượt 1 gọi tool (đốt token), lượt 2 lỗi transport."""
    def complete(self, **kw: Any) -> Completion:
        if kw.get("messages") and any(m["role"] == "tool" for m in kw["messages"]):
            raise TransientError("HTTP 503")
        return Completion(text="", input_tokens=2_000, output_tokens=100, model="fake",
                          stop_reason="tool_use", tool_calls=[_tc("list_files")])


def test_llm_error_audit_carries_tokens_burned_in_tool_loop(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1"); ws.create()
    bus = InMemoryBus(); sup = Supervisor(bus)
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload={**T1, "budget_tokens": 100_000}))
    with pytest.raises(TransientError):
        AgentRunner(bus, _FlakyClient()).generate("backend", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox())
    err = _audits(bus, "llm_error")
    assert len(err) == 1 and err[0]["tokens"] == 2_100 and sup.budgets["T1"].used == 2_100


# ---------- 6. supervisor: warn/budget_cut mỗi ticket một lần ----------

def test_supervisor_thresholds_fire_once_until_budget_extended():
    bus = InMemoryBus(); sup = Supervisor(bus)
    t = Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="backend", title="x", acceptance=["a"], budget_tokens=1000)
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=t.model_dump()))
    def audit(tokens, action="produced:x"):
        bus.publish(Envelope(topic="audit-log", key="backend", actor="backend",
                             payload=AuditLog(actor="backend", action=action, ticket_id="T1", tokens=tokens).model_dump()))
    audit(850); audit(0); audit(10)
    assert [a.action for a in sup.actions] == ["warn"]
    audit(200); audit(0); audit(50)
    assert [a.action for a in sup.actions] == ["warn", "budget_cut"], "sau ngưỡng không lặp lại mỗi audit"
    sup.budgets["T1"].limit += 1000; audit(0, "budget.extended")
    assert [a.action for a in sup.actions] == ["warn", "budget_cut"]
    audit(700)   # 1810/2000 = 90% → warn lại được
    audit(300)   # 2110/2000 → cắt lại được
    assert [a.action for a in sup.actions] == ["warn", "budget_cut", "warn", "budget_cut"]


# ---------- 7. OpenAI-compat: 400 vì lý do khác không tắt json_schema / prompt_cache_key ----------

def _openai(monkeypatch, responder):
    c = OpenAICompatClient(LLMConfig(provider="openai", base_url="http://x", models={"fast": "m", "smart": "m"}))
    monkeypatch.setattr(c, "_post", responder)
    return c


def test_openai_compat_keeps_features_when_400_is_unrelated(monkeypatch):
    def unrelated(body):
        raise LLMError('HTTP 400: {"error": "context length exceeded"}')
    c = _openai(monkeypatch, unrelated)
    with pytest.raises(LLMError, match="context length"):
        c.complete(system="s", user="u", schema={"type": "object"}, model_tier="fast", cache_key="backend")
    assert c._json_schema_ok is None and c._cache_key_ok is None, "không quy lỗi cho tính năng rồi tắt vĩnh viễn"


def test_openai_compat_falls_back_only_when_400_names_the_feature(monkeypatch):
    seen: list[dict] = []
    def responder(body):
        seen.append(body)
        if "prompt_cache_key" in body: raise LLMError('HTTP 400: {"error": "Unrecognized request argument: prompt_cache_key"}')
        if body.get("response_format", {}).get("type") == "json_schema": raise LLMError("HTTP 400: response_format unsupported")
        return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    c = _openai(monkeypatch, responder)
    c.complete(system="s", user="u", schema={"type": "object"}, model_tier="fast", cache_key="backend")
    assert c._json_schema_ok is False and c._cache_key_ok is False
    assert "prompt_cache_key" not in seen[-1] and seen[-1]["response_format"] == {"type": "json_object"}


# ---------- 8. SQLite bus: WAL, không bỏ sót event tiến trình khác, handler lỗi không làm mất event ----------

def _other_process(db, action):
    subprocess.run(["python", "-c", "import sys; sys.path.insert(0, 'src');"
                    "from company.sqlite_bus import SQLiteBus; from company.events import Envelope;"
                    f"SQLiteBus({str(db)!r}).publish(Envelope(topic='audit-log', key='x', actor='x', payload={{'actor': 'x', 'action': {action!r}}}))"],
                   check=True, cwd=os.getcwd())


def test_sqlite_bus_poll_sees_foreign_event_interleaved_with_own_publish(tmp_path):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db)
    assert bus._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    _other_process(db, "tien-trinh-khac")  # ghi vào file TRƯỚC khi tiến trình này publish
    bus.publish(Envelope(topic="audit-log", key="k", actor="a", payload={"actor": "a", "action": "cua-minh"}))
    got = [e.payload["action"] for e in bus.poll()]
    assert got == ["tien-trinh-khac"], "lastrowid của mình không được che event seq nhỏ hơn của tiến trình khác"
    assert bus.poll() == [] and [e.payload["action"] for e in bus.replay()][-2:] == ["tien-trinh-khac", "cua-minh"]
    assert len(bus) == 2, "event của mình không bị nạp lại vào log"


def test_sqlite_bus_poll_audits_failing_subscriber_and_continues(tmp_path):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); seen: list[str] = []
    def bad(env): raise RuntimeError("handler hỏng")
    bus.subscribe("audit-log", bad); bus.subscribe("audit-log", lambda e: seen.append(e.payload["action"]))
    _other_process(db, "tu-ngoai")
    assert [e.payload["action"] for e in bus.poll()] == ["tu-ngoai"]
    assert "tu-ngoai" in seen, "handler sau vẫn nhận event dù handler trước ném lỗi"
    err = _audits(bus, "subscriber_error")
    assert len(err) == 1 and "handler hỏng" in err[0]["evidence"]


# ---------- 9. watch: một nhịp lỗi được audit rồi đi tiếp ----------

def test_watch_survives_tick_error(monkeypatch):
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler)); n = {"tick": 0}
    real = orch.tick
    def flaky(now=None):
        n["tick"] += 1
        if n["tick"] == 1: raise RuntimeError("bus tạm lỗi")
        return real(now)
    monkeypatch.setattr(orch, "tick", flaky); monkeypatch.setattr("company.orchestrator.time.sleep", lambda s: None)
    orch.watch(interval=0, max_ticks=3)
    assert n["tick"] == 3
    err = _audits(bus, "tick_error")
    assert len(err) == 1 and "bus tạm lỗi" in err[0]["evidence"]


# ---------- 10. retry nhận ngân sách còn lại ----------

def test_retry_gets_remaining_budget(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler), repo=repo, base="main"); budgets: list[int] = []
    def fake_generate(agent, inp, ws, budget=None, max_turns=25):
        budgets.append(budget)
        # giả lập vòng tool đã đốt 2_000 token rồi lỗi: runner ghi audit (supervisor cộng dồn) và ném RunnerError
        orch.runner._audit(orch.runner.agents[agent], "invalid_output", inp, evidence="x", tokens=2_000)
        raise RunnerError("đầu ra hỏng")
    monkeypatch.setattr(orch.runner, "generate_in_workspace", fake_generate)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert budgets[0] == 6_000 and budgets[1] == 4_000 and budgets[2] == 2_000, "mỗi lần làm lại chỉ còn phần chưa đốt"


# ---------- 11. tool: bỏ symlink, chặn cờ trong paths ----------

def test_tools_skip_symlinks_and_reject_flags_in_paths(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1"); ws.create()
    secret = tmp_path / "ngoai.py"; secret.write_text("TOKEN = 'ngoai worktree'\n", encoding="utf-8")
    try:
        os.symlink(secret, ws.path / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("không tạo được symlink")
    tb = WorkspaceTools(ws).toolbox()
    assert "link.py" not in tb.call(ToolCall(id="1", name="list_files", args={}))
    assert "ngoai worktree" not in tb.call(ToolCall(id="2", name="search", args={"pattern": "TOKEN"}))
    out = tb.call(ToolCall(id="3", name="run", args={"command": "git_status", "paths": ["--output=/tmp/x"]}))
    assert out.startswith("lỗi") and "tuỳ chọn" in out
    out = tb.call(ToolCall(id="4", name="run", args={"command": "git_status", "paths": ["mod.py"]}))
    assert out.startswith("exit=0")
