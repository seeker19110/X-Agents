"""Cổng cho tài liệu ĐANG SỐNG: dẫn chiếu mở được, lệnh `cd`/`python -m` chạy được, CODEMAP gọi tên đủ module,
ARCHITECTURE kể đủ job CI, mẫu PR mang đúng khối BÁO CÁO XÁC THỰC của `AGENTS.md`, bảng không hàng nào thừa ô.

Vì sao cần: cải tổ thư mục #262 dời năm package vào `platform/`/`companies/`. #275 sửa số `../` trong `CLAUDE.md`
của package và đặt cổng cho đúng các file đó. Audit 2026-09-28 đo lại thì CÙNG họ lỗi vẫn sống ở các file bên
cạnh: `TRAPS.md`/`README.md`/`ARCHITECTURE.md` của package trỏ `../TRAPS.md` (ra `platform/TRAPS.md`), lệnh
`cd gateway` nằm ngay trong những `CLAUDE.md` đã sửa, `.claude/commands/gate-brief.md` bảo agent `cd
software-company` (thư mục không còn). Cổng phủ một file thì họ lỗi sống ở file bên cạnh — `AGENTS.md` luật bắt
buộc 5: sửa một lỗi thì rà cả họ. File này thay `test_claude_md_package_tro_dung_root_khong_lech_mot_cap` cũ.

Cùng kiểu trôi ở hai bản đồ: `CODEMAP.md` của bốn package không gọi tên 16 module (người muốn đổi hành vi không
tìm ra chỗ sửa), `ARCHITECTURE.md` §CI kể 8/18 job của `ci.yml` và bỏ sót hai workflow.

Tài liệu chia hai loại theo `docs/QUY-TRINH-GIT.md` §5 bước 0: bản ghi lịch sử (ADR, nhật ký phiên, báo cáo,
CHANGELOG, đặc tả/hồ sơ thi hành chụp tại một `main@<sha>`) được giữ dẫn chiếu chết — đó là sự thật của lúc
viết; tài liệu đang sống thì không. Test ở đây theo lối `test_cong_repo.py`: chạy trong `console-unit` trên ba nền.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
import tomllib
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]

# Thư mục bản ghi lịch sử: chụp repo tại một thời điểm, dẫn chiếu chết ở đó là sự thật của lúc ấy.
_THU_MUC_LICH_SU = frozenset({"adr", "sessions", "reports", "archive", "thi-hanh", "specs"})


def _la_lich_su(rel: str) -> bool:
    """`rel` (đường dẫn kiểu git) là bản ghi lịch sử: CHANGELOG, nằm trong thư mục lịch sử, hoặc đặc tả `DAC-TA-*`
    (tự khai "mọi file:dòng đo tại `main@<sha>`" — một ảnh chụp, không phải bản đồ sống)."""
    p = PurePosixPath(rel)
    return rel == "CHANGELOG.md" or p.name.startswith("DAC-TA-") or not _THU_MUC_LICH_SU.isdisjoint(p.parts[:-1])


def _packages() -> list[str]:
    """Thành viên workspace — nguồn sự thật duy nhất về "repo có mấy package"."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["tool"]["uv"]["workspace"]["members"])


def _tai_lieu_song() -> list[str]:
    kq = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True, check=True)
    song = [f for f in kq.stdout.decode("utf-8").split("\0") if f and not _la_lich_su(f)]
    assert song, "git ls-files không trả tài liệu nào — cổng xanh vì rỗng"
    return song


def _goc_package(rel: str) -> Path | None:
    """Gốc package chứa `rel`: lệnh trong tài liệu package chạy từ đó, không từ thư mục của file."""
    return next((ROOT / p for p in _packages() if rel.startswith(p + "/")), None)


def _dong(van: str, vi_tri: int) -> int:
    return van.count("\n", 0, vi_tri) + 1


# --- link markdown ---------------------------------------------------------------------------------------------

_KHOI_CODE = re.compile(r"```.*?```", re.DOTALL)
_CODE_DONG = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_CO_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _bo_code(van: str) -> str:
    """Xoá khối code và code trong dòng nhưng GIỮ vị trí từng ký tự — link trong code không phải link."""
    van = _KHOI_CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), van)
    return _CODE_DONG.sub(lambda m: " " * len(m.group(0)), van)


