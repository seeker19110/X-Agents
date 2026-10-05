"""Cổng cứng cho các file cấu hình CẤP GỐC trỏ vào cây thư mục.

Vì sao cần: cải tổ thư mục #262 (`software-company/` → `companies/software-company/`, `console|gateway|
xagents-core` → `platform/`) làm mọi đường dẫn trong `.pre-commit-config.yaml` và `.github/CODEOWNERS` trỏ vào
hư không. Không có gì gãy, không có gì đỏ — hook `subagents-check` chỉ đơn giản **không bao giờ chạy nữa**, và
CODEOWNERS rút về còn mỗi dòng `*`. Một cổng chết im lặng nguy hiểm hơn không có cổng: người ta vẫn tin nó canh.

Test này ở `platform/console/tests/` theo đúng lối `test_readme_goc.py` — package console là nơi repo đặt các
phép canh cấp gốc (chạy trong job `console-unit` trên cả ba nền).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"

# Tiền tố đường dẫn nghĩa đen trong một regex `files:` — cắt ở ký tự metachar đầu tiên.
_LITERAL = re.compile(r"[\w./-]+")


def _duong_dan_trong_regex(pattern: str) -> list[str]:
    """Các tiền tố đường dẫn nghĩa đen của một regex `files:` của pre-commit.

    `^(a/b/|c/d\\.md|\\.claude/x-)` → ['a/b/', 'c/d.md', '.claude/x-']. Chỉ lấy nhánh nào trông như đường dẫn
    (có dấu `/`); nhánh không có `/` là tiền tố tên file, không kiểm được bằng `exists()`.
    """
    than = pattern.lstrip("^").strip("()")
    ra = []
    for nhanh in than.split("|"):
        m = _LITERAL.match(nhanh.replace("\\", ""))
        if m and "/" in m.group(0):
            ra.append(m.group(0))
    return ra


def _hooks_local() -> list[dict]:
    cfg = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return [h for r in cfg["repos"] if r.get("repo") == "local" for h in r["hooks"]]


def test_moi_tien_to_duong_dan_trong_pre_commit_ton_tai() -> None:
    """`files:` trỏ vào thư mục không tồn tại = hook không bao giờ khớp file nào = cổng chết im lặng."""
    hong: list[str] = []
    for hook in _hooks_local():
        for dd in _duong_dan_trong_regex(hook.get("files", "")):
            goc = dd.rstrip("/")
            # tiền tố kiểu `.claude/agents/sc-` khớp nhiều file: đủ khi THƯ MỤC CHA có thật
            if not (ROOT / goc).exists() and not (ROOT / goc).parent.is_dir():
                hong.append(f"{hook['id']}: {dd}")
    assert not hong, f".pre-commit-config.yaml trỏ vào đường dẫn không tồn tại: {hong}"


def test_project_trong_entry_pre_commit_la_package_that() -> None:
    """`uv run --project <path>` với path sai thì hook lỗi ngay khi chạy, không phải khi review."""
    hong: list[str] = []
    for hook in _hooks_local():
        m = re.search(r"--project\s+(\S+)", hook.get("entry", ""))
        if m and not (ROOT / m.group(1) / "pyproject.toml").is_file():
            hong.append(f"{hook['id']}: --project {m.group(1)}")
    assert not hong, f"--project không trỏ tới package có pyproject.toml: {hong}"


def _ci() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _packages() -> list[str]:
    """Thành viên workspace — nguồn sự thật duy nhất về "repo có mấy package"."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["tool"]["uv"]["workspace"]["members"])


def test_moi_package_co_golden_deu_nam_trong_matrix_golden_check() -> None:
    """`companies/keeper` có `tests/golden/` và target `make golden` nhưng KHÔNG trong matrix `golden-check`:
    sửa prompt keeper mà quên tăng version/commit golden thì CI vẫn xanh. Cổng phải phủ mọi package có golden,
    không phải chỉ package được nhớ tới lúc viết workflow."""
    co_golden = {p for p in _packages() if (ROOT / p / "tests" / "test_golden_agents.py").is_file()}
    trong_matrix = {m["dir"] for m in _ci()["jobs"]["golden-check"]["strategy"]["matrix"]["include"]}
    thieu = sorted(co_golden - trong_matrix)
    assert not thieu, f"package có golden nhưng không được golden-check canh: {thieu}"


