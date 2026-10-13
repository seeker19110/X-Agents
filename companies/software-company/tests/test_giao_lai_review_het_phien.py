"""Họ lỗi "hết phiên `claude -p`" — đường giao lại review quá hạn và đường giả định câu hỏi làm rõ.

Đo hub thật 2026-10-13 (QLKH-DD-CSV), gói hết phiên 12:16 → "resets … " 16:31 UTC: lượt review gốc của DDCSV-43 (PR
11:57) nằm trong hẹn `defer.until` 16:31; `review_timeout` 2 giờ chạy hết lúc 13:57 → giao lại cho qa, rồi security —
cả hai lượt giao lại gặp 429 → `review.reassign_failed` → escalation DDCSV-43 lúc 13:58, trong khi chẳng có gì hỏng.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from company.bus import InMemoryBus
from company.llm import FakeClient, LLMError, TransientError
from company.orchestrator import Orchestrator
from test_orchestrator import HET_PHIEN, _agent_of, _drive_to_plan, _inp, _pub, handler


def _qa_t2(mode: dict):
    """qa chấm PR của T2 theo `mode["qa"]`: "het" → hết phiên, "loi" → lỗi thật, "ok" → chạy bình thường."""

    def h(system, user):
        if _agent_of(system) == "qa" and "`pull-requests`" in user and '"ticket_id": "T2"' in user:
            mode["n"] += 1
            if mode["qa"] == "het":
                raise TransientError(HET_PHIEN)
            if mode["qa"] == "loi":
                raise LLMError("timeout")
        return handler(system, user)

    return h


def _giao_lai_loi(orch) -> bool:
    return any("giao lại vẫn lỗi" in a.reason for a in orch.supervisor.actions)


def _acts(bus):
    return [e.payload["action"] for e in bus.replay(topic="audit-log")]


def test_review_goc_con_trong_hen_reset_thi_khong_giao_lai():
    mode = {"qa": "het", "n": 0}
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_qa_t2(mode)))
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.lead.state["T2"] == "in_review" and orch.defer_until, "lượt review gốc hoãn tới mốc reset"
    orch.tick(now=datetime.now(UTC) + timedelta(hours=3))
    assert "review.reassign" not in _acts(bus), "lượt gốc còn trong hẹn của backend: giao lại chỉ đập thêm vào 429"
    assert "T2" not in orch.gate.pending


def test_giao_lai_gap_het_phien_thi_hoan_khong_escalate():
    # Lượt gốc lỗi THẬT (không hẹn giờ) để review quá hạn đi tới đường giao lại; gate nó mở là chuyện của lượt gốc.
    mode = {"qa": "loi", "n": 0}
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_qa_t2(mode)))
    _drive_to_plan(bus, orch)
    orch.run()
    mode["qa"] = "het"
    later = datetime.now(UTC) + timedelta(hours=3)
    orch.tick(now=later)
    assert "review.reassign_failed" not in _acts(bus) and not _giao_lai_loi(orch), "429 hết phiên không phải lỗi"
    assert "review.reassign_deferred" in _acts(bus)
    n = mode["n"]
    orch.tick(now=later + timedelta(minutes=5))
    assert mode["n"] == n, "đã hẹn tới mốc reset thì nhịp kế không giao lại"
    mode["qa"] = "ok"
    for k in list(orch.defer_until):
        orch.defer_until[k] = 0.0
    orch.tick(now=later + timedelta(minutes=10))
    assert mode["n"] > n and "review.reassign_failed" not in _acts(bus), "hết hẹn thì giao lại thật, và qua"
    assert not _giao_lai_loi(orch)


def test_gia_dinh_lam_ro_gap_het_phien_hen_theo_moc_reset():
    """`_assume_clarifications` chỉ đọc "thử lại sau Ns": mốc "resets 6:30pm" không thành hẹn → mỗi nhịp hỏi lại."""
    goi = {"n": 0}

    def h(system, user):
        if _agent_of(system) == "product" and "assumed_answers" in _inp(user):
            goi["n"] += 1
            raise TransientError(HET_PHIEN)
        return handler(system, user)

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=h))
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    q = next(iter(bus.replay(topic="clarification-questions")))
    orch.tick(now=q.ts + timedelta(hours=25))
    orch.tick(now=q.ts + timedelta(hours=26))
    assert goi["n"] == 1, "mốc reset của backend phải thành hẹn, nhịp kế không hỏi lại"
