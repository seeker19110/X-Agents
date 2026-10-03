"""BT6 — `evidence.py`: bằng chứng đo hai chiều (bất biến I2) và chặn LỜI KHAI `verified_by`.

Hai ca quan trọng nhất, cả hai đều TẮT ĐƯỢC bản sửa rồi đo lại (không phải "chiều ngược" xanh vĩnh viễn):

* `test_patch_gia_khong_sua_gi_..._va_chieu_nguoc`: bỏ hàng kiểm `before-must-fail` → CÙNG đầu vào không còn ném.
* `test_loi_khai_verified_by_..._va_chieu_nguoc`: bỏ bộ lọc self-claim → lời khai của model LỌT vào báo cáo và
  mua được một `require_two_way` xanh.
"""
import subprocess
from pathlib import Path

import pytest

from keeper import evidence as evidence_mod
from keeper.events import RunOutcome
from keeper.evidence import (
    EVIDENCE_RULES,
    MISSING_EXIT,
    SELF_CLAIM_FIELDS,
    STASH_MESSAGE,
    TIMEOUT_EXIT,
    TRUSTED_VERIFIER,
    EvidenceError,
    TwoWayEvidence,
    _measured,
    collect_two_way,
    drop_self_claims,
    require_two_way,
    rules_without,
    run_command,
    verification_report,
)
from keeper.worktree import SharedCheckoutRefused

CI_CMD = ("uv", "run", "pytest", "-q")


def _ev(*, before: int, after: int, verified_by: str = TRUSTED_VERIFIER) -> TwoWayEvidence:
    return TwoWayEvidence(
        cmd=" ".join(CI_CMD),
        before=RunOutcome(cmd=" ".join(CI_CMD), exit_code=before, output_tail="output THẬT trước"),
        after=RunOutcome(cmd=" ".join(CI_CMD), exit_code=after, output_tail="output THẬT sau"),
        verified_by=verified_by,
    )


class _FakeGit:
    """`git` giả có ĐỘ SÂU STASH thật: lệnh CI trả `before_exit` khi đang stash (bản sửa bị TẮT), trả
    `after_exit` khi đã pop (bản sửa bật lại). Nhờ vậy "patch giả không sửa gì" = `before_exit=0`."""

    def __init__(self, *, before_exit: int = 1, after_exit: int = 0, push_exit: int = 0,
                 creates_stash: bool = True, pop_exit: int = 0, list_exit: int = 0) -> None:
        self.before_exit, self.after_exit = before_exit, after_exit
        self.push_exit, self.creates_stash, self.pop_exit, self.list_exit = (
            push_exit, creates_stash, pop_exit, list_exit)
        self.depth = 0
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, cwd, *, timeout: int = 600, tail: int | None = 2000) -> RunOutcome:
        argv = tuple(argv)
        self.calls.append(argv)
        cmd = " ".join(argv)
        if argv[:3] == ("git", "stash", "list"):
            body = "\n".join(f"stash@{{{i}}}: keeper" for i in range(self.depth))
            return RunOutcome(cmd=cmd, exit_code=self.list_exit, output_tail=body)
        if argv[:3] == ("git", "stash", "push"):
            if self.push_exit == 0 and self.creates_stash:
                self.depth += 1
            return RunOutcome(cmd=cmd, exit_code=self.push_exit, output_tail="stash push")
        if argv[:3] == ("git", "stash", "pop"):
            if self.pop_exit == 0:
                self.depth -= 1
            return RunOutcome(cmd=cmd, exit_code=self.pop_exit, output_tail="stash pop")
        code = self.before_exit if self.depth > 0 else self.after_exit
        return RunOutcome(cmd=cmd, exit_code=code, output_tail="output pytest")


# --- require_two_way: ba hàng kiểm ------------------------------------------------------------------

def test_bang_chung_du_ba_hang_kiem_thi_qua():
    require_two_way(_ev(before=1, after=0))


def test_patch_gia_khong_sua_gi_thi_before_xanh_va_bi_nem():
    """Patch giả (không sửa gì thật) → tắt nó đi test VẪN xanh → `before.exit_code == 0` → báo cáo vô hiệu."""
    ev = _ev(before=0, after=0)
    with pytest.raises(EvidenceError) as e:
        require_two_way(ev)
    assert "before-must-fail" in str(e.value)


