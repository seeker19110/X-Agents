"""ADR-0055: lệnh `image_digest` cho builder — digest manifest của image trong Dockerfile/compose, lấy từ Docker Hub.

Đo hub thật 2026-10-12 (QLKH-DD-CSV/DDCSV-20): job CI `image-pin` của repo khách đòi mọi `FROM` có `@sha256:`; builder
không có docker, không có mạng tới registry nên bị chặn hai lượt liên tiếp cùng một lý do và (đúng luật) không đoán
digest. Cùng họ `lock` (ADR-0054): việc cần mạng thì CODE mở đúng domain qua egress (ADR gốc 0010), model chỉ chọn tên
lệnh. Lệnh chỉ IN `ref@sha256:…` — không ghi file; builder đọc rồi tự ghim.

Digest là của **manifest list** (đa kiến trúc) — đúng thứ `docker pull` ghi vào `RepoDigests` và `FROM img:tag@sha256:`
cần; đo 2026-10-12 trên máy chủ: HEAD manifest qua HTTPS trả `519591d6…` cho `python:3.12.11-slim-bookworm`, khớp
`docker image inspect --format '{{.RepoDigests}}'` sau khi pull. Chỉ Docker Hub (`docker.io`): registry khác in `LOI`
và exit 1 — không đoán, không mở thêm domain mà không có ADR.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

from .deploy import COMPOSE_NAMES

DOMAINS = ("auth.docker.io", "registry-1.docker.io")
DOCKERFILES = ("Dockerfile", "*/Dockerfile")  # đúng tập mà job `image-pin` của khách quét
_FROM = re.compile(r"^\s*FROM\s+(.*)$", re.IGNORECASE)
_IMAGE = re.compile(r"""^\s*image:\s*["']?([^"'\s#]+)""")
_SERVICE = re.compile(r"^  ([A-Za-z0-9._-]+):\s*(#.*)?$")
_BUILD = re.compile(r"""^\s+build:\s*["']?([^"'\s#]*)""")
_BUILD_KEY = re.compile(r"""^\s*(context|dockerfile):\s*["']?([^"'\s#]+)""")
_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]{1,128})?(@sha256:[0-9a-f]{64})?$")
_SKIP = frozenset({"scratch"})

# Chạy TRONG sandbox bằng python của image (chỉ stdlib, không docker): token pull ẩn danh rồi HEAD manifest.
SCRIPT = r"""
import json, sys, urllib.request
ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])
def digest(ref):
    i = ref.rfind(":")
    name, tag = (ref[:i], ref[i + 1:]) if i > ref.rfind("/") else (ref, "latest")
    head = name.split("/")[0]
    if "." in head or head == "localhost":
        raise ValueError("registry ngoai docker.io chua ho tro (ADR-0055)")
    repo = name if "/" in name else "library/" + name
    tok = json.loads(urllib.request.urlopen(
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull" % repo, timeout=30).read())["token"]
    req = urllib.request.Request("https://registry-1.docker.io/v2/%s/manifests/%s" % (repo, tag), method="HEAD",
                                 headers={"Authorization": "Bearer " + tok, "Accept": ACCEPT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.headers["Docker-Content-Digest"]
bad = 0
for ref in sys.argv[1:]:
    try:
        print(ref + "@" + digest(ref))
    except Exception as e:
        bad += 1
        print(ref + " LOI: " + str(e)[:200])
sys.exit(1 if bad else 0)
"""


def _dockerfile_refs(text: str, pinned: bool = False) -> list[str]:
    refs, aliases = [], set()
    for line in text.splitlines():
        if not (m := _FROM.match(line)):
            continue
        toks = [t for t in m.group(1).split() if not t.startswith("--")]
        if not toks:
            continue
        ref = toks[0]
        if len(toks) >= 3 and toks[1].upper() == "AS":
            aliases.add(toks[2])
        if ref not in aliases and ref not in _SKIP and (pinned or "@" not in ref) and _REF.match(ref):
            refs.append(ref)
    return refs


def _compose_refs(text: str, pinned: bool = False) -> list[str]:
    return [
        m.group(1)
        for ln in text.splitlines()
        if (m := _IMAGE.match(ln)) and (pinned or "@" not in m.group(1)) and _REF.match(m.group(1))
    ]


