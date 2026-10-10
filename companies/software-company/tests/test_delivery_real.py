"""ADR-0027: giao hàng thật — tag `v<version>` + fast-forward `company/release` trong repo khách khi production được duyệt;
rollback lùi con trỏ (tag giữ nguyên); push tuỳ chọn, lỗi push không chặn; `main` của khách không bị chạm."""
from __future__ import annotations

import json
import subprocess

import pytest

from company import github_pr
from company.bus import InMemoryBus
from company.events import Envelope
from company.llm import FakeClient
from company.orch.release_fsm import _delivery_pr
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from company.workspace import Integration, TicketWorkspace, WorkspaceError
from test_orchestrator import _drive_to_plan, handler
from test_tools_and_agentic import _init_repo, _repo_tool_handler


def _git(repo, *a) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def _rev(repo, ref) -> str:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")


def _merge_ticket(repo, it: Integration, tid: str, fname: str) -> str:
    ws = TicketWorkspace(repo, tid, base=it.branch); ws.create()
    (ws.path / fname).write_text(f"X = '{tid}'\n", encoding="utf-8"); ws.commit_all(f"feat({tid}): {fname}")
    m = it.merge(ws.branch, f"merge({tid})"); assert m.ok
    return _rev(repo, it.branch)


def _audits(bus, prefix):
    return [(e.payload["action"], json.loads(e.payload["evidence"] or "{}")) for e in bus.replay(topic="audit-log")
            if e.payload["action"].startswith(prefix)]


# ---------- Integration.deliver / rollback_delivery / push ----------

def test_deliver_tag_va_fast_forward_nhanh_release(tmp_path):
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    sha_a = _merge_ticket(repo, it, "A", "a.py")
    r = it.deliver("0.1.1", "release REL-001 v0.1.1\n\ntickets: A")
    assert r.ok and r.tag == "v0.1.1" and r.tag_created and r.branch_moved and r.previous is None and r.pushed is None
    assert r.sha == sha_a == _rev(repo, "v0.1.1") == _rev(repo, "company/release") and r.short == sha_a[:7]
    assert _git(repo, "cat-file", "-t", "v0.1.1") == "tag", "tag chú thích, có thông điệp release"
    assert "tickets: A" in _git(repo, "tag", "-l", "-n3", "v0.1.1")
    assert _git(repo, "log", "-1", "--format=%s", "main") == "init", "main của khách không bị chạm"
    # idempotent: giao lại cùng phiên bản → không tạo gì, không lỗi
    r2 = it.deliver("0.1.1", "lại")
    assert r2.ok and not r2.tag_created and not r2.branch_moved and r2.previous == sha_a
    # lần giao sau: fast-forward, nhớ sha trước để rollback
    sha_b = _merge_ticket(repo, it, "B", "b.py")
    r3 = it.deliver("0.1.2", "release REL-002")
    assert r3.ok and r3.tag_created and r3.branch_moved and r3.previous == sha_a and r3.sha == sha_b
    assert _rev(repo, "company/release") == sha_b and _git(repo, "tag", "-l").split() == ["v0.1.1", "v0.1.2"]
    # giao một sha cụ thể (sha đã kiểm trên staging), không phải đầu nhánh tích hợp
    sha_c = _merge_ticket(repo, it, "C", "c.py")
    r4 = it.deliver("0.1.3", "x", sha=sha_b)
    assert r4.ok and r4.sha == sha_b and not r4.branch_moved and _rev(repo, "v0.1.3") == sha_b != sha_c
    assert _rev(repo, "company/release") == sha_b, "sha đã giao nằm sau con trỏ → không lùi, không lỗi"


