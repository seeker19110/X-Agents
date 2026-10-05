"""`evidence.py` — chiều ĐỎ của lệnh BỌC (`make test`, `scripts/dev-task.sh gate`) phải là test đỏ thật.

Lỗ cũ (marker `no-ky-thuat` ở `EVIDENCE_RULES`): hàng `pytest-before-must-be-test-failure` chỉ nhận ra pytest gọi
THẲNG. Lệnh bọc nuốt mã thoát — `dev-task.sh gate` thoát 1 cho cả ruff, mypy lẫn pytest, `make` thoát 2 cho mọi
recipe hỏng — nên một lần "đỏ" vì ruff hỏng, hay vì pytest không thu được test nào, vẫn được tính là chiều đỏ hợp
lệ của bằng chứng hai chiều (I2). Hàng mới đòi dòng tổng kết pytest CUỐI trong `output_tail` có `N failed`, N ≥ 1.

Chiều ngược (`test_chieu_nguoc_*`): bỏ đúng hàng `WRAPPED_RULE` ⇒ cùng đầu vào không còn bị từ chối.

Mẫu output lấy từ pytest THẬT chạy trong thư mục tạm (`_pytest_that`), không chỉ chuỗi gõ tay: định dạng dòng tổng
kết là thứ dễ lệch nhất khi pytest đổi bản.
"""

import os
import sys
from pathlib import Path

import pytest

from keeper.events import RunOutcome
from keeper.evidence import (
    TRUSTED_VERIFIER,
    EvidenceError,
    TwoWayEvidence,
    require_two_way,
    rules_without,
    run_command,
)

WRAPPED_RULE = "wrapped-before-must-show-test-failure"
DIRECT_RULE = "pytest-before-must-be-test-failure"

MAKE_TEST = "make test"
GATE = "scripts/dev-task.sh gate keeper"

# Output của `dev-task.sh gate` khi ruff hỏng: không có dòng tổng kết pytest nào, vì pytest chưa từng chạy.
GATE_RED_AT_LINT = (
    "[dev-task] chạy: uv run ruff check src tests\n"
    "src/keeper/evidence.py:152:5: E501 Line too long (130 > 120)\n"
    "Found 1 error.\n"
    "[dev-task] CỔNG ĐỎ ở bước: lint\n"
)


def _ev(cmd: str, *, exit_code: int, tail: str) -> TwoWayEvidence:
    return TwoWayEvidence(
        cmd=cmd,
        before=RunOutcome(cmd=cmd, exit_code=exit_code, output_tail=tail),
        after=RunOutcome(cmd=cmd, exit_code=0, output_tail="4 passed in 0.01s"),
        verified_by=TRUSTED_VERIFIER,
    )


def _pytest_that(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str], *args: str) -> RunOutcome:
    """Chạy pytest THẬT (tiến trình con, thư mục tạm) qua `run_command` — cùng đường mà `collect_two_way` dùng."""
    for name in [k for k in os.environ if k.startswith("COV_CORE")]:
        monkeypatch.delenv(name)  # pytest-cov của gói đang đo không được kéo tiến trình con vào cùng phép đo
    for rel, body in files.items():
        (tmp_path / rel).write_text(body, encoding="utf-8")
    return run_command((sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args), tmp_path)


def _wrapped(cmd: str, real: RunOutcome, *, exit_code: int) -> TwoWayEvidence:
    """Đầu ra pytest thật, nhưng mã thoát và tên lệnh là của lệnh BỌC (make: 2, dev-task.sh: 1)."""
    return _ev(cmd, exit_code=exit_code, tail=real.output_tail)


THREE_PASS_ONE_FAIL = {
    "test_a.py": (
        "def test_ok1(): assert True\ndef test_ok2(): assert True\ndef test_ok3(): assert True\n"
        "def test_bad(): assert 1 == 2\n"
    )
}
BROKEN_IMPORT = {"test_broken.py": "import khong_co_module_nay\n\ndef test_x(): assert True\n"}


# --- (1) lệnh bọc đỏ vì lý do KHÁC pytest ---------------------------------------------------------------------


@pytest.mark.parametrize("cmd,code", [(GATE, 1), (MAKE_TEST, 2)], ids=["dev-task", "make"])
def test_lenh_boc_do_o_buoc_lint_khong_co_dong_tong_ket_pytest_bi_tu_choi(cmd: str, code: int):
    """`dev-task.sh gate` đỏ ở bước lint: pytest chưa chạy, nhưng mã thoát 1 vẫn `> 0`. Không có dòng tổng kết
    pytest nào trong output ⇒ không test nào đỏ ⇒ không phải chiều ĐỎ của bằng chứng hai chiều."""
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(cmd, exit_code=code, tail=GATE_RED_AT_LINT))
    assert WRAPPED_RULE in str(e.value)


