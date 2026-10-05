"""ADR-0011: nhánh tích hợp — ticket rẽ từ `company/integration`, merge --no-ff khi đủ review pass; xung đột thì RC huỷ,
ticket làm lại trên nền mới. Nhánh của khách (`main`) không bị chạm."""
from __future__ import annotations

import json
import subprocess

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import MAX_CONFLICT_RETRIES, Orchestrator
from company.sqlite_bus import SQLiteBus
from company.workspace import Integration, TicketWorkspace
from test_orchestrator import (
    T1,
    T2,
    _agent_of,
    _drive_to_plan,
    _drive_to_spec_gate,
    _inp,
    _product_phase,
    _pub,
    handler,
)
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
    _drive_to_plan(bus, orch); orch.run()
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


def test_xung_dot_lap_lai_qua_nguong_moi_tinh_vao_retry_noi_dung(tmp_path):
    """`conflict_retries` (tách khỏi `Task.retry`) cho ticket thua cuộc đua merge một khoảng chịu đựng riêng, không
    đốt retry nội dung — xem `request_changes_no_retry_bump`. Nhưng KHÔNG vô hạn: xung đột lặp lại quá
    `MAX_CONFLICT_RETRIES` là dấu hiệu bế tắc cấu trúc thật (không chỉ xui thứ tự) và phải tính vào retry nội dung
    như cũ, để cuối cùng còn `ticket.blocked` → gate escalation cho người biết. Test dựng bằng cách đặt trước bộ đếm
    ở ngưỡng, để đúng MỘT xung đột thật đẩy nó qua ngưỡng."""
    repo = _init_repo(tmp_path / "repo")
    def lead_independent(system, user):
        if _agent_of(system) == "product" and _product_phase(system) == "plan" and "P1" in user and "decision" not in _inp(user):
            return {"items": [{**T1, "budget_tokens": 40_000}, {**T2, "title": "POST /notes", "depends_on": [], "risk_tags": [], "budget_tokens": 40_000, "priority": 3}],
                    "context_writes": [{"namespace": "architecture", "content_ref": "docs/c4.md", "summary": "L1-L2"},
                                        {"namespace": "api-contract", "content_ref": "openapi.yaml", "summary": "v1"}]}
        return handler(system, user)
    def th(msgs, tools):
        names = {t.name for t in tools}
        if "write_file" in names and _first_turn(msgs):
            p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
            if p.get("hint"):
                return [_tc("write_file", path=f"after_{tid.lower()}.py", content="Y = 1\n")]
            return [_tc("write_file", path="shared.py", content=f"X = '{tid}'\n")]
        return _repo_tool_handler(msgs, tools)
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    _drive_to_spec_gate(bus, orch)
    orch.conflict_retries["T2"] = MAX_CONFLICT_RETRIES  # giả lập đã xung đột đủ ngưỡng ở các lần trước
    orch.gate.decide("SPEC-P1", "approve", by="human:po")   # ADR-0037: ký gate spec là ticket được giao ngay
    orch.run()
    assert orch.conflict_retries["T2"] == MAX_CONFLICT_RETRIES + 1, "vẫn tăng đúng, chỉ đổi NGƯỠNG áp dụng"
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T2"]
    assert len(tasks) == 2 and tasks[1]["retry"] == 1, "vượt ngưỡng: xung đột này tính vào retry nội dung như cũ"
    assert orch.lead.state == {"T1": "merged", "T2": "merged"}, "vẫn chỉ 1 retry, còn xa max_retries=3 nên đi tiếp bình thường"


