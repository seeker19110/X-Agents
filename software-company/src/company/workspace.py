"""Workspace cô lập theo ticket: git worktree trên branch `ticket/<id>`, chạy lint/test thật, trả `local_checks`.
Tool xác định cho khối kỹ thuật; kết quả là bằng chứng để đưa vào `pull-requests.local_checks`.

`Integration` (ADR-0011): nhánh tích hợp của công ty (`company/integration`, rẽ từ `base` lần đầu). Ticket rẽ từ đây
và được merge vào đây (--no-ff) khi đủ review pass; xung đột thì huỷ merge, trả lại danh sách file để ticket làm lại
trên nền mới. Nhánh của khách (`main`) không bị chạm."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkspaceError(Exception): ...


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", input=stdin)
    if r.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


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

    def lint(self, *paths: str) -> CheckResult:
        return self._run(sys.executable, "-m", "ruff", "check", *(paths or (".",)))

    def test(self, *args: str) -> CheckResult:
        return self._run(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args)

    def run_checks(self) -> dict[str, Any]:
        """Đúng định dạng `pull-requests.local_checks`. Không có coverage thì bỏ trống chứ không bịa."""
        lint, test = self.lint(), self.test()
        return {"lint": lint.ok, "tests": test.ok, "lint_output": lint.output, "test_output": test.output}

    def commit_all(self, message: str) -> str:
        _git(self.path, "add", "-A")
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
