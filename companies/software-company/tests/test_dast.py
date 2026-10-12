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

from company.dast import BURST, contract_in_tree, deploy_of, evidence, login_op, run_dast, scan
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
        "paths": ["/api/v1/auth/session"],
        "operation_id": "createSession",
        "fields": {"password": "password", "username": ""},
    }, "changePassword cần phiên (security gốc) nên không phải cửa đăng nhập"
    assert "createSession" in why


def test_login_op_them_duong_theo_servers_cua_contract():
    """Đo hub 2026-10-13 (QLKH-DD-CSV): contract khai `servers: [{url: https://api…/v1}]` và `/auth/login`; devserver
    mount `/v1/auth/login`. Đường khai trong contract gồm cả tiền tố `servers[].url` — không phải dò đường (ADR-0047)."""
    c = CONTRACT.replace(
        "security: [{session: []}]\n",
        "security: [{session: []}]\nservers: [{url: https://api.x.vn/v1}, {url: /}, {url: 'http://h/api/v1/'}]\n",
    )
    op, _ = login_op(c)
    assert op is not None and op["paths"] == ["/api/v1/auth/session", "/v1/api/v1/auth/session"], (
        "gốc `/` không thêm gì; tiền tố đã có sẵn trong path thì không lặp; không trùng"
    )


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


def test_scan_chon_cua_dang_nhap_theo_servers_khi_duong_goc_404(app):
    """Contract khai `/auth/session` với `servers: [{url: /api/v1}]`; sản phẩm mount `/api/v1/auth/session` → thử
    đường gốc (404) rồi đường có tiền tố; burst chạy trên cửa thật, `login.path` ghi cửa đã chọn."""
    c = CONTRACT.replace("  /api/v1/auth/session:", "  /auth/session:").replace(
        "security: [{session: []}]\n", "security: [{session: []}]\nservers: [{url: /api/v1}]\n"
    )
    r = scan(app("kin"), "/healthz", c)
    login = r["checks"]["login"]
    assert login["path"] == "/api/v1/auth/session" and login["paths"] == ["/auth/session", "/api/v1/auth/session"]
    assert login["same_username"]["attempts"] == BURST and login["same_username"]["limited"] is True


def test_scan_moi_cua_dang_nhap_deu_404_thi_skipped_noi_ro_khong_burst(app):
    """Đo hub 2026-10-13 (REL-021): 24/24 POST trả 404 — cửa khai trong contract chưa được mount. Nói đúng điều đó
    thay vì 24 con số 404; không ghi thành lỗ hổng (sản phẩm chưa có cửa, không phải cửa hở)."""
    c = CONTRACT.replace("  /api/v1/auth/session:", "  /khong/co:")
    r = scan(app("kin"), "/healthz", c)
    login = r["checks"]["login"]
    assert "attempts" not in json.dumps(login) and "404" in login["skipped"] and "/khong/co" in login["skipped"]
    assert login["operation_id"] == "createSession" and not any("đăng nhập" in i for i in r["issues"])
    assert any("chưa được mount" in n for n in r["notes"])


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


def test_contract_in_tree_chon_openapi_trong_cay_rc_bo_thu_muc_rac(tmp_path):
    """Đo hub 2026-10-13 (QLKH-DD-CSV): DDCSV-01 đưa contract 1.5.0 vào repo (`api/QLKH/openapi.yaml`, có fitness test
    cấm `createSession`), còn bản `api-contract` trên blackboard từ pha plan vẫn khai `/auth/session` → DAST quét cửa
    sản phẩm không hề hứa. Contract trong cây RC là bản sống; blackboard chỉ là dự phòng."""

    assert contract_in_tree(tmp_path) is None
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "openapi.yaml").write_text(CONTRACT, encoding="utf-8")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "openapi.yaml").write_text(
        "openapi: 3.0.3\npaths:\n" + "".join(f"  /p{i}: {{}}\n" for i in range(20)), encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "openapi-old.json").write_text(
        json.dumps({"openapi": "3.0.0", "paths": {"/a": {}}}), encoding="utf-8"
    )
    (tmp_path / "openapi-hong.yaml").write_text("paths: [", encoding="utf-8")
    (tmp_path / "swagger.yaml").write_text("foo: 1\n", encoding="utf-8")
    text, rel = contract_in_tree(tmp_path)
    assert rel == "api/openapi.yaml" and text == CONTRACT, (
        "nhiều paths nhất ngoài thư mục rác; hỏng/không phải OpenAPI bỏ qua"
    )


