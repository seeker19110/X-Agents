"""Test server console: chạy server thật trên cổng ephemeral, gõ vào bằng http.client.

collect/decide do agent khác viết; ở đây luôn monkeypatch chúng nên test không phụ thuộc nội dung.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import stat
import struct
import sys
import threading
import time
import types
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

    def collect(company_db: Any, *a: Any, **k: Any) -> dict[str, Any]:
        calls["collect"].append((company_db,))
        if isinstance(state.get("__raise__"), Exception):
            raise state["__raise__"]
        return state

    def decide(company_db: Any, keeper_db: Any = None, **kw: Any) -> dict[str, Any]:
        calls["decide"].append(kw)
        result = box["decide_result"]
        if isinstance(result, Exception):
            raise result
        return result

    calls["submit"] = []
    box["submit_result"] = {"ok": True, "xuong": "software-company", "topic": "research-requests", "key": "P1", "event_id": "e9"}

    def submit(company_db: Any, keeper_db: Any = None, **kw: Any) -> dict[str, Any]:
        calls["submit"].append((company_db, kw))
        result = box["submit_result"]
        if isinstance(result, Exception):
            raise result
        return result

    mod_c = types.ModuleType("console.collect"); mod_c.collect = collect  # type: ignore[attr-defined]
    mod_d = types.ModuleType("console.decide"); mod_d.decide = decide  # type: ignore[attr-defined]
    mod_s = types.ModuleType("console.submit"); mod_s.submit = submit  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "console.collect", mod_c)
    monkeypatch.setitem(sys.modules, "console.decide", mod_d)
    monkeypatch.setitem(sys.modules, "console.submit", mod_s)
    return types.SimpleNamespace(calls=calls, state=state, box=box)


# --- giao việc: POST /api/request ---------------------------------------------

_REQ = {"xuong": "software-company", "topic": "research-requests", "actor": "human:sales",
        "payload": {"project_id": "P1", "description": "web bán khoá học"}}


def test_request_khoa_khi_khong_co_allow_submit(make_console, fake_modules) -> None:
    # --allow-decide KHÔNG mở giao việc: ba quyền ghi tách riêng.
    c = make_console(readonly=False)
    status, body = c.request("POST", "/api/request", body=_REQ)
    assert status == 403 and "--allow-submit" in body["error"]
    assert fake_modules.calls["submit"] == []


def test_request_goi_xuyen_toi_submit(make_console, fake_modules, tmp_path: Path) -> None:
    c = make_console(allow_submit=True, company_db=tmp_path / "c.sqlite")
    status, body = c.request("POST", "/api/request", body=_REQ)
    assert status == 200 and body["ok"] is True and body["event_id"] == "e9"
    (company_db, kw), = fake_modules.calls["submit"]
    assert company_db == tmp_path / "c.sqlite"
    assert kw == {"xuong": "software-company", "topic": "research-requests", "actor": "human:sales",
                  "payload": {"project_id": "P1", "description": "web bán khoá học"}}


@pytest.mark.parametrize("bad", [
    {**_REQ, "xuong": 1},                 # sai kiểu
    {k: v for k, v in _REQ.items() if k != "topic"},   # thiếu topic
    {**_REQ, "actor": None},
    {**_REQ, "payload": "P1"},            # payload không phải object
    {**_REQ, "payload": ["x"]},
])
def test_request_thieu_hoac_sai_truong_tra_400_khong_goi_submit(make_console, fake_modules, bad) -> None:
    c = make_console(allow_submit=True)
    status, body = c.request("POST", "/api/request", body=bad)
    assert status == 400 and "error" in body
    assert fake_modules.calls["submit"] == []


class _SubmitError(Exception):
    def __init__(self, msg: str, http_status: int) -> None:
        super().__init__(msg); self.http_status = http_status


@pytest.mark.parametrize("exc, status", [
    (ValueError("xưởng lạ"), 400),
    (PermissionError("không được phép"), 403),
    (_SubmitError("payload không hợp lệ theo JSON Schema", 400), 400),
    (_SubmitError("trùng", 409), 409),
    (RuntimeError("nổ"), 500),
])
def test_request_loi_tu_submit_thanh_ma_http(make_console, fake_modules, exc, status) -> None:
    fake_modules.box["submit_result"] = exc
    c = make_console(allow_submit=True)
    got, body = c.request("POST", "/api/request", body=_REQ)
    assert got == status and "error" in body
    if status == 500:
        assert "nổ" not in body["error"]   # lỗi bất ngờ không lộ chi tiết nội bộ


def test_index_chen_can_submit_vao_boot(make_console, fake_modules) -> None:
    c = make_console(allow_submit=True)
    _, body = c.request("GET", "/", token=None)
    assert '"can_submit": true' in body
    c2 = make_console()
    _, body2 = c2.request("GET", "/", token=None)
    assert '"can_submit": false' in body2


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
    c = make_console(company_db=Path("/a/company.sqlite"))
    status, body = c.request("GET", "/api/state")
    assert status == 200
    assert body == fake_modules.state
    assert fake_modules.calls["collect"] == [(Path("/a/company.sqlite"),)]


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
        body={"subject_id": "PUB-1", "xuong": "software-company", "decision": "approve", "by": "owner", "reason": "ok"},
    )
    assert status == 403
    assert fake_modules.calls["decide"] == []


def test_post_same_origin_duoc_qua(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request(
        "POST", "/api/gate/decide",
        headers={"Origin": f"http://127.0.0.1:{c.port}"},
        body={"subject_id": "PUB-1", "xuong": "software-company", "decision": "approve", "by": "owner", "reason": "ok"},
    )
    assert status == 200


# --- readonly / decide -----------------------------------------------------

DECIDE_BODY = {"subject_id": "PUB-1", "xuong": "software-company", "decision": "approve", "by": "owner", "reason": "ok"}


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
    c = make_console(readonly=False, company_db=Path("/a/c.sqlite"))
    status, body = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 200
    assert body == {"ok": True, "subject_id": "PUB-1", "decision": "approve", "event_id": "e1"}
    assert fake_modules.calls["decide"] == [DECIDE_BODY]


def test_thieu_truong_thi_400(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body={"subject_id": "PUB-1", "xuong": "software-company"})
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


# --- /api/stream (SSE) ------------------------------------------------------

def _read_sse(port: int, token: str | None, *, path: str = "/api/stream", limit: int = 1,
              timeout: float = 8.0) -> tuple[int, dict[str, str], list[tuple[str, Any]]]:
    """Đọc stream cho tới khi gom đủ `limit` khung `event:` rồi đóng kết nối.

    Đọc từng dòng chứ không `resp.read()`: thân bài của SSE không có `Content-Length` và chỉ kết
    thúc khi server đóng, nên `read()` sẽ treo tới hết `stream_max_seconds`.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path, headers=({"X-Console-Token": token} if token else {}))
        resp = conn.getresponse()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        if resp.status != 200:
            resp.read()
            return resp.status, headers, []
        frames: list[tuple[str, Any]] = []
        event = None
        while len(frames) < limit:
            line = resp.fp.readline()
            if not line:
                break
            text = line.decode("utf-8").rstrip("\r\n")
            if text.startswith("event: "):
                event = text[len("event: "):]
            elif text.startswith("data: "):
                frames.append((event or "", json.loads(text[len("data: "):])))
                event = None
        return resp.status, headers, frames
    finally:
        conn.close()


