"""`risk_tier(signal)` — BẢNG DỮ LIỆU tra cứu được, không phải chuỗi `if` (BT4, `DAC-TA-KEEPER.md` §6).

Bài học K1.7: bảng chuyển trạng thái tra cứu được thì test được **từng ô**. Ở đây "ô" là một `RiskRule` có
TÊN; test tham chiếu hàng theo tên, và `rules_without(...)` cho phép bỏ đúng một hàng rồi đo lại — đó là cách
duy nhất để một ca "chiều ngược" thật sự tắt bản sửa thay vì assert một hằng đúng.

Thứ tự bảng LÀ ngữ nghĩa: mọi hàng `high` đứng TRƯỚC mọi hàng `low`, và `risk_tier` trả tier của hàng khớp
ĐẦU TIÊN. Một signal vừa "chạm `xagents-core/`" vừa "chỉ là file `.md`" phải là `high` — nếu duyệt bảng theo
thứ tự khác thì một lệch tài liệu trong lõi bị hạ xuống `low` và tự merge.

**`semver_jump is None` không rơi vào `low`** (đo ở BT3, `scout.semver_jump`): `None` nghĩa là ba số không đổi
(`2.0.0` → `2.0.0rc1`) hoặc không parse được — tức là CHƯA BIẾT bậc nhảy. Hàng `dev-dependency-patch-minor`
đòi `semver_jump in {"patch", "minor"}` một cách tường minh, nên `None` rơi xuống `medium`. Cho `None` vào
`low` là để một bản pre-release của dev-dependency đi thẳng qua cổng với mức rủi ro thấp nhất, dựa trên một
điều mình không đo được. Không biết thì không phải là "an toàn".
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .events import RiskTier, Signal

DEFAULT_TIER: RiskTier = "medium"
#: Thứ hạng tier, nhỏ = nặng hơn (bảng chứ không `if`) — `budget` xếp hàng đợi, `triage` chọn bậc cao nhất của một nhóm gộp (K3).
TIER_RANK: dict[RiskTier, int] = {"high": 0, "medium": 1, "low": 2}

# Mục coverage của `pyproject.toml`: nhận ra bằng dấu vết TRONG nội dung thay đổi, không bằng riêng tên file —
# `pyproject.toml` bị chạm vì đổi mô tả package không phải rủi ro cao (bất biến I4 chỉ cấm hạ `fail_under`).
_COVERAGE_RE = re.compile(r"fail_under|tool\.coverage|\[coverage", re.IGNORECASE)
_PR_SUBJECT_RE = re.compile(r"^pr-\d+$")
_DOC_SUFFIXES = (".md", ".rst", ".txt")


@dataclass(frozen=True)
class RiskRule:
    """Một HÀNG của bảng: tên tra cứu được, tier nó gán, và phép thử trên `Signal`."""
    name: str
    tier: RiskTier
    match: Callable[[Signal], bool]


def paths(signal: Signal) -> tuple[str, ...]:
    """Các token có thể là ĐƯỜNG DẪN trong một signal: `subject` (file/gói bị chạm) và `evidence` (nguồn dẫn
    xuất, ví dụ `agents/engineering/builder.md` của một lệch `sc-*`). Cả hai đều được soi, vì lệch prompt có
    `subject` là tên file dẫn xuất còn đường dẫn nguồn chỉ nằm ở `evidence`."""
    return tuple(t.replace("\\", "/") for t in (signal.subject, signal.evidence) if t)


def _touches(signal: Signal, predicate: Callable[[str], bool]) -> bool:
    return any(predicate(p) for p in paths(signal))


def _in_segment(path: str, segment: str) -> bool:
    """`segment` là một THÀNH PHẦN đường dẫn, không phải substring: `agents/` khớp
    `software-company/agents/x.md` và `.claude/agents/y.md`, nhưng không khớp một gói tên `myagents`."""
    return segment in path.split("/")


def _is_doc(path: str) -> bool:
    """Dấu vết "tài liệu thuần": đuôi tài liệu, thư mục `docs/`, hoặc dấu tham chiếu PR `(#n)` — khuôn `evidence`
    của tín hiệu "thiếu dòng CHANGELOG" (phép (c) cũ của `drift.py`, đã bỏ ở audit 2026-10-10 F1; hiện không
    còn nơi phát nào đặt `(#n)` vào `evidence` của tín hiệu drift)."""
    return path.endswith(_DOC_SUFFIXES) or _in_segment(path, "docs") or path.startswith("(#")


RISK_RULES: tuple[RiskRule, ...] = (
    # --- high: sáu hàng của §6 ---
    RiskRule("semver-major", "high", lambda s: s.kind == "dependency" and s.semver_jump == "major"),
    RiskRule("touches-core", "high", lambda s: _touches(s, lambda p: _in_segment(p, "xagents-core"))),
    RiskRule("touches-agents-or-skills", "high",
             lambda s: _touches(s, lambda p: _in_segment(p, "agents") or _in_segment(p, "skills"))),
    RiskRule("touches-ci-config", "high", lambda s: _touches(s, lambda p: _in_segment(p, ".github"))),
    RiskRule("touches-coverage-config", "high",
             lambda s: _touches(s, lambda p: p.endswith("pyproject.toml"))
             and bool(_COVERAGE_RE.search(f"{s.detail} {s.evidence}"))),
    RiskRule("security-high", "high", lambda s: s.kind == "security" and s.severity in {"high", "critical"}),
    # --- low: hai hàng của §6 (đứng SAU mọi hàng high, xem docstring) ---
    RiskRule("dev-dependency-patch-minor", "low",
             lambda s: s.kind == "dependency" and s.is_dev and s.semver_jump in {"patch", "minor"}),
    RiskRule("docs-only-drift", "low",
             lambda s: s.kind == "drift"
             and (bool(_PR_SUBJECT_RE.match(s.subject)) or _is_doc(s.subject.replace("\\", "/")))
             and all(_is_doc(p) for p in paths(s) if not _PR_SUBJECT_RE.match(p))),
)


def rules_without(*names: str) -> tuple[RiskRule, ...]:
    """Bảng thiếu đúng những hàng được nêu — dụng cụ của ca chiều ngược. Tên không có trong bảng thì NỔ, chứ
    không im lặng trả về bảng đầy đủ: một ca "chiều ngược" gõ sai tên hàng sẽ xanh vĩnh viễn."""
    known = {r.name for r in RISK_RULES}
    missing = sorted(set(names) - known)
    if missing:
        raise KeyError(f"không có hàng {missing} trong RISK_RULES")
    return tuple(r for r in RISK_RULES if r.name not in names)


def risk_tier(signal: Signal, *, rules: tuple[RiskRule, ...] = RISK_RULES) -> RiskTier:
    """Tier của hàng khớp ĐẦU TIÊN; không hàng nào khớp → `DEFAULT_TIER` (`medium`)."""
    for rule in rules:
        if rule.match(signal):
            return rule.tier
    return DEFAULT_TIER
