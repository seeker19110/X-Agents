"""Cổng cho lớp hàng rào lấy từ `seeker19110/project-template`: `scripts/dev-task.sh` + `.claude/hooks/`.

Vì sao cần: `AGENTS.md` có 8 luật cấm rất chặt (không push `main`, không commit `llm.yaml`/`*.sqlite`, không hạ
`fail_under`) nhưng trước bộ này **không một cơ chế nào thi hành** chúng — tất cả dựa vào agent tự nhớ, CI bắt
sau khi đã push. Hook chặn tại chỗ gõ lệnh; test này canh chính hook, vì một hook trỏ sai đường dẫn là cổng
chết im lặng — nguy hiểm hơn không có cổng (cùng lý do `test_cong_repo.py`).

Đặt ở `platform/console/tests/` theo đúng lối `test_cong_repo.py`/`test_readme_goc.py`: console là nơi repo đặt
các phép canh cấp gốc.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest
import yaml

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
# cong_repo: file này đọc script, hook, workflow ở gốc repo → hook chạy nó cả ở chế độ nhanh (F6).
pytestmark = [
    pytest.mark.skipif(BASH is None, reason="cần bash (Git Bash trên Windows) để chạy hook"),
    pytest.mark.cong_repo,
]

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


def _mypy_ci() -> dict[str, list[str]]:
    """Thư mục gói → mọi lệnh mypy `ci.yml` chạy ở đó, đúng thứ tự (mọi job, kể cả `static`)."""
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    kq: dict[str, list[str]] = {}
    for job in ci["jobs"].values():
        for buoc in job.get("steps", []):
            run = buoc.get("run")
            if isinstance(run, str) and re.search(r"\bmypy\b", run):
                kq.setdefault(buoc.get("working-directory", "."), []).append(run.strip())
    return kq


@pytest.mark.parametrize("goi", sorted(GOI))
def test_dev_task_typecheck_chay_du_moi_lenh_mypy_cua_ci(goi: str) -> None:
    """F2 (audit 2026-10-10): từ #381 job `static` chạy mypy company HAI lần (lần hai `--extra graph`), còn
    `dev-task.sh typecheck company` chỉ một — lỗi kiểu ở `graph.py` lọt cổng cục bộ lẫn hook, chỉ lộ trên CI. Phép
    kiểm chuỗi `mypy src/<module>` ở trên không thấy vì lần một vẫn khớp. Đối chiếu nguyên danh sách: CI thêm lệnh
    mypy mà quên `dev-task.sh` thì đỏ ở đây."""
    thu_muc, _ = GOI[goi]
    kq = _chay(DEV_TASK, "typecheck", goi, DEV_TASK_DRY_RUN="1")
    assert kq.returncode == 0, kq.stderr
    cuc_bo = [d.removeprefix(f"{thu_muc}: ") for d in kq.stdout.splitlines() if d.strip()]
    assert cuc_bo == _mypy_ci()[thu_muc]


@pytest.mark.parametrize(("do_o", "con_chay_lan_hai"), [("lan-mot", False), ("lan-hai", True)])
def test_dev_task_typecheck_company_do_lan_nao_thi_do(tmp_path: Path, do_o: str, con_chay_lan_hai: bool) -> None:
    """Hai lệnh mypy cùng một task: lệnh nào đỏ thì task đỏ. `eval` cả khối hai dòng chỉ trả mã của dòng CUỐI —
    lần một đỏ, lần hai xanh là cổng báo xanh. `uv` giả ghi lại từng lần gọi, đỏ đúng ở lần được chọn."""
    bin_gia = tmp_path / "bin"
    bin_gia.mkdir()
    nhat_ky = tmp_path / "goi.txt"
    uv = bin_gia / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{nhat_ky.as_posix()}"\n'
        'case "$*" in *"--extra graph"*) lan=lan-hai ;; *) lan=lan-mot ;; esac\n'
        f'[ "$lan" = "{do_o}" ] && exit 1\n'
        "exit 0\n",
        encoding="utf-8", newline="\n",
    )
    uv.chmod(0o755)
    kq = _chay(DEV_TASK, "typecheck", "company", PATH=f"{bin_gia}{os.pathsep}{os.environ['PATH']}")
    assert kq.returncode != 0, f"mypy {do_o} đỏ mà typecheck company xanh: {kq.stderr}"
    assert ("--extra graph" in nhat_ky.read_text(encoding="utf-8")) is con_chay_lan_hai


def test_mypy_ci_doc_du_hai_lan_cua_job_static() -> None:
    """Chốt bộ đọc trước khi tin nó: đọc hụt thì phép đối chiếu trên xanh vì cả hai vế cùng ngắn."""
    static = [b["run"].strip() for b in yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml")
              .read_text(encoding="utf-8"))["jobs"]["static"]["steps"] if "mypy" in b.get("run", "")]
    assert len(static) == 2 and static == _mypy_ci()["companies/software-company"]


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


def test_dev_task_gate_dry_run_khong_bao_xanh() -> None:
    """Dry-run chỉ IN lệnh, không chạy gì — in "cổng XANH" lúc ấy là nói điều chưa đo (luật cấm 8): người lướt
    log thấy chữ XANH sẽ tin cổng đã qua."""
    kq = _chay(DEV_TASK, "gate", "console", DEV_TASK_DRY_RUN="1")
    assert kq.returncode == 0, kq.stderr
    assert "XANH" not in kq.stdout + kq.stderr, f"dry-run không chạy gì mà báo xanh: {kq.stderr}"
    assert "dry-run" in kq.stderr, f"dry-run phải nói rõ là chưa chạy gì: {kq.stderr}"


def test_dev_task_repo_gate_chi_chay_test_cong_repo_cua_console() -> None:
    """F6 (audit 2026-10-10): chế độ nhanh của cổng console cho commit chỉ sửa tài liệu/config ngoài gói. Không
    `--cov`: chạy một tập con thì `fail_under = 100` chắc chắn đỏ, và commit như vậy không đổi được độ phủ mã."""
    kq = _chay(DEV_TASK, "repo-gate", DEV_TASK_DRY_RUN="1")
    assert kq.returncode == 0, kq.stderr
    assert kq.stdout == "platform/console: uv run pytest -q -m cong_repo\n"
    assert "XANH" not in kq.stdout + kq.stderr, f"dry-run không chạy gì mà báo xanh: {kq.stderr}"


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
        # refspec đầy đủ và `+` (force theo refspec) vẫn là ghi vào main — đo được 2026-10-02: cả hai lọt
        "git push origin HEAD:refs/heads/main",
        "git push origin +main",
        "git push origin +HEAD:refs/heads/master",
    ],
)
def test_chan_git_chan_dung_khuon_cam(cmd: str) -> None:
    """Luật cấm 1 (`main`) và `AGENTS.md` §"Hàng rào thi hành" (`reset --hard`, `--abort`) — exit 2 = chặn."""
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
        # `refs/heads/` chỉ là đích khi đứng sau `:` hay đầu refspec — nhánh tên `refs/heads/main-x` thì không
        "git push origin HEAD:refs/heads/main-x",
        "git push origin +feat-x",
    ],
)
def test_chan_git_khong_chan_oan(cmd: str) -> None:
    """Chặn oan làm agent tưởng repo hỏng rồi đi đường vòng — tệ hơn không chặn."""
    kq = _chay(CHAN_GIT, stdin=_payload(cmd))
    assert kq.returncode == 0, f"chặn oan: {cmd}\n{kq.stderr}"


def test_chan_git_goi_dung_ten_force_push_qua_refspec_cong() -> None:
    """`+main` là force-push không cần cờ: thông điệp phải nói đúng là force (khuôn 1), không chỉ "push thẳng"."""
    kq = _chay(CHAN_GIT, stdin=_payload("git push origin +main"))
    assert kq.returncode == 2
    assert "force-push vào nhánh chính" in kq.stderr


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


@pytest.mark.parametrize("ten", ["llm.yaml", "media.yaml", "company.sqlite", "a/b/llm.yaml",
                                 # bản tạm/sao lưu của console (`settings._atomic_write`) mang cùng khoá API
                                 "llm.yaml.tmp", "a/llm.yaml.bak", "llm.yaml.bak.2"])
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


@pytest.mark.parametrize("ten", ["llm.example.yaml", "docs/llm.yaml.md"])
def test_cong_commit_khong_chan_nham_file_mau(kho_main: Path, ten: str) -> None:
    """Chiều ngược của phép trên: mẫu `*.example.yaml` là thứ PHẢI commit được (luật cấm 3)."""
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    f = kho_main / ten
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    _git(kho_main, "add", "-f", ten)
    assert _cong("git commit -m 'x'", kho_main).returncode == 0, f"chặn oan {ten}"


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


def _goi_cong(kq: subprocess.CompletedProcess[str]) -> set[str]:
    """Tập gói hook báo sẽ chạy cổng; rỗng khi nó bỏ qua cổng."""
    m = re.search(r"chạy cổng cho gói: (.*?) \(cây", kq.stderr)
    return set(m.group(1).split()) if m else set()


def _tao(kho: Path, *ten: str) -> None:
    for t in ten:
        f = kho / t
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n", encoding="utf-8")


def _stage(kho: Path, *ten: str) -> None:
    _git(kho, "checkout", "-q", "-b", "worktree-thu")
    _tao(kho, *ten)
    _git(kho, "add", "-A")


@pytest.mark.parametrize("ten", ["README.md", "docs/sessions/x.md", ".github/workflows/ci.yml", ".claude/hooks/x.sh",
                                 "scripts/x.py", "companies/keeper/CLAUDE.md"])
def test_cong_commit_file_khong_phai_ma_goi_van_chay_console(kho_main: Path, ten: str) -> None:
    """Console giữ cổng cấp repo: link tài liệu, README đếm test của mọi gói, hook, workflow, mẫu PR. Trước đây commit
    chỉ đụng tài liệu/`.github`/`.claude`/`scripts` bỏ qua MỌI cổng — đo 2026-09-28: gộp dòng `fail_under` của
    README làm cổng đỏ mà hook cho qua, chỉ CI bắt."""
    _stage(kho_main, ten)
    assert "console" in _goi_cong(_cong("git commit -m 'x'", kho_main))


def _goi_import() -> dict[str, set[str]]:
    """Gói → mọi gói import nó (bắc cầu), đọc từ `dependencies` của pyproject — nguồn sự thật hook phải khớp."""
    cfg = {g: tomllib.loads((ROOT / d / "pyproject.toml").read_text(encoding="utf-8"))["project"] for g, (d, _) in GOI.items()}
    ten = {c["name"]: g for g, c in cfg.items()}
    dung = {g: {ten[m.group()] for x in c.get("dependencies", []) if (m := re.match(r"[\w.-]+", x)) and m.group() in ten}
            for g, c in cfg.items()}
    kq: dict[str, set[str]] = {}
    for g in GOI:
        thay, cho = set(), [g]
        while cho:
            c = cho.pop()
            moi = {h for h in GOI if c in dung[h]} - thay
            thay |= moi
            cho += moi
        kq[g] = thay
    return kq


@pytest.mark.parametrize("goi", sorted(GOI))
def test_cong_commit_chay_goi_bi_dung_goi_import_no_va_console(kho_main: Path, goi: str) -> None:
    """Đổi một gói có thể làm đỏ gói import nó (company, keeper dùng core; console dùng company, keeper) — chạy riêng
    gói bị đụng là báo xanh điều chưa đo. Kỳ vọng tính từ pyproject: thêm phụ thuộc mà quên hook thì test này đỏ.
    Console luôn có: README đếm test của mọi gói, trần pragma/skip đếm trên mọi gói."""
    thu_muc, module = GOI[goi]
    _stage(kho_main, f"{thu_muc}/src/{module}/x.py")
    assert _goi_cong(_cong("git commit -m 'x'", kho_main)) == {goi, "console", *_goi_import()[goi]}


def test_goi_import_doc_dung_pyproject() -> None:
    """Chốt chính phép tính kỳ vọng trước khi tin nó: rỗng thì test trên xanh vì không kỳ vọng gì."""
    assert _goi_import()["core"] >= {"company", "keeper", "console"}
    assert _goi_import()["gateway"] == set()


@pytest.mark.parametrize("ten", ["docs/integrations/projects-template.lock.json", ".claude/agents/sc-x.md"])
def test_cong_commit_file_ngoai_goi_ma_company_doc_keo_company(kho_main: Path, ten: str) -> None:
    """Hai chỗ ngoài company mà test company đọc: lock template (`test_delivery_contract.py` đối chiếu với mã) và
    subagent sinh ra (`assetscan` quét `.claude/agents/`) — đổi riêng chúng phải chạy cả cổng company."""
    _stage(kho_main, ten)
    assert _goi_cong(_cong("git commit -m 'x'", kho_main)) == {"company", "console"}


def test_cong_commit_doi_ten_sang_goi_khac_chay_ca_goi_cu(kho_main: Path) -> None:
    """`git diff --name-only` mặc định dò đổi tên và chỉ in ĐÍCH: dời file khỏi gói A thì A mất file mà cổng A không
    chạy."""
    _stage(kho_main, "platform/gateway/src/gateway/x.py")
    _git(kho_main, "commit", "-qm", "nen")
    (kho_main / "companies/keeper/src/keeper").mkdir(parents=True)
    _git(kho_main, "mv", "platform/gateway/src/gateway/x.py", "companies/keeper/src/keeper/x.py")
    assert {"gateway", "keeper"} <= _goi_cong(_cong("git commit -m 'x'", kho_main))


@pytest.mark.parametrize("lenh", ["git add -A && git commit -m 'x'", "git add . ; git commit -m 'x'",
                                  "git commit -am 'x'"])
def test_cong_commit_stage_cung_lenh_van_chay_cong(kho_main: Path, lenh: str) -> None:
    """Hook chạy TRƯỚC cả lệnh: gõ `git add … && git commit` một lần thì lúc hook đọc, index còn rỗng — trước đây
    cổng bị bỏ qua hẳn. Phải xét cả thay đổi chưa stage lẫn file chưa track mà `git add` sắp lấy."""
    _stage(kho_main, "platform/gateway/src/gateway/x.py")
    _git(kho_main, "commit", "-qm", "nen")
    (kho_main / "platform/gateway/src/gateway/x.py").write_text("x = 2\n", encoding="utf-8")
    _tao(kho_main, "companies/keeper/src/keeper/moi.py")
    goi = _goi_cong(_cong(lenh, kho_main))
    assert "gateway" in goi, f"bỏ qua thay đổi chưa stage: {goi}"
    if "add" in lenh:
        assert "keeper" in goi, f"bỏ qua file chưa track mà `git add` sắp lấy: {goi}"


def test_cong_commit_stage_cung_lenh_van_chan_file_cam(kho_main: Path) -> None:
    _stage(kho_main, "nen.txt")
    _git(kho_main, "commit", "-qm", "nen")
    _tao(kho_main, "llm.yaml")
    kq = _cong("git add -A && git commit -m 'x'", kho_main)
    assert kq.returncode == 2, f"`git add -A && git commit` mang llm.yaml vào lịch sử: {kq.stderr}"


def test_cong_commit_a_van_chan_ha_nguong(kho_main: Path) -> None:
    _git(kho_main, "checkout", "-q", "-b", "worktree-thu")
    (kho_main / "pyproject.toml").write_text("fail_under = 100\n", encoding="utf-8")
    _git(kho_main, "add", "pyproject.toml")
    _git(kho_main, "commit", "-qm", "nen")
    (kho_main / "pyproject.toml").write_text("fail_under = 95\n", encoding="utf-8")
    kq = _cong("git commit -am 'x'", kho_main)
    assert kq.returncode == 2, f"`commit -a` hạ fail_under mà không bị chặn: {kq.stderr}"


# Test ngoài console với ra ngoài gói của nó. Hook chạy cổng gói bị đụng + gói import nó + console, nên đổi riêng file
# ngoài gói mà test ấy đọc KHÔNG chạy test ấy — trừ khi hook có ánh xạ riêng. Mỗi dòng nói nó được lo thế nào.
TEST_DOC_NGOAI_GOI = {
    "companies/software-company/tests/test_delivery_contract.py": "hook: `docs/integrations/*` kéo company",
    "companies/software-company/tests/test_roles.py": "no-ky-thuat ở hook: đọc `truth.py` của console",
    "companies/software-company/tests/test_codemap_duong_dan.py": "no-ky-thuat ở hook: thử đường dẫn từ gốc hub",
    "companies/software-company/tests/test_ranh_gioi_kieu.py": "an toàn: `SRC.parents[1]` là gốc gói",
    "platform/xagents-core/tests/test_cong_journal_append.py": "no-ky-thuat ở hook: quét `src/` của mọi gói",
}


def _voi_ra_ngoai_goi(p: Path, van: str | None = None) -> bool:
    """Có `parents[k]` ra khỏi gói: tính từ `__file__` mà k vượt gốc gói, hoặc từ biến khác — không tính được nó trỏ
    đâu, nên kể là ra (dòng an toàn thì ghi vào danh sách kèm lý do). `van` thay nội dung file, cho phép tự kiểm."""
    k_ra = len(p.relative_to(ROOT).parts) - 2   # companies/<gói>/tests/t.py: parents[2] đã là companies/
    for n in ast.walk(ast.parse(p.read_text(encoding="utf-8") if van is None else van)):
        if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) and n.value.attr == "parents"
                and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, int)):
            if n.slice.value >= (k_ra if "__file__" in ast.unparse(n.value.value) else 1):
                return True
    return False


def test_test_ngoai_console_doc_file_ngoai_goi_deu_co_ten() -> None:
    """Test của gói A đọc file ngoài A thì đổi riêng file ấy không chạy cổng A — đúng lỗ commit chỉ sửa README từng
    lọt (2026-09-28, test ở company đọc README gốc). Thêm test như vậy: đặt nó ở console (luôn chạy), hoặc thêm ánh
    xạ vào `pre-commit-gate.sh`; rồi ghi vào danh sách trên kèm cách nó được lo."""
    thay = {p.relative_to(ROOT).as_posix()
            for p in [*ROOT.glob("companies/*/tests/**/*.py"), *ROOT.glob("platform/*/tests/**/*.py")]
            if not p.is_relative_to(ROOT / "platform" / "console") and _voi_ra_ngoai_goi(p)}
    assert thay == set(TEST_DOC_NGOAI_GOI)


def test_bo_do_voi_ra_ngoai_goi_dung_y() -> None:
    """Chốt bộ dò trên mẫu biết trước (`TRAPS.md` §2): cổng mù thì danh sách trên xanh vì không thấy gì."""
    t = ROOT / "companies" / "software-company" / "tests" / "test_mau.py"
    ca = {"Path(__file__).resolve().parents[1] / 'src'": False, "Path(__file__).parents[3] / 'README.md'": True,
          "PKG.parents[1] / 'docs'": True, "# parents[3] trong chú thích\nx = 1": False}
    for van, ra in ca.items():
        assert _voi_ra_ngoai_goi(t, van) is ra, van


CONSOLE_TESTS = ROOT / "platform" / "console" / "tests"


def _mang_cong_repo(van: str) -> bool:
    """Module gán `pytestmark` ở cấp module có `pytest.mark.cong_repo` (một marker, hay một phần tử của danh sách)."""
    return any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
               and "pytest.mark.cong_repo" in ast.unparse(n.value) for n in ast.parse(van).body)


def test_test_console_doc_file_ngoai_goi_mang_marker_cong_repo() -> None:
    """F6: commit chỉ sửa tài liệu/config ngoài gói thì hook chỉ chạy `pytest -m cong_repo` của console. Một test
    console đọc file ngoài gói mà thiếu marker thì commit đổi đúng file ấy lọt cổng nhanh — dò bằng cùng bộ dò
    `parents[k]` với danh sách trên. Không phải test đọc file ngoài gói nào cũng tên `test_cong_*`
    (`test_static_ui.py` đọc ví dụ của company, `test_hop_dong_schema.py` đọc schema topic)."""
    doc_ngoai = {p.name: p for p in CONSOLE_TESTS.rglob("*.py") if _voi_ra_ngoai_goi(p)}
    assert {"test_cong_repo.py", "test_readme_goc.py", "test_static_ui.py"} <= set(doc_ngoai), "bộ dò mù"
    thieu = sorted(ten for ten, p in doc_ngoai.items() if not _mang_cong_repo(p.read_text(encoding="utf-8")))
    assert not thieu, f"test console đọc file ngoài gói mà thiếu `pytestmark` có `pytest.mark.cong_repo`: {thieu}"


def test_marker_cong_repo_dang_ky_trong_pyproject_console() -> None:
    """Marker chưa đăng ký thì `-m cong_repo` vẫn chạy nhưng mỗi file gắn nó sinh PytestUnknownMarkWarning."""
    cfg = tomllib.loads((ROOT / "platform" / "console" / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(m.startswith("cong_repo:") for m in cfg["tool"]["pytest"]["ini_options"].get("markers", []))


def test_bo_do_marker_cong_repo_dung_y() -> None:
    """Chốt hai bộ dò trên mẫu biết trước, ở đường dẫn console (gốc gói sâu khác companies/<gói>)."""
    t = CONSOLE_TESTS / "test_mau.py"
    assert _voi_ra_ngoai_goi(t, "Path(__file__).resolve().parents[1] / 'src'") is False
    assert _voi_ra_ngoai_goi(t, "Path(__file__).resolve().parents[3] / 'README.md'") is True
    assert _voi_ra_ngoai_goi(t, "PAGE.parents[5] / 'companies'") is True
    ca = {"pytestmark = pytest.mark.cong_repo": True,
          "pytestmark = [pytest.mark.usefixtures('x'), pytest.mark.cong_repo]": True,
          "@pytest.mark.cong_repo\ndef test_a(): pass": False, "x = pytest.mark.cong_repo": False,
          "pytestmark = pytest.mark.usefixtures('x')": False}
    for van, co in ca.items():
        assert _mang_cong_repo(van) is co, van


@pytest.fixture
def kho_worktree(kho_main: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Checkout chính đứng trên `main` + một worktree trên nhánh riêng.

    Đúng hoàn cảnh `AGENTS.md` luật cấm 2 bắt buộc: mỗi phiên một worktree. Trả `(chinh, worktree)`.
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
    đúng luật — hàng rào cản chính quy trình mà `AGENTS.md` luật cấm 2 bắt buộc.
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


def _dat_dev_task_gia(cay: Path, nhan: str, ma_thoat: int, biet_repo_gate: bool = True) -> None:
    """`scripts/dev-task.sh` giả cho một cây: khai nó là bản của cây nào, và `CLAUDE_PROJECT_DIR` trỏ cây nào.

    Cả hai đều phải là worktree: `dev-task.sh` thật lấy cây để `cd` từ `CLAUDE_PROJECT_DIR`, không từ vị trí của
    chính nó — gọi đúng bản của worktree mà để biến trỏ checkout chính vẫn là chạy cổng trên code khác.
    `nhan-cay.txt` không staged, nên không làm hook đổi gói phải chạy. `biet_repo_gate=False` giả bản dev-task cũ
    (nhánh tạo trước F6) chưa có task `repo-gate`.
    """
    (cay / "nhan-cay.txt").write_text(nhan, encoding="utf-8")
    s = cay / "scripts" / "dev-task.sh"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text(
        "#!/usr/bin/env bash\n"
        + ('case "$1" in\n  repo-gate) : ;;\nesac\n' if biet_repo_gate else "")
        + f'echo "dev-task-gia ban={nhan} du_an=$(cat "$CLAUDE_PROJECT_DIR/nhan-cay.txt" 2>/dev/null) $*" >&2\n'
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


# F6 (audit 2026-10-10): commit chỉ đụng tài liệu/config NGOÀI mọi gói thì console chạy chế độ nhanh
# (`dev-task.sh repo-gate` = `pytest -m cong_repo`, ~10 s) thay cho cả suite có `--cov` (~110 s). Mọi trường hợp
# khác giữ cổng đầy đủ. Ngoài console còn phải loại file trong gói khác: schema/prompt/mẫu (không phải `.py`) của
# company/keeper chảy vào test console qua import, không qua `ROOT/…`, nên marker không phủ được.
def _cong_console_chay(kho: Path, *ten: str, biet_repo_gate: bool = True) -> str:
    """Console chạy ở chế độ nào: `repo-gate` (nhanh) hay `day-du` (`gate console`, hoặc `gate all` có console)."""
    _stage(kho, *ten)
    _dat_dev_task_gia(kho, "chinh", 0, biet_repo_gate)
    kq = _cong("git commit -m 'x'", kho)
    assert kq.returncode == 0, kq.stderr
    goi = re.findall(r"dev-task-gia ban=chinh du_an=chinh (.*)", kq.stderr)
    if "repo-gate" in goi:
        assert not {"gate console", "gate all"} & set(goi), f"chạy cả hai chế độ: {goi}"
        return "repo-gate"
    return "day-du" if {"gate console", "gate all"} & set(goi) else repr(goi)


@pytest.mark.parametrize("ten", [("README.md",), ("docs/x.md",), ("README.md", "docs/x.md", ".github/workflows/ci.yml")])
def test_cong_commit_chi_tai_lieu_ngoai_goi_chay_console_che_do_nhanh(kho_main: Path, ten: tuple[str, ...]) -> None:
    assert _cong_console_chay(kho_main, *ten) == "repo-gate"


@pytest.mark.parametrize("ten", [("scripts/x.py",), ("README.md", "scripts/x.py"), ("platform/console/README.md",),
                                 ("companies/keeper/CLAUDE.md",), ("Makefile",)])
def test_cong_commit_dung_ma_hoac_goi_giu_cong_console_day_du(kho_main: Path, ten: tuple[str, ...]) -> None:
    assert _cong_console_chay(kho_main, *ten) == "day-du"


def test_cong_commit_dev_task_cu_chua_co_repo_gate_thi_chay_day_du(kho_main: Path) -> None:
    """Hook đến từ checkout chính, `dev-task.sh` từ cây đang commit: worktree tạo trước F6 chưa có `repo-gate` —
    gọi nó là `task lạ` → exit 2 → chặn mọi commit tài liệu ở đó. Không có task thì lùi về cổng đầy đủ."""
    assert _cong_console_chay(kho_main, "README.md", biet_repo_gate=False) == "day-du"


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


def test_moi_hook_khai_trong_settings_co_bit_thuc_thi_trong_git() -> None:
    """Claude Code gọi THẲNG đường dẫn trong `command`, không qua `bash <file>` như `_chay` ở file này. Thiếu bit
    thực thi thì trên Linux/macOS lệnh trả 126 "Permission denied" — Claude Code coi là lỗi không chặn và cho lệnh đi
    tiếp: cổng chết im lặng. Đo 2026-09-28 trên phiên cloud Linux: cả ba hook mode 100644 (commit từ Windows, nơi
    không có bit thực thi), `git commit` 40 file đụng năm gói xong trong 6 giây — riêng cổng năm gói mất 5 phút.
    Cùng họ `test_dev_task_entrypoint_is_executable_in_git` (#365), lần đó chỉ sửa `dev-task.sh`."""
    cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    duong = sorted({h["command"].replace("${CLAUDE_PROJECT_DIR}/", "").split()[0]
                    for nhom in cfg.get("hooks", {}).values() for muc in nhom for h in muc["hooks"]})
    kq = subprocess.run(["git", "ls-files", "-s", "--", *duong], cwd=ROOT, capture_output=True, text=True, check=True)
    mode = {dong.split("\t", 1)[1]: dong.split(" ", 1)[0] for dong in kq.stdout.splitlines()}
    thieu = [d for d in duong if mode.get(d) != "100755"]
    assert not thieu, f"hook khai trong settings.json thiếu bit thực thi trong git (cần 100755): {thieu}"


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
