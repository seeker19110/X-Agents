"""Test server console: chạy server thật trên cổng ephemeral, gõ vào bằng http.client.

collect/decide do agent khác viết; ở đây luôn monkeypatch chúng nên test không phụ thuộc nội dung.
"""

from __future__ import annotations

import http.client
import json
import stat
import sys
import threading
import types
import os
from pathlib import Path
from typing import Any

import pytest

from console import server as srv


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static"
    d.mkdir()
    (d / "index.html").write_text("<html><head><title>c</title></head><body>xin chào</body></html>", encoding="utf-8")
    (d / "app.js").write_text("// js", encoding="utf-8")
    return d


class Console:
    def __init__(self, server: srv.ConsoleServer) -> None:
        self.server = server
        self.token = server.token
        self.port = server.port

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = "auto",
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> tuple[int, dict[str, Any] | str]:
        hdrs = dict(headers or {})
        if token == "auto":
            hdrs.setdefault("X-Console-Token", self.token)
        elif token is not None:
            hdrs["X-Console-Token"] = token
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
        finally:
            conn.close()


@pytest.fixture
def make_console(static_dir: Path):
    started: list[srv.ConsoleServer] = []

    def _make(*, readonly: bool = True, **kw: Any) -> Console:
        server = srv.make_server("127.0.0.1", 0, readonly=readonly, static_dir=static_dir, **kw)
        started.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return Console(server)

    yield _make
    for s in started:
        s.shutdown()
        s.server_close()


@pytest.fixture
def fake_modules(monkeypatch: pytest.MonkeyPatch):
    """Thay hẳn console.collect / console.decide bằng module giả (chúng có thể chưa tồn tại)."""
    calls: dict[str, list[Any]] = {"collect": [], "decide": []}
    state: dict[str, Any] = {"ok": True}
    box: dict[str, Any] = {"decide_result": {"ok": True, "subject_id": "PUB-1", "decision": "approve", "event_id": "e1"}}

    def collect(company_db: Any, studio_db: Any, *a: Any, **k: Any) -> dict[str, Any]:
        calls["collect"].append((company_db, studio_db))
        if isinstance(state.get("__raise__"), Exception):
            raise state["__raise__"]
        return state

    def decide(company_db: Any, studio_db: Any, **kw: Any) -> dict[str, Any]:
        calls["decide"].append(kw)
        result = box["decide_result"]
        if isinstance(result, Exception):
            raise result
        return result

    mod_c = types.ModuleType("console.collect"); mod_c.collect = collect  # type: ignore[attr-defined]
    mod_d = types.ModuleType("console.decide"); mod_d.decide = decide  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "console.collect", mod_c)
    monkeypatch.setitem(sys.modules, "console.decide", mod_d)
    return types.SimpleNamespace(calls=calls, state=state, box=box)


# --- token -----------------------------------------------------------------

def test_state_khong_token_tra_401(make_console, fake_modules) -> None:
    c = make_console()
    status, body = c.request("GET", "/api/state", token=None)
    assert status == 401
    assert isinstance(body, dict) and "error" in body
    assert fake_modules.calls["collect"] == []


def test_state_sai_token_tra_401(make_console, fake_modules) -> None:
    c = make_console()
    status, _ = c.request("GET", "/api/state", token="sai-token")
    assert status == 401


def test_state_dung_token_tra_du_lieu_tu_collect(make_console, fake_modules) -> None:
    fake_modules.state.clear()
    fake_modules.state.update({"generated_at": "2026-09-03T08:41:12+07:00", "tiles": {"events": 238}})
    c = make_console(company_db=Path("/a/company.sqlite"), studio_db=None)
    status, body = c.request("GET", "/api/state")
    assert status == 200
    assert body == fake_modules.state
    assert fake_modules.calls["collect"] == [(Path("/a/company.sqlite"), None)]


def test_collect_no_loi_thi_500(make_console, fake_modules) -> None:
    fake_modules.state["__raise__"] = RuntimeError("bể")
    c = make_console()
    status, body = c.request("GET", "/api/state")
    assert status == 500
    assert isinstance(body, dict) and "bể" not in json.dumps(body)


# --- Host / Origin ---------------------------------------------------------

def test_host_khong_loopback_bi_tu_choi(make_console, fake_modules) -> None:
    c = make_console()
    status, _ = c.request("GET", "/api/state", headers={"Host": "console.evil.example"})
    assert status == 404
    assert fake_modules.calls["collect"] == []


def test_host_loopback_kem_cong_van_qua(make_console, fake_modules) -> None:
    c = make_console()
    status, _ = c.request("GET", "/api/state", headers={"Host": f"localhost:{c.port}"})
    assert status == 200


