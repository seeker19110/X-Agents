"""CHANGELOG — cổng chặn PR khi dòng CHANGELOG của nó chưa mang `(#<số PR này>)` (audit 2026-09-27 C1).

Bước cũ của `pr-policy.yml` chỉ kiểm CHANGELOG.md CÓ ĐỔI. Job `drift-check` (keeper, phép c) tìm `(#n)` SAU merge,
nên quên điền số chỉ lộ khi `main` đã đỏ (run 36253134720 của #353, 36261710782 của #357). Script này tìm đúng
chuỗi drift-check tìm — `(#n)`, có ngoặc — nhưng trên dòng THÊM của diff, trước merge.

Python stdlib thuần: `python3 scripts/pr_changelog_check.py`. Env: `BASE` (nhánh đích), `PR` (số PR), `LABELS`
(nhãn, phẩy ngăn cách; `no-changelog` miễn). Exit 1 và in lý do trên stderr, hoặc exit 0.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _exempt(labels: str) -> bool:
    return "no-changelog" in {x.strip() for x in labels.split(",")}


def check(diff: str, pr: str, labels: str) -> str | None:
    """Lý do đỏ, hoặc `None` nếu PR qua. `diff` là `git diff <base>...HEAD -- CHANGELOG.md`."""
    if _exempt(labels):
        return None
    added = [
        ln[1:]
        for ln in diff.replace("\r\n", "\n").split("\n")
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    if not added:
        return (
            "PR không đổi CHANGELOG.md. Thêm một dòng ở 'Chưa phát hành' (AGENTS.md luật bắt buộc 10), "
            "hoặc gắn nhãn no-changelog."
        )
    if not any(f"(#{pr})" in ln for ln in added):
        return (
            f"Dòng CHANGELOG.md của PR chưa mang (#{pr}). Điền số rồi commit tiếp vào CHÍNH PR này (AGENTS.md "
            "luật bắt buộc 10) — thiếu nó thì job drift-check đỏ trên main ngay sau merge."
        )
    return None


def main() -> int:
    base, pr, labels = (
        os.environ["BASE"],
        os.environ["PR"],
        os.environ.get("LABELS", ""),
    )
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
    if loi := check(diff, pr, labels):
        print(loi, file=sys.stderr)
        return 1
    print(f"OK: CHANGELOG.md có dòng mang (#{pr})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
