"""Quét tài sản prompt của chính repo như một mắt xích chuỗi cung ứng (ADR-0022).

`guard.py` bảo vệ **dữ liệu chạy qua** hệ thống. Nó không nhìn thứ nguy hiểm hơn: **chính các file prompt trong
repo** — `agents/*.md`, `skills/*.md`, `templates/`, `gates/`, `topics/`. Những file này đi thẳng vào system prompt
của mọi agent, không qua `guard_payload` lần nào, và chúng đến từ PR của người lạ, từ merge, từ copy-paste. Một dòng
"bỏ qua hướng dẫn trước" giấu trong một skill là injection **vĩnh viễn**, cho mọi agent nạp skill đó, ở mọi ticket.

Bốn lỗi nặng (`high`, làm CI đỏ):
- `injection`: mẫu điều khiển mô hình (dùng chung `guard.PATTERNS` — một nguồn sự thật duy nhất cho cả hai lớp).
- `hidden-char`: ký tự vô hình / đảo chiều (zero-width, bidi override). Trong văn xuôi tiếng Việt hay tiếng Anh
  chúng không có việc gì để làm; có mặt nghĩa là ai đó giấu chữ mà người review không thấy trong diff.
- `dangerous-command`: prompt bảo agent tải rồi chạy (`curl … | sh`), `rm -rf /`, `chmod 777`, `eval $(…)`,
  hay POST biến môi trường đi đâu đó.
- `secret-literal`: khóa thật lọt vào ví dụ (`sk-ant-…`, `ghp_…`, `AKIA…`). gitleaks quét lịch sử git; đây quét
  đúng những file sẽ được đọc lên làm prompt, và chạy được trước khi commit.

Một cảnh báo (`warn`, không làm CI đỏ): `remote-fetch` — prompt trỏ agent ra URL ngoài. Không sai tự thân (skill có
thể dẫn nguồn tiêu chuẩn), nhưng đó là chỗ nội dung ngoài chảy vào ngữ cảnh nên đáng được nhìn bằng mắt.

Miễn trừ: `assetscan-waivers.txt` ở gốc cây quét, mỗi dòng `đường/dẫn::rule::lý do` (lý do bắt buộc — miễn trừ
không có lý do là miễn trừ không ai dám xoá). Waiver không còn khớp gì sẽ bị báo `waiver-unused` để dọn.

Công cụ nằm trong package `company` vì nó dùng lại `guard.PATTERNS`; nhưng nó chỉ đọc file, không biết gì về
`registry`, nên chạy được cho bất kỳ cây nào có cùng bố cục — CI chạy nó cho cả `Studio-creators`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from . import guard

ASSET_DIRS = ("agents", "skills", "templates", "gates", "topics")
ASSET_SUFFIXES = frozenset({".md", ".json", ".yaml", ".yml", ".txt"})
WAIVERS_FILE = "assetscan-waivers.txt"

# Ký tự không nên có trong văn bản prompt: zero-width, joiner, bidi override, BOM, word-joiner.
_HIDDEN = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿]")

DANGEROUS: tuple[tuple[str, str], ...] = (
    ("pipe-to-shell", r"\b(curl|wget)\b[^\n|]{0,120}\|\s*(sudo\s+)?(ba|z|d)?sh\b"),
    ("rm-rf-root", r"\brm\s+-[a-z]*[rR][a-z]*f?\s+(/|~|\$HOME|/\*)(\s|$)"),
    ("chmod-777", r"\bchmod\s+(-R\s+)?777\b"),
    ("eval-subshell", r"\beval\s+[\"']?\$\("),
    ("base64-to-shell", r"\bbase64\s+(-d|--decode)\b[^\n]{0,60}\|\s*(ba|z)?sh\b"),
    ("env-exfil", r"\bcurl\b[^\n]{0,120}(-d|--data[a-z-]*)\s*[\"']?[^\n]{0,40}\$\{?(ANTHROPIC|OPENAI|AWS|GITHUB|GOOGLE|COMPANY|STUDIO)[A-Z_]*"),
    ("git-force-main", r"\bgit\s+push\b[^\n]{0,60}--force[^\n]{0,40}\b(main|master)\b"),
)

SECRETS: tuple[tuple[str, str], ...] = (
    ("anthropic-key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openai-key", r"\bsk-(proj-)?[A-Za-z0-9]{32,}"),
    ("github-token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("aws-key-id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("google-key", r"\bAIza[0-9A-Za-z_\-]{30,}"),
    ("private-key", r"-----BEGIN\s+(RSA|EC|OPENSSH|PGP|DSA)?\s*PRIVATE KEY-----"),
)

# URL được phép xuất hiện trong prompt (tiêu chuẩn, tài liệu chính thức). Ngoài danh sách này thì cảnh báo.
URL_ALLOW = ("rfc-editor.org", "ietf.org", "w3.org", "iso.org", "owasp.org", "cwe.mitre.org", "nist.gov",
             "python.org", "semver.org", "keepachangelog.com", "conventionalcommits.org", "opentelemetry.io",
             "json-schema.org", "spec.openapis.org", "asyncapi.com", "schema.org", "unicode.org", "example.com",
             "localhost", "127.0.0.1")
_URL = re.compile(r"https?://([A-Za-z0-9.\-]+)")
# Host thật: các nhãn ngăn bằng dấu chấm + TLD chữ, hoặc localhost/IPv4. Loại `https://...` trong ví dụ văn xuôi.
_REAL_HOST = re.compile(r"^(localhost|(\d{1,3}\.){3}\d{1,3}|[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)*\.[a-z]{2,})$")

_COMPILED_DANGEROUS = [(n, re.compile(rx, re.IGNORECASE)) for n, rx in DANGEROUS]
_COMPILED_SECRETS = [(n, re.compile(rx)) for n, rx in SECRETS]

SEVERITY = {"injection": "high", "hidden-char": "high", "dangerous-command": "high", "secret-literal": "high",
            "remote-fetch": "warn", "waiver-unused": "warn"}


@dataclass(frozen=True)
class Finding:
    path: str      # đường dẫn tương đối gốc cây quét
    rule: str      # tên rule (khớp SEVERITY)
    detail: str    # mẫu con đã khớp, đã rút gọn
    line: int      # dòng 1-based, 0 khi không gắn với dòng nào

    @property
    def severity(self) -> str: return SEVERITY.get(self.rule, "high")


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _describe_hidden(ch: str) -> str:
    try: name = unicodedata.name(ch)
    except ValueError: name = "?"
    return f"U+{ord(ch):04X} {name}"


def scan_text(text: str, path: str) -> list[Finding]:
    """Bốn rule nặng + cảnh báo URL, trên nội dung một file tài sản."""
    out: list[Finding] = []
    norm = guard.normalize(text)  # né mẫu bằng ký tự vô hình là cách rẻ nhất; dò trên bản đã chuẩn hoá
    for name, rx in guard._COMPILED:
        for m in rx.finditer(norm):
            out.append(Finding(path, "injection", f"{name}: {m.group(0)[:80]!r}", _line_of(norm, m.start())))
    for m in _HIDDEN.finditer(text):
        out.append(Finding(path, "hidden-char", _describe_hidden(m.group(0)), _line_of(text, m.start())))
    for name, rx in _COMPILED_DANGEROUS:
        for m in rx.finditer(norm):
            out.append(Finding(path, "dangerous-command", f"{name}: {m.group(0)[:80]!r}", _line_of(norm, m.start())))
    for name, rx in _COMPILED_SECRETS:
        for m in rx.finditer(norm):
            out.append(Finding(path, "secret-literal", f"{name}: {m.group(0)[:12]!r}…", _line_of(norm, m.start())))
    for m in _URL.finditer(norm):
        host = m.group(1).lower()
        if _REAL_HOST.match(host) and not any(host == a or host.endswith("." + a) for a in URL_ALLOW):
            out.append(Finding(path, "remote-fetch", host, _line_of(norm, m.start())))
    return out


def asset_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for d in ASSET_DIRS:
        base = root / d
        if not base.is_dir(): continue
        files.extend(p for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in ASSET_SUFFIXES)
    return files


@dataclass(frozen=True)
class Waiver:
    path: str
    rule: str
    reason: str


def load_waivers(root: Path) -> tuple[list[Waiver], list[str]]:
    """Đọc `assetscan-waivers.txt`. Trả về (waiver hợp lệ, lỗi cú pháp)."""
    f = root / WAIVERS_FILE
    if not f.is_file(): return [], []
    waivers, errors = [], []
    for n, raw in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        parts = [p.strip() for p in line.split("::")]
        if len(parts) != 3 or not all(parts):
            errors.append(f"{WAIVERS_FILE}:{n}: cần `đường/dẫn::rule::lý do`, cả ba phần không rỗng — {raw!r}")
            continue
        if parts[1] not in SEVERITY:
            errors.append(f"{WAIVERS_FILE}:{n}: rule không có thật: {parts[1]!r}")
            continue
        waivers.append(Waiver(*parts))
    return waivers, errors


def apply_waivers(findings: list[Finding], waivers: list[Waiver]) -> tuple[list[Finding], list[Waiver]]:
    """Trả về (finding còn lại, waiver không khớp gì)."""
    kept, used = [], set()
    for f in findings:
        hit = next((w for w in waivers if w.path == f.path and w.rule == f.rule), None)
        if hit is None: kept.append(f)
        else: used.add(hit)
    return kept, [w for w in waivers if w not in used]


def scan_root(root: Path) -> tuple[list[Finding], list[str]]:
    """Quét một cây tài sản, đã áp miễn trừ. Trả về (finding, lỗi cú pháp waiver)."""
    raw: list[Finding] = []
    for p in asset_files(root):
        rel = p.relative_to(root).as_posix()
        try: text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Tài sản prompt phải là UTF-8; file không giải mã được thì không ai review được nội dung thật của nó.
            raw.append(Finding(rel, "hidden-char", "file không phải UTF-8", 0)); continue
        raw.extend(scan_text(text, rel))
    waivers, errors = load_waivers(root)
    kept, unused = apply_waivers(raw, waivers)
    kept.extend(Finding(w.path, "waiver-unused", f"waiver cho rule {w.rule!r} không còn khớp gì", 0) for w in unused)
    return kept, errors


# ---------- budget: prompt tĩnh đã ăn bao nhiêu phần ngân sách token ----------

_FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
CHARS_PER_TOKEN = 4  # ước lượng thô, đủ để so sánh tương đối giữa các agent (không phải hoá đơn)


@dataclass(frozen=True)
class Weight:
    agent: str
    static_chars: int
    static_tokens: int
    budget_tokens: int
    share: float             # phần ngân sách đã bị prompt tĩnh chiếm, trước khi có bất kỳ dữ liệu nào
    missing_skills: list[str]


def agent_weights(root: Path) -> list[Weight]:
    """Prompt tĩnh (thân agent + toàn văn skill) so với `budget_tokens_per_task` của chính agent đó.

    Ý tưởng lấy từ `context-budget` của ECC, nhưng đo thứ repo này có mà harness không có: ngân sách khai trong
    front matter. Agent nào để prompt tĩnh ăn quá nửa ngân sách thì phần còn lại cho dữ liệu thật quá mỏng.
    """
    out: list[Weight] = []
    if not (root / "agents").is_dir(): return out
    for p in sorted((root / "agents").rglob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = _FM.match(text)
        if not m: continue
        fm = yaml.safe_load(m.group(1)) or {}
        chars, missing = len(text) - m.end(), []
        for name in [*(fm.get("skills") or []), *(fm.get("skills_core") or [])]:
            sp = root / "skills" / f"{name}.md"
            if sp.is_file(): chars += len(sp.read_text(encoding="utf-8"))
            else: missing.append(str(name))
        budget = int(fm.get("budget_tokens_per_task") or 0)
        tokens = chars // CHARS_PER_TOKEN
        out.append(Weight(str(fm.get("id") or p.stem), chars, tokens, budget,
                          round(tokens / budget, 3) if budget else 0.0, missing))
    return sorted(out, key=lambda w: w.share, reverse=True)


def _print_findings(findings: list[Finding], root: Path) -> None:
    for f in sorted(findings, key=lambda f: (f.severity != "high", f.path, f.line)):
        where = f"{f.path}:{f.line}" if f.line else f.path
        print(f"{f.severity:<4} {f.rule:<18} {where} — {f.detail}")
    highs = sum(1 for f in findings if f.severity == "high")
    print(f"{root}: {len(asset_files(root))} file, {highs} lỗi nặng, {len(findings) - highs} cảnh báo")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m company.assetscan",
                                 description="Quét tài sản prompt của repo (injection, ký tự ẩn, lệnh nguy hiểm, khóa lộ)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="quét tài sản prompt")
    sc.add_argument("roots", nargs="*", type=Path, help="gốc cây quét (mặc định: gốc repo của package)")
    sc.add_argument("--json", action="store_true")
    sc.add_argument("--strict", action="store_true", help="cảnh báo cũng làm đỏ")
    bg = sub.add_parser("budget", help="prompt tĩnh chiếm bao nhiêu phần ngân sách token của agent")
    bg.add_argument("roots", nargs="*", type=Path)
    bg.add_argument("--json", action="store_true")
    bg.add_argument("--max-share", type=float, default=0.5, help="ngưỡng đỏ cho tỉ lệ prompt tĩnh / ngân sách")
    ns = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")  # Windows console cp1252

    roots: list[Path] = list(ns.roots) or [Path(__file__).resolve().parents[2]]
    for r in roots:
        if not r.is_dir():
            print(f"không phải thư mục: {r}", file=sys.stderr); return 2

    if ns.cmd == "budget":
        report: dict[str, Any] = {}
        bad = False
        for root in roots:
            ws = agent_weights(root)
            report[str(root)] = [asdict(w) for w in ws]
            if not ns.json:
                print(f"# {root}")
                for w in ws:
                    flag = ""
                    if w.missing_skills: flag = f"  THIẾU SKILL: {', '.join(w.missing_skills)}"
                    elif w.share > ns.max_share: flag = "  VƯỢT NGƯỠNG"
                    print(f"{w.agent:<22} {w.static_tokens:>7} tok tĩnh / {w.budget_tokens:>7} ngân sách"
                          f"  = {w.share:>5.0%}{flag}")
                print()
            bad = bad or any(w.missing_skills or w.share > ns.max_share for w in ws)
        if ns.json: print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if bad else 0

    all_findings: list[Finding] = []
    errors: list[str] = []
    for root in roots:
        found, waiver_errors = scan_root(root)
        all_findings.extend(found); errors.extend(f"{root}: {x}" for x in waiver_errors)
        if not ns.json:
            print(f"# {root}"); _print_findings(found, root); print()
    if ns.json:
        print(json.dumps({"findings": [asdict(f) | {"severity": f.severity} for f in all_findings],
                          "waiver_errors": errors}, ensure_ascii=False, indent=2))
    for msg in errors: print(msg, file=sys.stderr)
    if errors: return 2
    if any(f.severity == "high" for f in all_findings): return 1
    return 1 if (ns.strict and all_findings) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
