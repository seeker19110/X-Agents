"""Ký Gate 3 mà lượt ops production gặp `TransientError` (backend hết quota/chập chờn) → production phải chạy lại
khi backend hồi, không bị bỏ rơi.

Trước đây `_on_gate_decide` gọi lượt production rồi `_mark` event `gate.decide` bất kể `res.transient`: lỗi tạm
thời nuốt mất quyết định của người — không deploy, không hoãn, không gate nào mở, `status` xanh. Lượt production
chỉ có MỘT đường vào (event `gate.decide`), nên mất event là mất luôn quyết định. Ghi ở `TRAPS.md` ("Còn mở") từ
lượt review 2026-10-02: hoãn event `gate.decide` thì lần xử lý lại không được đếm `escalation_decided` hai lần,
không được áp lại tác dụng của quyết định, và quá trần hoãn thì phải hỏi lại đúng gate đó — không mở escalation
cho subject là tên người ký (`env.key` của audit-log).
"""

from __future__ import annotations

import time

from company.bus import InMemoryBus
from company.llm import FakeClient, TransientError
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _drive_to_plan, handler


def _production_het_quota(orch, monkeypatch):
    goc = orch.runner.generate
    trang_thai = {"het": True}

    def gen(agent, env, topic, *a, **k):
        if trang_thai["het"] and agent == "ops" and env.payload.get("target_env") == "production":
            raise TransientError("backend hết quota")
        return goc(agent, env, topic, *a, **k)

    monkeypatch.setattr(orch.runner, "generate", gen)
    return trang_thai


def _production(bus, rid="REL-001"):
    return [
        e.payload["status"]
        for e in bus.replay(topic="release-events")
        if e.key == rid and e.payload["env"] == "production"
    ]


def _decide_event(bus, sid="REL-001"):
    import json

    return next(
        e
        for e in bus.replay(topic="audit-log")
        if e.payload["action"] == "gate.decide" and json.loads(e.payload["evidence"])["subject_id"] == sid
    )


def _ky_gate3_khi_het_quota(bus, orch, monkeypatch):
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "release"
    quota = _production_het_quota(orch, monkeypatch)
    orch.gate.decide(
        "REL-001", "approve", by="human:release-manager", reason="đủ bằng chứng staging, cho lên production"
    )
    orch.run()
    return quota


def test_ky_gate3_ma_production_tam_thoi_thi_hoan_va_chay_lai_khi_backend_hoi(monkeypatch):
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    quota = _ky_gate3_khi_het_quota(bus, orch, monkeypatch)
    quyet = _decide_event(bus)
    assert _production(bus) == [], "backend hết quota: chưa deploy được"
    assert quyet.event_id not in orch.processed and quyet.event_id in orch.deferred, (
        "lượt production chỉ có một đường vào là event gate.decide — đánh dấu xong là mất quyết định của người"
    )
    assert orch.escalation_decided["REL-001"] == 1

    orch.tick()  # còn hết quota: hoãn tiếp, không đếm lại quyết định
    assert quyet.event_id in orch.deferred and orch.escalation_decided["REL-001"] == 1

    quota["het"] = False
    orch.tick()
    assert _production(bus) == ["deployed"], "backend hồi: quyết định đã ký phải được thi hành"
    assert quyet.event_id in orch.processed and quyet.event_id not in orch.deferred
    assert orch.escalation_decided["REL-001"] == 1, "một quyết định đếm đúng một lần, dù xử lý ba lượt"
    assert orch.lead.state["T1"] == "released"


def test_restart_giua_luc_hoan_van_deploy_va_dem_khop_rehydrate(tmp_path, monkeypatch):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _ky_gate3_khi_het_quota(bus, orch, monkeypatch)
    assert _production(bus) == []
    bus.close()

    bus2 = SQLiteBus(tmp_path / "c.sqlite")
    orch2 = Orchestrator(bus2, FakeClient(handler=handler))
    orch2.run()
    assert _production(bus2) == ["deployed"]
    assert orch2.escalation_decided["REL-001"] == 1
    bus2.close()
    bus3 = SQLiteBus(tmp_path / "c.sqlite")
    orch3 = Orchestrator(bus3, FakeClient(handler=handler))
    assert orch3.escalation_decided["REL-001"] == 1, "đếm sống phải khớp đếm dựng lại từ log"
    bus3.close()