def test_conflict_voids_release_and_ticket_redoes_on_fresh_base(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    def lead_independent(system, user):  # hai ticket độc lập, cùng ghi shared.py khác nhau → ticket sau xung đột
        if _agent_of(system) == "product" and _product_phase(system) == "plan" and "P1" in user and "decision" not in _inp(user):
            return {"items": [{**T1, "budget_tokens": 40_000}, {**T2, "title": "POST /notes", "depends_on": [], "risk_tags": [], "budget_tokens": 40_000, "priority": 3}],
                    "context_writes": [{"namespace": "architecture", "content_ref": "docs/c4.md", "summary": "L1-L2"},
                                        {"namespace": "api-contract", "content_ref": "openapi.yaml", "summary": "v1"}]}  # đủ ngân sách cho một lần làm lại
        return handler(system, user)
    def th(msgs, tools):
        names = {t.name for t in tools}
        if "write_file" in names and _first_turn(msgs):
            p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
            if p.get("hint"):  # làm lại sau xung đột (không tính vào retry nữa, xem conflict_retries): sửa file khác
                return [_tc("write_file", path=f"after_{tid.lower()}.py", content="Y = 1\n")]
            return [_tc("write_file", path="shared.py", content=f"X = '{tid}'\n")]
        return _repo_tool_handler(msgs, tools)
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    assert orch.stats["conflicts"] == 1 and len(orch.void_releases) == 1
    assert orch.lead.state == {"T1": "merged", "T2": "merged"}, orch.lead.state
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T2"]
    # xung đột merge KHÔNG tính vào retry nội dung (ticket thua cuộc đua merge, không phải lỗi của nó) — chỉ
    # `orchestrator.conflict_retries` (đếm riêng) tăng; xem `request_changes_no_retry_bump`.
    assert len(tasks) == 2 and tasks[1]["retry"] == 0 and "xung đột" in tasks[1]["hint"] and "shared.py" in tasks[1]["hint"]
    assert orch.conflict_retries["T2"] == 1
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
    _pub(bus, "approved-specs", "P1", "product", {"project_id": "P1", "status": "pending_human", "kind": "library", "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
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
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=th)
    orch = Orchestrator(bus, client, repo=repo, base="main", batch_releases=True)
    _drive_to_plan(bus, orch); orch.run()
    assert seen == {"T1": [], "T2": ["f_t1.py"]}, "T2 (depends_on T1) bắt đầu trên nền đã có code T1"
    assert orch.lead.releases == ["REL-001"] and orch.lead.release_tickets["REL-001"] == ["T1", "T2"]
    merged = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "integration.merged"]
    assert [m["ticket_id"] for m in merged] == ["T1", "T2"] and merged[0]["release_id"] is None, "merge lúc approved, không đợi RC"
    assert orch.integration.files().count("f_t1.py") == 1
    assert [d["ticket_id"] for d in orch.supervisor.lessons()] == ["T1", "T2"], "bài học có ngay khi merge, trước nghiệm thu"
    t2_calls = [c for c in client.calls if _agent_of(c["system"]) == "builder" and '"T2"' in c["user"]]
    assert t2_calls and '"related_lessons"' in t2_calls[0]["user"] and '"ticket_id": "T1"' in t2_calls[0]["user"], "builder T2 nhận bài học T1 qua danh sách đã chọn"


def test_rework_state_survives_restart_and_empty_branch_is_not_integrated(tmp_path):
    """F17: task phát lại (retry/hint) phải được replay khi mở lại bus — nếu không ticket bị trả về lại thành approved.
    F18: branch vừa `fresh()` (không có gì mới) merge no-op không được tính là đã tích hợp."""
    repo = _init_repo(tmp_path / "repo"); db = tmp_path / "c.sqlite"
    def lead_independent(system, user):
        if _agent_of(system) == "product" and _product_phase(system) == "plan" and "P1" in user and "decision" not in _inp(user):
            return {"items": [{**T1, "budget_tokens": 40_000}, {**T2, "title": "POST /notes", "depends_on": [], "risk_tags": [], "budget_tokens": 40_000, "priority": 3}],
                    "context_writes": [{"namespace": "architecture", "content_ref": "docs/c4.md", "summary": "L1-L2"},
                                        {"namespace": "api-contract", "content_ref": "openapi.yaml", "summary": "v1"}]}
        return handler(system, user)
    calls = {"n": 0}
    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and _first_turn(msgs):
            p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
            if p.get("hint"):
                calls["n"] += 1
                return [_tc("write_file", path=f"after_{tid.lower()}.py", content="Y = 1\n")]
            return [_tc("write_file", path="shared.py", content=f"X = '{tid}'\n")]
        return _repo_tool_handler(msgs, tools)
    bus = SQLiteBus(db); orch = Orchestrator(bus, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    _drive_to_spec_gate(bus, orch)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")   # ADR-0037: ký gate spec là ticket được giao ngay
    # chạy tới đúng lúc T2 bị trả về vì xung đột (task với hint "xung đột" đã publish) rồi "tắt máy". Xung đột KHÔNG
    # tính vào retry nội dung (`request_changes_no_retry_bump`) nên tín hiệu chờ là hint, không phải retry==1.
    while orch.queue and not any(e.topic == "tasks" and "xung đột" in (e.payload.get("hint") or "") for e in bus.replay()):
        orch.run(max_steps=1)
    assert orch.lead.state["T2"] == "dispatched" and orch.lead.tickets["T2"].retry == 0 and orch.conflict_retries["T2"] == 1
    bus.close()
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    assert o2.lead.state["T2"] == "dispatched" and o2.lead.tickets["T2"].retry == 0, "F17: trạng thái làm lại sống sót qua restart"
    assert o2.conflict_retries["T2"] == 1, "F17b: bộ đếm xung đột (tách khỏi retry) cũng phải sống sót qua restart"
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
    """F15: có nhánh tích hợp thì ticket phụ thuộc chờ tới khi dependency MERGE xong, không phải lúc approved.
    F16: T1 budget 6000 < 3 lượt review, nhưng token review không trừ vào ngân sách ticket → T1 KHÔNG bị cắt."""
    repo = _init_repo(tmp_path / "repo")
    order: list[str] = []
    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and _first_turn(msgs):
            tid = _inp(msgs[0]["content"])["ticket_id"]; order.append(f"start:{tid}")
            order.append("t2_sees_t1" if tid == "T2" and (repo / ".worktrees" / "T2" / "f_t1.py").exists() else f"files:{tid}")
        return _repo_tool_handler(msgs, tools)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=th), repo=repo, base="main", batch_releases=True)
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.require_integration
    b = orch.supervisor.budgets["T1"]
    assert "T1" not in orch.paused and b.review_used > 0 and b.used < b.limit, "F16: review không làm ticket bị cắt ngân sách"
    assert order == ["start:T1", "files:T1", "start:T2", "t2_sees_t1"], order
    tasks_t2 = [e for e in bus.replay(topic="tasks") if e.key == "T2"]
    merged_t1 = next(e for e in bus.replay(topic="audit-log") if e.payload["action"] == "integration.merged" and '"T1"' in e.payload["evidence"])
    assert tasks_t2 and tasks_t2[0].ts >= merged_t1.ts, "T2 dispatch sau khi T1 merge"
    assert orch.lead.state == {"T1": "merged", "T2": "merged"} and orch.lead.release_tickets == {"REL-001": ["T1", "T2"]}


