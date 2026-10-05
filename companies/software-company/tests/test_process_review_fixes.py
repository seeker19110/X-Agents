"""Rà soát quy trình: các lỗi tìm được ở vòng review, blackboard, đo lường và tool web.

Mỗi test dưới đây thất bại trên bản trước khi sửa.
"""
from __future__ import annotations

import json
import socket
import threading

import pytest

from company import web as web_mod
from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Envelope, Task
from company.gate_cli import PersistentGate
from company.metrics import collect
from company.tools import ToolError
from company.web import _parse_ddg, check_url, resolve_host

T1 = {"ticket_id": "T1", "project_id": "P1", "requirement_id": "REQ-1", "assignee": "builder", "title": "GET /orders",
      "acceptance": ["given/when/then"], "estimate_tokens": 4_000, "budget_tokens": 6_000}
PR = {"ticket_id": "T1", "branch": "ticket/T1", "pr_ref": "#1", "local_checks": {"lint": True, "tests": True}}


def _lead(bus: InMemoryBus) -> DeliveryLead:
    gate = PersistentGate(bus); lead = DeliveryLead(bus, gate)
    lead.plans_ok.add("PLAN-1")   # ADR-0037: không còn gate plan
    lead.dispatch(Task.model_validate(T1), "PLAN-1")
    return lead


def _review(bus: InMemoryBus, source: str, verdict: str = "pass") -> None:
    bus.publish(Envelope(topic="review-results", key="T1", actor="qa",
                         payload={"ticket_id": "T1", "source": source, "verdict": verdict}))


# ---------- vòng review ----------

def test_review_tre_khong_pha_trang_thai_ticket_da_approved():
    """Review đến sau khi ticket đã rời vòng review (người review chậm, hoặc bị giao lại) bị bỏ qua.
    Trước đây nó được gộp vào rồi ép `approved → approved` và ném ValueError ra khỏi bus.publish."""
    bus = InMemoryBus(); lead = _lead(bus)
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="builder", payload=PR))
    _review(bus, "reviewer"); _review(bus, "qa")
    assert lead.state["T1"] == "approved"
    _review(bus, "reviewer")  # bản sao đến trễ
    assert lead.state["T1"] == "approved"


def test_review_tre_khi_ticket_da_changes_requested_khong_lam_no_approved():
    bus = InMemoryBus(); lead = _lead(bus)
    T2 = {**T1, "risk_tags": ["payment"]}  # cần thêm security
    lead.tickets["T1"] = Task.model_validate(T2)
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="builder", payload=PR))
    _review(bus, "reviewer"); _review(bus, "qa", "fail"); _review(bus, "security")
    assert lead.state["T1"] != "approved"


def test_pr_thu_hai_thay_pr_cu_thay_vi_ném_loi():
    """PR mới khi ticket đang in_review = PR thay thế: vòng review làm lại, không phải chuyển trạng thái sai."""
    bus = InMemoryBus(); lead = _lead(bus)
    lead.tickets["T1"] = lead.tickets["T1"].model_copy(update={"risk_tags": ["pii"]})  # cần thêm qa + security
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="builder", payload=PR))
    _review(bus, "reviewer")
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="builder", payload={**PR, "pr_ref": "#2"}))
    assert lead.state["T1"] == "in_review"
    assert lead.reviews["T1"] == {}, "review của PR cũ không được tính cho PR mới"


# ---------- blackboard ----------

def test_hai_chu_namespace_ghi_song_song_khong_mat_ban_ghi(monkeypatch):
    """`api-contract` có hai chủ (product, builder). Đánh version là đọc-sửa-ghi nên chạy song song
    (--workers > 1) mà không khoá thì cả hai cùng ra v1 và bản sau bị `_on` bỏ im lặng.

    `scope_of` chạy ngay trước lúc đọc version: cho cả hai luồng gặp nhau ở đúng điểm đó bằng Barrier mở đúng cửa
    sổ tranh chấp một cách xác định — không sleep, nên không phụ thuộc tốc độ máy."""
    bus = InMemoryBus(); bb = Blackboard(bus)
    real = bb.scope_of          # K3.6b: `scope_of` là PHƯƠNG THỨC (nó đọc `global_namespaces` từ `cfg`),
    inside = threading.Barrier(2, timeout=10)   # nên vá trên instance chứ không trên module

    def _scope(ns, pid):
        try: inside.wait()      # cả hai luồng phải cùng ở trong scope_of rồi mới đi tiếp
        except threading.BrokenBarrierError: pass
        return real(ns, pid)
    monkeypatch.setattr(bb, "scope_of", _scope)

    def w(actor: str) -> None:
        bb.write(actor, "api-contract", "openapi.yaml", actor, content=actor * 50, project_id="P1")

    ts = [threading.Thread(target=w, args=(a,)) for a in ("product", "builder")]
    for t in ts: t.start()
    for t in ts: t.join()
    versions = [e.payload["version"] for e in bus.replay(topic="shared-context")]
    assert sorted(versions) == [1, 2], versions
    assert bb.read("api-contract", "P1").version == 2


