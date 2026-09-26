"""ADR-0046: SBOM + license của release-check do orchestrator sinh trên đúng cây RC, không phải lời khai.

Đo được 2026-09-24 và 2026-09-26 (CAMPUS-UNI REL-004, REL-007): security chặn mọi release-check vì
`release-candidates` không kèm SBOM/license — và nó đúng, vì không có đường nào đưa con số tới nó."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from company.events import Envelope, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sandbox import Result, RunSpec, SubprocessSandbox
from company.sqlite_bus import SQLiteBus
from company.supply_chain import components, evidence, installed_licenses, spdx_of
from test_orchestrator import _agent_of, _inp, handler

UV_LOCK = """version = 1
requires-python = ">=3.12"

[[package]]
name = "campus"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "Django"
version = "5.2.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "typing_extensions"
version = "4.16.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "gpl-thing"
version = "1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "chi-windows"
version = "2.0"
source = { registry = "https://pypi.org/simple" }
"""

LICENSES = {
    "django": "BSD-3-Clause",
    "typing-extensions": "Python Software Foundation License",
    "gpl-thing": "GNU General Public License v3 (GPLv3)",
}


class FakeSandbox:
    """Sandbox giả: ghi lại lệnh, trả stdout định sẵn."""

    name = "fake"

    def __init__(self, stdout: str = "", exit_code: int | None = 0, stderr: str = ""):
        self.specs: list[RunSpec] = []
        self.out = Result(exit_code, stdout, stderr, exit_code is None, self.name)

    def run(self, spec: RunSpec) -> Result:
        self.specs.append(spec)
        return self.out


def _root(tmp_path: Path, lock: str | None = UV_LOCK) -> Path:
    root = tmp_path / "rc"
    root.mkdir()
    if lock is not None:
        (root / "uv.lock").write_text(lock, encoding="utf-8")
    return root


# ---------- components: đọc uv.lock, không chạy gì ----------


def test_components_doc_uv_lock_bo_goi_goc(tmp_path):
    c = components(_root(tmp_path))
    assert c is not None
    assert [x["name"] for x in c] == ["django", "typing-extensions", "gpl-thing", "chi-windows"], (
        "gói gốc editable bị bỏ"
    )
    assert c[0] == {"name": "django", "version": "5.2.0", "purl": "pkg:pypi/django@5.2.0"}


def test_components_bo_ca_goi_workspace_virtual(tmp_path):
    lock = UV_LOCK.replace('source = { editable = "." }', 'source = { virtual = "." }')
    assert "campus" not in [x["name"] for x in components(_root(tmp_path, lock)) or []]


def test_components_khong_co_uv_lock_thi_none(tmp_path):
    assert components(_root(tmp_path, None)) is None


# ---------- spdx_of: chuẩn hoá khi không mơ hồ, không đoán ----------


def test_spdx_of_giu_bieu_thuc_spdx_va_map_ten_ro_rang():
    assert spdx_of("BSD-3-Clause AND MIT") == "BSD-3-Clause AND MIT"
    assert spdx_of("Apache-2.0") == "Apache-2.0"
    assert spdx_of("MIT License") == "MIT"
    assert spdx_of("Python Software Foundation License") == "PSF-2.0"
    assert spdx_of("Apache License, Version 2.0") == "Apache-2.0"


def test_spdx_of_mo_ho_thi_noassertion():
    for raw in (
        "",
        "BSD License",
        "BSD",
        "Apache Software License",
        "OSI Approved",
        "GNU General Public License v3 (GPLv3)",
        "Copyright (c) 2020 ai đó, mọi quyền",
    ):
        assert spdx_of(raw) == "NOASSERTION", raw


# ---------- installed_licenses: metadata trong môi trường của khách (ADR-0044) ----------


def test_installed_licenses_chay_uv_run_frozen_trong_sandbox(tmp_path):
    sb = FakeSandbox(json.dumps(LICENSES))
    lic, err = installed_licenses(tmp_path, sb)
    assert lic == LICENSES and err is None
    spec = sb.specs[0]
    assert spec.argv[:6] == ["uv", "run", "--frozen", "--", "python", "-c"] and spec.cwd == tmp_path
    assert spec.max_output > 6000, "dự án vài trăm gói: stdout JSON không được bị cắt"


def test_installed_licenses_loi_thi_tra_ly_do_khong_nem(tmp_path):
    lic, err = installed_licenses(tmp_path, FakeSandbox("", 2, "error: No `project` table found"))
    assert lic == {} and err is not None and "exit_code=2" in err and "project" in err
    lic, err = installed_licenses(tmp_path, FakeSandbox("không phải json"))
    assert lic == {} and err is not None and "JSON" in err


def test_installed_licenses_khong_co_uv_thi_tra_ly_do(tmp_path):
    class Missing(FakeSandbox):
        def run(self, spec: RunSpec) -> Result:
            raise FileNotFoundError("uv")

    lic, err = installed_licenses(tmp_path, Missing())
    assert lic == {} and err is not None and "FileNotFoundError" in err


def test_script_license_that_doc_metadata_cua_venv(tmp_path):
    """Script thật (không giả stdout): chạy bằng Python của test thay cho `uv run -- python`, đọc gói đã cài."""

    class Here:
        name = "here"

        def run(self, spec: RunSpec) -> Result:
            argv = [sys.executable, *spec.argv[5:]]
            return SubprocessSandbox().run(RunSpec(argv=argv, cwd=spec.cwd, max_output=spec.max_output))

    lic, err = installed_licenses(tmp_path, Here())
    assert err is None and "pytest" in lic and spdx_of(lic["pytest"]) == "MIT"
    assert "pydantic" in lic, "tên chuẩn hoá PEP 503"


# ---------- evidence: gộp thành bằng chứng + SBOM CycloneDX ----------


def test_evidence_gop_thanh_phan_license_va_sbom(tmp_path):
    ev = evidence(_root(tmp_path), FakeSandbox(json.dumps(LICENSES)), sha="abc1234")
    assert ev["verified_by"] == "orchestrator" and ev["source"] == "uv.lock" and ev["sha"] == "abc1234"
    assert ev["components"] == 4 and ev["licenses"] == {"BSD-3-Clause": 1, "PSF-2.0": 1, "NOASSERTION": 2}
    assert [x["name"] for x in ev["noassertion"]] == ["gpl-thing", "chi-windows"]
    assert ev["noassertion"][1]["installed"] is False, "có trong lock nhưng không cài trên máy này"
    assert [x["name"] for x in ev["copyleft"]] == ["gpl-thing"] and "GPL" in ev["copyleft"][0]["raw"]
    sbom = ev["sbom"]
    assert sbom["bomFormat"] == "CycloneDX" and sbom["specVersion"] == "1.5" and len(sbom["components"]) == 4
    dj = sbom["components"][0]
    assert dj["purl"] == "pkg:pypi/django@5.2.0" and dj["licenses"] == [{"expression": "BSD-3-Clause"}]
    digest = hashlib.sha256(json.dumps(sbom, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert ev["sbom_ref"] == f"sha256:{digest}", "băm kiểm lại được từ chính SBOM đi kèm"
    assert "licenses_error" not in ev


def test_evidence_license_loi_van_co_thanh_phan(tmp_path):
    ev = evidence(_root(tmp_path), FakeSandbox("", 1, "boom"), sha="s")
    assert ev["components"] == 4 and ev["licenses"] == {"NOASSERTION": 4} and "boom" in ev["licenses_error"]


def test_evidence_khong_co_uv_lock_thi_unverified(tmp_path):
    sb = FakeSandbox()
    ev = evidence(_root(tmp_path, None), sb, sha="s")
    assert ev["unverified"] is True and "uv.lock" in ev["reason"] and ev["verified_by"] == "orchestrator"
    assert sb.specs == [], "không có lock thì không chạy gì trong repo khách"


# ---------- orchestrator: security release-check thấy bằng chứng, lời khai bị bỏ ----------


def _git(repo: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "khach"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "pyproject.toml").write_text("[project]\nname='campus'\nversion='0'\n", encoding="utf-8")
    (repo / "uv.lock").write_text(UV_LOCK, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _orch(tmp_path: Path, repo: Path | None, h=handler):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=h), repo=repo)
    orch.lead.tickets["T1"] = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title="T1",
        acceptance=["a"],
        risk_tags=["auth"],
    )
    orch.lead.state["T1"] = "approved"
    bus.publish(
        Envelope(
            topic="approved-specs",
            key="P",
            actor="product",
            payload={
                "project_id": "P",
                "status": "approved",
                "kind": "library",
                "artifacts": {"prd": "prd", "requirements": "req"},
            },
        )
    )
    bus.publish(
        Envelope(
            topic="release-candidates",
            key="REL-001",
            actor="delivery-lead",
            payload={"release_id": "REL-001", "project_id": "P", "tickets": ["T1"], "version": "0.1.0"},
        )
    )
    return bus, orch


def _security(bus) -> list[dict]:
    return [e.payload for e in bus.replay(topic="review-results") if e.payload.get("source") == "security"]


def _fake_licenses(monkeypatch, lic=LICENSES):
    import company.supply_chain as sc

    roots: list[Path] = []

    def fake(root, sandbox):
        roots.append(root)
        return dict(lic), None

    monkeypatch.setattr(sc, "installed_licenses", fake)
    return roots


def test_security_release_check_thay_va_mang_evidence_supply_chain(tmp_path, monkeypatch):
    seen: list[dict] = []

    def h(system, user):
        if _agent_of(system) == "security":
            seen.append(_inp(user))
        return handler(system, user)

    roots = _fake_licenses(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), h)
    orch.run()
    assert seen and seen[-1]["evidence"]["supply_chain"]["components"] == 4, "security nhìn thấy số máy vừa đo"
    sec = _security(bus)
    assert sec and sec[-1]["ticket_id"] == "REL-001"
    sc_ev = sec[-1]["evidence"]["supply_chain"]
    assert sc_ev["verified_by"] == "orchestrator" and sc_ev["sha"] and sec[-1]["sbom_ref"] == sc_ev["sbom_ref"]
    assert roots and roots[0].name == sc_ev["sha"], "đo trên checkout ĐÚNG sha đã staged, không ở đầu nhánh tích hợp"
    assert "supply_chain.run" in [e.payload["action"] for e in bus.replay(topic="audit-log")]


def test_loi_khai_supply_chain_va_sbom_ref_cua_model_bi_bo(tmp_path, monkeypatch):
    def h(system, user):
        out = handler(system, user)
        if _agent_of(system) == "security" and _inp(user).get("release_id"):
            out = {
                **out,
                "verdict": "block",
                "sbom_ref": "tu-khai",
                "evidence": {"supply_chain": {"components": 999, "verified_by": "security"}, "khac": "giữ"},
            }
        return out

    _fake_licenses(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), h)
    orch.run()
    sec = _security(bus)[-1]
    assert sec["evidence"]["supply_chain"]["components"] == 4 and sec["evidence"]["khac"] == "giữ"
    assert sec["sbom_ref"].startswith("sha256:")
    assert sec["verdict"] == "block", "ADR-0046 §3: máy đưa số, không ghi đè verdict"
    assert "supply_chain.claimed_ignored" in [e.payload["action"] for e in bus.replay(topic="audit-log")]


def test_khong_co_repo_thi_supply_chain_unverified(tmp_path):
    bus, orch = _orch(tmp_path, None)
    orch.run()
    sc_ev = _security(bus)[-1]["evidence"]["supply_chain"]
    assert sc_ev["unverified"] is True and "worktree" in sc_ev["reason"]
    assert _security(bus)[-1].get("sbom_ref") is None


def test_evidence_before_chi_chay_cho_dung_route_cham_release(tmp_path):
    """Route khác (không ra `review-results`, hay `release-events` không có tool đọc) không chạy gì trong repo khách."""
    from company.orch.routes import Route
    from company.orch.verify import evidence_before

    bus, orch = _orch(tmp_path, None)
    ev = Envelope(
        topic="release-events",
        key="REL-001",
        actor="ops",
        payload={"release_id": "REL-001", "env": "staging", "status": "deployed"},
    )
    assert evidence_before(orch, Route("release-events", "qa", "review-results"), ev) == (ev, None)
    rc = bus.latest("release-candidates", "REL-001")
    assert evidence_before(orch, Route("release-candidates", "ops", "release-events"), rc) == (rc, None)


# ---------- ADR-0046 bổ sung: lock file ngoài uv (npm, Cargo, Go) ----------

PACKAGE_LOCK = {
    "name": "web",
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "web", "version": "1.0.0"},
        "node_modules/react": {"version": "18.3.1", "license": "MIT"},
        "node_modules/@babel/core": {"version": "7.25.2", "license": "MIT", "dev": True},
        "node_modules/khong-khai": {"version": "1.0.0"},
        "node_modules/a/node_modules/react": {"version": "18.3.1", "license": "MIT"},
        "node_modules/lien-ket": {"resolved": "packages/lien-ket", "link": True},
        "packages/lien-ket": {"name": "lien-ket", "version": "0.0.1"},
    },
}

CARGO_LOCK = """version = 3

