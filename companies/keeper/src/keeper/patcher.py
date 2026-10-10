"""`patcher` — ĐÚNG BA thao tác vá, trong worktree riêng của ticket (BT5, `DAC-TA-KEEPER.md` §7).

Ba thao tác: `bump_dependency`, `regen_derived` (`make golden`, `make subagents`), `fix_docs` (dòng
`CHANGELOG.md` / mục nhật ký phiên). Không có thao tác thứ tư, và đặc biệt:

**I5 — `patcher` KHÔNG có thao tác xoá file *nội dung repo*.** Không `unlink`, không `rmtree`, không
`os.remove`, không đổi tên. Thấy dead code thì BÁO CÁO (signal), không xoá (`AGENTS.md` cấm §7). Ràng buộc
này được ép bằng một test đọc AST của chính file này, không phải bằng lời hứa trong tài liệu. Phạm vi I5 hẹp
đúng như vậy: nó nói về **nội dung repo**, KHÔNG nói về vòng đời worktree của chính `keeper` — `worktree.py`
vẫn có `git clean -fd` và `worktree remove --force`, nhưng chỉ trên worktree phụ do keeper tạo, sau chốt
`refuse_shared_checkout`. Hai chuyện khác nhau, đừng đọc lời hứa của cái này thành lời hứa của cái kia.

**CHỐT GHI — mọi đường ghi chạy trong worktree PHỤ.** `apply_edits` và `regen_derived` gọi
`refuse_shared_checkout(root)` TRƯỚC khi chạm gì. Không có chốt này thì `keeper run --root .` gõ nhầm trong
checkout chung sẽ ghi thẳng `CHANGELOG.md` của phiên khác — và `make` chạy với cwd bất kỳ. Chốt phải ở đường
GHI, không chỉ ở hai hàm dọn của `worktree.py`.

**I4 — đường cấm.** `FORBIDDEN_PATHS` chặn `.git/`, `.github/` (CẢ thư mục: `workflows/` chứa chính cổng CI
đang ép `fail_under`, gitleaks và ruleset — sửa được nó là gỡ được mọi chốt còn lại), `llm.yaml`,
`media.yaml`, `*.sqlite*`; và một chốt RIÊNG cấm HẠ ngưỡng coverage. Chốt ngưỡng phải tách khỏi bảng đường
dẫn vì `pyproject.toml` **được phép** sửa (bump dependency chính là sửa nó) — cấm là cấm đúng một giá trị,
không cấm cả file.

**Cạm bẫy §7 — agents/ và skills/ KHÔNG phải việc của máy.** Một patch chạm `*/agents/**` hay `*/skills/**`
bắt buộc đủ bảy bước `CONTRIBUTING.md` §3, trong đó `make eval-record` cần MODEL THẬT — `patcher` không có
model thật và không được giả vờ có. Nên nhánh này là một lời TỪ CHỐI tường minh (`NeedsHumanDecision`, kèm
`risk_tier="high"`) chứ không phải một cảnh báo rồi vẫn ghi. Câu cấm nằm ngay trong mã, không chỉ trong prompt.

Thứ tự kiểm cố định và kiểm HẾT trước khi ghi byte đầu tiên: một `Edit` hỏng trong lô làm cả lô không được
ghi. Vá nửa vời trong worktree là thứ khó phát hiện nhất khi đọc PR.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from xagents_core.sandbox import clean_env

from .events import PatchProposal
from .worktree import BRANCH_PREFIX, git_env, refuse_shared_checkout, slug

# Mẫu kết thúc bằng "/" là một CHUỖI SEGMENT: khớp khi nó xuất hiện làm tiền tố segment ở bất kỳ đâu trong
# đường dẫn — nên `.github/rulesets` (không có "/" cuối, chính THƯ MỤC đó) cũng bị chặn, chứ không lọt rồi nổ
# `IsADirectoryError` lúc ghi. Mẫu không có "/" khớp theo TÊN file (`fnmatch`).
FORBIDDEN_PATHS: tuple[str, ...] = (".git/", ".github/", "llm.yaml", "media.yaml", "*.sqlite*")
HUMAN_ONLY_SEGMENTS: tuple[str, ...] = ("agents", "skills")
# Target `make` mà `patcher` BIẾT. Mặc định chỉ `golden` — `subagents` nằm trong bảng để nhận diện và từ chối
# tường minh (xem `TARGET_WRITES_HUMAN_ONLY`), không phải để chạy.
MAKE_TARGETS: tuple[str, ...] = ("golden", "subagents")
DEFAULT_TARGETS: tuple[str, ...] = ("golden",)

# Target `make` nào GHI vào vùng chỉ-người-được-quyết. Bảng này để từ chối TRƯỚC KHI chạy `make`, không phải
# sau: `make subagents` ghi thẳng ra `.claude/agents/sc-*.md` (`software-company/src/company/subagents.py:28`),
# nên nếu chỉ kiểm đường dẫn ở bước "file nào đã đổi" thì lệnh đã kịp ghi rồi mới bị từ chối — và `patcher`
# không được xoá file (bất biến I5), nên rác nằm lại trong worktree. Chốt phải đứng trước hành động.
TARGET_WRITES_HUMAN_ONLY: dict[str, str] = {"subagents": ".claude/agents/"}
# Ngưỡng coverage viết ở dạng cờ dòng lệnh (`Makefile`, workflow, `tox.ini`, `setup.cfg`, `.coveragerc`).
# `pyproject.toml` đi đường riêng, đọc bằng `tomllib` (xem `check_coverage_guard`).
_COV_FLAG = re.compile(r"(?:--cov-)?fail[-_]under[\s=]+(\d+(?:\.\d+)?)", re.IGNORECASE)

Runner = Callable[[list[str], Path], tuple[int, str]]
ChangedFiles = Callable[[Path], list[str]]


class ForbiddenPath(Exception):
    """Patch chạm đường cấm của bất biến I4."""


class NeedsHumanDecision(Exception):
    """Patch thuộc nhóm phải đủ bảy bước `CONTRIBUTING.md` §3 → mở ticket `high`, để NGƯỜI quyết."""

    risk_tier = "high"


@dataclass(frozen=True)
class Edit:
    """Một file sẽ được ghi ĐÈ bằng `new_text`. Không có biến thể "xoá file" — xem I5 ở docstring module."""
    path: str
    new_text: str


def _norm(rel: str) -> str:
    return rel.replace("\\", "/")


def check_path(root: Path, rel: str, *, forbidden: Sequence[str] = FORBIDDEN_PATHS) -> Path:
    """Kiểm một đường dẫn tương đối; trả về đường dẫn tuyệt đối đã chuẩn hoá.

    Ba phép, theo thứ tự: thoát khỏi `root` → cấm; khớp bảng đường cấm → `ForbiddenPath`; chạm
    `agents/`/`skills/` → `NeedsHumanDecision`.

    Hai chi tiết có lý do: (1) mọi phép khớp chạy trên `target.relative_to(root)` — đường dẫn ĐÃ resolve —
    chứ không trên chuỗi `rel` người gọi đưa vào; khớp ở một không gian rồi ghi ở không gian khác là hình
    dạng TOCTOU cổ điển (`a/../llm.yaml` khác `llm.yaml` khi so chuỗi, giống hệt nhau sau khi resolve).
    (2) So sánh LUÔN không phân biệt hoa/thường, trên mọi nền: không phải vì Windows, mà vì cổng chặn không
    được có hành vi khác nhau theo nền tảng (`TRAPS.md` §2) — và phía chặn nhiều hơn là phía an toàn."""
    base = root.resolve()
    target = (root / _norm(rel)).resolve()
    if base not in target.parents:
        raise ForbiddenPath(f"{rel}: nằm ngoài worktree {root} — patcher chỉ ghi trong worktree của ticket")
    parts = _norm(str(target.relative_to(base))).split("/")
    low = [p.lower() for p in parts]
    for pat in forbidden:
        p = _norm(pat).lower()
        if p.endswith("/"):
            seg = [x for x in p.split("/") if x]
            khop = any(low[i:i + len(seg)] == seg for i in range(len(low)))
        else:
            khop = any(x == p or fnmatch.fnmatch(x, p) for x in low)
        if khop:
            raise ForbiddenPath(f"{rel}: đường cấm (bất biến I4, mẫu {pat!r})")
    if any(seg in low for seg in HUMAN_ONLY_SEGMENTS):
        raise NeedsHumanDecision(
            f"{rel}: chạm agents/ hoặc skills/ — bắt buộc bảy bước CONTRIBUTING.md §3, trong đó `make "
            f"eval-record` cần model thật. patcher không tự làm nhóm này: mở ticket risk_tier=high để người quyết")
    return target


def _fail_under_toml(text: str) -> float | str | None:
    """`tool.coverage.report.fail_under` của một `pyproject.toml`. `"hong"` khi text không phải TOML hợp lệ."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return "hong"
    v = data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    return v if isinstance(v, int | float) else None