def test_lenh_boc_output_rong_bi_tu_choi():
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(GATE, exit_code=1, tail=""))
    assert WRAPPED_RULE in str(e.value)


# --- (2) lệnh bọc có test đỏ thật ------------------------------------------------------------------------------


@pytest.mark.parametrize("cmd,code", [(GATE, 1), (MAKE_TEST, 2)], ids=["dev-task", "make"])
def test_lenh_boc_co_test_do_that_la_chieu_do_hop_le(cmd: str, code: int):
    tail = "FAILED tests/test_a.py::test_bad - assert 1 == 2\n1 failed, 3 passed in 0.12s\n"
    require_two_way(_ev(cmd, exit_code=code, tail=tail))  # không ném


def test_lenh_boc_voi_pytest_that_do_la_chieu_do_hop_le(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mẫu THẬT, dạng `-q` (cổng của repo chạy `pytest -q`): `1 failed, 3 passed in 0.02s`."""
    real = _pytest_that(tmp_path, monkeypatch, THREE_PASS_ONE_FAIL, "-q")
    assert real.exit_code == 1 and "1 failed, 3 passed in" in real.output_tail  # mẫu đúng là thứ mình tưởng
    require_two_way(_wrapped(MAKE_TEST, real, exit_code=2))
    require_two_way(_wrapped(GATE, real, exit_code=1))


# --- (3) không test nào chạy xong -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tail",
    [
        "no tests ran in 0.01s\n",
        "======================== no tests ran in 0.01s ========================\n",
        "4 deselected in 0.00s\n",
        "1 passed, 3 deselected in 0.01s\n",
    ],
    ids=["q", "vien", "chi-deselected", "xanh"],
)
def test_lenh_boc_khong_test_nao_do_bi_tu_choi(tail: str):
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(MAKE_TEST, exit_code=2, tail=tail))
    assert WRAPPED_RULE in str(e.value)


def test_lenh_boc_khong_thu_duoc_test_that_bi_tu_choi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mẫu THẬT: file test mới bị `git stash --include-untracked` cuốn đi ⇒ pytest nhắm vào nó thoát 4 và in
    `no tests ran`, rồi một dòng `ERROR: file or directory not found` SAU dòng tổng kết."""
    real = _pytest_that(tmp_path, monkeypatch, THREE_PASS_ONE_FAIL, "-q", "test_moi.py")
    assert real.exit_code == 4 and "no tests ran in" in real.output_tail
    with pytest.raises(EvidenceError) as e:
        require_two_way(_wrapped(MAKE_TEST, real, exit_code=2))
    assert WRAPPED_RULE in str(e.value)


def test_lenh_boc_loc_k_khong_khop_gi_that_bi_tu_choi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    real = _pytest_that(tmp_path, monkeypatch, THREE_PASS_ONE_FAIL, "-q", "-k", "khong_co_ca_nao")
    assert real.exit_code == 5
    with pytest.raises(EvidenceError) as e:
        require_two_way(_wrapped(GATE, real, exit_code=1))
    assert WRAPPED_RULE in str(e.value)


# --- (4) lỗi thu thập --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("args", [("-q",), ()], ids=["q", "thuong"])
def test_lenh_boc_loi_thu_thap_that_bi_tu_choi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...]):
    real = _pytest_that(tmp_path, monkeypatch, BROKEN_IMPORT, *args)
    assert real.exit_code == 2 and "error during collection" in real.output_tail
    with pytest.raises(EvidenceError) as e:
        require_two_way(_wrapped(MAKE_TEST, real, exit_code=2))
    assert WRAPPED_RULE in str(e.value)


def test_loi_thu_thap_bi_tu_choi_ke_ca_khi_cung_dong_co_chu_failed():
    """Dấu hiệu lượt chạy bị ngắt thắng mọi dòng khác: `Interrupted` / `error during collection` ⇒ từ chối, dù
    dòng tổng kết có `failed` (vd. test in ra nguyên văn một dòng pytest)."""
    for sign in ("!!!! Interrupted: 1 error during collection !!!!", "KeyboardInterrupt\nInterrupted: stop"):
        tail = f"{sign}\n1 failed, 3 passed in 0.12s\n"
        with pytest.raises(EvidenceError) as e:
            require_two_way(_ev(MAKE_TEST, exit_code=2, tail=tail))
        assert WRAPPED_RULE in str(e.value)


