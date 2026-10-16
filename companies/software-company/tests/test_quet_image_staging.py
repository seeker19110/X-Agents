"""ADR-0056 bổ sung 2026-10-14: release-check quét image ĐÃ DỰNG mà staging đang chạy, không chỉ image nền.

Đo hub thật 2026-10-14 (QLKH-DD-CSV REL-068 → REL-072): repo khách đổi service db từ `image: postgres:…` sang
`build: infra/db/Dockerfile` (image dẫn xuất gỡ gosu, CVE-2025-68121). `evidence.vuln.images` chỉ còn image nền của
app (`python:3.12.15-slim-trixie`): `infra/db/Dockerfile` sâu hai cấp nên ngoài `image_digest.DOCKERFILES`, và quét
image nền `postgres:16.15-trixie` cũng chỉ thấy lại gosu mà Dockerfile đã gỡ. Security chặn đúng luật "RC không có
bằng chứng về image db dẫn xuất" — mọi RC, kể cả khi sản phẩm đã đạt. Đo tay trên máy trực: `trivy image
sha256:c5aabbe2…` (image id của container db staging) — 0 CVE-2025-68121, 1 CRITICAL + 61 HIGH, 0 có bản sửa.
"""

from __future__ import annotations

import json

import company.scanners as sc
from company.scanners import vuln_evidence
from test_deploy_compose import _deploy, _probe_tra
from test_scanners import IMG_JSON, FakeTools

ID_DB = "sha256:" + "c5" * 32
ID_APP = "sha256:" + "47" * 32
PS_HAI = json.dumps(
    [
        {
            "Service": "app",
            "ID": "26ea6bb755ac0000",
            "State": "running",
            "Image": "company-p1-staging-app",
            "Labels": f"com.docker.compose.project=company-p1-staging,com.docker.compose.image={ID_APP},"
            "com.docker.compose.service=app",
            "Publishers": [{"PublishedPort": 8080, "TargetPort": 8080}],
        },
        {
            "Service": "db",
            "ID": "a69d4a090eb30000",
            "State": "running",
            "Image": "company-p1-staging-db",
            "Labels": f"com.docker.compose.image={ID_DB},com.docker.compose.service=db",
            "Publishers": [],
        },
    ]
)


def test_deploy_compose_ghi_image_id_cua_tung_service_tu_nhan_compose(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    r, _ = _deploy(tmp_path, ps=(0, PS_HAI, ""))
    assert r.ok is True and r.services == ("app", "db")
    assert r.image_ids == (ID_APP, ID_DB), "image id là của container đang chạy, đọc từ nhãn compose — máy sinh"
    assert r.record()["image_ids"] == [ID_APP, ID_DB]


def test_deploy_compose_thieu_nhan_image_thi_chuoi_rong_giu_dung_vi_tri(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    rows = json.loads(PS_HAI)
    rows[0]["Labels"] = "com.docker.compose.service=app"
    r, _ = _deploy(tmp_path, ps=(0, json.dumps(rows), ""))
    assert r.image_ids == ("", ID_DB), "thẳng hàng với `services`, không đoán image cho service thiếu nhãn"


def test_vuln_evidence_quet_image_dang_chay_theo_id_kem_service(tmp_path, monkeypatch):
    t = FakeTools()
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "0f6637f", ["python:3.12-slim"], deployed=[("app", ID_APP), ("db", ID_DB), ("x", "")])
    assert [i["ref"] for i in ev["images"]] == ["python:3.12-slim", ID_APP, ID_DB], "service thiếu id thì bỏ"
    base, app, db = ev["images"]
    assert "service" not in base and "deployed" not in base, "image nền giữ nguyên hình cũ"
    assert app["service"] == "app" and app["image_id"] == ID_APP
    assert db["service"] == "db" and db["deployed"] is True and db["image_id"] == ID_DB
    assert db["by_severity"] == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 1} and db["findings"]
    assert [c[-1] for c in t.calls if c[1] == "image"] == ["python:3.12-slim", ID_APP, ID_DB], "quét theo ID, không tên"


def test_vuln_evidence_image_dang_chay_trung_id_chi_quet_mot_lan(tmp_path, monkeypatch):
    t = FakeTools(img={**IMG_JSON})
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "s", [], deployed=[("db", ID_DB), ("migrate", ID_DB)])
    assert [i["service"] for i in ev["images"]] == ["db,migrate"] and len([c for c in t.calls if c[1] == "image"]) == 1


