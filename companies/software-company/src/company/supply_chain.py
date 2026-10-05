"""ADR-0046: bằng chứng chuỗi cung ứng (SBOM + license) của một cây RC, do orchestrator sinh — không phải lời khai.

Thành phần đọc từ lock file (không chạy gì): `uv.lock`, `package-lock.json` v2/v3, `Cargo.lock`, `go.mod` — ở gốc cây
RC và thư mục con một tầng. License: uv từ metadata gói đã cài trong môi trường của KHÁCH (`uv run --frozen`,
ADR-0044), Cargo từ `cargo metadata --offline`, cả hai qua sandbox (ADR-0035); npm từ chính lock + `node_modules`;
Go không có nguồn nào nên `NOASSERTION`. Chuẩn hoá sang SPDX chỉ khi không mơ hồ; còn lại là `NOASSERTION` kèm
chuỗi gốc — không đoán. Không kết luận hợp lệ hay không: đó là chính sách của dự án.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from .sandbox import RunSpec, clean_env
from .smoke import VERIFIED_BY, unverified

NOASSERTION = "NOASSERTION"

# Chạy trong venv của khách: in {tên PEP 503: chuỗi license gốc}. PEP 639 → classifier → trường `License`.
_SCRIPT = (
    "import importlib.metadata as m, json, re\n"
    "out = {}\n"
    "for d in m.distributions():\n"
    "    md = d.metadata\n"
    "    name = re.sub(r'[-_.]+', '-', md.get('Name') or '').lower()\n"
    "    if not name: continue\n"
    "    lic = (md.get('License-Expression') or '').strip()\n"
    "    if not lic:\n"
    "        lic = ' OR '.join(c.split('::')[-1].strip() for c in (md.get_all('Classifier') or []) if c.startswith('License ::'))\n"
    "    if not lic: lic = (md.get('License') or '').strip()\n"
    "    out[name] = lic.splitlines()[0][:200] if lic else ''\n"
    "print(json.dumps(out))\n"
)

# Tên gọi không mơ hồ → SPDX id. "BSD License", "Apache Software License" không nói phiên bản: không có ở đây.
_NAMES = {
    "mit": "MIT",
    "mit license": "MIT",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0",
    "apache software license 2.0": "Apache-2.0",
    "new bsd license": "BSD-3-Clause",
    "modified bsd license": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "simplified bsd license": "BSD-2-Clause",
    "bsd 2-clause": "BSD-2-Clause",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "python software foundation license": "PSF-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "the unlicense (unlicense)": "Unlicense",
}
_SPDX_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
_AMBIGUOUS = frozenset({"BSD", "GPL", "LGPL", "AGPL", "Apache", "Proprietary", "UNKNOWN", "Other"})
_OPS = frozenset({"AND", "OR", "WITH"})


def _pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def spdx_of(raw: str) -> str:
    """Chuỗi license gốc → SPDX (id hoặc biểu thức) khi không mơ hồ; ngược lại `NOASSERTION`."""
    s = raw.strip()
    if not s:
        return NOASSERTION
    if (named := _NAMES.get(s.lower())) is not None:
        return named
    toks = s.split()
    ids = [t.strip("()") for t in toks[0::2]]
    if all(op in _OPS for op in toks[1::2]) and all(_SPDX_ID.fullmatch(i) and i not in _AMBIGUOUS for i in ids):
        return s
    return NOASSERTION


def components(root: Path) -> list[dict[str, str]] | None:
    """Gói trong `uv.lock` (trừ gói gốc/workspace). Không có lock → None."""
    lock = root / "uv.lock"
    if not lock.is_file():
        return None
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    out = []
    for pkg in data.get("package", []):
        src = pkg.get("source") or {}
        if "editable" in src or "virtual" in src:
            continue
        name, version = _pep503(str(pkg.get("name", ""))), str(pkg.get("version", ""))
        out.append({"name": name, "version": version, "purl": f"pkg:pypi/{name}@{version}"})
    return out


def _json_run(sandbox: Any, spec: RunSpec) -> tuple[dict[str, Any], str | None]:
    """Chạy `spec` trong sandbox, đọc stdout là một object JSON. Lỗi → ({}, lý do), không ném."""
    try:
        r = sandbox.run(spec)
    except OSError as e:
        return {}, f"{type(e).__name__}: {e}"[:300]
    if r.exit_code != 0:
        return {}, f"exit_code={r.exit_code}: {r.stderr.strip()[-300:]}"
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {}, f"stdout không phải JSON: {r.stdout.strip()[:200]}"
    return data, None


def installed_licenses(root: Path, sandbox: Any) -> tuple[dict[str, str], str | None]:
    """License gốc của mọi gói đã cài trong môi trường của khách. Lỗi → ({}, lý do), không ném."""
    spec = RunSpec(
        argv=["uv", "run", "--frozen", "--", "python", "-c", _SCRIPT],
        cwd=root,
        env=clean_env(),
        timeout=600.0,
        max_output=2_000_000,
    )
    data, err = _json_run(sandbox, spec)
    return {str(k): str(v) for k, v in data.items()}, err


Rows = tuple[list[dict[str, Any]], str | None]


def _uv(d: Path, sandbox: Any) -> Rows:
    lic, err = installed_licenses(d, sandbox)
    rows = []
    for c in components(d) or []:
        raw = lic.get(c["name"])
        rows.append({**c, "raw": raw or "", "installed": (raw is not None) if err is None else None})
    return rows, err


def _npm_license(v: Any) -> str:
    """`license` của package.json: chuỗi, hoặc dạng cũ `{type: ...}`."""
    if isinstance(v, dict):
        v = v.get("type")
    return v.strip() if isinstance(v, str) else ""


def _npm(d: Path, sandbox: Any) -> Rows:
    """`package-lock.json` v2/v3 (`packages`): npm tự ghi `license` của từng gói; thiếu thì đọc `package.json` đã cài
    trong `node_modules`. Không chạy gì. Gói gốc (`""`), workspace (`link`) và đường không nằm dưới `node_modules/`
    (mã của chính dự án) không tính."""
    pkgs = json.loads((d / "package-lock.json").read_text(encoding="utf-8")).get("packages")
    if not isinstance(pkgs, dict):
        return [], "lockfileVersion 1 (không có `packages`) — chỉ đọc lock npm v2/v3"
    rows = []
    for path, e in pkgs.items():
        if "node_modules/" not in path or not isinstance(e, dict) or e.get("link") or not e.get("version"):
            continue
        name, version = str(e.get("name") or path.rsplit("node_modules/", 1)[1]), str(e["version"])
        pj = d / path / "package.json"
        raw = _npm_license(e.get("license"))
        if not raw and pj.is_file():
            raw = _npm_license(json.loads(pj.read_text(encoding="utf-8")).get("license"))
        purl = f"pkg:npm/{name.replace('@', '%40', 1)}@{version}"
        rows.append({"name": name, "version": version, "purl": purl, "raw": raw, "installed": pj.is_file()})
    return rows, None


def _cargo(d: Path, sandbox: Any) -> Rows:
    """`Cargo.lock` (gói có `source`; không có là crate của chính workspace). License từ `cargo metadata --locked
    --offline` trong sandbox: crates.io bắt khai biểu thức SPDX; `/` là cú pháp OR cũ Cargo còn chấp nhận."""
    data = tomllib.loads((d / "Cargo.lock").read_text(encoding="utf-8"))
    comps = [(str(p.get("name", "")), str(p.get("version", ""))) for p in data.get("package", []) if p.get("source")]
    spec = RunSpec(
        argv=["cargo", "metadata", "--format-version", "1", "--locked", "--offline"],
        cwd=d,
        env=clean_env(),
        timeout=600.0,
        max_output=30_000_000,
    )
    lic, err = _json_run(sandbox, spec)
    got = {f"{p.get('name')}@{p.get('version')}": str(p.get("license") or "") for p in lic.get("packages") or []}
    rows = []
    for name, version in comps:
        raw = got.get(f"{name}@{version}")
        rows.append(
            {
                "name": name,
                "version": version,
                "purl": f"pkg:cargo/{name}@{version}",
                "raw": raw or "",
                "spdx": spdx_of((raw or "").replace("/", " OR ")),
                "installed": (raw is not None) if err is None else None,
            }
        )
    return rows, err


def _go(d: Path, sandbox: Any) -> Rows:
    """`go.mod` (Go ≥ 1.17 ghi đủ phụ thuộc gián tiếp). Module Go không khai license trong metadata: mọi gói
    `NOASSERTION`, `licenses_error` nói vì sao — không đoán từ file LICENSE."""
    rows, block = [], False
    for line in (d / "go.mod").read_text(encoding="utf-8").splitlines():
        s = line.split("//", 1)[0].strip()
        if s == "require (":
            block = True
            continue
        if block and s == ")":
            block = False
            continue
        parts = s.split()
        if s.startswith("require ") and len(parts) == 3:
            parts = parts[1:]
        elif not block or len(parts) != 2:
            continue
        rows.append(
            {
                "name": parts[0],
                "version": parts[1],
                "purl": f"pkg:golang/{parts[0]}@{parts[1]}",
                "raw": "",
                "installed": None,
            }
        )
    return rows, "module Go không khai license trong metadata; chưa quét file LICENSE của module"


# Lock file → cách đọc. Thứ tự này là thứ tự trong SBOM.
_READERS = (("uv.lock", _uv), ("package-lock.json", _npm), ("Cargo.lock", _cargo), ("go.mod", _go))
_SKIP_DIRS = frozenset({"node_modules", "target", "vendor"})


def _dirs(root: Path) -> list[Path]:
    """Gốc cây RC + một tầng thư mục con (monorepo `frontend/`, `backend/`), bỏ thư mục ẩn và thư mục phụ thuộc."""
    subs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in _SKIP_DIRS]
    return [root, *sorted(subs)]


def evidence(root: Path, sandbox: Any, sha: str) -> dict[str, Any]:
    """Bằng chứng `evidence.supply_chain` của cây RC `root` (ADR-0046 §1, §4 và phần bổ sung)."""
    by_purl: dict[str, dict[str, Any]] = {}
    sources, errs = [], []
    for d in _dirs(root):
        for fname, read in _READERS:
            if not (d / fname).is_file():
                continue
            rel = (d / fname).relative_to(root).as_posix()
            try:
                got, err = read(d, sandbox)
            except (ValueError, OSError) as e:  # lock file của khách hỏng (JSON/TOML/UTF-8): lý do, không ném
                got, err = [], f"đọc không được: {type(e).__name__}: {e}"[:300]
            sources.append(rel)
            if err is not None:
                errs.append(f"{rel}: {err}")
            for r in got:
                by_purl.setdefault(r["purl"], {**r, "license": r.pop("spdx", None) or spdx_of(r["raw"]), "lock": rel})
    if not sources:
        return unverified(
            "cây RC không có lock file nào đọc được (uv.lock, package-lock.json, Cargo.lock, go.mod) ở gốc hay "
            "thư mục con một tầng"
        )
    rows = list(by_purl.values())
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": [
            {
                "type": "library",
                "name": r["name"],
                "version": r["version"],
                "purl": r["purl"],
                "licenses": [] if r["license"] == NOASSERTION else [{"expression": r["license"]}],
            }
            for r in rows
        ],
    }
    digest = hashlib.sha256(json.dumps(sbom, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    ev: dict[str, Any] = {
        "verified_by": VERIFIED_BY,
        "source": "+".join(sources),
        "sha": sha,
        "components": len(rows),
        "licenses": dict(Counter(r["license"] for r in rows)),
        "noassertion": [
            {k: r[k] for k in ("name", "version", "raw", "installed", "lock")}
            for r in rows
            if r["license"] == NOASSERTION
        ],
        "copyleft": [
            {k: r[k] for k in ("name", "version", "license", "raw")}
            for r in rows
            if re.search(r"GPL|GENERAL PUBLIC|SSPL", f"{r['raw']} {r['license']}".upper())
        ],
        "sbom_ref": f"sha256:{digest}",
        "sbom": sbom,
    }
    if errs:
        ev["licenses_error"] = "; ".join(errs)
    return ev