def test_deliver_khong_ghi_de_tag_khong_ep_nhanh_lech(tmp_path):
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    _merge_ticket(repo, it, "A", "a.py")
    subprocess.run(["git", "-C", str(repo), "tag", "v9.9.9", "main"], check=True)
    r = it.deliver("9.9.9", "x")
    assert not r.ok and r.problems == [f"tag_conflict:v9.9.9@{_rev(repo, 'main')[:7]}"] and not r.tag_created
    assert _rev(repo, "v9.9.9") == _rev(repo, "main"), "tag đã có ở sha khác thì giữ nguyên"
    assert r.branch_moved and _rev(repo, "company/release") == r.sha, "nhánh release vẫn được tạo"
    # ai đó commit thẳng lên company/release → lần giao sau không fast-forward được → nhánh giữ nguyên, tag vẫn tạo
    tay = TicketWorkspace(repo, "tay", base="main"); tay.create()
    (tay.path / "tay.py").write_text("x = 1\n", encoding="utf-8"); tay.commit_all("sửa tay")
    subprocess.run(["git", "-C", str(repo), "branch", "-f", "company/release", tay.branch], check=True)
    sha_b = _merge_ticket(repo, it, "B", "b.py")
    r2 = it.deliver("0.2.0", "y")
    assert not r2.ok and r2.problems == [f"diverged:{_rev(repo, tay.branch)[:7]}"] and r2.tag_created and not r2.branch_moved
    assert _rev(repo, "company/release") == _rev(repo, tay.branch) and _rev(repo, "v0.2.0") == sha_b
    with pytest.raises(WorkspaceError, match="chưa có gì để giao"):
        Integration(_init_repo(tmp_path / "trong"), base="main").deliver("0.1.0", "z")
    with pytest.raises(WorkspaceError, match="chưa có gì để giao"):
        it.deliver("0.3.0", "z", sha="0000000000000000000000000000000000000000")


def test_rollback_lui_con_tro_giu_tag_va_khong_de_len_release_sau(tmp_path):
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    _merge_ticket(repo, it, "A", "a.py"); r1 = it.deliver("0.1.1", "1")
    _merge_ticket(repo, it, "B", "b.py"); r2 = it.deliver("0.1.2", "2")
    rb = it.rollback_delivery(r2.previous, expected=r2.sha)
    assert rb.ok and rb.branch_moved and _rev(repo, "company/release") == r1.sha and _rev(repo, "v0.1.2") == r2.sha
    # release sau đã lên: rollback của bản trước không được lùi đè lên nó
    r3 = it.deliver("0.1.3", "3", sha=r2.sha)
    assert r3.ok and _rev(repo, "company/release") == r2.sha
    sup = it.rollback_delivery(r1.previous, expected=r1.sha)
    assert not sup.ok and sup.problems == [f"superseded:{r2.sha[:7]}"] and _rev(repo, "company/release") == r2.sha
    # lần giao đầu: rollback xoá nhánh; rollback lần nữa → nhánh không còn
    rb3 = it.rollback_delivery(None, expected=r2.sha)
    assert rb3.ok and rb3.branch_moved and not _git(repo, "branch", "--list", "company/release")
    rb4 = it.rollback_delivery(None, expected=r2.sha)
    assert not rb4.ok and rb4.problems == ["missing:nhánh release không còn"]
    assert _git(repo, "tag", "-l").split() == ["v0.1.1", "v0.1.2", "v0.1.3"], "tag là lịch sử bất biến"


def test_rollback_khi_da_o_dung_sha_khong_di_chuyen_nhanh(tmp_path):
    """`to_sha` trùng `cur` (đã lùi rồi, hoặc gọi lại idempotent): không có gì để `branch -f`, `branch_moved` False."""
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    _merge_ticket(repo, it, "A", "a.py"); r1 = it.deliver("0.1.1", "1")
    _merge_ticket(repo, it, "B", "b.py"); r2 = it.deliver("0.1.2", "2")
    rb = it.rollback_delivery(r2.previous, expected=r2.sha)
    assert rb.ok and rb.branch_moved
    rb2 = it.rollback_delivery(r1.sha, expected=r1.sha)
    assert rb2.ok and not rb2.branch_moved and _rev(repo, "company/release") == r1.sha


