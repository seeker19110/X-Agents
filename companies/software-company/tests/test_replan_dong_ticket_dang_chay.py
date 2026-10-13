"""CR `REPLAN-*` được chấp nhận thì ticket cũ CHƯA XONG phải đóng, kể cả khi nó đang chạy lại (sửa ADR-0051 §3).

Hub thật 2026-10-14 (QLKH-DD-CSV): DDCSV-35 blocked 17:31:43 sau 3 lần `error_max_turns`; `reviewer:tu-dong` mở lại nó
lúc 17:33:01 (cuộc chạy đua #486 đã chặn cho lần sau), rồi chấp nhận REPLAN-DDCSV-35-1 lúc 17:37:34. `_retire_replanned`
thấy ticket không còn `blocked` → `replan:DDCSV-35:not_blocked`, chỉ lập kế hoạch mới. 18:14:58 PLAN-QLKH-DD-CSV-9 giao
DDCSV-51..53 (tách nhỏ đúng việc của DDCSV-35) trong khi 18:15:00 builder vẫn chạy DDCSV-35: hai nhánh cùng sửa một
middleware, cùng tiêu ngân sách.

Luật mới: chấp nhận replan là quyết định SAU CÙNG về ticket đó — ticket còn dở (`dispatched`/`in_review`/
`changes_requested`/`blocked`…) thì đóng như cũ (`close_escalated`, audit `ticket.replanned`). Ticket đã xong
(`approved` trở đi) thì giữ: code đã có, đóng là mất việc thật. Đối soát chạy ở đầu mỗi `tick()` từ sổ CR đã chấp nhận
(dựng lại từ bus), nên ticket bản cũ đã bỏ sót cũng được đóng sau khi deploy.
"""

from __future__ import annotations

import json

from company.llm import FakeClient, TransientError
from company.orch import scheduler, ticket_fsm
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _inp
from test_replan_adr0051 import _drive_to_blocked, _planner_blocks_t1

HET_PHIEN = {"on": False}


def _h(system: str, user: str) -> dict:
    """Như `_planner_blocks_t1`, cộng: builder của T1 gặp hết phiên khi `HET_PHIEN` bật — ticket nằm `dispatched`."""
    if HET_PHIEN["on"] and _agent_of(system) == "builder" and _inp(user).get("ticket_id") == "T1":
        raise TransientError("hết 3 lần thử lại: HTTP 429 — thử lại sau 3600s")
    return _planner_blocks_t1(system, user)


def _mo_lai_roi_chap_nhan(db, bus, orch, monkeypatch=None) -> None:
    """Đúng thứ tự trên hub: gate escalation được duyệt mở lại TRƯỚC, rồi CR replan mới được chấp nhận."""
    HET_PHIEN["on"] = False
    _drive_to_blocked(bus, orch)
    HET_PHIEN["on"] = True
    orch.gate.decide("T1", "approve", by="human:pm", reason="mở lại trước khi CR được quyết")
    orch.run()
    assert orch.lead.state["T1"] == "dispatched" and "T1" not in orch.gate.pending
    assert orch_main(["--db", str(db), "decide-change", "REPLAN-T1-1", "accepted", "--by", "human:po"]) == 0


def _replanned(bus) -> list[dict]:
    return [
        json.loads(e.payload["evidence"])
        for e in bus.replay(topic="audit-log")
        if e.payload["action"] == "ticket.replanned"
    ]


def test_replan_chap_nhan_khi_ticket_cu_dang_chay_lai_thi_dong_no(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_h))
    _mo_lai_roi_chap_nhan(db, bus, orch)
    orch.tick()
    assert orch.lead.state["T1"] == "closed" and "T1" in orch.lead.abandoned
    assert [r["ticket_id"] for r in _replanned(bus)] == ["T1"]
    assert "T1R" in orch.lead.tickets, "kế hoạch mới vẫn được lập"


def test_ban_cu_bo_sot_thi_tick_doi_soat_dong_ticket_sau_restart(tmp_path, monkeypatch):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_h))
    monkeypatch.setattr(ticket_fsm, "_retire_replanned", lambda o, env, res: None)  # bản đang chạy trên hub bỏ sót
    monkeypatch.setattr(scheduler, "retire_accepted_replans", lambda o: None)
    _mo_lai_roi_chap_nhan(db, bus, orch)
    orch.tick()
    assert orch.lead.state["T1"] == "dispatched" and not _replanned(bus), "tiền đề: bản cũ bỏ sót"
    monkeypatch.undo()
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=_h))  # deploy bản sửa = mở lại bus
    o2.tick()
    assert o2.lead.state["T1"] == "closed" and [r["ticket_id"] for r in _replanned(bus)] == ["T1"]
    o2.tick()
    assert len(_replanned(bus)) == 1, "đối soát không ghi lặp"


def test_replan_chap_nhan_khi_ticket_cu_da_xong_thi_giu(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_h))
    _mo_lai_roi_chap_nhan(db, bus, orch)
    orch.lead.mark_done_already_integrated("T1")  # code đã vào nhánh tích hợp trước khi CR được áp
    orch.tick()
    assert orch.lead.state["T1"] == "merged" and not _replanned(bus)
