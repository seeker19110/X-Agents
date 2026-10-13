"""Bài học estimate-vs-actual đo cùng thước với trần ngân sách: TOKEN ĐẦU RA.

`budget_cut` so `output_used` với `budget_tokens` từ 2026-09-04 (`xagents_core.supervisor.Budget.ratio`: đếm cả input
thì mọi ticket nhiều lượt tool bị cắt oan). Bài học lại ghi `ratio = used / estimate` — `used` gồm cả input đọc lại từ
cache qua ~25 lượt nội bộ của `claude -p`. Đo hub thật 2026-10-13 (QLKH-DD-CSV): DDCSV-40 ước 110k, đầu ra 31,8k
(0,29), bài học ghi 1,57M (14,3); trung vị builder ~11× — `calibration()` đưa hệ số sai thước đó cho product ở mỗi lượt
lập kế hoạch, trong khi ticket > 200k token bị `_check_plan` chặn.
"""

from __future__ import annotations

import json

from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.events import AuditLog, Envelope, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.supervisor import Supervisor
from test_orchestrator import handler


def _ticket(bus: InMemoryBus, orch: Orchestrator) -> None:
    t = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title="x",
        acceptance=["a"],
        estimate_tokens=100_000,
        budget_tokens=150_000,
    )
    bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=t.model_dump()))
    orch.lead.tickets["T1"] = t
    bus.publish(
        Envelope(
            topic="audit-log",
            key="builder",
            actor="builder",
            payload=AuditLog(
                actor="builder",
                action="produced:pull-requests",
                ticket_id="T1",
                project_id="P",
                tokens=1_000_000,
                output_tokens=30_000,
            ).model_dump(),
        )
    )


def test_bai_hoc_do_dau_ra_so_uoc_luong():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _ticket(bus, orch)
    orch._record_lesson("T1")
    d = json.loads(orch.blackboard.read("knowledge").summary)
    assert d["output_tokens"] == 30_000 and d["actual_tokens"] == 1_000_000, "giữ cả tổng để báo cáo chi phí"
    assert d["ratio"] == 0.3, f"ratio = đầu ra / estimate, cùng thước với budget_cut (nhận {d['ratio']})"
    assert orch.supervisor.calibration()["builder"]["ratio_median"] == 0.3


def test_calibration_bo_bai_hoc_cu_do_bang_tong_token():
    """Bài học ghi trước bản sửa không mang `output_tokens` — ratio của nó là tổng/estimate, sai thước: không đưa vào
    hệ số. Không có mẫu thì planner ghi "chưa có tham chiếu" (skill cost-estimation), tốt hơn một hệ số 11× sai."""
    bus = InMemoryBus()
    sup = Supervisor(bus)
    bb = Blackboard(bus)
    bb.write(
        "supervisor",
        "knowledge",
        "audit-log:lesson:T9",
        json.dumps(
            {
                "ticket_id": "T9",
                "assignee": "builder",
                "estimate_tokens": 110_000,
                "actual_tokens": 1_571_533,
                "ratio": 14.29,
            }
        ),
    )
    assert sup.calibration() == {}
    bb.write(
        "supervisor",
        "knowledge",
        "audit-log:lesson:T8",
        json.dumps(
            {
                "ticket_id": "T8",
                "assignee": "builder",
                "estimate_tokens": 100_000,
                "actual_tokens": 900_000,
                "output_tokens": 40_000,
                "ratio": 0.4,
            }
        ),
    )
    assert sup.calibration() == {"builder": {"ratio_median": 0.4, "samples": 1}}
