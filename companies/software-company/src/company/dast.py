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

import yaml

from .smoke import _LOOPBACK, VERIFIED_BY, Runtime, free_port, parse_runtime, run_smoke, unverified

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
            return {"path": str(path), "operation_id": oid, "fields": fields}, f"POST {path} ({oid}) trong api-contract"
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
    if op is None:
        login = {"skipped": why}
        notes.append(f"không thử cửa đăng nhập: {why}")
    else:

        def burst(same: bool) -> dict[str, Any]:
            user, statuses, retry_after = _rand(), [], False
            for _ in range(BURST):
                u = user if same else _rand()
                body = {
                    f: (secrets.token_urlsafe(12) if f == "password" else f"{u}@dast.invalid" if fmt == "email" else u)
                    for f, fmt in op["fields"].items()
                }
                s, h, _ = call(op["path"], "POST", json.dumps(body).encode())
                if s is None:
                    break
                statuses.append(s)
                retry_after = retry_after or h.get("Retry-After") is not None
            return {
                "attempts": len(statuses),
                "statuses": statuses,
                "limited": bool({423, 429} & set(statuses)) or retry_after,
            }

        login = {**op, "distinct_usernames": burst(False), "same_username": burst(True)}
        st, _, text = call(op["path"], "POST", b"{")
        login["malformed_body"] = {"status": st, "debug_markers": _markers(text)}
        d = login["distinct_usernames"]
        if not d["limited"] and 401 in d["statuses"]:
            issues.append(
                f"{d['attempts']} lần đăng nhập sai liên tiếp từ một nguồn (mỗi lần một username) không bị "
                f"giới hạn — không có 429/Retry-After ở POST {op['path']}"
            )
        if (st or 0) >= 500 or login["malformed_body"]["debug_markers"]:
            issues.append(
                f"thân JSON hỏng ở POST {op['path']} → HTTP {st}, dấu vết debug: "
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


def evidence(root: Path, spec: dict[str, Any] | None, sandbox: Any, contract: str | None, sha: str) -> dict[str, Any]:
    """Bằng chứng `evidence.dast` của cây RC `root` (ADR-0047 §1, §4)."""
    rt = parse_runtime(spec)
    if rt is None:
        return unverified("spec không khai `runtime` (lệnh khởi động, cổng, đường health) — không có gì để quét")
    if rt.deploy:
        return unverified(
            "spec khai `runtime.deploy` (ADR-0041): sản phẩm cần môi trường dựng riêng, lệnh trần không "
            "đại diện — DAST trên môi trường đó chưa làm"
        )
    return {**run_dast(root, rt, sandbox, contract), "sha": sha}