def test_link_markdown_tuong_doi_mo_duoc() -> None:
    """`[x](../../platform/console/README.md)` viết từ `docs/` trỏ ra ngoài repo: GitHub render thành link 404,
    người đọc bấm vào thì mất đường, và không gì đỏ."""
    hong = []
    for rel in _tai_lieu_song():
        van = _bo_code((ROOT / rel).read_text(encoding="utf-8"))
        for m in _LINK.finditer(van):
            dich = m.group(1)
            if _CO_SCHEME.match(dich) or dich.startswith("#"):
                continue
            duong = unquote(dich.split("#", 1)[0].split("?", 1)[0])
            goc = ROOT if duong.startswith("/") else (ROOT / rel).parent
            if duong and not (goc / duong.lstrip("/")).exists():
                hong.append(f"{rel}:{_dong(van, m.start())}: {dich}")
    assert not hong, f"link tương đối trỏ vào hư không: {hong}"


# --- dẫn chiếu `../` -------------------------------------------------------------------------------------------

# `../x` đứng riêng trong backtick (mọi loại đường dẫn), hoặc `../x.md` trần trong văn xuôi, link hay khối lệnh.
_LEN_CHA = re.compile(r"`((?:\.\./)+[^`\s]*)`|(?<![\w./-])((?:\.\./)+[\w./-]+\.md)\b")
_KHUON = re.compile(r"[<*{$]")                        # `../<slug>`, `../*.md`: khuôn, không phải đường dẫn
_WORKTREE = re.compile(r"^(?:\.\./)+[\w.-]*-wt-")     # worktree anh em của clone (QUY-TRINH-GIT §2b), ngoài repo


def _dan_chieu_len(van: str) -> list[tuple[int, str, str]]:
    """Các dẫn chiếu `../` kiểm được: (vị trí, nguyên văn, đường dẫn đã bỏ `:dòng` và `#neo`)."""
    ra = []
    for m in _LEN_CHA.finditer(van):
        tho = m.group(1) or m.group(2)
        duong = re.sub(r":\d+(?:-\d+)?$", "", tho.split("#", 1)[0]).rstrip("/")
        if not _KHUON.search(duong) and not _WORKTREE.match(duong):
            ra.append((m.start(), tho, duong))
    return ra


def test_dan_chieu_len_thu_muc_cha_mo_duoc() -> None:
    """Mỗi `../` là một lời khai "file này nằm sâu N cấp". Dời package (#262) làm sai mọi lời khai đó cùng lúc, mà
    không cổng tồn-tại-đường-dẫn nào đọc văn xuôi — `../TRAPS.md` từ `platform/gateway/` chỉ ra `platform/`.

    Giải từ thư mục của file (văn xuôi, link) HOẶC gốc package chứa file (lệnh trong tài liệu package chạy từ
    đó, vd `--out ../../.claude/agents`). Không giải từ gốc repo: `../` từ gốc là ra khỏi repo.
    """
    hong = []
    for rel in _tai_lieu_song():
        van = (ROOT / rel).read_text(encoding="utf-8")
        goc = [(ROOT / rel).parent, *filter(None, [_goc_package(rel)])]
        for vi_tri, tho, duong in _dan_chieu_len(van):
            if not any((g / duong).exists() for g in goc):
                hong.append(f"{rel}:{_dong(van, vi_tri)}: {tho}")
    assert not hong, f"dẫn chiếu `../` chết (sai số cấp sau khi dời thư mục?): {hong}"


# --- lệnh `cd` -------------------------------------------------------------------------------------------------

# `cd <đích>` ở đầu một lệnh, trong khối code hay trong backtick. Không bắt "CI/CD" hay "abcd".
_CD = re.compile(r"(?<![\w/.-])cd\s+([^\s`&;|)]+)")
_TEN_CLONE = "x-agents"   # `git clone … && cd x-agents`: thư mục của chính clone, không nằm trong repo


def _dich_cd(van: str) -> list[tuple[int, str]]:
    """Các đích `cd` trỏ VÀO repo, kèm vị trí. Bỏ `..`/`.`, đường tuyệt đối, biến, khuôn `<…>` và tên clone."""
    return [(m.start(), m.group(1)) for m in _CD.finditer(van)
            if m.group(1)[0] not in "./~$<-%\\\"'…" and m.group(1).lower() != _TEN_CLONE]


