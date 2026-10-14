"""Hồ sơ Gate 3 (gate `release`) nói nguồn review nào đã được chấp nhận ở escalation của chính RC đó.

Đo hub thật 2026-10-14 (QLKH-DD-CSV REL-074): phiên chính approve escalation REL-074 lúc 17:38 — ký miễn ba finding
block của security theo ADR gốc 0036 (CVE không có bản sửa, DPIA chỉ dữ liệu giả) → `release_waived[REL-074] =
{security}`, RC đi tiếp lên Gate 3. Hồ sơ Gate 3 in "review staging security: block" mà không một chữ nào về miễn trừ;
`reviewer:tu-dong` reject và hint đòi chứng minh lại đúng ba finding đã miễn (sidecar trivy, liệt kê CVE, DPIA).
"""

from __future__ import annotations

from company import gate_brief as GB
from company.gates import GateRequest
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _pub, handler
from test_release_escalation_orchestrator import _blocked_release


def _gate3(tmp_path):
    orch = Orchestrator(SQLiteBus(tmp_path / "c.sqlite"), FakeClient(handler=handler))
    rid, _ = _blocked_release(orch)
    orch.gate.decide(rid, "approve", by="human:owner", reason="root_cause: CVE không có bản sửa; ADR gốc 0036")
    orch.run()
    assert orch.lead.release_waived[rid] == {"qa"}
    for src, verdict in (("qa", "fail"), ("security", "pass")):
        _pub(orch.bus, "review-results", rid, src, {"ticket_id": rid, "source": src, "verdict": verdict})
    orch.gate.request(GateRequest(kind="release", subject_id=rid, created_by="delivery-lead", checklist=["tests"]))
    return orch, rid


def test_ho_so_gate3_ghi_nguon_da_chap_nhan_o_escalation_kem_nguoi_ky_va_ly_do(tmp_path):
    orch, rid = _gate3(tmp_path)
    b = GB.build(orch, rid)
    rv = {r["source"]: r for r in b["extra"]["staging_reviews"]}
    assert rv["qa"]["waived"] == {
        "by": "human:owner",
        "reason": "root_cause: CVE không có bản sửa; ADR gốc 0036",
    }
    assert "waived" not in rv["security"], "nguồn không được miễn thì không gắn"
    md = GB.render_md(b)
    assert "review staging qa: fail" in md and "ĐÃ CHẤP NHẬN ở escalation bởi human:owner" in md
    assert "ADR gốc 0036" in md