def test_post_cross_origin_bi_tu_choi(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request(
        "POST", "/api/gate/decide",
        headers={"Origin": "https://evil.example"},
        body={"subject_id": "PUB-1", "xuong": "Studio-creators", "decision": "approve", "by": "owner", "reason": "ok"},
    )
    assert status == 403
    assert fake_modules.calls["decide"] == []


def test_post_same_origin_duoc_qua(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request(
        "POST", "/api/gate/decide",
        headers={"Origin": f"http://127.0.0.1:{c.port}"},
        body={"subject_id": "PUB-1", "xuong": "Studio-creators", "decision": "approve", "by": "owner", "reason": "ok"},
    )
    assert status == 200


# --- readonly / decide -----------------------------------------------------

DECIDE_BODY = {"subject_id": "PUB-1", "xuong": "Studio-creators", "decision": "approve", "by": "owner", "reason": "ok"}


def test_readonly_chan_post(make_console, fake_modules) -> None:
    c = make_console(readonly=True)
    status, body = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 403
    assert isinstance(body, dict) and "--allow-decide" in body["error"]
    assert fake_modules.calls["decide"] == []


def test_readonly_van_kiem_token_truoc(make_console, fake_modules) -> None:
    c = make_console(readonly=True)
    status, _ = c.request("POST", "/api/gate/decide", token=None, body=DECIDE_BODY)
    assert status == 401


def test_allow_decide_goi_xuyen_toi_decide(make_console, fake_modules) -> None:
    c = make_console(readonly=False, company_db=Path("/a/c.sqlite"), studio_db=Path("/b/s.sqlite"))
    status, body = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 200
    assert body == {"ok": True, "subject_id": "PUB-1", "decision": "approve", "event_id": "e1"}
    assert fake_modules.calls["decide"] == [DECIDE_BODY]


def test_thieu_truong_thi_400(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body={"subject_id": "PUB-1", "xuong": "Studio-creators"})
    assert status == 400
    assert fake_modules.calls["decide"] == []


def test_body_khong_phai_json_thi_400(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=5)
    conn.request("POST", "/api/gate/decide", body=b"{khong-phai-json", headers={"X-Console-Token": c.token})
    assert conn.getresponse().status == 400
    conn.close()


def test_decide_valueerror_thanh_400(make_console, fake_modules) -> None:
    fake_modules.box["decide_result"] = ValueError("quyết định 'xoá' không có trong Decision")
    c = make_console(readonly=False)
    status, body = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 400
    assert isinstance(body, dict) and "Decision" in body["error"]


def test_gate_error_bi_chan_thanh_403(make_console, fake_modules) -> None:
    class GateError(Exception): pass

    fake_modules.box["decide_result"] = GateError("người duyệt không được phép (four-eyes)")
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 403


def test_gate_error_da_quyet_thanh_409(make_console, fake_modules) -> None:
    class GateError(Exception): pass

    fake_modules.box["decide_result"] = GateError("gate PUB-1 đã quyết rồi")
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 409


def test_gate_error_khai_bao_ma_http(make_console, fake_modules) -> None:
    class GateError(Exception):
        http_status = 409

    fake_modules.box["decide_result"] = GateError("trạng thái không cho phép")
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 409


def test_loi_la_thanh_500(make_console, fake_modules) -> None:
    fake_modules.box["decide_result"] = RuntimeError("sqlite bể")
    c = make_console(readonly=False)
    status, body = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 500
    assert isinstance(body, dict) and "sqlite" not in body["error"]


# --- trang & đường dẫn -----------------------------------------------------

def test_healthz(make_console, fake_modules) -> None:
    c = make_console()
    status, body = c.request("GET", "/healthz", token=None)
    assert (status, body) == (200, {"ok": True})


def test_duong_dan_la_404(make_console, fake_modules) -> None:
    c = make_console()
    assert c.request("GET", "/khong-co-gi")[0] == 404
    assert c.request("POST", "/khong-co-gi", body={})[0] == 404


def test_index_chen_token_va_readonly(make_console, fake_modules) -> None:
    c = make_console(readonly=True)
    status, body = c.request("GET", "/", token=None)
    assert status == 200
    assert isinstance(body, str)
    assert f'"token": "{c.token}"' in body or f'"token":"{c.token}"' in body
    assert "window.__CONSOLE__" in body and "readonly" in body
    assert body.index("window.__CONSOLE__") < body.index("</head>")


def test_static_va_chan_di_ra_ngoai(make_console, fake_modules) -> None:
    c = make_console()
    assert c.request("GET", "/static/app.js", token=None)[0] == 200
    assert c.request("GET", "/static/khong-co.js", token=None)[0] == 404
    assert c.request("GET", "/static/../../pyproject.toml", token=None)[0] in (403, 404)


# --- token file ------------------------------------------------------------

POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="quyền 0600 chỉ có nghĩa trên POSIX; Windows luôn báo 0666")


@POSIX_ONLY
def test_file_token_tao_voi_quyen_0600(tmp_path: Path) -> None:
    path = tmp_path / ".console-token"
    token = srv.generate_token()
    srv.write_token_file(token, path)
    assert path.read_text(encoding="utf-8").strip() == token
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@POSIX_ONLY
def test_file_token_ghi_de_van_giu_0600(tmp_path: Path) -> None:
    path = tmp_path / ".console-token"
    path.write_text("cu", encoding="utf-8")
    path.chmod(0o644)
    srv.write_token_file(srv.generate_token(), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_token_khac_nhau_moi_lan_chay() -> None:
    assert srv.generate_token() != srv.generate_token()
    assert len(srv.generate_token()) >= 40


# --- CLI -------------------------------------------------------------------

def test_cli_tu_choi_host_khong_loopback(capsys: pytest.CaptureFixture[str]) -> None:
    from console.__main__ import main

    assert main(["--host", "0.0.0.0"]) == 2
    assert "Từ chối khởi động" in capsys.readouterr().out


def test_cli_mac_dinh_la_readonly() -> None:
    from console.__main__ import build_parser

    assert build_parser().parse_args([]).readonly is True
    assert build_parser().parse_args(["--allow-decide"]).readonly is False
    assert build_parser().parse_args([]).port == 8200
