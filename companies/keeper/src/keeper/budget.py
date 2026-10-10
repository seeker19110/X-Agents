"""Ngân sách thay đổi + hàng đợi việc (BT4, `DAC-TA-KEEPER.md` §6, bất biến I3).

**`can_open_pr()` HỎI GitHub mỗi lần được gọi** — không có biến đếm nào sống trong instance ở đây. Đó là chủ
đích, không phải quên tối ưu: "state chỉ sống trong RAM" là một trong bốn khuôn lỗi lặp lại của X-Agents
(`TRAPS.md`). Một con số PR-đang-mở nhớ trong tiến trình sẽ sai ngay khi một người merge tay, khi tiến trình
khởi động lại, hay khi có phiên thứ hai — và cái sai đó mở PR thứ hai, phá đúng bất biến I3. Lớp đệm duy nhất
là TTL theo argv trong `GitHubReader` (BT2, `github.py`): nó vẫn là câu trả lời của `gh`, có hạn dùng, và
không phải một biến đếm do `keeper` tự cộng.

Bảng kiểm cũng tra cứu được theo tên (`BUDGET_CHECKS` + `checks_without`), cùng lý do như `risk.RISK_RULES`:
ca chiều ngược phải bỏ được ĐÚNG một hàng kiểm rồi đo lại.

**Hạn mức tuần chỉ đếm PR CỦA KEEPER** (nhánh `worktree.BRANCH_PREFIX`, `is_keeper_pr`), không đếm PR của người
hay dependabot. Đo canary 2026-10-05 (`docs/reports/2026-10-05-keeper-canary-urllib3.md`): 28 PR của repo merge
trong tuần làm hạn mức 5 cạn dù keeper chưa mở PR nào, phải nâng tay `KEEPER_MAX_PR_PER_WEEK=30` cho một bản vá
bảo mật. Đo lại 2026-10-10: 30 PR merge/7 ngày, đúng 1 của keeper. Hạn mức là trần cho THAY ĐỔI TỰ ĐỘNG, không
phải cho độ bận của repo — cùng cách Renovate chỉ đếm PR mang `branchPrefix` của nó.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from .core import CORE
from .events import Signal
from .github import PullRequest
from .risk import TIER_RANK, risk_tier
from .worktree import BRANCH_PREFIX

MAX_PR_ENV = CORE.env_name("MAX_PR_PER_WEEK")  # "KEEPER_MAX_PR_PER_WEEK" — ghép tiền tố ở MỘT chỗ (config.py:90)
DEFAULT_MAX_PR_PER_WEEK = 5
WINDOW_DAYS = 7


class GitHubLike(Protocol):
    def open_prs(self) -> list[PullRequest] | None: ...
    def merged_prs(self, since: str) -> list[PullRequest] | None: ...


@dataclass(frozen=True)
class BudgetContext:
    """Ảnh chụp NGAY LÚC HỎI. Không được giữ lại giữa hai lần `can_open_pr()` — xem docstring module.

    `None` = `gh` không trả lời được. Mọi hàng kiểm coi `None` là KHÔNG QUA (fail closed, I3): không biết có
    PR nào đang mở hay không thì không được mở thêm."""
    open_pr_count: int | None
    merged_last_week: int | None  # chỉ PR của keeper (`is_keeper_pr`), không phải mọi PR của repo
    max_per_week: int


@dataclass(frozen=True)
class BudgetCheck:
    name: str
    ok: Callable[[BudgetContext], bool]


BUDGET_CHECKS: tuple[BudgetCheck, ...] = (
    BudgetCheck("no-open-pr", lambda c: c.open_pr_count == 0),              # bất biến I3
    BudgetCheck("weekly-quota", lambda c: c.merged_last_week is not None and c.merged_last_week < c.max_per_week),
)


def checks_without(*names: str) -> tuple[BudgetCheck, ...]:
    """Bảng kiểm thiếu đúng những hàng được nêu. Tên lạ thì NỔ (xem `risk.rules_without`)."""
    known = {c.name for c in BUDGET_CHECKS}
    missing = sorted(set(names) - known)
    if missing:
        raise KeyError(f"không có hàng kiểm {missing} trong BUDGET_CHECKS")
    return tuple(c for c in BUDGET_CHECKS if c.name not in names)


def max_pr_per_week(env: Mapping[str, str] | None = None) -> int:
    """Đọc `KEEPER_MAX_PR_PER_WEEK` MỖI LẦN gọi (người vận hành hạ hạn mức giữa đêm phải có hiệu lực ngay).
    Giá trị không phải số nguyên → mặc định, không nổ: một biến gõ sai không được biến thành "không giới hạn"
    cũng không được làm chết vòng watch."""
    raw = (env if env is not None else os.environ).get(MAX_PR_ENV)
    if raw is None:
        return DEFAULT_MAX_PR_PER_WEEK
    try:
        return int(raw.strip())
    except ValueError:
        return DEFAULT_MAX_PR_PER_WEEK


def is_keeper_pr(pr: PullRequest) -> bool:
    """PR do keeper mở = nhánh nguồn mang đúng tiền tố `worktree.BRANCH_PREFIX` (cách `KeeperWorktree.branch` đặt
    tên, cũng là nhánh `publish.push_branch` đẩy). Không nhìn tiêu đề (`fix(keeper)` là của người viết về keeper)
    hay tên có chữ "keeper" ở chỗ khác."""
    return pr.headRefName.startswith(BRANCH_PREFIX)


def since_iso(now: datetime) -> str:
    """Mốc `merged:>=` cho `gh pr list --search`: `gh` nhận NGÀY (`YYYY-MM-DD`), không nhận timestamp đầy đủ."""
    return (_as_aware(now) - timedelta(days=WINDOW_DAYS)).date().isoformat()


def _as_aware(now: datetime) -> datetime:
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now


def budget_context(
    gh: GitHubLike, *, now: datetime | None = None, env: Mapping[str, str] | None = None,
) -> BudgetContext:
    """Hai câu hỏi tới `gh` + một lần đọc biến môi trường, mỗi lần gọi. `GitHubReader.merged_prs` đã hỏi thẳng
    nhánh keeper; lọc lại ở đây để luật đúng với MỌI `GitHubLike` (fake, reader khác), không phụ thuộc câu hỏi."""
    reference = now or datetime.now(UTC)
    open_prs = gh.open_prs()
    merged = gh.merged_prs(since_iso(reference))
    return BudgetContext(
        open_pr_count=None if open_prs is None else len(open_prs),
        merged_last_week=None if merged is None else sum(1 for pr in merged if is_keeper_pr(pr)),
        max_per_week=max_pr_per_week(env),
    )


def can_open_pr(
    gh: GitHubLike, *, now: datetime | None = None, env: Mapping[str, str] | None = None,
    checks: tuple[BudgetCheck, ...] = BUDGET_CHECKS,
) -> bool:
    ctx = budget_context(gh, now=now, env=env)
    return all(c.ok(ctx) for c in checks)


class QueueItem(BaseModel):
    """Một signal đang chờ tới lượt. `age_days` đi KÈM signal chứ không nằm trong `Signal`: payload trên bus
    không mang mốc thời gian riêng (`signals.py` docstring — `ts` ở `Envelope`), nên tuổi là thứ người gọi đo
    từ envelope rồi đưa vào, không phải thứ suy ra từ nội dung."""
    signal: Signal
    age_days: float


def order_queue(items: Sequence[QueueItem]) -> list[QueueItem]:
    """FIFO theo `risk_tier` rồi tuổi: tier cao trước, trong cùng tier thì signal GIÀ nhất trước (FIFO thật —
    việc chờ lâu không được để một việc mới cùng tier chen lên)."""
    return sorted(items, key=lambda q: (TIER_RANK[risk_tier(q.signal)], -q.age_days))