def test_chieu_nguoc_bo_hang_kiem_before_thi_cung_dau_vao_khong_con_nem():
    """TẮT chính bản sửa (bỏ hàng `before-must-fail`, tương đương nới `== 0` thành `>= 0`): cùng `ev` đó
    KHÔNG còn ném. Hai chiều đo trên cùng một đầu vào."""
    ev = _ev(before=0, after=0)
    with pytest.raises(EvidenceError):
        require_two_way(ev)
    require_two_way(ev, rules=rules_without("before-must-fail"))  # không ném


@pytest.mark.parametrize("before", [TIMEOUT_EXIT, MISSING_EXIT, -9], ids=["qua-gio", "khong-co-lenh", "bi-giet"])
def test_lan_chay_truoc_khong_hoan_tat_khong_phai_chieu_do(before: int):
    """Chiều ngược nghĩa là TEST chạy xong và ĐỎ. Quá giờ (cache lạnh lần đầu, cache ấm lần sau), lệnh không có
    trên máy (script do chính patch thêm, bị stash cùng `--include-untracked`) hay tiến trình bị giết bằng tín
    hiệu (`-9` khi OOM) đều là KHÔNG test nào chạy — nhận chúng là bằng chứng hai chiều mà không đo gì."""
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(before=before, after=0))
    assert "before-must-fail" in str(e.value)


def _ev_cmd(cmd: str, *, before: int) -> TwoWayEvidence:
    return TwoWayEvidence(
        cmd=cmd, before=RunOutcome(cmd=cmd, exit_code=before, output_tail="output THẬT trước"),
        after=RunOutcome(cmd=cmd, exit_code=0, output_tail="output THẬT sau"), verified_by=TRUSTED_VERIFIER,
    )


PYTEST_CMDS = ["uv run pytest -q tests/test_moi.py", "python -m pytest tests/test_moi.py",
               r".venv\Scripts\pytest.exe -q tests\test_moi.py", "py.test -k ca_moi"]


@pytest.mark.parametrize("cmd", PYTEST_CMDS)
@pytest.mark.parametrize("before", [2, 3, 4, 5], ids=["ngat-hoac-loi-thu-thap", "loi-noi-bo", "sai-cach-goi",
                                                       "khong-thu-duoc-test"])
def test_pytest_thoat_khac_1_khong_phai_chieu_do(cmd: str, before: int):
    """`--include-untracked` stash luôn FILE TEST MỚI của patch: lệnh nhắm thẳng file đó (`pytest tests/test_moi.py`)
    thoát 4 vì đường dẫn không có, `-k ca_moi` thoát 5 vì không thu được test nào — `> 0` nên từng qua I2 mà không
    test nào chạy. Với pytest chỉ mã 1 nghĩa là "có test chạy xong và ĐỎ"."""
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev_cmd(cmd, before=before))
    assert "pytest-before-must-be-test-failure" in str(e.value)


@pytest.mark.parametrize("cmd", PYTEST_CMDS)
def test_pytest_thoat_1_van_la_chieu_do_va_chieu_nguoc(cmd: str):
    require_two_way(_ev_cmd(cmd, before=1))
    require_two_way(_ev_cmd(cmd, before=4), rules=rules_without("pytest-before-must-be-test-failure"))  # không ném


@pytest.mark.parametrize("cmd", ["make test", "scripts/dev-task.sh gate keeper", "uv run ruff check src tests/test_pytest.py"])
def test_lenh_khong_phai_pytest_giu_luat_lon_hon_0(cmd: str):
    """`make` thoát 2 khi một recipe đỏ, `ruff` thoát 1 khi có lỗi lint: ngoài pytest không biết nghĩa từng mã."""
    require_two_way(_ev_cmd(cmd, before=2))


def test_after_do_thi_bi_nem():
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(before=1, after=2))
    assert "after-must-pass" in str(e.value)


def test_verified_by_khac_workspace_thi_bi_nem():
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(before=1, after=0, verified_by="orchestrator"))
    assert "verifier-must-be-workspace" in str(e.value)


def test_rules_without_ten_la_thi_no():
    with pytest.raises(KeyError):
        rules_without("khong-co-hang-nay")


# --- lời khai verified_by ---------------------------------------------------------------------------

def test_truong_tu_khai_duoc_khai_bao():
    assert SELF_CLAIM_FIELDS == frozenset({"verified_by", "before", "after"})
    assert [r.name for r in EVIDENCE_RULES] == ["before-must-fail", "pytest-before-must-be-test-failure",
                                                "after-must-pass", "verifier-must-be-workspace"]


def test_drop_self_claims_bo_dung_truong_tu_khai():
    clean, dropped = drop_self_claims({"ticket_id": "T-1", "verified_by": "workspace", "family_hits": ["a.py"]})
    assert dropped == ["verified_by"]
    assert clean == {"ticket_id": "T-1", "family_hits": ["a.py"]}


