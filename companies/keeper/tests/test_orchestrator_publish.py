"""`KeeperOrchestrator.publish()` — biến ý định mở PR (`pr.intent`) thành PR THẬT (BT8 canary).

Repo git THẬT trong `tmp_path` (remote là repo bare local — không mạng); `gh pr create` giả bằng cách thay
`subprocess.run` trong `keeper.publish` (không gọi `gh` thật). Giả định commit đầu tiên (patch + dòng
CHANGELOG mang `(#PR)`) đã có trong worktree — `publish()` không tự vá, không tự commit, chỉ push + tạo PR +
điền số PR thật.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from keeper import publish as publish_mod
from keeper.events import RunOutcome, Signal
from keeper.evidence import TRUSTED_VERIFIER, TwoWayEvidence
from keeper.fakes import FakeGitHub
from keeper.orchestrator import KeeperOrchestrator
from keeper.publish import PublishError
from keeper.release import PR_PLACEHOLDER
from keeper.worktree import content_tree, open_worktree

NOW = datetime(2026, 9, 12, tzinfo=UTC)


class _GH(FakeGitHub):
    """Ngân sách RỘNG: không PR nào đang mở — `FakeGitHub()` trần có sẵn 1 PR mẫu, đủ để cổng `budget` (I3)
    chặn mọi ticket. Sao y `_GH` của `test_orchestrator.py`."""

    def open_prs(self) -> list:
        return []


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    # Danh tính cục bộ: `publish()` tự commit số PR (runner CI không có user.name toàn cục).
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@x")
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "khoi tao")
    return root


@pytest.fixture
def remote(tmp_path: Path, repo: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(bare.parent, "init", "--bare", "-b", "main", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", "main")
    return bare


def _orc_voi_ticket_du_cong(repo: Path) -> tuple[KeeperOrchestrator, str]:
    """Dựng orchestrator trên `repo`, đẩy một signal qua hết cổng tới khi có `release-notes` (pr_number=None)."""
    o = KeeperOrchestrator(repo.parent / "keeper.sqlite", repo, _GH())
    o.submit_signal(Signal.model_validate(
        {"subject": "requests", "kind": "dependency", "detail": "bump", "semver_jump": None}))
    (t,) = o.tick(now=NOW).tickets
    # Bằng chứng gắn danh tính worktree THẬT của ticket (ADR keeper 0001): worktree phải có trước lần đo, và cổng
    # `evidence` đo lại đúng nó lúc `tick` mở ý định PR.
    wt = open_worktree(t.ticket_id, repo=repo)
    cmd = "uv run pytest -q"
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, TwoWayEvidence(
        cmd=cmd, before=RunOutcome(cmd=cmd, exit_code=1), after=RunOutcome(cmd=cmd, exit_code=0),
        verified_by=TRUSTED_VERIFIER, patch_id=content_tree(wt.path)))
    res = o.tick(now=NOW)
    assert res.notes, "ticket phải đủ cổng để có release-notes trước khi publish() có gì để làm"
    return o, t.ticket_id


_GOC_RUN = subprocess.run


@dataclass
class _RunSpy:
    """Chỉ giả lệnh `gh` (theo kịch bản); mọi lệnh khác (`git` của `worktree.py`/`push_branch`) chạy THẬT —
    `subprocess` là module DÙNG CHUNG nên monkeypatch không phân biệt được ai gọi nếu giả hết."""
    script: list[tuple[int, str, str]]
    calls: list[list[str]]

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] != "gh":
            return _GOC_RUN(argv, **kw)
        self.calls.append(argv)
        code, out, err = self.script[len(self.calls) - 1]
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def _commit_dong_changelog(wt_path: Path, ticket_id: str) -> None:
    """Mô phỏng commit đầu tiên mà `keeper run`/người đã làm trước khi gọi `publish()`: một dòng CHANGELOG
    mang `(#PR)` — đúng thứ `release.compose()` sinh ra."""
    changelog = wt_path / "CHANGELOG.md"
    changelog.write_text(changelog.read_text(encoding="utf-8") +
                         f"- fix(keeper): bump requests — bảo trì tự động, tier low {PR_PLACEHOLDER}\n",
                         encoding="utf-8")
    _git(wt_path, "add", "-A")
    _git(wt_path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", f"vá {ticket_id}")


def test_publish_day_nhanh_tao_pr_va_dien_so_pr_that(
    monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path
) -> None:
    o, tid = _orc_voi_ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    pr = o.publish(tid, wt)

    assert pr is not None and pr.number == 9
    ls = subprocess.run(["git", "ls-remote", str(remote), wt.branch], capture_output=True, text=True)
    assert wt.branch in ls.stdout, "nhánh phải thật sự lên remote"
    assert o.notes[tid].pr_number == 9, "trạng thái orchestrator phải đồng bộ qua bus, không chỉ file"
    assert PR_PLACEHOLDER not in (wt.path / "CHANGELOG.md").read_text(encoding="utf-8")
    actions = [a.payload["action"] for a in o.bus.replay(topic="audit-log")]
    assert "pr.created" in actions


def test_publish_lan_hai_khong_tao_pr_trung(monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path) -> None:
    o, tid = _orc_voi_ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    o.publish(tid, wt)

    assert o.publish(tid, wt) is None, "note đã có pr_number -> publish lại là no-op, không gọi gh lần hai"
    assert len(spy.calls) == 1, "gh pr create/git push không được gọi lại"


def test_publish_khi_gh_bao_da_co_pr_thi_dung_so_do(monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path) -> None:
    """`gh pr create` từ chối vì nhánh đã có PR (ví dụ orchestrator restart giữa chừng) -> publish() dùng
    ĐÚNG số PR đã có, không coi là lỗi (I3: idempotent, không tạo PR trùng)."""
    o, tid = _orc_voi_ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(1, "", f'a pull request for branch "{wt.branch}" into branch "main" already '
                                  f'exists:\nhttps://github.com/o/r/pull/5')], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    pr = o.publish(tid, wt)

    assert pr is not None and pr.number == 5
    assert o.notes[tid].pr_number == 5


def test_publish_khong_co_note_thi_bao_ro(repo: Path) -> None:
    o = KeeperOrchestrator(repo.parent / "keeper.sqlite", repo, FakeGitHub())
    wt = open_worktree("KEEP:khong-ton-tai", repo=repo)
    with pytest.raises(ValueError, match="chưa có release-notes"):
        o.publish("KEEP:khong-ton-tai", wt)


def test_publish_push_that_bai_khong_goi_gh(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Không remote -> push lỗi thật -> PublishError, và `gh pr create` KHÔNG được gọi (không tạo PR cho một
    nhánh chưa thật sự lên remote)."""
    o, tid = _orc_voi_ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/1\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    with pytest.raises(PublishError):
        o.publish(tid, wt)  # không có `remote` fixture -> chưa add origin -> git push lỗi thật
    assert spy.calls == [], "gh pr create không được gọi khi push chưa xong"


