"""Cổng cho lớp hàng rào lấy từ `seeker19110/project-template`: `scripts/dev-task.sh` + `.claude/hooks/`.

Vì sao cần: `AGENTS.md` có 8 luật cấm rất chặt (không push `main`, không commit `llm.yaml`/`*.sqlite`, không hạ
`fail_under`) nhưng trước bộ này **không một cơ chế nào thi hành** chúng — tất cả dựa vào agent tự nhớ, CI bắt
sau khi đã push. Hook chặn tại chỗ gõ lệnh; test này canh chính hook, vì một hook trỏ sai đường dẫn là cổng
chết im lặng — nguy hiểm hơn không có cổng (cùng lý do `test_cong_repo.py`).

Đặt ở `platform/console/tests/` theo đúng lối `test_cong_repo.py`/`test_readme_goc.py`: console là nơi repo đặt
các phép canh cấp gốc.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEV_TASK = ROOT / "scripts" / "dev-task.sh"
HOOKS = ROOT / ".claude" / "hooks"
SETTINGS = ROOT / ".claude" / "settings.json"


def _bash_chay_duoc(ung_vien: str) -> bool:
    """Thử THẬT: viết một script vào thư mục tạm rồi bảo `ung_vien` chạy nó bằng đúng đường dẫn hệ điều hành.

    Không hỏi "đây có phải Git Bash không" (đoán theo tên/đường dẫn thì sai khi người ta cài chỗ khác), mà hỏi
    "cái này chạy được cái mà test sắp truyền vào không".
    """
    with tempfile.TemporaryDirectory() as d:
        s = Path(d) / "probe.sh"
        s.write_text("echo ok\n", encoding="utf-8")
        try:
            kq = subprocess.run(
                [ung_vien, str(s)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return kq.returncode == 0 and "ok" in kq.stdout


def _tim_bash() -> str | None:
    """Bash chạy được đường dẫn kiểu Windows — KHÔNG phải cái đầu tiên trong PATH.

    Trên máy Windows có WSL, `shutil.which("bash")` hay trả stub `AppData/Local/Microsoft/WindowsApps/bash.exe`
    — TUỲ thứ tự PATH của phiên shell, nên nó đỏ chập chờn: cùng một commit, chạy chỗ này xanh chỗ kia đỏ.
    Stub ấy chuyển tiếp vào WSL, nơi `C:\\Users\\x\\a.sh` bị nuốt hết dấu `\\` thành `C:Usersxa.sh` → 127 cho
    MỌI ca của file này (đo 2026-09-14: 51/73 đỏ trên máy phát triển, trong khi CI ubuntu xanh — cổng chết im
    lặng, đúng khuôn nguy hiểm mà chính file này được dựng để chặn).

    Git Bash hiểu đường dẫn Windows. Vị trí của nó suy từ `git --exec-path` (`<git>/mingw64/libexec/git-core`)
    chứ không đoán `C:\\Program Files`, để máy cài git chỗ khác vẫn đúng.
    """
    ung_vien: list[str] = []
    if (b := shutil.which("bash")) is not None:
        ung_vien.append(b)
    if os.name == "nt":
        try:
            ep = subprocess.run(
                ["git", "--exec-path"], capture_output=True, text=True, check=True, timeout=30
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ep = ""
        if ep:
            goc = Path(ep).parents[2]
            ung_vien += [str(goc / "bin" / "bash.exe"), str(goc / "usr" / "bin" / "bash.exe")]
    return next((c for c in ung_vien if _bash_chay_duoc(c)), None)


BASH = _tim_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="cần bash (Git Bash trên Windows) để chạy hook")

# Năm package của workspace và module mypy tương ứng — nguồn đối chiếu cho dev-task.sh.
GOI = {
    "company": ("companies/software-company", "company"),
    "gateway": ("platform/gateway", "gateway"),
    "console": ("platform/console", "console"),
    "core": ("platform/xagents-core", "xagents_core"),
    "keeper": ("companies/keeper", "keeper"),
}


def _chay(script: Path, *args: str, stdin: str = "", **moi_truong: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), **moi_truong}
    assert BASH is not None
    return subprocess.run(
        [BASH, str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # hook in tiếng Việt ra stderr; mặc định Windows là cp1252 → vỡ, stderr thành None
        env=env,
        cwd=ROOT,
    )


def _payload(cmd: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})


def _git(kho: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(kho), *args], check=True, capture_output=True)


@pytest.fixture
def kho_main(tmp_path: Path) -> Path:
    """Một repo git rỗng đang đứng trên nhánh `main` — để thử luật cấm 1 mà không đụng repo thật."""
    kho = tmp_path / "kho"
    kho.mkdir()
    _git(kho, "init", "-q", "-b", "main")
    _git(kho, "config", "user.email", "t@t")
    _git(kho, "config", "user.name", "t")
    return kho


# Dạng gọn một dòng mà phần lớn repo dùng — `ruff format` tách nó thành hai dòng.
GON = "a = 1; b = 2\n"


def _file_da_commit(kho: Path, ten: str, noi_dung: str) -> Path:
    f = kho / ten
    f.write_text(noi_dung, encoding="utf-8")
    _git(kho, "add", ten)
    _git(kho, "commit", "-qm", "nen")
    return f


# --- scripts/dev-task.sh ----------------------------------------------------


def test_dev_task_ton_tai_va_chay_duoc() -> None:
    assert DEV_TASK.is_file(), "AGENTS.md §3 bắt nhớ ba lệnh CI khác nhau cho năm package — cần một điểm vào"


def test_dev_task_task_la_bao_loi() -> None:
    kq = _chay(DEV_TASK, "khong-co-task-nay")
    assert kq.returncode == 2, f"task lạ phải exit 2, nhận {kq.returncode}: {kq.stderr}"


def test_dev_task_thieu_task_bao_loi() -> None:
    assert _chay(DEV_TASK).returncode == 2


def test_dev_task_entrypoint_is_executable_in_git() -> None:
    result = subprocess.run(["git", "ls-files", "-s", "scripts/dev-task.sh"], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    assert result.stdout.startswith("100755 "), "documented direct gate command needs executable Git mode"


@pytest.mark.parametrize("goi", sorted(GOI))
def test_dev_task_lint_dung_lenh_ci_cua_tung_goi(goi: str) -> None:
    """Lệnh in ra phải khớp AGENTS.md §3 — sai một chữ là cổng cục bộ khác cổng CI."""
    thu_muc, _ = GOI[goi]
    kq = _chay(DEV_TASK, "lint", goi, DEV_TASK_DRY_RUN="1")
    assert kq.returncode == 0, kq.stderr
    assert "uv run ruff check src tests" in kq.stdout
    assert thu_muc in kq.stdout


@pytest.mark.parametrize("goi", sorted(GOI))
def test_dev_task_typecheck_dung_module(goi: str) -> None:
    _, module = GOI[goi]
    kq = _chay(DEV_TASK, "typecheck", goi, DEV_TASK_DRY_RUN="1")
    assert kq.returncode == 0, kq.stderr
    assert f"uv run mypy src/{module}" in kq.stdout
    assert ("--ignore-missing-imports" in kq.stdout) == (goi != "core")


@pytest.mark.parametrize("goi", sorted(GOI))
def test_dev_task_test_luon_do_coverage(goi: str) -> None:
    """CI chạy `--cov` cho CẢ NĂM package (ci.yml) — cổng cục bộ thiếu `--cov` là cổng khác cổng CI.

    `fail_under = 100` chỉ có hiệu lực khi có `--cov`; bỏ nó đi thì cổng cục bộ xanh trong khi CI đỏ.
    """
    assert "--cov" in _chay(DEV_TASK, "test", goi, DEV_TASK_DRY_RUN="1").stdout


def test_dev_task_chi_software_company_chay_xdist() -> None:
    """`-n auto` chỉ software-company (ci.yml): bộ test của nó nặng I/O, các gói khác chạy tuần tự."""
    assert "-n auto" in _chay(DEV_TASK, "test", "company", DEV_TASK_DRY_RUN="1").stdout
    assert "-n auto" not in _chay(DEV_TASK, "test", "gateway", DEV_TASK_DRY_RUN="1").stdout


def test_dev_task_gate_chay_du_ba_cong_dung_thu_tu() -> None:
    kq = _chay(DEV_TASK, "gate", "console", DEV_TASK_DRY_RUN="1")
    assert kq.returncode == 0, kq.stderr
    vi_tri = [kq.stdout.find(x) for x in ("ruff check", "mypy", "pytest")]
    assert all(v >= 0 for v in vi_tri), f"gate thiếu bước: {kq.stdout}"
    assert vi_tri == sorted(vi_tri), f"gate sai thứ tự lint→typecheck→test: {kq.stdout}"


def test_dev_task_gate_khong_goi_chay_ca_nam_package() -> None:
    ra = _chay(DEV_TASK, "gate", DEV_TASK_DRY_RUN="1").stdout
    for thu_muc, _ in GOI.values():
        assert thu_muc in ra, f"gate toàn workspace bỏ sót {thu_muc}"


def test_moi_thu_muc_goi_trong_dev_task_ton_tai_that() -> None:
    """Cải tổ thư mục #262 từng làm mọi đường dẫn trỏ vào hư không — không để lặp lại ở đây."""
    than = DEV_TASK.read_text(encoding="utf-8")
    for thu_muc, module in GOI.values():
        assert (ROOT / thu_muc).is_dir()
        assert (ROOT / thu_muc / "src" / module).is_dir()
        assert thu_muc in than, f"dev-task.sh không biết tới {thu_muc}"


