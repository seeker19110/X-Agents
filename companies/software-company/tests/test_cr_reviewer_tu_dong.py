"""ADR gốc 0037: agent duyệt tự động `reviewer:tu-dong` quyết change request do MÁY nộp (`REPLAN-*`, `REWORK-*`,
`GATE3-*`) sau khi product đã ước lượng impact.

Đo hub thật 2026-10-13 (QLKH-DD-CSV): REPLAN-DDCSV-31-1 chờ từ 06:16 tới 07:18 chỉ vì không ai quyết — `run_tick` chỉ
đi qua `gate.pending`. Đo hai chiều: CR máy + impact → model được hỏi đúng một lần, quyết định đi đúng đường
`decide-change`; CR của người, CR chưa có impact, phạm vi hẹp hơn `toan-bo` → không đụng tới.
"""

from __future__ import annotations

import json

import pytest

from company import gate_reviewer as gr
from company.events import AuditLog, Envelope
from company.llm import FakeClient, LLMError
from company.orch.guards import _cr_accepted_when
from company.sqlite_bus import SQLiteBus

ID = "reviewer:tu-dong"
CID = "REPLAN-T1-1"
CR = {
    "change_id": CID,
    "project_id": "P1",
    "requested_by": "delivery-lead",
    "decision": "pending",
    "description": "Ticket T1 hết 3 lần retry; lập lại kế hoạch: A (adapter SQL), B (wiring)",
    "impact": {"kind": "replan", "ticket_id": "T1", "generation": 1},
}
OK = {"decision": "accepted", "root_cause": "chia T1 thành A/B, không đổi contract", "hint": "A trước B"}


@pytest.fixture
def toan_bo(monkeypatch):
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)


def _client(payload=None, raise_=None) -> FakeClient:
    def h(system, user):
        if raise_ is not None:
            raise raise_
        return payload or {}

    return FakeClient(handler=h)


def _bus(tmp_path, *, actor="delivery-lead", co_impact=True, **over):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    bus.publish(Envelope(topic="change-requests", key=CID, actor=actor, payload={**CR, **over}))
    if co_impact:
        ev = {"change_id": CID, "impact": {"estimate_days": 2, "estimate_tokens": 300000}}
        bus.publish(
            Envelope(
                topic="audit-log",
                key=CID,
                actor="product",
                payload=AuditLog(
                    actor="product", action="change.impact", evidence=json.dumps(ev, ensure_ascii=False)
                ).model_dump(),
            )
        )
    bus.close()
    return db


def _crs(db):
    bus = SQLiteBus(db)
    try:
        return [e for e in bus.replay(topic="change-requests") if e.key == CID]
    finally:
        bus.close()


def test_cr_may_co_impact_thi_tu_dong_quyet_dung_duong_decide_change(toan_bo, tmp_path):
    db = _bus(tmp_path)
    c = _client(OK)
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [(CID, "accepted")]
    last = _crs(db)[-1]
    assert last.actor == ID and last.payload["decision"] == "accepted"
    assert last.payload["impact"]["decided_by"] == ID and "chia T1" in last.payload["impact"]["reason"]
    assert last.payload["impact"]["estimate_tokens"] == 300000, "impact của product gộp vào như `decide-change`"
    assert _cr_accepted_when(False)(last, None), "orchestrator tin quyết định của reviewer ở phạm vi toan-bo"
    assert "REPLAN-T1-1" in c.calls[0]["user"] and "estimate_tokens" in c.calls[0]["user"]
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [] and len(c.calls) == 1, "đã quyết thì không hỏi lại"


def test_cr_hold_ghi_audit_va_khong_hoi_lai(toan_bo, tmp_path, capsys):
    db = _bus(tmp_path)
    c = _client({"decision": "hold", "root_cause": "kế hoạch đổi api-contract", "hint": "phiên chính xem"})
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [(CID, "hold")]
    assert _crs(db)[-1].payload["decision"] == "pending", "giữ = chưa quyết"
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [] and len(c.calls) == 1
    assert gr.main(["--db", str(db), "holds"]) == 0
    assert CID in capsys.readouterr().out, "phiên chính thấy CR bị giữ trong `gate_reviewer holds`"


