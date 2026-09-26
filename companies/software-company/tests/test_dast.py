"""ADR-0047: DAST tối thiểu do orchestrator chạy trên đúng cây RC trước release-check của security.

Đo được 2026-09-26 (CAMPUS-UNI REL-007): security chặn vì "không có kết quả DAST ... cần bằng chứng quét động
(rate-limit đăng nhập, khoá tài khoản, cookie session HttpOnly/SameSite)" — và không có đường nào đưa số tới nó.
Test chạy sản phẩm THẬT (server HTTP con), không giả phản hồi."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from company.dast import BURST, evidence, login_op, run_dast, scan
from company.smoke import Runtime, run_smoke

# Sản phẩm mẫu hai chế độ: `kin` (làm đúng) và `ho` (hở). Chạy được cả trong tiến trình test lẫn làm tiến trình con.
APP = r"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make(mode):
    tries = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def version_string(self):
            return "waitress" if mode == "kin" else "Foo/1.2.3"

        def _send(self, code, body=b"", headers=()):
            self.send_response(code)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _sec(self):
            if mode == "kin":
                return [("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                        ("Content-Security-Policy", "default-src 'self'"), ("Referrer-Policy", "same-origin")]
            return [("X-Powered-By", "Express 4.18.2")]

        def do_GET(self):
            if self.path in ("/", "/healthz"):
                return self._send(200, b"ok", [*self._sec(), ("Set-Cookie", "csrftoken=abc; Path=/; SameSite=Lax"),
                                               ("Set-Cookie", "theo_doi=1; Path=/")])
            body = b"Not found" if mode == "kin" else b"Traceback (most recent call last):\n  File app.py"
            return self._send(404, body, self._sec())

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path != "/api/v1/auth/session":
                return self._send(404)
            try:
                data = json.loads(raw)
            except ValueError:
                if mode == "kin":
                    return self._send(400, b"bad")
                return self._send(500, b"Traceback (most recent call last):")
            if "email" in data and "@" not in data["email"]:
                return self._send(400, b"email")
            if mode == "kin":
                ip = self.client_address[0]
                tries[ip] = tries.get(ip, 0) + 1
                if tries[ip] > 5:
                    return self._send(429, b"", [("Retry-After", "60")])
            return self._send(401, json.dumps({"detail": "sai"}).encode(), self._sec())

    return H


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), make(sys.argv[2])).serve_forever()
"""

CONTRACT = """
openapi: 3.0.3
info: {title: campus, version: '1'}
security: [{session: []}]
paths:
  /api/v1/auth/password:
    post:
      operationId: changePassword
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/ChangePassword'}
      responses: {'204': {description: ok}, '401': {description: sai}}
  /api/v1/auth/session:
    post:
      operationId: createSession
      security: []
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/LoginRequest'}
      responses: {'201': {description: ok}, '401': {description: sai}, '429': {description: chậm}}
components:
  schemas:
    LoginRequest:
      type: object
      required: [username, password]
      properties:
        username: {type: string}
        password: {type: string, format: password}
    ChangePassword:
      type: object
      properties:
        current_password: {type: string}
        password: {type: string}
"""


class _DongNgay(BaseHTTPRequestHandler):
    """Nhận kết nối rồi đóng, không trả gì: sản phẩm chết giữa chừng (nhanh hơn cổng đóng trên Windows)."""

    def handle(self) -> None:
        pass


def _handler(mode: str):
    if mode == "dong":
        return _DongNgay
    ns: dict = {"__name__": "app_mau"}
    exec(APP, ns)  # cùng mã với tiến trình con, chạy trong tiến trình test cho nhanh
    return ns["make"](mode)


@pytest.fixture
def app():
    servers = []

    def start(mode: str) -> str:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(mode))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


# ---------- login_op: cửa đăng nhập lấy từ api-contract, không dò đường ----------


def test_login_op_doc_tu_api_contract():
    op, why = login_op(CONTRACT)
    assert op == {
        "path": "/api/v1/auth/session",
        "operation_id": "createSession",
        "fields": {"password": "password", "username": ""},
    }, "changePassword cần phiên (security gốc) nên không phải cửa đăng nhập"
    assert "createSession" in why


