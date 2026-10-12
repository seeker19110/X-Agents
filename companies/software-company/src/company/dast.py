"""ADR-0047: DAST tối thiểu do orchestrator chạy trên đúng cây RC — bằng chứng quét động, không phải lời khai.

Khởi động sản phẩm theo `runtime` của spec (cùng đường `run_smoke`, ADR-0029/0035), rồi khi nó đang chạy chỉ gửi
request tới `127.0.0.1` của chính tiến trình đó: header bảo mật, trang lỗi lộ debug, cookie, và cửa đăng nhập LẤY TỪ
`api-contract` (OpenAPI) của dự án — thử sai liên tiếp để đo giới hạn. Kết quả là sự thật đo được (`checks`), các
sự thật thường thành finding (`issues`, câu trung tính, không gắn mức) và điều máy không đo được (`notes`). Không
kết luận chặn hay không: đó là việc của security và người ký (ADR-0046 §3).
"""

from __future__ import annotations

import http.client
import json
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import replace
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .deploy import deploy_thay_smoke
from .smoke import _LOOPBACK, VERIFIED_BY, Runtime, free_port, parse_runtime, run_smoke, unverified
from .smoke import _probe as http_probe  # cùng probe với smoke/deploy: "đang chạy" đo bằng một thước

BURST = 12  # vượt ngưỡng 10 lần/15 phút thường gặp (CAMPUS-UNI NFR-009)
TIMEOUT_S = 5
SECURITY_HEADERS = ("X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy", "Referrer-Policy")
LEAK_HEADERS = ("Server", "X-Powered-By")
DEBUG_MARKERS = ("Traceback (most recent call last)", "DEBUG = True", "Werkzeug Debugger")
NOTE_TLS = "HTTP loopback: không kiểm HSTS, cờ Secure, TLS"
NOTE_ACCOUNT = "username ngẫu nhiên, không tồn tại: không đo được khoá tài khoản có thật (xem test của sản phẩm)"
NOTE_SESSION = "máy không có tài khoản nên không đăng nhập thành công: cookie phiên sau đăng nhập chưa quan sát được"
OAS_SECURITY = "security"  # khoá Security Requirement của OpenAPI, không phải agent

Resp = tuple[int | None, Message, str]


CONTRACT_GLOBS = ("openapi*.yaml", "openapi*.yml", "openapi*.json", "swagger*.yaml", "swagger*.yml", "swagger*.json")
CONTRACT_SKIP = frozenset({".git", "node_modules", ".venv", "venv", "dist", "build", "vendor", "site-packages", ".tox"})
CONTRACT_MAX_BYTES = 2_000_000


def _openapi_doc(text: str) -> dict[str, Any] | None:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    ok = isinstance(doc, dict) and isinstance(doc.get("paths"), dict) and ("openapi" in doc or "swagger" in doc)
    return doc if ok else None


def contract_in_tree(root: Path) -> tuple[str, str] | None:
    """OpenAPI trong cây RC: `(toàn văn, đường dẫn tương đối)` của file có nhiều `paths` nhất ngoài thư mục rác; None khi
    không có. Bản trong repo là bản sống (CI của khách canh nó), bản `api-contract` trên blackboard từ pha plan có thể
    đã cũ — đo được 2026-10-13: blackboard khai `/auth/session`, repo khai `/auth/login` và cấm `createSession`."""
    best: tuple[int, int, str, str] | None = None
    for g in CONTRACT_GLOBS:
        for f in root.rglob(g):
            rel = f.relative_to(root)
            if CONTRACT_SKIP & set(rel.parts[:-1]) or not f.is_file() or f.stat().st_size > CONTRACT_MAX_BYTES:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            doc = _openapi_doc(text)
            if doc is None:
                continue
            key = (-len(doc["paths"]), len(rel.as_posix()), rel.as_posix(), text)
            if best is None or key < best:
                best = key
    return (best[3], best[2]) if best else None


def _base_paths(doc: dict[str, Any]) -> list[str]:
    """Tiền tố đường dẫn khai ở `servers[].url` (không phải dò đường: contract tự khai)."""
    out: list[str] = []
    for srv in doc.get("servers") or []:
        url = srv.get("url") if isinstance(srv, dict) else None
        base = urlparse(str(url)).path.rstrip("/") if url else ""
        if base and base not in out:
            out.append(base)
    return out