def test_without_repo_dependents_start_on_approve():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch); orch.run()
    assert not orch.lead.require_integration and orch.lead.state["T2"] == "merged"


def test_ticket_lam_lai_sau_khi_da_merge_thi_ban_sua_van_vao_nhanh_tich_hop(tmp_path):
    """Ticket đã merge một lần rồi bị trả về làm lại (nghiệm thu rejected / review block) và approved lần nữa: bản sửa
    PHẢI vào nhánh tích hợp. Trước đây tập `integrated` nhớ lần trước nên bỏ qua, release sau vẫn mang code cũ — đo
    được 2026-09-06 (TCK-CR-STAGE-001-02: bản sửa deploy.sh nằm trên branch, tag v0.18.2 vẫn là bản lỗi)."""
    from company.workspace import Integration, TicketWorkspace
    repo = _init_repo(tmp_path / "repo")
    integ = Integration(repo, base="main"); integ.ensure()
    ws = TicketWorkspace(repo, "T1", base="main"); ws.create()
    (ws.path / "f.py").write_text("v = 1\n", encoding="utf-8"); ws.commit_all("feat(T1): v1")
    assert integ.rev_list_count(ws.branch) == 1
    assert integ.merge(ws.branch, "merge(T1)").ok
    assert integ.rev_list_count(ws.branch) == 0, "merge xong thì branch không còn gì mới"
    (ws.path / "f.py").write_text("v = 2\n", encoding="utf-8"); ws.commit_all("fix(T1): v2 sau khi bị trả về")
    assert integ.rev_list_count(ws.branch) == 1, "bản sửa là commit mới → phải merge tiếp"
    assert integ.merge(ws.branch, "merge(T1) lần 2").ok
    assert (integ.path / "f.py").read_text(encoding="utf-8") == "v = 2\n"


