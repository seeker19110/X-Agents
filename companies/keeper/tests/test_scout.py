from pathlib import Path

import pytest

from keeper import scout
from keeper.fakes import FakeGitHub
from keeper.github import DependabotAlert


class _AlertGitHub(FakeGitHub):
    """`FakeGitHub` với `dependabot_alerts()` ghi đè để test scout — vẫn không chạm mạng, chỉ đổi dữ liệu cố
    định trả về (khuôn dùng lại, `DAC-TA-KEEPER.md` §5: "mọi test dùng FakeGitHub hoặc fixture trong tmp_path")."""

    def __init__(self, alerts: list[DependabotAlert]) -> None:
        super().__init__()
        self._alerts = alerts

    def dependabot_alerts(self) -> list[DependabotAlert]:
        self._count("dependabot_alerts")
        return self._alerts


def _write_uv_lock(repo: Path, packages: list[str]) -> None:
    body = "\n\n".join(f'[[package]]\nname = "{p}"\nversion = "1.0.0"' for p in packages)
    (repo / "uv.lock").write_text(body + "\n", encoding="utf-8")


def _write_pyproject(repo: Path, dev_packages: list[str]) -> None:
    dev = ", ".join(f'"{p}"' for p in dev_packages)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\n\n[dependency-groups]\ndev = [{dev}]\n', encoding="utf-8",
    )


def test_bump_patch_dev_dependency(tmp_path: Path) -> None:
    _write_uv_lock(tmp_path, ["pytest", "requests"])
    _write_pyproject(tmp_path, ["pytest"])
    gh = _AlertGitHub([DependabotAlert(number=1, state="open", severity="low",
                                        summary="Bump pytest from 8.1.0 to 8.1.1")])

    out = scout.scan(tmp_path, gh)

    assert len(out) == 1
    sig = out[0]
    assert sig.kind == "dependency"
    assert sig.subject == "pytest"
    assert sig.semver_jump == "patch"
    assert sig.is_dev is True


def test_bump_major_gia_thuong_khong_phai_dev(tmp_path: Path) -> None:
    _write_uv_lock(tmp_path, ["pytest", "requests"])
    _write_pyproject(tmp_path, ["pytest"])
    gh = _AlertGitHub([DependabotAlert(number=2, state="open", severity="high",
                                        summary="Bump requests from 2.30.0 to 3.0.0")])

    out = scout.scan(tmp_path, gh)

    assert len(out) == 1
    sig = out[0]
    assert sig.subject == "requests"
    assert sig.semver_jump == "major"
    assert sig.is_dev is False


def test_khong_uv_lock_van_chay(tmp_path: Path) -> None:
    """Không có `uv.lock`: không lọc theo khoá, vẫn phát signal cho alert parse được."""
    gh = _AlertGitHub([DependabotAlert(number=3, state="open", severity="medium",
                                        summary="Bump anypkg from 1.0.0 to 1.1.0")])
    out = scout.scan(tmp_path, gh)
    assert len(out) == 1
    assert out[0].semver_jump == "minor"


def test_alert_khong_parse_duoc_bi_bo_qua(tmp_path: Path) -> None:
    gh = _AlertGitHub([DependabotAlert(number=4, state="open", severity="low", summary="một mô tả không khuôn")])
    assert scout.scan(tmp_path, gh) == []


def test_goi_khong_trong_uv_lock_bi_loc(tmp_path: Path) -> None:
    """`uv.lock` có, nhưng gói trong alert không nằm trong đó → không phát (khoá không thật sự có gói này)."""
    _write_uv_lock(tmp_path, ["requests"])
    gh = _AlertGitHub([DependabotAlert(number=5, state="open", severity="low",
                                        summary="Bump ghost-pkg from 1.0.0 to 1.0.1")])
    assert scout.scan(tmp_path, gh) == []


@pytest.mark.parametrize("state", ["fixed", "dismissed", "auto_dismissed"])
def test_alert_khong_con_mo_bi_bo_qua(tmp_path: Path, state: str) -> None:
    """Alert đã đóng không phải việc phải làm — cùng luật `audit.dependabot_findings` (`state == "open"`)."""
    gh = _AlertGitHub([DependabotAlert(number=6, state=state, severity="high",
                                        summary="Bump requests from 2.30.0 to 3.0.0")])
    assert scout.scan(tmp_path, gh) == []


