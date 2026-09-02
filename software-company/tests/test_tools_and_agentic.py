"""ADR-0010: tool có ranh giới tin cậy, vòng lặp tool-use trung lập provider, PR mang bằng chứng do code điền,
eval ghi/phát lại, vòng học hiệu chỉnh ước lượng. Không gọi mạng: client giả + server HTTP cục bộ."""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

import company.evals as evals_mod
from company.bus import InMemoryBus
from company.evals import RecordingClient, ReplayClient, run_eval, stale_recordings
from company.evals import main as evals_main
from company.events import Envelope
from company.llm import AnthropicClient, FakeClient, LLMConfig, LLMError, OpenAICompatClient
from company.orchestrator import Orchestrator, _cycle
from company.runner import AgentRunner, RunnerError
from company.tools import ToolBox, ToolCall, ToolError, ToolSpec, WorkspaceTools, _clean_env
from company.workspace import TicketWorkspace
from test_orchestrator import T1, T2, _agent_of, _drive_to_plan, _inp, _pub, handler


def _init_repo(path: Path) -> Path:
    path.mkdir()
    def git(*a): subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    # dấu hiệu stack python: run_checks chọn ruff+pytest theo đây (ADR-0013)
    (path / "pyproject.toml").write_text('[project]\nname = "khach"\nversion = "0.1.0"\n', encoding="utf-8")
    (path / "mod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (path / "test_mod.py").write_text("from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    (path / ".env").write_text("API_KEY=sk_live_secret\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "init")
    return path


def _task_env(tid="T1", **extra) -> Envelope:
    return Envelope(topic="tasks", key=tid, actor="delivery-lead", payload={**T1, "ticket_id": tid, **extra})


def _tc(name, **args) -> ToolCall:
    return ToolCall(id=f"c-{name}", name=name, args=args)


def _first_turn(msgs) -> bool:
    return not any(m["role"] == "assistant" for m in msgs)


# ---------- ranh giới tool ----------

def test_tools_refuse_paths_outside_worktree_and_secrets(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    for bad in ("../mod.py", "../../etc/passwd", "/etc/passwd", "C:/Windows/win.ini", ".git/config", ".env", "sub/../../x"):
        out = tb.call(_tc("read_file", path=bad))
        assert out.startswith("lỗi"), (bad, out)
    assert tb.call(_tc("write_file", path=".git/hooks/pre-commit", content="x")).startswith("lỗi")
    assert tb.call(_tc("write_file", path="keys/id_rsa", content="x")).startswith("lỗi")
    assert not (ws.path / ".git" / "hooks" / "pre-commit").exists()
    # tìm kiếm không lộ file bí mật dù nội dung khớp
    assert "sk_live" not in tb.call(_tc("search", pattern="sk_live", glob="**/*"))


def test_tools_allowlist_and_argument_validation(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    assert "không trong allowlist" in tb.call(_tc("run", command="rm -rf /"))
    assert "không trong allowlist" in tb.call(_tc("run", command="sh"))
    assert tb.call(_tc("read_file", path="mod.py", shell="ls")).startswith("lỗi tham số")
    assert tb.call(_tc("read_file")).startswith("lỗi tham số")
    with pytest.raises(ToolError, match="không tồn tại"):
        tb.call(_tc("bash", command="ls"))
    assert tb.calls[-1]["name"] == "read_file" and tb.summary() == {"run": 2, "read_file": 2}


def test_read_only_toolbox_has_no_write(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws, allow_write=False).toolbox()
    assert [t.name for t in tb.specs()] == ["read_file", "list_files", "search", "run"]
    with pytest.raises(ToolError):
        tb.call(_tc("write_file", path="x.py", content="1"))


def test_tools_read_write_search_list_run(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    assert tb.call(_tc("write_file", path="pkg/new.py", content="X = 1\n")).startswith("đã tạo")
    assert tb.call(_tc("read_file", path="pkg/new.py")) == "    1\tX = 1"
    assert "pkg/new.py:1: X = 1" in tb.call(_tc("search", pattern="^X"))
    files = tb.call(_tc("list_files")).splitlines()
    assert "mod.py" in files and "pkg/new.py" in files and not any(f.startswith(".git") for f in files)
    assert ".env" not in files
    assert tb.call(_tc("run", command="test")).startswith("exit=0")
    assert tb.call(_tc("run", command="lint", paths=["pkg"])).startswith("exit=0")
    tb.call(_tc("write_file", path="mod.py", content="def add(a, b):\n    return a - b\n"))
    assert tb.call(_tc("run", command="test")).startswith("exit=1")
    assert "mod.py" in tb.call(_tc("run", command="git_status"))


def test_clean_env_drops_keys(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "x"); monkeypatch.setenv("DB_PASSWORD", "y"); monkeypatch.setenv("PATH_X", "z")
    env = _clean_env()
    assert "MY_API_KEY" not in env and "DB_PASSWORD" not in env and env["PATH_X"] == "z"


def test_toolbox_truncates_long_output():
    tb = ToolBox(); tb.add(ToolSpec("big", "", {"type": "object", "properties": {}}), lambda: "x" * 10_000)
    out = tb.call(_tc("big"))
    assert len(out) < 6_100 and "cắt" in out


# ---------- vòng lặp tool-use trong runner ----------

def _pr(p, **extra):
    return {"ticket_id": p["ticket_id"], "branch": "ticket/fake", "pr_ref": "#999", "summary": "đã làm",
            "local_checks": {"lint": True, "tests": True, "coverage": 0.99}, **extra}


def test_tool_loop_runs_tools_then_final_answer(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    def th(msgs, tools):
        if _first_turn(msgs): return [_tc("read_file", path="mod.py"), _tc("write_file", path="feature.py", content="F = 1\n")]
        assert msgs[-1]["role"] == "tool" and msgs[-1]["content"].startswith("đã tạo")
        return []
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    bus = InMemoryBus()
    g = AgentRunner(bus, client).generate("backend", _task_env(), "pull-requests", tools=tb)
    assert (ws.path / "feature.py").read_text(encoding="utf-8") == "F = 1\n"
    assert g.turns == 2 and g.tool_calls == {"read_file": 1, "write_file": 1} and g.tokens == 2 * 1300
    assert [c["tools"] for c in client.calls] == [["read_file", "write_file", "list_files", "search", "run"]] * 2
    assert "# Tool" in client.calls[0]["user"] and "run test" in client.calls[0]["user"]
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert acts == ["tools_used"]


def test_tool_loop_stops_when_budget_exhausted(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: [_tc("read_file", path="mod.py")])
    bus = InMemoryBus()
    with pytest.raises(RunnerError, match="vượt ngân sách"):
        AgentRunner(bus, client).generate("backend", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox(), budget=3_000)
    a = [e.payload for e in bus.replay(topic="audit-log")][-1]
    assert a["action"] == "budget_exhausted" and a["tokens"] == 3 * 1300 and len(client.calls) == 3


def test_tool_loop_max_turns_forces_final_json(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: [_tc("read_file", path="mod.py")])
    g = AgentRunner(InMemoryBus(), client).generate("backend", _task_env(), "pull-requests",
                                                     tools=WorkspaceTools(ws).toolbox(), max_turns=2)
    assert g.turns == 3 and len(client.calls) == 3 and client.calls[-1]["tools"] == []
    last = client.calls[-1]["messages"]
    assert last[-1]["role"] == "user" and "Hết lượt tool" in last[-1]["content"]
    assert last[-2]["role"] == "tool" and "hết lượt" in last[-2]["content"]


def test_tool_error_is_returned_to_model_not_raised(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    seen = []
    def th(msgs, tools):
        if _first_turn(msgs): return [_tc("nope"), _tc("read_file", path="../x")]
        seen.extend(m["content"] for m in msgs if m["role"] == "tool"); return []
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    AgentRunner(InMemoryBus(), client).generate("backend", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox())
    assert seen[0].startswith("lỗi: tool không tồn tại") and "thoát" in seen[1]


# ---------- PR mang bằng chứng do code điền ----------

def test_generate_in_workspace_overrides_model_claims_with_git_evidence(tmp_path):
    repo = _init_repo(tmp_path / "repo"); ws = TicketWorkspace(repo, "T1", base="main")
    def th(msgs, tools):
        return [_tc("write_file", path="feature.py", content="def f():\n    return 1\n"),
                _tc("write_file", path="test_feature.py", content="from feature import f\n\n\ndef test_f():\n    assert f() == 1\n")] \
            if _first_turn(msgs) else []
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    bus = InMemoryBus()
    g = AgentRunner(bus, client).generate_in_workspace("backend", _task_env(title="thêm f"), ws, budget=50_000)
    p = g.payloads[0]
    assert p["branch"] == "ticket/T1" and p["pr_ref"] != "#999" and len(p["pr_ref"]) >= 7
    assert p["local_checks"] == {"lint": True, "tests": True, "verified_by": "workspace", "stack": "python",
                                 "lint_output": p["local_checks"]["lint_output"], "test_output": p["local_checks"]["test_output"]}
    assert "coverage" not in p["local_checks"], "model khai coverage nhưng không đo được → bỏ, không bịa"
    assert p["impact"]["files"] == ["feature.py", "test_feature.py"] and p["summary"] == "đã làm"
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline", "ticket/T1"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "feat(T1): thêm f" in log and "+def f():" in ws.diff()
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert acts == ["tools_used", "local_checks"]


def test_generate_in_workspace_reports_failing_tests_truthfully(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    th = lambda m, t: [_tc("write_file", path="mod.py", content="def add(a, b):\n    return a - b\n")] if _first_turn(m) else []  # noqa: E731
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    p = AgentRunner(InMemoryBus(), client).generate_in_workspace("backend", _task_env(), ws).payloads[0]
    assert p["local_checks"]["tests"] is False and p["local_checks"]["lint"] is True, "model khai tests=true, máy nói false"


def test_generate_in_workspace_rejects_pr_without_changes(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: [_tc("read_file", path="mod.py")] if _first_turn(m) else [])
    bus = InMemoryBus()
    with pytest.raises(RunnerError, match="không sửa file"):
        AgentRunner(bus, client).generate_in_workspace("backend", _task_env(), ws)
    assert [e.payload["action"] for e in bus.replay(topic="audit-log")] == ["tools_used", "invalid_output"]


# ---------- orchestrator với repo thật ----------

def _repo_tool_handler(msgs, tools):
    names = {t.name for t in tools}
    if "write_file" in names and _first_turn(msgs):
        tid = _inp(msgs[0]["content"])["ticket_id"]
        return [_tc("write_file", path=f"f_{tid.lower()}.py", content=f"def {tid.lower()}():\n    return 1\n")]
    if "write_file" not in names and _first_turn(msgs):
        return [_tc("run", command="test")]  # QA tự chạy test bằng tool chỉ đọc
    return []


def test_orchestrator_with_repo_produces_verified_prs_and_reviewers_read_diff(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.lead.state["T1"] == "merged" and orch.lead.state["T2"] == "merged" and orch.stats["errors"] == 0
    prs = {e.key: e.payload for e in bus.replay(topic="pull-requests")}
    assert set(prs) == {"T1", "T2"}
    for tid, p in prs.items():
        assert p["local_checks"]["verified_by"] == "workspace" and p["local_checks"]["tests"] is True
        assert p["branch"] == f"ticket/{tid}" and p["impact"]["files"] == [f"f_{tid.lower()}.py"]
        assert (repo / ".worktrees" / tid / f"f_{tid.lower()}.py").exists()
    by_agent = {}
    for c in client.calls: by_agent.setdefault(_agent_of(c["system"]), []).append(c)
    rev = _inp(by_agent["reviewer"][0]["user"])
    assert "+def t1():" in rev["diff"] and rev["changed_files"] == ["f_t1.py"], "reviewer đọc diff thật"
    sec_pr = [c for c in by_agent["security-engineer"] if _inp(c["user"]).get("branch")]
    assert len(sec_pr) == 1 and "+def t2():" in _inp(sec_pr[0]["user"])["diff"], "security review PR T2 (risk_tags) đọc diff"
    qa_pr = [c for c in by_agent["qa-debugger"] if c["tools"]]
    assert qa_pr and all(c["tools"] == ["read_file", "list_files", "search", "run"] for c in qa_pr), "QA có tool chỉ đọc"
    assert any(m["role"] == "tool" and m["content"].startswith("exit=0") for c in qa_pr for m in c["messages"])
    assert not by_agent["reviewer"][0]["tools"], "reviewer chỉ đọc diff, không tool"
    assert orch.supervisor.sprint_report()["prs_unverified"] == 0


def test_orchestrator_without_repo_marks_prs_unverified():
    bus = InMemoryBus(); client = FakeClient(handler=handler); orch = Orchestrator(bus, client)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    prs = [e.payload for e in bus.replay(topic="pull-requests")]
    assert prs and all(p["local_checks"] == {"unverified": True} for p in prs), "lời khai của model không thành bằng chứng"
    a = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "local_checks.unverified"]
    assert len(a) == 2 and json.loads(a[0]["evidence"])["claimed"] == {"lint": True, "tests": True}
    assert orch.supervisor.sprint_report()["prs_unverified"] == 2
    assert "diff" not in _inp(next(c for c in client.calls if _agent_of(c["system"]) == "reviewer")["user"])


def test_orchestrator_rejects_non_git_repo(tmp_path):
    with pytest.raises(ValueError, match="git repository"):
        Orchestrator(InMemoryBus(), FakeClient(), repo=tmp_path)


def test_engineering_failure_in_workspace_is_audited_and_loop_continues(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=lambda m, t: []), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    # Agent không sửa file → invalid_output → ticket KHÔNG treo dispatched: retry kèm hint tới khi blocked → gate escalation
    assert not list(bus.replay(topic="pull-requests")) and orch.lead.state["T1"] == "blocked" and orch.stats["errors"] >= 3
    assert any(e.payload["action"] == "invalid_output" and "không có thay đổi" in e.payload["evidence"] for e in bus.replay(topic="audit-log"))
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert [t["retry"] for t in tasks] == [0, 1, 2] and all("lần trước lỗi" in t["hint"] for t in tasks[1:])
    assert orch.gate.pending["T1"].kind == "escalation"


# ---------- lập kế hoạch: chu trình, hiệu chỉnh ước lượng ----------

def test_cycle_detection():
    assert _cycle({"a": ["b"], "b": ["c"], "c": ["a"]}) == ["a", "b", "c", "a"]
    assert _cycle({"a": ["b"], "b": []}) == [] and _cycle({}) == []


def test_plan_with_dependency_cycle_is_rejected_before_gate():
    def cyc(system, user):
        if _agent_of(system) == "delivery-lead":
            return {"items": [{**T1, "depends_on": ["T2"]}, {**T2, "depends_on": ["T1"]}]}
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=cyc))
    _pub(bus, "approved-specs", "P1", "spec-writer", {"project_id": "P1", "status": "pending_human", "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
    orch.run(); orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    rej = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "plan_rejected"]
    assert rej and any("vòng" in p for p in rej[0]["problems"]) and not orch.plans


def test_lessons_calibrate_next_plan():
    bus = InMemoryBus(); client = FakeClient(handler=handler); orch = Orchestrator(bus, client)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:rm"); orch.run()
    assert orch.supervisor.calibration() == {}, "chưa nghiệm thu thì chưa có bài học"
    _pub(bus, "acceptance-results", "REL-001", "account-manager",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    cal = orch.supervisor.calibration()
    assert cal == {"backend": {"ratio_median": cal["backend"]["ratio_median"], "samples": 1}} and cal["backend"]["ratio_median"] > 0
    # dự án tiếp theo: delivery-lead nhận bảng hiệu chỉnh trong đầu vào
    _pub(bus, "approved-specs", "P2", "spec-writer", {"project_id": "P2", "status": "pending_human", "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
    orch.run(); orch.gate.decide("SPEC-P2", "approve", by="human:po"); orch.run()
    lead_calls = [c for c in client.calls if _agent_of(c["system"]) == "delivery-lead" and "P2" in c["user"]]
    assert lead_calls and _inp(lead_calls[-1]["user"])["estimate_calibration"] == cal
    # khôi phục từ bus: bài học đọc lại được từ shared-context, không chỉ bộ nhớ
    assert Orchestrator(bus, FakeClient()).supervisor.calibration() == cal
    rep = orch.supervisor.sprint_report()
    assert rep["calibration"] == cal and rep["rework_rate"] == 0.0 and rep["review_catch_rate"] == 0.0


# ---------- eval ghi / phát lại ----------

def _reviewer_handler(system, user):
    tid = _inp(user)["ticket_id"]; blocked = "sk_live" in user
    return {"ticket_id": tid, "source": "reviewer", "verdict": "block" if blocked else "pass",
            "findings": [{"level": "block", "text": "hard-coded secret"}] if blocked else []}


def test_eval_record_then_replay_without_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    with pytest.raises(LLMError, match="chưa có bản ghi"):
        ReplayClient("reviewer")
    rec = RecordingClient(FakeClient(handler=_reviewer_handler, tokens_per_call=(500, 40)), "reviewer")
    assert all(r.passed for r in run_eval("reviewer", rec))
    path = rec.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["agent"] == "reviewer" and data["prompt_version"] >= 1 and len(data["cases"]) == 2 and data["models"] == ["fake-strong"]
    res = run_eval("reviewer", ReplayClient("reviewer"))
    assert [r.passed for r in res] == [True, True] and all(r.tokens == 540 for r in res)
    assert stale_recordings(["reviewer"]) == {}
    # prompt đổi (mô phỏng: khoá trong bản ghi không còn khớp) → lệch, replay báo rõ phải ghi lại
    data["cases"] = {"stale": next(iter(data["cases"].values()))}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert list(stale_recordings(["reviewer"])) == ["reviewer"] and len(stale_recordings(["reviewer"])["reviewer"]) == 2
    bad = run_eval("reviewer", ReplayClient("reviewer"))
    assert not bad[0].passed and "lệch prompt" in bad[0].failures[0]
    # CLI: --replay bỏ qua agent chưa ghi (exit 0); --strict chỉ đỏ với agent có tên trong REQUIRED.txt
    assert evals_main(["backend", "--replay"]) == 0 and "SKIP backend" in capsys.readouterr().out
    assert evals_main(["backend", "--replay", "--strict"]) == 0, "chưa bắt buộc thì vẫn chỉ là SKIP"
    capsys.readouterr()
    (tmp_path / "REQUIRED.txt").write_text("# bắt buộc\nbackend\n", encoding="utf-8")
    assert evals_main(["backend", "--replay", "--strict"]) == 1
    assert "FAIL backend" in capsys.readouterr().out
    assert evals_main(["reviewer", "--replay"]) == 1


def test_committed_recordings_match_current_prompts():
    """CI: mọi bản ghi trong evals/recordings/ phải khớp prompt/skill/ca eval hiện tại. Lệch → ghi lại bằng model thật."""
    stale = stale_recordings()
    assert stale == {}, {a: f"chạy `make eval-record AGENT={a}` rồi commit evals/recordings/{a}.json (ca lệch: {c})"
                         for a, c in stale.items()}


# ---------- adapter provider: tool-use ----------

class _ToolSrv(BaseHTTPRequestHandler):
    """Server OpenAI-compatible giả: lượt 1 trả tool_call, lượt 2 trả JSON cuối."""
    seen: ClassVar[list[dict]] = []
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(body)
        has_tool_msg = any(m["role"] == "tool" for m in body["messages"])
        msg = ({"role": "assistant", "content": '{"ticket_id": "T1", "source": "reviewer", "verdict": "pass"}'} if has_tool_msg else
               {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                   "name": "read_file", "arguments": '{"path": "mod.py"}'}}]})
        out = {"model": "local", "choices": [{"message": msg, "finish_reason": "stop" if has_tool_msg else "tool_calls"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass


def test_openai_compat_tool_calls_roundtrip():
    _ToolSrv.seen.clear()
    srv = HTTPServer(("127.0.0.1", 0), _ToolSrv); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = LLMConfig(provider="openai", models={"strong": "m", "standard": "m"}, base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k")
        client = OpenAICompatClient(cfg)
        tools = [ToolSpec("read_file", "đọc", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})]
        schema = {"type": "object", "properties": {"ticket_id": {"type": "string"}}}
        c1 = client.complete(system="s", user="u", schema=schema, model_tier="strong", tools=tools)
        assert [(t.id, t.name, t.args) for t in c1.tool_calls] == [("call_1", "read_file", {"path": "mod.py"})] and c1.stop_reason == "tool_calls"
        msgs = [{"role": "user", "content": "u"}, {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "read_file", "args": {"path": "mod.py"}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "1\tx"}]
        c2 = client.complete(system="s", user="u", schema=schema, model_tier="strong", tools=tools, messages=msgs)
        assert not c2.tool_calls and c2.json()["verdict"] == "pass" and c2.tokens == 15
    finally:
        srv.shutdown()
    req1, req2 = _ToolSrv.seen
    assert req1["tools"][0]["function"]["name"] == "read_file" and req1["messages"][-1] == {"role": "user", "content": "u"}
    assert req2["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"path": "mod.py"}'
    assert req2["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "1\tx"}


def test_anthropic_message_conversion_groups_tool_results():
    msgs = [{"role": "user", "content": "u"},
            {"role": "assistant", "content": "đọc đã", "tool_calls": [{"id": "a", "name": "read_file", "args": {"path": "x"}},
                                                                      {"id": "b", "name": "search", "args": {"pattern": "y"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "1"}, {"role": "tool", "tool_call_id": "b", "content": "2"}]
    out = AnthropicClient._messages(msgs)
    assert out[0] == {"role": "user", "content": "u"}
    assert [b["type"] for b in out[1]["content"]] == ["text", "tool_use", "tool_use"] and out[1]["content"][1]["input"] == {"path": "x"}
    assert out[2]["role"] == "user" and [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"], "hai tool_result gộp một lượt user"


def test_required_recordings_exist_and_match_prompt_version():
    """Agent có tên trong evals/recordings/REQUIRED.txt phải có bản ghi tươi (ADR-0010)."""
    from company.evals import load_recording, outdated_versions, required_agents

    missing = [a for a in required_agents() if load_recording(a) is None]
    assert not missing, f"thiếu bản ghi eval: {missing} — chạy make eval-record cho từng agent"
    assert outdated_versions(required_agents()) == {}


def test_checks_follow_repo_stack_and_never_fake_pass(tmp_path):
    """ADR-0013: lệnh lint/test theo stack của repo khách; không nhận ra stack thì nói thẳng, không báo pass."""
    from company.stacks import detect

    (tmp_path / "node").mkdir()
    (tmp_path / "node" / "package.json").write_text('{"scripts": {"lint": "eslint .", "test": "vitest"}}', encoding="utf-8")
    assert detect(tmp_path / "node").name == "node"
    assert detect(tmp_path / "node").lint[:2] == ["npm", "run"]

    (tmp_path / "node-bare").mkdir()
    (tmp_path / "node-bare" / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    bare = detect(tmp_path / "node-bare")
    assert bare.name == "node" and bare.lint is None and bare.test is None, "không có script thì không giả vờ chạy được"

    for marker, name in (("go.mod", "go"), ("Cargo.toml", "rust"), ("pom.xml", "maven"), ("build.gradle", "gradle")):
        d = tmp_path / name; d.mkdir(); (d / marker).write_text("x", encoding="utf-8")
        assert detect(d).name == name

    (tmp_path / "tron").mkdir()
    assert detect(tmp_path / "tron").name == "unknown"

    repo = _init_repo(tmp_path / "khach")  # repo python: tool `run` có lint/test; stack lạ thì chỉ còn lệnh git
    ws = TicketWorkspace(repo, "T-STACK", base="main"); ws.create()
    assert set(WorkspaceTools(ws).COMMANDS) == {"lint", "test", "git_status", "git_diff"}
    (ws.path / "pyproject.toml").unlink()
    assert set(WorkspaceTools(ws).COMMANDS) == {"git_status", "git_diff"}
    checks = ws.run_checks()
    assert checks["stack"] == "unknown" and checks["lint"] is False and checks["tests"] is False


# ---------- F3/F6 (báo cáo mô phỏng donghanhcungban 2026-09-02) ----------

def test_staging_qa_gets_read_only_tools_on_integration_worktree(tmp_path):
    """F3: QA hồi quy sau deploy staging trước đây không có tool, verdict chỉ là lời khai."""
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.lead.releases == ["REL-001", "REL-002"] and orch.stats["errors"] == 0
    staging_qa = [c for c in client.calls if _agent_of(c["system"]) == "qa-debugger" and _inp(c["user"]).get("release_id")]
    assert staging_qa and all(c["tools"] == ["read_file", "list_files", "search", "run"] for c in staging_qa)
    ran = [m["content"] for c in staging_qa for m in c["messages"] if m["role"] == "tool"]
    assert ran and all(x.startswith("exit=0") for x in ran), "QA tự chạy test trên worktree tích hợp"
    assert not any(e.payload["action"] == "review.no_tool_evidence" for e in bus.replay(topic="audit-log"))


def test_reviewer_with_tools_but_no_calls_is_audited(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    lazy = lambda msgs, tools: _repo_tool_handler(msgs, tools) if "write_file" in {t.name for t in tools} else []  # noqa: E731
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=lazy), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    lazy_qa = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "review.no_tool_evidence"]
    assert lazy_qa and all(a["agent"] == "qa-debugger" for a in lazy_qa)
    assert {a["topic"] for a in lazy_qa} == {"pull-requests", "release-events"}


def test_pr_with_failing_local_checks_goes_back_to_ticket_not_to_review(tmp_path):
    """F6: test thật đỏ → không publish PR, không tốn reviewer/QA/security; ticket retry+1 với hint là đầu ra test."""
    repo = _init_repo(tmp_path / "repo")
    def th(msgs, tools):
        if "write_file" not in {t.name for t in tools} or not _first_turn(msgs): return _repo_tool_handler(msgs, tools)
        p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
        body = "    return 1\n" if p.get("retry", 0) >= 1 or tid != "T1" else "    return 2\n"  # T1 lần đầu sai
        return [_tc("write_file", path=f"f_{tid.lower()}.py", content=f"def {tid.lower()}():\n{body}"),
                _tc("write_file", path=f"test_{tid.lower()}.py", content=f"from f_{tid.lower()} import {tid.lower()}\n\n\ndef test_x():\n    assert {tid.lower()}() == 1\n")]
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=th)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.lead.state["T1"] == "merged" and orch.stats["errors"] == 0
    prs = [e.payload for e in bus.replay(topic="pull-requests") if e.key == "T1"]
    assert len(prs) == 1 and prs[0]["local_checks"]["tests"] is True, "PR đỏ không được publish"
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert [t["retry"] for t in tasks] == [0, 1] and "tests local fail" in tasks[1]["hint"] and "assert" in tasks[1]["hint"]
    rej = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "pr.rejected_local_checks"]
    assert rej == [{"ticket_id": "T1", "agent": "backend", "failed": ["tests"], "commit": rej[0]["commit"], "files": ["f_t1.py", "test_t1.py"]}]
    reviews_t1 = [e for e in bus.replay(topic="review-results") if e.key == "T1"]
    assert {e.payload["source"] for e in reviews_t1} == {"reviewer", "qa"} and len(reviews_t1) == 2, "chỉ review PR xanh"
    assert orch.supervisor.sprint_report()["tickets"]["T1"]["retry"] == 1
    assert orch.supervisor.budgets["T1"].used >= 2 * 1300, "token của lần đỏ vẫn được tính vào ticket"


def test_retry_that_rewrites_identical_files_is_no_change_not_commit_error(tmp_path):
    """F12: sau PR bị từ chối (commit đã nằm trên branch), lần làm lại ghi y hệt → 'không sửa file', không phải lỗi git."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    same = [_tc("write_file", path="mod.py", content="def add(a, b):\n    return a - b\n")]
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: same if _first_turn(m) else [])
    bus = InMemoryBus(); runner = AgentRunner(bus, client)
    assert runner.generate_in_workspace("backend", _task_env(), ws).payloads[0]["local_checks"]["tests"] is False
    with pytest.raises(RunnerError, match="không sửa file"):
        runner.generate_in_workspace("backend", _task_env(retry=1, hint="test đỏ"), ws)
    assert ws.has_changes() and not ws.dirty()
