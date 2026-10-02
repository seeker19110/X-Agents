"""`drift-detector` (BT3, `DAC-TA-KEEPER.md` §5): ba phép so THUẦN CỤC BỘ, không gọi mạng. Chỉ phát `Signal`
(kind="drift"), không xoá gì (bất biến I5).

**Đo trước khi viết (a)**: đặc tả gốc nói "so hash nguồn ghi trong front matter" của `.claude/agents/sc-*.md`.
Mở `software-company/src/company/subagents.py:131` (`render()`) và một file thật (`.claude/agents/sc-builder.md`)
cho thấy điều đó SAI theo hai cách:

1. Dấu vết nguồn không phải hash — nó là số **`version`** (nguyên, từ `AgentSpec.version`,
   `xagents-core/src/xagents_core/registry.py:61`, mặc định 1, tăng thủ công mỗi khi nội dung prompt đổi —
   ADR-0004).
2. Nó không nằm trong **front matter** (khối `---...---` đầu file) — nó là một dòng **HTML comment ngay sau**
   front matter: `<!-- SINH TỰ ĐỘNG từ agents/engineering/builder.md version=1 — sửa nguồn rồi chạy make
   subagents -->` (`subagents.py:131`).

Cơ chế thật: so `version=<n>` ghi trong comment đó với trường `version:` ở front matter của file nguồn
(`agents/<block>/<id>.md`). File nguồn KHÔNG khai `version:` thì coi là `1` (khớp default của `AgentSpec`).
`tests/golden/agents/<id>.md` mang đúng khuôn dấu vết tương tự: `<!-- golden agent=<id> version=<n> -->`
(so cùng cơ chế cho phép (b)).
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .events import Signal

_SC_SRC_RE = re.compile(r"<!--\s*SINH TỰ ĐỘNG từ (?P<src>\S+) version=(?P<ver>\d+)")
_GOLDEN_RE = re.compile(r"<!--\s*golden agent=(?P<id>\S+) version=(?P<ver>\d+)\s*-->")
_FRONT_MATTER_VERSION_RE = re.compile(r"(?m)^version:\s*(?P<ver>\d+)\s*$")
_PR_REF_RE = re.compile(r"\(#(?P<n>\d+)\)")
# Phép (d): chỗ đáng lẽ là số PR nhưng còn là chỗ trống. Đo từ dữ liệu thật chứ không đoán khuôn: bốn ca thiếu
# dòng CHANGELOG tìm ra ngày 2026-09-09 thì BA là "quên điền số" chứ không phải "quên viết dòng" — #208 để
# nguyên `(#PENDING)`, #161 và #192 viết đủ mô tả mà không có `(#n)` nào. Phép (c) mù với cả ba khi dòng đã
# tồn tại, nên nó chỉ bắt được chúng khi PR đã merge; phép này bắt NGAY, trước merge.
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_PLACEHOLDER_RE = re.compile(r"\(#(?:PRNUM|PENDING|TBD|n|N|<n>|\?+)\)")

# Mốc chặn dưới cho phép (c) — đo được TỪ ĐÂU, không đoán: `AGENTS.md` bắt buộc §10 ("Tài liệu đi CÙNG PR,
# không đi sau nó" — dòng CHANGELOG/nhật ký phiên phải nằm trong CHÍNH PR làm ra thay đổi) chỉ có hiệu lực từ
# commit thêm nó vào `AGENTS.md`. Đo bằng `git log -p --follow -- AGENTS.md | grep -n "Tài liệu đi CÙNG PR"`
# rồi `git show <commit> -s --format=%aI`: commit `a82a804ef70ca2526909accdf88435ae1ba64b07`,
# 2026-09-07T19:41:01+07:00. PR merge TRƯỚC mốc này không thể vi phạm một luật chưa tồn tại — không lọc bằng
# danh sách số PR (danh sách mục ngay tuần sau, `DAC-TA-KEEPER.md` §5 cạm bẫy).
CHANGELOG_RULE_CUTOFF = datetime(2026, 9, 7, 19, 41, 1, tzinfo=timezone(timedelta(hours=7)))


def _source_version(source_md: Path) -> int | None:
    """`version:` ở front matter của file nguồn agent; `None` khi KHÔNG có file nguồn.

    Trước đây thiếu file thì trả `1` (bắt chước `AgentSpec.version` default). Đó là fail-open: bản dẫn xuất trỏ
    sai đường dẫn hiện ra dưới dạng "nguồn hiện version=1" — người đọc đi tìm một lần tăng version không hề có,
    thay vì thấy ngay là đường dẫn trỏ vào chỗ trống. Phân biệt hai ca, vì cách xử lý của chúng khác hẳn nhau."""
    if not source_md.exists():
        return None
    text = source_md.read_text(encoding="utf-8")
    front = text.split("---", 2)
    body = front[1] if len(front) >= 3 and text.startswith("---") else text
    m = _FRONT_MATTER_VERSION_RE.search(body)
    return int(m.group("ver")) if m else 1


def sc_agent_drift(claude_agents_dir: Path, company_root: Path) -> list[Signal]:
    """Phép (a): mỗi `.claude/agents/sc-<id>.md` (không tính `sc-gate-*`) so `version=` ghi trong comment dẫn
    xuất với `version:` hiện tại của file nguồn `agents/<block>/<id>.md`."""
    out: list[Signal] = []
    for sc_path in sorted(claude_agents_dir.glob("sc-*.md")):
        if sc_path.stem.startswith("sc-gate-"):
            continue
        text = sc_path.read_text(encoding="utf-8")
        m = _SC_SRC_RE.search(text)
        if not m:
            continue
        src_rel, recorded = m.group("src"), int(m.group("ver"))
        actual = _source_version(company_root / src_rel)
        if actual is None:
            out.append(Signal(
                subject=str(sc_path.name), kind="drift",
                detail=f"{sc_path.name} trỏ nguồn {src_rel} nhưng KHÔNG có file đó — bản dẫn xuất ghi sai đường "
                       f"dẫn, chạy make subagents để sinh lại",
                evidence=src_rel,
            ))
        elif actual != recorded:
            out.append(Signal(
                subject=str(sc_path.name), kind="drift",
                detail=f"{sc_path.name} ghi version={recorded} của {src_rel} nhưng nguồn hiện version={actual}",
                evidence=src_rel,
            ))
    return out


def golden_drift(golden_agents_dir: Path, company_root: Path) -> list[Signal]:
    """Phép (b): mỗi `tests/golden/agents/<id>.md` so `version=` ghi trong comment với `version:` hiện tại của
    `agents/**/<id>.md` (dò mọi block, vì golden không ghi block)."""
    out: list[Signal] = []
    for golden_path in sorted(golden_agents_dir.glob("*.md")):
        text = golden_path.read_text(encoding="utf-8")
        m = _GOLDEN_RE.search(text)
        if not m:
            continue
        agent_id, recorded = m.group("id"), int(m.group("ver"))
        matches = list((company_root / "agents").rglob(f"{agent_id}.md"))
        actual = _source_version(matches[0]) if matches else None
        if actual != recorded:
            shown = "không có file nguồn" if actual is None else f"version={actual}"
            out.append(Signal(
                subject=golden_path.name, kind="drift",
                detail=f"golden {golden_path.name} ghi version={recorded} nhưng nguồn agent={agent_id} "
                       f"hiện {shown}",
                evidence=str(matches[0].relative_to(company_root)) if matches else "nguồn không tìm thấy",
            ))
    return out


def _git_log_pr_commits(repo: Path) -> list[tuple[int, datetime]]:
    """`(số PR, ngày merge)` cho mỗi commit trong `git log` của `repo` có `(#n)` ở tiêu đề — khuôn message của
    squash-merge GitHub. Lệnh `git log` cục bộ (đọc `.git` trên đĩa), không mạng."""
    r = subprocess.run(
        ["git", "log", "--format=%s%x1f%aI"], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", check=False,
    )
    if r.returncode != 0:
        return []
    out: list[tuple[int, datetime]] = []
    for line in r.stdout.splitlines():
        if "\x1f" not in line:
            continue
        subject, date_raw = line.split("\x1f", 1)
        m = _PR_REF_RE.search(subject)
        if not m:
            continue
        try:
            when = datetime.fromisoformat(date_raw)
        except ValueError:
            continue
        out.append((int(m.group("n")), when))
    return out


def history_gap(repo: Path) -> str | None:
    """Vì sao phép (c) KHÔNG soi được lịch sử của `repo`, hoặc `None` khi soi được.

    Phép (c) gặp `git log` lỗi thì trả rỗng — đúng cho một hàm phát tín hiệu, nhưng người gọi in "sạch" thì đó
    là cổng xanh giả. Hai ca đo được: không phải repo git (`--repo` trỏ sai chỗ), và clone nông (`--depth 1` chỉ
    còn một commit nên không PR nào bị soi). Lịch sử trống thì không có gì để soi, không phải lỗ."""
    r = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", check=False,
    )
    if r.returncode != 0:
        return f"{repo} không phải repo git — {(r.stderr or r.stdout).strip()[:200]}"
    if r.stdout.strip() == "true":
        return f"{repo} là clone nông — `git log` thiếu lịch sử, PR đã merge không được soi (cần fetch-depth: 0)"
    return None


def changelog_drift(repo: Path, changelog: Path, *, cutoff: datetime = CHANGELOG_RULE_CUTOFF) -> list[Signal]:
    """Phép (c): mỗi PR merged trong `git log` của `repo` SAU `cutoff` mà `(#n)` không xuất hiện trong
    `changelog` → một `Signal`. PR merge trước `cutoff` không bị soi (luật §10 chưa có hiệu lực khi đó)."""
    changelog_text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    out: list[Signal] = []
    for pr_number, when in _git_log_pr_commits(repo):
        if when <= cutoff:
            continue
        marker = f"(#{pr_number})"
        if marker not in changelog_text:
            out.append(Signal(
                subject=f"pr-{pr_number}", kind="drift",
                detail=f"PR #{pr_number} merged {when.isoformat()} (sau mốc luật §10) nhưng thiếu "
                       f"dòng CHANGELOG",
                evidence=marker,
            ))
    return out


def changelog_placeholder_drift(changelog: Path) -> list[Signal]:
    """Phép (d): dòng CHANGELOG còn chỗ trống thay cho số PR (`(#PRNUM)`, `(#PENDING)`, `(#n)`...).

    Thuần đọc file, không cần `git log` — nên KHÔNG phụ thuộc độ sâu clone, khác phép (c). Đó là điểm mạnh
    riêng của nó: phép (c) trên một clone `--depth 1` sẽ im lặng, phép này thì không."""
    if not changelog.exists():
        return []
    out: list[Signal] = []
    for i, line in enumerate(changelog.read_text(encoding="utf-8").splitlines(), start=1):
        # Bỏ đoạn trong backtick TRƯỚC khi dò: chính CHANGELOG này kể lại các ca placeholder bằng văn xuôi
        # (`đổi (#208) về (#PENDING)`, `điền (#<n>) rồi commit`), và một bộ dò báo động vì tài liệu MÔ TẢ nó
        # là bộ dò người ta sẽ tắt. Chỗ trống thật không bao giờ nằm trong code span.
        if m := _PLACEHOLDER_RE.search(_INLINE_CODE_RE.sub(" ", line)):
            out.append(Signal(
                subject=f"changelog-L{i}", kind="drift",
                detail=f"CHANGELOG.md dòng {i} còn chỗ trống {m.group(0)} thay cho số PR — điền `(#<n>)` rồi "
                       f"commit tiếp vào CHÍNH PR đó (AGENTS.md luật bắt buộc §10)",
                evidence=m.group(0),
            ))
    return out


def scan(*, claude_agents_dir: Path, golden_agents_dir: Path, company_root: Path, repo: Path,
          changelog: Path) -> list[Signal]:
    return (
        sc_agent_drift(claude_agents_dir, company_root)
        + golden_drift(golden_agents_dir, company_root)
        + changelog_drift(repo, changelog)
        + changelog_placeholder_drift(changelog)
    )