@pytest.mark.parametrize(
    ("contract", "trong_ly_do"),
    [
        (None, "không có api-contract"),
        ("paths: [", "YAML"),
        ("openapi: 3.0.3\n", "`paths`"),
        (CONTRACT.replace("      security: []\n", ""), "không khai operation đăng nhập"),
        (CONTRACT.replace(", '401': {description: sai}, '429'", ", '429'"), "không khai operation đăng nhập"),
        (CONTRACT.replace("/api/v1/auth/session:", "/api/v1/{tenant}/session:"), "không khai operation đăng nhập"),
        (CONTRACT.replace("username: {type: string}", "username: {type: integer}"), "không khai operation"),
        (CONTRACT.replace("password: {type: string, format: password}", "mat_khau: {type: string}"), "không khai"),
    ],
)
def test_login_op_khong_du_dieu_kien_thi_noi_ly_do(contract, trong_ly_do):
    op, why = login_op(contract)
    assert op is None and trong_ly_do in why


def test_login_op_khong_co_security_goc_va_required_thi_lay_moi_thuoc_tinh():
    c = CONTRACT.replace("security: [{session: []}]\n", "").replace("      required: [username, password]\n", "")
    c = c.replace("username: {type: string}", "email: {type: string, format: email}")
    op, _ = login_op(c)
    assert op is not None and op["path"] == "/api/v1/auth/password", (
        "không có security gốc: mọi op không khai đều công khai"
    )
    assert op["fields"] == {"current_password": "", "password": ""}
    op2, _ = login_op(c.replace("  /api/v1/auth/password:\n    post:", "  /api/v1/auth/password:\n    get:"))
    assert op2 is not None and op2["fields"] == {"email": "email", "password": "password"}


def test_login_op_request_body_la_ref():
    c = CONTRACT.replace(
        """      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/LoginRequest'}""",
        "      requestBody: {$ref: '#/components/requestBodies/Login'}",
    ).replace(
        "components:\n",
        "components:\n  requestBodies:\n    Login:\n      content:\n        application/json:\n"
        "          schema: {$ref: '#/components/schemas/LoginRequest'}\n",
    )
    op, _ = login_op(c)
    assert op is not None and op["operation_id"] == "createSession"


def test_login_op_ref_vong_khong_treo():
    c = CONTRACT.replace("schema: {$ref: '#/components/schemas/LoginRequest'}", "schema: {$ref: '#/components/x'}")
    c = c.replace("components:\n", "components:\n  x: {$ref: '#/components/x'}\n")
    op, why = login_op(c)
    assert op is None and "không khai operation đăng nhập" in why


# ---------- scan: đo trên sản phẩm đang chạy ----------


def test_scan_san_pham_lam_dung(app):
    base = app("kin")
    r = scan(base, "/healthz", CONTRACT)
    c = r["checks"]
    assert c["pages"]["/"] == {"status": 200, "missing_headers": [], "leaks": {}}
    assert c["error_page"]["status"] == 404 and c["error_page"]["debug_markers"] == []
    lg = c["login"]
    assert lg["operation_id"] == "createSession"
    assert lg["distinct_usernames"]["limited"] is True and 429 in lg["distinct_usernames"]["statuses"]
    assert lg["distinct_usernames"]["statuses"][:5] == [401] * 5, "sai 5 lần đầu là 401 thật, không phải lỗi thân"
    assert lg["same_username"]["limited"] is True
    assert lg["malformed_body"] == {"status": 400, "debug_markers": []}
    assert {"name": "csrftoken", "httponly": False, "secure": False, "samesite": "lax"} in c["cookies"]
    assert r["issues"] == ["cookie theo_doi không có SameSite"]
    assert any("khoá tài khoản có thật" in n for n in r["notes"]) and any("HSTS" in n for n in r["notes"])


