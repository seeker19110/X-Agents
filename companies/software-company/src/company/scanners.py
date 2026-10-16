"""ADR-0056: SCA và quét secret do ORCHESTRATOR chạy trên máy trực trước release-check của security.

Cùng họ với SBOM (ADR-0046) và DAST (ADR-0047): security được dặn không đoán, nên bằng chứng "0 High/Critical reachable"
và "không có secret trong lịch sử git" chỉ có khi MÁY đưa số. Hai binary ngoài, tìm trên `PATH` của máy trực:

- `trivy` (aquasecurity): `trivy fs` trên cây RC đọc lock file (kể cả `requirements.lock` của `uv pip compile`, tên mà
  trivy không tự nhận) và `trivy image` cho từng image của Dockerfile/compose (gói Debian của image nền). Lên bus: số
  theo mức độ + danh sách phát hiện của lock (có trần); image: số đếm + danh sách CRITICAL/HIGH (có trần) — 421 CVE
  Debian mức MEDIUM/LOW không phải thứ đọc trên bus.
- `gitleaks`: toàn bộ lịch sử git của cây RC. Lên bus chỉ VỊ TRÍ (rule, file, commit, dòng), không bao giờ giá trị.

Thiếu binary → `unverified` nói rõ cách cài; chạy lỗi/quá giờ → `unverified` kèm đuôi stderr. Có phát hiện KHÔNG phải
lỗi chạy (`--exit-code 0`): chặn hay không là chính sách của dự án, máy chỉ đưa số (ADR-0046 §3). `which`/`run` là thuộc
tính module để test tiêm như `deploy()`; CI không có hai binary này.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .smoke import VERIFIED_BY, unverified

which: Any = shutil.which
run: Any = subprocess.run
MAX_FINDINGS = 50
#: Trần AN TOÀN cho danh sách CRITICAL/HIGH — reviewer cần đủ từng cặp (CVE, gói, fixed) để ký miễn ADR gốc 0036;
#: `MAX_FINDINGS` chỉ còn cắt MEDIUM/LOW của lock file. Vượt trần thì `findings_complete=false`, không lặng lẽ cắt.
SERIOUS_MAX = 500
TIMEOUT_S = 600
TRIVY_FS = ("fs", "--scanners", "vuln", "--file-patterns", r"pip:requirements\.lock", "--format", "json", "--quiet")
TRIVY_IMAGE = ("image", "--scanners", "vuln", "--format", "json", "--quiet")
GITLEAKS = ("git", "--no-banner", "--redact=100", "--report-format", "json", "--exit-code", "0")
_SCANNED = re.compile(r"(\d+) commits scanned")
_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


def _tail(s: str, n: int = 300) -> str:
    return s.strip()[-n:]


def _exec(argv: list[str]) -> subprocess.CompletedProcess[str] | str:
    """Chạy binary ngoài; trả `str` = lý do không có kết quả (quá giờ / không chạy được)."""
    try:
        return run(argv, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"{argv[0]} quá {TIMEOUT_S}s — không có kết quả"
    except OSError as e:
        return f"không chạy được {argv[0]}: {e}"


def _tool(name: str, hint: str) -> tuple[str, str] | str:
    """`(đường dẫn, "tên phiên bản")` hay lý do `unverified` khi thiếu trên PATH của máy trực."""
    exe = which(name)
    if not exe:
        return f"{name} không có trên PATH của máy trực — {hint}"
    r = _exec([exe, "--version"])
    # trivy: "Version: 0.75.0"; gitleaks: "gitleaks version 8.30.1" — token cuối của dòng đầu là phiên bản
    first = (r.stdout.strip().splitlines() or [""])[0] if not isinstance(r, str) else ""
    return exe, f"{name} {(first.split() or [''])[-1]}".strip()


def _by_severity(vulns: list[dict[str, Any]]) -> dict[str, int]:
    out = {s: sum(1 for v in vulns if v.get("Severity") == s) for s in _SEVERITIES}
    return {k: n for k, n in out.items() if n}


def _finding(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "package": v.get("PkgName"),
        "version": v.get("InstalledVersion"),
        "id": v.get("VulnerabilityID"),
        "severity": v.get("Severity"),
        "fixed": v.get("FixedVersion"),
    }


def _image_summary(ref: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Đếm theo mức độ cho mọi CVE của image; danh sách chỉ CRITICAL + HIGH (CRITICAL trước, có bản sửa trước, trần
    `MAX_FINDINGS`). ADR-0056 bổ sung (REL-022): chỉ số đếm thì security không viết được hồ sơ ngoại lệ hay chọn CVE
    để vá; MEDIUM/LOW của image nền là hàng trăm dòng và vẫn chỉ đếm."""
    vulns = [v for r in doc.get("Results") or [] for v in r.get("Vulnerabilities") or []]
    meta = doc.get("Metadata") or {}
    os_ = meta.get("OS") or {}
    return {
        "ref": ref,
        "digest": next(iter(meta.get("RepoDigests") or []), None),
        "os": " ".join(str(x) for x in (os_.get("Family"), os_.get("Name")) if x) or None,
        "by_severity": _by_severity(vulns),
        "total": len(vulns),
        "fixable": sum(1 for v in vulns if v.get("FixedVersion")),
        **_serious(vulns),
        **_listed(vulns, others=False),
    }