def test_stream_khong_token_tra_401(make_console, fake_modules) -> None:
    c = make_console(stream_max_seconds=2.0)
    status, _, frames = _read_sse(c.port, None)
    assert status == 401
    assert frames == []
    assert fake_modules.calls["collect"] == []


def test_stream_sai_token_tra_401(make_console, fake_modules) -> None:
    c = make_console(stream_max_seconds=2.0)
    status, _, _ = _read_sse(c.port, "sai-token")
    assert status == 401


def test_stream_day_ngay_trang_thai_dau_tien(make_console, fake_modules, tmp_path: Path) -> None:
    """Khung đầu tiên đi ngay khi kết nối, không phải chờ bus đổi — nếu không, trang mới mở sẽ trắng."""
    fake_modules.state.clear()
    fake_modules.state.update({"generated_at": "2026-09-03T08:41:12+07:00", "tiles": {"events": 7}})
    db = tmp_path / "company.sqlite"
    db.write_bytes(b"x")
    c = make_console(company_db=db, stream_max_seconds=4.0)

    status, headers, frames = _read_sse(c.port, c.token)

    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-store"
    assert len(frames) == 1 and frames[0][0] == "state"
    payload = dict(frames[0][1])
    # `engine` đi kèm MỌI khung trạng thái (ADR-0004): /api/state và /api/stream phải trả cùng một payload,
    # nếu không thì ô Động cơ chỉ đúng ở đường hỏi lại 10 giây và sai ở đường stream.
    assert payload.pop("engine")["engines"][0]["xuong"] == "software-company"
    assert payload == {"generated_at": "2026-09-03T08:41:12+07:00", "tiles": {"events": 7}}


