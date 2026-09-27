"""`orchestrator redeploy <REL-xxx> --by human:x` — chạy lại lượt staging cho một RC đang kẹt.

Sự kiện `release-candidates` chỉ được xử lý MỘT lần (`processed`). Sau khi sửa một lỗi hạ tầng, các RC đang kẹt
không có đường nào chạy lại: chỉ RC MỚI mới hưởng bản vá, mà RC mới chỉ sinh khi có ticket approved chưa nằm trong
RC nào. Đo được 2026-09-06 (QLKH): vá xong deadlock `gate_release` ở staging thì 18 RC cũ vẫn kẹt vĩnh viễn, vì
14/14 ticket đều đã nằm trong một RC hợp lệ — không còn gì sinh RC mới. Người vận hành cũng không tự phát
`release-candidates` được (bus giữ topic đó cho delivery-lead), nên cần một lệnh riêng.
"""
from __future__ import annotations

import pytest

from company.events import Envelope, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from test_orchestrator import handler


def _setup(tmp_path, rid="REL-001", tid="T1"):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    client = FakeClient(handler=handler)
    orch = Orchestrator(bus, client, repo=None)
    orch.lead.tickets[tid] = Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="builder",
                                  title=tid, acceptance=["a"])
    orch.lead.state[tid] = "approved"
    orch.lead.releases.append(rid); orch.lead.release_tickets[rid] = [tid]
    bus.publish(Envelope(topic="release-candidates", key=rid, actor="delivery-lead",
                         payload={"release_id": rid, "project_id": "P", "tickets": [tid], "version": "0.1.0"}))
    orch.run()  # lượt đầu chạy hết, RC bị đánh dấu `processed`
    return bus, client, orch


def _staging_events(bus, rid="REL-001"):
    return [e for e in bus.replay(topic="release-events")
            if e.key == rid and e.payload.get("env") == "staging"]


def test_redeploy_chay_lai_luot_staging_cho_rc_da_xu_ly(tmp_path):
    bus, _client, orch = _setup(tmp_path)
    truoc = len(_staging_events(bus))
    assert truoc >= 1, "lượt đầu phải có release-event staging"
    assert not orch.queue, "RC đã xử lý xong, không còn gì trong hàng đợi — đây là chỗ RC kẹt vĩnh viễn"

    rc = orch.redeploy("REL-001", "human:lead")

    assert rc.key == "REL-001"
    assert len(_staging_events(bus)) == truoc + 1, "phải sinh thêm một lượt staging nữa"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "release.redeploy" in acts, "có audit để biết ai chạy lại và khi nào"


def test_redeploy_tu_choi_dau_vao_sai(tmp_path):
    _bus, _client, orch = _setup(tmp_path)
    with pytest.raises(ValueError, match="human"):
        orch.redeploy("REL-001", "delivery-lead")
    with pytest.raises(ValueError, match="không có release-candidate"):
        orch.redeploy("REL-404", "human:lead")
    orch._void("REL-001")
    with pytest.raises(ValueError, match="đã bị huỷ"):
        orch.redeploy("REL-001", "human:lead")


def test_redeploy_dung_client_that_khong_phai_fake(tmp_path, monkeypatch):
    """`redeploy` GỌI MODEL (lượt staging của release-engineer) nên CLI phải cấp client thật. Thiếu nó thì lệnh
    chạy bằng FakeClient và chết "FakeClient hết câu trả lời" — đo được 2026-09-06 khi chạy thật trên QLKH."""
    import company.orchestrator as O
    goi = []
    monkeypatch.setattr("company.llm.make_client", lambda *a, **k: (goi.append(1), FakeClient(handler=handler))[1])
    bus, _client, _orch = _setup(tmp_path)
    db = str(tmp_path / "c.sqlite"); bus.close()
    O.main(["--db", db, "redeploy", "REL-001", "--by", "human:lead"])
    assert goi, "CLI phải gọi make_client() cho `redeploy`, không dùng FakeClient mặc định"


def test_cli_redeploy(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("company.llm.make_client", lambda *a, **k: FakeClient(handler=handler))
    bus, _client, _orch = _setup(tmp_path)
    db = str(tmp_path / "c.sqlite")
    bus.close()

    assert orch_main(["--db", db, "redeploy", "REL-001", "--by", "human:lead"]) == 0
    assert "REL-001" in capsys.readouterr().out

    assert orch_main(["--db", db, "redeploy", "REL-404", "--by", "human:lead"]) == 2
    assert "không có release-candidate" in capsys.readouterr().err

    # lease đang bị TIẾN TRÌNH KHÁC giữ (orchestrator đang watch): không chạy chồng lên
    from xagents_core import sqlite_bus as SB  # `_alive`/`Lease` lên core ở K3.5c
    (tmp_path / "c.sqlite.lock").write_text("999999", encoding="utf-8")
    that = SB._alive
    SB._alive = lambda pid: True
    try:
        assert orch_main(["--db", db, "redeploy", "REL-001", "--by", "human:lead"]) == 3
        assert "đang chạy" in capsys.readouterr().err
    finally:
        SB._alive = that
        (tmp_path / "c.sqlite.lock").unlink(missing_ok=True)


def test_cli_redeploy_luot_staging_loi_thi_ma_thoat_khac_0(tmp_path, capsys, monkeypatch):
    """Audit 2026-09-27 B1: `redeploy` in "đã chạy lại" và thoát 0 cả khi lượt staging LỖI — `StepResult` của
    `_call` bị vứt, script vận hành không phân biệt được chạy lại thành công với chạy lại hỏng."""
    from company.llm import LLMError
    from test_orchestrator import _agent_of

    def hong(system, user):
        if _agent_of(system) == "ops":
            raise LLMError("model sập giữa lượt")
        return handler(system, user)

    monkeypatch.setattr("company.llm.make_client", lambda *a, **k: FakeClient(handler=hong))
    bus, _client, _orch = _setup(tmp_path)
    db = str(tmp_path / "c.sqlite"); bus.close()

    assert orch_main(["--db", db, "redeploy", "REL-001", "--by", "human:lead"]) == 1
    cap = capsys.readouterr()
    assert "đã chạy lại" not in cap.out
    assert "model sập giữa lượt" in cap.err