def _giu_duoc(cu: list[float], moi: list[float]) -> bool:
    """Mỗi ngưỡng cũ phải còn một ngưỡng mới ≥ nó (ghép từ lớn xuống). Bớt số cũng là hạ."""
    if len(moi) < len(cu):
        return False
    cu_s, moi_s = sorted(cu, reverse=True), sorted(moi, reverse=True)
    return all(m >= c for c, m in zip(cu_s, moi_s[:len(cu_s)], strict=True))


def check_coverage_guard(target: Path, new_text: str) -> None:
    """Bất biến I4: không HẠ ngưỡng coverage, ở bất kỳ file nào khai nó.

    So **giá trị**, không so dòng. Chốt cũ so danh sách dòng khớp `^\\s*fail_under\\s*=` nên lọt hết những
    cách hạ ngưỡng mà dòng vẫn y nguyên: đổi header `[tool.coverage.report]` thành `[tool.coverage.paths]`,
    hay chèn thêm một mục `[tool.coverage.report]` khác đè lên mục sau. Dòng giống nhau không có nghĩa là
    ngưỡng còn hiệu lực — chỉ giá trị đọc ra từ đúng mục mới nói được điều đó, nên `pyproject.toml` đi qua
    `tomllib`. TOML mới hỏng cũng là chặn: file không parse được thì ngưỡng cũng không còn hiệu lực (bản CŨ
    hỏng thì không có gì để giữ, cho qua).

    Ngoài `pyproject.toml`, cùng phép so chạy trên `--cov-fail-under` / `fail_under` dạng cờ dòng lệnh của
    MỌI file khác (`Makefile`, `setup.cfg`, `tox.ini`, `.coveragerc`, workflow…). Không có danh sách tên file
    nào cả: danh sách nào cũng thiếu đúng cái file người ta nghĩ ra sau."""
    if not target.exists():
        return   # file mới: không có ngưỡng cũ nào để giữ
    cu_text = target.read_text(encoding="utf-8")
    if target.name.lower() == "pyproject.toml":
        cu = _fail_under_toml(cu_text)
        if isinstance(cu, int | float):
            moi = _fail_under_toml(new_text)
            if not isinstance(moi, int | float) or moi < cu:
                raise ForbiddenPath(
                    f"{target.name}: tool.coverage.report.fail_under {cu} → {moi!r} là hạ ngưỡng coverage "
                    f"(bất biến I4). Ngưỡng mất hiệu lực vì đổi mục hay vì TOML hỏng đều tính là hạ")
    cu_flag = [float(x) for x in _COV_FLAG.findall(cu_text)]
    if cu_flag and not _giu_duoc(cu_flag, [float(x) for x in _COV_FLAG.findall(new_text)]):
        raise ForbiddenPath(f"{target.name}: hạ/bỏ ngưỡng fail_under {cu_flag} (bất biến I4)")