def test_stream_day_khung_moi_khi_bus_doi(make_console, fake_modules, tmp_path: Path) -> None:
    """Ghi thêm vào file bus → khung thứ hai. Đây là cả lý do tồn tại của /api/stream."""
    db = tmp_path / "company.sqlite"
    db.write_bytes(b"x")
    fake_modules.state.clear(); fake_modules.state.update({"n": 1})
    c = make_console(company_db=db, stream_max_seconds=8.0)

    conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=10)
    try:
        conn.request("GET", "/api/stream", headers={"X-Console-Token": c.token})
        resp = conn.getresponse()
        assert resp.status == 200

        def next_state() -> Any:
            while True:
                line = resp.fp.readline()
                assert line, "stream đóng sớm"
                text = line.decode("utf-8").rstrip("\r\n")
                if text.startswith("data: "):
                    return json.loads(text[len("data: "):])

        def state_khong_engine() -> Any:
            payload = dict(next_state())
            payload.pop("engine", None)
            return payload

        assert state_khong_engine() == {"n": 1}
        fake_modules.state.clear(); fake_modules.state.update({"n": 2})
        db.write_bytes(b"xy")            # bus đổi → dấu vân tay đổi
        assert state_khong_engine() == {"n": 2}
    finally:
        conn.close()


def test_stream_collect_loi_tra_khung_error_khong_dut_stream(make_console, fake_modules, tmp_path: Path) -> None:
    db = tmp_path / "company.sqlite"
    db.write_bytes(b"x")
    fake_modules.state["__raise__"] = RuntimeError("bus hỏng")
    c = make_console(company_db=db, stream_max_seconds=4.0)

    status, _, frames = _read_sse(c.port, c.token)

    assert status == 200
    assert frames == [("error", {"error": "không đọc được trạng thái"})]


def test_stream_host_la_bi_tu_choi(make_console, fake_modules) -> None:
    """Chống DNS rebinding phải áp cho cả stream, không chỉ /api/state."""
    c = make_console(stream_max_seconds=2.0)
    status, _ = c.request("GET", "/api/stream", headers={"Host": "ke-tan-cong.example"})
    assert status == 404
    assert fake_modules.calls["collect"] == []


def test_head_tra_header_khong_kem_than(make_console) -> None:
    """RFC 9110 §9.3.2: HEAD như GET nhưng KHÔNG có thân (phủ nhánh, audit 2026-09-28, #366). Đọc bằng socket
    thô: `http.client` tự bỏ thân của phản hồi HEAD nên không thấy được server lỡ ghi thân vào kết nối."""
    c = make_console()
    with socket.create_connection(("127.0.0.1", c.port), timeout=5) as s:
        s.sendall(f"HEAD /healthz HTTP/1.1\r\nHost: 127.0.0.1:{c.port}\r\nConnection: close\r\n\r\n".encode())
        raw = b""
        while chunk := s.recv(65536):
            raw += chunk
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("latin-1").split("\r\n")
    headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in header_lines)}
    assert " 200 " in status_line
    assert int(headers["content-length"]) == len(b'{"ok": true}')   # header nói đúng độ dài thân của GET
    assert body == b""


def test_stream_head_khong_treo(make_console, fake_modules) -> None:
    """do_HEAD gọi thẳng do_GET; nếu không chặn thì HEAD /api/stream sẽ ngồi trong vòng lặp đẩy."""
    c = make_console(stream_max_seconds=30.0)
    status, _ = c.request("HEAD", "/api/stream")
    assert status == 200


# --- dấu vân tay bus --------------------------------------------------------

def test_db_fingerprint_doi_khi_file_doi(tmp_path: Path) -> None:
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    a.write_bytes(b"1"); b.write_bytes(b"1")
    first = srv.db_fingerprint([a, b])
    assert srv.db_fingerprint([a, b]) == first      # không đổi thì không đẩy lại
    b.write_bytes(b"12")
    assert srv.db_fingerprint([a, b]) != first


def test_db_fingerprint_chap_nhan_file_chua_co(tmp_path: Path) -> None:
    """Công ty chưa chạy lần nào là trạng thái hợp lệ; lúc file xuất hiện thì vân tay phải đổi."""
    missing = tmp_path / "chua-co.sqlite"
    before = srv.db_fingerprint([missing, None])
    assert before == "-|-|-"  # DB + WAL chưa có, và một nguồn None
    missing.write_bytes(b"x")
    assert srv.db_fingerprint([missing, None]) != before