def test_dev_task_format_file_chi_dong_vao_file_python(kho_main: Path) -> None:
    for ten in ("b.py", "b.md"):
        (kho_main / ten).write_text(GON, encoding="utf-8")
    assert "ruff format" in _chay(DEV_TASK, "format-file", str(kho_main / "b.py"), DEV_TASK_DRY_RUN="1").stdout
    assert "ruff format" not in _chay(DEV_TASK, "format-file", str(kho_main / "b.md"), DEV_TASK_DRY_RUN="1").stdout


# format-file chỉ format file VỐN ĐÃ SẠCH `ruff format` trước lần sửa. Phần lớn repo viết gọn một dòng
# (`a = 1; b = 2`, `if x: return`) và CI chỉ chạy `ruff check`, không `ruff format --check` — format cả file sau
# một lần Edit là diff phình cả trăm dòng không ai yêu cầu (luật cấm 7). Đo 2026-09-27: sửa 5 dòng
# `orch/guards.py` thành +82, sửa 6 dòng `workspace.py` thành +212; 2026-09-26: `orch/gates_flow.py` 399 → 591
# dòng, vượt trần 400 của `test_orch_khuon_loi.py`.


def test_format_file_khong_dong_vao_file_chua_sach_format(kho_main: Path) -> None:
    """Bản trong index chưa sạch `ruff format` → không format: sửa một dòng không được kéo theo cả file."""
    f = _file_da_commit(kho_main, "gon.py", GON)
    sau_sua = GON + "c = 3; d = 4\n"
    f.write_text(sau_sua, encoding="utf-8")
    kq = _chay(DEV_TASK, "format-file", str(f))
    assert kq.returncode == 0, kq.stderr
    assert f.read_text(encoding="utf-8") == sau_sua, "format-file định dạng lại cả file vốn chưa sạch"