def _listed(vulns: list[dict[str, Any]], *, others: bool) -> dict[str, Any]:
    """Đủ mọi CRITICAL/HIGH (CRITICAL trước, có bản sửa trước, trần `SERIOUS_MAX`); lock file lấp thêm MEDIUM/LOW tới
    `MAX_FINDINGS`. Hub 2026-10-16 (REL-118): image db 62 C/H mà `findings` chỉ 50 ⇒ 12 cặp không kiểm được `fixed`."""
    serious = [v for v in vulns if v.get("Severity") in ("CRITICAL", "HIGH")]
    serious.sort(key=lambda v: (v.get("Severity") != "CRITICAL", not v.get("FixedVersion")))
    out = serious[:SERIOUS_MAX]
    if others:
        out += [v for v in vulns if v.get("Severity") not in ("CRITICAL", "HIGH")][: max(0, MAX_FINDINGS - len(out))]
    return {"findings": [_finding(v) for v in out], "findings_complete": len(serious) <= SERIOUS_MAX}


def _serious(vulns: list[dict[str, Any]]) -> dict[str, Any]:
    """CRITICAL/HIGH trên TOÀN BỘ, không theo trần `MAX_FINDINGS` — điều kiện ký miễn của ADR gốc 0036 ("mọi
    CRITICAL/HIGH không có bản sửa" + liệt kê mã CVE); hub 2026-10-14 REL-074: image db 62 C/H, `findings` chỉ 50 →
    reviewer giữ. Lock file (trivy fs) cũng cần: hub 2026-10-15 REL-090 mục `requirements.lock` luôn `complete=false`."""
    serious = [v for v in vulns if v.get("Severity") in ("CRITICAL", "HIGH")]
    return {
        "serious_fixable": sum(1 for v in serious if v.get("FixedVersion")),
        "serious_ids": sorted({str(v.get("VulnerabilityID")) for v in serious}),
    }


