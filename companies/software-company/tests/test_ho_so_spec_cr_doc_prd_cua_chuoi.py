"""Hồ sơ gate `SPEC-<mã CR>` đối chiếu PRD do CHÍNH chuỗi CR đó viết, không phải bản `prd` mới nhất của dự án.

Hub thật 2026-10-15 (QLKH-DD-CSV): CR-DDCSV-DPIA-001 viết PRD v5.1 (blackboard prd v9) lúc 06:59, rồi CR-DDCSV-SEC-006
viết PRD v6 (prd v10) lúc 09:37; hai gate spec mở cùng lúc. Hồ sơ của SPEC-CR-DDCSV-DPIA-001 đọc `prd` mới nhất — PRD
của SEC6 — nên mục NFR, ngoài phạm vi, PII đều nói về CR khác, và `reviewer:tu-dong` giữ gate vì "hồ sơ chưa trỏ
đúng PRD". #499 đã đưa runtime và câu hỏi về theo chuỗi; PRD thì chưa.
"""

from __future__ import annotations

from company import gate_brief as GB
from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _drive_to_plan, _pub, handler

PRD_A = "# PRD CR-A\n\n## NFR\n- xuất CSV ≤ 5 s p95\n\n## Ngoài phạm vi\n- không làm A1\n- không làm A2\n"
PRD_B = "# PRD CR-B\n\n## NFR\n- không có số đo\n\n## Ngoài phạm vi\n- không làm B1\n"


def _spec_cr(bus, orch, key, prd):
    base = dict(bus.latest("approved-specs", "P1").payload)
    _pub(bus, "approved-specs", key, "product", {**base, "change_id": key, "status": "pending_human"})
    orch.blackboard.write("product", "prd", f"prd/P1/change/{key}", summary=f"PRD {key}", content=prd, project_id="P1")


def _muc(b, mid):
    return next(x for x in b["self_check"] if x["id"] == mid)


def _hai_cr():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    _spec_cr(bus, orch, "CR-A", PRD_A)
    _spec_cr(bus, orch, "CR-B", PRD_B)
    orch.run()
    return bus, orch


def test_ho_so_spec_cr_doc_prd_cua_chinh_chuoi_khong_phai_ban_moi_nhat():
    _bus, orch = _hai_cr()
    b = GB.build(orch, "SPEC-CR-A")
    nfr = _muc(b, "spec.nfr-co-so-do")
    assert nfr["verdict"] == "ok" and "5 s" in " ".join(nfr["facts"]), "NFR của CR-A, không phải của CR-B"
    assert nfr["sources"][0]["content_ref"] == "prd/P1/change/CR-A"
    oos = _muc(b, "spec.out-of-scope")
    assert "2 mục" in oos["facts"][0]


def test_chuoi_cr_moi_nhat_van_doc_ban_moi_nhat():
    _bus, orch = _hai_cr()
    nfr = _muc(GB.build(orch, "SPEC-CR-B"), "spec.nfr-co-so-do")
    assert nfr["verdict"] == "gap" and nfr["sources"][0]["content_ref"] == "prd/P1/change/CR-B"


def test_chuoi_cr_khong_tu_viet_prd_thi_doc_ban_hien_hanh_luc_spec_ra():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch)
    orch.blackboard.write("product", "prd", "prd/P1/v-goc", summary="PRD gốc", content=PRD_A, project_id="P1")
    base = dict(bus.latest("approved-specs", "P1").payload)
    _pub(bus, "approved-specs", "CR-C", "product", {**base, "change_id": "CR-C", "status": "pending_human"})
    _spec_cr(bus, orch, "CR-B", PRD_B)
    orch.run()
    nfr = _muc(GB.build(orch, "SPEC-CR-C"), "spec.nfr-co-so-do")
    assert nfr["sources"][0]["content_ref"] == "prd/P1/v-goc", "bản prd hiện hành lúc spec CR-C ra, không phải của CR-B"


def test_spec_du_an_van_doc_prd_moi_nhat():
    _bus, orch = _hai_cr()
    nfr = _muc(GB.build(orch, "SPEC-P1", closed=True), "spec.nfr-co-so-do")
    assert nfr["sources"][0]["content_ref"] == "prd/P1/change/CR-B"


def _mo_gate(orch, sid):
    from company.gates import GateRequest

    orch.gate.request(GateRequest(kind="spec", subject_id=sid, created_by="product", checklist=["prd"]))


def test_chuoi_chua_co_spec_thi_doc_prd_moi_nhat_cua_du_an():
    _bus, orch = _hai_cr()
    _prd, src = GB._prd_of(orch, "P1", "CR-X")
    assert src is not None and src["content_ref"] == "prd/P1/change/CR-B", "không có spec của chuỗi: như cũ"


def test_chuoi_cr_ma_du_an_chua_co_prd_nao_thi_unknown():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    _pub(
        bus,
        "approved-specs",
        "CR-Z",
        "product",
        {"project_id": "P9", "change_id": "CR-Z", "kind": "library", "artifacts": {"prd": "-", "requirements": "-"}, "status": "pending_human"},
    )
    _mo_gate(orch, "SPEC-CR-Z")
    nfr = _muc(GB.build(orch, "SPEC-CR-Z"), "spec.nfr-co-so-do")
    assert nfr["verdict"] == "unknown" and not nfr["sources"]