# --- (5) các dạng dòng tổng kết ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "1 failed, 3 passed in 0.12s",
        "=========================== 1 failed, 3 passed in 0.12s ===========================",
        "1 failed, 3 passed in 61.50s (0:01:01)",
        "======= 1 failed, 3 passed in 61.50s (0:01:01) =======",
        "1 failed in 0.02s",
        "2 failed, 1 error in 0.02s",
        "1 failed, 3 passed, 2 deselected, 1 warning in 0.12s",
        "1 failed, 1 xfailed, 1 skipped in 0.12s",
        "  1 failed, 3 passed in 0.12s  ",
    ],
    ids=[
        "q",
        "vien",
        "q-thoi-gian",
        "vien-thoi-gian",
        "chi-failed",
        "kem-error",
        "kem-deselected",
        "kem-xfailed",
        "khoang-trang",
    ],
)
def test_dong_tong_ket_co_failed_duoc_nhan(line: str):
    require_two_way(_ev(MAKE_TEST, exit_code=2, tail=f"FAILED t.py::t\n{line}\n"))


def test_dong_tong_ket_voi_crlf_cua_windows_van_duoc_nhan():
    require_two_way(_ev(MAKE_TEST, exit_code=2, tail="FAILED t.py::t\r\n1 failed, 3 passed in 0.12s\r\n"))


@pytest.mark.parametrize(
    "line",
    [
        "3 passed in 0.12s",
        "1 error in 0.10s",
        "1 xfailed, 3 passed in 0.12s",
        "1 skipped in 0.01s",
        "0 failed, 3 passed in 0.12s",
    ],
    ids=["chi-passed", "chi-error", "xfailed-khong-phai-failed", "chi-skipped", "khong-failed"],
)
def test_dong_tong_ket_khong_co_failed_bi_tu_choi(line: str):
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(MAKE_TEST, exit_code=2, tail=f"{line}\n"))
    assert WRAPPED_RULE in str(e.value)


@pytest.mark.parametrize(
    "line",
    [
        "tests/test_a.py::test_bad failed, 3 passed in the morning",
        "1 failed, 3 passed",
        "FAILED tests/test_a.py::test_bad - assert 1 == 2",
        "failed in 0.12s",
        "x 1 failed in 0.12s",
    ],
    ids=["van-xuoi", "thieu-thoi-gian", "dong-failed-le", "thieu-so", "tien-to-la"],
)
def test_dong_giong_ma_khong_phai_dong_tong_ket_khong_duoc_nhan(line: str):
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(GATE, exit_code=1, tail=f"{line}\n"))
    assert WRAPPED_RULE in str(e.value)


def test_dong_tong_ket_cuoi_cung_thang_nhung_dong_truoc():
    """`make test` chạy pytest từng gói: lệnh dừng ở gói hỏng đầu tiên nên dòng tổng kết CUỐI là của lần hỏng.
    Dòng `failed` cũ (của gói trước, hay test in ra) không được cứu một lần chạy mà dòng cuối không có test đỏ."""
    with pytest.raises(EvidenceError):
        require_two_way(
            _ev(MAKE_TEST, exit_code=2, tail="1 failed, 3 passed in 0.12s\n4 passed in 0.50s\nno tests ran in 0s\n")
        )
    with pytest.raises(EvidenceError):
        require_two_way(_ev(MAKE_TEST, exit_code=2, tail="1 failed, 3 passed in 0.12s\n4 passed in 0.50s\n"))
    require_two_way(_ev(MAKE_TEST, exit_code=2, tail="4 passed in 0.50s\n1 failed, 3 passed in 0.12s\n"))


def test_lenh_boc_voi_dang_vien_that_cua_pytest_duoc_nhan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mẫu THẬT chế độ thường (không `-q`): dòng tổng kết có viền `=====`."""
    real = _pytest_that(tmp_path, monkeypatch, THREE_PASS_ONE_FAIL)
    assert "= 1 failed, 3 passed in" in real.output_tail
    require_two_way(_wrapped(MAKE_TEST, real, exit_code=2))


def test_lenh_boc_voi_coverage_that_dong_failed_van_la_dong_cuoi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Cổng của repo chạy `pytest -q --cov`: bảng coverage + dòng `FAIL Required test coverage` nằm TRƯỚC dòng tổng
    kết, nên dòng cuối vẫn là dòng tổng kết. `pytest-cov` là phụ thuộc dev của mọi gói: thiếu nó thì ca này ĐỎ,
    không skip (sổ `TRAN_SKIP` ở `test_cong_repo.py`)."""
    real = _pytest_that(tmp_path, monkeypatch, THREE_PASS_ONE_FAIL, "-q", "--cov=.", "--cov-fail-under=100")
    assert "Required test coverage" in real.output_tail
    require_two_way(_wrapped(GATE, real, exit_code=1))