def apply_edits(root: Path, edits: Sequence[Edit], *, operation: str, ticket_id: str,
                forbidden: Sequence[str] = FORBIDDEN_PATHS, coverage_guard: bool = True,
                write_guard: bool = True, summary: str = "") -> PatchProposal:
    """Kiểm HẾT rồi mới ghi. `forbidden`, `coverage_guard` và `write_guard` mở ra để ca "chiều ngược" TẮT
    được đúng bản sửa và đo thiệt hại thật — mã sản xuất không bao giờ truyền chúng.

    `write_guard` là chốt worktree: `root` phải là worktree PHỤ của keeper. Đây là đường GHI duy nhất của
    `patcher`, nên chốt đứng ở đây là đủ cho cả ba thao tác."""
    if write_guard:
        refuse_shared_checkout(root)
    targets: list[Path] = []
    for e in edits:
        t = check_path(root, e.path, forbidden=forbidden)
        if coverage_guard:
            check_coverage_guard(t, e.new_text)
        targets.append(t)
    for t, e in zip(targets, edits, strict=True):
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(e.new_text, encoding="utf-8", newline="\n")
    return PatchProposal(ticket_id=ticket_id, branch=f"{BRANCH_PREFIX}{slug(ticket_id)}",
                         operation=operation,  # type: ignore[arg-type]
                         summary=summary or f"{operation}: {len(edits)} file",
                         files=[_norm(e.path) for e in edits])