def test_contract_in_tree_file_khong_doc_duoc_thi_bo_qua(tmp_path):
    (tmp_path / "openapi.yaml").write_bytes(b"openapi: 3.0.3\npaths: {\xff\xfe}\n")
    assert contract_in_tree(tmp_path) is None, "file không phải UTF-8 không làm hỏng lượt quét"


def test_scan_nhieu_duong_theo_servers_deu_404_thi_skipped_khong_burst(app):
    """Như REL-021 sau khi đọc contract trong repo: `/auth/login` và `/v1/auth/login` đều 404 — dò một POST mỗi đường
    rồi dừng, không bắn 24 lần vào cửa không tồn tại."""
    c = CONTRACT.replace("  /api/v1/auth/session:", "  /khong/co:").replace(
        "security: [{session: []}]\n", "security: [{session: []}]\nservers: [{url: /v9}]\n"
    )
    r = scan(app("kin"), "/healthz", c)
    login = r["checks"]["login"]
    assert login["paths"] == ["/khong/co", "/v9/khong/co"] and "/v9/khong/co" in login["skipped"]
    assert "distinct_usernames" not in login and any("chưa được mount" in n for n in r["notes"])


def test_evidence_uu_tien_contract_trong_cay_rc_va_ghi_nguon(tmp_path):
    rt = _rt(tmp_path)
    spec = {"runtime": {"command": list(rt.command), "health": "/healthz", "timeout_s": 20}}
    bb = CONTRACT.replace("operationId: createSession", "operationId: taoPhienCu")
    ev = evidence(tmp_path, spec, None, bb, sha="s")
    assert ev["checks"]["login"]["operation_id"] == "taoPhienCu" and ev["contract_source"] == "blackboard:api-contract"
    (tmp_path / "openapi.yaml").write_text(CONTRACT, encoding="utf-8")
    ev = evidence(tmp_path, spec, None, bb, sha="s")
    assert ev["checks"]["login"]["operation_id"] == "createSession" and ev["contract_source"] == "repo:openapi.yaml"
    (tmp_path / "openapi.yaml").unlink()
    assert evidence(tmp_path, spec, None, None, sha="s")["contract_source"] is None


def test_evidence_quet_moi_truong_deploy_dang_chay_khi_spec_can_deploy(tmp_path, app):
    """Spec cần `deploy()` (`runtime.deploy` ADR-0039, hay dependencies + compose ADR-0053) thì DAST quét môi trường
    staging ĐÃ dựng — `release-events.evidence.deploy` của chính RC — không dựng lại bằng lệnh trần. Đo hub thật
    2026-10-12 (QLKH-DD-CSV REL-021): compose lên, smoke 200, nhưng DAST `unverified` → security chặn release."""
    base = app("kin")
    rec = {
        "ok": True,
        "port": int(base.rsplit(":", 1)[1]),
        "project": "company-p-staging",
        "env": "staging",
        "container_ids": ["c1", "c2"],
        "started_at": "2026-10-12T16:58:01+00:00",
        "smoke": {"ok": True},
        "compose_file": "compose.yml",
    }
    spec = {"runtime": {"command": ["app"], "health": "/healthz", "deploy": "compose.yml"}}
    ev = evidence(tmp_path, spec, None, CONTRACT, sha="abc", deployed=rec)
    assert ev["verified_by"] == "orchestrator" and ev["base_url"] == base and ev["sha"] == "abc"
    assert ev["checks"]["login"]["operation_id"] == "createSession" and "command" not in ev
    assert ev["deploy"] == {
        "project": "company-p-staging",
        "env": "staging",
        "container_ids": ["c1", "c2"],
        "started_at": "2026-10-12T16:58:01+00:00",
    }, "ghi quét CÁI GÌ, không chép lại smoke"
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    dep = {"runtime": {"command": ["app"], "health": "/healthz", "dependencies": ["PostgreSQL"]}}
    assert evidence(tmp_path, dep, None, CONTRACT, sha="s", deployed=rec)["base_url"] == base, "ADR-0053 cùng đường"
    assert json.loads(json.dumps(ev)) == ev


