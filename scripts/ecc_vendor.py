"""Vendor ECC chọn lọc vào `.claude/` — tiền tố `ecc-`, ghim commit, sha256 từng tệp (ADR-0028).

Nguồn duy nhất là `docs/integrations/ecc.lock.json`: `revision` ghim, `select` (mục được chép, kèm lý do),
`rejected` (mục đã cân rồi loại). Script sinh các tệp dưới đây rồi ghi lại `files` + `measured` vào lock:

    skills/<x>/**.md   → .claude/skills/ecc-<x>/**.md
    commands/<x>.md    → .claude/commands/ecc-<x>.md
    agents/<x>.md      → .claude/agents/ecc-<x>.md
    LICENSE            → docs/integrations/ecc.LICENSE

Biến đổi tất định, tối thiểu: `name:` trong frontmatter thêm tiền tố; tham chiếu TƯỜNG MINH tới mục đã vendor
(`/x`, `` `x` ``, `**x**`, `skill: x`, `agents|skills|commands/x`, tên agent có gạch nối) đổi sang `ecc-x`; một ghi
chú nguồn sau frontmatter. Nguồn có dấu hiệu "chỉ chạy được khi là plugin" thì dừng, không vá.

    python scripts/ecc_vendor.py build [--src <clone ECC>]   # make ecc-vendor
    python scripts/ecc_vendor.py check [--src <clone ECC>]   # make ecc-check; exit 1 nếu lệch
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_REL = "docs/integrations/ecc.lock.json"
LICENSE_REL = "docs/integrations/ecc.LICENSE"
PREFIX = "ecc-"
KINDS = ("skills", "commands", "agents")

# Dấu hiệu nội dung chỉ đúng khi ECC chạy như plugin cài vào máy (mỗi mẫu một lý do, ADR-0028 §3).
COUPLING = {
    r"CLAUDE_PLUGIN_ROOT": "đường dẫn gốc plugin",
    r"~/\.claude": "ghi vào thư mục cá nhân của Claude Code",
    r"(?<![\w~])\.claude/": "ghi vào cây .claude của repo",
    r"\bnode\s+scripts/": "gọi script node của ECC (không vendor)",
    r"\bnpx\s+(?:-y|--yes)\b": "tải và chạy gói npm không hỏi",
    r"\becc:[a-z]": "gọi mục ECC theo namespace plugin",
}

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


class VendorError(Exception):
    """Nguồn hoặc lock không đạt — dừng build, không vá tự động."""


def load_lock(root: Path) -> dict:
    return json.loads((root / LOCK_REL).read_text(encoding="utf-8"))


def read(p: Path) -> str:
    """`read_text` dịch CRLF → LF (universal newlines): checkout `autocrlf` của Windows không tính là trôi."""
    return p.read_text(encoding="utf-8")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_head(src: Path) -> str:
    kq = subprocess.run(
        ["git", "-C", str(src), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return kq.stdout.strip()


def _items(lock: dict) -> dict[str, str]:
    """Tên mục đã chọn → loại. Hai loại trùng tên thì cùng thành `/ecc-<tên>`: một cái che cái kia."""
    items: dict[str, str] = {}
    for kind in KINDS:
        for name in lock["select"].get(kind, {}):
            if name in items:
                raise VendorError(f"`{name}` được chọn ở cả {items[name]} và {kind}")
            items[name] = kind
    both = sorted(n for n in items if any(fnmatch.fnmatchcase(n, r) for r in lock.get("rejected", {})))
    if both:
        raise VendorError(f"vừa chọn vừa loại: {', '.join(both)}")
    return items


def _sources(src: Path, kind: str, name: str) -> list[Path]:
    if kind == "skills":
        base = src / "skills" / name
        if not (base / "SKILL.md").is_file():
            raise VendorError(f"không có skills/{name}/SKILL.md ở nguồn")
        files = sorted(p for p in base.rglob("*") if p.is_symlink() or p.is_file())
    else:
        p = src / kind / f"{name}.md"
        if not p.is_file():
            raise VendorError(f"không có {kind}/{name}.md ở nguồn")
        files = [p]
    for p in files:
        rel = p.relative_to(src).as_posix()
        if p.is_symlink():
            raise VendorError(f"{rel}: symlink — vendor chỉ nhận tệp thường")
        if p.suffix != ".md":
            raise VendorError(f"{rel}: không phải .md — skill có mã chạy kèm thì loại, không vendor nửa vời")
    return files


def _coupling(rel: str, text: str) -> None:
    for pattern, why in COUPLING.items():
        m = re.search(pattern, text)
        if m:
            line = text.count("\n", 0, m.start()) + 1
            raise VendorError(f"{rel}:{line}: `{m.group(0)}` — {why}; chuyển mục sang `rejected`")


def _frontmatter(rel: str, text: str) -> tuple[re.Match[str], dict]:
    m = _FRONTMATTER.match(text)
    meta = yaml.safe_load(m.group(1)) if m else None
    if m is None or not isinstance(meta, dict):
        raise VendorError(f"{rel}: thiếu frontmatter YAML dạng ánh xạ")
    return m, meta


def _rename(rel: str, text: str, kind: str, name: str) -> str:
    """Đổi `name:` trong frontmatter. Tệp chính phải có frontmatter, tên trùng tệp và mô tả."""
    m, meta = _frontmatter(rel, text)
    if kind != "commands" and meta.get("name") != name:
        raise VendorError(f"{rel}: `name` phải là `{name}`, đang là {meta.get('name')!r}")
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        raise VendorError(f"{rel}: thiếu `description` — không có thì mục không hiện trong danh sách")
    if "name" not in meta:
        return text
    head = re.sub(
        rf"^name:[ \t]*{re.escape(name)}[ \t]*$", f"name: {PREFIX}{name}", m.group(1), count=1, flags=re.MULTILINE
    )
    if yaml.safe_load(head).get("name") != PREFIX + name:
        raise VendorError(f"{rel}: không đổi được `name` (chỉ nhận dạng `name: {name}` trơn)")
    return f"---\n{head}\n---\n{text[m.end() :]}"


def _is_main(rel: str) -> bool:
    """Tệp mang frontmatter mà Claude Code liệt kê: SKILL.md, lệnh, agent — không tính tệp phụ của skill."""
    return rel.endswith("/SKILL.md") if rel.startswith(".claude/skills/") else rel != LICENSE_REL


def _description_chars(out: dict[str, tuple[str, str]]) -> int:
    return sum(len(_frontmatter(rel, text)[1]["description"]) for rel, (_, text) in out.items() if _is_main(rel))


def _ref_pattern(items: dict[str, str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(n) for n in sorted(items, key=len, reverse=True))
    return re.compile(rf"(?<![\w./-])(?P<pre>/|(?:{'|'.join(KINDS)})/)?(?P<name>{alt})(?![\w-])")


def rewrite_refs(text: str, items: dict[str, str]) -> str:
    """Chỉ đổi dạng tường minh: tên skill viết trơn có thể là từ thường ("error-handling patterns")."""
    pattern = _ref_pattern(items)

    def sub(m: re.Match[str]) -> str:
        pre, name = m.group("pre"), m.group("name")
        kind, new = items[name], PREFIX + name
        if pre == "/":
            return f"/{new}" if kind != "agents" else m.group(0)
        if pre:
            return f".claude/{kind}/{new}" if pre == f"{kind}/" else m.group(0)
        s, e = m.start(), m.end()
        explicit = (
            text[s - 1 : s] == "`" == text[e : e + 1]
            or text[s - 2 : s] == "**" == text[e : e + 2]
            or re.search(r"skill:[ \t]*$", text[max(0, s - 16) : s], re.IGNORECASE) is not None
            or (kind == "agents" and "-" in name)
        )
        return new if explicit else m.group(0)

    return pattern.sub(sub, text)


def _note(lock: dict, source: str) -> str:
    return (
        f"<!-- Sinh bởi scripts/ecc_vendor.py từ {lock['repository']}@{lock['revision']} ({source}) — không sửa tay; "
        f"đổi thì sửa {LOCK_REL} rồi chạy lại (ADR-0028). -->\n"
        "> **ECC (MIT), vendor vào X-Agents.** Luật ở `AGENTS.md` thắng khi trùng: coverage `fail_under = 100` "
        "(không phải 80%), test đỏ trước khi code, nhánh → PR theo `docs/QUY-TRINH-GIT.md`, không xoá code ngoài "
        "yêu cầu. Mục ECC được nhắc tới mà không có tệp `ecc-<tên>` trong `.claude/` thì repo không vendor — dùng "
        "`/gate`, `/debug`, `/adr`, `/thi-hanh` hoặc bỏ qua.\n\n"
    )


def _with_note(text: str, note: str) -> str:
    m = _FRONTMATTER.match(text)
    cut = m.end() if m else 0
    return text[:cut] + ("\n" if m else "") + note + text[cut:].lstrip("\n")


def _target(kind: str, name: str, rel_in_item: str) -> str:
    if kind == "skills":
        return f".claude/skills/{PREFIX}{name}/{rel_in_item}"
    return f".claude/{kind}/{PREFIX}{name}.md"


def render(src: Path, lock: dict) -> dict[str, tuple[str, str]]:
    """Đường dẫn trong repo → (đường dẫn nguồn, toàn văn). Không ghi gì."""
    head = _git_head(src)
    if head != lock["revision"]:
        raise VendorError(f"nguồn đang ở {head or '?'}, lock ghim revision {lock['revision']}")
    items = _items(lock)
    out: dict[str, tuple[str, str]] = {}
    for name, kind in items.items():
        for p in _sources(src, kind, name):
            rel = p.relative_to(src).as_posix()
            text = read(p)
            _coupling(rel, text)
            inner = p.relative_to(src / "skills" / name).as_posix() if kind == "skills" else ""
            if kind != "skills" or inner == "SKILL.md":
                text = _rename(rel, text, kind, name)
            out[_target(kind, name, inner)] = (rel, _with_note(rewrite_refs(text, items), _note(lock, rel)))
    lic = src / "LICENSE"
    if not lic.is_file():
        raise VendorError("nguồn thiếu LICENSE — không vendor mã không rõ giấy phép")
    out[LICENSE_REL] = ("LICENSE", read(lic))
    total = _description_chars(out)
    if total > lock["budget_description_chars"]:
        raise VendorError(f"mô tả cộng lại {total} ký tự > budget_description_chars {lock['budget_description_chars']}")
    return dict(sorted(out.items()))


def _measured(src: Path, out: dict[str, tuple[str, str]], lock: dict) -> dict:
    items = _items(lock)
    return {
        **{kind: sum(1 for k in items.values() if k == kind) for kind in KINDS},
        "files": len(out),
        "bytes": sum(len(text.encode("utf-8")) for _, text in out.values()),
        "description_chars": _description_chars(out),
        "upstream": {
            "skills": sum(1 for p in (src / "skills").glob("*/SKILL.md")),
            "commands": sum(1 for _ in (src / "commands").glob("*.md")),
            "agents": sum(1 for _ in (src / "agents").glob("*.md")),
        },
    }


def _new_lock(src: Path, lock: dict, out: dict[str, tuple[str, str]]) -> dict:
    files = [{"path": rel, "source": source, "sha256": sha256(text)} for rel, (source, text) in out.items()]
    return {**lock, "files": files, "measured": _measured(src, out, lock)}


def _dump(lock: dict) -> str:
    return json.dumps(lock, indent=2, ensure_ascii=False) + "\n"


def _on_disk(root: Path) -> list[str]:
    claude = root / ".claude"
    found = [p for p in (claude / "skills").glob(f"{PREFIX}*/**/*") if p.is_file()]
    found += [p for kind in ("commands", "agents") for p in (claude / kind).glob(f"{PREFIX}*.md")]
    found += [p for p in [root / LICENSE_REL] if p.is_file()]
    return sorted(p.relative_to(root).as_posix() for p in found)


def build(root: Path, src: Path) -> dict:
    lock = load_lock(root)
    out = render(src, lock)
    for d in (root / ".claude" / "skills").glob(f"{PREFIX}*"):
        shutil.rmtree(d)
    for rel in _on_disk(root):
        (root / rel).unlink()
    for rel, (_, text) in out.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    new = _new_lock(src, lock, out)
    (root / LOCK_REL).write_text(_dump(new), encoding="utf-8", newline="\n")
    return new


def check(root: Path, src: Path) -> list[str]:
    """Rỗng nghĩa là tệp trong repo và lock đúng là output của `build` tại commit ghim."""
    lock = load_lock(root)
    out = render(src, lock)
    report: list[str] = []
    for rel, (_, text) in out.items():
        p = root / rel
        if not p.is_file():
            report.append(f"thiếu: {rel}")
        elif read(p) != text:
            report.append(f"lệch: {rel}")
    report += [f"thừa: {rel}" for rel in _on_disk(root) if rel not in out]
    new = _new_lock(src, lock, out)
    report += [f"lock lệch: {key}" for key in ("files", "measured") if lock.get(key) != new[key]]
    return report


def fetch(remote: str, revision: str, dest: Path) -> Path:
    """Lấy nông đúng một commit — không clone cả lịch sử, không theo nhánh trôi."""
    dest.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["init", "-q"],
        ["fetch", "-q", "--depth", "1", remote, revision],
        ["checkout", "-q", "--detach", "FETCH_HEAD"],
    ):
        subprocess.run(["git", "-C", str(dest), *argv], check=True, capture_output=True)
    return dest


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows cp1252, CI PYTHONIOENCODING lạ
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Vendor ECC chọn lọc vào .claude/ (ADR-0028)")
    ap.add_argument("cmd", choices=("build", "check"))
    ap.add_argument(
        "--src",
        type=Path,
        help="clone ECC có sẵn, đứng ở đúng revision ghim; bỏ trống thì tự fetch",
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--remote", help="mặc định https://github.com/<repository>.git của lock")
    ns = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="ecc-") as tmp:
            src = ns.src
            if src is None:
                lock = load_lock(ns.root)
                src = fetch(
                    ns.remote or f"https://github.com/{lock['repository']}.git",
                    lock["revision"],
                    Path(tmp),
                )
            if ns.cmd == "build":
                new = build(ns.root, src)
                m = new["measured"]
                print(
                    f"ECC {new['tag']} → {m['files']} tệp: {m['skills']} skill, {m['commands']} lệnh, "
                    f"{m['agents']} agent; mô tả {m['description_chars']} ký tự"
                )
                return 0
            report = check(ns.root, src)
    except VendorError as e:
        print(f"ecc_vendor: {e}", file=sys.stderr)
        return 1
    for line in report:
        print(line, file=sys.stderr)
    if report:
        print(
            "Tập ECC vendor lệch nguồn ghim. Chạy `make ecc-vendor` rồi commit lại.",
            file=sys.stderr,
        )
        return 1
    print("ECC vendor khớp nguồn ghim.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