def _deref(doc: dict[str, Any], node: Any) -> Any:
    """Theo `$ref` nội bộ (`#/components/...`) tới node thật; hỏng thì None."""
    for _ in range(10):
        if not (isinstance(node, dict) and isinstance(node.get("$ref"), str)):
            return node
        cur: Any = doc
        for part in node["$ref"].removeprefix("#/").split("/"):
            cur = cur.get(part) if isinstance(cur, dict) else None
        node = cur
    return None


def _login_fields(doc: dict[str, Any], op: dict[str, Any]) -> dict[str, str] | None:
    """Trường gửi được của thân JSON: có `password`, mọi trường bắt buộc là chuỗi. Giá trị là `format` khai."""
    body = _deref(doc, op.get("requestBody")) or {}
    media = ((body.get("content") or {}).get("application/json") or {}) if isinstance(body, dict) else {}
    schema = _deref(doc, media.get("schema"))
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or "password" not in props:
        return None
    fields = {}
    for name in dict.fromkeys([*[str(x) for x in schema.get("required") or props], "password"]):
        prop = _deref(doc, props.get(name)) or {}
        if prop.get("type", "string") != "string":
            return None
        fields[name] = str(prop.get("format") or "")
    return fields


def login_op(contract: str | None) -> tuple[dict[str, Any] | None, str]:
    """Operation đăng nhập khai trong `api-contract`: POST công khai (`security: []`, hoặc không khai ở cả op lẫn
    gốc), không path param, thân JSON có `password`, khai phản hồi 401. Không có → (None, lý do). Không dò đường."""
    if not contract:
        return None, "dự án không có api-contract"
    try:
        doc = yaml.safe_load(contract)
    except yaml.YAMLError as e:
        return None, f"api-contract không phải YAML/JSON hợp lệ: {e}"[:200]
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        return None, "api-contract không có `paths` (không phải OpenAPI)"
    for path, item in doc["paths"].items():
        op = item.get("post") if isinstance(item, dict) else None
        if not isinstance(op, dict) or "{" in str(path) or op.get(OAS_SECURITY, doc.get(OAS_SECURITY)):
            continue
        if "401" not in {str(k) for k in op.get("responses") or {}}:
            continue
        fields = _login_fields(doc, op)
        if fields is not None:
            oid = op.get("operationId")
            paths = [str(path), *(b + str(path) for b in _base_paths(doc) if not str(path).startswith(b + "/"))]
            paths = list(dict.fromkeys(paths))
            return {
                "path": paths[0],
                "paths": paths,
                "operation_id": oid,
                "fields": fields,
            }, f"POST {path} ({oid}) trong api-contract"
    return None, "api-contract không khai operation đăng nhập (POST công khai, thân JSON có `password`, khai 401)"


def _req(url: str, method: str = "GET", body: bytes | None = None) -> Resp:
    """Một request tới sản phẩm; không ném — sản phẩm chết giữa chừng là (None, header rỗng, "")."""
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _LOOPBACK.open(req, timeout=TIMEOUT_S) as r:
            return int(r.status), r.headers, r.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return int(e.code), e.headers, e.read(4096).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return None, Message(), ""


def _markers(text: str) -> list[str]:
    return [m for m in DEBUG_MARKERS if m in text]


def _rand() -> str:
    return f"dast-{secrets.token_hex(4)}"