def test_release_check_quet_image_cua_staging_da_deploy(tmp_path, monkeypatch):
    """Dây: ops dựng staging TRƯỚC security trong cùng lượt RC; `evidence_before` lấy `image_ids` của
    `evidence.deploy` staging đưa cho `vuln_evidence` — cùng RC, cùng container mà DAST đã quét."""
    from company.events import Task
    from test_dast import _sec
    from test_deploy_release_fsm import RUNTIME, _fake_deploy, _orch, _repo
    from test_supply_chain import _fake_licenses

    _fake_licenses(monkeypatch)
    t = FakeTools()
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    fn, _ = _fake_deploy(monkeypatch, ps=(0, PS_HAI, ""))
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime={**RUNTIME, "deploy": "compose.yaml"})
    orch.lead.tickets["T1"] = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title="T1",
        acceptance=["a"],
        risk_tags=["auth"],
    )
    orch.run()
    imgs = _sec(bus)["evidence"]["vuln"]["images"]
    assert [(i.get("service"), i["ref"]) for i in imgs if i.get("deployed")] == [("app", ID_APP), ("db", ID_DB)]


def test_release_check_bo_image_nen_cua_image_da_dung_dang_chay(tmp_path, monkeypatch):
    """Bổ sung 2026-10-16 (REL-107): staging chạy app + db dựng từ Dockerfile → image nền của hai Dockerfile đó không
    vào `evidence.vuln.images` nữa; chỉ image đã dựng đang chạy là bằng chứng (`image_digest.scan_refs`)."""
    from company.events import Task
    from test_dast import _sec
    from test_deploy_release_fsm import RUNTIME, _fake_deploy, _git, _orch, _repo
    from test_supply_chain import _fake_licenses

    _fake_licenses(monkeypatch)
    t = FakeTools()
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    fn, _ = _fake_deploy(monkeypatch, ps=(0, PS_HAI, ""))
    repo = _repo(tmp_path)
    (repo / "compose.yaml").write_text(
        "services:\n  db:\n    build:\n      context: .\n      dockerfile: infra/db/Dockerfile\n  app:\n    build: .\n",
        encoding="utf-8",
    )
    (repo / "infra" / "db").mkdir(parents=True)
    (repo / "infra" / "db" / "Dockerfile").write_text("FROM postgres:16.15-trixie\n", encoding="utf-8")
    (repo / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "build")
    bus, orch = _orch(tmp_path, repo, deploy_fn=fn, runtime={**RUNTIME, "deploy": "compose.yaml"})
    orch.lead.tickets["T1"] = Task(
        ticket_id="T1",
        project_id="P",
        requirement_id="R1",
        assignee="builder",
        title="T1",
        acceptance=["a"],
        risk_tags=["auth"],
    )
    orch.run()
    imgs = _sec(bus)["evidence"]["vuln"]["images"]
    assert [i["ref"] for i in imgs if not i.get("deployed")] == [], "image nền của image đã dựng đang chạy: bỏ"
    assert [i.get("service") for i in imgs if i.get("deployed")] == ["app", "db"]


def test_nhan_compose_dang_dict_va_id_hong_hinh():
    from company.deploy import _image_id

    assert _image_id({"Labels": {"com.docker.compose.image": ID_DB}}) == ID_DB
    assert _image_id({"Labels": {"com.docker.compose.image": "khong-phai-id"}}) == ""
    assert _image_id({}) == "" and _image_id({"Labels": "x.com.docker.compose.image=" + ID_DB}) == ""


def test_deployed_images_ban_ghi_hong_hinh_thi_rong():
    from company.dast import deployed_images

    assert deployed_images(None) == [] and deployed_images({"services": ["a"]}) == []
    assert deployed_images({"services": ["a", "b"], "image_ids": [ID_DB]}) == [], "lệch vị trí thì không đoán ghép"
    assert deployed_images({"services": ["db"], "image_ids": [ID_DB]}) == [("db", ID_DB)]


def test_vuln_evidence_image_dang_chay_quet_loi_vao_errors(tmp_path, monkeypatch):
    t = FakeTools(fail="image")
    monkeypatch.setattr(sc, "which", t.which)
    monkeypatch.setattr(sc, "run", t.run)
    ev = vuln_evidence(tmp_path, "s", [], deployed=[("db", ID_DB)])
    assert ev["images"] == [] and ev["errors"][0]["image"] == ID_DB and "boom" in ev["errors"][0]["error"]
