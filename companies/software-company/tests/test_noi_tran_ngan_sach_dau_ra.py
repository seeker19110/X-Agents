"""Duyệt escalation cấp thêm ngân sách ticket theo ĐÚNG thước của trần: token ĐẦU RA.

`budget_cut` so `output_used` với `limit` (`Budget.ratio`, 2026-09-04). `_on_escalation_decided` lại nới
`limit = max(limit, used) + budget_tokens` — `used` là TỔNG token kể cả input đọc lại từ cache qua ~25 lượt nội bộ của
`claude -p`. Đo hub thật 2026-10-14 (QLKH-DD-CSV): DDCSV-43 được nới lên 918 814 token trong khi đầu ra cả ticket cỡ
30k — sau một lần duyệt, trần ngân sách của ticket coi như tắt.
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.events import AuditLog, Envelope
from company.llm import FakeClient, LLMError
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import ENGINEERING, _agent_of, _drive_to_plan, handler


def _hong_luon(system, user):
    if _agent_of(system) in ENGINEERING:
        raise LLMError("agent kỹ thuật hỏng")
    return handler(system, user)


def _tieu(bus, tokens: int, output: int) -> None:
    bus.publish(
        Envelope(
            topic="audit-log",
            key="builder",
            actor="builder",
            payload=AuditLog(
                actor="builder",
                action="produced:pull-requests",
                ticket_id="T1",
                project_id="P1",
                tokens=tokens,
                output_tokens=output,
            ).model_dump(),
        )
    )


def test_duyet_escalation_noi_tran_theo_dau_ra_khong_theo_tong():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_hong_luon))
    _drive_to_plan(bus, orch)
    orch.run()
    assert orch.lead.state["T1"] == "blocked"
    b = orch.supervisor.budgets["T1"]
    _tieu(bus, tokens=900_000, output=b.limit // 2)
    truoc, them = b.limit, orch.lead.tickets["T1"].budget_tokens
    orch.gate.decide("T1", "approve", by="human:lead", reason="root_cause: x; decision: reopen; hint: y")
    orch.run()
    assert b.limit == max(truoc, b.output_used) + them, f"nới theo đầu ra, không theo tổng (limit={b.limit})"


def test_tran_da_noi_song_sot_qua_restart(tmp_path):
    """Mốc nới chỉ nằm trong RAM: mở lại bus thì `limit` về `budget_tokens` gốc trong khi `output_used` dựng lại đủ
    — ticket vừa được duyệt chạy tiếp lại vượt trần ngay. `budget.extended` mang `limit` mới: dựng lại từ đó."""
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = Orchestrator(bus, FakeClient(handler=_hong_luon))
    _drive_to_plan(bus, orch)
    orch.run()
    orch.gate.decide("T1", "approve", by="human:lead", reason="root_cause: x; decision: reopen; hint: y")
    orch.run()
    noi = orch.supervisor.budgets["T1"].limit
    bus.close()
    bus2 = SQLiteBus(db)
    try:
        orch2 = Orchestrator(bus2, FakeClient(handler=_hong_luon))
        assert orch2.supervisor.budgets["T1"].limit == noi
    finally:
        bus2.close()


def test_budget_extended_evidence_hong_thi_bo_qua_khong_no():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_hong_luon))
    _drive_to_plan(bus, orch)
    orch.run()
    truoc = orch.supervisor.budgets["T1"].limit
    bus.publish(
        Envelope(
            topic="audit-log",
            key="orchestrator",
            actor="orchestrator",
            payload=AuditLog(
                actor="orchestrator", action="budget.extended", ticket_id="T1", evidence="không phải json"
            ).model_dump(),
        )
    )
    assert orch.supervisor.budgets["T1"].limit == truoc
    bus.publish(
        Envelope(
            topic="audit-log",
            key="orchestrator",
            actor="orchestrator",
            payload=AuditLog(
                actor="orchestrator", action="budget.extended", ticket_id="T-LA", evidence='{"limit": 5}'
            ).model_dump(),
        )
    )
    assert "T-LA" not in orch.supervisor.budgets, "ticket chưa có sổ ngân sách thì không tự tạo sổ"
