"""collect(): hợp đồng API.md trên DB thật (event publish qua bus của hai công ty)."""
from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from company.gates import HumanGate as CompanyHumanGate
from studio.events import AuditLog as StudioAudit
from studio.events import Envelope as StudioEnvelope
from studio.sqlite_bus import SQLiteBus as StudioSQLiteBus

import console.collect as collect_mod
from conftest import gate_decide
from console.collect import COMPANY, STUDIO, collect

DEAD_GATEWAY = "http://127.0.0.1:9"  # cổng 9 (discard) không có ai nghe → luôn từ chối ngay


def state(company_db: Path | None, studio_db: Path | None) -> dict:
    return collect(company_db, studio_db, gateway_url=DEAD_GATEWAY)


def test_hai_xuong_deu_co_du_lieu(company_db: Path, studio_db: Path) -> None:
    s = state(company_db, studio_db)
    assert s["sources"][COMPANY]["ok"] and s["sources"][STUDIO]["ok"]
    assert s["sources"][COMPANY]["events"] == 8 and s["sources"][STUDIO]["events"] == 5
    assert s["tiles"]["events"] == 13
    assert [t["id"] for t in s["tickets"]] == ["TCK-112"]
    assert s["tickets"][0]["bud"] == 120_000 and s["tickets"][0]["used"] == 8_420
    assert s["prs"] == [{"id": "TCK-112", "br": "ticket/TCK-112", "s": "thêm login",
                         "lint": "pass", "tests": "pass", "v": "workspace"}]
    assert s["reviews"][0]["v"] == "block" and "thiếu authz" in s["reviews"][0]["f"]
    assert [v["id"] for v in s["videos"]] == ["vid-042"]
    assert s["perf"] == [{"id": "vid-042", "imp": 41_200, "views": 7_840, "ctr": 0.19, "avd": 284}]
    assert s["retention"]["video_id"] == "vid-042" and s["retention"]["points"][0] == [0.0, 100.0]
    assert dict(s["agents"])["backend"] == 0.21
    assert {g["xuong"] for g in s["gates"]} == {COMPANY, STUDIO}
    assert [r["ac"] for r in s["log"]]  # audit `produced:*`, mới nhất trước
    assert len(s["cost_days"]["days"]) == len(s["cost_days"]["series"]) == 14
    assert s["cost_days"]["series"][-1][0] == 0.21  # backend = tier strong, hôm nay


def test_moi_khoa_luon_co_mat_va_khong_nem_khi_thieu_db(tmp_path: Path, studio_db: Path) -> None:
    s = state(tmp_path / "khong-co.sqlite", studio_db)
    assert s["sources"][COMPANY] == {"ok": False, "db": None, "events": 0, "error": "chưa có file DB"}
    assert s["sources"][STUDIO]["ok"]
    assert s["tickets"] == [] and s["prs"] == [] and s["reviews"] == []
    assert [g["xuong"] for g in s["gates"]] == [STUDIO, STUDIO]  # phần của xưởng hỏng rỗng, xưởng kia vẫn đủ
    assert s["videos"] and s["tiles"]["events"] == 5
    for key in ("generated_at", "sources", "tiles", "gates", "tickets", "prs", "reviews", "videos", "perf",
                "retention", "cost_days", "agents", "backends", "supervisor", "log"):
        assert key in s


def test_db_hong_bao_loi_chu_khong_nem(tmp_path: Path, studio_db: Path) -> None:
    bad = tmp_path / "hong.sqlite"; bad.write_bytes(b"day khong phai sqlite")
    s = state(bad, studio_db)
    assert s["sources"][COMPANY]["ok"] is False
    assert "không đọc được DB" in s["sources"][COMPANY]["error"]
    assert s["tickets"] == []


def test_khong_co_db_nao(tmp_path: Path) -> None:
    s = state(None, None)
    assert s["sources"][COMPANY]["error"] == "chưa cấu hình đường dẫn DB"
    assert s["tiles"]["events"] == 0 and s["gates"] == [] and s["retention"] == {"video_id": None, "points": []}


