"""README gốc (`/README.md`) không được lệch số ADR/agent thật của software-company trên đĩa.

Không trùng với `test_readme_khop_so_lieu_that` (canh README package) — test này chỉ canh README gốc.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.cong_repo   # đọc file ngoài gói console → hook chạy cả ở chế độ nhanh (F6)
ROOT_README = ROOT / "README.md"
COMPANY_ROW_RE = re.compile(
    r"\[`companies/software-company/`\].*?7 khối, (\d+) agent.*?ADR (\d{4})–(\d{4})",
)


def _company_row() -> re.Match[str]:
    text = ROOT_README.read_text(encoding="utf-8")
    match = COMPANY_ROW_RE.search(text)
    assert match, "README gốc: không tìm thấy dòng software-company đúng khuôn 7 khối/agent/ADR"
    return match


def test_so_agent_khop_dia() -> None:
    agent_files = list((ROOT / "companies" / "software-company" / "agents").glob("*/*.md"))
    match = _company_row()
    assert int(match.group(1)) == len(agent_files), (
        f"README gốc ghi {match.group(1)} agent nhưng companies/software-company/agents/*/*.md có {len(agent_files)} file"
    )


def test_so_adr_khop_dia() -> None:
    adr_files = list((ROOT / "companies" / "software-company" / "docs" / "adr").glob("*.md"))
    match = _company_row()
    adr_dau, adr_cuoi = int(match.group(2)), int(match.group(3))
    assert adr_cuoi - adr_dau + 1 == len(adr_files), (
        f"README gốc ghi ADR {match.group(2)}–{match.group(3)} "
        f"({adr_cuoi - adr_dau + 1} bản) nhưng companies/software-company/docs/adr/*.md có {len(adr_files)} file"
    )


# Dòng treo từ 2026-09-07 trong `docs/TASK-PACK.md`: cổng cũ chỉ canh software-company, nên dãy ADR của
# console lệch (README ghi 0001–0003 khi đĩa có 4) sống được 5 ngày mà không gì đỏ. Repo có BỐN dãy ADR cùng
# đánh số từ 0001, canh một dãy là bỏ ba.
# `[^\n]*?` chứ không `.*?` + `re.S`: đo 2026-09-28, dòng gateway KHÔNG khai dãy ADR nào mà phép vẫn xanh — nó trượt
# xuống dòng console bên dưới và mượn "ADR 0001–0004" của console (hai dãy tình cờ cùng dài). Phải đọc trong đúng dòng.
DAY_ADR = {
    "platform/console": r"\[`platform/console/`\][^\n]*?ADR (\d{4})–(\d{4})",
    "platform/gateway": r"\[`platform/gateway/`\][^\n]*?ADR (\d{4})–(\d{4})",
}


@pytest.mark.parametrize("pkg", sorted(DAY_ADR))
def test_so_adr_cac_day_khac_khop_dia(pkg: str) -> None:
    thu_muc = ROOT / pkg / "docs" / "adr"
    tren_dia = len([f for f in thu_muc.glob("*.md") if f.name != "README.md"])
    m = re.search(DAY_ADR[pkg], ROOT_README.read_text(encoding="utf-8"), re.S)
    assert m is not None, f"README gốc chưa khai dãy ADR cho {pkg} — thêm dòng ADR NNNN–NNNN vào bảng"
    khai = int(m.group(2)) - int(m.group(1)) + 1
    assert khai == tren_dia, f"README gốc ghi {khai} ADR cho {pkg} nhưng {thu_muc} có {tren_dia} file"


# `| [`companies/keeper/`](…) | … | … 553 test |` — một dòng bảng "Quy mô" của README gốc.
_DONG_GOI = re.compile(r"^\|\s*\[`([^`]+?)/?`\]\([^)]*\).*?\b(\d+) test\b", re.MULTILINE)


def _dem_that(goi: str) -> int:
    """Số ca `pytest` THẬT của một package — hỏi chính pytest, không đếm `def test_` bằng tay.

    Đếm bằng grep thì sai ở mọi chỗ có `parametrize`, mà repo này dùng `parametrize` khắp nơi (`test_cong_repo`
    chạy một ca cho mỗi package). Sai theo hướng nói ÍT hơn thật — đúng hướng lệch mà phép này sinh ra để bắt.
    """
    # `uv run --directory` chứ không `sys.executable -m pytest`: mỗi package có nhóm dev riêng — chạy pytest của
    # console trong thư mục gateway thì 10 file lỗi thu thập vì thiếu `pytest-asyncio`, và một cổng "đếm được 0"
    # là cổng nói dối chứ không phải cổng đỏ. `uv` luôn có: CI chạy test bằng chính nó.
    kq = subprocess.run(
        ["uv", "run", "--directory", str(ROOT / goi), "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    m = re.search(r"(\d+) tests? collected", kq.stdout)
    assert m, f"không đọc được số ca của {goi}: {kq.stdout[-500:]}\n{kq.stderr[-500:]}"
    return int(m.group(1))


def test_so_test_trong_readme_khop_dia() -> None:
    """Số test README khai phải bằng số pytest thu được — **không có cổng nào canh dòng này trước 2026-09-15**.

    Vì sao đáng một phép riêng: bản tự kiểm 2026-09-07 đã bắt 5/10 dòng số liệu README lệch với đĩa, **tất cả
    đều lệch một chiều "nói ít hơn thật"** và đúng những dòng KHÔNG có test CI canh. Sửa số một lần thì ba tháng
    sau lệch lại — thứ duy nhất giữ được là một cổng. Đo lại 2026-09-15 trước khi viết phép này: company
    1249→1256, gateway 251→256, core 479→488, cùng một chiều lệch, y hệt lần trước.

    Con số nói ít hơn thật không vô hại: nó là lời khai về quy mô kiểm thử, và người đọc README (kể cả agent
    phiên sau) dùng nó để quyết định có tin bộ test hay không.
    """
    doc = (ROOT / "README.md").read_text(encoding="utf-8")
    khai = {goi: int(so) for goi, so in _DONG_GOI.findall(doc)}
    assert khai, "không dòng nào của bảng README khai số test — regex hỏng chứ không phải README sạch"

    lech = {goi: (so, that) for goi, so in khai.items() if (that := _dem_that(goi)) != so}
    assert not lech, (
        "README khai số test không khớp đĩa (khai, thật): "
        + repr(lech)
        + " — sửa README trong CÙNG PR làm số đổi, đừng để lại cho phiên audit."
    )


def test_fail_under_trong_readme_khop_pyproject() -> None:
    """Dòng `fail_under` của README gốc khớp `pyproject.toml` từng gói — đo 2026-09-05 nó ghi 90 cho công ty khi
    pyproject đã nâng lên 98.

    Dời từ `test_review_fixes_2026_09.py` của software-company (2026-09-28): test ở company đọc README gốc thì commit
    chỉ sửa README không chạy nó, vì hook chạy cổng gói bị đụng + console (`test_cong_khung.py` `TEST_DOC_NGOAI_GOI`).
    """
    dong = next((ln for ln in ROOT_README.read_text(encoding="utf-8").splitlines() if "`fail_under`" in ln), "")
    m = re.search(r"`fail_under` ([\d /]+) cho ([\w\- /]+)", dong)
    assert m, "README gốc phải ghi '`fail_under` a / b / … cho <gói> / <gói> …' trên một dòng"
    khai = [int(x) for x in m.group(1).split("/")]
    goi = [p.strip() for p in m.group(2).split(" / ")]  # tên gói có `/` (ADR-0011) → tách theo " / ", không "/"
    assert len(khai) == len(goi), f"{len(khai)} ngưỡng nhưng {len(goi)} gói"
    for so, ten in zip(khai, goi, strict=True):
        cfg = tomllib.loads((ROOT / ten / "pyproject.toml").read_text(encoding="utf-8"))
        that = cfg["tool"]["coverage"]["report"]["fail_under"]
        assert so == that, f"README gốc ghi fail_under của {ten} là {so}, pyproject.toml nói {that}"


# Dòng mở/đóng conflict của git — `=======` không đủ (bảng Markdown, gạch dưới tiêu đề Setext đều hợp lệ).
_CONFLICT_MARKER = re.compile(r"^(<<<<<<< |>>>>>>> )", re.MULTILINE)


def test_khong_file_nao_con_conflict_marker() -> None:
    """Không file nào git theo dõi còn dấu conflict `<<<<<<< ` / `>>>>>>> ` ở đầu dòng.

    Vì sao đáng một phép riêng: PR #307 (2026-09-15) đưa lên `main` một `README.md` còn nguyên cả hai nhánh
    conflict ở bảng "Quy mô", và không cổng nào đỏ — `test_so_test_trong_readme_khop_dia` gom dòng bảng vào
    dict nên bản chép sau đè bản chép trước, còn Markdown thì render marker như chữ thường. Tức README nói
    hai số khác nhau cho cùng một gói suốt một tuần mà máy vẫn xanh. Marker là thứ xác định (đầu dòng, bảy ký
    tự, một dấu cách) nên canh bằng cổng, không canh bằng mắt người review.
    """
    kq = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    dinh = []
    for ten in kq.stdout.decode("utf-8").split("\0"):
        duong = ROOT / ten
        if not ten or not duong.is_file():
            continue
        try:
            noi_dung = duong.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # file nhị phân hoặc không đọc được — git merge cũng không chèn marker vào đó
        for m in _CONFLICT_MARKER.finditer(noi_dung):
            dinh.append(f"{ten}:{noi_dung.count(chr(10), 0, m.start()) + 1}")
    assert not dinh, "file còn conflict marker của git (giải conflict rồi mới commit): " + ", ".join(dinh)