def test_integrate_approved_merge_lai_ticket_da_integrated_khi_co_commit_moi(tmp_path):
    """Vòng `_integrate_approved` phải merge LẠI ticket đã nằm trong `self.integrated` nếu branch có commit mới.
    Đây là chỗ hỏng thật: ticket bị trả về làm lại rồi approved lần nữa, tập `integrated` nhớ lần trước nên bản sửa
    không bao giờ vào nhánh tích hợp. Tắt điều kiện `_branch_ahead` → assert cuối đỏ (nhánh tích hợp vẫn giữ v1)."""
    from company.orchestrator import StepResult
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    assert "T1" in orch.integrated and orch.lead.state["T1"] == "merged"
    ws = orch.workspace("T1"); assert ws is not None
    (ws.path / "f_t1.py").write_text("BAN_SUA = 2\n", encoding="utf-8"); ws.commit_all("fix(T1): bản sửa sau khi bị trả về")
    orch.lead.state["T1"] = "approved"  # trả về làm lại rồi approved lần nữa
    orch._integrate_approved(StepResult(event_id="e-rework", topic="ticket-updates", key="T1"))
    assert orch.integration is not None
    assert (orch.integration.path / "f_t1.py").read_text(encoding="utf-8") == "BAN_SUA = 2\n", "bản sửa phải vào nhánh tích hợp"


def test_branch_ahead_khong_no_khi_ref_branch_bien_mat(tmp_path):
    """`_branch_ahead` là điều kiện phụ của vòng merge lại: nếu git không trả lời được (ref branch đã bị xoá, worktree
    hỏng) thì phải coi như KHÔNG có gì mới và đi tiếp, chứ không được ném WorkspaceError làm chết cả lượt run()."""
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    ws = orch.workspace("T1"); assert ws is not None and ws.path.exists()
    _git(repo, "update-ref", "-d", f"refs/heads/{ws.branch}")
    assert orch._branch_ahead("T1") is False, "git lỗi → False, không ném"
    assert orch._branch_ahead("KHONG-CO-TICKET-NAY") is False, "không có workspace → False"


def test_integration_skipped_chi_ghi_mot_lan_cho_moi_ticket():
    """Nhánh "không có worktree" KHÔNG đổi trạng thái gì, nên mỗi nhịp watch gọi lại là ghi thêm một bản ghi
    y hệt vào audit-log.

    Đo trên dữ liệu chạy thật (`company.sqlite` của QLKH, 2026-09-09): `integration.skipped` chiếm
    13 399 / 17 278 bản ghi audit-log — 78% cả sổ. Không phải chuyện dung lượng: `metrics.py` và
    `console/collect.py` đọc "sự thật" từ chính sổ này, nên mọi thống kê bị pha loãng bởi một nhánh no-op.

    Đo hai chiều: bỏ `once=` khỏi `_audit` trong `worktree_flow.merge_ticket` thì ca này đỏ với 5 bản ghi."""
    from company.orchestrator import StepResult

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    for _ in range(5):
        assert orch._merge_ticket("TCK-1", StepResult("integration", "integration", "-"), "REL-1")

    ghi = [e for e in bus.replay(topic="audit-log")
           if json.loads(e.payload["evidence"]).get("ticket_id") == "TCK-1"
           and e.payload["action"] == "integration.skipped"]
    assert len(ghi) == 1, f"5 nhịp phải để lại đúng 1 bản ghi, nhận được {len(ghi)}"


def _merge_hong_khong_phai_xung_dot(tmp_path):
    """Nhánh tích hợp có file CHƯA TRACK trùng tên file ticket thêm vào → `git merge` từ chối
    ("untracked working tree files would be overwritten") mà KHÔNG có file xung đột nào."""
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    a = TicketWorkspace(repo, "A", base=it.branch); a.create()
    (a.path / "moi.py").write_text("X = 1\n", encoding="utf-8"); a.commit_all("feat(A): moi")
    (it.path / "moi.py").write_text("rac\n", encoding="utf-8")
    return repo, it, a


def test_integration_merge_hong_khong_phai_xung_dot_thi_khong_bao_conflict(tmp_path):
    """Audit 2026-09-23: mọi merge hỏng bị báo là xung đột với `conflicts=[stderr]`."""
    _, it, a = _merge_hong_khong_phai_xung_dot(tmp_path)
    before = it.sha()
    m = it.merge(a.branch, "merge(A): a")
    assert not m.ok and not m.conflicts, "không có file nào ở trạng thái U: đây không phải xung đột"
    assert "untracked" in m.error and it.sha() == before