# ---------- đo lường ----------

def test_ticket_closed_khong_tao_lead_time_khi_khong_co_nhanh_tich_hop():
    """Dự án không có repo vẫn đóng ticket, nhưng chưa có mốc merge để tính lead time."""
    from company.llm import FakeClient
    from company.orchestrator import Orchestrator
    from test_orchestrator import _drive_to_plan, _pub, handler

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    _pub(bus, "acceptance-results", "REL-001", "ops",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    assert orch.lead.state["T1"] == "closed"
    closed = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "ticket.closed"]
    assert [a["ticket_id"] for a in closed] == ["T1"], "phát đúng một lần cho mỗi ticket"
    assert "T1" not in collect(bus)["ticket_lead_seconds"]


# ---------- tool web ----------

class _Resp:
    def __init__(self, status, headers=None, body=b""):
        self.status, self.headers, self.body = status, headers or {}, body
    def getheader(self, k, default=None): return self.headers.get(k, default)
    def read(self, n=-1):   # như HTTPResponse thật: đọc hết rồi trả b"" (fetcher đọc theo khối, có hạn tổng)
        out, self.body = (self.body if n is None or n < 0 else self.body[:n]), (b"" if n is None or n < 0 else self.body[n:])
        return out
    def close(self): ...
    def __enter__(self): return self
    def __exit__(self, *a): ...


def _dns(monkeypatch, table):
    calls = []
    def fake(host, port, *a, **k):
        calls.append(host)
        if host not in table: raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]
    monkeypatch.setattr(web_mod.socket, "getaddrinfo", fake)
    return calls


def test_chuyen_huong_ve_host_noi_bo_bi_chan(monkeypatch):
    """check_url chỉ gác URL đầu; fetcher tự theo 302 và phải gác lại từng chặng."""
    _dns(monkeypatch, {"example.com": "93.184.216.34", "169.254.169.254": "169.254.169.254", "localhost": "127.0.0.1"})
    for target in ("http://169.254.169.254/latest/meta-data/", "http://localhost:8080/"):
        monkeypatch.setattr(web_mod, "_open_pinned", lambda url, ip, t, target=target: _Resp(302, {"Location": target}))
        with pytest.raises(ToolError, match="host bị chặn"):
            web_mod.default_fetcher("https://example.com/")


def test_fetcher_ghim_ip_da_kiem_va_theo_chuyen_huong_cong_khai(monkeypatch):
    """DNS rebinding: phân giải một lần, kết nối đúng IP đã kiểm ở mỗi chặng; quá MAX_REDIRECTS thì dừng."""
    calls = _dns(monkeypatch, {"a.example": "93.184.216.34", "b.example": "1.1.1.1"})
    seen = []
    def opener(url, ip, t):
        seen.append((url, ip))
        return _Resp(301, {"Location": "https://b.example/x?y=1"}) if "a.example" in url else _Resp(200, {"Content-Type": "text/plain"}, b"ok")
    monkeypatch.setattr(web_mod, "_open_pinned", opener)
    assert web_mod.default_fetcher("https://a.example/") == (200, "text/plain", b"ok")
    assert seen == [("https://a.example/", "93.184.216.34"), ("https://b.example/x?y=1", "1.1.1.1")]
    assert calls == ["a.example", "b.example"], "mỗi chặng phân giải đúng một lần"
    monkeypatch.setattr(web_mod, "_open_pinned", lambda url, ip, t: _Resp(302, {"Location": "https://a.example/loop"}))
    with pytest.raises(ToolError, match="chuyển hướng"):
        web_mod.default_fetcher("https://a.example/")