def test_semver_jump_khong_parse_duoc_tra_none() -> None:
    assert scout.semver_jump("abc", "1.0.0") is None
    assert scout.semver_jump("1.0.0", "xyz") is None


def test_locked_packages_uv_lock_hong(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("day khong phai toml hop le [[[", encoding="utf-8")
    assert scout.locked_packages(tmp_path) == set()


def test_locked_packages_khong_co_file(tmp_path: Path) -> None:
    assert scout.locked_packages(tmp_path) == set()


def test_dev_package_names_bo_qua_venv(tmp_path: Path) -> None:
    venv_pyproject = tmp_path / ".venv" / "lib" / "pyproject.toml"
    venv_pyproject.parent.mkdir(parents=True)
    venv_pyproject.write_text('[dependency-groups]\ndev = ["ma-doc-duoc"]\n', encoding="utf-8")
    assert "ma-doc-duoc" not in scout.dev_package_names(tmp_path)


def test_dev_package_names_pyproject_hong_bi_bo_qua(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("khong phai toml [[[", encoding="utf-8")
    assert scout.dev_package_names(tmp_path) == set()


@pytest.mark.parametrize(("old", "new"), [
    ("1.2.3", "1.2.3rc1"),
    ("1.2.3rc1", "1.2.3"),
    ("2.0.0", "2.0.0.post1"),
    ("2.0.0", "2.0.0.dev0"),
    ("1.0.0", "1.0.0+local1"),
])
def test_hau_to_khong_doi_ba_so_thi_khong_phai_bump(old, new):
    """Ba số bằng nhau, chỉ khác hậu tố → `None`, KHÔNG phải `"patch"`.

    Chiều ngược của nhánh `if ov == nv: return None`: bỏ nhánh đó thì mọi ca ở đây rơi xuống `return "patch"`.
    Điều đó nguy hiểm chứ không chỉ sai tên: `risk_tier` (BT4) cho patch được **tự merge**, nên một pre-release
    bị gọi nhầm là patch sẽ đi thẳng vào nhánh không cần người duyệt."""
    assert scout.semver_jump(old, new) is None


@pytest.mark.parametrize(("old", "new", "cho"), [
    ("1.2.3", "1.2.4rc1", "patch"),
    ("1.2.3", "1.3.0rc1", "minor"),
    ("1.2.3", "2.0.0rc1", "major"),
])
def test_hau_to_van_phan_loai_duoc_khi_ba_so_co_doi(old, new, cho):
    """Đối chứng: hậu tố KHÔNG làm mất khả năng phân loại khi phần số thật sự đổi — nếu nhánh `ov == nv` viết
    quá rộng (ví dụ so cả chuỗi) thì ba ca này thành `None` và test đỏ."""
    assert scout.semver_jump(old, new) == cho


def test_dev_package_names_bo_qua_entry_khong_co_ten(tmp_path: Path) -> None:
    """Entry chỉ có ràng buộc phiên bản, không có tên (`>=1.0`) → `re.split` trả chuỗi RỖNG.

    Không có vế `if pkg` thì một chuỗi rỗng lọt vào `names`, và `_norm("")` sẽ khiến mọi phép so tên sau đó
    coi "" là một gói dev có thật."""
    (tmp_path / "pyproject.toml").write_text(
        '[dependency-groups]\ndev = [">=1.0", "pytest>=8"]\n', encoding="utf-8")

    assert scout.dev_package_names(tmp_path) == {"pytest"}


class _GHKhongTraLoi(FakeGitHub):
    def dependabot_alerts(self) -> None:
        return None


def test_gh_khong_tra_loi_thi_scout_khong_phat_tin_hieu_va_khong_no(tmp_path: Path) -> None:
    """Scout chỉ QUAN SÁT (không mở cổng nào, như `health.pr_age_signals`): không biết thì không phát gì. Phần
    "không quét được ≠ sạch" thuộc `audit`, nơi có kết luận."""
    assert scout.scan(tmp_path, _GHKhongTraLoi()) == []