def test_format_file_van_format_file_von_sach(kho_main: Path) -> None:
    """Chiều kia: file vốn sạch vẫn được giữ sạch — lần sửa lệch format thì hook sửa lại, như trước."""
    f = _file_da_commit(kho_main, "sach.py", "a = 1\n")
    f.write_text("a = 1\nb=2\n", encoding="utf-8")
    assert _chay(DEV_TASK, "format-file", str(f)).returncode == 0
    assert f.read_text(encoding="utf-8") == "a = 1\nb = 2\n"


def test_format_file_van_format_file_moi_chua_track(kho_main: Path) -> None:
    """File mới chưa track: cả file là của lần sửa này, format không đụng code của ai."""
    f = kho_main / "moi.py"
    f.write_text(GON, encoding="utf-8")
    assert _chay(DEV_TASK, "format-file", str(f)).returncode == 0
    assert f.read_text(encoding="utf-8") == "a = 1\nb = 2\n"


def test_format_file_ngoai_repo_git_thi_bo_qua(tmp_path: Path) -> None:
    """Không có git thì không biết bản trước khi sửa → không format: không chắc thì đừng đụng."""
    f = tmp_path / "le.py"
    f.write_text(GON, encoding="utf-8")
    assert _chay(DEV_TASK, "format-file", str(f), GIT_CEILING_DIRECTORIES=str(tmp_path.parent)).returncode == 0
    assert f.read_text(encoding="utf-8") == GON


# --- .claude/hooks/block-dangerous-git.sh -----------------------------------

