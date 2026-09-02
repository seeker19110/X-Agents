"""Rà soát quy trình: các lỗi tìm được ở vòng review, blackboard, đo lường và tool web.

Mỗi test dưới đây thất bại trên bản trước khi sửa.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request

import pytest

from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Envelope, Task
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.metrics import collect
from company.tools import ToolError
from company.web import _CheckedRedirect, check_url

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

def test_chuyen_huong_ve_host_noi_bo_bi_chan():
    """check_url chỉ gác URL đầu; urlopen đi theo 302. Handler phải gác lại từng chặng."""
    h = _CheckedRedirect()
    req = urllib.request.Request("https://example.com/")
    with pytest.raises(ToolError, match="host bị chặn"):
        h.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ToolError):
        h.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8080/")


def test_check_url_van_chan_o_chang_dau():
    with pytest.raises(ToolError):
        check_url("http://127.0.0.1/")
