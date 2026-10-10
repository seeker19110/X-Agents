"""CHANGELOG — cổng chặn PR khi nó không THÊM dòng nào vào `CHANGELOG.md` (AGENTS.md luật bắt buộc 10).

Chỉ kiểm "có dòng thêm" trên diff `origin/<base>...HEAD`, không kiểm `(#<số PR>)`: số PR đã nằm trong subject
commit squash trên `main` (`… (#395)`), tra bằng `git blame CHANGELOG.md` hoặc `git log -S"<dòng>"`. Bắt điền tay
số làm mỗi PR tốn thêm một lượt đẩy và một lượt CI (audit 2026-10-10 F4). Chỗ trống kiểu `(#PENDING)` vẫn bị
phép (d) của `keeper drift` bắt.

Python stdlib thuần: `python3 scripts/pr_changelog_check.py`. Env: `BASE` (nhánh đích), `LABELS` (nhãn, phẩy ngăn
cách; `no-changelog` miễn). Exit 1 và in lý do trên stderr, hoặc exit 0.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _exempt(labels: str) -> bool:
    return "no-changelog" in {x.strip() for x in labels.split(",")}


def check(diff: str, labels: str) -> str | None:
    """Lý do đỏ, hoặc `None` nếu PR qua. `diff` là `git diff <base>...HEAD -- CHANGELOG.md`."""
    if _exempt(labels):
        return None
    if any(
        ln.startswith("+") and not ln.startswith("+++")
        for ln in diff.replace("\r\n", "\n").split("\n")
    ):
        return None
    return (
        "PR không thêm dòng nào vào CHANGELOG.md. Thêm một dòng ở 'Chưa phát hành' (AGENTS.md luật bắt buộc 10), "
        "hoặc gắn nhãn no-changelog."
    )


def main() -> int:
    base, labels = os.environ["BASE"], os.environ.get("LABELS", "")
    if _exempt(labels):
        print("miễn theo nhãn no-changelog")
        return 0
    subprocess.run(["git", "fetch", "-q", "origin", base], check=True)
    diff = subprocess.run(
        ["git", "diff", f"origin/{base}...HEAD", "--", "CHANGELOG.md"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    if loi := check(diff, labels):
        print(loi, file=sys.stderr)
        return 1
    print("OK: CHANGELOG.md có dòng thêm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
