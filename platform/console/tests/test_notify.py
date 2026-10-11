"""Thông báo đẩy khi có gate chờ người (ADR-0005).

Vì sao có lớp này: console chỉ hiện gate khi có người đang mở trang. Người trực đi khỏi máy thì gate chờ hàng giờ
mà không ai biết — console có `remind_at` 12 h / `timeout` 24 h để TÔ MÀU, không có gì để GỌI người. Lớp này gửi
một tin ra ngoài (ntfy / Telegram) mỗi khi một gate MỚI xuất hiện trong hàng đợi, kèm link mở đúng ngăn kéo gate.

Luật của lớp: không đụng bus (chỉ đọc qua `collect`), không bao giờ ném ra ngoài (lỗi mạng là số đếm + lý do trong
`status()`), không log/ghi token Telegram, và trạng thái phải ĐO ĐƯỢC (gửi mấy tin, hỏng mấy tin) chứ không phải
"đã bật".
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from company.events import AuditLog as CompanyAudit
from company.events import Envelope as CompanyEnvelope
from company.sqlite_bus import SQLiteBus as CompanySQLiteBus

from conftest import build_company_db, gate_request
from console import notify as nt

PUBLIC = "https://console.vi-du.ts.net"


def _gate(gid: str, *, kind: str = "release", xuong: str = "software-company", hours: int = 1,
          sev: str = "calm", title: str | None = None, effect: str = "deploy staging") -> dict[str, Any]:
    return {"id": gid, "xuong": xuong, "kind": kind, "by": "delivery-lead", "trigger": "", "hours": hours,
            "sev": sev, "effect": effect, "reject": "", "agent": "", "title": title or f"{kind} · {gid}",
            "facts": [], "cl": [], "decidable": True}


class _Post:
    """`post` giả: ghi lại mọi lần gọi; `status` là mã HTTP trả về; `boom` để ném."""

    def __init__(self, status: int = 200, boom: Exception | None = None) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self.status, self.boom = status, boom

    def __call__(self, url: str, data: bytes, headers: dict[str, str]) -> int:
        self.calls.append((url, data, headers))
        if self.boom is not None:
            raise self.boom
        return self.status


def _notifier(post: _Post, *channels: Any) -> nt.Notifier:
    return nt.Notifier(list(channels) or [nt.NtfyChannel("https://ntfy.sh/xagents-thu")], public_url=PUBLIC, post=post)


# --- Notifier.observe: cái gì được gửi, khi nào -----------------------------------------------------------------

def test_lan_quan_sat_dau_gui_mot_tin_tom_tat_khi_co_gate_cho() -> None:
    """Khởi động console lúc đã có 2 gate chờ: MỘT tin "2 gate đang chờ" (không phải 2 tin — người vừa bật console
    không cần bị dội), link về màn Trực ban."""
    post = _Post()
    n = _notifier(post)
    sent = n.observe([_gate("REL-001", hours=30, sev="over"), _gate("SPEC-9", kind="spec")])
    assert len(sent) == 1 and len(post.calls) == 1
    msg = sent[0]
    assert "2 gate" in msg.title
    assert "REL-001" in msg.body and "SPEC-9" in msg.body
    assert msg.link == f"{PUBLIC}/#/truc-ban"
    assert n.status()["sent"] == 1 and n.status()["watching"] == 2


def test_lan_quan_sat_dau_khong_co_gate_thi_im() -> None:
    post = _Post()
    n = _notifier(post)
    assert n.observe([]) == []
    assert post.calls == [] and n.status()["sent"] == 0 and n.status()["watching"] == 0


def test_gate_moi_xuat_hien_gui_dung_mot_tin_kem_link_ngan_keo() -> None:
    post = _Post()
    n = _notifier(post)
    n.observe([_gate("REL-001")])
    sent = n.observe([_gate("REL-001"), _gate("TCK-7", kind="escalation", hours=13, sev="warn",
                                              title="API đăng nhập", effect="builder làm lại với hint")])
    assert len(sent) == 1
    msg = sent[0]
    assert msg.title == "Gate chờ: escalation · TCK-7"
    assert "software-company" in msg.body and "API đăng nhập" in msg.body and "13 giờ" in msg.body
    assert "builder làm lại với hint" in msg.body
    assert msg.link == f"{PUBLIC}/#/truc-ban/gate/TCK-7"
    assert msg.priority == "default"
    # gate đã báo rồi thì KHÔNG báo lại ở nhịp sau
    assert n.observe([_gate("REL-001"), _gate("TCK-7", kind="escalation")]) == []
    assert len(post.calls) == 2


def test_gate_qua_han_mang_uu_tien_cao() -> None:
    post = _Post()
    n = _notifier(post)
    n.observe([])
    (msg,) = n.observe([_gate("REL-001", hours=30, sev="over")])
    assert msg.priority == "high" and "quá hạn" in msg.body


def test_gate_bien_mat_roi_xuat_hien_lai_thi_bao_lai() -> None:
    """Từ chối gate → ticket làm lại → gate mở lại CÙNG subject_id: đó là một lượt chờ người mới, phải báo lại.
    Bộ nhớ "đã báo" chỉ giữ những gate còn đang chờ."""
    post = _Post()
    n = _notifier(post)
    n.observe([])
    assert len(n.observe([_gate("TCK-7")])) == 1
    assert n.observe([]) == []
    assert len(n.observe([_gate("TCK-7")])) == 1
    assert n.status()["sent"] == 2


def test_cung_id_o_hai_xuong_la_hai_gate() -> None:
    post = _Post()
    n = _notifier(post)
    n.observe([])
    sent = n.observe([_gate("KEEP-1", xuong="software-company"), _gate("KEEP-1", xuong="keeper")])
    assert len(sent) == 2 and {m.link for m in sent} == {f"{PUBLIC}/#/truc-ban/gate/KEEP-1"}
    assert sorted(m.body.split("\n")[0] for m in sent)[0].startswith("keeper")


def test_id_co_ky_tu_la_duoc_ma_hoa_trong_link() -> None:
    post = _Post()
    n = _notifier(post)
    n.observe([])
    (msg,) = n.observe([_gate("CLARIFY-P 1", kind="clarification")])
    assert msg.link == f"{PUBLIC}/#/truc-ban/gate/CLARIFY-P%201"


def test_khong_kenh_nao_thi_tat_va_khong_gui() -> None:
    post = _Post()
    n = nt.Notifier([], public_url=PUBLIC, post=post)
    assert n.enabled is False
    assert n.observe([_gate("REL-001")]) == []
    assert n.observe([_gate("REL-001"), _gate("X")]) == []
    assert post.calls == []
    st = n.status()
    assert st["enabled"] is False and st["channels"] == [] and st["sent"] == 0


# --- lỗi gửi: đếm, không ném, không lộ bí mật -----------------------------------------------------------------

@pytest.mark.parametrize("post", [_Post(status=500), _Post(boom=OSError("mạng đứt"))])
def test_kenh_hong_thi_dem_va_khong_nem(post: _Post) -> None:
    n = _notifier(post, nt.TelegramChannel("1:x", "4242"))
    n.observe([])
    sent = n.observe([_gate("REL-001")])
    assert len(sent) == 1, "tin vẫn được dựng và thử gửi"
    st = n.status()
    assert st["failed"] == 1 and st["sent"] == 0
    assert st["last_error"] and "telegram" in st["last_error"]
    assert "1:x" not in st["last_error"] and "api.telegram.org" not in st["last_error"]


def test_mot_kenh_hong_khong_can_kenh_kia() -> None:
    calls: list[str] = []

    def post(url: str, data: bytes, headers: dict[str, str]) -> int:
        calls.append(url)
        return 503 if "ntfy" in url else 200

    n = nt.Notifier([nt.NtfyChannel("https://ntfy.sh/t"), nt.TelegramChannel("1:x", "4242")],
                    public_url=PUBLIC, post=post)
    n.observe([])
    n.observe([_gate("REL-001")])
    assert len(calls) == 2
    st = n.status()
    assert st["sent"] == 1 and st["failed"] == 1 and st["last_sent_at"]


# --- hai kênh: đúng giao thức -------------------------------------------------------------------------------------

def test_ntfy_post_than_utf8_vao_topic_kem_click_va_priority() -> None:
    post = _Post()
    n = _notifier(post, nt.NtfyChannel("https://ntfy.sh/xagents-thu"))
    n.observe([])
    n.observe([_gate("REL-001", hours=30, sev="over", title="Đăng nhập")])
    (url, data, headers) = post.calls[0]
    assert url == "https://ntfy.sh/xagents-thu"
    assert "Đăng nhập" in data.decode("utf-8") and "REL-001" in data.decode("utf-8")
    assert headers["Click"] == f"{PUBLIC}/#/truc-ban/gate/REL-001"
    assert headers["Priority"] == "high"
    assert headers["Content-Type"].startswith("text/plain")
    # tiêu đề đi trong thân (dòng đầu), KHÔNG qua header `Title`: header HTTP không mang được tiếng Việt
    assert "Title" not in headers
    assert data.decode("utf-8").splitlines()[0] == "Gate chờ: release · REL-001"


def test_telegram_post_json_toi_sendmessage_va_khong_lo_token() -> None:
    post = _Post()
    ch = nt.TelegramChannel("1:x", "4242")
    n = _notifier(post, ch)
    n.observe([])
    n.observe([_gate("REL-001")])
    (url, data, headers) = post.calls[0]
    assert url == "https://api.telegram.org/bot1:x/sendMessage"
    body = json.loads(data)
    assert body["chat_id"] == "4242" and "REL-001" in body["text"] and f"{PUBLIC}/#/truc-ban/gate/REL-001" in body["text"]
    assert body["disable_web_page_preview"] is True
    assert headers["Content-Type"].startswith("application/json")
    assert ch.name == "telegram:4242" and "1:x" not in repr(ch) and "1:x" not in str(n.status())


def test_http_post_that_gui_duoc_va_tra_ma_loi_thay_vi_nem(tmp_path: Path) -> None:
    """`http_post` mặc định: urllib, timeout ngắn, mã HTTP lỗi (4xx/5xx) trả về như một số chứ không ném — Notifier
    đếm nó như một lần hỏng. Dựng một HTTP server tí hon tại chỗ để không chạm mạng."""
    seen: list[tuple[str, bytes, str]] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            seen.append((self.path, self.rfile.read(n), self.headers.get("X-Thu") or ""))
            code = 500 if self.path.endswith("/hong") else 200
            self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()

        def log_message(self, *a: Any) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert nt.http_post(f"{base}/ok", "xin chào".encode(), {"X-Thu": "1"}) == 200
        assert nt.http_post(f"{base}/hong", b"x", {}) == 500
        with pytest.raises(OSError):
            nt.http_post("http://127.0.0.1:9/khong-ai-nghe", b"x", {}, timeout=0.5)
    finally:
        srv.shutdown(); srv.server_close()
    assert seen[0] == ("/ok", "xin chào".encode(), "1")


# --- NotifyWatcher: đọc bus thật qua collect, chỉ khi dấu vân tay đổi ---------------------------------------------

def test_watcher_doc_bus_that_bao_tom_tat_roi_bao_gate_moi(tmp_path: Path) -> None:
    db = build_company_db(tmp_path / "company.sqlite")  # REL-001 chờ 30 h; SPEC-1 đã quyết
    post = _Post()
    n = _notifier(post)
    w = nt.NotifyWatcher(n, (db, None))
    first = w.step()
    assert len(first) == 1 and "1 gate" in first[0].title and "REL-001" in first[0].body
    assert w.step() == [], "bus không đổi thì không đọc lại, không gửi lại"
    bus = CompanySQLiteBus(db)
    gate_request(bus, CompanyEnvelope, CompanyAudit, kind="escalation", subject_id="TCK-112",
                 checklist=["root_cause"], created_by="delivery-lead")
    bus.close()
    (msg,) = w.step()
    assert msg.title == "Gate chờ: escalation · TCK-112" and msg.priority == "default"
    assert "API đăng nhập" in msg.body, "tiêu đề ticket thật từ collect, không phải id trần"
    assert n.status()["watching"] == 2


def test_watcher_khong_goi_collect_khi_dau_van_tay_khong_doi(tmp_path: Path) -> None:
    db = build_company_db(tmp_path / "company.sqlite")
    calls = 0

    def fake_collect(*a: Any, **k: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"gates": []}

    w = nt.NotifyWatcher(_notifier(_Post()), (db, None), collect=fake_collect)
    w.step(); w.step(); w.step()
    assert calls == 1


def test_watcher_collect_nem_thi_ghi_loi_khong_chet(tmp_path: Path) -> None:
    db = build_company_db(tmp_path / "company.sqlite")

    def bad_collect(*a: Any, **k: Any) -> dict[str, Any]:
        raise RuntimeError("bus khoá")

    n = _notifier(_Post())
    w = nt.NotifyWatcher(n, (db, None), collect=bad_collect)
    assert w.step() == []
    assert "bus khoá" in (n.status()["last_error"] or "")
    # lần sau bus đổi thì vẫn thử lại (dấu vân tay chưa được ghi nhận khi collect hỏng)
    w.collect = lambda *a, **k: {"gates": [_gate("REL-001")]}  # type: ignore[assignment]
    assert len(w.step()) == 1


def test_watcher_thread_chay_va_dung_duoc(tmp_path: Path) -> None:
    db = build_company_db(tmp_path / "company.sqlite")
    post = _Post()
    w = nt.NotifyWatcher(_notifier(post), (db, None), interval=0.05)
    w.start()
    try:
        deadline = threading.Event()
        for _ in range(100):
            if post.calls: break
            deadline.wait(0.05)
        assert post.calls, "thread phải tự quan sát và gửi tin tóm tắt"
    finally:
        w.stop()
    assert not w.is_alive()
    w.stop()  # dừng hai lần không sao


# --- dựng từ dòng lệnh: token chỉ từ env, cờ thiếu thì nói ---------------------------------------------------------

def test_build_notifier_tu_co_va_env() -> None:
    n = nt.build_notifier(ntfy="https://ntfy.sh/t", telegram_chat="4242", public_url="https://x.example/",
                          env={"CONSOLE_TELEGRAM_TOKEN": "1:x"})
    assert n.enabled and n.status()["channels"] == ["ntfy:https://ntfy.sh/t", "telegram:4242"]
    assert n.public_url == "https://x.example"


def test_build_notifier_telegram_thieu_token_thi_tu_choi() -> None:
    with pytest.raises(nt.NotifyConfigError, match="CONSOLE_TELEGRAM_TOKEN"):
        nt.build_notifier(ntfy=None, telegram_chat="4242", public_url="http://127.0.0.1:8200", env={})


def test_build_notifier_ntfy_khong_phai_https_thi_tu_choi() -> None:
    """Topic ntfy là địa chỉ công khai; gửi qua http thường là phát tên gate và link console ra đường."""
    with pytest.raises(nt.NotifyConfigError, match="https"):
        nt.build_notifier(ntfy="http://ntfy.sh/t", telegram_chat=None, public_url="http://127.0.0.1:8200", env={})
    n = nt.build_notifier(ntfy="http://127.0.0.1:2586/t", telegram_chat=None, public_url="http://127.0.0.1:8200", env={})
    assert n.enabled, "ntfy tự host trên loopback thì http được"


def test_build_notifier_khong_co_gi_thi_tat() -> None:
    n = nt.build_notifier(ntfy=None, telegram_chat=None, public_url="http://127.0.0.1:8200", env={})
    assert n.enabled is False


# --- nối vào server: thread sống cùng server, trạng thái trong /api/state --------------------------------------

def _http(port: int, token: str, path: str) -> tuple[int, Any]:
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"X-Console-Token": token})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


def test_server_bat_watcher_khi_co_kenh_va_tat_cung_server(tmp_path: Path) -> None:
    from console import server as srv

    static = tmp_path / "static"; static.mkdir()
    (static / "index.html").write_text("<html></html>", encoding="utf-8")
    db = build_company_db(tmp_path / "company.sqlite")
    post = _Post()
    n = nt.Notifier([nt.NtfyChannel("https://ntfy.sh/t")], public_url=PUBLIC, post=post)
    server = srv.make_server("127.0.0.1", 0, static_dir=static, company_db=db, notifier=n)
    t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
    try:
        assert server.notify_watcher is not None and server.notify_watcher.is_alive()
        for _ in range(100):
            if post.calls: break
            threading.Event().wait(0.05)
        assert post.calls, "watcher phải gửi tin tóm tắt mà không cần ai mở /api/stream"
        code, state = _http(server.port, server.token, "/api/state")
        assert code == 200
        assert state["notify"]["enabled"] is True and state["notify"]["channels"] == ["ntfy:https://ntfy.sh/t"]
        assert state["notify"]["sent"] == 1 and state["notify"]["watching"] == 1
    finally:
        server.shutdown(); server.server_close()
    assert not server.notify_watcher.is_alive(), "con của console chết cùng console (như động cơ, ADR-0004)"


def test_server_khong_kenh_thi_khong_thread_nhung_state_van_khai(tmp_path: Path) -> None:
    from console import server as srv

    static = tmp_path / "static"; static.mkdir()
    (static / "index.html").write_text("<html></html>", encoding="utf-8")
    server = srv.make_server("127.0.0.1", 0, static_dir=static)
    t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
    try:
        assert server.notify_watcher is None
        code, state = _http(server.port, server.token, "/api/state")
        assert code == 200 and state["notify"] == {"enabled": False, "channels": [], "sent": 0, "failed": 0,
                                                    "last_error": None, "last_sent_at": None, "watching": 0}
    finally:
        server.shutdown(); server.server_close()


# --- dòng lệnh ----------------------------------------------------------------------------------------------------

def test_cli_notify_ntfy_dung_notifier_va_in_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from console import __main__ as cli
    from test_main import _FakeServer

    got: dict[str, Any] = {}
    fake = _FakeServer()

    def fake_make_server(*a: Any, **k: Any) -> _FakeServer:
        got.update(k)
        return fake

    monkeypatch.setattr(cli, "make_server", fake_make_server)
    assert cli.main(["--notify-ntfy", "https://ntfy.sh/xagents-thu", "--public-url", "https://x.example/"]) == 0
    n = got["notifier"]
    assert isinstance(n, nt.Notifier) and n.status()["channels"] == ["ntfy:https://ntfy.sh/xagents-thu"]
    assert n.public_url == "https://x.example"
    out = capsys.readouterr().out
    assert "Thông báo:" in out and "ntfy" in out and "https://x.example" in out


def test_cli_khong_notify_thi_banner_noi_cach_bat_va_public_url_mac_dinh(monkeypatch: pytest.MonkeyPatch,
                                                                         capsys: pytest.CaptureFixture[str]) -> None:
    from console import __main__ as cli
    from test_main import _FakeServer

    got: dict[str, Any] = {}
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: (got.update(k), _FakeServer())[1])
    assert cli.main(["--port", "8211"]) == 0
    n = got["notifier"]
    assert n.enabled is False and n.public_url == "http://127.0.0.1:8211"
    assert "--notify-ntfy" in capsys.readouterr().out


def test_cli_notify_telegram_thieu_token_tra_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from console import __main__ as cli

    monkeypatch.delenv(nt.TELEGRAM_TOKEN_ENV, raising=False)
    called = False

    def boom(*a: Any, **k: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "make_server", boom)
    assert cli.main(["--notify-telegram", "4242"]) == 2
    assert not called, "cấu hình sai thì dừng TRƯỚC khi mở cổng"
    assert nt.TELEGRAM_TOKEN_ENV in capsys.readouterr().out


def test_cli_notify_telegram_lay_token_tu_env(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from console import __main__ as cli
    from test_main import _FakeServer

    monkeypatch.setenv(nt.TELEGRAM_TOKEN_ENV, "1:x")
    got: dict[str, Any] = {}
    monkeypatch.setattr(cli, "make_server", lambda *a, **k: (got.update(k), _FakeServer())[1])
    assert cli.main(["--notify-telegram", "4242"]) == 0
    assert got["notifier"].status()["channels"] == ["telegram:4242"]
    out = capsys.readouterr().out
    assert "telegram:4242" in out and "1:x" not in out