def test_evidence_can_deploy_ma_thieu_hay_khong_tra_loi_thi_unverified_noi_ro(tmp_path):
    from company.smoke import free_port

    assert deploy_of(None) is None and deploy_of({"deploy": {}}) is None and deploy_of("x") is None
    assert deploy_of({"deploy": {"ok": True}}) == {"ok": True}, "đọc evidence.deploy của release-events"
    spec = {"runtime": {"command": ["app"], "health": "/healthz", "deploy": "compose.yml"}}
    none = evidence(tmp_path, spec, None, CONTRACT, sha="s", deployed=None)
    assert none["unverified"] is True and "runtime.deploy" in none["reason"] and "evidence.deploy" in none["reason"]
    hong = evidence(
        tmp_path, spec, None, CONTRACT, sha="s", deployed={"ok": False, "env": "staging", "error": "up thoát 1"}
    )
    assert hong["unverified"] is True and "up thoát 1" in hong["reason"] and hong["deploy"] == {"env": "staging"}
    chet = evidence(
        tmp_path, spec, None, CONTRACT, sha="s", deployed={"ok": True, "port": free_port(), "container_ids": ["c1"]}
    )
    assert (
        chet["unverified"] is True and "không trả lời" in chet["reason"] and chet["deploy"] == {"container_ids": ["c1"]}
    )


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


def test_dast_quet_staging_da_deploy_truoc_release_check(tmp_path, monkeypatch):
    """Dây: ops dựng staging TRƯỚC security trong cùng lượt RC (`STAGING_ROUTE` đứng trước `RELEASE_CHECK_ROUTE`),
    `evidence_before` lấy `evidence.deploy` của release-events staging đưa cho `dast.evidence` — cùng RC, cùng cổng."""
    import company.dast as dast
    from company.events import Task
    from test_deploy_release_fsm import RUNTIME, _fake_deploy, _orch, _repo
    from test_supply_chain import _fake_licenses

    _fake_licenses(monkeypatch)
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime={**RUNTIME, "deploy": "compose.yaml"})
    orch.lead.tickets["T1"] = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title="T1",
        acceptance=["a"],
        risk_tags=["auth"],
    )
    seen: list[str] = []
    monkeypatch.setattr(dast, "http_probe", lambda url: 200)
    monkeypatch.setattr(
        dast, "scan", lambda base, health, contract: seen.append(base) or {"checks": {}, "issues": [], "notes": []}
    )
    monkeypatch.setattr(dast, "run_dast", lambda *a: (_ for _ in ()).throw(AssertionError("dựng lại bằng lệnh trần")))
    orch.run()
    ev = _sec(bus)["evidence"]["dast"]
    assert seen == ["http://127.0.0.1:8080"] and ev["base_url"] == "http://127.0.0.1:8080"
    assert ev["verified_by"] == "orchestrator" and ev["deploy"]["container_ids"] == ["abcdef012345"]
    assert _audits(bus, "dast.run")[-1]["deploy"]["container_ids"] == ["abcdef012345"]


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
