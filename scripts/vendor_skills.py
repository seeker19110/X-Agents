"""Vendor skill chọn lọc từ nhiều nguồn vào `.claude/` — mỗi nguồn một lock, một tiền tố, ghim commit, sha256 từng
tệp (ADR gốc 0028, 0030).

Mỗi nguồn là một `docs/integrations/<tên>.lock.json`: `revision` ghim, `prefix` (vd `ecc-`, `mp-`), `label`,
`license_path`, `select` (mục được chép, kèm lý do), `rejected` (mục đã cân rồi loại); tuỳ chọn `paths` (khuôn thư mục
của nguồn), `ignore` (tệp phụ bỏ qua), `coupling` (dấu hiệu plugin riêng của nguồn). Script sinh các tệp dưới đây rồi
ghi lại `files` + `measured` vào lock:

    <paths.skills>/**.md     → .claude/skills/<prefix><x>/**.md      (mặc định skills/<x>)
    <paths.commands>         → .claude/commands/<prefix><x>.md       (mặc định commands/<x>.md)
    <paths.agents>           → .claude/agents/<prefix><x>.md         (mặc định agents/<x>.md)
    LICENSE                  → <license_path>

Biến đổi tất định, tối thiểu: `name:` trong frontmatter thêm tiền tố; tham chiếu TƯỜNG MINH tới mục đã vendor
(`/x`, `` `x` ``, `**x**`, `"x"`, `skill: x`, `agents|skills|commands/x`, tên agent có gạch nối) đổi sang
`<prefix>x`; một ghi chú nguồn sau frontmatter. Nguồn có dấu hiệu "chỉ chạy được khi là plugin" thì dừng, không vá.

    python scripts/vendor_skills.py build --lock <lock> [--src <clone nguồn>]   # make vendor LOCK=<lock>
    python scripts/vendor_skills.py check --lock <lock> [--src <clone nguồn>]   # make vendor-check; exit 1 nếu lệch
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
from collections.abc import Sequence
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("skills", "commands", "agents")
PATHS = {"skills": "skills/{name}", "commands": "commands/{name}.md", "agents": "agents/{name}.md"}
# Tiền tố đã có chủ: build xoá mọi `<tiền tố>*` cũ, nên lock mang tiền tố lồng với chúng sẽ xoá nhầm tệp của repo.
RESERVED = {"sc-": "`make subagents` (.claude/agents/sc-*)"}

# Dấu hiệu nội dung chỉ đúng khi nguồn chạy như plugin cài vào máy (mỗi mẫu một lý do, ADR-0028 §3). Mẫu riêng của
# một nguồn (vd `ecc:`) nằm trong `coupling` của lock đó.
COUPLING = {
    r"CLAUDE_PLUGIN_ROOT": "đường dẫn gốc plugin",
    r"~/\.claude": "ghi vào thư mục cá nhân của Claude Code",
    r"(?<![\w~])\.claude/": "ghi vào cây .claude của repo",
    r"\bnode\s+scripts/": "gọi script node của ECC (không vendor)",
    r"\bnpx\s+(?:-y|--yes)\b": "tải và chạy gói npm không hỏi",
}

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


class VendorError(Exception):
    """Nguồn hoặc lock không đạt — dừng build, không vá tự động."""


def load_lock(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
    """Tên mục đã chọn → loại. Hai loại trùng tên thì cùng thành `/<prefix><tên>`: một cái che cái kia."""
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


def _check_prefix(lock: dict, others: Sequence[dict]) -> None:
    prefix = lock["prefix"]
    if not re.fullmatch(r"[a-z0-9]+-", prefix):
        raise VendorError(f"prefix {prefix!r} phải khớp `[a-z0-9]+-`")
    taken = {**RESERVED, **{o["prefix"]: f"lock `{o['label']}`" for o in others}}
    for other, owner in taken.items():
        if prefix.startswith(other) or other.startswith(prefix):
            raise VendorError(f"tiền tố `{prefix}` lồng với `{other}` của {owner} — build sẽ xoá nhầm tệp của nhau")


def _sources(src: Path, lock: dict, kind: str, name: str) -> tuple[Path, list[Path]]:
    """(chỗ của mục ở nguồn, tệp sẽ chép). Khuôn `paths` của lock phải khớp đúng một chỗ."""
    pattern = {**PATHS, **lock.get("paths", {})}[kind].format(name=name)
    found = sorted(src.glob(pattern))
    if len(found) != 1:
        raise VendorError(f"`{pattern}` khớp {len(found)} chỗ ở nguồn — cần đúng 1")
    base = found[0]
    if kind == "skills":
        if not (base / "SKILL.md").is_file():
            raise VendorError(f"không có {pattern}/SKILL.md ở nguồn")
        ignore = lock.get("ignore", [])
        files = sorted(
            p
            for p in base.rglob("*")
            if (p.is_symlink() or p.is_file())
            and not any(fnmatch.fnmatchcase(p.relative_to(base).as_posix(), g) for g in ignore)
        )
    else:
        files = [base]
    for p in files:
        rel = p.relative_to(src).as_posix()
        if p.is_symlink():
            raise VendorError(f"{rel}: symlink — vendor chỉ nhận tệp thường")
        if p.suffix != ".md":
            raise VendorError(f"{rel}: không phải .md — skill có mã chạy kèm thì loại, không vendor nửa vời")
    return base, files


def _coupling(rel: str, text: str, lock: dict) -> None:
    for pattern, why in {**COUPLING, **lock.get("coupling", {})}.items():
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


def _rename(rel: str, text: str, kind: str, name: str, prefix: str) -> str:
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
        rf"^name:[ \t]*{re.escape(name)}[ \t]*$", f"name: {prefix}{name}", m.group(1), count=1, flags=re.MULTILINE
    )
    if yaml.safe_load(head).get("name") != prefix + name:
        raise VendorError(f"{rel}: không đổi được `name` (chỉ nhận dạng `name: {name}` trơn)")
    return f"---\n{head}\n---\n{text[m.end() :]}"


def _is_main(rel: str, lock: dict) -> bool:
    """Tệp mang frontmatter mà Claude Code liệt kê: SKILL.md, lệnh, agent — không tính tệp phụ của skill."""
    return rel.endswith("/SKILL.md") if rel.startswith(".claude/skills/") else rel != lock["license_path"]


def _description_chars(out: dict[str, tuple[str, str]], lock: dict) -> int:
    return sum(
        len(_frontmatter(rel, text)[1]["description"]) for rel, (_, text) in out.items() if _is_main(rel, lock)
    )


def _ref_pattern(items: dict[str, str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(n) for n in sorted(items, key=len, reverse=True))
    return re.compile(rf"(?<![\w./-])(?P<pre>/|(?:{'|'.join(KINDS)})/)?(?P<name>{alt})(?![\w-])")


def rewrite_refs(text: str, items: dict[str, str], prefix: str) -> str:
    """Chỉ đổi dạng tường minh: tên skill viết trơn có thể là từ thường ("error-handling patterns")."""
    pattern = _ref_pattern(items)

    def sub(m: re.Match[str]) -> str:
        pre, name = m.group("pre"), m.group("name")
        kind, new = items[name], prefix + name
        if pre == "/":
            return f"/{new}" if kind != "agents" else m.group(0)
        if pre:
            return f".claude/{kind}/{new}" if pre == f"{kind}/" else m.group(0)
        s, e = m.start(), m.end()
        explicit = (
            text[s - 1 : s] == "`" == text[e : e + 1]
            or text[s - 1 : s] == '"' == text[e : e + 1]
            or text[s - 2 : s] == "**" == text[e : e + 2]
            or re.search(r"skill:[ \t]*$", text[max(0, s - 16) : s], re.IGNORECASE) is not None
            or (kind == "agents" and "-" in name)
        )
        return new if explicit else m.group(0)

    return pattern.sub(sub, text)


def _note(lock: dict, source: str, lock_rel: str) -> str:
    label = lock["label"]
    return (
        f"<!-- Sinh bởi scripts/vendor_skills.py từ {lock['repository']}@{lock['revision']} ({source}) — không sửa tay; "
        f"đổi thì sửa {lock_rel} rồi chạy lại (ADR gốc 0030). -->\n"
        f"> **{label} ({lock['license']}), vendor vào X-Agents.** Luật ở `AGENTS.md` thắng khi trùng: coverage "
        "`fail_under = 100` (không phải 80%), test đỏ trước khi code, nhánh → PR theo `docs/QUY-TRINH-GIT.md`, không "
        f"xoá code ngoài yêu cầu. Mục của {label} được nhắc tới mà không có tệp `{lock['prefix']}<tên>` trong "
        "`.claude/` thì repo không vendor — dùng `/gate`, `/debug`, `/adr`, `/thi-hanh` hoặc bỏ qua.\n\n"
    )


def _with_note(text: str, note: str) -> str:
    m = _FRONTMATTER.match(text)
    cut = m.end() if m else 0
    return text[:cut] + ("\n" if m else "") + note + text[cut:].lstrip("\n")


def _target(prefix: str, kind: str, name: str, rel_in_item: str) -> str:
    if kind == "skills":
        return f".claude/skills/{prefix}{name}/{rel_in_item}"
    return f".claude/{kind}/{prefix}{name}.md"


def render(
    src: Path, lock: dict, *, lock_rel: str = "lock", others: Sequence[dict] = ()
) -> dict[str, tuple[str, str]]:
    """Đường dẫn trong repo → (đường dẫn nguồn, toàn văn). Không ghi gì. `others`: lock của nguồn khác cùng repo."""
    _check_prefix(lock, others)
    prefix = lock["prefix"]
    head = _git_head(src)
    if head != lock["revision"]:
        raise VendorError(f"nguồn đang ở {head or '?'}, lock ghim revision {lock['revision']}")
    items = _items(lock)
    out: dict[str, tuple[str, str]] = {}
    for name, kind in items.items():
        base, files = _sources(src, lock, kind, name)
        for p in files:
            rel = p.relative_to(src).as_posix()
            text = read(p)
            _coupling(rel, text, lock)
            inner = p.relative_to(base).as_posix() if kind == "skills" else ""
            if kind != "skills" or inner == "SKILL.md":
                text = _rename(rel, text, kind, name, prefix)
            note = _note(lock, rel, lock_rel)
            out[_target(prefix, kind, name, inner)] = (rel, _with_note(rewrite_refs(text, items, prefix), note))
    lic = src / "LICENSE"
    if not lic.is_file():
        raise VendorError("nguồn thiếu LICENSE — không vendor mã không rõ giấy phép")
    out[lock["license_path"]] = ("LICENSE", read(lic))
    total = _description_chars(out, lock)
    if total > lock["budget_description_chars"]:
        raise VendorError(f"mô tả cộng lại {total} ký tự > budget_description_chars {lock['budget_description_chars']}")
    return dict(sorted(out.items()))


def _measured(src: Path, out: dict[str, tuple[str, str]], lock: dict) -> dict:
    items = _items(lock)
    paths = {**PATHS, **lock.get("paths", {})}
    return {
        **{kind: sum(1 for k in items.values() if k == kind) for kind in KINDS},
        "files": len(out),
        "bytes": sum(len(text.encode("utf-8")) for _, text in out.values()),
        "description_chars": _description_chars(out, lock),
        "upstream": {
            kind: sum(1 for _ in src.glob(paths[kind].format(name="*") + ("/SKILL.md" if kind == "skills" else "")))
            for kind in KINDS
        },
    }


def _new_lock(src: Path, lock: dict, out: dict[str, tuple[str, str]]) -> dict:
    files = [{"path": rel, "source": source, "sha256": sha256(text)} for rel, (source, text) in out.items()]
    return {**lock, "files": files, "measured": _measured(src, out, lock)}


def _dump(lock: dict) -> str:
    return json.dumps(lock, indent=2, ensure_ascii=False) + "\n"


def _on_disk(root: Path, lock: dict) -> list[str]:
    claude, prefix = root / ".claude", lock["prefix"]
    found = [p for p in (claude / "skills").glob(f"{prefix}*/**/*") if p.is_file()]
    found += [p for kind in ("commands", "agents") for p in (claude / kind).glob(f"{prefix}*.md")]
    found += [p for p in [root / lock["license_path"]] if p.is_file()]
    return sorted(p.relative_to(root).as_posix() for p in found)


def _rel(root: Path, lock_path: Path) -> str:
    return lock_path.resolve().relative_to(root.resolve()).as_posix()


def _render_lock(root: Path, src: Path, lock_path: Path) -> tuple[dict, dict[str, tuple[str, str]]]:
    """Lock + output; lock anh em (cùng thư mục, có `select`) đi vào `others` để kiểm tiền tố."""
    lock = load_lock(lock_path)
    others = [
        o
        for p in sorted(lock_path.parent.glob("*.lock.json"))
        if p.resolve() != lock_path.resolve() and "select" in (o := load_lock(p))
    ]
    return lock, render(src, lock, lock_rel=_rel(root, lock_path), others=others)


def build(root: Path, src: Path, lock_path: Path) -> dict:
    lock, out = _render_lock(root, src, lock_path)
    for d in (root / ".claude" / "skills").glob(f"{lock['prefix']}*"):
        shutil.rmtree(d)
    for rel in _on_disk(root, lock):
        (root / rel).unlink()
    for rel, (_, text) in out.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    new = _new_lock(src, lock, out)
    lock_path.write_text(_dump(new), encoding="utf-8", newline="\n")
    return new


def check(root: Path, src: Path, lock_path: Path) -> list[str]:
    """Rỗng nghĩa là tệp trong repo và lock đúng là output của `build` tại commit ghim."""
    lock, out = _render_lock(root, src, lock_path)
    report: list[str] = []
    for rel, (_, text) in out.items():
        p = root / rel
        if not p.is_file():
            report.append(f"thiếu: {rel}")
        elif read(p) != text:
            report.append(f"lệch: {rel}")
    report += [f"thừa: {rel}" for rel in _on_disk(root, lock) if rel not in out]
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
    ap = argparse.ArgumentParser(description="Vendor skill chọn lọc vào .claude/ (ADR gốc 0028, 0030)")
    ap.add_argument("cmd", choices=("build", "check"))
    ap.add_argument("--lock", type=Path, required=True, help="vd docs/integrations/ecc.lock.json")
    ap.add_argument(
        "--src",
        type=Path,
        help="clone nguồn có sẵn, đứng ở đúng revision ghim; bỏ trống thì tự fetch",
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--remote", help="mặc định https://github.com/<repository>.git của lock")
    ns = ap.parse_args(argv)
    lock = load_lock(ns.lock)
    try:
        with tempfile.TemporaryDirectory(prefix="vendor-") as tmp:
            src = ns.src
            if src is None:
                src = fetch(
                    ns.remote or f"https://github.com/{lock['repository']}.git",
                    lock["revision"],
                    Path(tmp),
                )
            if ns.cmd == "build":
                new = build(ns.root, src, ns.lock)
                m = new["measured"]
                print(
                    f"{new['label']} {new['tag'] or new['version']} → {m['files']} tệp: {m['skills']} skill, {m['commands']} lệnh, "
                    f"{m['agents']} agent; mô tả {m['description_chars']} ký tự"
                )
                return 0
            report = check(ns.root, src, ns.lock)
    except VendorError as e:
        print(f"vendor_skills: {e}", file=sys.stderr)
        return 1
    for line in report:
        print(line, file=sys.stderr)
    if report:
        print(
            f"Tập vendor `{lock['label']}` lệch nguồn ghim. Chạy `make vendor LOCK={_rel(ns.root, ns.lock)}` rồi "
            "commit lại.",
            file=sys.stderr,
        )
        return 1
    print(f"Tập vendor `{lock['label']}` khớp nguồn ghim.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
