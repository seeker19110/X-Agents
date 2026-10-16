"""ADR-0060: vượt ngân sách đầu ra khi phiên agent ĐÃ XONG (trả lời cuối, không còn `tool_calls`) → giữ kết quả, ghi
`budget_overrun`; supervisor thấy output thật và `budget_cut` như mọi ticket chạm trần. Còn định gọi tool thì vẫn dừng.

Hub thật (QLKH-DD-CSV, 2026-10-12 → 16): 24 lượt `budget_exhausted` của builder (backend `claude -p`, cả phiên là một
lời gọi) bỏ 60,1M token đã tiêu; DDCSV-117 vượt 5,6 % mà mất 4,2M.

Hai chiều (luật bắt buộc 4): bỏ nhánh "phiên đã xong" trong `AgentRunner._loop` → 2/2 ca đầu đỏ; ca 3 (vòng tool
còn chạy vẫn dừng) giữ xanh ở cả hai chiều — nó canh để bản sửa không nới hàng rào cũ."""

from __future__ import annotations

import json
from typing import Any

import pytest

from company.bus import InMemoryBus
from company.events import Envelope, Task
from company.llm import Completion, FakeClient
from company.runner import AgentRunner, RunnerError
from company.supervisor import Supervisor
from company.tools import WorkspaceTools
from company.workspace import TicketWorkspace
from test_tools_and_agentic import _init_repo, _pr, _task_env, _tc


class _CliPhienDai(FakeClient):
    """Mode `cli` (ADR-0023): cả phiên agent trong một lời gọi, trả lời cuối ngay, output 5 000 token."""

    def complete(self, **kw: Any) -> Completion:
        return Completion(
            text=json.dumps(_pr({"ticket_id": "T1"}), ensure_ascii=False),
            input_tokens=400_000,
            output_tokens=5_000,
            model="fake",
            tool_mode="cli",
        )


def _acts(bus) -> list[dict]:
    return [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] != "token_estimate"]


def test_phien_da_xong_vuot_ngan_sach_thi_giu_ket_qua_va_ghi_budget_overrun(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    ws.create()
    bus = InMemoryBus()
    g = AgentRunner(bus, _CliPhienDai()).generate(
        "builder", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox(), budget=3_000
    )
    assert g.payloads[0]["ticket_id"] == "T1", "token đã tiêu — kết quả không bị bỏ"
    acts = _acts(bus)
    assert "budget_exhausted" not in [a["action"] for a in acts]
    ov = next(a for a in acts if a["action"] == "budget_overrun")
    assert ov["tokens"] == 0 and ov["output_tokens"] == 0, "token nằm ở audit `produced:*`, không đếm hai lần"
    assert json.loads(ov["evidence"]) == {"output": 5_000, "budget": 3_000, "turn": 1}


def test_supervisor_thay_output_that_va_cat_ticket_sau_khi_giu_ket_qua(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    ws.create()
    bus = InMemoryBus()
    sup = Supervisor(bus)
    t = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R",
        assignee="builder",
        title="x",
        acceptance=["a"],
        budget_tokens=3_000,
    )
    env = Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=t.model_dump())
    bus.publish(env)
    runner = AgentRunner(bus, _CliPhienDai())
    g = runner.generate("builder", env, "pull-requests", tools=WorkspaceTools(ws).toolbox(), budget=3_000)
    runner.publish("builder", env, "pull-requests", g.payloads[0], generated=g)
    assert [e.key for e in bus.replay(topic="pull-requests")] == ["T1"]
    assert sup.budgets["T1"].output_used == 5_000 and sup.actions[-1].action == "budget_cut", (
        "trần vẫn có hiệu lực: ticket dừng ở gate thay vì bị giao lại"
    )


def test_vong_tool_con_chay_vuot_ngan_sach_van_dung(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    ws.create()
    client = FakeClient(
        handler=lambda s, u: {},
        tool_handler=lambda msgs, tools: [_tc("read_file", path="mod.py")],
        tokens_per_call=(1_000, 4_000),
    )
    bus = InMemoryBus()
    with pytest.raises(RunnerError, match="vượt ngân sách"):
        AgentRunner(bus, client).generate(
            "builder", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox(), budget=3_000
        )
    assert [a["action"] for a in _acts(bus)][-1] == "budget_exhausted" and len(client.calls) == 1
