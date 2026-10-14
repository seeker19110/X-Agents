"""ADR gốc 0035: change request không cần người — phạm vi `toan-bo` của reviewer gồm cả NỘP và QUYẾT change request.

Đo hub thật 2026-10-12 (QLKH-DD-CSV): sau ADR gốc 0033/0034 mọi gate do reviewer ký, nhưng CR compose (gỡ REL-001→011)
và CR replan vẫn chờ `human:*` qua `publish`/`decide-change` — chủ dự án: *"bỏ human"*. Đo hai chiều: không cờ hay
phạm vi hẹp hơn → CLI từ chối, orchestrator không tin CR do reviewer ghi; `toan-bo` → đi như người.
"""

from __future__ import annotations

import json

import pytest
from xagents_core.bus import PermissionDenied

from company.bus import REVIEWER_PREFIX, InMemoryBus
from company.core import REVIEWER_FAMILY, TOPIC_PRODUCERS
from company.events import Envelope
from company.gate_reviewer import FLAG_ENV, SCOPE_ENV, SCOPE_RONG, SCOPE_TOAN_BO, cr_actor_refusal, cr_trusted
from company.llm import FakeClient
from company.orch.guards import _cr_accepted_when
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from test_replan_adr0051 import _crs, _drive_to_blocked, _planner_blocks_t1

_cr_accepted_direct, _cr_accepted_needs_research = _cr_accepted_when(False), _cr_accepted_when(True)
CR = {"change_id": "CR-1", "project_id": "P1", "requested_by": "reviewer:phien-chinh", "description": "thêm compose"}
REASON = "root_cause: app cần PostgreSQL; decision: accepted; hint: compose postgres + app"


@pytest.fixture
def toan_bo(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(SCOPE_ENV, SCOPE_TOAN_BO)


@pytest.fixture
def khong_co(monkeypatch):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(SCOPE_ENV, raising=False)


def _env(actor: str, decision: str = "accepted", **extra) -> Envelope:
    return Envelope(topic="change-requests", key="CR-1", actor=actor, payload={**CR, "decision": decision, **extra})


def _cr_file(tmp_path):
    f = tmp_path / "cr.json"
    f.write_text(json.dumps(CR), encoding="utf-8")
    return f


# ---------- ACL bus: họ `reviewer:*` chỉ ở change-requests ----------


def test_bus_cho_ho_reviewer_phat_change_requests_khong_phat_topic_nguoi_khac():
    assert REVIEWER_FAMILY == REVIEWER_PREFIX + "*" and REVIEWER_FAMILY in TOPIC_PRODUCERS["change-requests"]
    # ADR gốc 0038: thêm đúng một topic — `clarification-answers` (agent đại diện khách trả lời câu hỏi làm rõ)
    assert {t for t, v in TOPIC_PRODUCERS.items() if REVIEWER_FAMILY in v} == {"change-requests", "clarification-answers"}
    bus = InMemoryBus()
    bus.publish(_env("reviewer:phien-chinh", "pending"))
    with pytest.raises(PermissionDenied):
        bus.publish(Envelope(topic="supervisor-actions", key="T1", actor="reviewer:phien-chinh",
                             payload={"target": "T1", "action": "resume", "reason": "không phải việc của reviewer"}))


# ---------- chiều ghi: CLI publish / decide-change ----------


def test_cli_publish_va_decide_change_nhan_reviewer_khi_toan_bo(tmp_path, toan_bo):
    db = tmp_path / "c.sqlite"
    f = _cr_file(tmp_path)
    assert orch_main(["--db", str(db), "publish", "change-requests", str(f), "--actor", "reviewer:phien-chinh"]) == 0
    assert orch_main(["--db", str(db), "decide-change", "CR-1", "accepted", "--by", "reviewer:phien-chinh",
                      "--reason", REASON]) == 0
    last = _crs(SQLiteBus(db))[-1]
    assert last.actor == "reviewer:phien-chinh" and last.payload["decision"] == "accepted"
    assert last.payload["impact"]["decided_by"] == "reviewer:phien-chinh"


@pytest.mark.parametrize("scope", [None, SCOPE_RONG])
def test_cli_tu_choi_reviewer_khi_khong_co_co_hay_pham_vi_hep(tmp_path, khong_co, monkeypatch, capsys, scope):
    if scope is not None:
        monkeypatch.setenv(FLAG_ENV, "1")
        monkeypatch.setenv(SCOPE_ENV, scope)
    db = tmp_path / "c.sqlite"
    f = _cr_file(tmp_path)
    assert orch_main(["--db", str(db), "publish", "change-requests", str(f), "--actor", "reviewer:phien-chinh"]) == 2
    assert orch_main(["--db", str(db), "publish", "change-requests", str(f), "--actor", "human:po"]) == 0
    assert orch_main(["--db", str(db), "decide-change", "CR-1", "accepted", "--by", "reviewer:phien-chinh"]) == 2
    assert orch_main(["--db", str(db), "publish", "research-requests", str(f), "--actor", "reviewer:phien-chinh"]) == 2
    err = capsys.readouterr().err
    assert err.count("ADR gốc 0035") == 2 and ("toan-bo" in err) == (scope == SCOPE_RONG)
    assert "phải là người" in err, "topic khác change-requests vẫn chỉ nhận người"
    assert [e.payload.get("decision", "pending") for e in _crs(SQLiteBus(db))] == ["pending"], "không ghi gì khi bị từ chối"


def test_cr_actor_refusal_nguoi_luon_duoc_agent_khong_bao_gio(khong_co):
    assert cr_actor_refusal("human:po") == "" and cr_actor_refusal("human") == ""
    assert "reviewer" in cr_actor_refusal("ops") and "reviewer" in cr_actor_refusal("orchestrator")


# ---------- chiều tin: orchestrator chỉ tin CR của reviewer khi cờ + phạm vi đang bật ----------


class _Orch:
    """Chỉ `_audit`, như guard dùng: ghi (action, evidence, once) để test đọc."""

    def __init__(self) -> None:
        self.audits: list[tuple[str, dict, str | None]] = []

    def _audit(self, action, evidence, *, once=None, project_id=None, **_):
        self.audits.append((action, evidence, once))


def test_orchestrator_chi_tin_cr_cua_reviewer_khi_toan_bo(monkeypatch, khong_co):
    o = _Orch()
    direct, research = _env("reviewer:phien-chinh"), _env("reviewer:phien-chinh", affects_requirements=["R1"])
    assert not cr_trusted(direct) and not _cr_accepted_direct(direct, o) and not _cr_accepted_needs_research(research, o)
    assert [a for a, _, _ in o.audits] == ["change.untrusted"] * 2 and o.audits[0][2] == f"cr_untrusted:{direct.event_id}"
    assert o.audits[0][1]["actor"] == "reviewer:phien-chinh" and "chưa bật" in o.audits[0][1]["reason"]
    assert _cr_accepted_direct(_env("human:po"), o), "người không phụ thuộc cờ"
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(SCOPE_ENV, SCOPE_TOAN_BO)
    assert cr_trusted(direct) and _cr_accepted_direct(direct, o) and _cr_accepted_needs_research(research, o)
    assert not _cr_accepted_direct(_env("reviewer:phien-chinh", "rejected"), o) and len(o.audits) == 2


def test_replan_do_reviewer_chap_nhan_thi_dong_ticket_cu_gate_de_lai_cho_chu_ky(tmp_path, toan_bo, capsys):
    """Người `accepted` replan thì `decide-change` đóng luôn gate escalation dưới tên người (ADR-0051). Reviewer không
    có đường đó: `gate.decide` trần dưới tên `reviewer:*` không ai tin (ADR gốc 0024) — ticket cũ vẫn đóng, kế hoạch
    mới vẫn lập, còn gate để lại cho `gate_reviewer decide --decision reject` có chữ ký."""
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "reviewer:phien-chinh",
                      "--reason", "lập lại"]) == 0
    out = capsys.readouterr().out
    assert "gate_reviewer decide T1 --decision reject --id phien-chinh" in out
    orch.tick()
    assert orch.lead.state["T1"] == "closed" and "T1" in orch.lead.abandoned and "T1" in orch.gate.pending
    rp = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "ticket.replanned"]
    assert rp and rp[0]["by"] == "reviewer:phien-chinh"
    assert "PLAN-P1-2" in orch.plans


