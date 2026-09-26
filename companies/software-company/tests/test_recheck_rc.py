"""`orchestrator recheck <REL-xxx> --by human:x|reviewer:y` — chấm lại release-check của security với bằng chứng mới
(ADR-0047 §5).

`release-candidates` chỉ được xử lý MỘT lần (`processed`), nên sau khi PR bằng chứng (SBOM/license ADR-0046, DAST
ADR-0047) merge, RC cũ bị chặn không có đường nào được chấm bằng bằng chứng mới — đo được 2026-09-27 với
CAMPUS-UNI REL-007. `redeploy` chạy lại lượt STAGING, không phải lượt security; lệnh này là đường riêng.
"""

from __future__ import annotations

import pytest

from company.events import Envelope, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, handler


def _setup(tmp_path, risk_tags=("auth",), h=handler):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=h), repo=None)
    orch.lead.tickets["T1"] = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title="T1",
        acceptance=["a"],
        risk_tags=list(risk_tags),
    )
    orch.lead.state["T1"] = "approved"
    orch.lead.releases.append("REL-001")
    orch.lead.release_tickets["REL-001"] = ["T1"]
    bus.publish(
        Envelope(
            topic="release-candidates",
            key="REL-001",
            actor="delivery-lead",
            payload={"release_id": "REL-001", "project_id": "P", "tickets": ["T1"], "version": "0.1.0"},
        )
    )
    orch.run()  # lượt đầu chạy hết, RC bị đánh dấu `processed`
    return bus, orch


def _security(bus) -> list[dict]:
    return [
        e.payload
        for e in bus.replay(topic="review-results")
        if e.payload.get("source") == "security" and e.payload.get("ticket_id") == "REL-001"
    ]


def test_recheck_chay_lai_security_voi_bang_chung_moi_giu_waiver(tmp_path):
    bus, orch = _setup(tmp_path)
    truoc = len(_security(bus))
    assert truoc == 1 and not orch.queue, "RC đã xử lý xong — đây là chỗ RC bị chặn nằm yên"
    orch.lead.release_waived["REL-001"].add("security")  # người đã chấp nhận rủi ro ở gate escalation

    rc = orch.recheck("REL-001", "reviewer:phien-chinh")

    assert rc.key == "REL-001"
    sec = _security(bus)
    assert len(sec) == truoc + 1, "một lượt security nữa trên cùng RC"
    assert "dast" in sec[-1]["evidence"] and "supply_chain" in sec[-1]["evidence"], "bằng chứng máy dựng lại"
    assert "security" in orch.lead.release_waived["REL-001"], "recheck không huỷ quyết định đã có của người"
    rec = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.recheck"]
    assert rec and rec[-1]["actor"] == "reviewer:phien-chinh"
    assert not [e for e in bus.replay(topic="release-events") if e.payload.get("env") == "staging"][1:], (
        "không chạy lại staging: đó là việc của `redeploy`"
    )


def test_recheck_goi_dung_luot_security_khong_goi_agent_khac(tmp_path):
    goi: list[str] = []

    def h(system, user):
        goi.append(_agent_of(system))
        return handler(system, user)

    _bus, orch = _setup(tmp_path, h=h)
    goi.clear()
    orch.recheck("REL-001", "human:lead")
    assert goi == ["security"]


def test_recheck_tu_choi_dau_vao_sai(tmp_path):
    _bus, orch = _setup(tmp_path)
    with pytest.raises(ValueError, match="human"):
        orch.recheck("REL-001", "security")
    with pytest.raises(ValueError, match="không có release-candidate"):
        orch.recheck("REL-404", "human:lead")
    orch.delivered["REL-001"] = {"tag": "v0.1.0"}
    with pytest.raises(ValueError, match="đã giao"):
        orch.recheck("REL-001", "human:lead")
    orch.delivered.pop("REL-001")
    orch._void("REL-001")
    with pytest.raises(ValueError, match="đã bị huỷ"):
        orch.recheck("REL-001", "human:lead")


def test_recheck_rc_khong_can_security_thi_tu_choi(tmp_path):
    _bus, orch = _setup(tmp_path, risk_tags=())
    with pytest.raises(ValueError, match="không cần security"):
        orch.recheck("REL-001", "human:lead")


def test_cli_recheck_dung_client_that_va_lease(tmp_path, capsys, monkeypatch):
    """`recheck` GỌI MODEL (lượt security) nên CLI phải cấp client thật, như `redeploy` (đo được 2026-09-06)."""
    goi = []
    monkeypatch.setattr("company.llm.make_client", lambda *a, **k: (goi.append(1), FakeClient(handler=handler))[1])
    # ticket của `_setup` dựng tay trong RAM, không có trên bus để tiến trình CLI dựng lại risk_tags — phần "cần
    # security" đã có test riêng ở trên; ở đây đo client/lease/mã thoát.
    monkeypatch.setattr("company.delivery.DeliveryLead.release_needs_security", lambda self, rid: True)
    bus, _orch = _setup(tmp_path)
    db = str(tmp_path / "c.sqlite")
    bus.close()

    assert orch_main(["--db", db, "recheck", "REL-001", "--by", "reviewer:phien-chinh"]) == 0
    assert "REL-001" in capsys.readouterr().out and goi

    assert orch_main(["--db", db, "recheck", "REL-404", "--by", "human:lead"]) == 2
    assert "không có release-candidate" in capsys.readouterr().err

    from xagents_core import sqlite_bus as SB

    (tmp_path / "c.sqlite.lock").write_text("999999", encoding="utf-8")
    that = SB._alive
    SB._alive = lambda pid: True
    try:
        assert orch_main(["--db", db, "recheck", "REL-001", "--by", "human:lead"]) == 3
    finally:
        SB._alive = that
        (tmp_path / "c.sqlite.lock").unlink(missing_ok=True)
