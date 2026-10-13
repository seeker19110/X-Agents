"""Họ lỗi "hết phiên `claude -p`" còn sót sau #476 — hai chỗ khác cùng đọc lỗi tạm thời như lỗi thật.

Đo hub thật 2026-10-13 (QLKH-DD-CSV), gói hết phiên 07:35 → "resets 6:30pm (Asia/Bangkok)" (11:31 UTC):
- Watchdog: DDCSV-43 bị escalate "không hoạt động > 4 giờ" lúc 11:23, DDCSV-40 lúc 11:30 — trong khi event của chúng
  đang nằm trong hẹn `defer.until` 11:31 của backend. Im lặng vì hệ thống ĐƯỢC BẢO chờ, không phải vì kẹt.
- Agent duyệt tự động: gặp 429 hết phiên thì ghi `reviewer.hold` "model lỗi: … 429" cho DDCSV-43 lúc 11:24 — hold là
  vĩnh viễn ở thế hệ gate đó, phiên chính phải tự duyệt thay cho một lỗi tự hết sau 7 phút.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from company import gate_reviewer as gr
from company.bus import InMemoryBus
from company.events import AuditLog, Envelope
from company.gate_cli import PersistentGate
from company.gate_cli import main as gate_main
from company.llm import FakeClient, TransientError
from company.orchestrator import Orchestrator
from company.roles import ROLE
from company.sqlite_bus import SQLiteBus
from company.supervisor import IDLE_REASON
from test_gate_reviewer import TICKET
from test_orchestrator import HET_PHIEN, _drive_to_spec_gate, handler

ID = "reviewer:tu-dong"
OK = {"decision": "approve", "root_cause": "builder hết lượt tool, WIP còn nguyên", "hint": "làm tiếp từ WIP"}


# ---------- watchdog ----------


def _builder_het_phien(bus, orch, monkeypatch):
    _drive_to_spec_gate(bus, orch)
    goc = orch.runner.generate

    def gen(agent, env, topic, *a, **k):
        if agent == "builder":
            raise TransientError(HET_PHIEN)
        return goc(agent, env, topic, *a, **k)

    monkeypatch.setattr(orch.runner, "generate", gen)
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    orch.run()


def _idle(bus) -> set[str]:
    return {
        e.payload["target"]
        for e in bus.replay(topic="supervisor-actions")
        if e.payload.get("action") == "escalate" and str(e.payload.get("reason", "")).startswith(IDLE_REASON)
    }


def test_ticket_dang_trong_hen_reset_khong_bi_watchdog_danh_khong_hoat_dong(monkeypatch):
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _builder_het_phien(bus, orch, monkeypatch)
    hen = {
        env.payload.get("ticket_id") or env.key
        for eid, (env, _) in orch.deferred.items()
        if orch.defer_until.get(eid, 0.0) > 0
    }
    assert hen, "builder hết phiên → event `tasks` hoãn có hẹn reset"
    orch.tick(now=datetime.now(UTC) + timedelta(hours=5))
    assert not (hen & _idle(bus)), "đang trong hẹn của backend là chờ có chủ đích, không phải im lặng"


def test_het_hen_roi_ma_van_im_lang_thi_watchdog_van_bat(monkeypatch):
    """Chiều ngược: miễn trừ chỉ sống trong hẹn. Hẹn đã qua (event đã thử lại, vẫn nằm đó) → đếm im lặng như cũ."""
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _builder_het_phien(bus, orch, monkeypatch)
    tids = {env.payload.get("ticket_id") or env.key for env, _ in orch.deferred.values()}
    orch.defer_until.clear()
    orch.deferred.clear()
    orch.tick(now=datetime.now(UTC) + timedelta(hours=5))
    assert tids & _idle(bus)


# ---------- agent duyệt tự động ----------


@pytest.fixture
def khoa(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry.json"))
    return gr.new_key(ID, tmp_path / "registry.json", tmp_path / "keys")


def _client(payload=None, raise_=None) -> FakeClient:
    def h(system, user):
        if raise_ is not None:
            raise raise_
        return payload or {}

    return FakeClient(handler=h)


def _stub_brief(tmp_path):
    def f(orch, sid):
        p = tmp_path / f"{sid}.json"
        p.write_text(json.dumps({"subject_id": sid}), encoding="utf-8")
        return f"hồ sơ {sid}", p

    return f


def _gate_t1(tmp_path) -> Path:
    db = tmp_path / "c.sqlite"
    gate_main(
        ["--db", str(db), "request", "escalation", "T1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(TICKET)]
    )
    return db


def _hold_actions(db) -> list[str]:
    bus = SQLiteBus(db)
    try:
        return [
            e.payload["action"]
            for e in bus.replay(topic="audit-log")
            if e.payload.get("action") in {gr.HOLD_ACTION, "reviewer.cr_hold"}
        ]
    finally:
        bus.close()


def test_gate_gap_het_phien_khong_ghi_hold_va_vong_sau_hoi_lai(khoa, tmp_path):
    db = _gate_t1(tmp_path)
    with pytest.raises(TransientError):
        gr.run_tick(db, ID, khoa, _client(raise_=TransientError(HET_PHIEN)), brief_fn=_stub_brief(tmp_path))
    assert _hold_actions(db) == [], "lỗi tạm thời của backend không phải lý do giữ gate"
    assert gr.run_tick(db, ID, khoa, _client(OK), brief_fn=_stub_brief(tmp_path)) == [("T1", "approve")]


def test_cr_gap_het_phien_khong_ghi_hold(khoa, tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    cid = "REPLAN-T1-1"
    bus.publish(
        Envelope(
            topic="change-requests",
            key=cid,
            actor="delivery-lead",
            payload={
                "change_id": cid,
                "project_id": "P1",
                "requested_by": "delivery-lead",
                "decision": "pending",
                "description": "replan",
                "impact": {"kind": "replan", "ticket_id": "T1"},
            },
        )
    )
    bus.publish(
        Envelope(
            topic="audit-log",
            key=cid,
            actor="product",
            payload=AuditLog(actor="product", action="change.impact", evidence="2 ticket mới").model_dump(),
        )
    )
    bus.close()
    with pytest.raises(TransientError):
        gr.run_tick(db, ID, khoa, _client(raise_=TransientError(HET_PHIEN)))
    assert _hold_actions(db) == []


def test_cli_run_gap_het_phien_nghi_toi_moc_reset(khoa, tmp_path, monkeypatch, capsys):
    db = _gate_t1(tmp_path)
    monkeypatch.setattr("company.llm.make_client", lambda *a, **k: _client(raise_=TransientError(HET_PHIEN)))
    monkeypatch.setattr(gr, "_brief_cua", lambda db, repo: _stub_brief(tmp_path))
    ngu: list[float] = []

    def sleep(s: float) -> None:
        ngu.append(s)
        raise KeyboardInterrupt

    monkeypatch.setattr(gr.time, "sleep", sleep)
    assert gr.main(["--db", str(db), "run", "--id", "tu-dong", "--key", str(khoa), "--watch", "7"]) == 0
    assert ngu and ngu[0] >= 60, f"nghỉ tới mốc 'resets 6:30pm', không phải nhịp 7 s (nghỉ {ngu})"
    assert "nghỉ" in capsys.readouterr().out
    assert _hold_actions(db) == []


def test_cli_run_once_gap_loi_tam_thoi_khong_hen_gio_thi_thoat_sach(khoa, tmp_path, monkeypatch, capsys):
    db = _gate_t1(tmp_path)
    monkeypatch.setattr("company.llm.make_client", lambda *a, **k: _client(raise_=TransientError("503 overloaded")))
    monkeypatch.setattr(gr, "_brief_cua", lambda db, repo: _stub_brief(tmp_path))
    assert gr.main(["--db", str(db), "run", "--id", "tu-dong", "--key", str(khoa), "--once"]) == 0
    assert "T1" in PersistentGate(SQLiteBus(db)).pending and _hold_actions(db) == []
