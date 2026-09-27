"""CHANGELOG — cổng chặn PR khi dòng CHANGELOG của nó chưa mang `(#<số PR này>)` (audit 2026-09-27 C1).

Bước cũ của `pr-policy.yml` chỉ kiểm CHANGELOG.md CÓ ĐỔI; job `drift-check` (keeper, phép c) tìm `(#n)` SAU merge,
nên quên điền số chỉ lộ khi `main` đã đỏ — run 36253134720 của #353, 36261710782 của #357.
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
    assert _load().check(DIFF_CO_SO, "361", "") is None


def test_dong_them_thieu_so_pr_thi_do_va_noi_ro_so_can_dien():
    """Đúng ca #353/#357: có dòng CHANGELOG nhưng quên `(#n)` — bước cũ cho qua, drift-check đỏ sau merge."""
    loi = _load().check(DIFF_CO_SO.replace("(#361)", "(#PENDING)"), "361", "")
    assert loi is not None and "(#361)" in loi


def test_so_cua_pr_khac_khong_tinh():
    """`(#36)` hay `(#3610)` không phải `(#361)`: khớp đúng chuỗi drift-check tìm, có ngoặc."""
    mod = _load()
    assert mod.check(DIFF_CO_SO.replace("(#361)", "(#36)"), "361", "") is not None
    assert mod.check(DIFF_CO_SO.replace("(#361)", "(#3610)"), "361", "") is not None


def test_so_chi_nam_o_dong_bi_xoa_khong_tinh():
    diff = DIFF_CO_SO.replace("+- fix", "-- fix")
    assert _load().check(diff, "361", "") is not None


def test_khong_doi_changelog_thi_do():
    loi = _load().check("", "361", "")
    assert loi is not None and "không đổi CHANGELOG.md" in loi


def test_nhan_no_changelog_mien():
    assert _load().check("", "361", "dependencies,no-changelog") is None


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def _run(cwd: Path, pr: str, labels: str = "") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "BASE": "main", "PR": pr, "LABELS": labels, "PYTHONIOENCODING": "utf-8"}
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
    with (clone / "CHANGELOG.md").open("a", encoding="utf-8") as f:
        f.write("- fix(company): sửa (#PENDING).\n")
    _git(clone, "commit", "-q", "-am", "thiếu số")

    r = _run(clone, "361")
    assert r.returncode == 1 and "(#361)" in r.stderr

    (clone / "CHANGELOG.md").write_text(
        (clone / "CHANGELOG.md").read_text(encoding="utf-8").replace("(#PENDING)", "(#361)"), encoding="utf-8"
    )
    _git(clone, "commit", "-q", "-am", "điền số")
    r = _run(clone, "361")
    assert r.returncode == 0, r.stderr

    assert _run(tmp_path, "361", "no-changelog").returncode == 0, "nhãn miễn không cần tới git"