def scan(base: str, health: str, contract: str | None) -> dict[str, Any]:
    """Đo trên sản phẩm ĐANG chạy ở `base`. Trả `checks`/`issues`/`notes` (ADR-0047 §1)."""
    jar: dict[str, dict[str, Any]] = {}

    def call(path: str, method: str = "GET", body: bytes | None = None) -> Resp:
        st, h, text = _req(base + path, method, body)
        for c in h.get_all("Set-Cookie") or []:
            name, _, rest = c.partition("=")
            attrs = [a.strip().lower() for a in rest.split(";")[1:]]
            same = next((a.split("=", 1)[1] for a in attrs if a.startswith("samesite=")), None)
            jar[name.strip()] = {
                "name": name.strip(),
                "httponly": "httponly" in attrs,
                "secure": "secure" in attrs,
                "samesite": same,
            }
        return st, h, text

    issues: list[str] = []
    pages: dict[str, Any] = {}
    for path in dict.fromkeys(["/", health]):
        st, h, _ = call(path)
        missing = [x for x in SECURITY_HEADERS if h.get(x) is None] if st is not None else []
        leaks = {x: str(h[x]) for x in LEAK_HEADERS if h.get(x) is not None and re.search(r"\d", str(h[x]))}
        pages[path] = {"status": st, "missing_headers": missing, "leaks": leaks}
        issues += [f"thiếu header {x} ở GET {path}" for x in missing]
        issues += [f"header {k}: {v} lộ phiên bản ở GET {path}" for k, v in leaks.items()]
    probe = f"/__dast-{secrets.token_hex(4)}"
    st, _, text = call(probe)
    markers = _markers(text)
    error_page = {"path": probe, "status": st, "debug_markers": markers}
    if markers:
        issues.append(f"trang lỗi GET {probe} lộ dấu vết debug: {', '.join(markers)}")

    notes = [NOTE_TLS]
    op, why = login_op(contract)
    login: dict[str, Any]
    chua_mount = (
        f"cửa đăng nhập khai trong contract chưa được mount ở sản phẩm đang chạy (POST {', '.join(op['paths'])} đều 404)"
        if op is not None
        else ""
    )
    if op is not None and len(op["paths"]) > 1:
        # nhiều đường khai (gốc rồi `servers[].url` + đường): cửa thật = đường đầu tiên không trả 404, dò bằng một POST
        # `{}` mỗi đường (tốn một lượt hạn mức trên cửa thật). Một đường thì burst tự nói: toàn 404 = chưa mount.
        door = next((c for c in op["paths"] if call(c, "POST", b"{}")[0] != 404), None)
        op = {**op, "path": door} if door else {**op, "skipped": chua_mount}
    if op is None:
        login = {"skipped": why}
        notes.append(f"không thử cửa đăng nhập: {why}")
    elif "skipped" in op:
        login = op
        notes.append(f"không thử cửa đăng nhập: {chua_mount}")
    else:
        door_op: dict[str, Any] = op

        def burst(same: bool) -> dict[str, Any]:
            user, statuses, retry_after = _rand(), [], False
            for _ in range(BURST):
                u = user if same else _rand()
                body = {
                    f: (secrets.token_urlsafe(12) if f == "password" else f"{u}@dast.invalid" if fmt == "email" else u)
                    for f, fmt in door_op["fields"].items()
                }
                s, h, _ = call(door_op["path"], "POST", json.dumps(body).encode())
                if s is None:
                    break
                statuses.append(s)
                retry_after = retry_after or h.get("Retry-After") is not None
            return {
                "attempts": len(statuses),
                "statuses": statuses,
                "limited": bool({423, 429} & set(statuses)) or retry_after,
            }

        login = {**door_op, "distinct_usernames": burst(False), "same_username": burst(True)}
        d = login["distinct_usernames"]
        if d["statuses"] and set(d["statuses"]) == {404}:
            # đo hub 2026-10-13 (REL-021): 24/24 POST trả 404 — nói đúng "chưa mount" thay vì 24 con số
            login = {**door_op, "skipped": chua_mount}
            notes.append(f"không thử cửa đăng nhập: {chua_mount}")
    if "distinct_usernames" in login:
        st, _, text = call(login["path"], "POST", b"{")
        login["malformed_body"] = {"status": st, "debug_markers": _markers(text)}
        d = login["distinct_usernames"]
        if not d["limited"] and 401 in d["statuses"]:
            issues.append(
                f"{d['attempts']} lần đăng nhập sai liên tiếp từ một nguồn (mỗi lần một username) không bị "
                f"giới hạn — không có 429/Retry-After ở POST {login['path']}"
            )
        if (st or 0) >= 500 or login["malformed_body"]["debug_markers"]:
            issues.append(
                f"thân JSON hỏng ở POST {login['path']} → HTTP {st}, dấu vết debug: "
                f"{login['malformed_body']['debug_markers']}"
            )
        notes += [NOTE_ACCOUNT, NOTE_SESSION]
    cookies = sorted(jar.values(), key=lambda c: str(c["name"]))
    issues += [f"cookie {c['name']} không có SameSite" for c in cookies if c["samesite"] is None]
    checks = {"pages": pages, "error_page": error_page, "login": login, "cookies": cookies}
    return {"checks": checks, "issues": issues, "notes": notes}


