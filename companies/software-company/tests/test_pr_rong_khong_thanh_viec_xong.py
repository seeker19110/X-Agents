"""PR rỗng của ticket CHƯA từng tích hợp (builder dừng vì bị chặn/cần quyết định) không phải việc xong: không review,
không RC — ticket `blocked` và change request `REPLAN-*` mang lý do của builder cho planner.

Hub thật 2026-10-14 (QLKH-DD-CSV): builder của DDCSV-73 dừng ngay lượt đầu vì đầu vào mâu thuẫn (spec ghi cổng 8080,
compose publish 8000, ticket cấm sửa compose) và ghi lý do vào `no_changes_reason` — đúng như prompt dặn cho "bị chặn,
cần người quyết". Runner ra PR 0 file ở sha nền (đường "đã xong từ lượt trước" của TCK-CR-RUNTIME-01); QA chấm pass kèm
warn "ticket chưa làm, không được tính là xong"; orchestrator `integration.noop` rồi tạo REL-062 chỉ với ticket đó.

Ticket ĐÃ tích hợp mà làm lại không đổi code là ADR-0057 (`rework_no_change`), không phải ca này.
"""

from __future__ import annotations

from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _drive_to_plan, _inp, handler
from test_tools_and_agentic import _init_repo

LY_DO = "Đầu vào mâu thuẫn: acceptance đòi cổng 8080 nhưng scope cấm sửa docker-compose.yml đang publish 8000"


def _builder_dung(system: str, user: str) -> dict:
    out = handler(system, user)
    if _agent_of(system) == "builder" and _inp(user).get("ticket_id") == "T1":
        out["no_changes_reason"] = LY_DO
    return out


def test_pr_rong_luot_dau_thanh_blocked_va_replan_khong_review_khong_rc(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    repo = _init_repo(tmp_path / "repo")
    bus = SQLiteBus(tmp_path / "c.sqlite")
    client = FakeClient(handler=_builder_dung, tool_handler=lambda m, t: [])  # không ghi file nào
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch)
    orch.run()
    review = [
        c
        for c in client.calls
        if _agent_of(c["system"]) in {"qa", "security"} and _inp(c["user"]).get("ticket_id") == "T1"
    ]
    assert not review, "PR rỗng của ticket chưa làm không đi review"
    assert orch.lead.state["T1"] == "blocked" and "T1" not in orch.integrated
    assert not [r for r, t in orch.lead.release_tickets.items() if "T1" in t], "không RC nào mang ticket chưa làm"
    crs = [e.payload for e in bus.replay(topic="change-requests") if e.key.startswith("REPLAN-T1-")]
    assert len(crs) == 1 and LY_DO in crs[0]["description"] and crs[0]["impact"]["kind"] == "replan"
    acts = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "pr.empty"]
    assert acts and LY_DO in acts[0]["evidence"]


def test_pr_rong_blocked_ben_qua_mo_lai_bus(tmp_path, monkeypatch):
    """Hub restart mỗi lần deploy: mở lại bus thì ticket vẫn `blocked`, không quay về `in_review` rồi đi review."""
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    repo = _init_repo(tmp_path / "repo")
    client = FakeClient(handler=_builder_dung, tool_handler=lambda m, t: [])
    orch = Orchestrator(SQLiteBus(tmp_path / "c.sqlite"), client, repo=repo, base="main")
    _drive_to_plan(orch.bus, orch)
    orch.run()
    n = len(client.calls)
    lai = Orchestrator(SQLiteBus(tmp_path / "c.sqlite"), client, repo=repo, base="main")
    lai.run()
    assert lai.lead.state["T1"] == "blocked"
    sau = [
        c
        for c in client.calls[n:]
        if _agent_of(c["system"]) in {"qa", "security"} and _inp(c["user"]).get("ticket_id") == "T1"
    ]
    assert not sau, "mở lại bus không đưa PR rỗng đi review"
