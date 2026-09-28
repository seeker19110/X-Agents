"""decide(): đi qua HumanGate thật của software-company (four-eyes, allowlist, audit-log)."""
from __future__ import annotations

from pathlib import Path

import pytest
from company.gate_cli import PersistentGate as CompanyGate
from company.gates import APPROVERS_ENV as COMPANY_APPROVERS_ENV
from company.sqlite_bus import SQLiteBus as CompanySQLiteBus

from console.collect import COMPANY, collect
from console.decide import GateError, decide

DEAD_GATEWAY = "http://127.0.0.1:9"


def test_duyet_gate_that(company_db: Path) -> None:
    out = decide(company_db, subject_id="REL-001", xuong=COMPANY, decision="approve",
                 by="human:pm", reason="ok")
    assert out["ok"] is True and out["subject_id"] == "REL-001" and out["decision"] == "approve"
    assert out["event_id"]
    # quyết định nằm trong bus của công ty và gate không còn chờ
    bus = CompanySQLiteBus(company_db)
    try:
        gate = CompanyGate(bus)
        assert "REL-001" not in gate.pending and gate.is_approved("REL-001")
        assert any(e.event_id == out["event_id"] and e.payload["action"] == "gate.decide"
                   for e in bus.replay(topic="audit-log"))
    finally:
        bus.close()
    assert "REL-001" not in {g["id"] for g in collect(company_db, gateway_url=DEAD_GATEWAY)["gates"]}


def test_four_eyes_chan_nguoi_tao(company_db: Path) -> None:
    """Gate do NGƯỜI mở (`gate_cli request --by human:…`): từ F-A (audit 2026-09-27) `by` không hình người bị chặn
    trước khi tới four-eyes, nên tên agent đã tạo gate (`delivery-lead`) không còn thử được chốt này."""
    from company.gates import GateRequest
    bus = CompanySQLiteBus(company_db)
    try:
        CompanyGate(bus).request(GateRequest(kind="release", subject_id="REL-002", checklist=["tests"],
                                             created_by="human:lead"))
    finally:
        bus.close()
    with pytest.raises(GateError) as e:
        decide(company_db, subject_id="REL-002", xuong=COMPANY, decision="approve",
               by="human:lead", reason="tự duyệt")
    assert "four-eyes" in str(e.value)
    assert "REL-002" in {g["id"] for g in collect(company_db, gateway_url=DEAD_GATEWAY)["gates"]}