def _compose_builds(root: Path) -> list[tuple[str, Path]]:
    """(service, Dockerfile) mà compose BUILD — `build: <context>` hay khối `build:` với `context`/`dockerfile` (mặc
    định `Dockerfile` trong context), kể cả ngoài `DOCKERFILES`. Hub 2026-10-16 (REL-105): `infra/db/Dockerfile` hai
    tầng thư mục nên image nền db không được quét. Đường ra ngoài repo bị bỏ. Đọc theo dòng như `_IMAGE`: service là
    khoá thụt đúng hai dấu cách."""
    top, out = root.resolve(), []
    for n in COMPOSE_NAMES:
        try:
            lines = (root / n).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        svc, ctx, df = "", None, "Dockerfile"
        for ln in [*lines, "  __eof__:"]:
            if m := _SERVICE.match(ln):
                p: Path | None = None if ctx is None else (root / ctx / df).resolve()
                if p is not None and p.is_relative_to(top) and p.is_file():
                    out.append((svc, p))
                svc, ctx, df = m.group(1), None, "Dockerfile"
            elif m := _BUILD.match(ln):
                ctx = m.group(1) or "."
            elif ctx is not None and (m := _BUILD_KEY.match(ln)):
                ctx, df = (m.group(2), df) if m.group(1) == "context" else (ctx, m.group(2))
    return out


def _refs(p: Path, read: Callable[[str, bool], list[str]], pinned: bool = True) -> list[str]:
    try:
        return read(p.read_text(encoding="utf-8"), pinned)
    except (OSError, UnicodeDecodeError):
        return []


def references(root: Path, *, pinned: bool = False) -> list[str]:
    """Image chưa ghim digest, theo thứ tự gặp, không trùng. Bỏ alias stage, `${ARG}`, `scratch`, đã có `@sha256:`.
    `pinned=True` giữ cả image đã ghim — tập để quét lỗ hổng image nền (ADR-0056), không phải tập cần ghim."""
    out: list[str] = []
    files = [(p, _dockerfile_refs) for g in DOCKERFILES for p in sorted(root.glob(g))]
    files += [(p, _dockerfile_refs) for _, p in _compose_builds(root)]  # trùng file thì trùng ref: bỏ ở dưới
    files += [(root / n, _compose_refs) for n in COMPOSE_NAMES]
    for p, read in files:
        for r in _refs(p, read, pinned):
            if r not in out:
                out.append(r)
    return out


def scan_refs(root: Path, deployed: set[str]) -> list[str]:
    """Image nền cần quét lỗ hổng (ADR-0056): `references(pinned=True)` BỎ image nền của Dockerfile mà image đã dựng
    từ nó đang chạy ở staging (`deployed` = service có image id) — image đó được quét riêng và mới là bằng chứng.

    Hub 2026-10-16 (REL-107): `infra/db/Dockerfile` cố ý ghim base `postgres:16.15-trixie` rồi `apt-get upgrade` và gỡ
    `gosu` (ADR-DD-15); image db đang chạy có 0 CVE có bản sửa, base có 25. Đưa base vào bằng chứng → reviewer đòi đổi
    base, đi ngược quyết định kiến trúc. Base còn được Dockerfile chưa chạy hay `image:` của compose dùng thì giữ."""
    builds = _compose_builds(root)
    done = {p for s, p in builds if s in deployed}
    other = {p.resolve() for g in DOCKERFILES for p in root.glob(g)} | {p for _, p in builds}
    keep = {r for p in other - done for r in _refs(p, _dockerfile_refs)}
    keep |= {r for n in COMPOSE_NAMES for r in _refs(root / n, _compose_refs)}
    drop = {r for p in done for r in _refs(p, _dockerfile_refs)} - keep
    return [r for r in references(root, pinned=True) if r not in drop]


def tags(root: Path) -> list[str]:
    """Mọi image của Dockerfile/compose, bỏ `@sha256:` — hỏi digest HIỆN TẠI của tag, không trùng.

    ADR-0055 bổ sung (hub 2026-10-13, CR-DDCSV-SEC-001): nâng image đã ghim lên bản vá cũng cần digest mới; bản đầu
    chỉ hỏi image chưa ghim nên repo ghim hết thì builder không có lệnh nào và chỉ còn sửa tay (cấm) hay dừng. Ref chỉ
    có digest, không tag, thành tên trần — script hỏi `latest` như `docker pull`."""
    out: list[str] = []
    for r in references(root, pinned=True):
        t = r.split("@", 1)[0]
        if t not in out:
            out.append(t)
    return out


def argv(root: Path) -> list[str] | None:
    """argv của `run image_digest`; None = repo không có image nào ⇒ không có lệnh trong allowlist. `WorkspaceTools.run`
    gọi lại hàm này lúc chạy: builder sửa tag giữa lượt thì argv theo file hiện tại."""
    refs = tags(root)
    return [sys.executable, "-c", SCRIPT, *refs] if refs else None