[[package]]
name = "app"
version = "0.1.0"

[[package]]
name = "serde"
version = "1.0.200"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "regex"
version = "1.10.4"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""

CARGO_METADATA = {
    "packages": [
        {"name": "app", "version": "0.1.0", "license": None},
        {"name": "serde", "version": "1.0.200", "license": "MIT OR Apache-2.0"},
        {"name": "regex", "version": "1.10.4", "license": "MIT/Apache-2.0"},
    ]
}

GO_MOD = """module example.com/app

go 1.22

require github.com/gin-gonic/gin v1.10.0

require (
\tgolang.org/x/net v0.25.0 // indirect
\tgithub.com/stretchr/testify v1.9.0
)
"""


def _files(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def test_evidence_npm_doc_license_tu_lock_va_node_modules(tmp_path):
    root = _files(
        _root(tmp_path, None),
        {
            "package-lock.json": json.dumps(PACKAGE_LOCK),
            "node_modules/khong-khai/package.json": json.dumps({"license": {"type": "ISC"}}),
        },
    )
    sb = FakeSandbox()
    ev = evidence(root, sb, sha="s")
    assert sb.specs == [], "npm: license đọc từ lock + node_modules, không chạy gì trong repo khách"
    assert ev["source"] == "package-lock.json" and ev["components"] == 3, "trùng purl gộp; gói gốc, link không tính"
    purls = [c["purl"] for c in ev["sbom"]["components"]]
    assert purls == ["pkg:npm/react@18.3.1", "pkg:npm/%40babel/core@7.25.2", "pkg:npm/khong-khai@1.0.0"]
    assert ev["licenses"] == {"MIT": 2, "ISC": 1} and "licenses_error" not in ev


def test_evidence_npm_lock_v1_khong_doc_duoc_thi_noi_ro(tmp_path):
    root = _files(_root(tmp_path, None), {"package-lock.json": json.dumps({"lockfileVersion": 1, "dependencies": {}})})
    ev = evidence(root, FakeSandbox(), sha="s")
    assert ev["components"] == 0 and "lockfileVersion" in ev["licenses_error"]


def test_evidence_cargo_license_tu_cargo_metadata_trong_sandbox(tmp_path):
    root = _files(_root(tmp_path, None), {"Cargo.lock": CARGO_LOCK})
    sb = FakeSandbox(json.dumps(CARGO_METADATA))
    ev = evidence(root, sb, sha="s")
    assert sb.specs[0].argv[:2] == ["cargo", "metadata"] and "--locked" in sb.specs[0].argv
    assert "--offline" in sb.specs[0].argv, "không kéo mạng trong repo khách"
    assert [c["purl"] for c in ev["sbom"]["components"]] == ["pkg:cargo/serde@1.0.200", "pkg:cargo/regex@1.10.4"]
    assert ev["licenses"] == {"MIT OR Apache-2.0": 2}, "`/` là cú pháp OR cũ của Cargo, có tài liệu — không phải đoán"
    assert ev["source"] == "Cargo.lock" and "licenses_error" not in ev


def test_evidence_cargo_metadata_loi_van_co_thanh_phan(tmp_path):
    root = _files(_root(tmp_path, None), {"Cargo.lock": CARGO_LOCK})
    ev = evidence(root, FakeSandbox("", 101, "error: failed to download"), sha="s")
    assert ev["components"] == 2 and ev["licenses"] == {"NOASSERTION": 2}
    assert ev["licenses_error"].startswith("Cargo.lock:") and "failed to download" in ev["licenses_error"]


def test_evidence_go_mod_co_thanh_phan_license_noassertion_noi_ro_ly_do(tmp_path):
    root = _files(_root(tmp_path, None), {"go.mod": GO_MOD})
    sb = FakeSandbox()
    ev = evidence(root, sb, sha="s")
    assert sb.specs == []
    assert [c["purl"] for c in ev["sbom"]["components"]] == [
        "pkg:golang/github.com/gin-gonic/gin@v1.10.0",
        "pkg:golang/golang.org/x/net@v0.25.0",
        "pkg:golang/github.com/stretchr/testify@v1.9.0",
    ]
    assert ev["licenses"] == {"NOASSERTION": 3} and "LICENSE" in ev["licenses_error"]
    assert all(x["installed"] is None for x in ev["noassertion"])


def test_evidence_gop_nhieu_lock_ca_thu_muc_con_mot_tang(tmp_path):
    root = _files(
        _root(tmp_path),
        {
            "frontend/package-lock.json": json.dumps(PACKAGE_LOCK),
            "node_modules/package-lock.json": json.dumps(PACKAGE_LOCK),
            ".an/go.mod": GO_MOD,
            "a/b/go.mod": GO_MOD,
        },
    )
    ev = evidence(root, FakeSandbox(json.dumps(LICENSES)), sha="s")
    assert ev["source"] == "uv.lock+frontend/package-lock.json", "chỉ gốc + một tầng, bỏ thư mục ẩn"
    assert ev["components"] == 4 + 3
    locks = {x["name"]: x["lock"] for x in ev["noassertion"]}
    assert locks["gpl-thing"] == "uv.lock"


def test_evidence_khong_co_lock_nao_thi_unverified_ke_du_ten(tmp_path):
    ev = evidence(_root(tmp_path, None), FakeSandbox(), sha="s")
    assert ev["unverified"] is True
    assert all(n in ev["reason"] for n in ("uv.lock", "package-lock.json", "Cargo.lock", "go.mod"))