def test_loi_khai_verified_by_bi_loc_gia_tri_dung_la_gia_tri_code_do():
    """Model trả JSON tự khai `verified_by="workspace"`; bằng chứng ĐO ĐƯỢC lại là `orchestrator`
    (không phải nơi vừa chạy lệnh). Lời khai phải KHÔNG lọt → `require_two_way` ném."""
    payload = {"ticket_id": "T-1", "verified_by": "workspace", "family_hits": ["x.py"],
               "family_safe": [{"path": "y.py", "reason": "đã soi, cùng khoá tra bảng"}]}
    measured = _ev(before=1, after=0, verified_by="orchestrator")
    with pytest.raises(EvidenceError) as e:
        verification_report(payload, evidence=measured)
    assert "verifier-must-be-workspace" in str(e.value)


def test_self_claim_fields_phu_kin_moi_truong_do_duoc():
    """`SELF_CLAIM_FIELDS` phải bằng ĐÚNG tập trường mà code tự đo.

    Bản đầu chỉ liệt kê `verified_by`; `before`/`after` không bị lọc nên payload ghi đè được kết quả đo, và
    `require_two_way` đi chấm chính lời khai đó — một `VerificationReport` hợp lệ mà KHÔNG lệnh nào chạy.
    Khoá hai tập bằng nhau ở đây, nên thêm một trường đo mới mà quên lọc là CI đỏ chứ không phải lỗ im lặng."""
    assert SELF_CLAIM_FIELDS == set(_measured(_ev(before=1, after=0)))


def test_payload_tu_khai_before_after_khong_ghi_de_duoc_so_do():
    """Đòn thật mà `sc-security` chỉ ra: model khai `before` đỏ / `after` xanh để tự cấp bằng chứng hai chiều.

    Ở đây số đo là `before=0` (tắt bản sửa mà VẪN xanh ⇒ test không đo gì) nên báo cáo PHẢI bị từ chối, bất kể
    payload khai gì."""
    payload = {"ticket_id": "T-1", "family_hits": ["x.py"],
               "family_safe": [{"path": "y.py", "reason": "đã soi, cùng khoá tra bảng"}],
               "before": {"cmd": "pytest", "exit_code": 1, "output_tail": "giả vờ đỏ"},
               "after": {"cmd": "pytest", "exit_code": 0, "output_tail": "giả vờ xanh"}}
    with pytest.raises(EvidenceError, match="before-must-fail"):
        verification_report(payload, evidence=_ev(before=0, after=0))


def test_chieu_nguoc_hai_lop_bao_ve_deu_can_thiet():
    """Chiều ngược, đo TỪNG LỚP một — vì hai lớp cố ý thừa nhau.

    Lớp 1 (`drop_self_claims`): tắt bộ lọc → trường tự khai còn nguyên trong payload đã "làm sạch".
    Lớp 2 (thứ tự hợp nhất `{**clean, **measured}`): nếu hợp nhất theo chiều cũ `{**measured, **clean}` thì
    chính payload còn nguyên đó ghi đè số đo. Ca này dựng lại đúng đường cũ để chứng minh nó THỦNG."""
    payload = {"ticket_id": "T-1", "verified_by": "workspace", "family_hits": ["x.py"], "family_safe": ["y.py"],
               "before": {"cmd": "pytest", "exit_code": 1, "output_tail": ""},
               "after": {"cmd": "pytest", "exit_code": 0, "output_tail": ""}}
    measured_ev = _ev(before=0, after=0, verified_by="orchestrator")

    con_nguyen, bo = drop_self_claims(payload, fields=frozenset())     # lớp 1 tắt
    assert bo == [] and con_nguyen["verified_by"] == "workspace"

    duong_cu = {**_measured(measured_ev), **con_nguyen}               # lớp 2 theo chiều cũ
    assert duong_cu["verified_by"] == "workspace"                     # lời khai LỌT
    assert duong_cu["before"]["exit_code"] == 1                       # số đo THẬT là 0

    # Đường đang dùng: số đo hợp nhất sau, nên lời khai không với tới được.
    duong_moi = {**con_nguyen, **_measured(measured_ev)}
    assert duong_moi["verified_by"] == "orchestrator"
    assert duong_moi["before"]["exit_code"] == 0