def vuln_evidence(
    root: Path, sha: str, images: list[str], deployed: list[tuple[str, str]] | None = None
) -> dict[str, Any]:
    """`evidence.vuln` của cây RC `root`: lock file (trivy fs) + image nền (trivy image từng `ref`) + image ĐÃ DỰNG
    của staging (`deployed` = cặp service, image id từ `evidence.deploy`; ADR-0056 bổ sung 2026-10-14). Image dẫn xuất
    (`build:`) không có image nền nào nói đúng về nó — gói đã gỡ trong Dockerfile vẫn nằm trong image nền."""
    t = _tool("trivy", "cài aquasecurity/trivy (một binary) để có SCA cho release-check")
    if isinstance(t, str):
        return unverified(t)
    exe, tool = t
    r = _exec([exe, *TRIVY_FS, str(root)])
    if isinstance(r, str):
        return {**unverified(r), "tool": tool}
    if r.returncode != 0:
        return {**unverified(f"trivy fs thoát {r.returncode}: {_tail(r.stderr)}"), "tool": tool}
    targets: list[dict[str, Any]] = []
    all_vulns: list[dict[str, Any]] = []
    for res in json.loads(r.stdout or "{}").get("Results") or []:
        vulns = res.get("Vulnerabilities") or []
        all_vulns += vulns
        targets.append(
            {
                "target": res.get("Target"),
                "type": res.get("Type"),
                "packages": len(res.get("Packages") or []),
                "by_severity": _by_severity(vulns),
                "total": len(vulns),
                **_serious(vulns),
                **_listed(vulns, others=True),
            }
        )
    by_id: dict[str, list[str]] = {}
    for service, image_id in deployed or []:
        if image_id:
            by_id.setdefault(image_id, []).append(service)
    jobs: list[tuple[str, dict[str, Any]]] = [(ref, {}) for ref in images]
    jobs += [(i, {"service": ",".join(s), "deployed": True, "image_id": i}) for i, s in by_id.items()]
    imgs, errors = [], []
    for ref, extra in jobs:
        ri = _exec([exe, *TRIVY_IMAGE, ref])
        if isinstance(ri, str) or ri.returncode != 0:
            errors.append({"image": ref, "error": ri if isinstance(ri, str) else _tail(ri.stderr)})
            continue
        imgs.append({**_image_summary(ref, json.loads(ri.stdout or "{}")), **extra})
    return {
        "verified_by": VERIFIED_BY,
        "tool": tool,
        "sha": sha,
        "by_severity": _by_severity(all_vulns),
        "total": len(all_vulns),
        "targets": targets,
        "images": imgs,
        "errors": errors,
    }


def counts_only(ev: dict[str, Any]) -> dict[str, Any]:
    """Bản của `evidence.vuln` cho audit-log: image chỉ giữ số đếm, danh sách CVE đi trong `review-results`."""
    imgs = ev.get("images")
    if not isinstance(imgs, list):
        return ev
    return {**ev, "images": [{k: v for k, v in i.items() if k != "findings"} for i in imgs]}


def secret_evidence(root: Path, sha: str) -> dict[str, Any]:
    """`evidence.secrets` của cây RC `root`: gitleaks trên toàn bộ lịch sử git, chỉ vị trí lên bus."""
    t = _tool("gitleaks", "cài gitleaks/gitleaks (một binary) để có quét secret cho release-check")
    if isinstance(t, str):
        return unverified(t)
    exe, tool = t
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "gitleaks.json"
        r = _exec([exe, *GITLEAKS, "--report-path", str(report), str(root)])
        if isinstance(r, str):
            return {**unverified(r), "tool": tool}
        if r.returncode != 0:
            return {**unverified(f"gitleaks thoát {r.returncode}: {_tail(r.stderr)}"), "tool": tool}
        leaks = json.loads(report.read_text(encoding="utf-8") or "[]") if report.exists() else []
    m = _SCANNED.search(r.stderr)
    findings = [
        {
            "rule": x.get("RuleID"),
            "file": x.get("File"),
            "commit": str(x.get("Commit") or "")[:7],
            "line": x.get("StartLine"),
        }
        for x in leaks
    ]
    return {
        "verified_by": VERIFIED_BY,
        "tool": tool,
        "sha": sha,
        "commits_scanned": int(m.group(1)) if m else None,
        "total": len(findings),
        "findings": findings,
    }
