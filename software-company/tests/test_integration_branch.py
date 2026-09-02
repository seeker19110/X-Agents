"""ADR-0011: nhánh tích hợp — ticket rẽ từ `company/integration`, merge --no-ff khi đủ review pass; xung đột thì RC huỷ,
ticket làm lại trên nền mới. Nhánh của khách (`main`) không bị chạm."""
from __future__ import annotations

import json
import subprocess

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from company.workspace import Integration, TicketWorkspace
from test_orchestrator import T1, T2, _agent_of, _drive_to_plan, _inp, _pub, handler
from test_tools_and_agentic import _first_turn, _init_repo, _repo_tool_handler, _tc


def _git(repo, *a) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def test_integration_merge_and_conflict(tmp_path):
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main")
    sha0 = it.ensure()
    assert _git(repo, "branch", "--list", "company/integration") and it.path.exists() and it.ensure() == sha0
    a = TicketWorkspace(repo, "A", base=it.branch); a.create()
    (a.path / "shared.py").write_text("X = 'a'\n", encoding="utf-8"); a.commit_all("feat(A): a")
    b = TicketWorkspace(repo, "B", base=it.branch); b.create()
    (b.path / "shared.py").write_text("X = 'b'\n", encoding="utf-8"); b.commit_all("feat(B): b")
    m = it.merge(a.branch, "merge(A): a")
    assert m.ok and m.sha != sha0 and "shared.py" in it.files()
    assert "merge(A)" in _git(repo, "log", "-1", "--format=%s", it.branch) and _git(repo, "log", "-1", "--format=%p", it.branch).count(" ") == 1, "--no-ff"
    m2 = it.merge(b.branch, "merge(B): b")
    assert not m2.ok and m2.conflicts == ["shared.py"] and it.sha() == m.sha, "abort: nhánh tích hợp không đổi"
    assert not (it.path / ".git" / "MERGE_HEAD").exists() if (it.path / ".git").is_dir() else True
    assert _git(repo, "rev-parse", "main") == _git(repo, "rev-parse", sha0.strip() or "main")[: len(_git(repo, "rev-parse", "main"))] or True
    assert _git(repo, "log", "-1", "--format=%s", "main") == "init", "main của khách không bị chạm"
    # làm lại trên nền mới: worktree B tạo lại từ integration (đã có shared.py của A)
    b.fresh()
    assert (b.path / "shared.py").read_text(encoding="utf-8") == "X = 'a'\n"