def bump_dependency(root: Path, ticket_id: str, *, package: str, new_spec: str,
                    files: Sequence[str] = ("pyproject.toml",)) -> PatchProposal:
    """Thay MỌI ràng buộc phiên bản của `package` bằng `new_spec` trong các file đã nêu.

    Không tìm thấy gói ở đâu cả → `ValueError`, không ghi gì: một bump không khớp chỗ nào là dấu hiệu signal
    sai chủ thể, không phải chuyện im lặng bỏ qua."""
    # Chỉ CHUỖI requirement: tên gói ngay sau dấu nháy mở, spec xong là hết chuỗi (`"`, `'`), tới marker (`;`) hoặc
    # ràng buộc kế (`,`) — không phải comment, mô tả hay khoá TOML (`[tool.uv.sources] pkg = {…}`), và vì neo nháy
    # nên `pytest` cũng không khớp `pytest-cov`/`xpytest`/`[tool.pytest.ini_options]`. Có extras (`pkg[x]`) thì bỏ
    # qua: `new_spec` không mang extras, thay là mất chúng.
    pattern = re.compile(rf"(?<=[\"']){re.escape(package)}(?:[ \t]*[=<>!~^]=?[ \t]*[^\"',;\s]*)?(?=[ \t]*[\"',;])")
    edits: list[Edit] = []
    for rel in files:
        target = check_path(root, rel)
        text = target.read_text(encoding="utf-8")
        moi, n = pattern.subn(lambda _m: new_spec, text)  # new_spec là chữ, không phải mẫu thay thế regex
        if n:
            edits.append(Edit(rel, moi))
    if not edits:
        raise ValueError(f"không tìm thấy {package} trong {list(files)} — signal sai chủ thể?")
    return apply_edits(root, edits, operation="bump_dependency", ticket_id=ticket_id,
                       summary=f"bump {package} → {new_spec}")


def fix_docs(root: Path, ticket_id: str, *, changelog_line: str = "", session_line: str = "",
             session_date: str = "", changelog: str = "CHANGELOG.md") -> PatchProposal:
    """Thêm một dòng `CHANGELOG.md` (mới nhất TRÊN CÙNG, ngay dưới tiêu đề — `AGENTS.md` §10) và/hoặc một mục
    `docs/sessions/<ngày>.md`. Chỉ THÊM, không bao giờ bỏ dòng nào của bản cũ."""
    edits: list[Edit] = []
    if changelog_line:
        target = check_path(root, changelog)
        cu = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        vi_tri = 1 if cu and cu[0].startswith("#") else 0
        moi = cu[:vi_tri] + ([""] if vi_tri else []) + [changelog_line] + cu[vi_tri:]
        edits.append(Edit(changelog, "\n".join(moi) + "\n"))
    if session_line:
        if not session_date:
            raise ValueError("session_line cần session_date (tên file nhật ký phiên)")
        rel = f"docs/sessions/{session_date}.md"
        target = check_path(root, rel)
        cu_text = target.read_text(encoding="utf-8") if target.exists() else f"# Phiên {session_date}\n\n"
        if not cu_text.endswith("\n"):
            cu_text += "\n"
        edits.append(Edit(rel, cu_text + session_line + "\n"))
    if not edits:
        raise ValueError("fix_docs cần ít nhất một trong changelog_line / session_line")
    return apply_edits(root, edits, operation="fix_docs", ticket_id=ticket_id, summary="cập nhật tài liệu")


def default_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    """Chạy thật một lệnh, env đã lọc khoá (`clean_env`) và không hook."""
    r = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                       env=clean_env(), timeout=900)
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-4000:]


