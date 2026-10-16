"""ADR-0057 bổ sung 2026-10-16: từ chối escalation release chỉ đá về làm lại ticket mà file đã đổi (merge commit
`merge(<tid>):` trên nhánh tích hợp) chạm vị trí file của finding `block`. Không ticket nào chạm → không làm lại ai,
nộp một CR (`kind=release_gate_reject`, đường `tu-dong` đã quyết được) mang lý do từ chối. Không đo được → như cũ.

Hub thật (QLKH-DD-CSV, 2026-10-12 → 16): 44,9M token tiêu cho 58 lượt builder + 23 lượt review làm lại ticket ĐÃ merge
sau release reject; REL-085/087/090/091/096/098 bị chặn bởi một phát hiện gitleaks ở
`tests/security/rel_verify/rel_fixtures.py:24` (commit của DDCSV-95) — mỗi lần reject đá các ticket của RC (không
ticket nào đụng file đó) về làm lại, rồi ADR-0057 §1 mới đổi thành CR.

Hai chiều (luật bắt buộc 4): bỏ phép lọc theo file trong nhánh reject của `gates_flow` → ca 1, 3 đỏ; ca 2 (finding
chạm file của ticket → làm lại như cũ) xanh ở cả hai chiều."""

from __future__ import annotations

from company.events import ReviewResult
from company.gates import GateRequest
from company.workspace import Integration, WorkspaceError
from test_adr0057 import _merged_t1


def _reject_with(orch, rid: str, location: str | None, reason: str = "gỡ phát hiện secret; xem finding"):
    orch.lead.release_reviews[rid]["security"] = ReviewResult(
        ticket_id=rid,
        source="security",
        verdict="block",
        findings=[
            {"level": "block", "text": "gitleaks generic-api-key", "location": location},
            {"level": "warn", "text": "chỉ cảnh báo — không làm ticket nào bị làm lại", "location": "f_t1.py:9"},
        ],
    )
    orch.gate.request(
        GateRequest(
            kind="escalation",
            subject_id=rid,
            created_by="delivery-lead",
            checklist=["root_cause", "decision:reopen|close", "hint"],
        )
    )
    orch.gate.decide(rid, "reject", by="human:owner", reason=reason)
    return orch.run()


def _crs(bus, rid):
    return [e.payload for e in bus.replay(topic="change-requests") if e.key.startswith(f"REWORK-{rid}-")]


def test_finding_o_file_khong_ticket_nao_cua_rc_cham_thi_khong_lam_lai_ma_nop_cr(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    bus, _client, orch, rid = _merged_t1(tmp_path, {"t1": "def t1():\n    return 1\n"})
    res = _reject_with(orch, rid, "mod.py:3")  # mod.py có trong cây tích hợp, T1 chỉ đổi f_t1.py
    assert orch.lead.state["T1"] == "merged" and orch.lead.tickets["T1"].retry == 0, (
        "T1 không đụng mod.py: không làm lại"
    )
    assert not any(a.startswith("release_reworked") for r in res for a in r.actions)
    crs = _crs(bus, rid)
    assert len(crs) == 1 and crs[0]["impact"]["kind"] == "release_gate_reject" and crs[0]["decision"] == "pending"
    assert "gỡ phát hiện secret" in crs[0]["description"] and crs[0]["impact"]["release_id"] == rid
    out = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.rework_outside"]
    assert out and '"mod.py"' in out[-1]["evidence"]


def test_finding_cham_file_cua_ticket_thi_lam_lai_nhu_cu(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    bus, _client, orch, rid = _merged_t1(tmp_path, {"t1": "def t1():\n    return 1\n"})
    res = _reject_with(orch, rid, "f_t1.py:1", reason="sửa t1 cho đúng")
    assert orch.lead.tickets["T1"].retry == 1 and any(a == f"release_reworked:{rid}" for r in res for a in r.actions)
    assert _crs(bus, rid) == []


def test_finding_khong_co_vi_tri_file_thi_khong_doan_ticket_ma_nop_cr(tmp_path, monkeypatch):
    """Image nền, DPIA, CVE OS: không ticket nào sở hữu — đá ticket về chỉ ra một lượt builder không đổi gì (ADR-0057 §1)."""
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    bus, _client, orch, rid = _merged_t1(tmp_path, {"t1": "def t1():\n    return 1\n"})
    _reject_with(orch, rid, None)
    assert orch.lead.tickets["T1"].retry == 0 and len(_crs(bus, rid)) == 1


def test_git_loi_khi_do_thi_giu_hanh_vi_cu(tmp_path, monkeypatch):
    def _hong(self, tid):
        raise WorkspaceError("git hỏng")

    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    _bus, _client, orch, rid = _merged_t1(tmp_path, {"t1": "def t1():\n    return 1\n"})
    monkeypatch.setattr(Integration, "ticket_files", _hong)
    res = _reject_with(orch, rid, "mod.py:3")
    assert orch.lead.tickets["T1"].retry == 1 and any(a == f"release_reworked:{rid}" for r in res for a in r.actions)


def test_ticket_khong_tim_thay_merge_commit_thi_coi_nhu_cham(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    bus, _client, orch, rid = _merged_t1(tmp_path, {"t1": "def t1():\n    return 1\n"})
    monkeypatch.setattr(Integration, "ticket_files", lambda self, tid: set())
    _reject_with(orch, rid, "mod.py:3")
    assert orch.lead.tickets["T1"].retry == 1 and _crs(bus, rid) == [], "không biết ticket đổi gì → làm lại như cũ"
