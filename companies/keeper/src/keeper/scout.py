"""`dependency-scout` (BT3, `DAC-TA-KEEPER.md` §5): đọc `uv.lock` + dependabot alert (`github.py`/`fakes.py`)
→ `Signal(kind="dependency")`.

Dependabot chỉ cho biết PHIÊN BẢN CŨ→MỚI trong `summary` (khuôn chuẩn GitHub: "Bump <pkg> from <old> to
<new>"); `keeper` không tự đoán "gói nào là dev theo tên gói" — đo bằng cách đọc `[dependency-groups] dev` /
`[tool.uv] dev-dependencies` / `[project.optional-dependencies] dev` của MỌI `pyproject.toml` trong workspace,
đúng yêu cầu §5. `uv.lock` chỉ dùng để biết gói nào thật sự có trong khoá (lọc bớt gói không liên quan còn
trong alert cũ).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Protocol

from .events import SemverJump, Signal
from .github import DependabotAlert

_BUMP_RE = re.compile(
    r"bump\s+(?P<pkg>[\w][\w.\-]*)\s+from\s+(?P<old>\d+(?:\.\d+){0,2}\S*)\s+to\s+(?P<new>\d+(?:\.\d+){0,2}\S*)",
    re.IGNORECASE,
)


class GitHubLike(Protocol):
    def dependabot_alerts(self) -> list[DependabotAlert] | None: ...


def _norm(name: str) -> str:
    """Tên gói PyPI so khớp không phân biệt hoa/thường và `_`/`-` (chuẩn PEP 503)."""
    return name.strip().lower().replace("_", "-")


def _version_tuple(v: str) -> tuple[int, ...] | None:
    """Phần SỐ ở đầu chuỗi version. Hậu tố (`rc1`, `.post1`, `.dev0`, `+local`) bị bỏ — xem `semver_jump`."""
    m = re.match(r"^\d+(\.\d+){0,2}", v)
    if not m:
        return None
    return tuple(int(x) for x in m.group(0).split("."))


def semver_jump(old: str, new: str) -> SemverJump | None:
    """`None` khi không parse được cả hai — không đoán mù.

    `None` CŨNG cho trường hợp ba số bằng nhau mà chuỗi khác nhau: `1.2.3` → `1.2.3rc1`, `2.0.0` → `2.0.0.post1`.
    `_version_tuple` chỉ đọc phần số, nên nếu cứ rơi xuống nhánh cuối thì hai ca đó bị gọi là `"patch"` — một
    bump vá lỗi không hề xảy ra. `keeper` xếp bậc rủi ro theo `semver_jump`, nên một `"patch"` sai ở đây thành
    một patch **tự merge** cho thứ chưa phải bản phát hành. Không phân loại còn hơn phân loại sai."""
    ov, nv = _version_tuple(old), _version_tuple(new)
    if ov is None or nv is None:
        return None
    if ov == nv:
        return None
    ov = (*ov, 0, 0, 0)[:3]
    nv = (*nv, 0, 0, 0)[:3]
    if nv[0] != ov[0]:
        return "major"
    if nv[1] != ov[1]:
        return "minor"
    return "patch"


def locked_packages(repo: Path) -> set[str]:
    """Tên gói (đã chuẩn hoá) có mặt trong `uv.lock`. Rỗng nếu không có file — không ném lỗi, scout chỉ báo
    những gì đọc được."""
    lock = repo / "uv.lock"
    if not lock.exists():
        return set()
    try:
        data = tomllib.loads(lock.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return set()
    return {_norm(p["name"]) for p in data.get("package", []) if isinstance(p, dict) and "name" in p}


def dev_package_names(repo: Path) -> set[str]:
    """Tên gói (đã chuẩn hoá) khai trong `[dependency-groups] dev`, `[tool.uv] dev-dependencies`, hoặc
    `[project.optional-dependencies] dev` của MỌI `pyproject.toml` dưới `repo` (bỏ qua `.venv`/`node_modules`)."""
    names: set[str] = set()
    for path in repo.rglob("pyproject.toml"):
        parts = path.relative_to(repo).parts
        if any(p in {".venv", "node_modules", ".git"} for p in parts):
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            continue
        raw: list[str] = []
        raw += data.get("dependency-groups", {}).get("dev", [])
        raw += data.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
        raw += data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
        for entry in raw:
            pkg = re.split(r"[<>=!~;\[\s]", entry.strip(), maxsplit=1)[0]
            if pkg:
                names.add(_norm(pkg))
    return names


def scan(repo: Path, gh: GitHubLike) -> list[Signal]:
    """Một `Signal` cho mỗi dependabot alert parse được thành `Bump X from A to B`, giới hạn ở gói thật sự có
    trong `uv.lock` (khi có `uv.lock` để lọc theo)."""
    locked = locked_packages(repo)
    dev_names = dev_package_names(repo)
    out: list[Signal] = []
    # `None` (gh không trả lời) → không tín hiệu: scout chỉ quan sát, như `health.pr_age_signals`. Kết luận
    # "không có lỗ hổng" là việc của `audit`, và nó báo lỗi công cụ cho đúng ca này.
    for alert in gh.dependabot_alerts() or []:
        if alert.state != "open":  # fixed/dismissed không phải việc phải làm — cùng luật audit.dependabot_findings
            continue
        m = _BUMP_RE.search(alert.summary)
        if not m:
            continue
        pkg = m.group("pkg")
        norm = _norm(pkg)
        if locked and norm not in locked:
            continue
        jump = semver_jump(m.group("old"), m.group("new"))
        out.append(
            Signal(
                subject=pkg,
                kind="dependency",
                detail=alert.summary,
                semver_jump=jump,
                is_dev=norm in dev_names,
                evidence=f"dependabot#{alert.number}",
            )
        )
    return out