def test_push_len_remote_cua_khach_va_loi_push_khong_chan(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bare = tmp_path / "remote.git"; subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    it = Integration(repo, base="main"); it.ensure(); _merge_ticket(repo, it, "A", "a.py")
    r = it.deliver("0.1.1", "1", push_remote="origin")
    assert r.ok and r.pushed is True and r.push_error == ""
    assert _rev(bare, "company/release") == r.sha and _rev(bare, "v0.1.1") == r.sha
    _merge_ticket(repo, it, "B", "b.py"); r2 = it.deliver("0.1.2", "2", push_remote="origin")
    assert r2.pushed is True and _rev(bare, "company/release") == r2.sha
    rb = it.rollback_delivery(r2.previous, expected=r2.sha, push_remote="origin")
    assert rb.ok and rb.pushed is True and _rev(bare, "company/release") == r.sha, "force-with-lease lùi remote về bản trước"
    # remote không tồn tại: bản giao cục bộ vẫn xong, lỗi push chỉ được ghi lại
    _merge_ticket(repo, it, "C", "c.py"); r3 = it.deliver("0.1.3", "3", push_remote="khong-co")
    assert r3.ok and r3.tag_created and r3.pushed is False and r3.push_error
    # remote đã bị người khác đẩy đi (lease sai) → push bị từ chối, nhánh cục bộ vẫn lùi, không đè lên remote
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", f"{r3.sha}:refs/heads/company/release"], check=True)
    rb2 = it.rollback_delivery(r2.sha, expected=r3.sha, push_remote="origin")
    assert rb2.ok and rb2.branch_moved and rb2.pushed is True and _rev(bare, "company/release") == r2.sha
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", f"{r3.sha}:refs/heads/company/release"], check=True)
    it2 = Integration(repo, base="main"); subprocess.run(["git", "-C", str(repo), "branch", "-f", "company/release", r3.sha], check=True)
    rb3 = it2.rollback_delivery(r.sha, expected=r3.sha, push_remote="origin")  # lease đúng cục bộ, remote đã khác? không — remote = r3
    assert rb3.ok and rb3.pushed is True
    subprocess.run(["git", "-C", str(repo), "branch", "-f", "company/release", r3.sha], check=True)
    rb4 = it2.rollback_delivery(r2.sha, expected=r3.sha, push_remote="origin")  # remote đang ở r.sha, lease đòi r3 → từ chối
    assert rb4.ok and rb4.branch_moved and rb4.pushed is False and rb4.push_error and _rev(bare, "company/release") == r.sha
    # giao lại cùng phiên bản lên remote hợp lệ: push lại tag/nhánh là idempotent
    r5 = it.deliver("0.1.3", "3", push_remote="origin")
    assert r5.ok and r5.pushed is True and r5.push_error == "" and _rev(bare, "company/release") == r3.sha
    # không có ref nào để push (tag trùng ở sha khác, nhánh đã đúng chỗ) → không gọi push, không báo lỗi push
    subprocess.run(["git", "-C", str(repo), "tag", "v7.7.7", "main"], check=True)
    r6 = it.deliver("7.7.7", "x", sha=r3.sha, push_remote="khong-co")
    assert not r6.ok and r6.problems[0].startswith("tag_conflict") and not r6.branch_moved
    assert r6.pushed is True and r6.push_error == ""


# ---------- orchestrator: production duyệt → giao; rolled_back → lùi; bền qua restart ----------

def test_orchestrator_giao_hang_khi_production_va_lui_khi_rollback(tmp_path):
    repo = _init_repo(tmp_path / "repo"); db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main", deliver=True)
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.state == {"T1": "merged", "T2": "merged"} and orch.stats["errors"] == 0
    assert not orch.delivered and not _git(repo, "tag", "-l"), "chưa qua gate 3 thì chưa giao"
    staged = orch.release_sha
    assert set(staged) == {"REL-001", "REL-002"} and staged["REL-001"] != staged["REL-002"]
    assert _git(repo, "ls-tree", "-r", "--name-only", staged["REL-001"]).split().count("f_t2.py") == 0, "sha staging của REL-001 chưa có T2"

    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    d = orch.delivered["REL-001"]
    assert d["version"] == "0.1.1" and d["tag"] == "v0.1.1" and d["tag_created"] and d["branch_moved"]
    assert d["problems"] == [] and d["pushed"] is None and d["previous"] is None and d["sha"] == staged["REL-001"]
    assert _rev(repo, "v0.1.1") == d["sha"] == _rev(repo, "company/release"), "tag ở đúng sha QA đã hồi quy, không phải đầu nhánh tích hợp"
    assert _rev(repo, "company/integration") == staged["REL-002"] != d["sha"]
    assert "f_t2.py" not in _git(repo, "ls-tree", "-r", "--name-only", "v0.1.1")
    assert _git(repo, "log", "-1", "--format=%s", "main") == "init", "main của khách không bị chạm"
    done = _audits(bus, "delivery.")
    assert [a for a, _ in done] == ["delivery.done"] and done[0][1]["release_id"] == "REL-001"
    st = orch.status()["delivery"]
    assert st == {"REL-001": {"version": "0.1.1", "tag": "v0.1.1", "short": d["short"], "branch": "company/release",
                              "problems": [], "pushed": None, "pr": None}}  # `pr` None: --deliver-pr tắt (ADR-0038)
    assert any(a.startswith("delivered:REL-001@v0.1.1") for r in orch.run() for a in r.actions) is False, "không giao lại"

    # mở lại bus: bản đã giao và sha staging dựng lại từ audit-log
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main", deliver=True)
    assert o2.delivered == orch.delivered and o2.release_sha == orch.release_sha
    assert not _git(repo, "tag", "-l").split() != ["v0.1.1"] and o2.run() == [], "mở lại không tag lại, không giao lại"

    # REL-002 lên production: fast-forward tiếp
    orch.gate.decide("REL-002", "approve", by="human:release-manager"); orch.run()
    d2 = orch.delivered["REL-002"]
    assert d2["tag"] == "v0.2.0" and d2["previous"] == d["sha"] and _rev(repo, "company/release") == d2["sha"] == staged["REL-002"]

    # production của REL-002 rolled_back → con trỏ lùi về REL-001, tag v0.2.0 giữ nguyên
    bus.publish(Envelope(topic="release-events", key="REL-002", actor="ops",
                         payload={"release_id": "REL-002", "version": "0.2.0", "env": "production", "status": "rolled_back"}))
    orch.run()
    assert "REL-002" not in orch.delivered and "REL-001" in orch.delivered
    assert _rev(repo, "company/release") == d["sha"] and _rev(repo, "v0.2.0") == d2["sha"]
    rb = [ev for a, ev in _audits(bus, "delivery.rolled_back")]
    assert rb and rb[0]["from"] == d2["sha"] and rb[0]["to"] == d["sha"] and rb[0]["problems"] == []
    o3 = Orchestrator(SQLiteBus(db), FakeClient(handler=handler), repo=repo, base="main", deliver=True)
    assert set(o3.delivered) == {"REL-001"}


def test_khong_bat_deliver_thi_nhu_cu(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert orch.lead.state["T1"] == "released" and not orch.delivered and orch.status()["delivery"] == {}
    assert not _git(repo, "tag", "-l") and not _git(repo, "branch", "--list", "company/release")
    assert not _audits(bus, "delivery.") and orch.release_sha, "sha staging vẫn được ghi để bật giao hàng về sau"


def test_deliver_khong_repo_thi_bo_qua_co_audit(tmp_path):
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler), deliver=True)
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert orch.lead.state["T1"] == "released" and not orch.delivered
    skipped = _audits(bus, "delivery.skipped")
    assert len(skipped) == 1 and "không có nhánh tích hợp" in skipped[0][1]["reason"]