def run_dast(root: Path, rt: Runtime, sandbox: Any, contract: str | None) -> dict[str, Any]:
    """Khởi động sản phẩm (cổng trống nếu lệnh có `{port}`: không tranh với smoke staging/QA của cùng RC), quét khi
    nó vừa trả lời health, rồi giết. Không lên → `unverified` kèm bằng chứng smoke."""
    if any("{port}" in a for a in rt.command):
        rt = replace(rt, port=free_port())
    found: dict[str, Any] = {}
    smoke = run_smoke(root, rt, sandbox=sandbox, probe=lambda base: found.update(scan(base, rt.path, contract)))
    if not found:
        why = smoke.get("error") or f"http_status={smoke.get('http_status')} exit_code={smoke.get('exit_code')}"
        keep = ("command", "http_status", "exit_code", "error", "stderr_tail", "sandbox")
        return {**unverified(f"sản phẩm không lên để quét: {why}"), "smoke": {k: smoke[k] for k in keep if k in smoke}}
    return {
        "verified_by": VERIFIED_BY,
        "base_url": f"http://127.0.0.1:{smoke['port']}",
        "command": smoke["command"],
        "sandbox": smoke["sandbox"],
        **found,
    }


def deploy_of(evidence: Any) -> dict[str, Any] | None:
    """`evidence.deploy` (bản ghi `DeployRecord.record()`) trong `release-events.payload.evidence`; None khi chưa deploy
    (ADR-0039) hay payload không phải dict. Ở đây chứ không ở `orch/` để `verify.py` không thêm `dict[str, Any]`."""
    rec = evidence.get("deploy") if isinstance(evidence, dict) else None
    return rec if isinstance(rec, dict) and rec else None


def deploy_ref(deployed: dict[str, Any]) -> dict[str, Any]:
    """Phần của `release-events.evidence.deploy` nói quét/đo CÁI GÌ — không chép lại smoke của lần deploy."""
    return {k: deployed[k] for k in ("project", "env", "container_ids", "started_at") if k in deployed}


def scan_deployed(rt: Runtime, deployed: dict[str, Any], contract: str | None) -> dict[str, Any]:
    """Quét môi trường `deploy()` ĐÃ dựng (ADR-0039/0053): không khởi động, không giết gì — probe health trên cổng đã
    map của chính RC rồi `scan`. `deployed` là `release-events.evidence.deploy` (ba hình của `DeployRecord`: chỉ
    `ok=True` là có gì để quét; container có thể đã bị RC sau thay nên vẫn phải probe lại ngay lúc quét)."""
    ref = deploy_ref(deployed)
    if not deployed.get("ok") or not deployed.get("port"):
        why = deployed.get("error") or deployed.get("skipped") or "không có cổng"
        return {
            **unverified(
                f"bằng chứng deploy staging không phải 'đang chạy' (ok={deployed.get('ok')}: {why}) "
                "— không có gì để quét"
            ),
            "deploy": ref,
        }
    base = f"http://127.0.0.1:{deployed['port']}"
    st = http_probe(base + rt.path)
    if st != rt.expect_status:
        return {
            **unverified(
                f"môi trường deploy không trả lời {base}{rt.path} (http_status={st}, chờ "
                f"{rt.expect_status}) — container có thể đã bị RC sau thay"
            ),
            "deploy": ref,
        }
    return {"verified_by": VERIFIED_BY, "base_url": base, "deploy": ref, **scan(base, rt.path, contract)}


def evidence(
    root: Path,
    spec: dict[str, Any] | None,
    sandbox: Any,
    contract: str | None,
    sha: str,
    deployed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bằng chứng `evidence.dast` của cây RC `root` (ADR-0047 §1, §4). Spec cần `deploy()` (ADR-0039/0053) thì quét
    môi trường staging đã dựng — `deployed` là `evidence.deploy` của release-events cùng RC — thay vì lệnh trần."""
    rt = parse_runtime(spec)
    if rt is None:
        return unverified("spec không khai `runtime` (lệnh khởi động, cổng, đường health) — không có gì để quét")
    tree = contract_in_tree(root)
    source: str | None = "blackboard:api-contract" if contract else None
    if tree is not None:
        contract, source = tree[0], f"repo:{tree[1]}"
    if why := deploy_thay_smoke(rt, root):
        if deployed is None:
            return unverified(f"{why}; chưa có `evidence.deploy` của staging cho RC này — chưa quét được")
        return {**scan_deployed(rt, deployed, contract), "contract_source": source, "sha": sha}
    return {**run_dast(root, rt, sandbox, contract), "contract_source": source, "sha": sha}
