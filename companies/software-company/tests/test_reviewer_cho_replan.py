"""Agent duyệt tự động không chạy đua với change request `REPLAN-*` của cùng ticket (ADR-0051 + ADR gốc 0037).

Hub thật 2026-10-14 (QLKH-DD-CSV): DDCSV-35 blocked 17:31:43, máy nộp REPLAN-DDCSV-35-1 và mở gate escalation có lựa
chọn `replan:REPLAN-DDCSV-35-1`. `reviewer:tu-dong` duyệt mở lại gate lúc 17:33:01 — trước khi product ước lượng impact
(17:37:13) — rồi chính nó chấp nhận CR lúc 17:37:34. `_retire_replanned` thấy ticket không còn `blocked` (đã mở lại)
nên chỉ lập kế hoạch mới, không đóng DDCSV-35: ticket cũ và các ticket chia nhỏ cùng làm một việc.

Luật mới: gate có `replan:<cid>` mà CR còn `pending` → bỏ qua (chờ đường CR); CR `accepted` → ký `reject` (đóng ticket cũ,
đúng điều CLI `decide-change` dặn reviewer); CR `rejected` → xét gate như thường.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from company import gate_reviewer as gr
from company.events import Envelope
from company.gate_cli import PersistentGate
from company.gate_cli import main as gate_main
from company.llm import FakeClient
from company.roles import ROLE
from company.sqlite_bus import SQLiteBus

ID = "reviewer:tu-dong"
CID = "REPLAN-T1-1"
OK = {"decision": "approve", "root_cause": "builder hết lượt tool, WIP còn nguyên", "hint": "làm tiếp từ WIP"}


@pytest.fixture
def khoa(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry.json"))
    return gr.new_key(ID, tmp_path / "registry.json", tmp_path / "keys")


def _stub_brief(tmp_path):
    def f(orch, sid):
        p = tmp_path / f"{sid}.json"
        p.write_text(json.dumps({"subject_id": sid}), encoding="utf-8")
        return f"hồ sơ {sid}", p

    return f


def _client() -> FakeClient:
    return FakeClient(handler=lambda system, user: OK)


def _gate_replan(tmp_path, decision: str) -> Path:
    db = tmp_path / "c.sqlite"
    gate_main(
        [
            "--db",
            str(db),
            "request",
            "escalation",
            "T1",
            "--by",
            ROLE.SUPERVISOR,
            "--checklist",
            f"root_cause,decision:reopen|close,hint,replan:{CID}",
        ]
    )
    bus = SQLiteBus(db)
    bus.publish(
        Envelope(
            topic="change-requests",
            key=CID,
            actor="delivery-lead",
            payload={
                "change_id": CID,
                "project_id": "P1",
                "requested_by": "delivery-lead",
                "decision": "pending",
                "description": "replan T1",
                "impact": {"kind": "replan", "ticket_id": "T1", "generation": 1},
            },
        )
    )
    if decision != "pending":
        bus.publish(
            Envelope(
                topic="change-requests",
                key=CID,
                actor=ID,
                payload={
                    "change_id": CID,
                    "project_id": "P1",
                    "requested_by": "delivery-lead",
                    "decision": decision,
                    "description": "replan T1",
                    "impact": {"kind": "replan", "ticket_id": "T1", "decided_by": ID},
                },
            )
        )
    bus.close()
    return db


def _gate(db) -> PersistentGate:
    return PersistentGate(SQLiteBus(db))


def test_replan_con_cho_thi_khong_xet_gate(khoa, tmp_path):
    db = _gate_replan(tmp_path, "pending")
    c = _client()
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == []
    assert c.calls == [], "CR replan còn chờ: quyết gate trước là chạy đua với đường CR"
    g = _gate(db)
    assert "T1" in g.pending and gr.held(g) == {}


def test_replan_da_chap_nhan_thi_ky_dong_gate_khong_hoi_model(khoa, tmp_path):
    db = _gate_replan(tmp_path, "accepted")
    c = _client()
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == [("T1", "reject")]
    assert c.calls == [], "quyết định đã có ở CR — không cần model"
    g = _gate(db)
    assert "T1" not in g.pending
    h = [x for x in g.history if x.subject_id == "T1"][-1]
    assert h.decided_by == ID and CID in h.reason


def test_replan_bi_tu_choi_thi_xet_gate_nhu_thuong(khoa, tmp_path):
    db = _gate_replan(tmp_path, "rejected")
    c = _client()
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == [("T1", "approve")]
    assert len(c.calls) == 1


def test_replan_khong_tim_thay_cr_thi_coi_nhu_con_cho(khoa, tmp_path):
    db = tmp_path / "c.sqlite"
    gate_main(["--db", str(db), "request", "escalation", "T1", "--by", ROLE.SUPERVISOR,
               "--checklist", "root_cause,decision:reopen|close,hint,replan:REPLAN-KHONG-CO"])
    c = _client()
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == [] and c.calls == []


def test_code_tu_choi_reject_theo_replan_thi_giu(khoa, tmp_path, monkeypatch):
    db = _gate_replan(tmp_path, "accepted")

    def tu_choi(*a, **k):
        raise PermissionError("ngoài phạm vi")

    monkeypatch.setattr(gr, "decide", tu_choi)
    assert gr.run_tick(db, ID, khoa, _client(), brief_fn=_stub_brief(tmp_path)) == [("T1", "hold")]
    assert "code từ chối reject" in gr.held(_gate(db))["T1"]["reason"]