def test_db_fingerprint_sees_committed_wal_before_checkpoint(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "bus.sqlite"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE events (value TEXT)")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = srv.db_fingerprint([path, None])
        stat = path.stat()
        db.execute("INSERT INTO events VALUES ('new event')")
        db.commit()
        assert (path.stat().st_mtime_ns, path.stat().st_size) == (stat.st_mtime_ns, stat.st_size)
        assert srv.db_fingerprint([path, None]) != before
    finally:
        db.close()


def test_sse_frame_dung_dinh_dang() -> None:
    assert srv.sse_frame("state", {"a": 1}) == b'event: state\ndata: {"a": 1}\n\n'


def test_sse_frame_khong_lam_vo_khung_boi_xuong_dong(tmp_path: Path) -> None:
    """Chuỗi có \n trong dữ liệu không được cắt khung SSE làm đôi — JSON đã thoát sẵn."""
    raw = srv.sse_frame("state", {"msg": "dòng 1\ndòng 2"})
    assert raw.count(b"\n\n") == 1 and raw.endswith(b"\n\n")
    assert raw.decode("utf-8").count("data: ") == 1


# --- vỏ PWA ----------------------------------------------------------------

@pytest.fixture
def pwa_static(static_dir: Path) -> Path:
    """static_dir tối giản của các test khác không có vỏ PWA; thêm vào cho nhóm test này."""
    (static_dir / "sw.js").write_text("// sw", encoding="utf-8")
    (static_dir / "manifest.webmanifest").write_text('{"name":"x"}', encoding="utf-8")
    return static_dir


def _raw(port: int, path: str, method: str = "GET") -> tuple[int, dict[str, str], str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read().decode("utf-8")
    finally:
        conn.close()


def test_sw_phuc_vu_o_goc_khong_can_token(make_console, fake_modules, pwa_static) -> None:
    """Service worker chỉ điều khiển được đường trong thư mục chứa nó, mà nó cần điều khiển "/".
    Phục vụ dưới /static/sw.js là scope hoá thành /static/ và vô dụng."""
    c = make_console()
    status, headers, body = _raw(c.port, "/sw.js")
    assert status == 200
    assert headers["content-type"].startswith("text/javascript")
    assert body == "// sw"


def test_manifest_phuc_vu_o_goc_dung_content_type(make_console, fake_modules, pwa_static) -> None:
    c = make_console()
    status, headers, body = _raw(c.port, "/manifest.webmanifest")
    assert status == 200
    assert headers["content-type"].startswith("application/manifest+json")
    assert json.loads(body) == {"name": "x"}


def test_vo_pwa_van_bi_chan_khi_host_la(make_console, fake_modules, pwa_static) -> None:
    """Chống DNS rebinding áp cho mọi đường, kể cả đường không mang dữ liệu."""
    c = make_console()
    status, _ = c.request("GET", "/sw.js", headers={"Host": "ke-tan-cong.example"})
    assert status == 404


def test_thieu_file_vo_pwa_tra_404_khong_no(make_console, fake_modules, static_dir) -> None:
    """static/ chưa có sw.js (bản cài cũ) thì 404 gọn, không phải 500."""
    c = make_console()
    status, _, _ = _raw(c.port, "/sw.js")
    assert status == 404


# --- vỏ PWA thật trong repo (không phải static_dir giả) ----------------------

REAL_STATIC = srv.STATIC_DIR


def test_manifest_that_du_dieu_kien_cai_dat() -> None:
    """Thiếu một trong các trường này thì trình duyệt lặng lẽ không hiện nút Cài đặt."""
    m = json.loads((REAL_STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["start_url"] == "/" and m["scope"] == "/"
    assert m["display"] == "standalone"
    assert m["name"] and m["short_name"]
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes         # Chrome cần ít nhất 192 và 512
    for icon in m["icons"]:
        assert (REAL_STATIC / icon["src"].removeprefix("/static/")).is_file(), icon["src"]
        assert icon["type"] == "image/png"


def test_icon_that_dung_kich_thuoc_manifest_khai() -> None:
    """Đọc IHDR của PNG: manifest khai 192/512 mà file lại khác thì Chrome bỏ qua icon đó."""
    for size in (192, 512):
        raw = (REAL_STATIC / f"icon-{size}.png").read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", raw[16:24])
        assert (width, height) == (size, size)


def test_sw_that_khong_bao_gio_cache_du_lieu_song() -> None:
    """Bảo vệ đúng hai lời hứa của sw.js. Cache /api/* là phục vụ số liệu cũ trên một mặt kính
    trực ban; cache "/" là phục vụ lại token phiên cũ và ăn 401 ở lần chạy sau."""
    sw = (REAL_STATIC / "sw.js").read_text(encoding="utf-8")
    assert 'url.pathname.startsWith("/api/")) return;' in sw
    assert 'url.pathname === "/") return;' in sw
    # Danh sách cache chỉ được có icon — không HTML, không API.
    assets = sw.split("const ASSETS = ")[1].split(";")[0]
    assert "/api" not in assets and ".html" not in assets


# --- ồn khi client ngắt kết nối ---------------------------------------------

def test_client_ngat_ket_noi_khong_in_traceback(make_console, fake_modules, capsys) -> None:
    """Đóng tab giữa lúc /api/stream đang mở là chuyện thường; in traceback cho mỗi lần như vậy
    làm chìm mất lỗi thật trong terminal người vận hành."""
    c = make_console()
    try:
        raise ConnectionResetError(10054, "client đóng")
    except ConnectionResetError:
        c.server.handle_error(None, ("127.0.0.1", 1234))
    assert capsys.readouterr().err == ""


def test_loi_that_van_noi_len_nguyen_ven(make_console, fake_modules, capsys) -> None:
    """Chỉ hạ lỗi mất kết nối — bịt luôn mọi lỗi khác thì console hỏng trong im lặng."""
    c = make_console()
    try:
        raise RuntimeError("hỏng thật")
    except RuntimeError:
        c.server.handle_error(None, ("127.0.0.1", 1234))
    assert "hỏng thật" in capsys.readouterr().err


# --- host_header_is_loopback: nhánh đơn vị -----------------------------------

def test_host_header_none_va_rong_duoc_cho_qua() -> None:
    assert srv.host_header_is_loopback(None) is True
    assert srv.host_header_is_loopback("") is True
    assert srv.host_header_is_loopback("   ") is True


def test_host_header_ipv6_trong_ngoac_vuong() -> None:
    assert srv.host_header_is_loopback("[::1]:8200") is True
    assert srv.host_header_is_loopback("[::1") is True   # thiếu "]" đóng: vẫn cắt được, không ném


# --- Tên miền giả loopback (audit 2026-09-13 mục S1) -------------------------
#
# `is_loopback_host` từng kết thúc bằng `h.startswith("127.")`, nên MỌI tên miền bắt đầu bằng "127." đi lọt.
# Kẻ tấn công sở hữu `evil.com` chỉ cần một bản ghi A `127.0.0.1.evil.com → 127.0.0.1`: trang ở
# `http://127.0.0.1.evil.com:8200` khi đó CÙNG NGUỒN với console, nên nó `fetch("/")` đọc được HTML —
# mà `_serve_index` nhúng token phiên vào `window.__CONSOLE__` — rồi dùng token gọi `/api/gate/decide`.
# Không cần DNS rebinding, chỉ cần một bản ghi A. Hai hàng rào `Host` và `Origin` cùng gọi một hàm này nên
# cùng thủng một lượt.
GIA_LOOPBACK = ("127.0.0.1.evil.example", "127.evil.example", "127.0.0.1x.evil.example")


@pytest.mark.parametrize("ten", GIA_LOOPBACK)
def test_ten_mien_gia_loopback_khong_duoc_coi_la_loopback(ten: str) -> None:
    assert srv.is_loopback_host(ten) is False
    assert srv.host_header_is_loopback(f"{ten}:8200") is False


def test_ip_loopback_that_va_ten_that_van_qua() -> None:
    """Chiều ngược của test trên: siết không được siết nhầm vào thứ vốn hợp lệ."""
    for h in ("127.0.0.1", "127.0.0.2", "127.1.2.3", "localhost", "::1", "0:0:0:0:0:0:0:1"):
        assert srv.is_loopback_host(h) is True, h
    assert srv.host_header_is_loopback("127.0.0.1:8200") is True
    assert srv.host_header_is_loopback("[::1]:8200") is True


def test_host_gia_loopback_bi_tu_choi_o_request_that(make_console, fake_modules) -> None:
    """Mức đơn vị chưa đủ: phải chứng minh `_guard` thật sự chặn, không chỉ hàm thuần trả False."""
    c = make_console()
    status, _ = c.request("GET", "/api/state", headers={"Host": "127.0.0.1.evil.example:8200"})
    assert status == 404
    assert fake_modules.calls["collect"] == []


def test_origin_gia_loopback_bi_tu_choi_o_request_that(make_console, fake_modules) -> None:
    """Cùng lỗ, đường khác: `_origin_allowed` gọi lại đúng hàm ấy nên POST cross-origin cũng đi lọt."""
    c = make_console(readonly=False)
    status, _ = c.request(
        "POST", "/api/gate/decide",
        headers={"Origin": f"http://127.0.0.1.evil.example:{c.port}"},
        body={"subject_id": "PUB-1", "xuong": "software-company", "decision": "approve", "by": "owner",
              "reason": "ok"},
    )
    assert status == 403
    assert fake_modules.calls["decide"] == []


# --- write_token_file (không phụ thuộc quyền POSIX) --------------------------

def test_write_token_file_tao_va_ghi_de_tren_moi_he_dieu_hanh(tmp_path: Path) -> None:
    path = tmp_path / "sub" / ".console-token"
    token = srv.generate_token()
    out = srv.write_token_file(token, path)
    assert out == path
    assert path.read_text(encoding="utf-8").strip() == token
    token2 = srv.generate_token()
    srv.write_token_file(token2, path)
    assert path.read_text(encoding="utf-8").strip() == token2


# --- ConsoleServer với host IPv6 không ngoặc ---------------------------------

def test_server_host_ipv6_khong_ngoac_dung_af_inet6(static_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chọn AF_INET6 là quyết định của CODE, không phải của môi trường: container CI thường tắt IPv6 và
    `socket(AF_INET6)` ném `OSError` ngay — test cũ đỏ ở đó dù code đúng. Ở đây socket được thay bằng bản
    giả chạy trên IPv4 nên chỉ còn đo đúng thứ cần đo: `address_family` mà server tự đặt."""
    import socketserver

    class _SocketGia(socket.socket):
        """Ghi lại address family được yêu cầu, nhưng luôn mở/bind bằng IPv4 (môi trường nào cũng có)."""

        def __init__(self, family: int = -1, type: int = -1, proto: int = -1, fileno: int | None = None) -> None:
            super().__init__(socket.AF_INET, socket.SOCK_STREAM)
            self.duoc_yeu_cau = family

        def bind(self, _address: object) -> None:  # type: ignore[override]
            super().bind(("127.0.0.1", 0))

    monkeypatch.setattr(socketserver.socket, "socket", _SocketGia)
    server = srv.make_server("::1", 0, static_dir=static_dir)
    try:
        assert server.address_family == socket.AF_INET6
        assert server.socket.duoc_yeu_cau == socket.AF_INET6  # family thật sự truyền xuống socket
    finally:
        server.server_close()


# --- _gate_error_status: nhánh mặc định --------------------------------------

def test_gate_error_khong_khop_tu_khoa_nao_thi_400(make_console, fake_modules) -> None:
    class GateError(Exception): pass

    fake_modules.box["decide_result"] = GateError("lỗi lạ không rơi vào nhóm nào")
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 400


# --- Origin: nhánh scheme lạ / thiếu "://" -----------------------------------

def test_origin_scheme_la_bi_tu_choi(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request(
        "POST", "/api/gate/decide",
        headers={"Origin": "ftp://127.0.0.1"},
        body=DECIDE_BODY,
    )
    assert status == 403


def test_origin_khong_co_phan_sau_bi_tu_choi(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request(
        "POST", "/api/gate/decide",
        headers={"Origin": "http://"},
        body=DECIDE_BODY,
    )
    assert status == 403


# --- GET/POST /api/* không khớp route nào ------------------------------------

def test_get_api_khong_khop_route_thieu_token_tra_401(make_console, fake_modules) -> None:
    c = make_console()
    status, _ = c.request("GET", "/api/khong-co-duong-nay", token=None)
    assert status == 401


def test_get_api_khong_khop_route_du_token_tra_404(make_console, fake_modules) -> None:
    c = make_console()
    status, _ = c.request("GET", "/api/khong-co-duong-nay")
    assert status == 404


def test_post_api_khong_khop_route_tra_404(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/khong-co-duong-nay", body={})
    assert status == 404


# --- body: Content-Length hỏng / quá lớn / không phải object ----------------

def test_content_length_khong_phai_so_tra_400(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=5)
    try:
        conn.request("POST", "/api/gate/decide", body=b"{}",
                     headers={"X-Console-Token": c.token, "Content-Length": "khong-phai-so"})
        assert conn.getresponse().status == 400
    finally:
        conn.close()


def test_content_length_qua_lon_tra_400(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=5)
    try:
        conn.request("POST", "/api/gate/decide", body=b"{}",
                     headers={"X-Console-Token": c.token, "Content-Length": str(srv.MAX_BODY_BYTES + 1)})
        assert conn.getresponse().status == 400
    finally:
        conn.close()


def test_body_json_khong_phai_object_tra_400(make_console, fake_modules) -> None:
    c = make_console(readonly=False)
    status, body = c.request("POST", "/api/gate/decide", body=["khong", "phai", "object"])
    assert status == 400
    assert "object JSON" in body["error"]


# --- /api/gate/decide: PermissionError và LookupError ------------------------

def test_decide_permissionerror_thanh_403(make_console, fake_modules) -> None:
    fake_modules.box["decide_result"] = PermissionError("không được phép")
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 403


def test_decide_lookuperror_thanh_404(make_console, fake_modules) -> None:
    fake_modules.box["decide_result"] = LookupError("không tìm thấy subject")
    c = make_console(readonly=False)
    status, _ = c.request("POST", "/api/gate/decide", body=DECIDE_BODY)
    assert status == 404


# --- /api/settings POST: OSError khi ghi -------------------------------------

def test_settings_post_oserror_khi_ghi_thanh_500(make_console, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_oserror(*a: Any, **k: Any) -> Any:
        raise OSError("đĩa đầy")

    mod = types.ModuleType("console.settings")
    mod.DEFAULT_LLM_YAML = {"software-company": Path("/x/llm.yaml")}  # type: ignore[attr-defined]
    mod.SettingsError = ValueError  # type: ignore[attr-defined]
    mod.update_settings = _raise_oserror  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "console.settings", mod)

    c = make_console(allow_config=True)
    status, body = c.request("POST", "/api/settings", body={"company": "software-company"})
    assert status == 500
    assert "đĩa" not in json.dumps(body)


# --- trang chủ: thiếu index.html ---------------------------------------------

def test_thieu_index_html_tra_404(make_console, fake_modules, tmp_path: Path) -> None:
    empty_static = tmp_path / "static-rong"
    empty_static.mkdir()
    c = srv.make_server("127.0.0.1", 0, static_dir=empty_static)
    threading.Thread(target=c.serve_forever, daemon=True).start()
    try:
        console = Console(c)
        status, _ = console.request("GET", "/", token=None)
        assert status == 404
    finally:
        c.shutdown()
        c.server_close()


# --- /static: đường ném OSError khi resolve() --------------------------------

def test_static_resolve_nem_oserror_tra_404(make_console, fake_modules, monkeypatch: pytest.MonkeyPatch) -> None:
    import pathlib

    real_resolve = pathlib.Path.resolve

    def _boom_resolve(self: pathlib.Path, *a: Any, **k: Any) -> pathlib.Path:
        if "boom-oserror" in str(self):
            raise OSError("resolve hỏng")
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "resolve", _boom_resolve)
    c = make_console()
    status, _ = c.request("GET", "/static/boom-oserror.js", token=None)
    assert status == 404


# --- /api/stream: heartbeat và mất kết nối giữa chừng ------------------------

def test_stream_gui_heartbeat_khi_khong_co_gi_doi(make_console, fake_modules, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "STREAM_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(srv, "STREAM_POLL_SECONDS", 0.02)
    fake_modules.state.clear(); fake_modules.state.update({"n": 1})
    c = make_console(stream_max_seconds=1.0)

    conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=5)
    try:
        conn.request("GET", "/api/stream", headers={"X-Console-Token": c.token})
        resp = conn.getresponse()
        assert resp.status == 200
        saw_ping = False
        for _ in range(300):
            line = resp.fp.readline()
            if not line:
                break
            if line.strip() == b": ping":
                saw_ping = True
                break
        assert saw_ping
    finally:
        conn.close()


def test_stream_mat_ket_noi_giua_chung_khong_nem(make_console, fake_modules, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """time.sleep() ném BrokenPipeError giả lập client đã ngắt — vòng lặp phải thoát êm, không traceback."""
    calls = {"n": 0}
    real_sleep = srv.time.sleep

    def _sleep_then_break(seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise BrokenPipeError("client đã đóng")
        real_sleep(seconds)

    monkeypatch.setattr(srv.time, "sleep", _sleep_then_break)
    c = make_console(stream_max_seconds=5.0)
    status, _, frames = _read_sse(c.port, c.token, limit=1)
    assert status == 200
    assert frames

    deadline = time.monotonic() + 3.0
    while calls["n"] < 2 and time.monotonic() < deadline:
        real_sleep(0.02)   # dùng sleep GỐC — srv.time.sleep đã bị vá, gọi nó ở đây sẽ tự ném luôn
    assert calls["n"] >= 2   # đủ để vòng lặp chạm nhánh sleep() ném BrokenPipeError


# --- động cơ: POST /api/engine (ADR-0004) -------------------------------------

class _FakeEngine:
    """Thay `EngineManager` để test SERVER (định tuyến, quyền, mã HTTP) mà không tạo tiến trình con thật —
    vòng đời tiến trình đã có `tests/test_engine.py` kiểm bằng tiến trình thật."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_with: Exception | None = None

    def status(self) -> dict[str, Any]:
        return {"engines": [{"xuong": "software-company", "state": "stopped"}]}

    def fingerprint(self) -> str:
        return "fp"

    def stop_all(self) -> None:
        self.calls.append(("stop_all", {}))

    def start(self, xuong: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("start", {"xuong": xuong, **kw}))
        if self.raise_with is not None:
            raise self.raise_with
        return {"ok": True, "state": "running", "xuong": xuong}

    def stop(self, xuong: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("stop", {"xuong": xuong, **kw}))
        if self.raise_with is not None:
            raise self.raise_with
        return {"ok": True, "state": "exited", "xuong": xuong}


@pytest.fixture
def engine_console(make_console):
    def _make(**kw: Any) -> tuple[Console, _FakeEngine]:
        c = _make_with(kw)
        return c

    def _make_with(kw: dict[str, Any]) -> tuple[Console, _FakeEngine]:
        c = make_console(**kw)
        fake = _FakeEngine()
        c.server.engine = fake
        return c, fake
    return _make


_ENG = {"action": "start", "xuong": "software-company", "by": "human:truc-ban", "interval": 30}


def test_engine_bi_khoa_khi_khong_co_allow_engine(engine_console) -> None:
    c, fake = engine_console()
    status, body = c.request("POST", "/api/engine", body=_ENG)
    assert status == 403 and "--allow-engine" in body["error"] and fake.calls == []


def test_engine_khong_dinh_kem_allow_decide(engine_console) -> None:
    """Bốn quyền là bốn cờ: mở cửa duyệt gate không đồng nghĩa mở cửa đốt hạn mức model."""
    c, fake = engine_console(readonly=False, allow_submit=True, allow_config=True)
    assert c.request("POST", "/api/engine", body=_ENG)[0] == 403 and fake.calls == []


def test_engine_start_va_stop_di_toi_manager(engine_console) -> None:
    c, fake = engine_console(allow_engine=True)
    status, body = c.request("POST", "/api/engine", body=_ENG)
    assert status == 200 and body["state"] == "running"
    assert fake.calls[0] == ("start", {"xuong": "software-company", "interval": 30, "by": "human:truc-ban"})
    status, body = c.request("POST", "/api/engine", body={**_ENG, "action": "stop"})
    assert status == 200 and fake.calls[1] == ("stop", {"xuong": "software-company", "by": "human:truc-ban"})


def test_engine_thieu_interval_thi_dung_mac_dinh(engine_console) -> None:
    c, fake = engine_console(allow_engine=True)
    c.request("POST", "/api/engine", body={"action": "start", "xuong": "software-company", "by": "human:a"})
    assert fake.calls[0][1]["interval"] == srv.DEFAULT_ENGINE_INTERVAL


@pytest.mark.parametrize("body,mong", [
    ({"action": "toggle", "xuong": "software-company", "by": "human:a"}, "'action'"),
    ({"action": "start", "xuong": 7, "by": "human:a"}, "'xuong'"),
    ({"action": "start", "xuong": "software-company"}, "'xuong'"),
])
def test_engine_tu_choi_body_sai(engine_console, body: dict[str, Any], mong: str) -> None:
    c, fake = engine_console(allow_engine=True)
    status, resp = c.request("POST", "/api/engine", body=body)
    assert status == 400 and mong in resp["error"] and fake.calls == []


def test_engine_giu_nguyen_ma_http_cua_engine_error(engine_console) -> None:
    from console.engine import EngineError

    c, fake = engine_console(allow_engine=True)
    fake.raise_with = EngineError("động cơ xưởng phần mềm đang chạy rồi (pid 7)", 409)
    status, body = c.request("POST", "/api/engine", body=_ENG)
    assert status == 409 and "đang chạy rồi" in body["error"]


def test_engine_can_token_nhu_moi_api(engine_console) -> None:
    c, _ = engine_console(allow_engine=True)
    assert c.request("POST", "/api/engine", token="sai", body=_ENG)[0] == 401


def test_state_mang_trang_thai_dong_co_va_co_quyen(engine_console, fake_modules) -> None:
    c, _ = engine_console(allow_engine=True)
    status, body = c.request("GET", "/api/state")
    assert status == 200 and body["engine"]["allowed"] is True
    assert body["engine"]["engines"][0]["xuong"] == "software-company"


def test_state_noi_ro_dong_co_bi_khoa_khi_chua_bat_co(engine_console, fake_modules) -> None:
    c, _ = engine_console()
    assert c.request("GET", "/api/state")[1]["engine"]["allowed"] is False


def test_trang_biet_minh_co_quyen_bat_dong_co_khong(make_console) -> None:
    c = make_console(allow_engine=True)
    html = c.request("GET", "/")[1]
    assert '"can_engine": true' in html.replace("'", '"')
    assert '"can_engine": false' in make_console().request("GET", "/")[1].replace("'", '"')


def test_dong_server_thi_tat_moi_dong_co(static_dir: Path) -> None:
    """Con của console chết cùng console (ADR-0004): orchestrator mồ côi vẫn ghi bus là thứ tệ nhất."""
    server = srv.make_server("127.0.0.1", 0, static_dir=static_dir)
    fake = _FakeEngine()
    server.engine = fake
    server.server_close()
    assert ("stop_all", {}) in fake.calls


def test_duong_dan_bus_mac_dinh_tro_dung_cay_cong_ty() -> None:
    """Mặc định `--company-db`/`--keeper-db` phải trỏ vào cây công ty thật. Trỏ sai thì console mở lên vẫn
    xanh — nó chỉ hiện bảng RỖNG (bẫy "xanh vì rỗng", TRAPS.md), không lỗi, không dấu hiệu."""
    from console import server as sv
    for db in (sv.DEFAULT_COMPANY_DB, sv.DEFAULT_KEEPER_DB):
        assert (db.parent / "pyproject.toml").is_file(), f"{db} không nằm trong cây package nào"