CHAN_GIT = HOOKS / "block-dangerous-git.sh"


@pytest.mark.parametrize(
    "cmd",
    [
        "git push --force origin main",
        "git push -f origin main",
        "git push --force-with-lease origin main",
        "git push origin main",
        "git push origin HEAD:main",
        "git reset --hard origin/main",
        "git merge --abort",
        "git rebase --abort",
        "git cherry-pick --abort",
        # tách theo đoạn lệnh không được làm lọt push vào main nằm ở đoạn sau
        "git status && git push origin main",
        "git push origin feat-x; git push origin main",
        "git fetch | git push -f origin main",
    ],
)
def test_chan_git_chan_dung_khuon_cam(cmd: str) -> None:
    """Luật cấm 1 (`main`) và `CLAUDE.md` §8 (`reset --hard`, `--abort`) — exit 2 = chặn."""
    kq = _chay(CHAN_GIT, stdin=_payload(cmd))
    assert kq.returncode == 2, f"đáng lẽ chặn: {cmd} (exit {kq.returncode})"


@pytest.mark.parametrize(
    "cmd",
    [
        "git status --short",
        "git log --oneline -5",
        "git push origin worktree-abc",
        "git push --force-with-lease origin worktree-abc",
        "git commit -m 'nói về git reset --hard trong message'",
        "echo 'git push origin main'",
        "git diff main...HEAD",
        # đo được 2026-09-26: `main` ở lệnh KHÁC trong cùng dòng (đích PR của gh) bị đọc thành đích push
        "git push -u origin feat-x && gh pr create --base main --title t",
        "git push origin feat-x || git log main",
    ],
)
def test_chan_git_khong_chan_oan(cmd: str) -> None:
    """Chặn oan làm agent tưởng repo hỏng rồi đi đường vòng — tệ hơn không chặn."""
    kq = _chay(CHAN_GIT, stdin=_payload(cmd))
    assert kq.returncode == 0, f"chặn oan: {cmd}\n{kq.stderr}"


def test_chan_git_co_duong_thoat_tuong_minh() -> None:
    kq = _chay(CHAN_GIT, stdin=_payload("git reset --hard"), ALLOW_DANGEROUS_GIT="1")
    assert kq.returncode == 0


def test_chan_git_thieu_jq_thi_noi_ra() -> None:
    """Fail-open IM LẶNG là cái bẫy: người tưởng hàng rào đang canh suốt phiên (template F-007)."""
    kq = _chay(CHAN_GIT, stdin=_payload("git reset --hard"), PATH="/nonexistent")
    assert kq.returncode == 0
    assert "jq" in kq.stderr


# --- .claude/hooks/pre-commit-gate.sh ---------------------------------------

CONG_COMMIT = HOOKS / "pre-commit-gate.sh"