def test_lenh_cd_tro_thu_muc_that() -> None:
    """`cd gateway`/`cd console`/`cd software-company` là bố cục PHẲNG trước #262. Người làm theo lệnh gặp "No such
    file or directory" ở bước một; agent làm theo `.claude/commands/gate-brief.md` thì không sinh được hồ sơ gate."""
    hong = []
    for rel in _tai_lieu_song():
        van = (ROOT / rel).read_text(encoding="utf-8")
        goc = [ROOT, *filter(None, [_goc_package(rel)])]
        for vi_tri, dich in _dich_cd(van):
            if not any((g / dich).is_dir() for g in goc):
                hong.append(f"{rel}:{_dong(van, vi_tri)}: cd {dich}")
    assert not hong, f"`cd` vào thư mục không tồn tại (tính từ gốc repo hay gốc package): {hong}"


# --- lệnh `python -m` ------------------------------------------------------------------------------------------

_PY_M = re.compile(r"python -m ([A-Za-z_][\w.]*\w)")
_KHOI_MAIN = re.compile(r"""__name__\s*==\s*["']__main__["']""")


def _goc_import() -> dict[str, Path]:
    """Tên import cấp cao nhất của workspace → thư mục `src/` chứa nó (`company` → `companies/software-company/src`)."""
    return {d.name: d.parent for p in _packages() for d in (ROOT / p / "src").iterdir() if (d / "__init__.py").exists()}


def _chay_duoc_bang_m(ten: str, goc_import: dict[str, Path]) -> bool | None:
    """`python -m <ten>` có chạy được không. `None`: không phải module của workspace (`pytest`, `app` của khách…)."""
    phan = ten.split(".")
    if phan[0] not in goc_import:
        return None
    duong = goc_import[phan[0]].joinpath(*phan)
    file = duong.with_suffix(".py")
    return (duong / "__main__.py").is_file() or (file.is_file() and bool(_KHOI_MAIN.search(file.read_text("utf-8"))))


def test_lenh_python_m_tro_module_chay_duoc() -> None:
    """Đo 2026-09-28: `companies/keeper/CLAUDE.md` bảo gõ `python -m keeper run|watch|publish` — package không có
    `__main__.py`, người làm theo nhận "No module named keeper.__main__"; lệnh đúng là `python -m keeper.cli`. Lệnh
    trong tài liệu là lời khai "gõ thế này thì chạy": module phải tồn tại VÀ có đường vào cho `-m`. Câu phủ định
    cũng bị bắt — viết "không có `__main__.py`" thay cho "không có `python -m x`"."""
    goc_import = _goc_import()
    hong = []
    for rel in _tai_lieu_song():
        van = (ROOT / rel).read_text(encoding="utf-8")
        for m in _PY_M.finditer(van):
            if _chay_duoc_bang_m(m.group(1), goc_import) is False:
                hong.append(f"{rel}:{_dong(van, m.start())}: python -m {m.group(1)}")
    assert not hong, f"`python -m` trỏ module không chạy được bằng -m: {hong}"


# --- CODEMAP ---------------------------------------------------------------------------------------------------

_DUOI_FILE = r"(?:ya?ml|json|md|toml|sqlite|txt|html|js|css|sh|lock|example)\b"


def _goi_ten(van: str, module: PurePosixPath) -> bool:
    """`van` gọi tên `company/orch/fsm.py` khi có `fsm.py`, `company.orch.fsm` hoặc `fsm.<tên>` — nhưng `llm.yaml`
    không phải cách gọi tên `llm.py`."""
    ten = re.escape(module.stem)
    cham = re.escape(".".join(module.with_suffix("").parts))
    return re.search(rf"(?<!\w){ten}\.py\b|(?<![\w.]){cham}\b|(?<!\w){ten}\.(?!{_DUOI_FILE})[A-Za-z_]", van) is not None


@pytest.mark.parametrize("pkg", _packages())
def test_codemap_goi_ten_moi_module(pkg: str) -> None:
    """CODEMAP trả lời "muốn đổi X thì sửa ở đâu". Module không có tên trong đó là chỗ sửa không ai tìm ra: đo
    2026-09-28 thiếu 16 module, gồm cả `orch/fsm.py` (bảng chuyển trạng thái) và `console/engine.py` (ADR-0004)."""
    src = ROOT / pkg / "src"
    van = (ROOT / pkg / "CODEMAP.md").read_text(encoding="utf-8")
    modules = [PurePosixPath(f.relative_to(src).as_posix()) for f in src.rglob("*.py") if f.name != "__init__.py"]
    assert modules, f"{pkg}/src không có module nào — cổng xanh vì rỗng"
    thieu = sorted(str(m) for m in modules if not _goi_ten(van, m))
    assert not thieu, f"{pkg}/CODEMAP.md không gọi tên: {thieu} — thêm dòng 'muốn đổi X → sửa ở đây' cho từng module"