def test_cr_replan_cua_reviewer_khi_khong_co_co_thi_orchestrator_bo_qua(tmp_path, khong_co):
    """ACL bus cho `reviewer:*` GHI (như `gate.decide`); tin hay không là việc của orchestrator theo cờ hub đang chạy."""
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_planner_blocks_t1))
    _drive_to_blocked(bus, orch)
    cr = _crs(bus)[-1]
    bus.publish(Envelope(topic="change-requests", key="REPLAN-T1-1", actor="reviewer:ai-do",
                         payload={**cr.payload, "decision": "accepted",
                                  "impact": {**cr.payload["impact"], "decided_by": "reviewer:ai-do"}}))
    orch.tick()
    assert orch.lead.state["T1"] == "blocked" and "T1" not in orch.lead.abandoned and "PLAN-P1-2" not in orch.plans
    why = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "change.untrusted"]
    assert len(why) == 1 and why[0]["change_id"] == "REPLAN-T1-1" and why[0]["actor"] == "reviewer:ai-do"


# ---------- CR không ghi `decision`: schema nói mặc định `pending`, route phải hiểu như vậy ----------


def test_cr_khong_co_truong_decision_van_duoc_uoc_luong_impact(tmp_path, toan_bo):
    """Đo hub thật 2026-10-12: `publish change-requests` một JSON không có `decision` (schema/`ChangeRequest` mặc định
    `pending`) → orchestrator `orchestrated actions: []`, CR nằm im không ai ước lượng, không lỗi, không audit. Route
    "pending" so `payload.get("decision") in ("pending",)` nên thiếu trường = không khớp. Thiếu trường phải là `pending`,
    như `DeliveryLead` (`replan_open`) đã đọc."""
    from company.orch.guards import _cr_pending
    from test_orchestrator import _agent_of, _inp, handler

    def _uoc_luong(system: str, user: str) -> dict:
        # fake `product` của test_orchestrator cũng chỉ ước lượng khi payload có `decision: pending`; ở đây CR không có
        p = _inp(user)
        if _agent_of(system) == "product" and "change_id" in p and "decision" not in p:
            return {"actor": "delivery-lead", "action": "change.impact", "project_id": p["project_id"],
                    "evidence": json.dumps({"change_id": p["change_id"], "impact": {"estimate_days": 1}})}
        return handler(system, user)

    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_uoc_luong))
    f = _cr_file(tmp_path)  # CR không có `decision`
    assert orch_main(["--db", str(db), "publish", "change-requests", str(f), "--actor", "reviewer:phien-chinh"]) == 0
    orch.tick()
    impact = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "change.impact"]
    assert impact and impact[0].actor == "product", "CR thiếu `decision` vẫn là CR đang chờ → product ước lượng"
    assert _cr_pending(_env("human:po", "pending"), None) and not _cr_pending(_env("human:po", "accepted"), None)