def test_quality_needs_phu_moi_job_con() -> None:
    """`quality` là required status check của branch protection; job con không nằm trong `needs` của nó thì
    hỏng cũng không chặn merge — cổng xanh giả. Luật này đang là chú thích trong ci.yml, không ai canh."""
    jobs = _ci()["jobs"]
    needs = set(jobs["quality"]["needs"])
    thieu = sorted(set(jobs) - needs - {"quality"})
    assert not thieu, f"job không có trong `needs` của quality (hỏng vẫn merge được): {thieu}"


# --- Trần cho các lối thoát hợp lệ khỏi `fail_under = 100` -------------------------------------------------
#
# `fail_under = 100` ở cả năm package là cổng mạnh nhất repo có. Nhưng nó có ba lối thoát hợp lệ, và tới trước
# PR này cả ba đều KHÔNG CÓ TRẦN, KHÔNG CÓ HẠN ĐÁO, KHÔNG AI ĐẾM LẠI: thêm bao nhiêu cũng được, coverage vẫn
# khai 100%. Sổ dưới đây là số đo ngày 2026-09-12. Thêm một lối thoát mới ⇒ CI đỏ tới khi sửa số ở đây, tức là
# đi qua review. Bỏ bớt một lối thoát cũng phải sửa số — sổ chỉ có giá trị khi nó khớp chính xác hai chiều.
TRAN_PRAGMA = {                      # `# pragma: no cover` / `no branch` trong src/ của từng package
    "platform/xagents-core": 6,      # `grep 'pragma: no cover'` ra 7: llm.py:509 là văn xuôi NHẮC TỚI
    "platform/gateway": 0,           # `` `pragma: no cover` `` (có backtick), không phải directive
    "platform/console": 2,
    "companies/software-company": 13,  # +3 (#366): `no branch` bắt đầu được đếm khi cả năm package bật
                                       # `branch = true` — mcp_bridge.py:181/183, llm.py:497; cả ba có lời đo
                                       # tracer ngay trên dòng (arc thoát qua `with` bị ghi về dòng `with`)
    "companies/keeper": 4,               # +1 (2026-09-12): PullRequestExists.__str__ (publish.py) — chỉ phục
                                          # vụ traceback người đọc, không ai assert chuỗi này
}
TRAN_SKIP = {                        # skip/xfail trong tests/ của từng package
    "platform/xagents-core": 0,
    "platform/gateway": 3,
    "platform/console": 5,          # +3 (#366): regex cũ bỏ sót `pytestmark` của test_cong_khung.py (bỏ CẢ
                                    # module khi máy thiếu bash) và hai `@POSIX_ONLY` của test_server.py;
                                    # +1 (2026-10-02): test_settings.py quyền nhóm/người khác của `.bak` —
                                    # Windows không có khái niệm đó (chmod chỉ đổi cờ read-only)
    "companies/software-company": 3,  # thêm ca symlink thư mục: chỉ skip khi OS không cấp quyền tạo symlink
    "companies/keeper": 0,
}
TRAN_OMIT = 2                        # dòng `omit` trong pyproject.toml của các package

# Lối thoát thứ tư, và là lối duy nhất KHÔNG phải một dòng người ta thêm vào: `fail_under = 100` trên **dòng**
# vẫn để lọt nhánh chưa đi (`docs/TASK-PACK.md` A6). Package nào chưa `branch = true` thì con số "phủ 100%"
# của nó nông hơn các package kia, mà không chỗ nào nói ra. Sổ này nói ra. Đo 2026-09-14: gateway và console
# chưa bật. Audit 2026-09-27/28 (#366) phủ nốt 27 nhánh của gateway rồi 13 nhánh của console — sổ rỗng, cả năm
# package đo nhánh. Sổ vẫn giữ để canh chiều ngược lại: một package lặng lẽ tắt `branch` thì test đỏ.
# Bật xong một package ⇒ test đỏ tới khi bỏ nó khỏi sổ — sổ chỉ có giá trị khi khớp chính xác hai chiều.
CHUA_PHU_NHANH: set[str] = set()

