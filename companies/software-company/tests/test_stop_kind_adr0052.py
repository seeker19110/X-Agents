"""ADR-0052: một bảng `STOP_POLICY`, một `classify_error`, mọi audit dừng mang `stop_kind`, `ticket.blocked` nói retry đã
đếm cái gì (`stops`). Hai chiều: chưa có module → cả file đỏ (ImportError); bỏ `stop_kind` khỏi một audit → ca tương ứng đỏ."""
from __future__ import annotations

import json

import pytest

from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Task
from company.gate_cli import PersistentGate
from company.llm import FakeClient, LLMError, TransientError
from company.orch import routes
from company.orchestrator import Orchestrator
from company.stop_kind import AUTORETRY_SUBTYPES, STOP_KINDS, STOP_POLICY, Policy, classify_error, cli_subtype
from test_on_dinh_auto import HET_LUOT, SCHEMA, _audits, _builder_het_luot
from test_orchestrator import _drive_to_plan, handler
from test_tools_and_agentic import _init_repo


def _ev(p: dict) -> dict:
    return json.loads(p["evidence"])


# ---------- bảng ----------

def test_bang_chinh_sach_phu_moi_kieu_va_la_nguon_cua_hai_hang_cu():
    assert set(STOP_POLICY) == set(STOP_KINDS) and all(isinstance(p, Policy) for p in STOP_POLICY.values())
    assert routes.MAX_TURN_CONTINUATIONS == STOP_POLICY["turn_limit"].free_stops == 3
    assert routes.MAX_CONFLICT_RETRIES == STOP_POLICY["merge_conflict"].free_stops == 6
    assert STOP_POLICY["agent_error"].burns_retry and STOP_POLICY["agent_error"].free_stops is None
    assert not STOP_POLICY["infra_transient"].burns_retry and STOP_POLICY["infra_transient"].then == "defer"
    assert STOP_POLICY["needs_human"].then == "escalate"


@pytest.mark.parametrize("err, kind", [
    (TransientError("429"), "infra_transient"),
    (LLMError(HET_LUOT, model_text="x"), "turn_limit"),
    (LLMError(SCHEMA, model_text="x"), "infra_transient"),
    (LLMError("claude -p thoát mã 1 (subtype=error_max_budget_usd, api_error_status=None): ", model_text="x"), "budget"),
    (LLMError("JSON hỏng"), "agent_error"),
    (ValueError("handler từ chối"), "agent_error"),
])
def test_classify_error(err, kind):
    assert classify_error(err) == kind


def test_classify_khong_soi_chu_cua_model():
    """Model viết `subtype=error_max_turns` trong câu trả lời không đổi được kiểu dừng (chỉ `head` được soi)."""
    e = LLMError("claude -p thoát mã 1 (subtype=unknown_x, api_error_status=None): ", model_text="subtype=error_max_turns")
    assert cli_subtype(e) == "unknown_x" and classify_error(e) == "agent_error"
    assert "error_max_structured_output_retries" in AUTORETRY_SUBTYPES


# ---------- lead: đếm theo kiểu, ticket.blocked nói rõ ----------

def _lead():
    bus = InMemoryBus(); lead = DeliveryLead(bus, PersistentGate(bus)); lead.plans_ok.add("P-1")
    lead.dispatch(Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="builder", title="x", acceptance=["a"]), "P-1")
    return bus, lead


def test_ticket_blocked_mang_stop_kind_va_stops_theo_kieu():
    bus, lead = _lead()
    lead.state["T1"] = "dispatched"; lead.rework("T1", "pytest đỏ", kind="agent_error")
    lead.state["T1"] = "approved"; lead.request_changes("T1", "xung đột lần 7", kind="merge_conflict")
    lead.state["T1"] = "dispatched"; lead.rework("T1", "hết lượt, worktree sạch", kind="turn_limit")
    assert lead.state["T1"] == "blocked" and lead.stops["T1"] == {"agent_error": 1, "merge_conflict": 1, "turn_limit": 1}
    ev = _ev(_audits(bus, "ticket.blocked")[-1])
    assert ev["stop_kind"] == "turn_limit" and ev["stops"] == {"agent_error": 1, "merge_conflict": 1, "turn_limit": 1}
    cr = list(bus.replay(topic="change-requests"))[-1].payload
    assert cr["impact"]["stops"] == ev["stops"], "planner được biết ticket chết vì gì (ADR-0051 + 0052)"


