"""BT5 — `patcher.py`: ba thao tác, đường cấm (I4), không xoá file (I5), không tự làm agents/skills.

Mỗi ca "chiều ngược" TẮT chính bản sửa (bảng chặn / chốt coverage) rồi assert kết quả KHÁC — file bị sửa
THẬT trên đĩa, không phải một hằng đúng.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest
from xagents_core.sandbox import clean_env

from keeper import patcher as patcher
from keeper import worktree as worktree
from keeper.patcher import (
    FORBIDDEN_PATHS,
    HUMAN_ONLY_SEGMENTS,
    Edit,
    ForbiddenPath,
    NeedsHumanDecision,
    apply_edits,
    bump_dependency,
    default_runner,
    fix_docs,
    regen_derived,
)
from keeper.worktree import SharedCheckoutRefused, git_env, is_linked_worktree

CI_YML = "jobs:\n  test:\n    run: pytest --cov-fail-under=100\n"
MAKEFILE = "test:\n\tpytest --cov-fail-under=100\n"

PYPROJECT = """[project]
name = "demo"
description = "cu"
dependencies = ["pydantic>=2.6"]

[tool.coverage.report]
fail_under = 100
"""


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    """Checkout CHUNG giả, có đủ những đường dẫn nhạy cảm mà bảng chặn nói tới."""
    r = tmp_path / "chung"
    (r / ".github" / "rulesets").mkdir(parents=True)
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / "software-company" / "agents").mkdir(parents=True)
    (r / "keeper" / "skills").mkdir(parents=True)
    (r / "docs" / "sessions").mkdir(parents=True)
    (r / ".github" / "rulesets" / "x.yml").write_text("bao ve main\n", encoding="utf-8")
    (r / ".github" / "workflows" / "ci.yml").write_text(CI_YML, encoding="utf-8")
    (r / "llm.yaml").write_text("bi mat\n", encoding="utf-8")
    (r / "keeper" / "media.yaml").write_text("bi mat\n", encoding="utf-8")
    (r / "company.sqlite").write_text("db\n", encoding="utf-8")
    (r / "keeper" / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (r / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (r / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    (r / "software-company" / "agents" / "builder.md").write_text("prompt\n", encoding="utf-8")
    (r / "keeper" / "skills" / "vá.md").write_text("skill\n", encoding="utf-8")
    (r / "docs" / "sessions" / ".gitkeep").write_text("", encoding="utf-8")
    (r / "CHANGELOG.md").write_text("# Nhật ký thay đổi\n\n- dòng cũ\n", encoding="utf-8")
    _git(r, "init", "-b", "main")
    _git(r, "add", "-A")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "khoi tao")
    return r


@pytest.fixture
def root(main_repo: Path) -> Path:
    """Đường GHI chỉ chạy được trong WORKTREE PHỤ (CHẶN-1) — nên mọi ca dùng `root` phải là worktree phụ."""
    wt = main_repo.parent / "wt-keeper-t"
    _git(main_repo, "worktree", "add", "-b", "chore/keeper-t", str(wt), "HEAD")
    return wt


# --- I4: đường cấm ---------------------------------------------------------------------------------------


def test_rulesets_bi_chan_va_file_khong_doi(root: Path):
    f = root / ".github" / "rulesets" / "x.yml"
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit(".github/rulesets/x.yml", "ai cung push duoc\n")],
                    operation="fix_docs", ticket_id="T1")
    assert f.read_text(encoding="utf-8") == "bao ve main\n"


def test_chieu_nguoc_xoa_bang_chan_thi_ruleset_bi_sua_that(root: Path):
    """Tắt đúng bản sửa (`forbidden=()`) → file THẬT trong repo tạm đổi nội dung. Rồi khôi phục."""
    f = root / ".github" / "rulesets" / "x.yml"
    apply_edits(root, [Edit(".github/rulesets/x.yml", "ai cung push duoc\n")],
                operation="fix_docs", ticket_id="T1", forbidden=())
    assert f.read_text(encoding="utf-8") == "ai cung push duoc\n"
    _git(root, "checkout", "--", ".github/rulesets/x.yml")
    assert f.read_text(encoding="utf-8") == "bao ve main\n"


@pytest.mark.parametrize("rel", ["llm.yaml", "keeper/media.yaml", "company.sqlite"])
def test_cac_duong_cam_con_lai(root: Path, rel: str):
    truoc = (root / rel).read_text(encoding="utf-8")
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit(rel, "rac\n")], operation="fix_docs", ticket_id="T1")
    assert (root / rel).read_text(encoding="utf-8") == truoc


def test_sqlite_khop_ca_duoi_wal_shm(root: Path):
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit("keeper.sqlite-wal", "rac\n")], operation="fix_docs", ticket_id="T1")
    assert not (root / "keeper.sqlite-wal").exists()


def test_duong_dan_thoat_ra_ngoai_root_bi_chan(root: Path):
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit("../ngoai.txt", "rac\n")], operation="fix_docs", ticket_id="T1")
    assert not (root.parent / "ngoai.txt").exists()


def test_ha_fail_under_bi_chan_o_moi_pyproject(root: Path):
    for rel in ("pyproject.toml", "keeper/pyproject.toml"):
        moi = PYPROJECT.replace("fail_under = 100", "fail_under = 90")
        with pytest.raises(ForbiddenPath):
            apply_edits(root, [Edit(rel, moi)], operation="fix_docs", ticket_id="T1")
        assert "fail_under = 100" in (root / rel).read_text(encoding="utf-8")


def test_chieu_nguoc_tat_chot_coverage_thi_fail_under_tut_that(root: Path):
    f = root / "keeper" / "pyproject.toml"
    apply_edits(root, [Edit("keeper/pyproject.toml", PYPROJECT.replace("fail_under = 100", "fail_under = 90"))],
                operation="fix_docs", ticket_id="T1", coverage_guard=False)
    assert "fail_under = 90" in f.read_text(encoding="utf-8")
    _git(root, "checkout", "--", "keeper/pyproject.toml")
    assert "fail_under = 100" in f.read_text(encoding="utf-8")


def test_sua_pyproject_khong_dung_toi_fail_under_thi_duoc(root: Path):
    moi = PYPROJECT.replace('description = "cu"', 'description = "moi"')
    apply_edits(root, [Edit("keeper/pyproject.toml", moi)], operation="fix_docs", ticket_id="T1")
    assert 'description = "moi"' in (root / "keeper" / "pyproject.toml").read_text(encoding="utf-8")


def test_them_moi_pyproject_khong_no_vi_chua_co_ban_cu(root: Path):
    apply_edits(root, [Edit("moi/pyproject.toml", PYPROJECT)], operation="fix_docs", ticket_id="T1")
    assert (root / "moi" / "pyproject.toml").exists()


# --- Cạm bẫy §7: agents/ và skills/ phải do NGƯỜI quyết ---------------------------------------------------


@pytest.mark.parametrize("rel", ["software-company/agents/builder.md", "keeper/skills/vá.md",
                                 ".claude/agents/sc-builder.md"])
def test_cham_agents_hay_skills_thi_tu_choi_va_doi_ticket_high(root: Path, rel: str):
    with pytest.raises(NeedsHumanDecision) as e:
        apply_edits(root, [Edit(rel, "prompt moi\n")], operation="fix_docs", ticket_id="T1")
    assert e.value.risk_tier == "high"
    assert "eval-record" in str(e.value)
    p = root / rel
    if p.exists():
        assert p.read_text(encoding="utf-8") in ("prompt\n", "skill\n")
    else:
        assert not p.exists()  # không tự tạo file mới trong nhóm này


def test_segment_agents_khong_khop_goi_ten_giong(root: Path):
    apply_edits(root, [Edit("myagents/x.md", "ok\n")], operation="fix_docs", ticket_id="T1")
    assert (root / "myagents" / "x.md").exists()
    for seg in HUMAN_ONLY_SEGMENTS:   # mỗi segment trong bảng phải CHẶN thật, không chỉ có mặt trong bảng
        with pytest.raises(NeedsHumanDecision):
            apply_edits(root, [Edit(f"x/{seg}/y.md", "rac\n")], operation="fix_docs", ticket_id="T1")


# --- I5: KHÔNG có thao tác xoá file -----------------------------------------------------------------------


def test_patcher_khong_co_bat_ky_thao_tac_xoa_nao():
    """Đọc chính AST của `patcher.py`: không hàm nào tên xoá, không lời gọi nào xoá file."""
    import keeper.patcher as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    ten_ham = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    assert not [t for t in ten_ham if any(x in t.lower() for x in ("delete", "unlink", "rmtree", "remove"))]
    goi = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    cam = ("unlink", "remove", "rmtree", "rmdir", "shutil.move", "os.replace", "rename")
    assert not [g for g in goi if any(c in g for c in cam)], goi
    assert "import shutil" not in src


# --- Ba thao tác ------------------------------------------------------------------------------------------


def test_bump_dependency_doi_dung_dong_va_tra_proposal(root: Path):
    p = bump_dependency(root, "T1", package="pydantic", new_spec="pydantic>=2.9",
                        files=("pyproject.toml", "keeper/pyproject.toml"))
    assert p.operation == "bump_dependency"
    assert p.branch == "chore/keeper-T1"
    assert p.files == ["pyproject.toml", "keeper/pyproject.toml"]
    assert 'dependencies = ["pydantic>=2.9"]' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "fail_under = 100" in (root / "pyproject.toml").read_text(encoding="utf-8")


def test_bump_dependency_khong_thay_gi_thi_no(root: Path):
    with pytest.raises(ValueError, match="không tìm thấy"):
        bump_dependency(root, "T1", package="khong-co", new_spec="khong-co>=1", files=("pyproject.toml",))


def test_bump_dependency_vao_file_cam_van_bi_chan(root: Path):
    with pytest.raises(ForbiddenPath):
        bump_dependency(root, "T1", package="bi", new_spec="bi>=2", files=("llm.yaml",))


def test_fix_docs_them_dong_changelog_va_nhat_ky_phien(root: Path):
    p = fix_docs(root, "T1", changelog_line="- fix(keeper): BT5 (#0)", session_line="- BT5 xong",
                 session_date="2026-09-09")
    cl = (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    assert cl[0] == "# Nhật ký thay đổi"
    assert cl[2] == "- fix(keeper): BT5 (#0)"   # mới nhất trên cùng, dưới tiêu đề
    assert "- dòng cũ" in cl
    assert (root / "docs" / "sessions" / "2026-09-09.md").read_text(encoding="utf-8").endswith("- BT5 xong\n")
    assert p.operation == "fix_docs"
    assert p.files == ["CHANGELOG.md", "docs/sessions/2026-09-09.md"]


def test_fix_docs_khong_co_gi_de_sua_thi_no(root: Path):
    with pytest.raises(ValueError):
        fix_docs(root, "T1", session_date="2026-09-09")


def test_regen_derived_chay_dung_lenh_make_duoc_phep(root: Path):
    """`subagents` không nằm ở đây: nó bị từ chối trước khi chạy (test riêng bên dưới)."""
    da_chay: list[list[str]] = []

    def runner(argv: list[str], cwd: Path) -> tuple[int, str]:
        da_chay.append(argv)
        (cwd / "tests" / "golden").mkdir(parents=True, exist_ok=True)
        (cwd / "tests" / "golden" / "a.json").write_text("{}\n", encoding="utf-8")
        return 0, "ok"

    p = regen_derived(root, "T1", targets=("golden",), runner=runner)
    assert da_chay == [["make", "golden"]]
    assert p.operation == "regen_derived"
    assert p.files == ["tests/golden/a.json"]


def test_regen_derived_lenh_that_bai_thi_no(root: Path):
    with pytest.raises(RuntimeError, match="make golden"):
        regen_derived(root, "T1", targets=("golden",), runner=lambda argv, cwd: (1, "hong"))


def test_regen_derived_target_la_thi_no(root: Path):
    with pytest.raises(ValueError):
        regen_derived(root, "T1", targets=("deploy",), runner=lambda argv, cwd: (0, ""))


def test_regen_derived_dung_toi_agents_thi_van_doi_nguoi(root: Path):
    def runner(argv: list[str], cwd: Path) -> tuple[int, str]:
        (cwd / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (cwd / ".claude" / "agents" / "sc-x.md").write_text("moi\n", encoding="utf-8")
        return 0, "ok"

    with pytest.raises(NeedsHumanDecision):
        regen_derived(root, "T1", targets=("subagents",), runner=runner)


def test_default_runner_chay_that_mot_lenh_vo_hai(root: Path):
    code, out = default_runner(["git", "--version"], root)
    assert code == 0
    assert "git" in out


@pytest.mark.parametrize("rel", [".github/rulesets/x.yml", ".github/workflows/ci.yml", ".github/x.txt",
                                 ".github/rulesets", ".git/config", "llm.yaml", "keeper/media.yaml",
                                 "a.sqlite-wal", "LLM.YAML"])
def test_moi_mau_trong_bang_chan_deu_chan_that(root: Path, rel: str):
    """Đo hành vi từng mẫu thay vì so hằng số với đặc tả: hai hằng số bằng nhau không chứng minh gì chạy."""
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit(rel, "rac\n")], operation="fix_docs", ticket_id="T1")
    assert FORBIDDEN_PATHS


def test_session_line_thieu_ngay_thi_no(root: Path):
    with pytest.raises(ValueError, match="session_date"):
        fix_docs(root, "T1", session_line="- x")


def test_nhat_ky_phien_cu_khong_ket_thuc_bang_xuong_dong(root: Path):
    f = root / "docs" / "sessions" / "2026-09-09.md"
    f.write_text("# Phiên\n\n- cũ", encoding="utf-8")
    fix_docs(root, "T1", session_line="- mới", session_date="2026-09-09")
    assert f.read_text(encoding="utf-8") == "# Phiên\n\n- cũ\n- mới\n"


def test_regen_derived_tu_choi_subagents_TRUOC_khi_chay(root: Path):
    """`make subagents` bị từ chối TRƯỚC khi chạy: runner không hề được gọi và `.claude/agents/` trống."""
    calls: list[list[str]] = []

    def runner(argv, cwd):
        calls.append(list(argv))
        (cwd / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (cwd / ".claude" / "agents" / "sc-x.md").write_text("moi\n", encoding="utf-8")
        return 0, ""

    with pytest.raises(patcher.NeedsHumanDecision):
        patcher.regen_derived(root, "TCK-1", targets=("subagents",), runner=runner)
    assert calls == []
    assert not (root / ".claude" / "agents" / "sc-x.md").exists()


def test_regen_derived_chieu_nguoc_bo_chot_truoc_thi_FILE_da_bi_ghi(root: Path, monkeypatch):
    """CHIỀU NGƯỢC đo THIỆT HẠI THẬT (không đo biến đếm): bỏ bảng `TARGET_WRITES_HUMAN_ONLY` → `make
    subagents` chạy và GHI THẬT `.claude/agents/sc-x.md`. Chốt sau-khi-chạy vẫn ném, nhưng đã muộn: file nằm
    lại trong worktree và `patcher` không được xoá (I5). Đó chính là lý do chốt phải đứng TRƯỚC."""
    def runner(argv, cwd):
        (cwd / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (cwd / ".claude" / "agents" / "sc-x.md").write_text("moi\n", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(patcher, "TARGET_WRITES_HUMAN_ONLY", {})
    with pytest.raises(patcher.NeedsHumanDecision):
        patcher.regen_derived(root, "TCK-1", targets=("subagents",), runner=runner)
    assert (root / ".claude" / "agents" / "sc-x.md").read_text(encoding="utf-8") == "moi\n"


# --- CHẶN-1: mọi đường GHI phải đi qua chốt "đây có phải worktree phụ không" -------------------------------


def test_apply_edits_tu_choi_tren_checkout_chung_va_file_khong_doi(main_repo: Path):
    f = main_repo / "CHANGELOG.md"
    truoc = f.read_text(encoding="utf-8")
    with pytest.raises(SharedCheckoutRefused):
        apply_edits(main_repo, [Edit("CHANGELOG.md", "rac\n")], operation="fix_docs", ticket_id="T1")
    assert f.read_text(encoding="utf-8") == truoc


def test_chieu_nguoc_tat_chot_worktree_thi_checkout_chung_BI_GHI_THAT(main_repo: Path):
    f = main_repo / "CHANGELOG.md"
    apply_edits(main_repo, [Edit("CHANGELOG.md", "rac\n")], operation="fix_docs", ticket_id="T1",
                write_guard=False)
    assert f.read_text(encoding="utf-8") == "rac\n"
    _git(main_repo, "checkout", "--", "CHANGELOG.md")


def test_fix_docs_va_bump_deu_tu_choi_tren_checkout_chung(main_repo: Path):
    truoc = (main_repo / "pyproject.toml").read_text(encoding="utf-8")
    with pytest.raises(SharedCheckoutRefused):
        fix_docs(main_repo, "T1", changelog_line="- x")
    with pytest.raises(SharedCheckoutRefused):
        bump_dependency(main_repo, "T1", package="pydantic", new_spec="pydantic>=2.9")
    assert (main_repo / "pyproject.toml").read_text(encoding="utf-8") == truoc
    assert (main_repo / "CHANGELOG.md").read_text(encoding="utf-8") == "# Nhật ký thay đổi\n\n- dòng cũ\n"


def test_regen_derived_tu_choi_tren_checkout_chung_va_make_khong_chay(main_repo: Path):
    calls: list[list[str]] = []

    def runner(argv, cwd):
        calls.append(list(argv))
        (cwd / "tests" / "golden").mkdir(parents=True, exist_ok=True)
        (cwd / "tests" / "golden" / "a.json").write_text("{}\n", encoding="utf-8")
        return 0, "ok"

    with pytest.raises(SharedCheckoutRefused):
        regen_derived(main_repo, "T1", targets=("golden",), runner=runner)
    assert calls == []
    assert not (main_repo / "tests" / "golden" / "a.json").exists()


def test_chieu_nguoc_tat_chot_thi_make_chay_tren_checkout_chung(main_repo: Path):
    def runner(argv, cwd):
        (cwd / "tests" / "golden").mkdir(parents=True, exist_ok=True)
        (cwd / "tests" / "golden" / "a.json").write_text("{}\n", encoding="utf-8")
        return 0, "ok"

    regen_derived(main_repo, "T1", targets=("golden",), runner=runner, write_guard=False)
    assert (main_repo / "tests" / "golden" / "a.json").exists()


# --- CHẶN-2: `git status` thất bại phải NỔ, không được thành danh sách rỗng --------------------------------


def test_changed_files_git_that_bai_thi_nem(tmp_path: Path):
    with pytest.raises(RuntimeError, match="git status"):
        patcher._changed_files(tmp_path / "khong-phai-repo")


def test_chieu_nguoc_nuot_loi_git_thi_danh_sach_RONG(tmp_path: Path):
    """CHIỀU NGƯỢC: bỏ kiểm `returncode` → `[]` → vòng `check_path` chạy 0 lần. Đúng khuôn "xanh vì rỗng"."""
    assert patcher._changed_files(tmp_path / "khong-phai-repo", strict=False) == []


def test_regen_derived_nuot_loi_git_thi_file_cam_LOT_QUA(root: Path):
    """Thiệt hại thật của CHẶN-2: chốt-sau-khi-chạy rỗng ⇒ file trong `.claude/agents/` lọt, proposal XANH."""
    def runner(argv, cwd):
        (cwd / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (cwd / ".claude" / "agents" / "sc-x.md").write_text("moi\n", encoding="utf-8")
        return 0, "ok"

    with pytest.raises(NeedsHumanDecision):                     # chốt thật: bắt được
        regen_derived(root, "T1", targets=("golden",), runner=runner)
    (root / ".claude" / "agents" / "sc-x.md").unlink()
    p = regen_derived(root, "T1", targets=("golden",), runner=runner,
                      changed_files=lambda _r: patcher._changed_files(_r.parent / "khong-repo", strict=False))
    assert p.files == []                                        # xanh vì rỗng
    assert (root / ".claude" / "agents" / "sc-x.md").exists()    # lọt hoàn toàn


def test_changed_files_doc_duoc_ten_unicode(root: Path):
    (root / "keeper" / "skills" / "vá.md").write_text("skill moi\n", encoding="utf-8")
    assert "keeper/skills/vá.md" in patcher._changed_files(root)


def test_changed_files_doi_ten_tra_ve_CA_HAI_dau(root: Path):
    _git(root, "mv", "CHANGELOG.md", "software-company/agents/CHANGELOG.md")
    files = patcher._changed_files(root)
    assert "CHANGELOG.md" in files
    assert "software-company/agents/CHANGELOG.md" in files


def test_regen_derived_doi_ten_vao_agents_van_bi_bat(root: Path):
    """`R  cũ -> mới`: đích nằm trong `agents/` nên phải bị bắt. `line[3:]` cũ chỉ thấy một chuỗi ghép."""
    def runner(argv, cwd):
        _git(cwd, "mv", "CHANGELOG.md", "software-company/agents/CHANGELOG.md")
        return 0, "ok"

    with pytest.raises(NeedsHumanDecision):
        regen_derived(root, "T1", targets=("golden",), runner=runner)


# --- CHẶN-3: chốt fail_under nhìn GIÁ TRỊ trong đúng MỤC, không nhìn dòng ----------------------------------


@pytest.mark.parametrize("moi", [
    PYPROJECT.replace("[tool.coverage.report]", "[tool.coverage.paths]"),   # đổi mục, giữ nguyên dòng
    PYPROJECT.replace("fail_under = 100", ""),                              # xoá hẳn
    PYPROJECT.replace("fail_under = 100", "fail_under = 90"),               # hạ số
    PYPROJECT + "\n[tool.coverage.report]\nfail_under = 0\n",               # thêm mục trùng (TOML hỏng)
])
def test_ha_nguong_bang_moi_kieu_deu_bi_chan(root: Path, moi: str):
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit("keeper/pyproject.toml", moi)], operation="fix_docs", ticket_id="T1")
    assert "fail_under = 100" in (root / "keeper" / "pyproject.toml").read_text(encoding="utf-8")


def test_nang_nguong_thi_duoc(root: Path):
    apply_edits(root, [Edit("keeper/pyproject.toml", PYPROJECT.replace("fail_under = 100", "fail_under = 100.0"))],
                operation="fix_docs", ticket_id="T1")
    assert "100.0" in (root / "keeper" / "pyproject.toml").read_text(encoding="utf-8")


def test_cov_fail_under_trong_makefile_cung_duoc_chot(root: Path):
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit("Makefile", MAKEFILE.replace("100", "90"))],
                    operation="fix_docs", ticket_id="T1")
    assert "100" in (root / "Makefile").read_text(encoding="utf-8")


def test_chieu_nguoc_tat_chot_thi_makefile_tut_that(root: Path):
    apply_edits(root, [Edit("Makefile", MAKEFILE.replace("100", "90"))], operation="fix_docs",
                ticket_id="T1", coverage_guard=False)
    assert "--cov-fail-under=90" in (root / "Makefile").read_text(encoding="utf-8")
    _git(root, "checkout", "--", "Makefile")


def test_pyproject_khong_co_nguong_thi_khong_can_giu(root: Path):
    (root / "trong").mkdir()
    (root / "trong" / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    apply_edits(root, [Edit("trong/pyproject.toml", '[project]\nname = "y"\n')],
                operation="fix_docs", ticket_id="T1")
    assert '"y"' in (root / "trong" / "pyproject.toml").read_text(encoding="utf-8")


def test_pyproject_ban_cu_hong_toml_thi_khong_chan(root: Path):
    (root / "hong").mkdir()
    (root / "hong" / "pyproject.toml").write_text("[a\n", encoding="utf-8")
    apply_edits(root, [Edit("hong/pyproject.toml", "[b]\nx = 1\n")], operation="fix_docs", ticket_id="T1")
    assert "[b]" in (root / "hong" / "pyproject.toml").read_text(encoding="utf-8")


# --- Góp ý: biến môi trường GIT_* không được vòng qua chốt worktree ----------------------------------------


def test_git_env_bo_moi_bien_GIT(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/khong/co")
    monkeypatch.setenv("GIT_WORK_TREE", "/khong/co")
    assert not [k for k in git_env() if k.startswith("GIT_")]
    assert "GIT_DIR" in clean_env()   # `clean_env()` KHÔNG lọc chúng — vì thế mới cần `git_env()`


def test_chieu_nguoc_giu_GIT_DIR_thi_chot_worktree_bi_lua(root: Path, tmp_path: Path, monkeypatch):
    """Trỏ `GIT_DIR`/`GIT_WORK_TREE` vào worktree phụ rồi hỏi về một thư mục KHÔNG phải repo:
    lọc GIT_* → False (đúng); không lọc (`clean_env`) → True, chốt bị lừa."""
    ngoai = tmp_path / "ngoai"
    ngoai.mkdir()
    monkeypatch.setenv("GIT_DIR", _git(root, "rev-parse", "--absolute-git-dir"))
    monkeypatch.setenv("GIT_WORK_TREE", str(root))
    assert is_linked_worktree(ngoai) is False
    monkeypatch.setattr(worktree, "git_env", clean_env)
    assert is_linked_worktree(ngoai) is True


def test_bo_bot_mot_nguong_cung_la_ha(root: Path):
    """Hai ngưỡng cũ, còn một ngưỡng mới: số còn lại vẫn 100 nhưng một cổng đã biến mất."""
    hai = MAKEFILE + "test-slow:\n\tpytest --cov-fail-under=100\n"
    (root / "Makefile").write_text(hai, encoding="utf-8")
    with pytest.raises(ForbiddenPath):
        apply_edits(root, [Edit("Makefile", MAKEFILE)], operation="fix_docs", ticket_id="T1")
    assert (root / "Makefile").read_text(encoding="utf-8") == hai


def test_changed_files_ban_ghi_doi_ten_bi_cut_khong_no(monkeypatch, tmp_path: Path):
    """`R` ở cuối output mà KHÔNG có trường `origPath` theo sau → bỏ qua, không IndexError.

    `git status -z` để `origPath` thành trường NUL riêng; output bị cắt ngang (đĩa đầy, pipe đứt, git bị giết)
    cho ra đúng hình dạng này. Không có vế `i < len(toks) and toks[i]` thì đây là `IndexError` giữa lúc
    `regen_derived` đang chốt — chốt nổ còn tệ hơn chốt sai, vì nó giấu luôn kết quả thật."""
    class _R:
        returncode = 0
        stdout = "R  keeper/agents/moi.md\0"   # thiếu hẳn trường origPath phía sau
        stderr = ""

    monkeypatch.setattr(patcher.subprocess, "run", lambda *a, **k: _R())

    assert patcher._changed_files(tmp_path) == ["keeper/agents/moi.md"]


def test_bump_dependency_khong_dung_goi_trung_tien_to(root: Path):
    # audit 2026-09-23: regex không có ranh giới tên gói — bump `pytest` biến `pytest-cov>=5` thành
    # `pytest>=8.3-cov>=5` và `[tool.pytest.ini_options]` thành `[tool.pytest>=8.3.ini_options]`.
    goc = '[project]\ndependencies = ["pytest>=7", "pytest-cov>=5", "xpytest==1"]\n[tool.pytest.ini_options]\nx = 1\n'
    (root / "pyproject.toml").write_text(goc, encoding="utf-8")
    bump_dependency(root, "T1", package="pytest", new_spec="pytest>=8.3", files=("pyproject.toml",))
    moi = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert moi == goc.replace('"pytest>=7"', '"pytest>=8.3"')


def test_bump_dependency_new_spec_khong_la_mau_regex(root: Path):
    (root / "pyproject.toml").write_text('dependencies = ["bi>=1"]\n', encoding="utf-8")
    bump_dependency(root, "T1", package="bi", new_spec=r"bi>=2\1", files=("pyproject.toml",))
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == 'dependencies = ["bi>=2\\1"]\n'


def test_bump_dependency_chi_sua_chuoi_requirement_khong_sua_van_xuoi_hay_khoa_toml(root: Path):
    # audit 2026-10-10 (K9): ranh giới tên gói không đủ — regex khớp tên gói Ở BẤT KỲ ĐÂU, nên comment, mô tả và
    # khoá `[tool.uv.sources]` cũng bị "bump": `pydantic = { workspace = true }` thành `pydantic>=2.9 { … }`
    # (TOML hỏng). Chỉ chuỗi requirement — tên gói ngay sau dấu nháy mở — mới là chỗ được thay.
    goc = ('[project]\ndescription = "pydantic giúp kiểm, dùng pydantic để kiểm"\n'
           '# pydantic là lõi, đừng gỡ pydantic\n'
           'dependencies = ["pydantic>=2", \'pydantic-core==2\']\n'
           '[tool.uv.sources]\npydantic = { workspace = true }\n')
    (root / "pyproject.toml").write_text(goc, encoding="utf-8")
    bump_dependency(root, "T1", package="pydantic", new_spec="pydantic>=2.9", files=("pyproject.toml",))
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == goc.replace('"pydantic>=2"', '"pydantic>=2.9"')


def test_bump_dependency_khong_cat_extras_thanh_requirement_hong(root: Path):
    # Cùng họ K9: `"pydantic[email]>=2"` từng thành `"pydantic>=2.9[email]>=2"`. `new_spec` không mang extras nên
    # thay cả cụm là mất extras — không đoán: bỏ qua chuỗi đó; không còn chỗ nào khớp thì `ValueError`, không ghi.
    goc = 'dependencies = ["pydantic[email]>=2"]\n'
    (root / "pyproject.toml").write_text(goc, encoding="utf-8")
    with pytest.raises(ValueError, match="không tìm thấy"):
        bump_dependency(root, "T1", package="pydantic", new_spec="pydantic>=2.9", files=("pyproject.toml",))
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == goc


def test_bump_dependency_spec_co_khoang_trang_thay_tron(root: Path):
    # Cùng họ K9: PEP 508 cho khoảng trắng quanh toán tử; `"pydantic >= 2.0"` từng thành `"pydantic>=2.9 2.0"`.
    (root / "pyproject.toml").write_text('dependencies = ["pydantic >= 2.0"]\n', encoding="utf-8")
    bump_dependency(root, "T1", package="pydantic", new_spec="pydantic>=2.9", files=("pyproject.toml",))
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == 'dependencies = ["pydantic>=2.9"]\n'