def _cong(cmd: str, kho: Path, _cwd: str | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    """`kho` = cây mặc định (cwd và `CLAUDE_PROJECT_DIR`); `_cwd` tách hai thứ đó ra khi cần thử worktree."""
    assert BASH is not None
    cwd = _cwd if _cwd is not None else str(kho)
    return subprocess.run(
        [BASH, str(CONG_COMMIT)],
        input=_payload(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(kho), "DEV_TASK_DRY_RUN": "1", **env},
        cwd=cwd,
    )


def test_cong_commit_chan_khi_dang_dung_tren_main(kho_main: Path) -> None:
    """Luật cấm 1: commit thẳng `main` — bắt TRƯỚC khi commit, không đợi ruleset từ chối lúc push."""
    kq = _cong("git commit -m 'x'", kho_main)
    assert kq.returncode == 2, kq.stderr + kq.stdout
    assert "main" in kq.stderr


def test_cong_commit_cho_qua_tren_nhanh_rieng(kho_main: Path) -> None:
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    assert _cong("git commit -m 'x'", kho_main).returncode == 0


@pytest.mark.parametrize("ten", ["llm.yaml", "media.yaml", "company.sqlite", "a/b/llm.yaml"])
def test_cong_commit_chan_file_cam_trong_staged(kho_main: Path, ten: str) -> None:
    """Luật cấm 3: gitleaks quét cả lịch sử — lỡ commit rồi xoá vẫn đỏ, nên phải chặn trước khi vào lịch sử."""
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    f = kho_main / ten
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    _git(kho_main, "add", "-f", ten)
    kq = _cong("git commit -m 'x'", kho_main)
    assert kq.returncode == 2, f"đáng lẽ chặn {ten}"
    assert ten.split("/")[-1] in kq.stderr


def test_cong_commit_chan_ha_nguong_coverage(kho_main: Path) -> None:
    """Luật cấm 6: `fail_under = 100`, mất một dòng phủ thì thêm test — không hạ số."""
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    (kho_main / "pyproject.toml").write_text("fail_under = 100\n", encoding="utf-8")
    _git(kho_main, "add", "pyproject.toml")
    _git(kho_main, "commit", "-qm", "nen")
    (kho_main / "pyproject.toml").write_text("fail_under = 95\n", encoding="utf-8")
    _git(kho_main, "add", "pyproject.toml")
    kq = _cong("git commit -m 'x'", kho_main)
    assert kq.returncode == 2, "hạ fail_under phải bị chặn"
    assert "fail_under" in kq.stderr


def test_cong_commit_bo_qua_khi_co_no_verify(kho_main: Path) -> None:
    assert _cong("git commit --no-verify -m 'x'", kho_main).returncode == 0


def test_cong_commit_khong_dong_vao_lenh_khac(kho_main: Path) -> None:
    assert _cong("git status", kho_main).returncode == 0


def test_cong_commit_chi_chay_cong_cua_goi_bi_dung(kho_main: Path) -> None:
    """Chạy cổng cả năm package trước MỖI commit mất nhiều phút — agent sẽ tìm cách né, hàng rào thành vô dụng.

    Cổng chỉ chạy cho package có file trong diff staged.
    """
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    f = kho_main / "platform" / "console" / "src" / "console" / "x.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x = 1\n", encoding="utf-8")
    _git(kho_main, "add", "-A")
    kq = _cong("git commit -m 'x'", kho_main)
    assert kq.returncode == 0, kq.stderr
    assert "console" in kq.stderr, f"không nói nó chạy cổng cho gói nào: {kq.stderr}"
    assert "gateway" not in kq.stderr, f"chạy cổng cho gói không đụng tới: {kq.stderr}"


def test_cong_commit_doi_file_goc_thi_chay_ca_workspace(kho_main: Path) -> None:
    """Đổi `pyproject.toml`/`Makefile` ở gốc ảnh hưởng mọi gói → không được chạy cổng hẹp rồi báo xanh."""
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    (kho_main / "Makefile").write_text("x:\n", encoding="utf-8")
    _git(kho_main, "add", "-A")
    assert "all" in _cong("git commit -m 'x'", kho_main).stderr


