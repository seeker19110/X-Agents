"""Workspace cô lập theo ticket: git worktree trên branch `ticket/<id>`, chạy lint/test thật, trả `local_checks`.
Tool xác định cho khối kỹ thuật; kết quả là bằng chứng để đưa vào `pull-requests.local_checks`.

`Integration` (ADR-0011): nhánh tích hợp của công ty (`company/integration`, rẽ từ `base` lần đầu). Ticket rẽ từ đây
và được merge vào đây (--no-ff) khi đủ review pass; xung đột thì huỷ merge, trả lại danh sách file để ticket làm lại
trên nền mới. Nhánh của khách (`main`) không bị chạm."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stacks import Stack, detect


class WorkspaceError(Exception): ...


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", input=stdin)
    if r.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


# Rác do agent chạy lint/test sinh ra trong worktree. `commit_all` dùng `git add -A`: không loại thì `.pyc` của hai
# ticket cùng vào branch rồi xung đột nhị phân lúc merge (mô phỏng donghanhcungban, F14). Ghi vào `.git/info/exclude`
# (áp cho mọi worktree, không chạm `.gitignore` của khách) và không bao giờ add vào index.
JUNK_PATTERNS = (".worktrees/", "__pycache__/", "*.pyc", "*.pyo", ".ruff_cache/", ".pytest_cache/", ".mypy_cache/",
                 ".hypothesis/", ".venv/", "*.egg-info/")


def exclude_worktrees(repo: Path) -> None:
    """`.worktrees/` và rác lint/test là của công ty, không phải của khách: ghi vào `.git/info/exclude` để `git status`
    của khách không thấy untracked và `git add -A` của `commit_all` không vơ vào."""
    git_dir = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not git_dir.is_absolute(): git_dir = repo / git_dir
    f = git_dir / "info" / "exclude"
    try:
        current = f.read_text(encoding="utf-8") if f.exists() else ""
    except OSError:
        return
    have = set(current.splitlines())
    missing = [x for x in JUNK_PATTERNS if x not in have]
    if not missing: return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(current + ("" if not current or current.endswith("\n") else "\n") + "\n".join(missing) + "\n", encoding="utf-8")


@dataclass
class CheckResult:
    ok: bool
    output: str


@dataclass
class TicketWorkspace:
    repo: Path
    ticket_id: str
    base: str = "HEAD"

    @property
    def branch(self) -> str: return f"ticket/{self.ticket_id}"
    @property
    def path(self) -> Path: return self.repo / ".worktrees" / self.ticket_id

    def create(self) -> Path:
        if self.path.exists():
            return self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exclude_worktrees(self.repo)
        if _git(self.repo, "branch", "--list", self.branch):
            _git(self.repo, "worktree", "add", str(self.path), self.branch)
        else:
            _git(self.repo, "worktree", "add", "-b", self.branch, str(self.path), self.base)
        return self.path

    def remove(self, delete_branch: bool = False) -> None:
        if self.path.exists():
            _git(self.repo, "worktree", "remove", "--force", str(self.path))
        if delete_branch:
            _git(self.repo, "branch", "-D", self.branch)

    def _run(self, *cmd: str, timeout: int = 600) -> CheckResult:
        # Không ghi .pyc vào worktree: tránh cache cũ che sửa đổi (Windows mtime thô) và rác trong branch.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run(cmd, cwd=self.path, capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=env)
        return CheckResult(ok=r.returncode == 0, output=(r.stdout + r.stderr)[-4000:])

    def stack(self) -> Stack:
        """Stack của repo khách (ADR-0013); quyết định lệnh lint/test thật sự chạy được."""
        return detect(self.path)

    def lint(self, *paths: str) -> CheckResult:
        argv = self.stack().lint
        if argv is None: return CheckResult(ok=False, output="không có lệnh lint cho stack này")
        return self._run(*argv, *paths)

    def test(self, *args: str) -> CheckResult:
        argv = self.stack().test
        if argv is None: return CheckResult(ok=False, output="không có lệnh test cho stack này")
        return self._run(*argv, *args)

    def run_checks(self) -> dict[str, Any]:
        """Đúng định dạng `pull-requests.local_checks`. Không có coverage thì bỏ trống chứ không bịa.
        Stack không nhận ra (hoặc không có lệnh) → `lint`/`tests` là False và `stack` nói rõ lý do:
        thà nói không kiểm được còn hơn báo pass bằng một lệnh không liên quan đến code vừa sửa."""
        st = self.stack()
        lint, test = self.lint(), self.test()
        return {"lint": lint.ok, "tests": test.ok, "lint_output": lint.output, "test_output": test.output,
                "stack": st.name}

    def commit_all(self, message: str) -> str:
        exclude_worktrees(self.repo)  # rác lint/test không vào index (F14), kể cả khi worktree được tạo bởi bản cũ
        _git(self.path, "add", "-A")
        # Rác đã bị theo dõi từ trước (branch cũ commit nhầm) thì gỡ khỏi index ở ticket này — không xoá file trên đĩa.
        tracked = [x for x in _git(self.path, "ls-files", "--cached").splitlines()
                   if "__pycache__/" in x or x.endswith((".pyc", ".pyo")) or x.startswith((".ruff_cache/", ".pytest_cache/", ".mypy_cache/"))]
        if tracked:
            _git(self.path, "rm", "-r", "-q", "--cached", "--", *tracked)
        # message qua stdin: argv trên Windows đi qua codepage console, tiếng Việt thành mojibake
        _git(self.path, "-c", "user.name=agent", "-c", "user.email=agent@company.local", "commit", "-F", "-", stdin=message)
        return _git(self.path, "rev-parse", "--short", "HEAD")

    def fresh(self) -> Path:
        """Bỏ worktree + branch cũ và tạo lại từ `base` hiện tại (ticket làm lại sau xung đột tích hợp)."""
        self.remove(delete_branch=True)
        return self.create()

    def base_sha(self) -> str:
        """Điểm rẽ nhánh thật (merge-base) — diff/changed_files so với đây, không phụ thuộc HEAD của repo đã đi tiếp."""
        return _git(self.repo, "merge-base", self.base, self.branch)

    def changed_files(self) -> list[str]:
        out = _git(self.path, "diff", "--name-only", self.base_sha())
        return [x for x in out.splitlines() if x]

    def has_changes(self) -> bool:
        return bool(_git(self.path, "status", "--porcelain")) or bool(self.changed_files())

    def dirty(self) -> bool:
        """Có sửa đổi chưa commit (so với HEAD của branch ticket). Khác `has_changes` (so với điểm rẽ nhánh): lần làm lại
        sau một PR bị từ chối vẫn thấy commit cũ trên branch, nên chỉ `dirty()` mới nói agent lần này có làm gì không."""
        return bool(_git(self.path, "status", "--porcelain"))

    def diff(self, max_chars: int = 20_000) -> str:
        """Diff so với điểm rẽ nhánh (gồm cả phần chưa commit) để reviewer/QA đọc; cắt để không phá ngữ cảnh."""
        d = _git(self.path, "diff", self.base_sha())
        return d if len(d) <= max_chars else d[:max_chars] + f"\n… (cắt, còn {len(d) - max_chars} ký tự)"


@dataclass
class MergeResult:
    ok: bool
    sha: str = ""
    conflicts: list[str] | None = None


@dataclass
class Integration:
    """Nhánh tích hợp trong worktree riêng `.worktrees/_integration`; merge ticket vào đây, không checkout repo gốc."""
    repo: Path
    branch: str = "company/integration"
    base: str = "HEAD"

    @property
    def path(self) -> Path: return self.repo / ".worktrees" / "_integration"

    def ensure(self) -> str:
        """Tạo nhánh (từ `base`) và worktree nếu chưa có; trả về sha hiện tại của nhánh tích hợp."""
        if not _git(self.repo, "branch", "--list", self.branch):
            _git(self.repo, "branch", self.branch, self.base)
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            exclude_worktrees(self.repo)
            _git(self.repo, "worktree", "add", str(self.path), self.branch)
        return self.sha()

    def sha(self) -> str:
        return _git(self.repo, "rev-parse", "--short", self.branch)

    def merge(self, ticket_branch: str, message: str) -> MergeResult:
        """merge --no-ff ticket vào nhánh tích hợp. Xung đột → abort, trả về file xung đột; nhánh tích hợp không đổi."""
        self.ensure()
        # `merge -F -` không đọc stdin như `commit`; ghi message ra file UTF-8 để tránh mojibake argv trên Windows
        msg = self.repo / ".worktrees" / "_merge_msg.txt"
        msg.write_text(message, encoding="utf-8", newline="\n")
        r = subprocess.run(["git", "-C", str(self.path), "-c", "user.name=delivery-lead", "-c", "user.email=lead@company.local",
                            "merge", "--no-ff", "-F", str(msg), ticket_branch], capture_output=True, text=True, encoding="utf-8")
        msg.unlink(missing_ok=True)
        if r.returncode == 0:
            return MergeResult(ok=True, sha=self.sha())
        conflicts = [x for x in _git(self.path, "diff", "--name-only", "--diff-filter=U").splitlines() if x]
        subprocess.run(["git", "-C", str(self.path), "merge", "--abort"], capture_output=True)
        return MergeResult(ok=False, conflicts=conflicts or [r.stderr.strip()[:300]])

    def files(self) -> list[str]:
        return [x for x in _git(self.repo, "ls-tree", "-r", "--name-only", self.branch).splitlines() if x]