def test_ket_noi_ghim_ip_giu_host_va_sni(monkeypatch):
    seen = []
    monkeypatch.setattr(web_mod.socket, "create_connection", lambda addr, timeout=None, *a, **k: (seen.append(addr), object())[1])
    c = web_mod._PinnedHTTPConnection("example.com", 8080, pinned_ip="93.184.216.34", timeout=1)
    c.connect()
    assert seen == [("93.184.216.34", 8080)] and c.host == "example.com"   # header Host lấy từ `host`, không phải IP
    sni = []
    class _Ctx:
        def wrap_socket(self, sock, server_hostname=None): sni.append(server_hostname); return sock
    cs = web_mod._PinnedHTTPSConnection("example.com", 443, pinned_ip="93.184.216.34", timeout=1)
    cs._context = _Ctx(); cs.connect()
    assert seen[-1] == ("93.184.216.34", 443) and sni == ["example.com"]


def test_search_url_noi_bo_cua_nguoi_van_hanh_duoc_phep_con_url_cua_model_thi_khong(monkeypatch):
    _dns(monkeypatch, {"searx.internal": "10.0.0.5"})
    body = json.dumps({"results": [{"title": "t", "url": "https://x.example/", "content": "c"}]}).encode()
    fetched = []
    def fetcher(url): fetched.append(url); return 200, "application/json", body
    web = web_mod.WebTools(fetcher=fetcher, search_url="http://searx.internal:8080/search?q={q}&format=json")
    assert web.trusted_hosts == frozenset({"searx.internal:8080"}), "tin theo host:port, không phải host trần"
    assert "1. t" in web.web_search("abc") and fetched == ["http://searx.internal:8080/search?q=abc&format=json"]
    with pytest.raises(ToolError, match="host bị chặn"):   # cùng host nhưng do model đưa qua fetch_url: vẫn chặn
        web.fetch_url("http://searx.internal:8080/admin")
    with pytest.raises(ToolError, match="http/https"):     # scheme vẫn bị kiểm với URL cấu hình
        web_mod.WebTools(fetcher=fetcher, search_url="file:///etc/passwd?{q}").web_search("abc")
    d = web_mod.WebTools(search_url="http://searx.internal/?q={q}")
    assert d.fetcher.keywords == {"trusted_hosts": frozenset({"searx.internal:80"})}   # fetcher mặc định mang danh sách tin cậy


def test_check_url_van_chan_o_chang_dau():
    with pytest.raises(ToolError):
        check_url("http://127.0.0.1/")


def test_resolve_host_bao_loi_khi_khong_phan_giai_duoc(monkeypatch):
    def boom(host, port):
        raise socket.gaierror("không phân giải được")
    monkeypatch.setattr(web_mod.socket, "getaddrinfo", boom)
    with pytest.raises(ToolError, match="host bị chặn"):
        resolve_host("khong-ton-tai.invalid")


def test_blocked_host_true_khi_resolve_host_bao_loi(monkeypatch):
    _dns(monkeypatch, {"trong.internal": "127.0.0.1"})
    assert web_mod._blocked_host("trong.internal") is True
    _dns(monkeypatch, {"ngoai.example": "93.184.216.34"})
    assert web_mod._blocked_host("ngoai.example") is False


def test_open_pinned_dung_dung_connection_theo_scheme(monkeypatch):
    """`_open_pinned` chọn `_PinnedHTTPSConnection`/`_PinnedHTTPConnection` theo scheme và trả response thật."""
    seen = {}

    class FakeConn:
        def __init__(self, host, port, pinned_ip=None, timeout=None):
            seen["host"], seen["port"], seen["ip"] = host, port, pinned_ip
        def request(self, method, path, headers=None):
            seen["method"], seen["path"] = method, path
        def getresponse(self):
            return _Resp(200, {"Content-Type": "text/plain"}, b"ok")

    monkeypatch.setattr(web_mod, "_PinnedHTTPSConnection", FakeConn)
    monkeypatch.setattr(web_mod, "_PinnedHTTPConnection", FakeConn)
    r = web_mod._open_pinned("https://example.com/p?x=1", "93.184.216.34", 5)
    assert r.status == 200 and seen["ip"] == "93.184.216.34" and seen["path"] == "/p?x=1"


def test_default_fetcher_bao_loi_khi_ket_noi_hong(monkeypatch):
    """Lỗi mạng thật (HTTPException/TimeoutError/OSError) lúc mở kết nối phải hoá thành ToolError rõ, không rò traceback."""
    _dns(monkeypatch, {"loi.example": "93.184.216.34"})
    def boom(url, ip, t):
        raise ConnectionResetError("kết nối bị đóng")
    monkeypatch.setattr(web_mod, "_open_pinned", boom)
    with pytest.raises(ToolError, match="không lấy được"):
        web_mod.default_fetcher("https://loi.example/")