# --- ARCHITECTURE §CI ------------------------------------------------------------------------------------------

def _phan_ci() -> str:
    van = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    m = re.search(r"^## CI\b.*?(?=^## |\Z)", van, re.MULTILINE | re.DOTALL)
    assert m, "ARCHITECTURE.md mất phần '## CI' — cổng canh nhầm file hay đã đổi khung?"
    return m.group(0)


def test_architecture_ke_du_workflow_va_job_ci() -> None:
    """`ARCHITECTURE.md` §CI là chỗ README và CONTRIBUTING trỏ về khi hỏi "CI chạy gì". Đo 2026-09-28: nó kể 8/18
    job của `ci.yml` (thiếu cả `core-*` lẫn `drift-check`) và không nhắc `dependency-review.yml`, `eval-record.yml`.
    Thêm job mà quên tài liệu thì đỏ ở đây, trong CÙNG PR."""
    phan = _phan_ci()
    thieu = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        if f"{wf.name}`" not in phan:
            thieu.append(wf.name)
        jobs = yaml.safe_load(wf.read_text(encoding="utf-8")).get("jobs", {})
        thieu += [f"{wf.name}::{job}" for job in jobs if f"`{job}`" not in phan]
    assert not thieu, f"ARCHITECTURE.md §CI không kể: {thieu}"


# --- mẫu PR ↔ AGENTS.md ----------------------------------------------------------------------------------------

def _khoi_bao_cao(van: str) -> str | None:
    """Khối code bắt đầu bằng `BÁO CÁO XÁC THỰC —`, bỏ thụt lề chung (trong `AGENTS.md` nó nằm trong danh sách)."""
    m = re.search(r"^([ \t]*)```\n(\1BÁO CÁO XÁC THỰC — .*?\n)\1```", van, re.MULTILINE | re.DOTALL)
    return textwrap.dedent(m.group(2)) if m else None


def test_mau_pr_mang_nguyen_van_khoi_bao_cao_xac_thuc() -> None:
    """`AGENTS.md` luật cấm 8 bắt điền khối BÁO CÁO XÁC THỰC trước khi nói "sẵn sàng merge", và
    `scripts/pr_dod_check.py` đọc mục cùng tên trong thân PR. Đo 2026-09-28: mẫu PR không có mục đó (Validation còn
    ghi `make lint`/`make test`), nên mỗi PR tự chép khối từ luật — bản chép tay lệch dần. Mẫu phải mang NGUYÊN VĂN."""
    goc = _khoi_bao_cao((ROOT / "AGENTS.md").read_text(encoding="utf-8"))
    assert goc, "AGENTS.md mất khối BÁO CÁO XÁC THỰC — cổng canh nhầm chỗ?"
    mau = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "\n## BÁO CÁO XÁC THỰC\n" in mau, "mẫu PR thiếu mục '## BÁO CÁO XÁC THỰC' mà pr_dod_check.py đọc"
    assert _khoi_bao_cao(mau) == goc, "khối BÁO CÁO XÁC THỰC trong mẫu PR lệch khối trong AGENTS.md"


# --- bảng markdown ---------------------------------------------------------------------------------------------

_HANG_PHAN_CACH = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")


def _so_o(hang: str) -> int:
    """Số ô GFM của một hàng: tách ở mọi `|` không thoát, KỂ CẢ `|` trong code span — GFM tách ô trước khi đọc
    inline, nên muốn giữ `a|b` trong backtick phải viết `a\\|b`."""
    hang = hang.strip().removeprefix("|")
    if hang.endswith("|") and not hang.endswith("\\|"):
        hang = hang[:-1]
    return len(re.split(r"(?<!\\)\|", hang))


def _hang_thua_o(van: str) -> list[tuple[int, int, int]]:
    """`(dòng, ô tiêu đề, ô hàng)` cho mỗi hàng bảng NHIỀU ô hơn tiêu đề. Bảng = hàng mở bằng `|` nằm ngay trên
    một hàng phân cách `|---|`, kéo tới dòng đầu tiên không mở bằng `|`; bảng trong khối code không tính."""
    dong = _KHOI_CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), van).split("\n")
    thua: list[tuple[int, int, int]] = []
    tieu_de: int | None = None
    for i, d in enumerate(dong):
        if not d.lstrip().startswith("|"):
            tieu_de = None
        elif tieu_de is None:
            if i + 1 < len(dong) and _HANG_PHAN_CACH.match(dong[i + 1].strip()):
                tieu_de = _so_o(d)
        elif _so_o(d) > tieu_de:
            thua.append((i + 1, tieu_de, _so_o(d)))
    return thua