_PRAGMA = re.compile(r"#\s*pragma:\s*no (?:cover|branch)")
_SKIP = re.compile(r"pytest\.mark\.(?:skipif|skip|xfail)\b|pytest\.(?:skip|xfail|importorskip)\(")
# Marker skip gán vào biến tự nó chưa bỏ ca nào — mỗi `@TEN` mới bỏ một ca, nên đếm chỗ dùng thay chỗ gán.
# `pytestmark` thì pytest tự áp cho CẢ module: chính phép gán là một chỗ bỏ, đếm một.
# no-ky-thuat: chỉ đếm `@TEN` trong cùng file với phép gán, quay lại khi có marker skip dùng chung qua conftest/import
_MARKER_GAN = re.compile(r"^(\w+)\s*=\s*pytest\.mark\.(?:skipif|skip|xfail)\b", re.MULTILINE)
_TU_NO = "test_cong_repo.py"         # chính file này chứa các mẫu trên dưới dạng chuỗi — không tự đếm mình


def _dem_pragma(van_ban: str) -> int:
    return len(_PRAGMA.findall(van_ban))


def _dem_skip(van_ban: str) -> int:
    gan = [ten for ten in _MARKER_GAN.findall(van_ban) if ten != "pytestmark"]
    dung = sum(len(re.findall(rf"^\s*@{re.escape(ten)}\b", van_ban, re.MULTILINE)) for ten in gan)
    return len(_SKIP.findall(van_ban)) - len(gan) + dung


def _dem(thu_muc: Path, dem: Callable[[str], int]) -> int:
    if not thu_muc.is_dir():
        return 0
    return sum(dem(f.read_text(encoding="utf-8", errors="replace"))
               for f in thu_muc.rglob("*.py") if f.name != _TU_NO)


@pytest.mark.parametrize("pkg", sorted(TRAN_PRAGMA))
def test_pragma_no_cover_khong_vuot_tran(pkg: str) -> None:
    that = _dem(ROOT / pkg / "src", _dem_pragma)
    assert that == TRAN_PRAGMA[pkg], (
        f"{pkg}: đếm được {that} `pragma: no cover`, sổ ghi {TRAN_PRAGMA[pkg]}. Mỗi cái là một dòng được miễn "
        f"khỏi fail_under=100 — thêm thì phải sửa số ở đây (đi qua review), bớt thì cũng phải sửa cho khớp.")


@pytest.mark.parametrize("pkg", sorted(TRAN_SKIP))
def test_skip_xfail_khong_vuot_tran(pkg: str) -> None:
    that = _dem(ROOT / pkg / "tests", _dem_skip)
    assert that == TRAN_SKIP[pkg], (
        f"{pkg}: đếm được {that} skip/xfail, sổ ghi {TRAN_SKIP[pkg]}. Ca bị bỏ im lặng không hiện trong "
        f"`pytest -q` — đó là cách 'xanh vì rỗng' sống sót.")


def test_branch_coverage_dung_so_chua_phu_nhanh() -> None:
    """`fail_under = 100` trên dòng vẫn để lọt nhánh (A6). Package nào chưa `branch = true` phải nằm đúng
    trong `CHUA_PHU_NHANH` — không cổng nào canh việc một package lặng lẽ tắt `branch`, và "phủ 100%" của nó
    khi ấy nông hơn hẳn các package còn lại mà tài liệu vẫn nói chung một câu."""
    that = {p for p in _packages()
            if (ROOT / p / "pyproject.toml").is_file()
            and "branch = true" not in (ROOT / p / "pyproject.toml").read_text(encoding="utf-8")}
    assert that == CHUA_PHU_NHANH, (
        f"package chưa `branch = true`: đếm được {sorted(that)}, sổ ghi {sorted(CHUA_PHU_NHANH)}. "
        f"Bật thêm một package thì hạ sổ trong CÙNG PR; tắt đi thì phải nói lý do ở đây (đi qua review).")