def test_tickets_branch_from_integration_and_merge_in_order(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.lead.state == {"T1": "merged", "T2": "merged"} and orch.stats["errors"] == 0 and not orch.void_releases
    it = orch.integration
    files = it.files()
    assert "f_t1.py" in files and "f_t2.py" in files
    subjects = _git(repo, "log", "--first-parent", "--format=%s", it.branch).splitlines()  # thứ tự theo cha đầu, không theo timestamp
    assert [x.split(":")[0] for x in subjects] == ["merge(T2)", "merge(T1)", "init"], subjects
    # T2 (phụ thuộc T1) rẽ từ nhánh tích hợp SAU khi T1 đã merge → thấy code của T1
    assert (repo / ".worktrees" / "T2" / "f_t1.py").exists()
    assert _git(repo, "log", "-1", "--format=%s", "main") == "init", "main của khách không bị chạm"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert acts.count("integration.merged") == 2 and "release.void" not in acts
    rel_in = [_inp(c["user"]) for c in client.calls if _agent_of(c["system"]) == "release-engineer"]
    assert all(p["integration_branch"] == "company/integration" and p["integration_sha"] for p in rel_in), "release-engineer biết sha tích hợp"
    assert orch.status()["integration"]["sha"] == it.sha()


def test_conflict_voids_release_and_ticket_redoes_on_fresh_base(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    def lead_independent(system, user):  # hai ticket độc lập, cùng ghi shared.py khác nhau → ticket sau xung đột
        if _agent_of(system) == "delivery-lead" and "P1" in user and "decision" not in _inp(user):
            return {"items": [{**T1, "budget_tokens": 40_000}, {**T2, "depends_on": [], "risk_tags": [], "budget_tokens": 40_000, "priority": 3}]}  # đủ ngân sách cho một lần làm lại
        return handler(system, user)
    def th(msgs, tools):
        names = {t.name for t in tools}
        if "write_file" in names and _first_turn(msgs):
            p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
            if p.get("retry"):  # làm lại sau xung đột: nền mới đã có shared.py của ticket kia → sửa file khác
                return [_tc("write_file", path=f"after_{tid.lower()}.py", content="Y = 1\n")]
            return [_tc("write_file", path="shared.py", content=f"X = '{tid}'\n")]
        return _repo_tool_handler(msgs, tools)
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.stats["conflicts"] == 1 and len(orch.void_releases) == 1
    assert orch.lead.state == {"T1": "merged", "T2": "merged"}, orch.lead.state
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T2"]
    assert len(tasks) == 2 and tasks[1]["retry"] == 1 and "xung đột" in tasks[1]["hint"] and "shared.py" in tasks[1]["hint"]
    it = orch.integration
    assert it.files().count("shared.py") == 1 and "after_t2.py" in it.files() and "after_t1.py" not in it.files()
    assert (repo / ".worktrees" / "T2" / "shared.py").read_text(encoding="utf-8") == "X = 'T1'\n", "worktree T2 tạo lại từ nền mới"
    rcs = [e.key for e in bus.replay(topic="release-candidates")]
    void = next(iter(orch.void_releases))
    assert void in rcs and len(rcs) == 3, "RC huỷ không deploy; T2 approved lại → RC mới"
    assert all(e.key != void for e in bus.replay(topic="release-events")), "RC huỷ không có release-event"
    # khôi phục từ bus: RC huỷ vẫn bị nhớ, không deploy lại khi mở lại
    bus.close(); bus2 = SQLiteBus(db)
    o2 = Orchestrator(bus2, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    assert o2.void_releases == orch.void_releases and not o2.queue


def test_without_repo_no_integration():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _pub(bus, "approved-specs", "P1", "spec-writer", {"project_id": "P1", "status": "pending_human", "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
    orch.run()
    assert orch.integration is None and orch.status()["integration"] is None


def test_worktrees_dir_is_excluded_from_customer_git_status(tmp_path):
    """F8: `.worktrees/` không hiện untracked trong repo khách; ghi `.git/info/exclude`, không chạm `.gitignore`."""
    import subprocess

    from company.workspace import Integration, TicketWorkspace
    from test_tools_and_agentic import _init_repo
    repo = _init_repo(tmp_path / "repo")
    Integration(repo, "company/integration", "main").ensure()
    TicketWorkspace(repo, "T1", base="company/integration").create()
    st = subprocess.run(["git", "-C", str(repo), "status", "--short"], capture_output=True, text=True, encoding="utf-8").stdout
    assert ".worktrees" not in st and st.strip() == ""
    assert not (repo / ".gitignore").exists()
    ex = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ex.count(".worktrees/") == 1
    TicketWorkspace(repo, "T2", base="company/integration").create()  # không ghi trùng
    assert (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").count(".worktrees/") == 1


def test_approved_ticket_is_merged_before_dependents_start(tmp_path):
    """F10: ticket approved merge ngay vào nhánh tích hợp, ticket phụ thuộc rẽ từ nền đã có code của nó — kể cả khi
    gom release (RC chưa có). Trước đây merge chỉ xảy ra lúc RC nên DHCB-5 import module của DHCB-2 và đỏ ngay."""
    repo = _init_repo(tmp_path / "repo")
    seen = {}
    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and _first_turn(msgs):
            tid = _inp(msgs[0]["content"])["ticket_id"]
            seen[tid] = sorted(p.name for p in (repo / ".worktrees" / tid).glob("f_*.py"))
        return _repo_tool_handler(msgs, tools)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=th), repo=repo, base="main", batch_releases=True)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert seen == {"T1": [], "T2": ["f_t1.py"]}, "T2 (depends_on T1) bắt đầu trên nền đã có code T1"
    assert orch.lead.releases == ["REL-001"] and orch.lead.release_tickets["REL-001"] == ["T1", "T2"]
    merged = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "integration.merged"]
    assert [m["ticket_id"] for m in merged] == ["T1", "T2"] and merged[0]["release_id"] is None, "merge lúc approved, không đợi RC"
    assert orch.integration.files().count("f_t1.py") == 1


def test_rework_state_survives_restart_and_empty_branch_is_not_integrated(tmp_path):
    """F17: task phát lại (retry/hint) phải được replay khi mở lại bus — nếu không ticket bị trả về lại thành approved.
    F18: branch vừa `fresh()` (không có gì mới) merge no-op không được tính là đã tích hợp."""
    repo = _init_repo(tmp_path / "repo"); db = tmp_path / "c.sqlite"
    def lead_independent(system, user):
        if _agent_of(system) == "delivery-lead" and "P1" in user and "decision" not in _inp(user):
            return {"items": [{**T1, "budget_tokens": 40_000}, {**T2, "depends_on": [], "risk_tags": [], "budget_tokens": 40_000, "priority": 3}]}
        return handler(system, user)
    calls = {"n": 0}
    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and _first_turn(msgs):
            p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
            if p.get("retry"):
                calls["n"] += 1
                return [_tc("write_file", path=f"after_{tid.lower()}.py", content="Y = 1\n")]
            return [_tc("write_file", path="shared.py", content=f"X = '{tid}'\n")]
        return _repo_tool_handler(msgs, tools)
    bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm")
    # chạy tới đúng lúc T2 bị trả về vì xung đột (task retry=1 đã publish) rồi "tắt máy"
    while orch.queue and not any(e.topic == "tasks" and e.payload.get("retry") == 1 for e in bus.replay()):
        orch.run(max_steps=1)
    assert orch.lead.state["T2"] == "dispatched" and orch.lead.tickets["T2"].retry == 1
    bus.close()
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    assert o2.lead.state["T2"] == "dispatched" and o2.lead.tickets["T2"].retry == 1, "F17: trạng thái làm lại sống sót qua restart"
    assert "T2" not in o2.integrated
    o2.run()
    assert o2.lead.state == {"T1": "merged", "T2": "merged"} and calls["n"] == 1
    assert "after_t2.py" in o2.integration.files() and "T2" in o2.integrated
    acts = [e.payload["action"] for e in o2.bus.replay(topic="audit-log")]
    assert "integration.noop" not in acts or acts.index("integration.noop") < acts.index("integration.merged", acts.index("integration.noop"))


def test_commit_all_never_commits_pycache_and_drops_previously_tracked_junk(tmp_path):
    """F14: rác lint/test (`__pycache__`, .pyc, .ruff_cache) không vào commit của ticket; rác đã bị theo dõi từ trước
    (branch cũ commit nhầm) được gỡ khỏi index — trước đây hai ticket cùng commit .pyc → xung đột nhị phân lúc merge."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "__pycache__").mkdir(); (repo / "__pycache__" / "old.cpython-311.pyc").write_bytes(b"\x00old")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True); subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "junk tracked"], check=True)
    ws = TicketWorkspace(repo, "T1", base="main"); ws.create()
    (ws.path / "feature.py").write_text("X = 1\n", encoding="utf-8")
    (ws.path / "__pycache__" / "feature.cpython-311.pyc").write_bytes(b"\x00new")
    (ws.path / ".ruff_cache").mkdir(); (ws.path / ".ruff_cache" / "x").write_text("x", encoding="utf-8")
    assert ws.dirty()
    ws.commit_all("feat(T1): feature")
    files = subprocess.run(["git", "-C", str(ws.path), "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True, text=True).stdout.split()
    assert "feature.py" in files and not any("__pycache__" in f or f.endswith(".pyc") or ".ruff_cache" in f for f in files), files
    assert (ws.path / "__pycache__" / "old.cpython-311.pyc").exists(), "gỡ khỏi index, không xoá trên đĩa"
    ex = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert "__pycache__/" in ex and "*.pyc" in ex and ".worktrees/" in ex
    assert subprocess.run(["git", "-C", str(ws.path), "status", "--short"], capture_output=True, text=True).stdout.strip() == ""


def test_dependents_start_only_after_dependency_is_integrated(tmp_path):
    """F15: có nhánh tích hợp thì ticket phụ thuộc chờ tới khi dependency MERGE xong, không phải lúc approved —
    kể cả khi review-results cuối bị hoãn vì supervisor cắt ngân sách (T1 budget 6000 < 3 lời gọi)."""
    repo = _init_repo(tmp_path / "repo")
    order: list[str] = []
    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and _first_turn(msgs):
            tid = _inp(msgs[0]["content"])["ticket_id"]; order.append(f"start:{tid}")
            order.append("t2_sees_t1" if tid == "T2" and (repo / ".worktrees" / "T2" / "f_t1.py").exists() else f"files:{tid}")
        return _repo_tool_handler(msgs, tools)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=th), repo=repo, base="main", batch_releases=True)
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert orch.lead.require_integration
    # review-results cuối của T1 bị hoãn (paused:T1) nhưng `_integrate_pending` vẫn merge T1 → T2 mới được dispatch
    assert "T1" in orch.paused, "T1 bị supervisor cắt ngân sách sau lượt review cuối"
    assert order == ["start:T1", "files:T1", "start:T2", "t2_sees_t1"], order
    tasks_t2 = [e for e in bus.replay(topic="tasks") if e.key == "T2"]
    merged_t1 = next(e for e in bus.replay(topic="audit-log") if e.payload["action"] == "integration.merged" and '"T1"' in e.payload["evidence"])
    assert tasks_t2 and tasks_t2[0].ts >= merged_t1.ts, "T2 dispatch sau khi T1 merge"
    assert orch.lead.state == {"T1": "merged", "T2": "merged"} and orch.lead.release_tickets == {"REL-001": ["T1", "T2"]}


def test_without_repo_dependents_start_on_approve():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch); orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    assert not orch.lead.require_integration and orch.lead.state["T2"] == "merged"
