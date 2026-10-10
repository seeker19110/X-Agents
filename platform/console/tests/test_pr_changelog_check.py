"""CHANGELOG — cổng chặn PR khi nó không THÊM dòng nào vào `CHANGELOG.md` (AGENTS.md luật bắt buộc 10).

Không còn bắt `(#<số PR này>)` (audit 2026-10-10 F4): số PR đã nằm trong subject commit squash trên `main`, tra bằng
`git blame CHANGELOG.md`/`git log -S`. Chỗ trống kiểu `(#PENDING)` vẫn do phép (d) của `keeper drift` bắt.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "pr_changelog_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("pr_changelog_check", SCRIPT)
    assert spec and spec.loader, f"Không tải được script {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIFF_CO_SO = """diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -3,0 +4 @@
+- fix(company): recheck thoát 1 khi lượt security lỗi (#361).
"""


def test_dong_them_mang_so_pr_thi_qua():
    assert _load().check(DIFF_CO_SO, "") is None


def test_dong_them_khong_mang_so_pr_van_qua():
    """Audit 2026-10-10 F4: số PR đã nằm trong subject commit squash trên `main` (`… (#395)`), tra bằng
    `git blame CHANGELOG.md`/`git log -S`. Bắt điền tay `(#n)` chỉ tốn thêm một lượt đẩy + một lượt CI mỗi PR."""
    diff = DIFF_CO_SO.replace(" (#361).", ".")
    assert _load().check(diff, "") is None


def test_chi_xoa_dong_khong_tinh_la_them():
    """Dòng bắt đầu bằng `-` là dòng bị xoá, `+++` là tiêu đề file: không cái nào là dòng CHANGELOG mới."""
    loi = _load().check(DIFF_CO_SO.replace("+- fix", "-- fix"), "")
    assert loi is not None and "không thêm dòng nào" in loi


def test_khong_doi_changelog_thi_do():
    loi = _load().check("", "")
    assert loi is not None and "không thêm dòng nào" in loi


def test_nhan_no_changelog_mien():
    assert _load().check("", "dependencies,no-changelog") is None


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def _run(cwd: Path, labels: str = "") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "BASE": "main", "LABELS": labels, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8"
    )


def test_main_doc_diff_that_voi_origin(tmp_path):
    """Chạy như workflow: `git fetch origin <BASE>` rồi diff `origin/<BASE>...HEAD` trên một clone thật."""
    goc, clone = tmp_path / "goc", tmp_path / "clone"
    goc.mkdir()
    _git(goc, "init", "-q", "-b", "main")
    _git(goc, "config", "user.email", "t@t")
    _git(goc, "config", "user.name", "t")
    (goc / "CHANGELOG.md").write_text("# Changelog\n\n## Chưa phát hành\n", encoding="utf-8")
    _git(goc, "add", "-A")
    _git(goc, "commit", "-q", "-m", "init")
    _git(tmp_path, "clone", "-q", str(goc), str(clone))
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    _git(clone, "switch", "-q", "-c", "nhanh")
    (clone / "README.md").write_text("x\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "chưa đụng CHANGELOG")

    r = _run(clone)
    assert r.returncode == 1 and "không thêm dòng nào" in r.stderr

    with (clone / "CHANGELOG.md").open("a", encoding="utf-8") as f:
        f.write("- fix(company): sửa.\n")
    _git(clone, "commit", "-q", "-am", "thêm dòng, không số")
    r = _run(clone)
    assert r.returncode == 0, r.stderr

    assert _run(tmp_path, "no-changelog").returncode == 0, "nhãn miễn không cần tới git"
