"""Lượt staging của `ops` nhận SỰ THẬT MÁY về việc dựng được staging hay không (ADR-0061 bổ sung 2026-10-16).

`deploy()` chỉ chạy khi ops khai `deployed` (ADR-0039). Hub thật (QLKH-DD-CSV, REL-105): ops khai `pending_human` vì
"staging còn thiếu QLKH_COMPOSE_DB_PASSWORD (TM-REL102-02)" — đọc từ threat-model cũ, trong khi hub đã cấp secret qua
`COMPANY_DEPLOY_ENV_DIR` (#530). Không container, không DAST, security chặn RC. Ops không đo được env của hub; code đo
và đưa vào đầu vào (`deploy_readiness`, `verified_by=orchestrator`) — đường dẫn/có-không, không bao giờ giá trị.

Hai chiều (luật bắt buộc 4): bỏ enrich khỏi `STAGING_ROUTE` → ca 1 đỏ."""

from __future__ import annotations

import json

from company.deploy import ENV_MODE, ENV_SECRETS_DIR
from company.orch.routes import STAGING_ROUTE
from test_deploy_release_fsm import RUNTIME, _orch, _repo

GIA_TRI_GIA = "gia-tri-gia-cua-test"


def _rc(tmp_path, monkeypatch, *, mode: int | None = 0o600):
    monkeypatch.setenv(ENV_MODE, "compose")
    d = tmp_path / "secrets"
    d.mkdir()
    if mode is not None:
        f = d / "company-p-staging.env"
        f.write_text(f"QLKH_COMPOSE_DB_PASSWORD={GIA_TRI_GIA}\n", encoding="utf-8")
        f.chmod(mode)
    monkeypatch.setenv(ENV_SECRETS_DIR, str(d))
    bus, orch = _orch(tmp_path, _repo(tmp_path), runtime=RUNTIME)
    orch.integration.ensure()
    return bus.latest("release-candidates", "REL-001"), orch


def test_staging_cua_ops_mang_su_that_may_ve_deploy(tmp_path, monkeypatch):
    rc, orch = _rc(tmp_path, monkeypatch)
    assert STAGING_ROUTE.enrich is not None, "lượt staging phải được làm giàu bằng sự thật máy"
    r = STAGING_ROUTE.enrich(rc, orch)["deploy_readiness"]
    assert r["verified_by"] == "orchestrator" and r["mode"] == "compose" and r["compose_file"] == "compose.yaml"
    assert r["secret_env_file"] is True and r["project"] == "company-p-staging"
    assert GIA_TRI_GIA not in json.dumps(r, ensure_ascii=False), "chỉ có/không, không bao giờ giá trị"


def test_khong_co_file_secret_thi_noi_ro_la_khong(tmp_path, monkeypatch):
    rc, orch = _rc(tmp_path, monkeypatch, mode=None)
    r = STAGING_ROUTE.enrich(rc, orch)["deploy_readiness"]
    assert r["secret_env_file"] is False and "secret_env_file_error" not in r


def test_file_secret_sai_quyen_thi_ghi_loi_ma_khong_nem(tmp_path, monkeypatch):
    rc, orch = _rc(tmp_path, monkeypatch, mode=0o644)
    r = STAGING_ROUTE.enrich(rc, orch)["deploy_readiness"]
    assert r["secret_env_file"] is False and "chmod 600" in r["secret_env_file_error"]