def test_rework_mac_dinh_la_agent_error_va_reopen_xoa_dem():
    _bus, lead = _lead()
    for _ in range(3):
        lead.state["T1"] = "dispatched"; lead.rework("T1", "đỏ")
    assert lead.stops["T1"] == {"agent_error": 3}
    lead.reopen("T1", "người mở lại")
    assert "T1" not in lead.stops


def test_kind_la_phai_thuoc_bang():
    _bus, lead = _lead()
    lead.state["T1"] = "dispatched"
    with pytest.raises(ValueError, match="stop_kind"):
        lead.rework("T1", "x", kind="tu_bia")


# ---------- orchestrator: audit dừng mang stop_kind ----------

def test_lam_tiep_vi_het_luot_va_blocked_cuoi_mang_stop_kind(tmp_path, monkeypatch):
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler), repo=_init_repo(tmp_path / "repo"), base="main")
    _builder_het_luot(orch, monkeypatch, sua_file=True)
    _drive_to_plan(bus, orch); orch.run()
    assert {_ev(a)["stop_kind"] for a in _audits(bus, "ticket.continued")} == {"turn_limit"}
    ev = _ev(_audits(bus, "ticket.blocked")[-1])
    assert ev["stop_kind"] == "turn_limit" and ev["stops"] == {"turn_limit": 3}, "ba retry cháy đều là hết lượt (sau 3 lần miễn), không phải làm sai"


def test_loi_schema_tu_thu_lai_mang_stop_kind_infra(tmp_path, monkeypatch):
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler), repo=_init_repo(tmp_path / "repo"), base="main")
    _builder_het_luot(orch, monkeypatch, sua_file=False, err=LLMError(SCHEMA, model_text="x"))
    _drive_to_plan(bus, orch); orch.run()
    assert _ev(_audits(bus, "llm.autoretry")[0])["stop_kind"] == "infra_transient"


def test_unhandled_va_stalled_mang_stop_kind_needs_human():
    def product_chet(system, user):
        if system.startswith("# product"): raise LLMError("JSON hỏng")
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=product_chet))
    bus.publish(__import__("company.events", fromlist=["Envelope"]).Envelope(
        topic="research-requests", key="P1", actor="human:sales", payload={"project_id": "P1", "description": "app"}))
    orch.run()
    st = _audits(bus, "project.stalled")
    assert st and _ev(st[0])["stop_kind"] == "needs_human" and _ev(st[0])["error_kind"] == "agent_error"


def test_xung_dot_merge_mang_stop_kind_va_vuot_tran_thi_dem_vao_stops(tmp_path):
    """Cùng kịch bản `test_xung_dot_lap_lai_qua_nguong_moi_tinh_vao_retry_noi_dung`: audit `integration.conflict` mang
    `stop_kind=merge_conflict`, và lần vượt trần đi qua `_retry(kind="merge_conflict")` nên `stops` của lead ghi đúng kiểu."""
    from company.sqlite_bus import SQLiteBus
    from test_integration_branch import T1, T2, _first_turn, _repo_tool_handler, _tc
    from test_orchestrator import _agent_of, _drive_to_spec_gate, _inp, _product_phase
    repo = _init_repo(tmp_path / "repo")
    def lead_independent(system, user):
        if _agent_of(system) == "product" and _product_phase(system) == "plan" and "P1" in user and "decision" not in _inp(user):
            return {"items": [{**T1, "budget_tokens": 40_000}, {**T2, "title": "POST /notes", "depends_on": [], "risk_tags": [], "budget_tokens": 40_000, "priority": 3}],
                    "context_writes": [{"namespace": "architecture", "content_ref": "docs/c4.md", "summary": "L1-L2"},
                                        {"namespace": "api-contract", "content_ref": "openapi.yaml", "summary": "v1"}]}
        return handler(system, user)
    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and _first_turn(msgs):
            p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
            return [_tc("write_file", path=f"after_{tid.lower()}.py" if p.get("hint") else "shared.py", content=f"X = '{tid}'\n")]
        return _repo_tool_handler(msgs, tools)
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=lead_independent, tool_handler=th), repo=repo, base="main")
    _drive_to_spec_gate(bus, orch)
    orch.conflict_retries["T2"] = routes.MAX_CONFLICT_RETRIES
    orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    assert _ev(_audits(bus, "integration.conflict")[0])["stop_kind"] == "merge_conflict"
    assert orch.lead.stops["T2"] == {"merge_conflict": 1}