def test_fetch_url_json_hong_giu_nguyen_van_ban_goc(monkeypatch):
    _dns(monkeypatch, {"x.example": "93.184.216.34"})
    def fetcher(url):
        return 200, "application/json", b"{khong phai json hop le"
    web = web_mod.WebTools(fetcher=fetcher)
    out = web.fetch_url("https://x.example/")
    assert "khong phai json hop le" in out


def test_web_search_voi_search_url_json_hong_bao_loi_ro(monkeypatch):
    """Nhánh có `search_url`: JSON hỏng phải báo lỗi rõ, không sập (dòng 184-185)."""
    _dns(monkeypatch, {"searx.internal": "10.0.0.5"})
    def fetcher(url):
        return 200, "application/json", b"khong phai json"
    web = web_mod.WebTools(fetcher=fetcher, search_url="http://searx.internal:8080/search?q={q}&format=json")
    assert web.web_search("abc") == "lỗi: máy tìm kiếm không trả JSON {results: [...]}"


def test_resolve_host_bao_loi_khi_getaddrinfo_tra_danh_sach_rong(monkeypatch):
    """web.py 61->exit: `getaddrinfo` không ném lỗi nhưng trả danh sách rỗng (máy/hệ điều hành lạ) → vẫn bị chặn
    như không phân giải được, không để `ips[0]` sập với IndexError."""
    monkeypatch.setattr(web_mod.socket, "getaddrinfo", lambda host, port: [])
    with pytest.raises(ToolError, match="host bị chặn"):
        resolve_host("rong.example")