def test_allowlist_nguoi_duyet_cua_cong_ty_gia_cong(company_db: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """K3.7: `COMPANY_GATE_APPROVERS` phải áp trên đường console giống hệt CLI/orchestrator — trước bản vá này
    console mở `PersistentGate(bus)` không truyền `approvers`, nên allowlist bị bỏ qua trên riêng đường này."""
    monkeypatch.setenv(COMPANY_APPROVERS_ENV, "human:cto")
    with pytest.raises(GateError) as e:
        decide(company_db, subject_id="REL-001", xuong=COMPANY, decision="approve",
               by="human:intern", reason="")
    assert "danh sách người duyệt" in str(e.value)
    out = decide(company_db, subject_id="REL-001", xuong=COMPANY, decision="approve",
                 by="human:cto", reason="ok")
    assert out["ok"] and out["event_id"]


@pytest.mark.parametrize("by", ["reviewer:x", "orchestrator", "owner"])
def test_by_khong_phai_nguoi_bi_tu_choi_truoc_khi_ghi(company_db: Path, by: str) -> None:
    """Ô "Bạn là" của console là chữ tự do (`drawer.js`). Trước bản vá (audit 2026-09-27, F-A): `reviewer:x` và
    `orchestrator` trả `ok` kèm `event_id` nhưng mọi tiến trình khác bỏ bản ghi (`_trusted` → None) nên gate vẫn
    chờ; `owner` (quên tiền tố) nổ `PermissionDenied` của ACL bus — không phải `PermissionError` — nên server trả
    500 "lỗi không lường trước"."""
    with pytest.raises(ValueError, match="không phải người"):
        decide(company_db, subject_id="REL-001", xuong=COMPANY, decision="approve", by=by, reason="ok")
    assert "REL-001" in {g["id"] for g in collect(company_db, gateway_url=DEAD_GATEWAY)["gates"]}
    bus = CompanySQLiteBus(company_db)
    try:
        assert not [e for e in bus.replay(topic="audit-log")
                    if e.payload.get("action") == "gate.decide" and "REL-001" in (e.payload.get("evidence") or "")]
    finally:
        bus.close()


def test_subject_khong_co_gate_cho(company_db: Path) -> None:
    with pytest.raises(GateError) as e:
        decide(company_db, subject_id="TCK-999", xuong=COMPANY, decision="approve", by="human:pm", reason="")
    assert "không có gate chờ" in str(e.value)


def test_xuong_la(company_db: Path) -> None:
    with pytest.raises(ValueError, match="xưởng lạ"):
        decide(company_db, subject_id="REL-001", xuong="phòng-marketing", decision="approve",
               by="human:pm", reason="")


def test_verb_quyet_dinh_la(company_db: Path) -> None:
    for verb in ("merge", "pending", ""):
        with pytest.raises(ValueError, match="quyết định lạ"):
            decide(company_db, subject_id="REL-001", xuong=COMPANY, decision=verb, by="human:pm", reason="")


def test_thieu_db(tmp_path: Path) -> None:
    with pytest.raises(GateError, match="chưa có file DB"):
        decide(tmp_path / "khong-co.sqlite", subject_id="REL-001", xuong=COMPANY, decision="approve",
               by="human:pm", reason="")
    with pytest.raises(GateError, match="chưa có file DB"):
        decide(None, subject_id="REL-001", xuong=COMPANY, decision="approve", by="human:pm", reason="")


def test_thieu_nguoi_duyet(company_db: Path) -> None:
    with pytest.raises(ValueError, match="người duyệt"):
        decide(company_db, subject_id="REL-001", xuong=COMPANY, decision="approve", by="  ", reason="")
    with pytest.raises(ValueError, match="subject_id"):
        decide(company_db, subject_id="", xuong=COMPANY, decision="approve", by="human:pm", reason="")


def _spec_gate(db: Path, *, pinned: bool) -> None:
    """Gate SPEC-P9 đang chờ; `pinned` ⇒ dự án đã có quality profile người ghim (ADR gốc 0021, quyết định 2)."""
    from company.gates import GateRequest
    from company.quality_floor import PROFILE_ACTION
    bus = CompanySQLiteBus(db)
    try:
        gate = CompanyGate(bus)
        gate.request(GateRequest(kind="spec", subject_id="SPEC-P9", created_by="product", checklist=["prd"]))
        if pinned:
            gate._log("human:po", PROFILE_ACTION, {"project_id": "P9", "run_id": "run-P9",
                                                   "profile_sha256": "a" * 64, "contract_hash": "b", "by": "human:po"},
                      by="human:po")
    finally:
        bus.close()


def test_duyet_spec_du_an_da_co_profile_bi_tu_choi_huong_sang_cli(company_db: Path) -> None:
    _spec_gate(company_db, pinned=True)
    with pytest.raises(GateError) as e:
        decide(company_db, subject_id="SPEC-P9", xuong=COMPANY, decision="approve", by="human:pm", reason="ok")
    assert "gate_cli approve SPEC-P9 --quality-profile" in str(e.value)
    assert "SPEC-P9" in {g["id"] for g in collect(company_db, gateway_url=DEAD_GATEWAY)["gates"]}, "chưa ký"
    out = decide(company_db, subject_id="SPEC-P9", xuong=COMPANY, decision="request_changes", by="human:pm",
                 reason="thiếu mục tiêu đo được")
    assert out["ok"], "chỉ lần KÝ spec cần profile"


def test_duyet_spec_du_an_chua_tung_co_profile_giu_hanh_vi_cu(company_db: Path) -> None:
    _spec_gate(company_db, pinned=False)
    out = decide(company_db, subject_id="SPEC-P9", xuong=COMPANY, decision="approve", by="human:pm", reason="ok")
    assert out["ok"]