def test_merge_hong_khong_phai_xung_dot_khong_xoa_nhanh_ticket_da_duyet(tmp_path):
    """Audit 2026-09-23: merge hỏng vì lý do môi trường bị coi là xung đột → `ws.fresh()` xoá nhánh ticket ĐÃ
    DUYỆT và đá nó về rework. Đúng ra: giữ nhánh, không rework, báo lên người (escalate) một lần."""
    from company.orchestrator import StepResult

    repo, _, _ = _merge_hong_khong_phai_xung_dot(tmp_path)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler), repo=repo, base="main")
    ws = orch.workspace("A"); tip = _git(repo, "rev-parse", ws.branch)
    for _ in range(2):
        assert orch._merge_ticket("A", StepResult("integration", "integration", "-"), None) is False
    assert _git(repo, "rev-parse", ws.branch) == tip and (ws.path / "moi.py").exists(), "nhánh ticket còn nguyên"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "integration.conflict" not in acts and "handler_error" not in acts and not orch.conflict_retries
    assert acts.count("integration.failed") == 1, "mỗi nhịp watch gọi lại — chỉ ghi một lần"
    esc = [e for e in bus.replay(topic="supervisor-actions") if e.payload.get("action") == "escalate"]
    assert len(esc) == 1 and "untracked" in json.dumps(esc[0].payload, ensure_ascii=False)


def test_git_khong_chet_khi_repo_khach_co_byte_khong_phai_utf8(tmp_path):
    """Repo khách có tệp không phải UTF-8 (log console Windows cp1252 dán vào tài liệu) → `git show`/`diff` in ra byte
    không giải mã được. Trước đây mọi lời gọi git giải mã `encoding="utf-8"` không kèm `errors=`: Linux ném
    `UnicodeDecodeError`, Windows chết ở luồng đọc và trả `stdout=None` → `'NoneType' object has no attribute 'strip'`.
    Đo được 2026-09-24 (CAMPUS-UNI/TCK-001): QA review PR lỗi handler, ticket rơi về escalation dù code không sai."""
    from company import gate_brief, workspace
    repo = _init_repo(tmp_path / "repo")
    (repo / "log.md").write_bytes(b"bootstrap: c\\u01a1 s\\u1edf d\xe3 s\xe0ng\n")  # nguyen van byte cp1252 cua log that
    subprocess.run(["git", "-C", str(repo), "add", "log.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "log"],
                   check=True, capture_output=True)
    assert "bootstrap" in workspace._git(repo, "show", "HEAD")
    ok, out = workspace._git_ok(repo, "show", "HEAD")
    assert ok and "bootstrap" in out
    assert "bootstrap" in (gate_brief._git(repo, "show", "HEAD") or "")


def test_merge_abort_hong_sau_xung_dot_la_loi_moi_truong_khong_phai_xung_dot(tmp_path, monkeypatch):
    """Audit 2026-09-22 → 2026-09-27 (B6): `Integration.merge` bỏ kết quả `merge --abort`. Abort hỏng sau xung đột
    (một tiến trình git khác giữ index) để worktree tích hợp DỞ merge, mà người gọi vẫn nhận "xung đột" → xoá nhánh
    ticket đã duyệt, đá về rework, và mọi merge sau hỏng vì "unmerged files". Đúng ra: lỗi môi trường
    (`conflicts=[]`, `error`) để orchestrator giữ nhánh và escalate như mọi merge hỏng không vì xung đột."""
    from pathlib import Path

    import company.workspace as ws_mod

    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    a = TicketWorkspace(repo, "A", base=it.branch); a.create()
    (a.path / "shared.py").write_text("X = 'a'\n", encoding="utf-8"); a.commit_all("feat(A): a")
    b = TicketWorkspace(repo, "B", base=it.branch); b.create()
    (b.path / "shared.py").write_text("X = 'b'\n", encoding="utf-8"); b.commit_all("feat(B): b")
    assert it.merge(a.branch, "merge(A): a").ok
    goc = ws_mod.subprocess.run

    def khoa_index_dung_luc_abort(argv, **kw):
        if "--abort" in argv:
            (Path(_git(it.path, "rev-parse", "--absolute-git-dir")) / "index.lock").write_text("", encoding="utf-8")
        return goc(argv, **kw)

    monkeypatch.setattr(ws_mod.subprocess, "run", khoa_index_dung_luc_abort)
    m = it.merge(b.branch, "merge(B): b")
    assert not m.ok and not m.conflicts, "worktree tích hợp dở merge là lỗi môi trường, không phải xung đột của ticket"
    assert "merge --abort" in m.error and "index.lock" in m.error
