"""Sau khi người đưa yêu cầu (và ký spec), công ty phải tự đi tới cùng — hoặc HỎI người qua gate. Không đường
nào được kết thúc trong im lặng (`TRAPS.md` §1). Audit 2026-09-23 đo được bốn chỗ còn im lặng, mỗi ca dưới đây
tả một chỗ:

1. `product[plan]` ném `RunnerError`/`LLMError` → `_mark` xong, không gate, không retry (`ticket_fsm._plan`).
2. Threat model `verdict=block` → chỉ audit `spec_blocked_by_security`, không gate (`ticket_fsm._threat_model`).
3. Câu hỏi làm rõ không ai trả lời → chờ vô hạn, chỉ hiện ở `status` (`guards.pending_clarifications`).
4. Event hoãn `transient:` thử lại mỗi nhịp không có trần (`scheduler._defer`).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from company.bus import InMemoryBus
from company.events import AuditLog
from company.llm import FakeClient, TransientError
from company.orchestrator import Orchestrator
from company.roles import PHASE
from company.runner import RunnerError
from test_orchestrator import _agent_of, _drive_to_spec_gate, _inp, _pub, _topics, handler


def _orch(h=handler):
    bus = InMemoryBus()
    return bus, Orchestrator(bus, FakeClient(handler=h))


def _actions(bus):
    return [e.payload["action"] for e in bus.replay(topic="audit-log")]


def _escalation_pending(orch, subject):
    r = orch.gate.pending.get(subject)
    return r is not None and r.kind == "escalation"


# ---------- 1. plan lỗi ----------

def test_plan_loi_runner_mo_gate_escalation_khong_im_lang(monkeypatch):
    bus, orch = _orch()
    _drive_to_spec_gate(bus, orch)
    that = orch.runner.generate

    def hong(agent, env, topic, *a, **k):
        if k.get("phase") == PHASE.PLAN:
            raise RunnerError("model trả JSON hỏng")
        return that(agent, env, topic, *a, **k)

    monkeypatch.setattr(orch.runner, "generate", hong)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    assert not orch.plans, "kịch bản: lập kế hoạch lỗi thật"
    assert "agent_error_unhandled" in _actions(bus), f"lỗi plan phải ghi sổ, nhận: {_actions(bus)[-5:]}"
    assert _escalation_pending(orch, "P1"), f"phải có gate escalation cho dự án, gate: {list(orch.gate.pending)}"
    # người duyệt → chạy lại đúng event approved-specs, plan ra đời
    monkeypatch.setattr(orch.runner, "generate", that)
    orch.gate.decide("P1", "approve", by="human:po", reason="model đã ổn, chạy lại")
    orch.run()
    assert orch.plans, "duyệt escalation phải chạy lại lượt plan"


# ---------- 2. threat model block ----------

def test_threat_model_block_mo_gate_escalation_va_duyet_thi_chay_lai():
    chan = {"on": True}

    def blocker(system, user):
        if chan["on"] and _agent_of(system) == "security" and "artifacts" in _inp(user):
            return {"ticket_id": "SPEC-P1", "source": "security", "verdict": "block",
                    "findings": [{"level": "block", "text": "PII không mã hoá"}]}
        return handler(system, user)

    bus, orch = _orch(blocker)
    _pub(bus, "approved-specs", "P1", "product", {"project_id": "P1", "status": "pending_human", "kind": "library",
                                                  "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
    orch.run(); orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    assert not orch.plans and "spec_blocked_by_security" in _actions(bus)
    assert _escalation_pending(orch, "P1"), f"spec bị security chặn phải HỎI người qua gate, gate: {list(orch.gate.pending)}"
    chan["on"] = False  # người sửa nguyên nhân rồi duyệt escalation → threat model chạy lại → plan
    orch.gate.decide("P1", "approve", by="human:po", reason="đã bổ sung mã hoá PII vào spec")
    orch.run()
    assert orch.plans, "duyệt escalation phải chạy lại threat model và lập kế hoạch"


# ---------- 3. câu hỏi làm rõ quá hạn → giả định theo default ----------

def test_cau_hoi_lam_ro_qua_han_thi_tu_gia_dinh_theo_default_va_di_tiep():
    bus, orch = _orch()
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    assert _topics(bus)[-1] == "clarification-questions" and orch.status()["clarifications_pending"]
    q = next(iter(bus.replay(topic="clarification-questions")))
    orch.tick(now=q.ts + timedelta(hours=1))
    assert "clarification.assumed" not in _actions(bus), "chưa quá hạn thì vẫn chờ người"
    orch.tick(now=q.ts + timedelta(hours=25))
    acts = _actions(bus)
    assert "clarification.assumed" in acts, f"quá hạn phải ghi sổ giả định, nhận: {acts[-6:]}"
    assert [e.actor for e in bus.replay(topic="approved-specs")] == ["product"], "pha spec phải chạy từ draft"
    assert "SPEC-P1" in orch.gate.pending, "dự án đi tiếp tới gate spec (người vẫn ký spec)"
    assert orch.status()["clarifications_pending"] == {}, "đã giả định thì không còn 'chờ người'"
    orch.tick(now=q.ts + timedelta(hours=26))
    assert acts.count("clarification.assumed") == _actions(bus).count("clarification.assumed") == 1, "chỉ giả định một lần"


def test_gia_dinh_gap_transient_thi_nhip_sau_thu_lai_khong_ket_im():
    """`_assume_clarifications` từng ghi `clarification.assumed` TRƯỚC khi gọi pha spec: spec-writer gặp
    `TransientError` thì vòng câu hỏi đã bị coi là "đã giả định" (`pending_clarifications` bỏ qua) — không spec,
    không gate, không nhịp nào thử lại, `clarifications_pending` rỗng: dự án đứng im mà `status` nói không chờ ai.
    Sổ giả định chỉ được ghi khi pha spec thật sự chạy; thử lại giữ mốc hẹn của backend như mọi `transient:` khác
    (nhịp 5s mà hỏi lại thì mỗi nhịp một dòng `llm_error`). Đo hai chiều: ghi sổ trước lời gọi thì assert đầu đỏ;
    bỏ mốc hẹn thì assert "nhịp kế không hỏi lại" đỏ."""
    goi = {"n": 0, "nghi": True}
    def h(system, user):
        if _agent_of(system) == "product" and "assumed_answers" in _inp(user):
            goi["n"] += 1
            if goi["nghi"]: raise TransientError("mọi backend đều đang nghỉ, thử lại sau 1515s")
        return handler(system, user)
    bus, orch = _orch(h)
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    q = next(iter(bus.replay(topic="clarification-questions")))
    orch.tick(now=q.ts + timedelta(hours=25))
    assert "clarification.assumed" not in _actions(bus), "pha spec chưa chạy được thì chưa được ghi là đã giả định"
    assert "P1" in orch.status()["clarifications_pending"], "vẫn phải hiện là đang chờ, không biến mất"
    orch.tick(now=q.ts + timedelta(hours=26))
    assert goi["n"] == 1, "backend đã hẹn 1515s thì nhịp kế không hỏi lại"
    goi["nghi"] = False
    for k in orch.defer_until: orch.defer_until[k] = 0.0
    orch.tick(now=q.ts + timedelta(hours=26))
    assert goi["n"] == 2 and "SPEC-P1" in orch.gate.pending and _actions(bus).count("clarification.assumed") == 1


def test_gia_dinh_gap_transient_khong_hen_gio_thi_nhip_sau_thu_lai_ngay():
    """Backend không nói phải chờ bao lâu → như `_defer` không `wait_s`: nhịp sau thử lại luôn."""
    goi = {"n": 0}
    def h(system, user):
        if _agent_of(system) == "product" and "assumed_answers" in _inp(user):
            goi["n"] += 1
            if goi["n"] == 1: raise TransientError("mọi backend đều đang nghỉ")
        return handler(system, user)
    bus, orch = _orch(h)
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    q = next(iter(bus.replay(topic="clarification-questions")))
    orch.tick(now=q.ts + timedelta(hours=25))
    orch.tick(now=q.ts + timedelta(hours=26))
    assert goi["n"] == 2 and "SPEC-P1" in orch.gate.pending


def test_han_cau_hoi_lam_ro_doc_tu_env(monkeypatch):
    monkeypatch.setenv("COMPANY_CLARIFY_TIMEOUT_H", "2")
    bus, orch = _orch()
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    q = next(iter(bus.replay(topic="clarification-questions")))
    orch.tick(now=q.ts + timedelta(hours=3))
    assert "clarification.assumed" in _actions(bus)


def test_qua_han_ma_khong_co_draft_thi_khong_gia_dinh():
    """Câu hỏi treo cho một dự án không có `requirements-draft` (chuỗi nghiên cứu chết, publish nhầm dự án):
    không có gì để viết spec → không giả định, không audit; `status` vẫn báo chờ."""
    bus, orch = _orch()
    q = _pub(bus, "clarification-questions", "P9", "product",
             {"project_id": "P9", "round": 1, "questions": [{"id": "Q-1", "text": "?", "options": ["a"], "default": "a"}]})
    orch.run()
    orch.tick(now=q.ts + timedelta(hours=25))
    assert "clarification.assumed" not in _actions(bus) and not list(bus.replay(topic="approved-specs"))
    assert "P9" in orch.status()["clarifications_pending"]


def test_audit_gia_dinh_hong_json_bi_bo_qua():
    """Bản ghi `clarification.assumed` mà `evidence` không phải JSON thì không khớp vòng nào → vòng vẫn 'chờ người'."""
    bus, orch = _orch()
    _pub(bus, "clarification-questions", "P1", "product",
         {"project_id": "P1", "round": 1, "questions": [{"id": "Q-1", "text": "?", "options": ["a"], "default": "a"}]})
    _pub(bus, "audit-log", "orchestrator", "orchestrator",
         AuditLog(actor="orchestrator", action="clarification.assumed", evidence="không phải json").model_dump())
    assert "P1" in orch.status()["clarifications_pending"]


# ---------- 4. transient quá lâu ----------

def test_transient_qua_lau_thi_escalation_thay_vi_thu_lai_mai(monkeypatch):
    bus, orch = _orch()
    _drive_to_spec_gate(bus, orch)

    def chap_chon(agent, env, topic, *a, **k):
        raise TransientError("backend hết quota")

    monkeypatch.setattr(orch.runner, "generate", chap_chon)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()
    assert orch.deferred and "agent_error_unhandled" not in _actions(bus), "lần đầu: hoãn, chưa escalate"
    for eid in list(orch.transient_since):
        orch.transient_since[eid] = time.monotonic() - 3 * 3600
    orch.tick(now=datetime.now(UTC))
    assert "agent_error_unhandled" in _actions(bus), f"transient > trần phải ra gate, nhận: {_actions(bus)[-5:]}"
    assert _escalation_pending(orch, "P1")
    assert not any(v[1].startswith("transient:") for v in orch.deferred.values()), "không còn hoãn transient"