def test_bao_cao_hop_le_dung_gia_tri_do_duoc_va_giu_truong_ke_chuyen():
    payload = {"ticket_id": "T-1", "verified_by": "orchestrator", "family_hits": ["x.py"],
               "family_safe": [{"path": "y.py", "reason": "cùng chuỗi đã aware, không so naive"}]}
    report = verification_report(payload, evidence=_ev(before=1, after=0))
    assert report.verified_by == "workspace"
    assert report.before.exit_code == 1 and report.after.exit_code == 0
    assert report.family_hits == ["x.py"]
    assert [s.path for s in report.family_safe] == ["y.py"]


# --- require_family_report nối vào verification_report (`sc-security`: ràng buộc chỉ sống trong test) -----

def test_verification_report_co_family_hits_ma_khong_co_family_safe_thi_bi_nem():
    payload = {"ticket_id": "T-1", "verified_by": "orchestrator", "family_hits": ["x.py"], "family_safe": []}
    with pytest.raises(EvidenceError, match="safe-must-exist"):
        verification_report(payload, evidence=_ev(before=1, after=0))


def test_verification_report_khong_co_family_hits_thi_khong_can_safe():
    payload = {"ticket_id": "T-1", "verified_by": "orchestrator", "family_hits": [], "family_safe": []}
    report = verification_report(payload, evidence=_ev(before=1, after=0))
    assert report.family_hits == [] and report.family_safe == []




# --- repo thật trong tmp_path: `collect_two_way` chốt checkout chung nên KHÔNG được dùng `Path(".")` ------
# Dùng `Path(".")` là để phép đo phụ thuộc chỗ chạy: nó đi lọt chỉ vì phiên này tình cờ ngồi trong một
# worktree phụ. Chạy trong một clone thường thì cùng test đó đỏ — đúng khuôn "cổng đúng-sai theo máy chạy".

def _run_git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture
def repo_chinh(tmp_path: Path) -> Path:
    """Checkout CHÍNH (không phải worktree phụ) — thứ `collect_two_way` phải từ chối."""
    r = tmp_path / "nha" / "repo"
    r.mkdir(parents=True)
    _run_git("init", "-b", "main", cwd=r)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(r), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(r), check=True, capture_output=True)
    (r / "a.txt").write_text("x", encoding="utf-8")
    _run_git("add", "-A", cwd=r)
    _run_git("commit", "-m", "khoi tao", cwd=r)
    return r


@pytest.fixture
def worktree_phu(repo_chinh: Path) -> Path:
    """Worktree PHỤ của repo trên — thứ `collect_two_way` được phép chạm."""
    wt = repo_chinh.parent / "wt-keeper-t1"
    _run_git("worktree", "add", "-b", "chore/keeper-t1", str(wt), cwd=repo_chinh)
    return wt


# --- collect_two_way: git stash → chạy → git stash pop -----------------------------------------------

def test_collect_two_way_stash_chay_pop_va_tu_dat_verified_by(worktree_phu: Path):
    git = _FakeGit(before_exit=1, after_exit=0)
    ev = collect_two_way(CI_CMD, worktree_phu, runner=git)
    assert ev.verified_by == TRUSTED_VERIFIER
    assert ev.before.exit_code == 1 and ev.after.exit_code == 0
    assert ev.cmd == "uv run pytest -q"
    assert git.depth == 0  # đã pop lại
    assert ("git", "stash", "pop") in git.calls
    require_two_way(ev)


def test_collect_two_way_patch_gia_thi_bang_chung_khong_qua_cua(worktree_phu: Path):
    """Patch không sửa gì: stash rồi chạy vẫn xanh → `require_two_way` ném trên chính bằng chứng thu được."""
    ev = collect_two_way(CI_CMD, worktree_phu, runner=_FakeGit(before_exit=0, after_exit=0))
    assert ev.before.exit_code == 0
    with pytest.raises(EvidenceError):
        require_two_way(ev)


def test_collect_two_way_stash_push_that_bai_thi_nem(worktree_phu: Path):
    with pytest.raises(EvidenceError, match="stash push"):
        collect_two_way(CI_CMD, worktree_phu, runner=_FakeGit(push_exit=1))


def test_collect_two_way_khong_tao_muc_stash_nao_thi_nem(worktree_phu: Path):
    """`git stash` không tạo mục nào ⇒ không có diff để TẮT ⇒ `before` sẽ đo chính bản gốc, vô nghĩa."""
    with pytest.raises(EvidenceError, match="không tạo mục stash"):
        collect_two_way(CI_CMD, worktree_phu, runner=_FakeGit(creates_stash=False))


