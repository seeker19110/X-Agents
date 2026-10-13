"""ADR-0056: SCA (trivy) và quét secret (gitleaks) do ORCHESTRATOR chạy trên máy trực trước release-check của security.

Đo hub thật 2026-10-12/13 (QLKH-DD-CSV REL-021, hai lượt liên tiếp): security chặn vì "không có kết quả quét lỗ hổng
(pip-audit/OSV/Trivy) cho requirements.lock và gói Debian trong image" và "không có kết quả quét secret (gitleaks) trên
toàn bộ lịch sử git" — cùng họ với SBOM (ADR-0046) và DAST (ADR-0047): bằng chứng chỉ máy mới cho được, không đưa thì
security đúng luật chặn mọi RC. Đo tay trên máy trực: trivy fs 0,1 s (16 gói, 3 HIGH), trivy image 1,9 s (421 CVE
Debian), gitleaks 0,7 s (123 commit, 1 phát hiện). Test không cần binary: `which`/`run` tiêm được như `deploy()`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import company.scanners as sc
from company.scanners import secret_evidence, vuln_evidence

FS_JSON = {
    "SchemaVersion": 2,
    "Results": [
        {
            "Target": "requirements.lock",
            "Class": "lang-pkgs",
            "Type": "pip",
            "Packages": [{"Name": "pg8000"}, {"Name": "starlette"}, {"Name": "six"}],
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2025-61385",
                    "PkgName": "pg8000",
                    "InstalledVersion": "1.31.2",
                    "FixedVersion": "1.31.5",
                    "Severity": "HIGH",
                    "Title": "pg8000 ...",
                },
                {
                    "VulnerabilityID": "CVE-2026-48818",
                    "PkgName": "starlette",
                    "InstalledVersion": "0.49.1",
                    "FixedVersion": "1.1.0",
                    "Severity": "HIGH",
                },
                {
                    "VulnerabilityID": "CVE-2026-48710",
                    "PkgName": "starlette",
                    "InstalledVersion": "0.49.1",
                    "FixedVersion": "1.0.1",
                    "Severity": "MEDIUM",
                },
                {"VulnerabilityID": "CVE-2026-1", "PkgName": "six", "InstalledVersion": "1.0", "Severity": "LOW"},
            ],
        }
    ],
}
IMG_JSON = {
    "ArtifactName": "python:3.12.11-slim-bookworm",
    "Metadata": {"OS": {"Family": "debian", "Name": "12.12"}, "RepoDigests": ["python@sha256:" + "5" * 64]},
    "Results": [
        {
            "Target": "python:3.12.11-slim-bookworm (debian 12.12)",
            "Class": "os-pkgs",
            "Type": "debian",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-9",
                    "PkgName": "zlib1g",
                    "Severity": "CRITICAL",
                    "FixedVersion": "1:1.2.13-2",
                },
                {"VulnerabilityID": "CVE-2026-8", "PkgName": "libc6", "Severity": "HIGH"},
                {"VulnerabilityID": "CVE-2026-7", "PkgName": "perl", "Severity": "LOW"},
            ],
        },
        {
            "Target": "Python",
            "Class": "lang-pkgs",
            "Type": "python-pkg",
            "Vulnerabilities": [{"VulnerabilityID": "CVE-2026-6", "PkgName": "pip", "Severity": "MEDIUM"}],
        },
    ],
}
LEAKS = [
    {
        "RuleID": "generic-api-key",
        "File": "tests/authz/test_x.py",
        "Commit": "5654a27deadbeef",
        "StartLine": 12,
        "Secret": "REDACTED",
        "Match": 'api_key = "REDACTED"',
    },
]


class FakeTools:
    """`which` + `run` giả: ghi lại argv, trả JSON dựng sẵn theo lệnh con. Không chạy trivy/gitleaks nào."""

    def __init__(self, *, have=("trivy", "gitleaks"), fs=FS_JSON, img=IMG_JSON, leaks=LEAKS, fail: str = ""):
        self.have, self.fs, self.img, self.leaks, self.fail = set(have), fs, img, leaks, fail
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return f"/usr/local/bin/{name}" if name in self.have else None

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        tool, sub = Path(argv[0]).name, argv[1]
        if sub == "--version":
            out = "Version: 0.75.0\nVulnerability DB:\n" if tool == "trivy" else "gitleaks version 8.30.1\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        if self.fail == sub:
            return subprocess.CompletedProcess(argv, 1, "", "FATAL\tscan error: boom\n")
        if tool == "trivy":
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.fs if sub == "fs" else self.img), "")
        rp = argv[argv.index("--report-path") + 1]
        Path(rp).write_text(json.dumps(self.leaks), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "INF 123 commits scanned.\nWRN leaks found: 1\n")


@pytest.fixture
def tools(monkeypatch):
    t = FakeTools()
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    return t


# ---------- vuln_evidence: trivy fs trên cây RC + trivy image cho từng image của Dockerfile/compose ----------


def test_vuln_evidence_tom_tat_trivy_fs_va_image_theo_muc_do(tmp_path, tools):
    ev = vuln_evidence(
        tmp_path, "abc1234", ["python:3.12.11-slim-bookworm@sha256:" + "5" * 64, "postgres:16.10-bookworm"]
    )
    assert ev["verified_by"] == "orchestrator" and ev["tool"] == "trivy 0.75.0" and ev["sha"] == "abc1234"
    assert ev["by_severity"] == {"HIGH": 2, "MEDIUM": 1, "LOW": 1} and ev["total"] == 4
    t = ev["targets"][0]
    assert t["target"] == "requirements.lock" and t["type"] == "pip" and t["packages"] == 3
    assert t["findings"][0] == {
        "package": "pg8000",
        "version": "1.31.2",
        "id": "CVE-2025-61385",
        "severity": "HIGH",
        "fixed": "1.31.5",
    }
    assert [i["ref"] for i in ev["images"]] == [
        "python:3.12.11-slim-bookworm@sha256:" + "5" * 64,
        "postgres:16.10-bookworm",
    ]
    img = ev["images"][0]
    assert img["os"] == "debian 12.12" and img["digest"] == "python@sha256:" + "5" * 64
    assert (
        img["by_severity"] == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 1}
        and img["total"] == 4
        and img["fixable"] == 1
    )
    # ADR-0056 bổ sung (hub 2026-10-13, REL-022): security chặn vì "RC không có danh sách CVE" của image — chỉ số đếm
    # thì không viết được hồ sơ ngoại lệ hay chọn CVE để vá. Danh sách CRITICAL + HIGH, CRITICAL trước, có bản sửa
    # trước; MEDIUM/LOW vẫn chỉ đếm (421 CVE Debian không đi lên bus).
    assert img["findings"] == [
        {"package": "zlib1g", "version": None, "id": "CVE-2026-9", "severity": "CRITICAL", "fixed": "1:1.2.13-2"},
        {"package": "libc6", "version": None, "id": "CVE-2026-8", "severity": "HIGH", "fixed": None},
    ]
    fs = tools.calls[1]
    assert fs[1:] == [
        "fs",
        "--scanners",
        "vuln",
        "--file-patterns",
        r"pip:requirements\.lock",
        "--format",
        "json",
        "--quiet",
        str(tmp_path),
    ], "requirements.lock của uv pip compile không phải tên trivy tự nhận"
    assert tools.calls[2][1:4] == ["image", "--scanners", "vuln"] and tools.calls[2][-1].startswith("python:")
    assert json.loads(json.dumps(ev)) == ev


def test_vuln_evidence_khong_co_trivy_thi_unverified_noi_cach_cai(tmp_path, monkeypatch):
    t = FakeTools(have=("gitleaks",))
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "s", [])
    assert ev["unverified"] is True and "trivy" in ev["reason"] and "PATH" in ev["reason"] and not t.calls


def test_vuln_evidence_trivy_fs_loi_thi_unverified_kem_stderr(tmp_path, monkeypatch):
    t = FakeTools(fail="fs")
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "s", ["python:3.12"])
    assert ev["unverified"] is True and "boom" in ev["reason"] and ev["tool"] == "trivy 0.75.0"


def test_vuln_evidence_mot_image_loi_khong_lam_hong_ca_bang_chung(tmp_path, monkeypatch):
    t = FakeTools(fail="image")
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "s", ["ghcr.io/x/y:1"])
    assert (
        "unverified" not in ev
        and ev["images"] == []
        and ev["errors"] == [{"image": "ghcr.io/x/y:1", "error": "FATAL\tscan error: boom"}]
    )


def test_vuln_evidence_cat_danh_sach_phat_hien_theo_tran(tmp_path, monkeypatch):
    many = {
        "Results": [
            {
                "Target": "uv.lock",
                "Type": "uv",
                "Packages": [],
                "Vulnerabilities": [
                    {"VulnerabilityID": f"CVE-{i}", "PkgName": "p", "Severity": "LOW"} for i in range(80)
                ],
            }
        ]
    }
    t = FakeTools(fs=many)
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "s", [])
    assert ev["total"] == 80 and len(ev["targets"][0]["findings"]) == sc.MAX_FINDINGS == 50
    assert ev["targets"][0]["total"] == 80, "số đầy đủ vẫn còn, chỉ danh sách bị cắt"


def test_vuln_evidence_timeout_thanh_unverified(tmp_path, monkeypatch):
    def run(argv, **kw):
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "Version: 0.75.0\n", "")
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(sc, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(sc, "run", run)
    ev = vuln_evidence(tmp_path, "s", [])
    assert ev["unverified"] is True and "quá" in ev["reason"] and str(sc.TIMEOUT_S) in ev["reason"]


def test_vuln_evidence_binary_khong_chay_duoc_thanh_unverified(tmp_path, monkeypatch):
    def run(argv, **kw):
        raise PermissionError("Permission denied")

    monkeypatch.setattr(sc, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(sc, "run", run)
    ev = vuln_evidence(tmp_path, "s", [])
    assert ev["unverified"] is True and "không chạy được" in ev["reason"] and "Permission denied" in ev["reason"]
    assert ev["tool"] == "trivy", "`--version` cũng không chạy được thì tên công cụ vẫn ghi"


# ---------- secret_evidence: gitleaks trên TOÀN BỘ lịch sử git của cây RC, không mang secret lên bus ----------


def test_secret_evidence_timeout_thanh_unverified(tmp_path, monkeypatch):
    def run(argv, **kw):
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "gitleaks version 8.30.1\n", "")
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(sc, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(sc, "run", run)
    ev = secret_evidence(tmp_path, "s")
    assert ev["unverified"] is True and "quá" in ev["reason"] and ev["tool"] == "gitleaks 8.30.1"


def test_secret_evidence_gitleaks_quet_lich_su_git_va_chi_mang_vi_tri(tmp_path, tools):
    ev = secret_evidence(tmp_path, "abc1234")
    assert ev["verified_by"] == "orchestrator" and ev["tool"] == "gitleaks 8.30.1" and ev["sha"] == "abc1234"
    assert ev["commits_scanned"] == 123 and ev["total"] == 1
    assert ev["findings"] == [
        {"rule": "generic-api-key", "file": "tests/authz/test_x.py", "commit": "5654a27", "line": 12}
    ]
    assert "REDACTED" not in json.dumps(ev), "giá trị secret (kể cả đã che) không lên bus"
    argv = tools.calls[-1]
    assert argv[1:4] == ["git", "--no-banner", "--redact=100"] and "--exit-code" in argv and argv[-1] == str(tmp_path)
    assert argv[argv.index("--exit-code") + 1] == "0", "có phát hiện không phải lỗi chạy: chính sách là của security"


def test_secret_evidence_khong_co_gitleaks_thi_unverified(tmp_path, monkeypatch):
    t = FakeTools(have=("trivy",))
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = secret_evidence(tmp_path, "s")
    assert ev["unverified"] is True and "gitleaks" in ev["reason"] and not t.calls


def test_secret_evidence_gitleaks_loi_thi_unverified(tmp_path, monkeypatch):
    t = FakeTools(fail="git")
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = secret_evidence(tmp_path, "s")
    assert ev["unverified"] is True and "boom" in ev["reason"]


def test_secret_evidence_khong_co_bao_cao_la_khong_phat_hien(tmp_path, monkeypatch):
    def run(argv, **kw):
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "8.30.1\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "INF 7 commits scanned.\nINF no leaks found\n")

    monkeypatch.setattr(sc, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(sc, "run", run)
    ev = secret_evidence(tmp_path, "s")
    assert ev["findings"] == [] and ev["total"] == 0 and ev["commits_scanned"] == 7


# ---------- orchestrator: cả hai đi cùng supply_chain + dast trước release-check, model tự khai thì bị bỏ ----------


def test_release_check_mang_vuln_va_secrets_cua_may(tmp_path, monkeypatch, tools):
    from test_dast import _audits, _orch_rc, _sec
    from test_orchestrator import _agent_of, _inp, handler

    seen: list[dict] = []

    def h(system, user):
        out = handler(system, user)
        if _agent_of(system) == "security" and _inp(user).get("release_id"):
            seen.append(_inp(user))
            out = {**out, "evidence": {"vuln": {"total": 0, "verified_by": "security"}, "secrets": {"total": 0}}}
        return out

    bus, orch = _orch_rc(tmp_path, monkeypatch, h)
    (orch.repo / "Dockerfile").write_text("FROM python:3.12-slim@sha256:" + "a" * 64 + "\n", encoding="utf-8")
    import subprocess as sp

    sp.run(["git", "-C", str(orch.repo), "add", "-A"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", str(orch.repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "img"],
        check=True,
        capture_output=True,
    )
    orch.run()
    ev = _sec(bus)["evidence"]
    assert seen[-1]["evidence"]["vuln"]["by_severity"] == {"HIGH": 2, "MEDIUM": 1, "LOW": 1}, (
        "security nhìn thấy số máy đo"
    )
    assert (
        ev["vuln"]["tool"] == "trivy 0.75.0" and ev["vuln"]["images"][0]["ref"] == "python:3.12-slim@sha256:" + "a" * 64
    )
    assert ev["secrets"]["total"] == 1 and ev["secrets"]["findings"][0]["rule"] == "generic-api-key"
    assert ev["supply_chain"]["verified_by"] == "orchestrator" and ev["dast"], "cặp cũ vẫn nguyên"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "vuln.claimed_ignored" in acts and "secrets.claimed_ignored" in acts
    assert "targets" not in _audits(bus, "vuln.run")[-1] and "findings" not in _audits(bus, "secrets.run")[-1]
    assert all("findings" not in i for i in _audits(bus, "vuln.run")[-1]["images"]), "audit chỉ đếm, danh sách ở review"
    assert ev["vuln"]["images"][0]["findings"], "review-results vẫn mang danh sách CVE của image"
    assert _audits(bus, "vuln.run")[-1]["by_severity"]["HIGH"] == 2


def test_khong_co_repo_thi_vuln_va_secrets_unverified(tmp_path):
    from test_supply_chain import _orch, _security

    bus, orch = _orch(tmp_path, None)
    orch.run()
    ev = _security(bus)[-1]["evidence"]
    assert (
        ev["vuln"]["unverified"] is True and ev["secrets"]["unverified"] is True and "worktree" in ev["vuln"]["reason"]
    )


def test_vuln_evidence_image_findings_critical_truoc_co_ban_sua_truoc_va_co_tran(tmp_path, monkeypatch):
    vulns = [{"VulnerabilityID": f"H-{i}", "PkgName": "p", "Severity": "HIGH"} for i in range(60)]
    vulns += [
        {"VulnerabilityID": "H-fix", "PkgName": "q", "Severity": "HIGH", "FixedVersion": "2"},
        {"VulnerabilityID": "C-1", "PkgName": "r", "Severity": "CRITICAL"},
        {"VulnerabilityID": "M-1", "PkgName": "s", "Severity": "MEDIUM", "FixedVersion": "1"},
    ]
    t = FakeTools(img={"Results": [{"Target": "x", "Vulnerabilities": vulns}]})
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    f = vuln_evidence(tmp_path, "s", ["a:1"])["images"][0]["findings"]
    assert [x["id"] for x in f[:2]] == ["C-1", "H-fix"] and len(f) == sc.MAX_FINDINGS
    assert all(x["severity"] in ("CRITICAL", "HIGH") for x in f), "MEDIUM/LOW chỉ đếm"
