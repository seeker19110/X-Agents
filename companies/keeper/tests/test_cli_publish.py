"""`keeper publish` — CLI cho `KeeperOrchestrator.publish()` (BT8 canary).

Repo git THẬT (remote là repo bare local, không mạng); `gh pr create` giả bằng cách thay `subprocess.run`
trong `keeper.publish` (không gọi `gh` thật, chỉ `git` chạy thật)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from keeper import publish as publish_mod
from keeper.cli import main
from keeper.events import RunOutcome, Signal
from keeper.evidence import TRUSTED_VERIFIER, TwoWayEvidence
from keeper.fakes import FakeGitHub
from keeper.orchestrator import KeeperOrchestrator
from keeper.release import PR_PLACEHOLDER
from keeper.worktree import open_worktree

NOW = datetime(2026, 9, 12, tzinfo=UTC)
_GOC_RUN = subprocess.run


class _GH(FakeGitHub):
    def open_prs(self) -> list:
        return []


@dataclass
class _RunSpy:
    script: list[tuple[int, str, str]]
    calls: list[list[str]]

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] != "gh":
            return _GOC_RUN(argv, **kw)
        self.calls.append(argv)
        code, out, err = self.script[len(self.calls) - 1]
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


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


def _ticket_du_cong(repo: Path) -> str:
    o = KeeperOrchestrator(repo.parent / "keeper.sqlite", repo, _GH())
    o.submit_signal(Signal.model_validate(
        {"subject": "requests", "kind": "dependency", "detail": "bump", "semver_jump": None}))
    (t,) = o.tick(now=NOW).tickets
    cmd = "uv run pytest -q"
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, TwoWayEvidence(
        cmd=cmd, before=RunOutcome(cmd=cmd, exit_code=1), after=RunOutcome(cmd=cmd, exit_code=0),
        verified_by=TRUSTED_VERIFIER))
    assert o.tick(now=NOW).notes, "phải có release-notes trước khi publish có gì để làm"
    return t.ticket_id


def _commit_dong_changelog(wt_path: Path, ticket_id: str) -> None:
    changelog = wt_path / "CHANGELOG.md"
    changelog.write_text(changelog.read_text(encoding="utf-8") +
                         f"- fix(keeper): bump requests — bảo trì tự động, tier low {PR_PLACEHOLDER}\n",
                         encoding="utf-8")
    _git(wt_path, "add", "-A")
    _git(wt_path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", f"vá {ticket_id}")


def test_publish_qua_cli_tao_pr_that_in_ra_url(
    monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tid = _ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    code = main(["publish", "--db", str(repo.parent / "keeper.sqlite"), "--repo", str(repo), tid])

    assert code == 0
    out = capsys.readouterr().out
    assert "PR #9" in out and "pull/9" in out


def test_publish_qua_cli_repo_la_thu_muc_con_van_tim_dung_worktree(
    monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--repo` là thư mục con: worktree của ticket nằm cạnh GỐC repo, không cạnh thư mục con. Trước đây vị trí
    worktree tính từ `--repo` nguyên văn (`repo.parent / ...`) trong khi `git worktree` tự dò lên gốc — lệnh
    tìm worktree sai chỗ rồi `worktree add` lại đúng nhánh đang checkout ở worktree thật."""
    tid = _ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    con = repo / "docs"
    con.mkdir()
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    code = main(["publish", "--db", str(repo.parent / "keeper.sqlite"), "--repo", str(con), tid])

    assert code == 0
    assert "PR #9" in capsys.readouterr().out


def test_publish_qua_cli_repo_la_thu_muc_con_khong_ghi_gi_vao_checkout_chung(repo: Path) -> None:
    """I1: nhánh ticket chưa có thì `open_worktree` dựng worktree MỚI — trước đây ở `<thư mục con>.parent`, tức
    ngay TRONG checkout chung (thư mục lạ mà `drift-detector` quét phải ở vòng sau), trước cả khi biết ticket có
    release-notes hay không."""
    con = repo / "docs"
    con.mkdir()

    code = main(["publish", "--db", str(repo.parent / "keeper.sqlite"), "--repo", str(con), "KEEP:khong-co"])

    assert code == 2
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_publish_qua_cli_lan_hai_bao_da_publish(
    monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tid = _ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)
    spy = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    db, r = str(repo.parent / "keeper.sqlite"), str(repo)
    main(["publish", "--db", db, "--repo", r, tid])

    code = main(["publish", "--db", db, "--repo", r, tid])

    assert code == 0
    assert "đã publish từ trước" in capsys.readouterr().out


def test_publish_qua_cli_chua_co_note_thi_ma_loi_2(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["publish", "--db", str(repo.parent / "keeper.sqlite"), "--repo", str(repo), "KEEP:khong-co"])
    assert code == 2
    assert "chưa có release-notes" in capsys.readouterr().err


def test_publish_qua_cli_push_loi_thi_ma_loi_3(
    monkeypatch: pytest.MonkeyPatch, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Không có `remote` fixture -> chưa `git remote add origin` -> push lỗi thật -> mã thoát 3."""
    tid = _ticket_du_cong(repo)
    wt = open_worktree(tid, repo=repo)
    _commit_dong_changelog(wt.path, tid)

    code = main(["publish", "--db", str(repo.parent / "keeper.sqlite"), "--repo", str(repo), tid])

    assert code == 3
    assert capsys.readouterr().err.strip() != ""
