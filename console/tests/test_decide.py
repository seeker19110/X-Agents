"""decide(): đi qua HumanGate thật của từng công ty (four-eyes, allowlist, audit-log)."""
from __future__ import annotations

from pathlib import Path

import pytest
from company.gate_cli import PersistentGate as CompanyGate
from company.sqlite_bus import SQLiteBus as CompanySQLiteBus
from studio.gates import APPROVERS_ENV

from console.collect import COMPANY, STUDIO, collect
from console.decide import GateError, decide

DEAD_GATEWAY = "http://127.0.0.1:9"


def test_duyet_gate_that(company_db: Path, studio_db: Path) -> None:
    out = decide(company_db, studio_db, subject_id="PLAN-1", xuong=COMPANY, decision="approve",
                 by="human:pm", reason="ok")
    assert out["ok"] is True and out["subject_id"] == "PLAN-1" and out["decision"] == "approve"
    assert out["event_id"]
    # quyết định nằm trong bus của công ty và gate không còn chờ
    bus = CompanySQLiteBus(company_db)
    try:
        gate = CompanyGate(bus)
        assert "PLAN-1" not in gate.pending and gate.is_approved("PLAN-1")
        assert any(e.event_id == out["event_id"] and e.payload["action"] == "gate.decide"
                   for e in bus.replay(topic="audit-log"))
    finally:
        bus.close()
    assert "PLAN-1" not in {g["id"] for g in collect(company_db, studio_db, gateway_url=DEAD_GATEWAY)["gates"]}


def test_four_eyes_chan_nguoi_tao(company_db: Path, studio_db: Path) -> None:
    with pytest.raises(GateError) as e:
        decide(company_db, studio_db, subject_id="PLAN-1", xuong=COMPANY, decision="approve",
               by="delivery-lead", reason="tự duyệt")
    assert "four-eyes" in str(e.value)
    assert "PLAN-1" in {g["id"] for g in collect(company_db, studio_db, gateway_url=DEAD_GATEWAY)["gates"]}


def test_allowlist_nguoi_duyet_cua_xuong_video(company_db: Path, studio_db: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(APPROVERS_ENV, "human:owner")
    with pytest.raises(GateError) as e:
        decide(company_db, studio_db, subject_id="PUB-vid-042", xuong=STUDIO, decision="approve",
               by="human:khach-la", reason="")
    assert "danh sách người duyệt" in str(e.value)
    out = decide(company_db, studio_db, subject_id="PUB-vid-042", xuong=STUDIO, decision="approve",
                 by="human:owner", reason="ok")
    assert out["ok"] and out["event_id"]


def test_subject_khong_co_gate_cho(company_db: Path, studio_db: Path) -> None:
    with pytest.raises(GateError) as e:
        decide(company_db, studio_db, subject_id="TCK-999", xuong=COMPANY, decision="approve", by="human:pm", reason="")
    assert "không có gate chờ" in str(e.value)


def test_xuong_la(company_db: Path, studio_db: Path) -> None:
    with pytest.raises(ValueError, match="xưởng lạ"):
        decide(company_db, studio_db, subject_id="PLAN-1", xuong="phòng-marketing", decision="approve",
               by="human:pm", reason="")


def test_verb_quyet_dinh_la(company_db: Path, studio_db: Path) -> None:
    for verb in ("merge", "pending", ""):
        with pytest.raises(ValueError, match="quyết định lạ"):
            decide(company_db, studio_db, subject_id="PLAN-1", xuong=COMPANY, decision=verb, by="human:pm", reason="")


def test_thieu_db(tmp_path: Path, studio_db: Path) -> None:
    with pytest.raises(GateError, match="chưa có file DB"):
        decide(tmp_path / "khong-co.sqlite", studio_db, subject_id="PLAN-1", xuong=COMPANY, decision="approve",
               by="human:pm", reason="")
    with pytest.raises(GateError, match="chưa có file DB"):
        decide(None, studio_db, subject_id="PLAN-1", xuong=COMPANY, decision="approve", by="human:pm", reason="")


def test_thieu_nguoi_duyet(company_db: Path, studio_db: Path) -> None:
    with pytest.raises(ValueError, match="người duyệt"):
        decide(company_db, studio_db, subject_id="PLAN-1", xuong=COMPANY, decision="approve", by="  ", reason="")
    with pytest.raises(ValueError, match="subject_id"):
        decide(company_db, studio_db, subject_id="", xuong=COMPANY, decision="approve", by="human:pm", reason="")