def test_scan_san_pham_ho(app):
    base = app("ho")
    r = scan(base, "/", CONTRACT)
    c = r["checks"]
    assert list(c["pages"]) == ["/"], "health trùng `/` thì đo một lần"
    assert c["pages"]["/"]["missing_headers"] == [
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Content-Security-Policy",
        "Referrer-Policy",
    ]
    assert c["pages"]["/"]["leaks"] == {
        "Server": "Foo/1.2.3",
        "X-Powered-By": "Express 4.18.2",
    }
    assert c["error_page"]["debug_markers"] == ["Traceback (most recent call last)"]
    lg = c["login"]
    assert lg["distinct_usernames"] == {"attempts": BURST, "statuses": [401] * BURST, "limited": False}
    assert lg["malformed_body"]["status"] == 500
    issues = "\n".join(r["issues"])
    assert "thiếu header X-Content-Type-Options ở GET /" in issues
    assert "Server" in issues and "X-Powered-By" in issues
    assert "lộ dấu vết debug" in issues
    assert f"{BURST} lần đăng nhập sai liên tiếp" in issues and "/api/v1/auth/session" in issues
    assert "thân JSON hỏng" in issues


def test_scan_khong_co_cua_dang_nhap_thi_ghi_skipped(app):
    r = scan(app("kin"), "/healthz", None)
    assert r["checks"]["login"] == {"skipped": "dự án không có api-contract"}
    assert any("không thử cửa đăng nhập" in n for n in r["notes"])


def test_scan_truong_email_gui_email_hop_le(app):
    c = CONTRACT.replace("username: {type: string}", "email: {type: string, format: email}")
    c = c.replace("required: [username, password]", "required: [email, password]")
    lg = scan(app("ho"), "/", c)["checks"]["login"]
    assert lg["fields"] == {"email": "email", "password": "password"}
    assert lg["distinct_usernames"]["statuses"] == [401] * BURST, "sản phẩm trả 400 nếu email sai định dạng"


def test_scan_san_pham_chet_giua_chung_khong_nem(app):
    r = scan(app("dong"), "/", CONTRACT)
    assert r["checks"]["pages"]["/"]["status"] is None
    assert r["checks"]["login"]["distinct_usernames"]["attempts"] == 0


# ---------- run_smoke(probe=...) + run_dast + evidence: sản phẩm là tiến trình con ----------


def _rt(tmp_path: Path, mode: str = "kin", port: int = 0) -> Runtime:
    (tmp_path / "app.py").write_text(APP, encoding="utf-8")
    return Runtime((sys.executable, str(tmp_path / "app.py"), "{port}", mode), port=port, path="/healthz", timeout_s=20)


def test_run_smoke_goi_probe_khi_san_pham_len(tmp_path):
    seen: list[str] = []
    r = run_smoke(tmp_path, _rt(tmp_path), probe=seen.append)
    assert r["ok"] is True and seen == [f"http://127.0.0.1:{r['port']}"]
    dead = run_smoke(tmp_path, Runtime((sys.executable, "-c", "raise SystemExit(3)"), timeout_s=5), probe=seen.append)
    assert dead["ok"] is False and len(seen) == 1, "không lên thì không quét"


def test_run_dast_chay_tren_cong_trong_khong_tranh_cong_cua_spec(tmp_path):
    ev = run_dast(tmp_path, _rt(tmp_path, port=8000), None, CONTRACT)
    assert ev["verified_by"] == "orchestrator" and not ev["base_url"].endswith(":8000")
    assert ev["checks"]["login"]["distinct_usernames"]["limited"] is True
    assert ev["command"][-2] != "{port}" and ev["sandbox"]


def test_run_dast_san_pham_khong_len_thi_unverified_kem_smoke(tmp_path):
    rt = Runtime((sys.executable, "-c", "import sys;sys.stderr.write('thiếu DATABASE_URL');sys.exit(3)"), timeout_s=5)
    ev = run_dast(tmp_path, rt, None, CONTRACT)
    assert ev["unverified"] is True and "không lên" in ev["reason"] and "exit_code=3" in ev["reason"]
    assert ev["smoke"]["exit_code"] == 3 and "DATABASE_URL" in ev["smoke"]["stderr_tail"]
    to = run_dast(tmp_path, Runtime((sys.executable, "-c", "import time;time.sleep(30)"), timeout_s=1), None, None)
    assert to["unverified"] is True and "không trả lời" in to["reason"]