@pytest.fixture
def kho_worktree(kho_main: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Checkout chính đứng trên `main` + một worktree trên nhánh riêng.

    Đúng hoàn cảnh `CLAUDE.md` luật 2 bắt buộc: mỗi phiên một worktree. Trả `(chinh, worktree)`.
    """
    (kho_main / "nen.txt").write_text("x", encoding="utf-8")
    _git(kho_main, "add", "-A")
    _git(kho_main, "commit", "-qm", "nen")
    wt = tmp_path / "wt"
    _git(kho_main, "worktree", "add", "-q", "-b", "fix/thu", str(wt))
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    return kho_main, wt


def test_cong_commit_khong_chan_oan_trong_worktree(kho_worktree: tuple[Path, Path]) -> None:
    """Hook phải đọc nhánh của CÂY ĐANG COMMIT, không phải của checkout chính.

    Checkout chính đứng trên `main`; worktree đứng trên `fix/thu`. Đọc nhầm cây ⇒ chặn oan mọi commit
    đúng luật — hàng rào cản chính quy trình mà `CLAUDE.md` luật 2 bắt buộc.
    """
    chinh, wt = kho_worktree
    (wt / "a.txt").write_text("x", encoding="utf-8")
    _git(wt, "add", "-A")
    kq = _cong("git commit -m 'x'", wt, CLAUDE_PROJECT_DIR=str(chinh))
    assert kq.returncode == 0, f"chặn oan commit trên nhánh 'fix/thu': {kq.stderr}"


def test_cong_commit_van_chan_file_cam_trong_worktree(kho_worktree: tuple[Path, Path]) -> None:
    """Chiều ngược: đọc nhầm cây cũng làm index của worktree vô hình ⇒ file cấm lọt qua."""
    chinh, wt = kho_worktree
    (wt / "llm.yaml").write_text("x", encoding="utf-8")
    _git(wt, "add", "-f", "llm.yaml")
    kq = _cong("git commit -m 'x'", wt, CLAUDE_PROJECT_DIR=str(chinh))
    assert kq.returncode == 2, f"file cấm trong worktree lọt qua cổng: {kq.stderr}"
    assert "llm.yaml" in kq.stderr


def test_cong_commit_van_chan_ha_nguong_trong_worktree(kho_worktree: tuple[Path, Path]) -> None:
    """Phép 3 cũng đọc index — cùng một lỗi cây, nên cùng phải có ca."""
    chinh, wt = kho_worktree
    (wt / "pyproject.toml").write_text("fail_under = 100\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "nen")
    (wt / "pyproject.toml").write_text("fail_under = 90\n", encoding="utf-8")
    _git(wt, "add", "-A")
    kq = _cong("git commit -m 'x'", wt, CLAUDE_PROJECT_DIR=str(chinh))
    assert kq.returncode == 2, f"hạ fail_under trong worktree lọt qua: {kq.stderr}"
    assert "fail_under" in kq.stderr


def _dat_dev_task_gia(cay: Path, nhan: str, ma_thoat: int) -> None:
    """`scripts/dev-task.sh` giả cho một cây: khai nó là bản của cây nào, và `CLAUDE_PROJECT_DIR` trỏ cây nào.

    Cả hai đều phải là worktree: `dev-task.sh` thật lấy cây để `cd` từ `CLAUDE_PROJECT_DIR`, không từ vị trí của
    chính nó — gọi đúng bản của worktree mà để biến trỏ checkout chính vẫn là chạy cổng trên code khác.
    `nhan-cay.txt` không staged, nên không làm hook đổi gói phải chạy.
    """
    (cay / "nhan-cay.txt").write_text(nhan, encoding="utf-8")
    s = cay / "scripts" / "dev-task.sh"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "dev-task-gia ban={nhan} du_an=$(cat "$CLAUDE_PROJECT_DIR/nhan-cay.txt" 2>/dev/null) $*" >&2\n'
        f"exit {ma_thoat}\n",
        encoding="utf-8",
        newline="\n",
    )
    s.chmod(0o755)


def _stage_file_console(wt: Path) -> None:
    f = wt / "platform" / "console" / "src" / "console" / "x.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x = 1\n", encoding="utf-8")
    _git(wt, "add", "platform/console/src/console/x.py")


def test_cong_commit_chay_cong_tren_worktree_khong_phai_checkout_chinh(kho_worktree: tuple[Path, Path]) -> None:
    """Phép 4 phải chạy `dev-task.sh gate` trên CÂY ĐANG COMMIT, không trên checkout chính.

    Đo 2026-09-27 từ worktree `release-bang-chung`: hook đỏ với `uv trampoline failed to canonicalize script
    path` ở `uv run mypy` — venv của checkout chính (Python 3.11, mypy.exe cũ), trong khi cùng cổng chạy thẳng
    trong worktree xanh. Checkout chính đỏ vì lý do không dính gì tới diff → chặn oan.
    """
    chinh, wt = kho_worktree
    _dat_dev_task_gia(chinh, "chinh", 1)
    _dat_dev_task_gia(wt, "worktree", 0)
    _stage_file_console(wt)
    kq = _cong("git commit -m 'x'", wt, CLAUDE_PROJECT_DIR=str(chinh))
    ra = kq.stdout + kq.stderr
    assert kq.returncode == 0, f"cổng chạy trên checkout chính, chặn oan: {ra}"
    assert "ban=worktree" in ra, f"không gọi dev-task.sh của worktree: {ra}"
    assert "du_an=worktree" in ra, f"CLAUDE_PROJECT_DIR của dev-task.sh vẫn trỏ checkout chính: {ra}"
    cay = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert f"(cây {cay})" in kq.stderr, f"hook không nói cổng chạy trên cây nào: {kq.stderr}"


def test_cong_commit_van_chan_khi_worktree_do_du_checkout_chinh_xanh(kho_worktree: tuple[Path, Path]) -> None:
    """Chiều nguy hiểm hơn của cùng lỗi: code của checkout chính xanh thì cổng xanh, dù code đang commit đỏ."""
    chinh, wt = kho_worktree
    _dat_dev_task_gia(chinh, "chinh", 0)
    _dat_dev_task_gia(wt, "worktree", 1)
    _stage_file_console(wt)
    kq = _cong("git commit -m 'x'", wt, CLAUDE_PROJECT_DIR=str(chinh))
    assert kq.returncode == 2, f"code worktree đỏ mà cổng cho qua nhờ code checkout chính: {kq.stdout + kq.stderr}"


def test_cong_commit_worktree_thieu_dev_task_thi_lui_ve_root(kho_worktree: tuple[Path, Path]) -> None:
    """Cây đang commit không có `scripts/dev-task.sh` (nhánh cũ, repo khác) → lùi về bản của `$ROOT`, như trước.

    Không có lối lùi thì hook gọi một đường dẫn không tồn tại → 127 → chặn mọi commit ở cây đó.
    """
    chinh, wt = kho_worktree
    _dat_dev_task_gia(chinh, "chinh", 0)
    _stage_file_console(wt)
    kq = _cong("git commit -m 'x'", wt, CLAUDE_PROJECT_DIR=str(chinh))
    ra = kq.stdout + kq.stderr
    assert kq.returncode == 0, f"thiếu dev-task.sh ở worktree mà không lùi về ROOT: {ra}"
    assert "ban=chinh du_an=chinh" in ra, ra


def test_cong_commit_lui_ve_root_khi_cwd_khong_phai_repo(kho_main: Path, tmp_path: Path) -> None:
    """`git rev-parse --show-toplevel` rỗng ngoài repo → phải lùi về `CLAUDE_PROJECT_DIR`, không buông cổng."""
    ngoai = tmp_path / "ngoai"
    ngoai.mkdir()
    kq = _cong("git commit -m 'x'", kho_main, _cwd=str(ngoai))
    assert kq.returncode == 2, f"mất phép kiểm nhánh khi cwd ngoài repo: {kq.stderr}"
    assert "main" in kq.stderr


# --- .claude/hooks/auto-format.sh -------------------------------------------

DINH_DANG = HOOKS / "auto-format.sh"


def test_auto_format_khong_bao_gio_can_luong() -> None:
    """Hook format mà chặn được luồng là hook sai: nó chạy sau MỌI lần sửa file."""
    for payload in ('{"tool_input":{"file_path":"a.py"}}', "{}", "khong-phai-json"):
        kq = subprocess.run(
            [str(BASH), str(DINH_DANG)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), "DEV_TASK_DRY_RUN": "1"},
            cwd=ROOT,
        )
        assert kq.returncode == 0, f"auto-format trả {kq.returncode} với payload {payload!r}"


def test_auto_format_khong_lam_phinh_file_chua_sach(kho_main: Path) -> None:
    """Đường thật của lỗi: Edit → hook PostToolUse → `dev-task.sh format-file`. Đo qua chính hook."""
    f = _file_da_commit(kho_main, "gon.py", GON)
    sau_sua = GON + "c = 3; d = 4\n"
    f.write_text(sau_sua, encoding="utf-8")
    kq = _chay(DINH_DANG, stdin=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(f)}}))
    assert kq.returncode == 0, kq.stderr
    assert f.read_text(encoding="utf-8") == sau_sua, "hook auto-format định dạng lại cả file vốn chưa sạch"


# --- .claude/settings.json --------------------------------------------------


def test_moi_hook_khai_trong_settings_ton_tai_that() -> None:
    """Hook trỏ sai đường dẫn = cổng chết im lặng, đúng khuôn lỗi `test_cong_repo.py` canh."""
    cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    lenh = [h["command"] for nhom in cfg.get("hooks", {}).values() for muc in nhom for h in muc["hooks"]]
    assert lenh, "settings.json chưa nối hook nào — hàng rào không được bật"
    for mot_lenh in lenh:
        duong_dan = mot_lenh.replace("${CLAUDE_PROJECT_DIR}/", "").split()[0]
        assert (ROOT / duong_dan).is_file(), f"settings.json trỏ vào hook không tồn tại: {duong_dan}"


def test_moi_hook_deu_co_test_trong_file_nay() -> None:
    """Thêm hook mà quên test = thêm một cổng không ai biết nó còn sống không."""
    than = Path(__file__).read_text(encoding="utf-8")
    for hook in sorted(HOOKS.glob("*.sh")):
        assert hook.name in than, f"hook {hook.name} chưa có test nào trong test_cong_khung.py"


def test_moi_script_sh_duoc_chot_eol_lf() -> None:
    """Máy phát triển là Windows: `.sh` lọt vào repo với CRLF thì bash trên CI Linux báo `\\r: command not found`.

    Hook vỡ theo kiểu này KHÔNG đỏ ở đâu cả — nó chỉ lặng lẽ không canh gì nữa.
    """
    scripts = [
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in [*(ROOT / "scripts").glob("*.sh"), *HOOKS.glob("*.sh"), *(ROOT / "docker").glob("*.sh")]
    ]
    assert scripts
    kq = subprocess.run(
        ["git", "-C", str(ROOT), "check-attr", "eol", "--", *scripts],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    hong = [d for d in kq.stdout.splitlines() if not d.endswith(": eol: lf")]
    assert not hong, f".gitattributes chưa chốt eol=lf cho: {hong}"


# --- .claude/commands/ ------------------------------------------------------

LENH = ROOT / ".claude" / "commands"
_DUONG_DAN = re.compile(r"`((?:scripts|docs|platform|companies)/[\w./-]+)`")


@pytest.mark.parametrize("f", sorted(LENH.glob("*.md")), ids=lambda p: p.name)
def test_moi_slash_command_co_description(f: Path) -> None:
    """Không có `description:` thì lệnh không hiện trong danh sách — viết xong mà không ai gọi được."""
    than = f.read_text(encoding="utf-8")
    assert than.startswith("---"), f"{f.name} thiếu frontmatter"
    assert "description:" in than.split("---")[1], f"{f.name} thiếu description"


@pytest.mark.parametrize("f", sorted(LENH.glob("*.md")), ids=lambda p: p.name)
def test_slash_command_khong_tro_vao_duong_dan_khong_ton_tai(f: Path) -> None:
    """Lệnh bảo agent chạy một script không tồn tại = agent đi bịa lệnh thay thế."""
    hong = [dd for dd in _DUONG_DAN.findall(f.read_text(encoding="utf-8")) if not (ROOT / dd).exists()]
    assert not hong, f"{f.name} trỏ vào đường dẫn không tồn tại: {hong}"


@pytest.mark.parametrize("ten", ["gate", "debug", "adr", "no-ky-thuat"])
def test_co_du_cac_lenh_bat_buoc(ten: str) -> None:
    assert (LENH / f"{ten}.md").is_file(), f"thiếu /{ten}"


# --- luật phát cho mọi harness ----------------------------------------------


@pytest.mark.parametrize("ten", [".cursorrules", "GEMINI.md", ".windsurfrules", ".clinerules"])
def test_file_luat_cho_harness_khac_tro_ve_agents_md(ten: str) -> None:
    """Agent không phải Claude Code cũng phải đọc đúng một nguồn luật, không tự suy diễn."""
    f = ROOT / ten
    assert f.is_file(), f"thiếu {ten}: agent khác Claude Code vào repo không biết luật ở đâu"
    assert "AGENTS.md" in f.read_text(encoding="utf-8")


def test_bash_duoc_chon_chay_duoc_script_theo_duong_dan_repo(tmp_path: Path) -> None:
    """Cổng phải chọn bash chạy được **chính đường dẫn** test truyền vào, không phải bash đầu PATH.

    Trên Windows `shutil.which("bash")` hay trúng stub WSL ở `AppData/Local/Microsoft/WindowsApps`: nó nhận
    `C:\\Users\\...\\x.sh` rồi NUỐT sạch dấu `\\` (`/bin/bash: C:Usersliend...: No such file or directory`)
    và trả 127 cho MỌI ca của file này — 51/73 đỏ, đúng khuôn "chế độ hỏng không tự khai báo": cổng chết mà
    CI ubuntu vẫn xanh nên không ai thấy. Git Bash hiểu đường dẫn Windows; WSL bash thì không.
    """
    script = tmp_path / "in-ra.sh"
    script.write_text("echo CHAY_DUOC\n", encoding="utf-8")
    assert BASH is not None
    kq = subprocess.run([BASH, str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert kq.returncode == 0 and "CHAY_DUOC" in kq.stdout, (
        f"bash được chọn ({BASH}) không chạy nổi script ở {script}: rc={kq.returncode} err={kq.stderr!r}"
    )
