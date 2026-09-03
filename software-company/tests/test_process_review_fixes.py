"""Rà soát quy trình: các lỗi tìm được ở vòng review, blackboard, đo lường và tool web.

Mỗi test dưới đây thất bại trên bản trước khi sửa.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from company import web as web_mod
from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Envelope, Task
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.metrics import collect
from company.tools import ToolError
from company.web import check_url

T1 = {"ticket_id": "T1", "project_id": "P1", "requirement_id": "REQ-1", "assignee": "backend", "title": "GET /orders",
      "acceptance": ["given/when/then"], "estimate_tokens": 4_000, "budget_tokens": 6_000}
PR = {"ticket_id": "T1", "branch": "ticket/T1", "pr_ref": "#1", "local_checks": {"lint": True, "tests": True}}


def _lead(bus: InMemoryBus) -> DeliveryLead:
    gate = PersistentGate(bus); lead = DeliveryLead(bus, gate)
    gate.request(GateRequest(kind="plan", subject_id="PLAN-1", created_by="delivery-lead", checklist=["tickets"]))
    gate.decide("PLAN-1", "approve", by="human:pm")
    lead.dispatch(Task.model_validate(T1), "PLAN-1")
    return lead


def _review(bus: InMemoryBus, source: str, verdict: str = "pass") -> None:
    bus.publish(Envelope(topic="review-results", key="T1", actor="reviewer",
                         payload={"ticket_id": "T1", "source": source, "verdict": verdict}))


# ---------- vòng review ----------

def test_review_tre_khong_pha_trang_thai_ticket_da_approved():
    """Review đến sau khi ticket đã rời vòng review (người review chậm, hoặc bị giao lại) bị bỏ qua.
    Trước đây nó được gộp vào rồi ép `approved → approved` và ném ValueError ra khỏi bus.publish."""
    bus = InMemoryBus(); lead = _lead(bus)
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="backend", payload=PR))
    _review(bus, "reviewer"); _review(bus, "qa")
    assert lead.state["T1"] == "approved"
    _review(bus, "reviewer")  # bản sao đến trễ
    assert lead.state["T1"] == "approved"


def test_review_tre_khi_ticket_da_changes_requested_khong_lam_no_approved():
    bus = InMemoryBus(); lead = _lead(bus)
    T2 = {**T1, "risk_tags": ["payment"]}  # cần thêm security
    lead.tickets["T1"] = Task.model_validate(T2)
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="backend", payload=PR))
    _review(bus, "reviewer"); _review(bus, "qa", "fail"); _review(bus, "security")
    assert lead.state["T1"] != "approved"


def test_pr_thu_hai_thay_pr_cu_thay_vi_ném_loi():
    """PR mới khi ticket đang in_review = PR thay thế: vòng review làm lại, không phải chuyển trạng thái sai."""
    bus = InMemoryBus(); lead = _lead(bus)
    lead.tickets["T1"] = lead.tickets["T1"].model_copy(update={"risk_tags": ["pii"]})  # cần thêm qa + security
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="backend", payload=PR))
    _review(bus, "reviewer")
    bus.publish(Envelope(topic="pull-requests", key="T1", actor="backend", payload={**PR, "pr_ref": "#2"}))
    assert lead.state["T1"] == "in_review"
    assert lead.reviews["T1"] == {}, "review của PR cũ không được tính cho PR mới"


# ---------- blackboard ----------

def test_hai_chu_namespace_ghi_song_song_khong_mat_ban_ghi(monkeypatch):
    """`api-contract` có hai chủ (delivery-lead, backend). Đánh version là đọc-sửa-ghi nên chạy song song
    (--workers > 1) mà không khoá thì cả hai cùng ra v1 và bản sau bị `_on` bỏ im lặng.

    `scope_of` chạy ngay trước lúc đọc version, nên chèn độ trễ ở đó mở đúng cửa sổ tranh chấp một cách xác định
    thay vì trông chờ vào lịch chuyển luồng của GIL."""
    import company.blackboard as bbm
    real = bbm.scope_of
    monkeypatch.setattr(bbm, "scope_of", lambda ns, pid: (time.sleep(0.05), real(ns, pid))[1])
    bus = InMemoryBus(); bb = Blackboard(bus)
    barrier = threading.Barrier(2)

    def w(actor: str) -> None:
        barrier.wait()
        bb.write(actor, "api-contract", "openapi.yaml", actor, content=actor * 50, project_id="P1")

    ts = [threading.Thread(target=w, args=(a,)) for a in ("delivery-lead", "backend")]
    for t in ts: t.start()
    for t in ts: t.join()
    versions = [e.payload["version"] for e in bus.replay(topic="shared-context")]
    assert sorted(versions) == [1, 2], versions
    assert bb.read("api-contract", "P1").version == 2


# ---------- đo lường ----------

def test_lead_time_ticket_co_so_lieu():
    """`metrics.collect` tính lead time từ audit `ticket.closed`; trước đây không agent nào phát action đó
    nên `ticket_lead_seconds` luôn rỗng và gauge Prometheus không bao giờ xuất hiện."""
    from company.llm import FakeClient
    from company.orchestrator import Orchestrator
    from test_orchestrator import _drive_to_plan, _pub, handler

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.gate.decide("PLAN-P1-1", "approve", by="human:pm"); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    _pub(bus, "acceptance-results", "REL-001", "account-manager",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    assert orch.lead.state["T1"] == "closed"
    closed = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "ticket.closed"]
    assert [a["ticket_id"] for a in closed] == ["T1"], "phát đúng một lần cho mỗi ticket"
    assert "T1" in collect(bus)["ticket_lead_seconds"]


# ---------- tool web ----------

class _Resp:
    def __init__(self, status, headers=None, body=b""):
        self.status, self.headers, self.body = status, headers or {}, body
    def getheader(self, k, default=None): return self.headers.get(k, default)
    def read(self, n=-1): return self.body
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
    assert web.trusted_hosts == frozenset({"searx.internal"})
    assert "1. t" in web.web_search("abc") and fetched == ["http://searx.internal:8080/search?q=abc&format=json"]
    with pytest.raises(ToolError, match="host bị chặn"):   # cùng host nhưng do model đưa qua fetch_url: vẫn chặn
        web.fetch_url("http://searx.internal:8080/admin")
    with pytest.raises(ToolError, match="http/https"):     # scheme vẫn bị kiểm với URL cấu hình
        web_mod.WebTools(fetcher=fetcher, search_url="file:///etc/passwd?{q}").web_search("abc")
    d = web_mod.WebTools(search_url="http://searx.internal/?q={q}")
    assert d.fetcher.keywords == {"trusted_hosts": frozenset({"searx.internal"})}   # fetcher mặc định mang danh sách tin cậy


def test_check_url_van_chan_o_chang_dau():
    with pytest.raises(ToolError):
        check_url("http://127.0.0.1/")