def test_omit_khong_vuot_tran() -> None:
    that = sum(1 for p in _packages()
               if (ROOT / p / "pyproject.toml").is_file()
               for line in (ROOT / p / "pyproject.toml").read_text(encoding="utf-8").splitlines()
               if line.strip().startswith("omit"))
    assert that == TRAN_OMIT, (
        f"đếm được {that} dòng `omit`, sổ ghi {TRAN_OMIT}. `omit` bỏ hẳn file khỏi mẫu số 100% — "
        f"nặng hơn `pragma` vì không thấy được ở diff của file bị bỏ.")


KHUNG = ("CLAUDE.md", "TRAPS.md", "CODEMAP.md", "ARCHITECTURE.md")


def test_agents_md_khong_khai_khong_ve_bo_khung_package() -> None:
    """`AGENTS.md` mở đầu bằng "Mỗi package con có CLAUDE.md, TRAPS.md, CODEMAP.md, ARCHITECTURE.md riêng" —
    câu đầu tiên người mới tin. Đo 2026-09-12: `platform/xagents-core` và `companies/keeper` thiếu CẢ BỐN.

    Đây là lời khai sai nằm trong chính file luật (`AGENTS.md` luật cấm 8: không tin lời khai — kể cả của
    mình). Cổng này để câu đó chỉ đúng hoặc bị xoá, không có cửa thứ ba.
    """
    tuyen_bo = "Mỗi package con có" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    thieu = {p: [f for f in KHUNG if not (ROOT / p / f).is_file()] for p in _packages()}
    thieu = {p: f for p, f in thieu.items() if f}
    assert not (tuyen_bo and thieu), (
        f"AGENTS.md khai mọi package có đủ {list(KHUNG)}, nhưng thiếu: {thieu}. "
        f"Hoặc thêm file cho đủ, hoặc sửa câu khai cho đúng thực tế — không để câu sai nằm trong file luật.")


# Dẫn chiếu `../` trong `CLAUDE.md` package (#275) nay canh chung với mọi tài liệu sống ở `test_cong_tai_lieu.py`:
# cổng cũ chỉ đọc CLAUDE.md nên cùng họ lỗi sống tiếp ở TRAPS/README/ARCHITECTURE ngay bên cạnh.


def test_moi_duong_dan_trong_codeowners_ton_tai() -> None:
    """CODEOWNERS trỏ đường dẫn cũ thì luật sở hữu rút về còn dòng `*` — mất hẳn lớp bảo vệ theo vùng."""
    assert CODEOWNERS.is_file(), "repo mất .github/CODEOWNERS"
    hong: list[str] = []
    for dong in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        dong = dong.split("#", 1)[0].strip()
        if not dong:
            continue
        mau = dong.split()[0]
        if mau == "*" or "*" in mau:
            continue
        if not (ROOT / mau.strip("/")).exists():
            hong.append(mau)
    assert not hong, f".github/CODEOWNERS trỏ vào đường dẫn không tồn tại: {hong}"


# --- bản sao luật cho harness khác (`pt.1`) ---------------------------------
#
# Bốn file này tự khai "cố ý không chép lại luật" (`.cursorrules:4`) nhưng thực tế CÓ chép hai danh sách —
# file cấm commit và tên gói — và đã trôi khỏi `AGENTS.md`. Agent không phải Claude Code không có hook nào
# canh, nó đọc đúng bản trôi đó. Cổng này trích danh sách **từ nguồn** rồi soi mọi bản sao; chốt cứng danh
# sách ở đây sẽ tự biến test thành bản sao thứ năm, trôi tiếp.

