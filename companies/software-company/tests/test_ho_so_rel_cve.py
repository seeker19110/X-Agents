"""Hồ sơ escalation `REL-*` mang số đo lỗ hổng của máy (ADR-0056 bổ sung 2026-10-14, ADR gốc 0036).

Đo hub thật 2026-10-14 (QLKH-DD-CSV REL-074): sau #506 security thấy image db dẫn xuất, ba finding block còn lại đều
thuộc diện ký miễn của ADR gốc 0036 (CVE không có bản sửa, DPIA chỉ dữ liệu giả). `reviewer:tu-dong` vẫn GIỮ: "đoạn
này bị cắt giữa chừng ('CVE-2026-74860, 861…') và hồ sơ không kèm evidence.vuln, nên không đối chiếu được rằng mọi CVE
CRITICAL/HIGH đều có fixed rỗng, và không liệt kê đủ mã CVE". Hai lỗ: hồ sơ chỉ chép câu chữ (cắt) của finding, và
`images[].findings` có trần 50 trong khi image db có 62 CRITICAL/HIGH — kể cả đọc được evidence cũng không đủ.
"""

from __future__ import annotations

from company import gate_brief as GB
from company.scanners import _image_summary

ID_DB = "sha256:" + "24" * 32


def _vuln(i: int, sev: str = "HIGH", fixed: str | None = None) -> dict:
    return {"VulnerabilityID": f"CVE-2026-{i:05d}", "PkgName": "p", "Severity": sev, "FixedVersion": fixed}


def test_image_summary_dem_ca_h_co_ban_sua_va_ma_cve_tren_toan_bo_khong_theo_tran():
    vulns = [_vuln(i) for i in range(60)] + [_vuln(1, "HIGH")] + [_vuln(99, "CRITICAL", "1.2")] + [_vuln(7, "LOW", "2")]
    s = _image_summary(ID_DB, {"Results": [{"Vulnerabilities": vulns}]})
    assert len(s["findings"]) == 50, "danh sách chi tiết vẫn có trần"
    assert s["serious_fixable"] == 1, "đếm CRITICAL/HIGH có bản sửa trên TOÀN BỘ, không chỉ 50 dòng đầu"
    assert s["serious_ids"] == sorted({f"CVE-2026-{i:05d}" for i in [*range(60), 99]}), "mã duy nhất, đủ, có thứ tự"
    assert s["fixable"] == 2, "fixable cũ vẫn đếm mọi mức độ"


def _rel_orch(tmp_path):
    from test_orchestrator import _pub
    from test_smoke_evidence import SERVER_DIE, _orch, _repo

    repo = _repo(tmp_path, SERVER_DIE)
    _, orch = _orch(tmp_path, repo, {"command": "python serve.py", "port": 0, "timeout_s": 10})
    orch.run()
    assert orch.gate.pending["REL-001"].kind == "escalation"
    return orch, _pub


def test_ho_so_escalation_release_in_lo_hong_cua_may_tu_review_security(tmp_path):
    orch, pub = _rel_orch(tmp_path)
    vuln = {
        "verified_by": "orchestrator",
        "tool": "trivy 0.75.0",
        "sha": "0f6637f",
        "targets": [{"target": "requirements.lock", "by_severity": {}, "total": 0, "findings": []}],
        "images": [
            {
                "ref": "python:3.12-slim",
                "by_severity": {"HIGH": 44},
                "fixable": 8,
                "serious_fixable": 0,
                "serious_ids": ["CVE-2026-9538"],
                "findings": [],
            },
            {
                "ref": ID_DB,
                "service": "db",
                "deployed": True,
                "image_id": ID_DB,
                "by_severity": {"CRITICAL": 1, "HIGH": 61},
                "fixable": 0,
                "serious_fixable": 0,
                "serious_ids": ["CVE-2026-6653", "CVE-2026-74860"],
                "findings": [],
            },
            "hỏng hình",
        ],
        "errors": [{"image": "sha256:dead", "error": "boom"}],
    }
    pub(
        orch.bus,
        "review-results",
        "REL-001",
        "security",
        {
            "ticket_id": "REL-001",
            "source": "security",
            "verdict": "block",
            "root_cause": "x",
            "evidence": {"vuln": vuln},
        },
    )
    b = GB.build(orch, "REL-001")
    v = b["extra"]["vuln"]
    assert v["tool"] == "trivy 0.75.0" and v["sha"] == "0f6637f"
    db = next(i for i in v["items"] if i.get("service") == "db")
    assert db["serious_fixable"] == 0 and db["serious_ids"] == ["CVE-2026-6653", "CVE-2026-74860"] and db["complete"]
    md = GB.render_md(b)
    assert "## Lỗ hổng" in md and "CVE-2026-74860" in md and "db (deployed)" in md
    assert "CRITICAL/HIGH có bản sửa: 0" in md
    assert len(v["items"]) == 3 and "lỗi quét `sha256:dead`: boom" in md, "mục hỏng hình bỏ qua, lỗi quét vẫn hiện"


def test_ho_so_evidence_cu_khong_co_ma_day_du_thi_lay_tu_findings_va_noi_ro_co_tran(tmp_path):
    orch, pub = _rel_orch(tmp_path)
    vuln = {
        "verified_by": "orchestrator",
        "tool": "trivy",
        "sha": "s",
        "targets": [],
        "errors": [],
        "images": [
            {
                "ref": "postgres:16",
                "by_severity": {"HIGH": 2},
                "fixable": 1,
                "findings": [
                    {"id": "CVE-1", "severity": "HIGH", "fixed": "2"},
                    {"id": "CVE-2", "severity": "HIGH", "fixed": None},
                ],
            }
        ],
    }
    pub(
        orch.bus,
        "review-results",
        "REL-001",
        "security",
        {"ticket_id": "REL-001", "source": "security", "verdict": "block", "evidence": {"vuln": vuln}},
    )
    it = GB.build(orch, "REL-001")["extra"]["vuln"]["items"][0]
    assert it["serious_ids"] == ["CVE-1", "CVE-2"] and it["serious_fixable"] == 1 and it["complete"] is False
    assert "danh sách có trần" in GB.render_md(GB.build(orch, "REL-001"))


def test_ho_so_vuln_unverified_hoac_khong_co_review_security(tmp_path):
    orch, pub = _rel_orch(tmp_path)
    assert "vuln" not in GB.build(orch, "REL-001")["extra"], "chưa có review security thì không bịa mục"
    pub(
        orch.bus,
        "review-results",
        "REL-001",
        "security",
        {
            "ticket_id": "REL-001",
            "source": "security",
            "verdict": "block",
            "evidence": {"vuln": {"unverified": True, "reason": "không có trivy"}},
        },
    )
    b = GB.build(orch, "REL-001")
    assert b["extra"]["vuln"] == {"unverified": "không có trivy"} and "không có trivy" in GB.render_md(b)