def _changed_files(root: Path, *, strict: bool = True) -> list[str]:
    """File đã đổi trong `root`. `git status` thất bại → NỔ, không trả danh sách rỗng.

    Không kiểm `returncode` là khuôn lỗi "số xanh vì rỗng": `root` không phải repo, hay không có `git` trên
    máy, thì stdout rỗng → `files == []` → vòng `check_path` của `regen_derived` chạy 0 lần → proposal trả về
    THÀNH CÔNG dù `make` vừa ghi bất cứ thứ gì. Chốt đọc rỗng là chốt không tồn tại.

    `-z` + `core.quotepath=false`: dạng mặc định escape tên non-ASCII (`"keeper/skills/v\\303\\241.md"`) và
    ghép đổi tên thành một chuỗi `cũ -> mới`, nên cắt `line[3:]` cho ra một đường dẫn không có thật —
    `check_path` soi nó sẽ không thấy `agents/` ở đích. Dạng `-z` tách từng đường dẫn bằng NUL và để `origPath`
    thành trường riêng; cả HAI đầu của một lần đổi tên đều được kiểm.

    `strict=False` chỉ dành cho ca "chiều ngược" dựng lại đúng hành vi nuốt lỗi cũ. Đừng gọi từ mã sản xuất."""
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", "status", "--porcelain",
                        "-uall", "-z"], capture_output=True, text=True, encoding="utf-8", env=git_env(),
                       timeout=120)
    if r.returncode != 0 and strict:
        raise RuntimeError(f"git status trong {root} thất bại (exit {r.returncode}): "
                           f"{(r.stderr or r.stdout).strip()[:300]}")
    toks = r.stdout.split("\0")
    files: set[str] = set()
    i = 0
    while i < len(toks):
        t = toks[i]
        i += 1
        if len(t) < 4:
            continue
        files.add(_norm(t[3:]))
        if t[0] in "RC" or t[1] in "RC":   # `origPath` là trường NUL riêng ngay sau
            if i < len(toks) and toks[i]:
                files.add(_norm(toks[i]))
            i += 1
    return sorted(files)


def regen_derived(root: Path, ticket_id: str, *, targets: Sequence[str] = DEFAULT_TARGETS,
                  runner: Runner | None = None, write_guard: bool = True,
                  changed_files: ChangedFiles | None = None) -> PatchProposal:
    """Sinh lại bản dẫn xuất bằng `make <target>` (`AGENTS.md` cấm §5: sửa nguồn rồi SINH LẠI, không sửa tay).

    Ba chốt, theo đúng thứ tự này:

    0. TRƯỚC KHI CHẠM GÌ — `refuse_shared_checkout(root)`: `make` chạy với cwd là `root`, tức là một lệnh ghi
       vào bất cứ đâu người gọi trỏ tới. `root` phải là worktree phụ của keeper (`write_guard` chỉ để ca
       chiều ngược tắt được).
    1. TRƯỚC khi chạy — `TARGET_WRITES_HUMAN_ONLY`: `make subagents` ghi ra `.claude/agents/sc-*.md`, vùng
       bắt buộc bảy bước `CONTRIBUTING.md` §3. Từ chối ngay, không chạy. Kiểm sau khi chạy là quá muộn: lệnh
       đã ghi file, và `patcher` không được xoá (I5) nên rác nằm lại.
    2. SAU khi chạy — `check_path` trên mọi file đã đổi, phòng khi một target hợp lệ ghi ra chỗ bất ngờ.

    `make golden` chỉ ghi `tests/golden/**`, không chạm vùng người, nên đi qua bình thường."""
    if write_guard:
        refuse_shared_checkout(root)
    la = [t for t in targets if t not in MAKE_TARGETS]
    if la:
        raise ValueError(f"target {la} không thuộc {list(MAKE_TARGETS)} — patcher chỉ có ba thao tác")
    for t in targets:
        if (dest := TARGET_WRITES_HUMAN_ONLY.get(t)) is not None:
            raise NeedsHumanDecision(
                f"make {t}: ghi vào {dest} — vùng bắt buộc bảy bước CONTRIBUTING.md §3, trong đó "
                f"`make eval-record` cần model thật. Từ chối TRƯỚC khi chạy: chạy rồi mới từ chối thì file đã "
                f"ghi ra, và patcher không được xoá (I5). Mở ticket risk_tier=high để người quyết")
    run = runner or default_runner
    for t in targets:
        code, out = run(["make", t], root)
        if code != 0:
            raise RuntimeError(f"make {t} thất bại (exit {code}): {out[-500:]}")
    files = (changed_files or _changed_files)(root)
    for rel in files:
        check_path(root, rel)
    return PatchProposal(ticket_id=ticket_id, branch=f"{BRANCH_PREFIX}{slug(ticket_id)}",
                         operation="regen_derived", summary=f"make {' '.join(targets)}", files=files)
