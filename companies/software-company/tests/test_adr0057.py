"""ADR-0057: rework release không đổi code → change request cho planner, không review lại, không RC mới.

Đo được hub thật 2026-10-13 (QLKH-DD-CSV): security chặn REL-022…025 vì image nền và route chưa mount; reject escalation
đá ticket trong RC về làm lại, builder đúng đắn không sửa gì, nộp lại commit cũ → review pass → RC mới cùng sha 4ef9665
→ chặn y hệt. Bốn vòng, không vòng nào đổi một dòng code."""

from __future__ import annotations

from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _drive_to_plan, _inp, handler
from test_tools_and_agentic import _first_turn, _init_repo, _tc

HINT = "nâng image nền python lên bản vá và apt-get upgrade; thêm hồ sơ ngoại lệ CVE cho postgres"


def _builder_noop(system: str, user: str) -> dict:
    out = handler(system, user)
    if _agent_of(system) == "builder":
        out["no_changes_reason"] = "việc trong hint nằm ngoài phạm vi ticket, code của ticket đã xong từ lượt trước"
    return out


def _merged_t1(tmp_path, body: dict[str, str]):
    """T1 đi trọn vòng tới `merged` với một commit thật (`f_t1.py`); `body["t1"]` là nội dung builder ghi ở MỌI lượt —
    đổi nó trước khi rework để mô phỏng "có commit mới", giữ nguyên để mô phỏng "không đổi gì"."""
    repo = _init_repo(tmp_path / "repo")
    def th(m, t):
        return [_tc("write_file", path="f_t1.py", content=body["t1"])] if _first_turn(m) else []
    bus = SQLiteBus(tmp_path / "c.sqlite"); client = FakeClient(handler=_builder_noop, tool_handler=th)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    orch._rework_after_error = lambda *a, **k: True  # type: ignore[method-assign]
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.state["T1"] == "merged" and "T1" in orch.integrated, "tiền đề: T1 đã tích hợp và đã release"
    rid = next(r for r, t in orch.lead.release_tickets.items() if "T1" in t)
    return bus, client, orch, rid


def _review_calls(client, tid: str) -> int:
    return len(
        [
            c
            for c in client.calls
            if _agent_of(c["system"]) in {"qa", "security"} and _inp(c["user"]).get("ticket_id") == tid
        ]
    )


def _rcs_with(orch, tid: str) -> list[str]:
    return [r for r, t in orch.lead.release_tickets.items() if tid in t]


def test_rework_release_khong_doi_code_thanh_change_request_khong_review_lai(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    bus, client, orch, rid = _merged_t1(tmp_path, {"t1": "def t1():\n    return 1\n"})
    n_review, rcs = _review_calls(client, "T1"), _rcs_with(orch, "T1")
    orch.lead.rework_release_tickets(rid, HINT)  # = reject escalation của release
    results = orch.run()
    assert any(a == "rework_no_change:T1" for r in results for a in r.actions)
    assert _review_calls(client, "T1") == n_review, "PR nộp lại commit đã tích hợp thì không review lại"
    assert orch.lead.state["T1"] == "merged", "code đã ở nhánh tích hợp: về merged, không approved (không RC mới)"
    assert _rcs_with(orch, "T1") == rcs, "không sinh RC mới cùng sha"
    crs = [e.payload for e in bus.replay(topic="change-requests") if e.key.startswith("REWORK-T1-")]
    assert len(crs) == 1, crs
    cr = crs[0]
    assert cr["requested_by"] == "delivery-lead" and cr["decision"] == "pending" and cr["affects_requirements"] == []
    assert cr["impact"]["kind"] == "rework_no_change" and cr["impact"]["ticket_id"] == "T1"
    assert rid in cr["impact"]["releases"] and HINT in cr["impact"]["hint"] and HINT in cr["description"]
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload.get("ticket_id") == "T1"]
    assert "rework.no_change" in acts


def test_rework_release_co_commit_moi_thi_review_nhu_cu(tmp_path, monkeypatch):
    """Chiều ngược: finding đúng là lỗi trong code của ticket → builder sửa, nhánh đi trước → review chạy, không CR."""
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    body = {"t1": "def t1():\n    return 1\n"}
    bus, client, orch, rid = _merged_t1(tmp_path, body)
    body["t1"] = "def t1():\n    return 2\n"
    n_review = _review_calls(client, "T1")
    orch.lead.rework_release_tickets(rid, "sửa t1 trả 2")
    orch.run()
    assert _review_calls(client, "T1") > n_review, "có commit mới thì vòng review chạy như cũ"
    assert not [e for e in bus.replay(topic="change-requests") if e.key.startswith("REWORK-")]
