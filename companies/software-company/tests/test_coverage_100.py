"""Các nhánh còn hở sau khi đo coverage: nhánh lỗi, nhánh theo nền tảng và các đường `--closed` ít đi qua.

Mục tiêu là 100% dòng cho `src/company`, để mọi dòng còn lại trong repo đều có ít nhất một test đi qua —
ngưỡng `fail_under` trong pyproject nâng theo, nên tụt lại một dòng là CI đỏ.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from company import gate_brief as GB
from company import subagents as SA
from company.bus import InMemoryBus
from company.events import Envelope
from company.llm import FakeClient
from company.metrics import diagnose
from company.orchestrator import Orchestrator
from company.web import ToolError, pin_url
from company.workspace import Integration, WorkspaceError, _git_ok
from test_delivery_real import _merge_ticket, _rev
from test_gate_brief import _scenario, fail_handler, rich_handler
from test_orchestrator import _agent_of, _drive_to_plan, _inp, _ops_phase, handler
from test_tools_and_agentic import _init_repo, _repo_tool_handler


def _verdicts(b): return {it["id"]: it["verdict"] for it in b["self_check"]}


def _audits(bus, prefix):
    return [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"].startswith(prefix)]


# ---------- web ----------

def test_pin_url_cong_khong_hop_le():
    with pytest.raises(ToolError, match="cổng không hợp lệ"):
        pin_url("https://vi.du:99999999999/a")


# ---------- gate_checklists ----------

def test_checklist_heading_rong_bao_loi(tmp_path, monkeypatch):
    from company import gate_checklists as GC
    block = "Người tự kiểm thêm:\n\n\n"   # có heading nhưng dưới nó không còn dòng `- [ ]` nào
    with pytest.raises(ValueError, match="không có mục nào"):
        GC._items(block, GC.SELF_HEAD, GC._SELF_ITEM, "spec")


# ---------- metrics ----------

def test_diagnose_dem_gate_qua_han():
    bus = InMemoryBus()
    for act in ("gate.request", "gate.overdue", "gate.overdue", "gate.decide"):
        bus.publish(Envelope(topic="audit-log", key="g", actor="orchestrator",
                             payload={"action": act, "actor": "orchestrator",
                                      "evidence": '{"subject_id": "PLAN-P1-1", "kind": "plan"}'}))
    d = diagnose(bus)
    assert d["gate"]["qua_han"] == 2 and d["gate"]["mo"] == 1 and d["gate"]["quyet"] == 1


# ---------- workspace ----------

def test_git_ok_bao_qua_han(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")

    def boom(*a, **k): raise subprocess.TimeoutExpired("git", 1)
    monkeypatch.setattr(subprocess, "run", boom)
    ok, msg = _git_ok(repo, "status", timeout=1)
    assert ok is False and msg == "git status: quá 1s"


def test_deliver_sha_nam_sau_con_tro_khong_lui_nhanh(tmp_path):
    repo = _init_repo(tmp_path / "repo"); it = Integration(repo, base="main"); it.ensure()
    _merge_ticket(repo, it, "A", "a.py"); r1 = it.deliver("0.1.1", "1")
    sha_b = _merge_ticket(repo, it, "B", "b.py"); it.deliver("0.1.2", "2")
    # giao lại một sha CŨ hơn con trỏ release: không lùi nhánh, cũng không coi là lệch
    r3 = it.deliver("0.1.3", "3", sha=r1.sha)
    assert r3.ok and r3.problems == [] and not r3.branch_moved
    assert _rev(repo, "company/release") == sha_b and _rev(repo, "v0.1.3") == r1.sha


# ---------- subagents ----------

def test_build_chan_file_sinh_vuot_tran(tmp_path, monkeypatch):
    monkeypatch.setattr(SA, "oversize", lambda spec, text, stem: f"{stem}: dài quá")
    with pytest.raises(SystemExit, match="file sinh vượt trần"):
        SA.build(out=tmp_path)


def test_cli_build_in_ra_file_da_ghi(tmp_path, capsys):
    assert SA.main(["build", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("đã ghi ") == len(list(tmp_path.glob("*.md"))) > 0


def test_dunder_main_goi_main_va_thoat(monkeypatch, capsys):
    """`if __name__ == "__main__": raise SystemExit(main())` cuối subagents.py — chạy qua runpy để dòng đó
    thực sự thực thi trong tiến trình pytest."""
    import runpy

    monkeypatch.setattr(sys, "argv", ["company-subagents", "list"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("company.subagents", run_name="__main__")
    assert e.value.code == 0 and "->" in capsys.readouterr().out


# ---------- orchestrator: chẩn đoán và giao hàng ----------

def test_chan_doan_hong_khong_lam_hong_luot_review(monkeypatch):
    from company import metrics
    from company import orchestrator as O
    monkeypatch.setattr(metrics, "diagnose", lambda bus, top=30: (_ for _ in ()).throw(RuntimeError("bus hỏng")))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    env = Envelope(topic="pull-requests", key="T1", actor="builder", payload={"ticket_id": "T1"})
    out = O._with_chan_doan(env, orch)
    assert out == {"chan_doan_error": "bus hỏng"}


def _orch_da_giao(tmp_path, **kw):
    repo = _init_repo(tmp_path / "repo"); bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main",
                        deliver=True, **kw)
    _drive_to_plan(bus, orch); orch.run()
    return repo, bus, orch


def test_khong_giao_khi_gate_release_chua_duyet(tmp_path, monkeypatch):
    """Lớp phòng thủ SAU delivery-lead: `_deliver` tự hỏi lại gate thay vì tin lời khai của event."""
    from company.orchestrator import StepResult
    _repo, bus, orch = _orch_da_giao(tmp_path)
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert "REL-001" in orch.delivered
    orch.delivered.clear()
    monkeypatch.setattr(orch.gate, "is_approved", lambda sid: False)
    env = next(e for e in bus.replay(topic="release-events")
               if e.payload.get("env") == "production" and e.key == "REL-001")
    res = StepResult(env.event_id, env.topic, env.key)
    orch._deliver(env, res)
    assert not orch.delivered and res.actions == []
    skipped = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "delivery.skipped"]
    assert skipped and "gate release chưa duyệt" in skipped[-1]["evidence"]


def test_version_khop_thi_khong_ghi_de_khong_audit(tmp_path):
    """release_fsm.py 83->87: model trả đúng `version` như RC yêu cầu — không ghi đè, không audit
    `release.version_overridden` (nhánh còn lại của phòng thủ đã test ở test_release_engineer_cannot_override_rc_version)."""
    def h(system, user):
        a, p = _agent_of(system), _inp(user)
        if a == "ops" and _ops_phase(system) == "deploy":
            return {"release_id": p["release_id"], "version": p.get("version"), "env": p["target_env"], "status": "deployed"}
        return handler(system, user)

    repo = _init_repo(tmp_path / "repo"); bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=h, tool_handler=_repo_tool_handler), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="ok"); orch.run()
    n = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.version_overridden")
    assert n == 0
    evs = [e.payload["version"] for e in bus.replay(topic="release-events") if e.key == "REL-001"]
    assert evs and all(v for v in evs)


def test_giao_lai_release_da_giao_thi_khong_lam_gi(tmp_path):
    """`rid in o.delivered` (đã giao rồi) → `_deliver` không giao lại, không audit thêm lần nữa."""
    from company.orchestrator import StepResult
    _repo, bus, orch = _orch_da_giao(tmp_path)
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert "REL-001" in orch.delivered
    n_done_truoc = len([e for e in bus.replay(topic="audit-log") if e.payload["action"] == "delivery.done"])
    env = next(e for e in bus.replay(topic="release-events")
               if e.payload.get("env") == "production" and e.key == "REL-001")
    res = StepResult(env.event_id, env.topic, env.key)
    orch._deliver(env, res)
    assert res.actions == []
    n_done_sau = len([e for e in bus.replay(topic="audit-log") if e.payload["action"] == "delivery.done"])
    assert n_done_sau == n_done_truoc


def test_loi_workspace_khi_giao_thanh_audit_khong_ném(tmp_path, monkeypatch):
    _repo, bus, orch = _orch_da_giao(tmp_path)

    def boom(*a, **k): raise WorkspaceError("git chết")
    monkeypatch.setattr(Integration, "deliver", boom)
    orch.gate.decide("REL-001", "approve", by="human:release-manager")
    res = orch.run()
    assert not orch.delivered and _audits(bus, "delivery.") == ["delivery.error"]
    assert any(a == "delivery_error:REL-001" for r in res for a in r.actions)


def test_loi_workspace_khi_rollback_thanh_audit(tmp_path, monkeypatch):
    _repo, bus, orch = _orch_da_giao(tmp_path)
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert "REL-001" in orch.delivered

    def boom(*a, **k): raise WorkspaceError("git chết")
    monkeypatch.setattr(Integration, "rollback_delivery", boom)
    bus.publish(Envelope(topic="release-events", key="REL-001", actor="ops",
                         payload={"release_id": "REL-001", "version": "0.1.1", "env": "production", "status": "rolled_back"}))
    res = orch.run()
    assert "REL-001" in orch.delivered and "delivery.error" in _audits(bus, "delivery.")
    assert any(a == "rollback_error:REL-001" for r in res for a in r.actions)


def test_loi_push_khi_rollback_duoc_ghi_audit(tmp_path):
    _repo, bus, orch = _orch_da_giao(tmp_path, push_remote="khong-co")
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    bus.publish(Envelope(topic="release-events", key="REL-001", actor="ops",
                         payload={"release_id": "REL-001", "version": "0.1.1", "env": "production", "status": "rolled_back"}))
    orch.run()
    acts = _audits(bus, "delivery.")
    assert acts.count("delivery.push_failed") == 2, "một lần lúc giao, một lần lúc lùi"
    assert "delivery.rolled_back" in acts


def test_cli_diagnose_in_json(tmp_path, capsys):
    from company.orchestrator import main as orch_main
    from company.sqlite_bus import SQLiteBus
    SQLiteBus(tmp_path / "c.sqlite").close()
    assert orch_main(["--db", str(tmp_path / "c.sqlite"), "diagnose", "--top", "5"]) == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert "loi_theo_khuon" in out and "gate" in out


# ---------- gate_brief ----------

def test_project_of_kind_la_hoac_subject_khong_theo_mau(tmp_path):
    """ADR-0037: `plan` không còn là kind nào cả. Kind lạ (hay subject không theo mẫu của kind đó) → `None`,
    không đoán một project_id ra từ chuỗi."""
    _db, _, orch = _scenario(tmp_path, to="plan")
    assert GB._project_of(orch, "kind-la", "X") is None
    assert GB._project_of(orch, "spec", "khong-theo-mau") is None


def test_spec_thieu_nfr_va_out_of_scope(tmp_path):
    prd = "# PRD P1\n## Yêu cầu\n- REQ-1 GET /orders p95 < 300 ms\n- REQ-2 không số\n"

    def h(system, user):
        from test_orchestrator import _agent_of, _product_phase
        out = rich_handler(system, user)
        if _agent_of(system) == "product" and _product_phase(system) == "spec" and "context_writes" in out:
            out["context_writes"][0]["content"] = prd
        return out
    db, _, _ = _scenario(tmp_path, h, to="plan")
    b = GB.build(GB.load_state(db), "SPEC-P1", closed=True)
    v = _verdicts(b); facts = {it["id"]: it["facts"] for it in b["self_check"]}
    assert v["spec.nfr-co-so-do"] == "unknown" and "không có mục NFR" in facts["spec.nfr-co-so-do"][0]
    assert any("1 dòng trong toàn PRD" in f for f in facts["spec.nfr-co-so-do"])
    assert v["spec.out-of-scope"] == "gap" and "không có heading Out of scope" in facts["spec.out-of-scope"][0]


def test_release_chua_co_api_contract_thi_unknown(tmp_path):
    db, _, _ = _scenario(tmp_path, handler, to="release")  # handler gốc: blackboard chỉ có con trỏ
    b = GB.build(GB.load_state(db), "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "release.dashboard-alert")
    assert it["verdict"] == "unknown" and it["facts"] == ["chưa có api-contract"]


def test_escalation_gom_comment_cua_nguoi_va_review_block(tmp_path):
    db, bus, _orch = _scenario(tmp_path, fail_handler, to="escalation")
    bus.publish(Envelope(topic="audit-log", key="T1", actor="human:lead",
                         payload={"action": "human.comment", "actor": "human:lead", "ticket_id": "T1",
                                  "evidence": '{"text": "thử đọc lại log CI"}'}))
    bus.publish(Envelope(topic="review-results", key="T1", actor="qa",
                         payload={"ticket_id": "T1", "source": "reviewer", "verdict": "block",
                                  "findings": [{"level": "block", "text": "SQL injection ở /orders"}]}))
    b = GB.build(GB.load_state(db), "T1")
    assert any(h["decision"] == "comment" and "đọc lại log CI" in h["reason"] for h in b["extra"]["hints_used"])
    rv = [h for h in b["extra"]["history"] if h["action"] == "review reviewer block"]
    assert rv and "SQL injection" in rv[0]["detail"]


def test_escalation_chua_co_ngan_sach_thi_unknown(tmp_path):
    _db, _, orch = _scenario(tmp_path, fail_handler, to="escalation")
    orch.supervisor.budgets.pop("T1")
    b = GB.build(orch, "T1")
    it = next(x for x in b["self_check"] if x["id"] == "escalation.ngan-sach")
    assert it["verdict"] == "unknown" and "chưa có ngân sách" in it["facts"][0] and b["extra"]["budget"] == {}


def test_escalation_chan_doan_hong_thi_bo_qua(tmp_path, monkeypatch):
    _db, _, orch = _scenario(tmp_path, fail_handler, to="escalation")
    from company import metrics
    monkeypatch.setattr(metrics, "diagnose", lambda bus, top=30: (_ for _ in ()).throw(RuntimeError("hỏng")))
    b = GB.build(orch, "T1")
    assert b["extra"]["diagnose"] is None and b["extra"]["history"], "hồ sơ vẫn dựng được"