def test_evidence_theo_runtime_cua_spec(tmp_path):
    rt = _rt(tmp_path)
    spec = {"runtime": {"command": list(rt.command), "health": "/healthz", "timeout_s": 20}}
    ev = evidence(tmp_path, spec, None, CONTRACT, sha="abc1234")
    assert ev["sha"] == "abc1234" and ev["checks"]["login"]["operation_id"] == "createSession"
    none = evidence(tmp_path, {"kind": "library"}, None, CONTRACT, sha="s")
    assert none["unverified"] is True and "runtime" in none["reason"]
    dep = evidence(tmp_path, {"runtime": {**spec["runtime"], "deploy": "compose.yml"}}, None, CONTRACT, sha="s")
    assert dep["unverified"] is True and "runtime.deploy" in dep["reason"]
    assert json.loads(json.dumps(ev)) == ev, "bằng chứng đi trên bus: phải là JSON"


# ---------- orchestrator: evidence.dast trước release-check của security ----------


def _orch_rc(tmp_path: Path, monkeypatch, h=None, runtime: dict | None = None):
    from test_orchestrator import handler
    from test_supply_chain import _fake_licenses, _orch, _repo

    _fake_licenses(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), h or handler)
    if runtime is not None:
        spec = bus.latest("approved-specs", "P")
        bus.publish(spec.model_copy(update={"event_id": "spec-2", "payload": {**spec.payload, "runtime": runtime}}))
    return bus, orch


def _sec(bus) -> dict:
    return [e.payload for e in bus.replay(topic="review-results") if e.payload.get("source") == "security"][-1]


def _audits(bus, action: str) -> list[dict]:
    return [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == action]


def test_security_thay_evidence_dast_khong_runtime_thi_unverified(tmp_path, monkeypatch):
    from test_orchestrator import _agent_of, _inp, handler

    seen: list[dict] = []

    def h(system, user):
        if _agent_of(system) == "security":
            seen.append(_inp(user))
        return handler(system, user)

    bus, orch = _orch_rc(tmp_path, monkeypatch, h)
    orch.run()
    assert seen and seen[-1]["evidence"]["dast"]["unverified"] is True, "security nhìn thấy lý do máy không quét"
    assert "runtime" in _sec(bus)["evidence"]["dast"]["reason"]
    runs = _audits(bus, "dast.run")
    assert runs and runs[-1]["unverified"] is True


def test_dast_quet_dung_cay_rc_voi_contract_tu_blackboard(tmp_path, monkeypatch):
    import company.dast as dast

    calls: list[tuple] = []

    def fake(root, rt, sandbox, contract):
        calls.append((root, rt, contract))
        return {"verified_by": "orchestrator", "checks": {"login": {"skipped": "x"}}, "issues": ["i"], "notes": []}

    monkeypatch.setattr(dast, "run_dast", fake)
    bus, orch = _orch_rc(tmp_path, monkeypatch, runtime={"command": ["app", "{port}"], "health": "/healthz"})
    orch.blackboard.write("product", "api-contract", "openapi.yaml", "v1", content=CONTRACT, project_id="P")
    orch.run()
    ev = _sec(bus)["evidence"]["dast"]
    assert calls and calls[0][2] == CONTRACT and calls[0][1].path == "/healthz"
    assert ev["issues"] == ["i"] and calls[0][0].name == ev["sha"], "quét trên checkout ĐÚNG sha đã staged"


def test_loi_khai_dast_cua_model_bi_bo_dast_summary_giu(tmp_path, monkeypatch):
    from test_orchestrator import _agent_of, _inp, handler

    def h(system, user):
        out = handler(system, user)
        if _agent_of(system) == "security" and _inp(user).get("release_id"):
            out = {
                **out,
                "verdict": "block",
                "dast_summary": "lời đọc của security",
                "evidence": {"dast": {"issues": [], "verified_by": "security"}, "khac": "giữ"},
            }
        return out

    bus, orch = _orch_rc(tmp_path, monkeypatch, h)
    orch.run()
    sec = _sec(bus)
    assert sec["evidence"]["dast"]["unverified"] is True and sec["evidence"]["khac"] == "giữ"
    assert sec["dast_summary"] == "lời đọc của security" and sec["verdict"] == "block", "ADR-0047 §3"
    ignored = _audits(bus, "dast.claimed_ignored")
    assert ignored and ignored[-1]["claimed"] == {"issues": [], "verified_by": "security"}
