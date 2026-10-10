"""Capability GHI thật duy nhất ngoài `worktree.py`: push nhánh của ticket + `gh pr create` (BT8 canary).

Bất biến I1 (`DAC-TA-KEEPER.md` §0) cho phép ĐÚNG BA việc: tạo nhánh, commit trong worktree của chính ticket,
và mở PR. Hai việc đầu đã có ở `worktree.py`/`patcher.py`. Việc thứ ba — thứ canary BT8 cần để "mở PR" có kết
quả thật thay vì chỉ ghi ý định (`orchestrator.open_pr()`) — sống ở ĐÂY, tách khỏi `github.py` một cách có chủ
ý: `GitHubReader` giữ nguyên bất biến "chỉ đọc" mà TRAPS.md/CLAUDE.md của package này đã ghi, không lẫn một
hàm ghi vào giữa các hàm đọc. Muốn rút lại quyền ghi thì xoá đúng một file này.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from xagents_core.sandbox import clean_env

from .worktree import NO_HOOKS, KeeperWorktree, git_env, refuse_shared_checkout

_PR_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)")


class PublishError(Exception):
    """`git push` hoặc `gh pr create` thất bại vì lý do không phải "PR đã tồn tại"."""


@dataclass
class PullRequestExists(Exception):
    """`gh pr create` từ chối vì nhánh này đã có PR mở — không phải lỗi, là idempotent: ai gọi lại `create_pr`
    cho cùng một ticket thì nhận về PR đã có, không tạo bản trùng (I3: một PR bảo trì tại một thời điểm)."""
    url: str
    number: int

    def __str__(self) -> str:  # pragma: no cover - chỉ phục vụ traceback người đọc, không ai assert chuỗi này
        return f"PR đã tồn tại: {self.url}"


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str


def push_branch(wt: KeeperWorktree, *, sha: str, remote: str = "origin", timeout: int = 120) -> None:
    """`git push <remote> <sha>:refs/heads/<branch>` từ chính worktree của ticket. Đích luôn là nhánh của
    worktree, không bao giờ nhánh khác — I1 giới hạn phạm vi ghi vào đúng ticket đang xử lý. Idempotent: remote
    đã ở đúng SHA thì git trả 0, không lỗi.

    Đẩy `sha` (commit người gọi đã kiểm — `_require_measured` trả nó), KHÔNG đẩy theo tên nhánh: tên nhánh được
    phân giải lại lúc push, nên commit chen vào nhánh giữa kiểm và push sẽ lên remote mà không ai đo (ADR keeper
    0002). Không `-u`: nguồn là sha thì git không có nhánh cục bộ nào để gắn upstream — đo git 2.43, `push -u`
    trả 0 mà `branch.*` vẫn rỗng — và không chỗ nào trong keeper đọc upstream (`create_pr` nhận `--head`)."""
    refuse_shared_checkout(wt.path)
    try:
        r = subprocess.run(
            # `NO_HOOKS` như `_git` của worktree: `pre-push` của repo khách là mã người lạ, không chạy khi đẩy tự động.
            ["git", "-C", str(wt.path), *NO_HOOKS, "push", remote, f"{sha}:refs/heads/{wt.branch}"],
            capture_output=True, text=True, encoding="utf-8", env=git_env(), timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise PublishError(f"git push {remote} {sha}:{wt.branch}: quá {timeout}s") from e
    if r.returncode != 0:
        raise PublishError(f"git push {remote} {sha}:{wt.branch}: {(r.stderr or r.stdout).strip()}")


def create_pr(repo: Path, *, title: str, body: str, head: str, base: str = "main",
              timeout: int = 60) -> PullRequest:
    """`gh pr create` THẬT. Argv chốt cứng — chỉ bốn giá trị người gọi truyền đi vào bốn cờ cố định, không
    ghép chuỗi, không `shell=True`, không đường nào khác cho argv tự do lọt vào."""
    try:
        r = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body, "--head", head, "--base", base],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8", env=clean_env(), timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise PublishError(f"gh pr create ({head} -> {base}): quá {timeout}s") from e

    text = r.stdout if r.returncode == 0 else r.stderr
    m = _PR_URL_RE.search(text)
    if r.returncode != 0:
        if "already exists" in text and m:
            raise PullRequestExists(url=m.group(0), number=int(m.group(1)))
        raise PublishError(f"gh pr create ({head} -> {base}): {text.strip()[-300:]}")
    if not m:
        raise PublishError(f"gh pr create ({head} -> {base}): không đọc được URL PR từ output: {text.strip()[:200]}")
    return PullRequest(number=int(m.group(1)), url=m.group(0))