def test_default_fetcher_qua_han_tong_giua_chung_chuyen_huong(monkeypatch):
    """web.py 147->exit: hạn tổng cho CẢ lượt (kể cả theo chuyển hướng) hết ngay giữa vòng lặp, không phải chỉ ở
    lần gọi socket đầu — mỗi chặng đều phải kiểm `deadline`, không chỉ chặng cuối."""
    _dns(monkeypatch, {"a.example": "93.184.216.34", "b.example": "1.1.1.1"})
    times = iter([0.0, 0.0, 100.0])  # đủ cho: deadline=T0+60, lần kiểm đầu (left>0), lần kiểm hai (đã quá hạn)

    def fake_monotonic():
        return next(times, 100.0)
    monkeypatch.setattr(web_mod.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(web_mod, "_open_pinned",
                        lambda url, ip, t: _Resp(301, {"Location": "https://b.example/"}))
    with pytest.raises(ToolError, match=f"quá {web_mod.TOTAL_TIMEOUT}s cho cả lượt lấy"):
        web_mod.default_fetcher("https://a.example/")


def test_read_deadline_dung_dung_khi_du_max_bytes(monkeypatch):
    """web.py 165->171: đọc đủ (hoặc vượt) `MAX_BYTES` thì vòng lặp dừng bằng điều kiện `while`, không cần chạm
    hạn thời gian — trả đúng phần đã đọc, không đọc thêm."""
    monkeypatch.setattr(web_mod, "MAX_BYTES", 10)
    r = _Resp(200, {}, b"0123456789ABCDEF")  # 16 byte > MAX_BYTES=10
    out = web_mod._read_deadline(r, web_mod.time.monotonic() + 60, "https://x.example/")
    assert len(out) == 11, "đọc tới khi vượt MAX_BYTES rồi dừng ở lần đọc kế tiếp"


def test_fetch_url_http_loi_tra_thong_bao_khong_lay_noi_dung(monkeypatch):
    """HTTP >= 400 → trả thông báo lỗi ngay, không đụng tới thân trang."""
    _dns(monkeypatch, {"loi.example": "93.184.216.34"})
    def fetcher(url):
        return 404, "text/plain", b"not found"
    web = web_mod.WebTools(fetcher=fetcher)
    out = web.fetch_url("https://loi.example/")
    assert out == "lỗi: HTTP 404 cho https://loi.example/"


def test_fetch_url_trang_qua_lon_bao_loi_ro(monkeypatch):
    """web.py 208->exit: `fetcher` (đã tự giới hạn theo `MAX_BYTES` khi đọc stream) vẫn có thể trả về đúng-bằng
    hoặc lớn hơn hạn — `fetch_url` phải tự kiểm lại, không tin dữ liệu đã đủ nhỏ."""
    monkeypatch.setattr(web_mod, "MAX_BYTES", 10)
    _dns(monkeypatch, {"lon.example": "93.184.216.34"})
    def fetcher(url):
        return 200, "text/plain", b"noi dung dai hon muoi byte"
    web = web_mod.WebTools(fetcher=fetcher)
    out = web.fetch_url("https://lon.example/")
    assert out == "lỗi: trang > 10 byte"


def test_fetch_url_van_ban_thuan_khong_qua_html_to_text(monkeypatch):
    """web.py 213->215: nội dung KHÔNG phải JSON và không phải HTML (content-type `text/plain`, không mở đầu
    bằng `<`) → giữ nguyên văn bản, không đi qua `html_to_text`."""
    _dns(monkeypatch, {"txt.example": "93.184.216.34"})
    def fetcher(url):
        return 200, "text/plain", b"chi la van ban thuan, khong the/tag nao"
    web = web_mod.WebTools(fetcher=fetcher)
    out = web.fetch_url("https://txt.example/")
    assert "chi la van ban thuan" in out


def test_web_search_query_rong_bao_loi_ro():
    web = web_mod.WebTools(fetcher=lambda url: (200, "", b""))
    assert web.web_search("   ") == "lỗi: query rỗng"


def test_web_search_search_url_http_loi(monkeypatch):
    """web.py 231->exit: nhánh CÓ `search_url` mà máy tìm kiếm trả HTTP lỗi."""
    _dns(monkeypatch, {"searx.internal": "10.0.0.5"})
    def fetcher(url):
        return 503, "text/plain", b"unavailable"
    web = web_mod.WebTools(fetcher=fetcher, search_url="http://searx.internal:8080/search?q={q}&format=json")
    assert web.web_search("abc") == "lỗi: HTTP 503 từ máy tìm kiếm"


def test_web_search_duckduckgo_http_loi(monkeypatch):
    """web.py 239->exit: nhánh KHÔNG có `search_url` (duckduckgo) mà HTTP lỗi."""
    _dns(monkeypatch, {"html.duckduckgo.com": "1.1.1.1"})
    def fetcher(url):
        return 500, "text/html", b"error"
    web = web_mod.WebTools(fetcher=fetcher)
    assert web.web_search("abc") == "lỗi: HTTP 500 từ máy tìm kiếm"


def test_web_search_duckduckgo_khong_co_ket_qua(monkeypatch):
    """web.py 241->exit: trang kết quả không khớp regex nào → không phải lỗi, chỉ là rỗng."""
    _dns(monkeypatch, {"html.duckduckgo.com": "1.1.1.1"})
    def fetcher(url):
        return 200, "text/html", b"<html><body>khong co ket qua nao</body></html>"
    web = web_mod.WebTools(fetcher=fetcher)
    assert web.web_search("abc") == "(không có kết quả)"


def test_parse_ddg_link_khong_boc_uddg_giu_nguyen_href():
    """web.py 274->277: href KHÔNG mang tham số `uddg=` (không bọc qua chuyển hướng của DDG) → dùng thẳng href."""
    page = '<a class="result__a" href="https://direct.example/page">Direct hit</a>'
    rows = _parse_ddg(page)
    assert rows and rows[0][1] == "https://direct.example/page"


def test_parse_ddg_lay_duoc_doan_trich_va_khong_muon_cua_ket_qua_sau():
    """`.*?(?:<a class="result__snippet">…</a>)?`: `.*?` lười khớp rỗng rồi nhóm tuỳ chọn cũng khớp rỗng — đoạn trích
    LUÔN rỗng, researcher chỉ thấy tiêu đề + URL. Sửa phải không làm kết quả không có trích "mượn" trích của kết quả
    kế tiếp. Đo hai chiều: regex cũ cho `rows[0][2] == ""`."""
    page = ('<a rel="nofollow" class="result__a" href="https://a.example/">A</a>'
            '<div><a class="result__snippet" href="https://a.example/">trích của A</a></div>'
            '<a rel="nofollow" class="result__a" href="https://b.example/">B</a>'
            '<a rel="nofollow" class="result__a" href="https://c.example/">C</a>'
            '<a class="result__snippet" href="https://c.example/">trích của C</a>')
    rows = _parse_ddg(page)
    assert [(t, s) for t, _, s in rows] == [("A", "trích của A"), ("B", ""), ("C", "trích của C")]
