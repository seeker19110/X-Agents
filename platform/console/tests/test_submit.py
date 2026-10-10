"""submit.py: publish event do người tạo vào bus THẬT của software-company (không mock bus) — payload bị kiểm theo
schema của topic y như CLI `publish`, và mọi lỗi người dùng thấy được là ValueError/SubmitError tiếng Việt."""
from __future__ import annotations

from pathlib import Path

import pytest
from company.sqlite_bus import SQLiteBus as CompanyBus

from console import submit as sm

REQ = {"project_id": "P1", "description": "Web bán khoá học tiếng Nhật, mobile-first.", "attachments": []}


@pytest.fixture
def company_db(tmp_path: Path) -> Path:
    return tmp_path / "company.sqlite"


def _last(bus_cls, path: Path, topic: str, key: str):
    bus = bus_cls(path)
    try:
        return list(bus.replay(topic, key))[-1]
    finally:
        bus.close()


# ---------- đường vui ----------

def test_research_request_vao_bus_company_voi_key_project_id(company_db) -> None:
    r = sm.submit(company_db, xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="human:sales")
    assert r["ok"] is True and r["xuong"] == sm.COMPANY and r["topic"] == "research-requests" and r["key"] == "P1"
    env = _last(CompanyBus, company_db, "research-requests", "P1")
    assert env.event_id == r["event_id"] and env.actor == "human:sales" and env.payload["description"] == REQ["description"]


def test_research_request_tao_file_bus_moi_neu_chua_co(company_db) -> None:
    assert not company_db.exists()
    r = sm.submit(company_db, xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="human:sales")
    assert r["key"] == "P1" and company_db.exists()


def test_clarification_answers_vao_bus_company(company_db) -> None:
    payload = {"project_id": "P1", "answers": [{"question_id": "Q1", "answer": "chỉ VNPay"}]}
    r = sm.submit(company_db, xuong=sm.COMPANY, topic="clarification-answers", payload=payload, actor="human:po")
    assert r["key"] == "P1"
    assert _last(CompanyBus, company_db, "clarification-answers", "P1").payload["answers"][0]["question_id"] == "Q1"


def test_research_request_mang_repo_va_base_theo_du_an(company_db) -> None:
    # ADR-0025 (software-company): `repo`/`base` là trường tuỳ chọn của research-requests — console chỉ chuyển nguyên
    # chuỗi, orchestrator mới là nơi kiểm repo có .git hay không.
    payload = {**REQ, "repo": "D:\\khach\\web", "base": "main"}
    r = sm.submit(company_db, xuong=sm.COMPANY, topic="research-requests", payload=payload, actor="human:sales")
    env = _last(CompanyBus, company_db, "research-requests", r["key"])
    assert env.payload["repo"] == "D:\\khach\\web" and env.payload["base"] == "main"


def test_actor_duoc_strip(company_db) -> None:
    sm.submit(company_db, xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="  human:sales ")
    assert _last(CompanyBus, company_db, "research-requests", "P1").actor == "human:sales"


# ---------- tham số sai -> ValueError, không chạm bus ----------

@pytest.mark.parametrize("kw, match", [
    (dict(xuong="nha-may", topic="research-requests", payload=REQ, actor="human"), "xưởng lạ"),
    (dict(xuong=sm.COMPANY, topic="audit-log", payload={"x": 1}, actor="human"), "không nạp tay được"),
    (dict(xuong=sm.COMPANY, topic="research-requests", payload={}, actor="human"), "không rỗng"),
    (dict(xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="   "), "thiếu người giao việc"),
    (dict(xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="h" * 81), "quá dài"),
    (dict(xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="human:a\nhuman:b"), "ký tự điều khiển"),
    (dict(xuong=sm.COMPANY, topic="research-requests", payload={"description": "x"}, actor="human"), "thiếu `project_id`"),
])
def test_tham_so_sai_valueerror_khong_tao_bus(company_db, kw, match) -> None:
    with pytest.raises(ValueError, match=match):
        sm.submit(company_db, **kw)
    assert not company_db.exists()


def test_khong_co_duong_dan_bus_valueerror() -> None:
    with pytest.raises(ValueError, match="--company-db"):
        sm.submit(None, xuong=sm.COMPANY, topic="research-requests", payload=REQ, actor="human")


# ---------- bus từ chối -> SubmitError (schema của topic là hàng rào thật) ----------

def test_payload_sai_schema_company_thanh_submit_error(company_db) -> None:
    with pytest.raises(sm.SubmitError) as ei:
        sm.submit(company_db, xuong=sm.COMPANY, topic="research-requests",
                  payload={"project_id": "P1", "description": 123}, actor="human")   # description phải là string
    assert ei.value.http_status == 400 and "research-requests" in str(ei.value)
    bus = CompanyBus(company_db)
    try:
        assert list(bus.replay("research-requests", "P1")) == []
    finally:
        bus.close()


def test_submit_error_mac_dinh_400_va_giu_ma_truyen_vao() -> None:
    assert sm.SubmitError("x").http_status == 400
    assert sm.SubmitError("x", 409).http_status == 409