def test_bang_markdown_khong_hang_nao_thua_o() -> None:
    """GitHub lặng lẽ bỏ ô vượt số cột tiêu đề — không lỗi, không cảnh báo, chữ cứ thế mất. Đo 2026-09-28: 6 hàng
    trong tài liệu sống, không hàng nào cố ý — cột "Test đối chiếu" của `companies/software-company/CODEMAP.md`
    §Bằng chứng do code sinh (tiêu đề chỉ hai cột), ô "Lần sau" của bẫy `$?` sau pipe trong `TRAPS.md` (`|` trong
    backtick). Hàng ÍT ô hơn thì được điền rỗng, không mất chữ nào — không canh."""
    thua = [f"{rel}:{d} ({m} ô > {n} ô tiêu đề)" for rel in _tai_lieu_song()
            for d, n, m in _hang_thua_o((ROOT / rel).read_text(encoding="utf-8"))]
    assert not thua, f"hàng bảng thừa ô, GitHub bỏ phần thừa (`|` trong code span phải viết `\\|`): {thua}"


# --- chính các bộ lọc ------------------------------------------------------------------------------------------

def test_bo_loc_cua_cong_tai_lieu_dung_y() -> None:
    """Bộ lọc hỏng theo hướng lỏng thì các cổng trên xanh vì rỗng — chốt từng ca biên bằng ví dụ."""
    assert all(map(_la_lich_su, ["CHANGELOG.md", "docs/adr/0001-x.md", "docs/DAC-TA-KICH-BAN-B.md",
                                 "companies/software-company/docs/sessions/x.md", "docs/thi-hanh/k3.7.md"]))
    assert not any(map(_la_lich_su, ["README.md", "platform/console/CLAUDE.md", "docs/HUONG-DAN-VAN-HANH.md",
                                     ".claude/commands/gate-brief.md"]))

    assert _bo_code("a `[x](y)` b\n```\n[z](w)\n```\n[k](l)").count("](") == 1

    assert [t for _, t, _ in _dan_chieu_len(
        "bổ sung `../../AGENTS.md`; xem ../TRAPS.md#muc; `../x.py:12`; `../<slug>`; `../Claude-Agents-wt-a`; "
        "`../../AGENTS.md luật 4`")] == ["../../AGENTS.md", "../TRAPS.md", "../x.py:12", "../../AGENTS.md"]

    assert _dich_cd("`cd platform/gateway && make login`\ncd ../../x\ngit clone … && cd X-Agents") == [
        (1, "platform/gateway")]
    assert _dich_cd("CI/CD chạy; abcd x") == []

    assert _PY_M.findall("uv run python -m keeper.cli drift --repo .; `python -m qlkh...`; python -m app.") == [
        "keeper.cli", "qlkh", "app"]
    goc_import = _goc_import()
    assert set(goc_import) >= {"company", "gateway", "console", "keeper", "xagents_core"}
    assert _chay_duoc_bang_m("keeper.cli", goc_import) and _chay_duoc_bang_m("console", goc_import)
    assert _chay_duoc_bang_m("company.khong_co_module_nay", goc_import) is False
    assert _chay_duoc_bang_m("company.events", goc_import) is False       # có file, không có đường vào `-m`
    assert _chay_duoc_bang_m("pytest", goc_import) is None

    fsm = PurePosixPath("company/orch/fsm.py")
    assert _goi_ten("| bảng chuyển | `orch/fsm.py` |", fsm) and _goi_ten("`company.orch.fsm`", fsm)
    assert _goi_ten("`budget.can_open_pr`", PurePosixPath("keeper/budget.py"))
    assert not _goi_ten("sửa `llm.yaml`", PurePosixPath("company/llm.py"))
    assert not _goi_ten("`paragraph.py`", PurePosixPath("company/graph.py"))

    bang = ("| a | b |\n|---|:-:|\n| `x|y` | z |\n| `x\\|y` | z |\n| một |\n\n| c |\n|---|\n| d | e |\n"
            "```\n| f |\n|---|\n| g | h |\n```\n| i | j | k |\n")
    assert _hang_thua_o(bang) == [(3, 2, 3), (9, 1, 2)]
