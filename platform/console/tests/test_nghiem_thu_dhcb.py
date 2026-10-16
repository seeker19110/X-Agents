"""`scripts/nghiem_thu_dhcb.py` — nghiệm thu ẩn của đề bài DHCB-B1 (`docs/do-hai-khung/`), đo hai chiều.

Chấm thật trên bản mẫu `fixtures/dhcb_mau/` (máy chủ thật, cổng thật, tiến trình thật): bản đúng phải đạt 12/12 Must,
bản cài lỗi (`MAU_LOI`) phải trượt ĐÚNG các Must bị phá và không kéo Must khác trượt theo. Không có hai chiều này thì
một bộ chấm "luôn đạt" hay "luôn trượt" cũng xanh.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.cong_repo   # đọc script ngoài gói console → hook chạy cả ở chế độ nhanh (F6)
SCRIPT = ROOT / "scripts" / "nghiem_thu_dhcb.py"
MAU = Path(__file__).resolve().parent / "fixtures" / "dhcb_mau"
MUST = {f"M-{i:02d}" for i in range(1, 13)}


def _load():
    spec = importlib.util.spec_from_file_location("nghiem_thu_dhcb", SCRIPT)
    assert spec and spec.loader, f"Không tải được script {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["nghiem_thu_dhcb"] = module
    spec.loader.exec_module(module)
    return module


def _ban_mau(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(MAU, repo)
    return repo


def test_ban_mau_dung_dat_du_12_must(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAU_LOI", raising=False)
    kq = _load().cham(_ban_mau(tmp_path), cho=20)
    truot = [c for c in kq["ca"] if not c["dat"]]
    assert truot == [], truot
    assert (kq["must_dat"], kq["must_tong"], kq["khoi_dong"]) == (12, 12, True)
    assert kq["ca_dat"] == kq["ca_tong"] >= 20
    assert kq["test_sh"]["exit"] == 0 and kq["setup"]["exit"] == 0
    assert set(kq["must"]) == MUST


def test_ten_mot_ky_tu_bi_tu_choi_khong_lam_ca_khong_luu_bao_oan(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Chập chờn có thật (cổng console 2026-10-16): C05 gửi họ tên `A`, C12 tìm `A` trong trang quản trị — trúng
    mọi tên thử có chữ A. Ép tên thử luôn có chữ A để tái hiện chắc chắn thay vì một lần trên vài lần."""
    monkeypatch.delenv("MAU_LOI", raising=False)
    m = _load()
    monkeypatch.setattr(m, "_ten", lambda: "Nguyễn Thị Kiểm A" + m.secrets.token_hex(3))
    kq = m.cham(_ban_mau(tmp_path), cho=20)
    assert [c["id"] for c in kq["ca"] if not c["dat"]] == []


def test_moi_must_co_it_nhat_mot_ca() -> None:
    assert {ca.must for ca in _load().CA} == MUST


LOI_PHA = {"khong_luu": "M-04", "trung_sdt": "M-07", "xss": "M-08", "log_pii": "M-09",
           "mat_khau_mac_dinh": "M-10", "csv_cong_thuc": "M-11", "khong_413": "M-12"}


def test_ban_mau_cai_loi_truot_dung_must_bi_pha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAU_LOI", ",".join(LOI_PHA))
    kq = _load().cham(_ban_mau(tmp_path), cho=20)
    truot = {m for m, dat in kq["must"].items() if not dat}
    assert truot == set(LOI_PHA.values())
    assert all(c["ghi_chu"] for c in kq["ca"] if not c["dat"])


def test_may_chu_khong_len_thi_moi_ca_truot_va_noi_ro(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "run.sh").write_text("#!/bin/sh\necho hỏng >&2\nexit 3\n", encoding="utf-8")
    (repo / "run.sh").chmod(0o755)
    kq = _load().cham(repo, cho=5)
    assert kq["khoi_dong"] is False
    assert (kq["must_dat"], kq["ca_dat"]) == (0, 0)
    assert all("không lên" in c["ghi_chu"] for c in kq["ca"])
    assert kq["test_sh"]["exit"] is None
    assert any("setup.sh" in c for c in kq["canh_bao"]) and any("test.sh" in c for c in kq["canh_bao"])


def test_run_sh_thieu_quyen_thuc_thi_van_chay_nhung_bi_ghi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAU_LOI", raising=False)
    repo = _ban_mau(tmp_path)
    (repo / "run.sh").chmod(0o644)
    kq = _load().cham(repo, cho=20)
    assert kq["khoi_dong"] is True
    assert any("quyền thực thi" in c for c in kq["canh_bao"])


def test_cli_ghi_ket_qua_va_thoat_0_khi_du_must(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAU_LOI", raising=False)
    out = tmp_path / "nt.json"
    assert _load().main(["--repo", str(_ban_mau(tmp_path)), "--cho", "20", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["de_bai"] == "DHCB-B1 v1"


def test_cli_repo_khong_ton_tai_thoat_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _load().main(["--repo", str(tmp_path / "khong-co")]) == 2
    assert "khong-co" in capsys.readouterr().err