@pytest.mark.parametrize("out", [{"decision": "approve", "root_cause": "x", "hint": ""}, {"decision": "accepted"}])
def test_cr_dau_ra_hong_thanh_hold(toan_bo, tmp_path, out):
    db = _bus(tmp_path)
    assert gr.run_tick(db, ID, tmp_path / "k.pem", _client(out)) == [(CID, "hold")]


def test_cr_model_loi_thanh_hold(toan_bo, tmp_path):
    db = _bus(tmp_path)
    assert gr.run_tick(db, ID, tmp_path / "k.pem", _client(raise_=LLMError("hết phiên"))) == [(CID, "hold")]


@pytest.mark.parametrize("kw", [{"actor": "human:po"}, {"co_impact": False}, {"impact_kind": "khac"}])
def test_cr_khong_phai_cua_may_hoac_chua_co_impact_thi_khong_dung(toan_bo, tmp_path, kw):
    over = {"impact": {**CR["impact"], "kind": kw.pop("impact_kind")}} if "impact_kind" in kw else {}
    db = _bus(tmp_path, **kw, **over)
    c = _client(OK)
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [] and c.calls == []


def test_cr_ngoai_pham_vi_toan_bo_thi_khong_dung(tmp_path, monkeypatch):
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    db = _bus(tmp_path)
    c = _client(OK)
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [] and c.calls == []


def test_ho_so_cr_neu_cr_khac_cung_du_an_de_nhan_ra_trung(toan_bo, tmp_path):
    db = _bus(tmp_path)
    bus = SQLiteBus(db)
    bus.publish(
        Envelope(
            topic="change-requests",
            key="GATE3-REL-9",
            actor="delivery-lead",
            payload={**CR, "change_id": "GATE3-REL-9", "decision": "accepted", "description": "dashboard"},
        )
    )
    for ev in ("không phải json", json.dumps({"key": CID, "decision": "kho phiên là bảng sessions"})):
        bus.publish(
            Envelope(
                topic="audit-log",
                key=CID,
                actor="product",
                payload=AuditLog(actor="product", action="ruling", evidence=ev).model_dump(),
            )
        )
    bus.close()
    c = _client(OK)
    gr.run_tick(db, ID, tmp_path / "k.pem", c)
    user = c.calls[0]["user"]
    assert "GATE3-REL-9" in user and "accepted" in user
    assert "kho phiên là bảng sessions" in user, "ruling của product vào hồ sơ; evidence hỏng thì bỏ qua, không nổ"


def test_impact_product_van_xuoi_vao_ho_so_nguyen_van(toan_bo, tmp_path):
    """Hub thật 2026-10-13: product ghi `change.impact` bằng VĂN XUÔI, không phải JSON — hồ sơ in `{}` và agent duyệt
    giữ REPLAN-DDCSV-21-1 vì "impact product rỗng" dù product đã ước lượng đủ."""
    db = _bus(tmp_path, co_impact=False)
    bus = SQLiteBus(db)
    van = "Đánh giá tác động REPLAN-T1-1: 2 ticket mới, khoảng 1 ngày, DDCSV-24 chờ ticket B."
    bus.publish(
        Envelope(
            topic="audit-log",
            key=CID,
            actor="product",
            payload=AuditLog(actor="product", action="change.impact", evidence=van).model_dump(),
        )
    )
    bus.close()
    c = _client(OK)
    assert gr.run_tick(db, ID, tmp_path / "k.pem", c) == [(CID, "accepted")]
    assert van in c.calls[0]["user"], "impact văn xuôi của product phải vào hồ sơ nguyên văn"


def test_prompt_reviewer_co_muc_change_request_may_nop():
    version, body = gr.load_prompt()
    assert version >= 3, "đổi luật của agent duyệt là đổi prompt — tăng version"
    for tu in ("ADR gốc 0037", "accepted", "rejected", "change request"):
        assert tu in body, f"prompt phải nêu `{tu}`"