def test_hoan_qua_tran_thi_escalation_dung_release_va_duyet_thi_deploy(monkeypatch):
    """Quá trần hoãn: đường chung `_mark_unhandled` → escalation. Subject phải là `subject_id` trong evidence (REL-001),
    không phải `env.key` của audit-log (tên người ký). Duyệt escalation → `_retry_unhandled` đưa đúng event
    `gate.decide` cũ vào lại hàng đợi — lúc đó gate MỚI NHẤT của REL-001 là escalation, nên lần xử lý lại phải dùng
    loại gate đã gắn lúc hoãn (release), không tra lại `history`."""
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    quota = _ky_gate3_khi_het_quota(bus, orch, monkeypatch)
    quyet = _decide_event(bus)
    orch.transient_since[quyet.event_id] = time.monotonic() - 3 * 3600
    orch.tick()
    assert quyet.event_id in orch.processed and "REL-001" in orch.unhandled
    assert not any(s.startswith("human:") for s in [*orch.gate.pending, *orch.unhandled, *orch.paused]), \
        "subject của gate.decide là subject_id trong evidence, không phải env.key (tên người ký)"
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation"

    quota["het"] = False
    orch.gate.decide("REL-001", "approve", by="human:lead", reason="root_cause: hết quota; decision: chạy lại production")
    orch.run()
    assert _production(bus) == ["deployed"], "duyệt escalation = chạy lại lượt production đã bị bỏ"
    assert orch.escalation_decided["REL-001"] == 2, "hai quyết định (Gate 3 + escalation), mỗi cái đếm một lần"


def test_duyet_escalation_release_ma_luot_chay_lai_tam_thoi_thi_hoan(monkeypatch):
    """Cùng họ: `_rerun_release` (duyệt escalation của RC `pending_human`) gặp transient. Trước đây quyết định bị
    `_mark` — RC kẹt `pending_human` với khoá sweep đã dùng, không gate nào mở lại."""
    from test_release_pending_human import _pausing_release_engineer
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=_pausing_release_engineer({"production": 1})))
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert _production(bus) == ["pending_human"] and orch.gate.pending["REL-001"].kind == "escalation"
    quota = _production_het_quota(orch, monkeypatch)
    orch.gate.decide("REL-001", "approve", by="human:lead", reason="đã xử lý, chạy lại production"); orch.run()
    assert _production(bus) == ["pending_human"]
    quota["het"] = False
    orch.tick()
    assert _production(bus) == ["pending_human", "deployed"]
    assert orch.escalation_decided["REL-001"] == 2


def test_duyet_escalation_ticket_ma_review_chay_lai_tam_thoi_thi_hoan(tmp_path, monkeypatch):
    """Cùng họ: review chạy lại sau duyệt escalation (reviewer lỗi) gặp transient. Lần xử lý lại chỉ gọi lại review,
    không cấp thêm ngân sách lần hai."""
    from company.llm import LLMError
    from test_orchestrator import _agent_of
    calls = {"qa": 0}

    def reviewer_hong_lan_dau(system, user):
        if _agent_of(system) == "qa":
            calls["qa"] += 1
            if calls["qa"] == 1: raise LLMError("reviewer hỏng một lần")
        return handler(system, user)

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=reviewer_hong_lan_dau))
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.state["T1"] == "in_review" and orch.gate.pending.get("T1")
    goc = orch.runner.generate
    het = {"qa": True}

    def gen(agent, env, topic, *a, **k):
        if het["qa"] and agent == "qa": raise TransientError("backend hết quota")
        return goc(agent, env, topic, *a, **k)

    monkeypatch.setattr(orch.runner, "generate", gen)
    orch.gate.decide("T1", "approve", by="human:lead", reason="CLI lỗi tạm, chấm lại"); orch.run()
    quyet = _decide_event(bus, "T1")
    assert quyet.event_id in orch.deferred and orch.lead.state["T1"] == "in_review"
    han_muc = orch.supervisor.budgets["T1"].limit
    het["qa"] = False
    orch.tick()
    assert orch.lead.state["T1"] in {"approved", "merged", "released"}
    assert orch.supervisor.budgets["T1"].limit == han_muc, "lần xử lý lại không áp lại tác dụng của quyết định"
    assert orch.escalation_decided["T1"] == 1