def test_tuoi_gate_va_nguong_sev_theo_hang_so_cua_cong_ty(company_db: Path, studio_db: Path) -> None:
    g = CompanyHumanGate()
    over_h = g.timeout.total_seconds() / 3600
    warn_h = g.remind_at.total_seconds() / 3600
    by_id = {x["id"]: x for x in state(company_db, studio_db)["gates"]}
    assert by_id["PLAN-1"]["hours"] == 30 and by_id["PLAN-1"]["sev"] == "over"
    assert by_id["PUB-vid-042"]["hours"] == 13 and by_id["PUB-vid-042"]["sev"] == "warn"
    assert by_id["PLAN-ch1"]["hours"] == 2 and by_id["PLAN-ch1"]["sev"] == "calm"
    assert by_id["PLAN-1"]["hours"] >= over_h > by_id["PUB-vid-042"]["hours"] >= warn_h > by_id["PLAN-ch1"]["hours"]
    assert math.floor(over_h) == 24 and math.floor(warn_h) == 12  # khớp GATE_TIMEOUT/REMIND của repo


def test_gate_da_quyet_khong_con_trong_danh_sach(company_db: Path, studio_db: Path) -> None:
    s = state(company_db, studio_db)
    assert "SPEC-1" not in {g["id"] for g in s["gates"]}          # đã có gate.decide trong log
    assert {"PLAN-1", "PUB-vid-042", "PLAN-ch1"} == {g["id"] for g in s["gates"]}
    bus = StudioSQLiteBus(studio_db)
    gate_decide(bus, StudioEnvelope, StudioAudit, subject_id="PLAN-ch1", decision="approve", by="human:owner")
    bus.close()
    assert "PLAN-ch1" not in {g["id"] for g in state(company_db, studio_db)["gates"]}


def test_gate_mang_du_kien_va_checklist(company_db: Path, studio_db: Path) -> None:
    pub = next(g for g in state(company_db, studio_db)["gates"] if g["id"] == "PUB-vid-042")
    assert pub["kind"] == "publish" and pub["by"] == "publisher" and pub["trigger"] == "human:owner"
    assert pub["title"] == "Ống kính 50mm"
    assert ["video_id", "vid-042"] in pub["facts"]
    assert [item for item, _ in pub["cl"]] == ["review:fact:pass", "thumbnail"]


@pytest.fixture()
def khong_co_llm_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Máy chạy test có thể có sẵn `llm.yaml` của một trong hai công ty; khi đó collect() lấy backend từ đó và
    không bao giờ hỏi gateway. Ép nhánh gateway để test đúng thứ nó định test."""
    monkeypatch.setattr(collect_mod, "_routing_status", lambda: None)


def test_gateway_chet_khong_lam_hong_trang(company_db: Path, studio_db: Path, khong_co_llm_yaml: None) -> None:
    start = datetime.now(UTC)
    s = collect(company_db, studio_db, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == []
    assert s["sources"]["gateway"]["ok"] is False
    assert "gateway" in s["sources"]["gateway"]["error"]
    assert (datetime.now(UTC) - start).total_seconds() < 5  # timeout ngắn, không treo trang
    assert s["tickets"] and s["videos"]  # phần còn lại vẫn đầy đủ


def test_doc_khong_ghi_vao_db(company_db: Path, studio_db: Path) -> None:
    before = (company_db.read_bytes(), studio_db.read_bytes())
    state(company_db, studio_db)
    assert (company_db.read_bytes(), studio_db.read_bytes()) == before


@pytest.mark.parametrize("token", [None])
def test_token_gateway_khong_bat_buoc(company_db: Path, studio_db: Path, token: Path | None, khong_co_llm_yaml: None) -> None:
    s = collect(company_db, studio_db, gateway_token_file=token, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == []
