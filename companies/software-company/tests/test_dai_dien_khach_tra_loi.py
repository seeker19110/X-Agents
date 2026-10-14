"""ADR gốc 0038 bước 1: agent đại diện khách (`reviewer:*` ở phạm vi `toan-bo`) phát được `clarification-answers`.

Hub thật 2026-10-14 (QLKH-DD-CSV): `product` hỏi ba câu làm rõ cho CR-DDCSV-INFRA-002; chủ dự án đã trả lời trong
chat, nhưng ACL bus và CLI chỉ cho `human:*` phát `clarification-answers` — phiên chính chỉ còn cách giả danh người
(cấm) hoặc chờ 24 h để orchestrator lấy `default` (sai ý chủ dự án ở CQ-CR2-01).

Cùng luật ghi/tin với change request (ADR gốc 0035): CLI kiểm `cr_actor_refusal` khi ghi; orchestrator chỉ tính câu
trả lời của reviewer khi cờ + phạm vi đang bật.
"""

from __future__ import annotations

import json

import pytest

from company.bus import InMemoryBus
from company.core import REVIEWER_FAMILY, TOPIC_PRODUCERS
from company.gate_reviewer import FLAG_ENV, SCOPE_ENV, SCOPE_RONG, SCOPE_TOAN_BO
from company.llm import FakeClient
from company.orch.guards import pending_clarifications
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _pub, _topics, handler

ANS = {
    "project_id": "P1",
    "answers": [{"question_id": "Q1", "answer": "a — theo lệnh chủ dự án trong chat 2026-10-14"}],
}


@pytest.fixture
def toan_bo(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(SCOPE_ENV, SCOPE_TOAN_BO)


@pytest.fixture
def khong_co(monkeypatch):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(SCOPE_ENV, raising=False)


def _ans_file(tmp_path):
    f = tmp_path / "ans.json"
    f.write_text(json.dumps(ANS), encoding="utf-8")
    return f


def test_bus_cho_ho_reviewer_phat_clarification_answers():
    assert REVIEWER_FAMILY in TOPIC_PRODUCERS["clarification-answers"]


def test_cli_publish_clarification_answers_nhan_reviewer_khi_toan_bo(tmp_path, toan_bo):
    db = tmp_path / "c.sqlite"
    rc = orch_main(
        [
            "--db",
            str(db),
            "publish",
            "clarification-answers",
            str(_ans_file(tmp_path)),
            "--actor",
            "reviewer:phien-chinh",
        ]
    )
    assert rc == 0
    got = list(SQLiteBus(db).replay(topic="clarification-answers"))
    assert [e.actor for e in got] == ["reviewer:phien-chinh"]


@pytest.mark.parametrize("scope", [None, SCOPE_RONG])
def test_cli_tu_choi_reviewer_tra_loi_khi_khong_toan_bo(tmp_path, khong_co, monkeypatch, capsys, scope):
    if scope is not None:
        monkeypatch.setenv(FLAG_ENV, "1")
        monkeypatch.setenv(SCOPE_ENV, scope)
    db = tmp_path / "c.sqlite"
    rc = orch_main(
        [
            "--db",
            str(db),
            "publish",
            "clarification-answers",
            str(_ans_file(tmp_path)),
            "--actor",
            "reviewer:phien-chinh",
        ]
    )
    assert rc == 2 and "ADR gốc 0038" in capsys.readouterr().err
    assert not list(SQLiteBus(db).replay(topic="clarification-answers"))


def _toi_cau_hoi():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    assert _topics(bus)[-1] == "clarification-questions"
    return bus, orch


def test_orchestrator_tinh_cau_tra_loi_cua_reviewer_khi_toan_bo(toan_bo):
    bus, orch = _toi_cau_hoi()
    _pub(bus, "clarification-answers", "P1", "reviewer:phien-chinh", ANS)
    orch.run()
    assert "approved-specs" in _topics(bus), "câu trả lời của agent đại diện khách đủ để viết spec"
    assert "P1" not in pending_clarifications(bus)


def test_orchestrator_bo_qua_cau_tra_loi_cua_reviewer_khi_tat_co(khong_co):
    bus, orch = _toi_cau_hoi()
    _pub(bus, "clarification-answers", "P1", "reviewer:phien-chinh", ANS)
    orch.run()
    assert "approved-specs" not in _topics(bus), "bỏ cờ thì câu trả lời của reviewer không được tính"
    assert pending_clarifications(bus)["P1"]["unanswered"] == ["Q1"], "vẫn chờ người trả lời"