BAN_SAO_LUAT = (".cursorrules", ".windsurfrules", ".clinerules", "GEMINI.md")
AGENTS_MD = ROOT / "AGENTS.md"

# Mục luật bắt đầu bằng "<số>. " và chạy tới mục kế (hoặc hết phần). Phải DOTALL + non-greedy: phần in đậm mở
# đầu của luật bắt buộc 4 trải HAI dòng, regex một dòng sẽ sót đúng mục đó.
_MUC = re.compile(r"^(\d+)\.[ ](.+?)(?=^\d+\.[ ]|\Z)", re.MULTILINE | re.DOTALL)


def _than_phan(phan: str) -> str:
    """Thân của một phần `## <phan>` trong `AGENTS.md`, cắt trước tiêu đề `##` kế tiếp."""
    van = AGENTS_MD.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(phan)}\n(.*?)(?=^## )", van, re.MULTILINE | re.DOTALL)
    assert m, f"AGENTS.md không còn phần '## {phan}' — cổng này canh nhầm file hay luật đã đổi khung?"
    return m.group(1)


def _cac_muc(phan: str) -> dict[int, str]:
    return {int(so): than for so, than in _MUC.findall(_than_phan(phan))}


def _muc_luat(phan: str, so: int) -> str:
    muc = _cac_muc(phan)
    assert so in muc, f"AGENTS.md '{phan}' không có mục {so} (có: {sorted(muc)})"
    return muc[so]


def _phan_tu(van: str) -> tuple[str, ...]:
    """Các phần tử của một danh sách liệt kê bằng dấu phẩy, bỏ backtick và nhấn mạnh markdown."""
    ra = []
    for tho in van.split(","):
        sach = tho.replace("`", "").replace("**", "").strip().rstrip(".")
        if sach:
            ra.append(sach)
    return tuple(ra)


def _danh_sach_file_cam() -> tuple[str, ...]:
    """Luật cấm 3: mọi thứ liệt kê sau "Không commit", tới hết câu."""
    than = _muc_luat("Luật cấm", 3)
    m = re.search(r"\*\*Không commit\*\*(.+?)\.\s", than, re.DOTALL)
    assert m, "luật cấm 3 đổi cách viết — sửa cổng, đừng sửa luật cho vừa cổng"
    return _phan_tu(m.group(1).replace("\n", " "))


def _danh_sach_goi() -> tuple[str, ...]:
    """Luật bắt buộc 3: tên năm gói + `all` của `dev-task.sh`."""
    than = _muc_luat("Luật bắt buộc", 3)
    m = re.search(r"`gói`:\s*`([^`]+)`", than)
    assert m, "luật bắt buộc 3 đổi cách viết danh sách gói — sửa cổng, đừng sửa luật"
    return tuple(p.strip() for p in m.group(1).split("|") if p.strip())


def test_trich_du_moi_muc_luat_cua_agents_md() -> None:
    """Regex sót một mục = cổng dưới canh thiếu một luật mà không ai biết.

    Bẫy thật: phần in đậm mở đầu luật bắt buộc 4 trải hai dòng, regex `^\\d+\\. \\*\\*(.+?)\\*\\*` một dòng
    sót đúng mục đó.
    """
    cam, bat_buoc = _cac_muc("Luật cấm"), _cac_muc("Luật bắt buộc")
    assert sorted(cam) == list(range(1, 9)), f"đếm được {sorted(cam)} mục ở Luật cấm, mong 1..8"
    assert sorted(bat_buoc) == list(range(1, 12)), f"đếm được {sorted(bat_buoc)} mục ở Luật bắt buộc, mong 1..11"


@pytest.mark.parametrize("ten", BAN_SAO_LUAT)
def test_ban_sao_luat_khong_thieu_phan_tu_danh_sach(ten: str) -> None:
    """Bản sao thiếu một phần tử ⇒ agent đọc nó tin mình đúng luật trong khi đang phá luật.

    Ví dụ đã xảy ra: cả bốn file thiếu "khoá/token, dữ liệu khách thật" của luật cấm 3 — agent commit khoá
    mà không thấy mình sai, và gitleaks quét cả lịch sử nên xoá sau cũng không cứu được.
    """
    f = ROOT / ten
    assert f.is_file(), f"{ten} biến mất — sửa BAN_SAO_LUAT hay khôi phục file?"
    van = f.read_text(encoding="utf-8").replace("`", "")
    thieu = [p for p in _danh_sach_file_cam() + _danh_sach_goi() if p not in van]
    assert not thieu, (
        f"{ten} chép lại danh sách của AGENTS.md nhưng thiếu: {thieu}. Bản sao trôi là bản sao nguy hiểm — "
        f"thêm cho đủ, hoặc bỏ hẳn bản chép và chỉ trỏ về AGENTS.md.")


@pytest.mark.parametrize("ten", ["company.sqlite-wal", "company.sqlite-shm", "company.sqlite.lock",
                                 "companies/keeper/x.sqlite-wal", "platform/console/c.sqlite.lock"])
def test_file_anh_em_cua_bus_bi_gitignore(ten):
    """Audit 2026-09-27 (H): bus chạy WAL (`xagents_core/sqlite_bus.py`) nên mỗi `*.sqlite` có hai file anh em
    `-wal`/`-shm`, cộng `.lock` của lease. `.gitignore` bắt `*.sqlite` mà không bắt ba đuôi đó → chạy nhầm một lệnh
    ở gốc là `git status` bẩn, và `git add -A` là commit một mảnh bus (luật cấm 3)."""
    import subprocess

    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", ten], cwd=ROOT, capture_output=True)
    assert r.returncode == 0, f"{ten} chưa bị .gitignore bắt"


@pytest.mark.parametrize("ten", ["companies/software-company/llm.yaml.tmp", "companies/keeper/llm.yaml.tmp",
                                 "companies/software-company/llm.yaml.bak", "companies/keeper/llm.yaml.bak"])
def test_ban_tam_cua_llm_yaml_bi_gitignore(ten):
    """Console ghi `llm.yaml` qua `.tmp` rồi `os.replace`, sao lưu ra `.bak` (`console/settings.py:_atomic_write`):
    cả hai mang khoá API như bản gốc. Chết giữa hai bước là `.tmp` nằm lại — `.gitignore` không bắt thì `git add
    -A` commit khoá (luật cấm 3)."""
    import subprocess

    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", ten], cwd=ROOT, capture_output=True)
    assert r.returncode == 0, f"{ten} chưa bị .gitignore bắt"


def test_bo_dem_loi_thoat_bat_du_cac_dang_viet() -> None:
    """F-C (audit 2026-09-28, #366): hai bộ đếm cũ hụt ở ba dạng có thật trong repo — `pytestmark =
    pytest.mark.skipif(...)` (bỏ CẢ module), marker skip gán vào biến rồi dùng `@TEN` (mỗi `@TEN` bỏ một ca),
    và `# pragma: no branch` (miễn một nhánh khỏi `branch = true`). Sổ khớp đúng số mà bộ đếm hụt thì sổ nói
    ít hơn thật — đúng hướng lệch cổng này sinh ra để chặn."""
    van_ban = (
        'pytestmark = pytest.mark.skipif(X, reason="a")\n'
        'POSIX_ONLY = pytest.mark.skipif(Y, reason="b")\n'
        "@POSIX_ONLY\ndef test_a(): ...\n"
        "@POSIX_ONLY\ndef test_b(): ...\n"
        '@pytest.mark.xfail(reason="c")\ndef test_c(): ...\n'
        'def test_d():\n    pytest.skip("d")\n'
        'np = pytest.importorskip("numpy")\n'
    )
    assert _dem_skip(van_ban) == 6   # pytestmark + 2 × @POSIX_ONLY + xfail + skip( + importorskip(
    assert _dem_pragma("x = 1  # pragma: no cover\nif a: b  # pragma: no branch\n") == 2