# --- (6) nhận diện lệnh bọc và hồi quy cho phần còn lại -----------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "make test",
        "make -C companies/keeper test",
        "uv run make test",
        "/usr/bin/make test",
        "gmake test",
        "scripts/dev-task.sh gate keeper",
        "bash scripts/dev-task.sh gate keeper",
        "./scripts/dev-task.sh test all",
        r"C:\repo\scripts\dev-task.sh gate keeper",
        "make.exe test",
    ],
)
def test_nhan_ra_lenh_boc(cmd: str):
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(cmd, exit_code=2, tail=GATE_RED_AT_LINT))
    assert WRAPPED_RULE in str(e.value)


@pytest.mark.parametrize(
    "cmd",
    [
        "uv run ruff check src tests",
        "uv run mypy src/keeper",
        "uv run python -m keeper.cli drift --repo .",
        "tox -e py",
        "bash ci.sh",
        "makefile-lint src",
        "uv run python -c 'print(1)'",
        "git diff --exit-code",
    ],
    ids=["ruff", "mypy", "drift", "tox", "script-rieng", "ten-gan-giong-make", "python-c", "git-diff"],
)
def test_lenh_la_khong_phai_bao_giu_luat_lon_hon_0(cmd: str):
    """Lệnh KHÔNG bọc (công cụ đơn, hay bọc mà repo chưa biết tên) giữ hành vi cũ: mã thoát dương là đủ — mã của
    ruff/mypy/drift có nghĩa rõ ràng, còn bọc lạ thì chưa có cách đọc đáng tin (marker `no-ky-thuat` ở evidence.py)."""
    require_two_way(_ev(cmd, exit_code=2, tail=GATE_RED_AT_LINT))  # không ném


def test_pytest_goi_thang_giu_nguyen_hanh_vi_cu():
    """Hồi quy: pytest gọi thẳng chỉ xét MÃ THOÁT (1 = có test đỏ), không đọc output; hàng mới không đụng tới."""
    require_two_way(_ev("uv run pytest -q", exit_code=1, tail="output không có dòng tổng kết nào"))  # không ném
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev("uv run pytest -q tests/test_moi.py", exit_code=4, tail="1 failed, 3 passed in 0.12s"))
    assert DIRECT_RULE in str(e.value)
    assert WRAPPED_RULE not in str(e.value)


def test_lenh_boc_mang_ma_thoat_khong_duong_van_roi_o_hang_before_must_fail():
    """Mã ≤ 0 là việc của hàng `before-must-fail`; hàng mới không báo trùng cho các ca đó."""
    for code in (0, -1, -2, -9):
        with pytest.raises(EvidenceError) as e:
            require_two_way(_ev(MAKE_TEST, exit_code=code, tail="1 failed, 3 passed in 0.12s"))
        assert "before-must-fail" in str(e.value)
        assert WRAPPED_RULE not in str(e.value)


# --- (7) chiều ngược ---------------------------------------------------------------------------------------------


def test_chieu_nguoc_bo_hang_lenh_boc_thi_cung_dau_vao_khong_con_bi_tu_choi():
    """TẮT chính bản sửa (bỏ đúng hàng `WRAPPED_RULE`): cùng `dev-task.sh gate` đỏ ở bước lint, trước đây bị
    nhận như chiều đỏ, nay lại được nhận. Hai chiều đo trên cùng một đầu vào."""
    ev = _ev(GATE, exit_code=1, tail=GATE_RED_AT_LINT)
    with pytest.raises(EvidenceError):
        require_two_way(ev)
    require_two_way(ev, rules=rules_without(WRAPPED_RULE))  # không ném


def test_chieu_nguoc_bo_hang_pytest_thang_khong_lam_hang_lenh_boc_mat_tac_dung():
    """Hai hàng độc lập: bỏ hàng pytest-gọi-thẳng không nới lệnh bọc, và ngược lại."""
    wrapped = _ev(GATE, exit_code=1, tail=GATE_RED_AT_LINT)
    with pytest.raises(EvidenceError):
        require_two_way(wrapped, rules=rules_without(DIRECT_RULE))
    direct = _ev("uv run pytest -q tests/test_moi.py", exit_code=4, tail="")
    with pytest.raises(EvidenceError):
        require_two_way(direct, rules=rules_without(WRAPPED_RULE))


def test_ly_do_cua_hang_lenh_boc_noi_ro_vi_sao():
    with pytest.raises(EvidenceError) as e:
        require_two_way(_ev(GATE, exit_code=1, tail=GATE_RED_AT_LINT))
    msg = str(e.value)
    assert "ruff" in msg and "mypy" in msg and "N failed" in msg
