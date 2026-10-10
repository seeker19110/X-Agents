"""BT8 canary — capability ghi THẬT duy nhất ngoài `worktree.py`: push nhánh của ticket + `gh pr create`.

Mọi ca dựng repo git THẬT trong `tmp_path` cho push (remote là một repo local khác, không mạng); `gh pr
create` được giả bằng cách thay `subprocess.run` — không ca nào gọi `gh` thật hay chạm mạng.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from keeper import publish as publish_mod
from keeper.publish import PublishError, PullRequestExists, create_pr, push_branch
from keeper.worktree import KeeperWorktree, open_worktree


def _run(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "nha" / "repo"
    root.mkdir(parents=True)
    _run(root, "init", "-b", "main")
    (root / "README.md").write_text("xin chao\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "khoi tao")
    return root


@pytest.fixture
def remote(tmp_path: Path, repo: Path) -> Path:
    """Remote THẬT là một repo bare cục bộ — `git push` chạy nguyên vẹn, không cần mạng."""
    bare = tmp_path / "remote.git"
    _run(bare.parent, "init", "--bare", "-b", "main", str(bare))
    _run(repo, "remote", "add", "origin", str(bare))
    _run(repo, "push", "origin", "main")
    return bare


# ---------- push_branch ----------

def test_push_branch_day_nhanh_ticket_len_remote(repo: Path, remote: Path) -> None:
    wt = open_worktree("KEEP:1", repo=repo)
    (wt.path / "vá.md").write_text("noi dung\n", encoding="utf-8")
    _run(wt.path, "add", "-A")
    _run(wt.path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "vá")

    push_branch(wt, sha=_run(wt.path, "rev-parse", "HEAD"))

    ls = subprocess.run(["git", "ls-remote", str(remote), wt.branch], capture_output=True, text=True)
    assert wt.branch in ls.stdout


def test_push_branch_day_dung_sha_duoc_dua_khong_theo_dau_nhanh(repo: Path, remote: Path) -> None:
    """Nhánh đi tiếp sau commit đã kiểm (tiến trình khác commit chen): remote nhận ĐÚNG sha được đưa, vẫn chỉ vào
    nhánh của worktree — không phải đầu nhánh hiện tại, không nhánh nào khác (I1)."""
    wt = open_worktree("KEEP:6", repo=repo)
    (wt.path / "vá.md").write_text("đã kiểm\n", encoding="utf-8")
    _run(wt.path, "add", "-A")
    _run(wt.path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "vá")
    da_kiem = _run(wt.path, "rev-parse", "HEAD")
    (wt.path / "vá.md").write_text("chen sau khi kiểm\n", encoding="utf-8")
    _run(wt.path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-am", "chen")

    push_branch(wt, sha=da_kiem)

    dong = _run(remote, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads").splitlines()
    assert dict(d.split() for d in dong) == {"refs/heads/main": _run(repo, "rev-parse", "main"),
                                             f"refs/heads/{wt.branch}": da_kiem}


def test_push_branch_tu_choi_tren_checkout_chung(repo: Path, remote: Path) -> None:
    wt = KeeperWorktree(repo=repo, ticket_id="KEEP:2")  # chưa create() -> wt.path không tồn tại/không phải worktree phụ
    from keeper.worktree import SharedCheckoutRefused
    with pytest.raises(SharedCheckoutRefused):
        push_branch(wt, sha=_run(repo, "rev-parse", "HEAD"))


def test_push_branch_loi_git_nem_publish_error(repo: Path) -> None:
    """Không có remote -> git push lỗi thật -> PublishError, không phải traceback trần."""
    wt = open_worktree("KEEP:3", repo=repo)
    with pytest.raises(PublishError):
        push_branch(wt, sha=_run(wt.path, "rev-parse", "HEAD"))


def test_push_branch_idempotent_goi_hai_lan_khong_hong(repo: Path, remote: Path) -> None:
    wt = open_worktree("KEEP:4", repo=repo)
    (wt.path / "vá.md").write_text("a\n", encoding="utf-8")
    _run(wt.path, "add", "-A")
    _run(wt.path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "vá")
    sha = _run(wt.path, "rev-parse", "HEAD")
    push_branch(wt, sha=sha)
    push_branch(wt, sha=sha)  # cùng SHA, remote đã đúng -> không lỗi


# ---------- create_pr (subprocess giả, không gọi gh thật) ----------

@dataclass
class _RunSpy:
    """Thay `subprocess.run`: trả `CompletedProcess` theo kịch bản, ghi lại argv đã gọi."""
    script: list[tuple[int, str, str]]
    calls: list[list[str]]

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        code, out, err = self.script[len(self.calls) - 1]
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


@dataclass
class _RunSpyKw(_RunSpy):
    """Như `_RunSpy`, ghi thêm `kwargs` để ca kiểm `env=` được truyền đúng."""
    kwargs: list[dict[str, Any]]

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.kwargs.append(kw)
        return super().__call__(argv, **kw)


def test_create_pr_goi_gh_pr_create_dung_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spy = _RunSpyKw(script=[(0, "https://github.com/o/r/pull/42\n", "")], calls=[], kwargs=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)

    pr = create_pr(tmp_path, title="fix: t", body="mô tả", head="chore/keeper-x", base="main")

    assert pr.number == 42 and pr.url == "https://github.com/o/r/pull/42"
    argv = spy.calls[0]
    assert argv[:3] == ["gh", "pr", "create"]
    for flag, val in [("--title", "fix: t"), ("--body", "mô tả"), ("--head", "chore/keeper-x"), ("--base", "main")]:
        assert argv[argv.index(flag) + 1] == val


def test_create_pr_khong_lo_bien_moi_truong_bi_mat_cua_tien_trinh_cha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`env=` truyền cho subprocess phải là một dict RIÊNG (`clean_env()`-kiểu), không phải `os.environ` mặc
    định của tiến trình cha — cùng bất biến `github.py` đã giữ cho mọi lệnh `gh` khác."""
    spy = _RunSpyKw(script=[(0, "https://github.com/o/r/pull/1\n", "")], calls=[], kwargs=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    monkeypatch.setenv("SOME_API_TOKEN", "khong-duoc-lo")

    create_pr(tmp_path, title="t", body="b", head="h", base="main")

    env = spy.kwargs[0].get("env")
    assert env is not None, "phải truyền env= tường minh, không để subprocess kế thừa os.environ"
    assert "SOME_API_TOKEN" not in env


def test_create_pr_that_bai_nem_publish_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spy = _RunSpy(script=[(1, "", "some gh error")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    with pytest.raises(PublishError):
        create_pr(tmp_path, title="t", body="b", head="h", base="main")


def test_push_branch_qua_han_nem_publish_error(monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path) -> None:
    """`refuse_shared_checkout` (worktree.py) cũng gọi `subprocess.run` thật — chỉ giả timeout đúng lệnh
    `push`, để lời gọi kiểm checkout riêng trước đó không bị ăn theo."""
    wt = open_worktree("KEEP:5", repo=repo)
    sha = _run(wt.path, "rev-parse", "HEAD")
    goc = subprocess.run

    def _chi_timeout_push(argv: list[str], **k: Any) -> subprocess.CompletedProcess[str]:
        if "push" in argv:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=k.get("timeout", 0))
        return goc(argv, **k)

    monkeypatch.setattr(publish_mod.subprocess, "run", _chi_timeout_push)
    with pytest.raises(PublishError, match="quá"):
        push_branch(wt, sha=sha)


def test_create_pr_qua_han_nem_publish_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _timeout(*a: Any, **k: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=k.get("timeout", 0))

    monkeypatch.setattr(publish_mod.subprocess, "run", _timeout)
    with pytest.raises(PublishError, match="quá"):
        create_pr(tmp_path, title="t", body="b", head="h", base="main")


def test_create_pr_thanh_cong_nhung_khong_doc_duoc_url_thi_bao_ro(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`gh` đổi định dạng output hoặc in thêm rác trước URL tới mức regex không khớp — báo lỗi rõ ràng thay vì
    trả `PullRequest` với `number`/`url` rỗng/sai (xanh vì rỗng)."""
    spy = _RunSpy(script=[(0, "đã tạo xong, không có URL nào ở đây\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    with pytest.raises(PublishError, match="không đọc được URL"):
        create_pr(tmp_path, title="t", body="b", head="h", base="main")


def test_create_pr_da_co_pr_cho_nhanh_nay_thi_bao_ro_khong_tao_trung(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`gh pr create` tự chối khi head branch đã có PR mở — bắt đúng thông điệp đó, ném loại lỗi RIÊNG
    (không phải PublishError chung chung) để lớp gọi phân biệt được "đã có PR" với "gh hỏng thật"."""
    spy = _RunSpy(script=[(1, "", "a pull request for branch \"chore/keeper-x\" into branch \"main\" already exists:\nhttps://github.com/o/r/pull/7")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", spy)
    with pytest.raises(PullRequestExists) as ei:
        create_pr(tmp_path, title="t", body="b", head="chore/keeper-x", base="main")
    assert ei.value.url == "https://github.com/o/r/pull/7"


def test_push_branch_khong_chay_hook_pre_push(repo: Path, remote: Path) -> None:
    """`worktree.NO_HOOKS`: "orchestrator không bao giờ chạy hook" — nhưng `push_branch` tự gọi `subprocess.run`
    không mang `NO_HOOKS`, nên `pre-push` của repo khách (mã người lạ, có thể do chính patch vừa sửa) chạy dưới
    quyền người vận hành trong một lần đẩy không ai ngồi xem (audit 2026-10-10, họ của `_git`)."""
    hook = repo / ".git" / "hooks" / "pre-push"
    dau_vet = repo.parent / "hook-da-chay"
    hook.write_text(f"#!/bin/sh\ntouch '{dau_vet}'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    wt = open_worktree("KEEP:1", repo=repo)
    (wt.path / "vá.md").write_text("noi dung\n", encoding="utf-8")
    _run(wt.path, "add", "-A")
    _run(wt.path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "vá")

    push_branch(wt, sha=_run(wt.path, "rev-parse", "HEAD"))

    assert not dau_vet.exists(), "pre-push của repo khách đã chạy trong lúc keeper đẩy nhánh"
    ls = subprocess.run(["git", "ls-remote", str(remote), wt.branch], capture_output=True, text=True)
    assert wt.branch in ls.stdout