def test_collect_two_way_stash_list_hong_thi_nem(worktree_phu: Path):
    with pytest.raises(EvidenceError, match="stash list"):
        collect_two_way(CI_CMD, worktree_phu, runner=_FakeGit(list_exit=1))


def test_collect_two_way_pop_that_bai_thi_nem_to_vi_patch_chua_duoc_khoi_phuc(worktree_phu: Path):
    with pytest.raises(EvidenceError, match="stash pop") as e:
        collect_two_way(CI_CMD, worktree_phu, runner=_FakeGit(pop_exit=1))
    # Người mất việc phải tự khôi phục tay được: thông điệp phải nêu ref stash + lệnh khôi phục, không chỉ
    # "thất bại" suông.
    assert "stash@{0}" in str(e.value)
    assert "git stash apply" in str(e.value)
    assert STASH_MESSAGE in str(e.value)


def test_collect_two_way_van_pop_khi_lenh_ci_no(worktree_phu: Path):
    class _Boom(_FakeGit):
        def __call__(self, argv, cwd, **kw):
            if tuple(argv) == CI_CMD and self.depth > 0:
                self.calls.append(tuple(argv))
                raise RuntimeError("lệnh CI nổ")
            return super().__call__(argv, cwd, **kw)

    git = _Boom()
    with pytest.raises(RuntimeError):
        collect_two_way(CI_CMD, worktree_phu, runner=git)
    assert ("git", "stash", "pop") in git.calls and git.depth == 0


# --- run_command: tiến trình thật, không mạng --------------------------------------------------------

def test_run_command_chay_that_va_cat_duoi(tmp_path):
    import sys
    r = run_command((sys.executable, "-c", "print('xin chao')"), tmp_path)
    assert r.exit_code == 0 and "xin chao" in r.output_tail
    r2 = run_command((sys.executable, "-c", "print('a' * 50)"), tmp_path, tail=10)
    assert len(r2.output_tail) == 10
    r3 = run_command((sys.executable, "-c", "print('b' * 50)"), tmp_path, tail=None)
    assert len(r3.output_tail.strip()) == 50


def test_run_command_cong_cu_khong_co_tren_may_thi_khong_nem(tmp_path):
    r = run_command(("keeper-khong-ton-tai-tren-may-nay",), tmp_path)
    assert r.exit_code == MISSING_EXIT and "không có trên máy" in r.output_tail


def test_run_command_qua_gio_thi_khong_nem(tmp_path):
    import sys
    r = run_command((sys.executable, "-c", "import time; time.sleep(5)"), tmp_path, timeout=1)
    assert r.exit_code == TIMEOUT_EXIT and "quá" in r.output_tail


def test_run_command_exit_khac_khong_giu_stderr(tmp_path):
    import sys
    r = run_command((sys.executable, "-c", "import sys; sys.stderr.write('vo'); sys.exit(3)"), tmp_path)
    assert r.exit_code == 3 and "vo" in r.output_tail


def test_collect_two_way_tu_choi_checkout_chung(repo_chinh: Path):
    """Chốt chặn: `git stash push --include-untracked` cất TOÀN BỘ worktree, không chỉ diff của patch —
    chạy trên checkout chung là nuốt việc chưa commit của phiên khác.

    Ca này đo cả thiệt hại: đặt một file untracked của "phiên khác" rồi khẳng định nó CÒN NGUYÊN sau khi bị
    từ chối, và runner KHÔNG hề được gọi."""
    cua_phien_khac = repo_chinh / "viec-dang-lam.txt"
    cua_phien_khac.write_text("chua commit", encoding="utf-8")
    git = _FakeGit(before_exit=1, after_exit=0)
    with pytest.raises(SharedCheckoutRefused):
        collect_two_way(CI_CMD, repo_chinh, runner=git)
    assert git.calls == []
    assert cua_phien_khac.read_text(encoding="utf-8") == "chua commit"


def test_chieu_nguoc_bo_chot_thi_stash_chay_tren_checkout_chung(repo_chinh: Path, monkeypatch):
    """Chiều ngược: gỡ chốt → cùng lời gọi đó CHẠY `git stash push` trên checkout chung (runner ghi nhận).
    Đây chính là hành vi cũ mà chốt sửa."""
    monkeypatch.setattr(evidence_mod, "refuse_shared_checkout", lambda _p: None)
    git = _FakeGit(before_exit=1, after_exit=0)
    collect_two_way(CI_CMD, repo_chinh, runner=git)
    assert ("git", "stash", "push", "--include-untracked", "-m", evidence_mod.STASH_MESSAGE) in git.calls