def test_deliver_ghi_van_de_va_loi_push_vao_audit(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "-C", str(repo), "tag", "v0.1.1", "main"], check=True)  # tag trùng phiên bản sẽ giao
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main",
                        deliver=True, push_remote="khong-co", release_branch="rel/prod")
    _drive_to_plan(bus, orch); orch.run()
    res = []
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); res = orch.run()
    d = orch.delivered["REL-001"]
    assert d["problems"] == [f"tag_conflict:v0.1.1@{_rev(repo, 'main')[:7]}"] and d["pushed"] is False and d["push_error"]
    assert d["branch"] == "rel/prod" and _rev(repo, "rel/prod") == d["sha"]
    acts = [a for a, _ in _audits(bus, "delivery.")]
    assert acts == ["delivery.done", "delivery.tag_conflict", "delivery.push_failed"]
    assert any(a.startswith("delivered:REL-001@v0.1.1(tag_conflict") for r in res for a in r.actions)


def test_cli_co_co_deliver(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo"); db = str(tmp_path / "c.sqlite"); SQLiteBus(db).close()
    assert orch_main(["--db", db, "--repo", str(repo), "--deliver", "--push-remote", "origin", "--release-branch", "rel", "status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["delivery"] == {}


# ---------- ADR-0038: PR thật nhánh release → nhánh của khách, mở không merge ----------

class _FakeGh:
    """`gh` giả: kịch bản trả lời theo lệnh con (`list`/`create`), ghi lại argv để test đo đường đi chứ không đo gh."""

    def __init__(self, list_out="[]", list_ok=True, create_out="https://github.com/acme/app/pull/7", create_ok=True):
        self.list_out, self.list_ok, self.create_out, self.create_ok = list_out, list_ok, create_out, create_ok
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, repo, *args, timeout=60):
        self.calls.append(args)
        if args[:2] == ("pr", "list"): return self.list_ok, self.list_out
        assert args[:2] == ("pr", "create"), args
        return self.create_ok, self.create_out


def test_github_slug_nhan_dang_remote_github():
    assert github_pr.github_slug("https://github.com/acme/app.git") == "acme/app"
    assert github_pr.github_slug("https://github.com/acme/app") == "acme/app"
    assert github_pr.github_slug("git@github.com:acme/app.git") == "acme/app"
    assert github_pr.github_slug("ssh://git@github.com/acme/app/") == "acme/app"
    for other in ("https://gitlab.com/acme/app.git", "/tmp/remote.git", "", None, "https://github.com/acme"):
        assert github_pr.github_slug(other) is None, other


def test_open_pr_mo_moi_dung_lai_va_loi(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir()
    # remote không phải GitHub: không gọi gh lấy một lần
    gh = _FakeGh(); monkeypatch.setattr(github_pr, "_gh", gh)
    r = github_pr.open_pr(repo, str(tmp_path / "bare.git"), "company/release", "main", "t", "b")
    assert not r.ok and r.slug == "" and "không phải GitHub" in r.reason and gh.calls == []
    assert r.record() == {"error": r.reason, "slug": ""}
    # chưa có PR đang mở → create; số PR đọc từ URL
    r = github_pr.open_pr(repo, "https://github.com/acme/app.git", "company/release", "main", "release REL-1 v1", "body")
    assert r.ok and r.created and r.number == 7 and r.url.endswith("/pull/7") and r.slug == "acme/app"
    assert gh.calls[0][:2] == ("pr", "list") and "--head" in gh.calls[0] and gh.calls[1][:2] == ("pr", "create")
    create = gh.calls[1]
    assert create[create.index("--base") + 1] == "main" and create[create.index("--head") + 1] == "company/release"
    assert create[create.index("--repo") + 1] == "acme/app" and create[create.index("--title") + 1] == "release REL-1 v1"
    assert r.record() == {"url": r.url, "number": 7, "created": True, "slug": "acme/app"}
    # PR đang mở cùng head/base → dùng lại, không create
    gh = _FakeGh(list_out='[{"number": 3, "url": "https://github.com/acme/app/pull/3"}]'); monkeypatch.setattr(github_pr, "_gh", gh)
    r = github_pr.open_pr(repo, "git@github.com:acme/app.git", "company/release", "main", "t", "b")
    assert r.ok and not r.created and r.number == 3 and [c[:2] for c in gh.calls] == [("pr", "list")]
    # list trả JSON hỏng → coi như chưa có → create; URL không có /pull/<n> → number None
    gh = _FakeGh(list_out="không phải json", create_out="đã tạo"); monkeypatch.setattr(github_pr, "_gh", gh)
    r = github_pr.open_pr(repo, "https://github.com/acme/app", "company/release", "main", "t", "b")
    assert r.ok and r.created and r.number is None and r.url == "đã tạo"
    # list có PR nhưng thiếu number → number None
    gh = _FakeGh(list_out='[{"url": "u"}]'); monkeypatch.setattr(github_pr, "_gh", gh)
    assert github_pr.open_pr(repo, "https://github.com/acme/app", "h", "b", "t", "b").number is None
    # gh lỗi ở list / ở create → ok=False kèm lý do, slug vẫn có (để phân biệt với "không phải GitHub")
    gh = _FakeGh(list_ok=False, list_out="gh: not logged in"); monkeypatch.setattr(github_pr, "_gh", gh)
    r = github_pr.open_pr(repo, "https://github.com/acme/app", "h", "b", "t", "b")
    assert not r.ok and r.slug == "acme/app" and r.reason == "gh: not logged in"
    gh = _FakeGh(create_ok=False, create_out="permission denied", list_out=""); monkeypatch.setattr(github_pr, "_gh", gh)
    r = github_pr.open_pr(repo, "https://github.com/acme/app", "h", "b", "t", "b")
    assert not r.ok and r.reason == "permission denied" and len(gh.calls) == 2


def test_gh_that_thieu_tren_may_qua_han_va_ma_thoat(tmp_path, monkeypatch):
    """`_gh` thật với `subprocess.run` giả: không có gh, quá hạn, mã thoát ≠ 0, mã thoát 0 — không ném ở ca nào."""
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        mode = argv[1]
        if mode == "missing": raise FileNotFoundError(argv[0])
        if mode == "slow": raise subprocess.TimeoutExpired(argv, kw["timeout"])
        if mode == "bad": return subprocess.CompletedProcess(argv, 1, stdout="", stderr="x" * 400)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(github_pr.subprocess, "run", fake_run)
    monkeypatch.setenv("GH_TOKEN", "ghp_secret"); monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret2")
    assert github_pr._gh(tmp_path, "missing") == (False, "gh: không có trên máy (cài GitHub CLI rồi `gh auth login`)")
    ok, why = github_pr._gh(tmp_path, "slow", "x", timeout=3)
    assert not ok and why == "gh slow x: quá 3s"
    ok, why = github_pr._gh(tmp_path, "bad")
    assert not ok and len(why) == 300
    assert github_pr._gh(tmp_path, "good") == (True, "ok")
    env = calls[-1][1]["env"]
    assert "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env, "gh xác thực bằng cấu hình trên đĩa, không qua env (ADR-0027 §4)"
    assert calls[-1][0][0] == "gh" and calls[-1][1]["cwd"] == str(tmp_path)


def test_gh_co_that_ma_khong_chay_duoc_thi_khong_nem(tmp_path, monkeypatch):
    """Docstring `_gh` hứa "không ném", nhưng `gh` CÓ trên máy mà không chạy được (quyền, binary hỏng) ném
    `OSError` khác `FileNotFoundError` — xuyên qua `open_pr` vào lượt giao hàng thay vì thành `PrResult` lỗi.
    `gh` cố định trong argv nên giả `subprocess.run` (không dựng được file thật cùng tên trên cả hai nền tảng)."""
    def khong_quyen(argv, **kw):
        raise PermissionError(13, "Permission denied", argv[0])

    monkeypatch.setattr(github_pr.subprocess, "run", khong_quyen)
    assert github_pr._gh(tmp_path, "pr", "list") == (False, "gh: không chạy được (Permission denied)")


def test_integration_remote_url_va_base_branch(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    it = Integration(repo, base="main")
    assert it.remote_url("origin") is None and it.base_branch() == "main"
    bare = tmp_path / "remote.git"; subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    assert it.remote_url("origin") == str(bare)
    assert Integration(repo, base="khong-co").base_branch() is None
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach"], check=True)
    assert Integration(repo, base="HEAD").base_branch() is None, "HEAD tách rời không phải nhánh đích cho PR"


class _O:
    def __init__(self, deliver_pr=True, push_remote="origin"): self.deliver_pr, self.push_remote = deliver_pr, push_remote


def test_delivery_pr_moi_ly_do_bo_qua(tmp_path, monkeypatch):
    """`_delivery_pr` từng nhánh: tắt → None; thiếu --push-remote; push hỏng; base không phải nhánh; remote không
    phải GitHub → `skipped` có lý do; gh lỗi → `error`; còn lại → url + base/head."""
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main")
    assert _delivery_pr(_O(deliver_pr=False), it, "R", "1.0.0", ["T1"], True, "v1.0.0") is None
    assert "cần --push-remote" in _delivery_pr(_O(push_remote=None), it, "R", "1.0.0", ["T1"], True, "v1.0.0")["skipped"]
    assert "push chưa thành công" in _delivery_pr(_O(), it, "R", "1.0.0", ["T1"], False, "v1.0.0")["skipped"]
    assert "push chưa thành công" in _delivery_pr(_O(), it, "R", "1.0.0", ["T1"], None, "v1.0.0")["skipped"]
    assert "không phải nhánh" in _delivery_pr(_O(), Integration(repo, base="khong-co"), "R", "1.0.0", [], True, "v1")["skipped"]
    gh = _FakeGh(); monkeypatch.setattr(github_pr, "_gh", gh)
    assert "không phải GitHub" in _delivery_pr(_O(), it, "R", "1.0.0", ["T1"], True, "v1.0.0")["skipped"] and gh.calls == []
    monkeypatch.setattr(Integration, "remote_url", lambda self, remote: "https://github.com/acme/app.git")
    got = _delivery_pr(_O(), it, "REL-9", "1.0.0", ["T1", "T2"], True, "v1.0.0")
    assert got == {"url": "https://github.com/acme/app/pull/7", "number": 7, "created": True, "slug": "acme/app",
                   "base": "main", "head": "company/release"}
    create = gh.calls[-1]; body = create[create.index("--body") + 1]
    assert "T1, T2" in body and "UAT-REL-9" in body and "không merge" in body and create[create.index("--title") + 1] == "release REL-9 v1.0.0"
    gh = _FakeGh(list_ok=False, list_out="gh: auth"); monkeypatch.setattr(github_pr, "_gh", gh)
    assert _delivery_pr(_O(), it, "R", "1.0.0", [], True, "v1")["error"] == "gh: auth"


def _orch_pr(tmp_path, bus, monkeypatch, gh, **kw):
    repo = _init_repo(tmp_path / "repo")
    bare = tmp_path / "remote.git"; subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    monkeypatch.setattr(github_pr, "_gh", gh)
    monkeypatch.setattr(Integration, "remote_url", lambda self, remote: "https://github.com/acme/app.git")
    orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main",
                        deliver=True, push_remote="origin", deliver_pr=True, **kw)
    _drive_to_plan(bus, orch); orch.run()
    return repo, bare, orch


def test_orchestrator_mo_pr_that_sau_khi_giao_va_dung_lai_khi_da_mo(tmp_path, monkeypatch):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); gh = _FakeGh()
    repo, bare, orch = _orch_pr(tmp_path, bus, monkeypatch, gh)
    assert gh.calls == [], "chưa qua gate 3 thì chưa có gì để mở PR"
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    d = orch.delivered["REL-001"]
    assert d["pushed"] is True and _rev(bare, "company/release") == d["sha"], "PR chỉ mở sau khi nhánh đã lên remote"
    assert d["pr"] == {"url": "https://github.com/acme/app/pull/7", "number": 7, "created": True, "slug": "acme/app",
                       "base": "main", "head": "company/release"}
    assert [c[:2] for c in gh.calls] == [("pr", "list"), ("pr", "create")]
    acts = _audits(bus, "delivery.")
    assert [a for a, _ in acts] == ["delivery.done", "delivery.pr_opened"] and acts[1][1]["url"].endswith("/pull/7")
    assert orch.status()["delivery"]["REL-001"]["pr"]["url"].endswith("/pull/7")
    assert _git(repo, "log", "-1", "--format=%s", "main") == "init" and _rev(bare, "main") == "", "main khách không bị chạm (cục bộ lẫn remote): PR chỉ mở"
    # mở lại bus: PR dựng lại từ delivery.done, không gọi gh lần nữa
    gh2 = _FakeGh(); monkeypatch.setattr(github_pr, "_gh", gh2)
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main",
                      deliver=True, push_remote="origin", deliver_pr=True)
    assert o2.delivered["REL-001"]["pr"] == d["pr"] and o2.run() == [] and gh2.calls == []
    # REL-002: PR cùng head/base đang mở → dùng lại (fast-forward nhánh release đã đẩy bản mới lên chính PR đó)
    gh3 = _FakeGh(list_out='[{"number": 7, "url": "https://github.com/acme/app/pull/7"}]'); monkeypatch.setattr(github_pr, "_gh", gh3)
    orch.gate.decide("REL-002", "approve", by="human:release-manager"); orch.run()
    d2 = orch.delivered["REL-002"]
    assert d2["pr"]["created"] is False and d2["pr"]["number"] == 7 and [c[:2] for c in gh3.calls] == [("pr", "list")]
    assert [a for a, _ in _audits(bus, "delivery.pr_")] == ["delivery.pr_opened", "delivery.pr_reused"]


def test_orchestrator_pr_loi_gh_va_bo_qua_khi_thieu_push_remote(tmp_path, monkeypatch):
    bus = InMemoryBus(); gh = _FakeGh(list_ok=False, list_out="gh: not logged in")
    _repo, _bare, orch = _orch_pr(tmp_path, bus, monkeypatch, gh)
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    d = orch.delivered["REL-001"]
    assert d["pushed"] is True and d["pr"] == {"error": "gh: not logged in", "slug": "acme/app", "base": "main", "head": "company/release"}
    assert [a for a, _ in _audits(bus, "delivery.")] == ["delivery.done", "delivery.pr_failed"], "gh hỏng không chặn bản giao"
    # không có --push-remote: bật --deliver-pr là vô nghĩa, ghi lý do chứ không im lặng
    repo2 = _init_repo(tmp_path / "repo2"); bus2 = InMemoryBus()
    orch2 = Orchestrator(bus2, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo2, base="main",
                         deliver=True, deliver_pr=True)
    _drive_to_plan(bus2, orch2); orch2.run()
    orch2.gate.decide("REL-001", "approve", by="human:release-manager"); orch2.run()
    pr = orch2.delivered["REL-001"]["pr"]
    assert "cần --push-remote" in pr["skipped"] and [a for a, _ in _audits(bus2, "delivery.pr_")] == ["delivery.pr_skipped"]


def test_cli_co_co_deliver_pr(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo"); db = str(tmp_path / "c.sqlite"); SQLiteBus(db).close()
    assert orch_main(["--db", db, "--repo", str(repo), "--deliver", "--push-remote", "origin", "--deliver-pr", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["delivery"] == {}