def test_publish_commit_va_push_so_pr_da_dien(monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path) -> None:
    """Số PR thật điền vào CHANGELOG phải thành một COMMIT và lên REMOTE — không chỉ nằm trong worktree. Không
    thì PR giữ `(#PR)` mãi, vì lần `publish()` sau trả sớm (note đã có `pr_number`)."""
    o, tid = _orc_voi_ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    o.publish(tid, wt)

    assert _git(wt.path, "status", "--porcelain") == "", "bản điền số PR phải được commit, không để dở"
    assert "(#9)" in _git(wt.path, "show", "HEAD:CHANGELOG.md")
    assert PR_PLACEHOLDER not in _git(wt.path, "show", "HEAD:CHANGELOG.md")
    head = _git(wt.path, "rev-parse", "HEAD")
    ls = subprocess.run(["git", "ls-remote", str(remote), wt.branch], capture_output=True, text=True)
    assert ls.stdout.startswith(head), "commit điền số PR phải được push lên nhánh của PR"


def test_publish_lan_hai_sau_khi_push_dien_so_hong_thi_hoan_tat(
        monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path) -> None:
    """Push lần hai (commit điền số) hỏng → note chưa có `pr_number`; gọi lại `publish()` phải push nốt commit
    đó và kết thúc, không nổ `ValueError` vì `(#PR)` đã được thay trong commit lần trước."""
    import keeper.orchestrator as orch_mod
    o, tid = _orc_voi_ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    goc_push = orch_mod.push_branch
    lan = {"n": 0}

    def push_hong_lan_hai(w: Any, **kw: Any) -> None:
        lan["n"] += 1
        if lan["n"] == 2:
            raise PublishError("mạng rớt")
        goc_push(w, **kw)

    monkeypatch.setattr(orch_mod, "push_branch", push_hong_lan_hai)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", ""),
                          (1, "", "a pull request for branch already exists: https://github.com/o/r/pull/9\n")],
                  calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    with pytest.raises(PublishError):
        o.publish(tid, wt)
    assert o.notes[tid].pr_number is None

    pr = o.publish(tid, wt)

    assert pr is not None and pr.number == 9 and o.notes[tid].pr_number == 9
    head = _git(wt.path, "rev-parse", "HEAD")
    ls = subprocess.run(["git", "ls-remote", str(remote), wt.branch], capture_output=True, text=True)
    assert ls.stdout.startswith(head) and "(#9)" in _git(wt.path, "show", "HEAD:CHANGELOG.md")
