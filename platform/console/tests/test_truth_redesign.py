"""Đợt 3 — console thiết kế lại: lớp `truth.py` của C1–C5.

Mỗi test dưới đây đo MỘT ghi nhận đêm 05–06/09 (`console/TRAPS.md`), và đo hai chiều: đặt tình huống mà bản cũ
hiển thị sai, rồi khẳng định con số mới nói đúng. Tắt phần sửa (bỏ `product_funnel`, `silent_ticket_deadlocks`,
`pending_decision`, `review_trimmed_sources`, `gate_reject_effect`) là cả file đỏ.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from company.events import AuditLog, Envelope, ReviewResult, Task
from company.gates import GateRequest, HumanGate

from console.truth import Truth, gate_next_agent, gate_reject_effect

NOW = datetime(2026, 9, 6, 4, 0, tzinfo=UTC)


def audit(actor: str, action: str, ev: dict[str, Any] | None = None, *, ts: datetime = NOW) -> Envelope:
    p = AuditLog(actor=actor, action=action, evidence=json.dumps(ev, ensure_ascii=False) if ev is not None else None)
    return Envelope(topic="audit-log", key=actor, actor=actor, ts=ts, payload=p.model_dump())


def rel_event(rid: str, env: str, status: str, **extra: Any) -> Envelope:
    return Envelope(topic="release-events", key=rid, actor="ops", ts=NOW,
                    payload={"release_id": rid, "version": "1.0.0", "env": env, "status": status, **extra})


def rc(rid: str, tickets: list[str]) -> Envelope:
    return Envelope(topic="release-candidates", key=rid, actor="delivery-lead", ts=NOW,
                    payload={"release_id": rid, "project_id": "P1", "tickets": tickets, "version": "1.0.0"})


def topic_event(topic: str, pid: str, key: str) -> Envelope:
    return Envelope(topic=topic, key=key, actor="human:owner", ts=NOW, payload={"project_id": pid, "id": key})


def review(tid: str, source: str, verdict: str) -> Envelope:
    r = ReviewResult(ticket_id=tid, source=source, verdict=verdict)
    return Envelope(topic="review-results", key=tid, actor="qa", ts=NOW, payload=r.model_dump())


def task(tid: str = "T1", pid: str = "P1") -> Task:
    return Task(ticket_id=tid, project_id=pid, requirement_id="R1", assignee="builder", title="x",
                acceptance=["ok"], estimate_tokens=1, budget_tokens=2)


def lead_stub(**over: Any) -> SimpleNamespace:
    base = {"state": {}, "tickets": {}, "releases": [], "release_tickets": {}, "release_reviews": {}, "release_waived": {}}
    return SimpleNamespace(**{**base, **over})


# ---- C1: phễu sản phẩm, ô rỗng là ô xám -----------------------------------

def test_c1_o_rong_deu_mang_empty_khong_bao_gio_nhin_nhu_o_tot() -> None:
    """Bẫy hiển thị số 1: `queue 0, blocked [], gates {}` vẽ y hệt một dự án khoẻ. Một dự án mới có đúng một bậc
    có dữ liệu (ticket) thì sáu bậc còn lại PHẢI mang `empty=True` để trang tô xám."""
    tr = Truth([], lead_stub(tickets={"T1": task()}, state={"T1": "in_progress"}), HumanGate(), NOW)
    rows = tr.product_funnel()
    assert [r["project_id"] for r in rows] == ["P1"]
    assert [s["stage"] for s in rows[0]["stages"]] == \
        ["request", "spec", "ticket", "rc", "staging", "production", "acceptance"]
    stages = {s["stage"]: s for s in rows[0]["stages"]}
    assert stages["ticket"]["n"] == 1 and stages["ticket"]["empty"] is False
    assert all(stages[k]["empty"] for k in ("request", "spec", "rc", "staging", "production", "acceptance"))
    assert rows[0]["delivered"] is False


def test_c1_bac_staging_va_production_dem_smoke_chu_khong_dem_loi_khai() -> None:
    """`status=deployed` là lời khai của agent; `payload.smoke` là bằng chứng máy sinh (ADR-0029)."""
    lead = lead_stub(tickets={"T1": task()}, state={"T1": "released"}, releases=["REL-1"],
                     release_tickets={"REL-1": ["T1"]})
    env = [topic_event("research-requests", "P1", "R1"), topic_event("approved-specs", "P1", "SPEC-1"),
           topic_event("acceptance-results", "P1", "UAT-1"), rc("REL-1", ["T1"]),
           rel_event("REL-1", "staging", "deployed", smoke={"ok": True, "http_status": 200}),
           rel_event("REL-1", "production", "deployed", smoke={"ok": False, "error": "502"})]
    stages = {s["stage"]: s for s in Truth(env, lead, HumanGate(), NOW).product_funnel()[0]["stages"]}
    assert stages["request"]["n"] == 1 and stages["spec"]["n"] == 1 and stages["rc"]["n"] == 1
    assert stages["staging"]["smoke"] == "ok" and stages["production"]["smoke"] == "fail"
    assert stages["acceptance"]["n"] == 1

    khong = Truth([rc("REL-1", ["T1"]), rel_event("REL-1", "staging", "deployed")], lead, HumanGate(), NOW)
    assert {s["stage"]: s for s in khong.product_funnel()[0]["stages"]}["staging"]["empty"] is True, \
        "deployed mà không smoke thì KHÔNG được tính là đã lên staging"
    chua = Truth([rc("REL-1", ["T1"]), rel_event("REL-1", "staging", "deployed", smoke={"unverified": True})],
                 lead, HumanGate(), NOW)
    assert {s["stage"]: s for s in chua.product_funnel()[0]["stages"]}["staging"]["smoke"] == "unverified"


def test_c1_da_giao_can_ca_production_va_nghiem_thu() -> None:
    lead = lead_stub(tickets={"T1": task()}, releases=["REL-1"], release_tickets={"REL-1": ["T1"]})
    env = [rc("REL-1", ["T1"]), rel_event("REL-1", "production", "deployed", smoke={"ok": True})]
    assert Truth(env, lead, HumanGate(), NOW).product_funnel()[0]["delivered"] is False, "lên production chưa phải đã giao"
    assert Truth([*env, topic_event("acceptance-results", "P1", "UAT-1")], lead, HumanGate(), NOW) \
        .product_funnel()[0]["delivered"] is True


def test_c1_rc_bi_huy_khong_dem_va_rc_khong_ro_du_an_van_hien() -> None:
    lead = lead_stub(releases=["REL-1", "REL-2"], release_tickets={"REL-1": ["T-la"]})
    env = [audit("orchestrator", "release.void", {"release_id": "REL-1", "reason": "trùng ticket"}), rc("REL-2", [])]
    rows = Truth(env, lead, HumanGate(), NOW).product_funnel()
    assert [r["project_id"] for r in rows] == ["?"], "RC không truy được dự án vẫn phải hiện, dưới nhãn `?`"
    assert {s["stage"]: s["n"] for s in rows[0]["stages"]}["rc"] == 1, "RC void không đếm vào phễu"


# ---- C2: hậu quả hai chiều ------------------------------------------------

def test_c2_tu_choi_thi_ticket_ve_dau_va_duyet_thi_ai_chay_lai() -> None:
    assert "không deploy" in gate_reject_effect("release", "REL-1")
    assert "nằm nguyên bậc" in gate_reject_effect("escalation", "REL-1")
    assert "ĐÓNG hẳn" in gate_reject_effect("escalation", "T1")
    assert gate_reject_effect("plan", "PLAN-ch1") == "", "ADR-0037: company không còn gate plan; studio có nhưng không dùng bảng này"
    assert "viết lại PRD" in gate_reject_effect("spec", "SPEC-1")
    assert "mở lại" in gate_reject_effect("acceptance", "UAT-1")
    assert gate_reject_effect("publish", "PUB-1") == "", "không biết thì im, không đoán"
    assert gate_next_agent("release") == "ops" and gate_next_agent("publish") == ""


# ---- C3: quyết định đã ký, máy chưa áp ------------------------------------

def test_c3_badge_quyet_dinh_cho_ap_gan_dung_ticket() -> None:
    """Ký 01:34, áp 01:48, trang im lặng suốt 14 phút (TRAPS §6). Giờ badge nằm trên chính ticket đó."""
    lead = lead_stub(tickets={"T1": task()}, state={"T1": "escalated"})
    decide = audit("human:owner", "gate.decide",
                   {"subject_id": "T1", "decision": "approve", "by": "human:owner", "reason": "root_cause: thiếu authz"},
                   ts=NOW - timedelta(minutes=14))
    tr = Truth([decide], lead, HumanGate(), NOW)
    pd = tr.ticket_extra("T1")["pending_decision"]
    assert pd is not None and pd["decision"] == "approve" and pd["minutes"] == 14
    assert tr.pending_decision_of("T-khac") is None
    done = audit("orchestrator", "orchestrated", {"event_id": decide.event_id})
    assert Truth([decide, done], lead, HumanGate(), NOW).ticket_extra("T1")["pending_decision"] is None, \
        "đã áp rồi thì badge phải biến mất, không thì nó thành nhiễu vĩnh viễn"


# ---- C4: bế tắc im lặng ---------------------------------------------------

def test_c4_chi_ticket_ket_ma_khong_gate_nao_cho_moi_la_be_tac_im_lang() -> None:
    gate = HumanGate()
    gate.request(GateRequest(kind="escalation", subject_id="T-co-gate", checklist=[], created_by="supervisor"))
    lead = lead_stub(state={"T-im": "blocked", "T-co-gate": "blocked", "T-chay": "in_progress"})
    silent = Truth([], lead, gate, NOW).silent_ticket_deadlocks()
    assert [d["id"] for d in silent] == ["T-im"], "ticket đã có gate chờ là 'đang chờ người', không phải bế tắc"
    assert silent[0]["kind"] == "ticket" and "không ai được hỏi" in silent[0]["why"]


# ---- C5: bằng chứng bị cắt ------------------------------------------------

def test_c5_liet_ke_dung_tung_nguon_bi_cat_va_so_ky_tu_mat() -> None:
    """"security chặn vì thiếu diff" hoá ra là openapi 804 dòng ăn hết hạn mức, và không ai thấy (TRAPS §8)."""
    lead = lead_stub()
    rv = review("T1", "security", "block")
    prod = audit("security-engineer", "produced:review-results", {"event": rv.event_id, "duration_ms": 60_000})
    cut = audit("security-engineer", "context_trimmed",
                {"trimmed_payload": 804, "trimmed_context": {"api-contract": 13170}}, ts=NOW - timedelta(seconds=40))
    assert Truth([rv, prod, cut], lead, HumanGate(), NOW).review_trimmed_sources(rv) == \
        [{"src": "api-contract", "chars": 13170}, {"src": "payload", "chars": 804}]
    assert Truth([rv], lead, HumanGate(), NOW).review_trimmed_sources(rv) == [], "không biết thì không nói"
    other = audit("qa", "context_trimmed", {"trimmed_context": {"prd": 1}}, ts=NOW - timedelta(seconds=10))
    assert Truth([rv, prod, other], lead, HumanGate(), NOW).review_trimmed_sources(rv) == [], \
        "bản ghi cắt của agent KHÁC không được gán cho verdict này"


# ---- K2.7: lệnh của khách chạy trong lớp bảo vệ nào (ADR-0035) -------------

def _pr(tid: str, sandbox: str | None, *, ts: datetime = NOW) -> Envelope:
    lc: dict[str, Any] = {"lint": True, "tests": True, "verified_by": "workspace"}
    if sandbox is not None: lc["sandbox"] = sandbox
    return Envelope(topic="pull-requests", key=tid, actor="builder", ts=ts,
                    payload={"ticket_id": tid, "branch": f"ticket/{tid}", "local_checks": lc})


def test_k27_dem_theo_ten_sandbox_tu_ca_ba_nguon_bang_chung() -> None:
    """Ba chỗ CODE điền bằng chứng, không đọc cấu hình: PR (lint/test), release-events (smoke), audit tools_used
    (tool `run` của model). Đọc cấu hình thay vì bằng chứng là sai loại: cấu hình lúc người trực mở trang có thể
    đã khác cấu hình lúc lượt đó chạy."""
    env = [_pr("T1", "subprocess"),
           rel_event("REL-1", "staging", "deployed", smoke={"ok": True, "sandbox": "container:python:3.12-slim"}),
           audit("builder", "tools_used", {"run": 2, "sandbox": "subprocess"})]
    sb = Truth(env, lead_stub(), HumanGate(), NOW).sandbox()
    assert sb["runs"] == 3 and sb["unsandboxed"] == 2
    assert sb["by_name"] == {"container:python:3.12-slim": 1, "subprocess": 2}
    assert sb["last_at"] == NOW.isoformat(timespec="seconds")


def test_s1_sandbox_mode_doc_audit_moi_nhat_ke_ca_khi_chua_co_luot_chay() -> None:
    env = [audit("orchestrator", "sandbox.mode", {"mode": "container:old"}, ts=NOW - timedelta(minutes=2)),
           audit("orchestrator", "sandbox.mode", {"mode": "subprocess"}),
           audit("builder", "sandbox.mode", {"mode": "container:fake"})]
    sb = Truth(env, lead_stub(), HumanGate(), NOW).sandbox()
    assert sb["mode"] == "subprocess"
    assert sb["runs"] == 0


def test_k27_moi_luot_trong_container_thi_khong_con_gi_de_canh_bao() -> None:
    env = [_pr("T1", "container:img"), _pr("T2", "container:img")]
    sb = Truth(env, lead_stub(), HumanGate(), NOW).sandbox()
    assert sb["runs"] == 2 and sb["unsandboxed"] == 0, "ô cảnh báo tắt khi `unsandouxed` = 0"


def test_k27_luot_cu_hon_cua_so_khong_keo_canh_bao_sang_mai() -> None:
    """Người vận hành bật container hôm nay thì ô phải TẮT hôm nay — một lượt subprocess tuần trước không nói gì
    về hiện tại. Bỏ bộ lọc thời gian là cảnh báo không bao giờ tắt được, và cảnh báo không tắt được thì người
    học cách bỏ qua nó."""
    cu = _pr("T0", "subprocess", ts=NOW - timedelta(hours=30))
    moi = _pr("T1", "container:img")
    sb = Truth([cu, moi], lead_stub(), HumanGate(), NOW).sandbox()
    assert sb["runs"] == 1 and sb["unsandboxed"] == 0
    rong = Truth([cu], lead_stub(), HumanGate(), NOW).sandbox()
    assert rong["runs"] == 0 and rong["last_at"] is None
    assert Truth([cu], lead_stub(), HumanGate(), NOW).sandbox(hours=72)["unsandboxed"] == 1, "nới cửa sổ thì thấy lại"


def test_k27_luot_khong_khai_sandbox_khong_bi_dem_nham() -> None:
    """PR từ trước ADR-0035 (hoặc bảng tool `allow_run=False`) không có trường `sandbox`. Đếm nó là `subprocess`
    thì log cũ làm cảnh báo sáng vĩnh viễn; đếm nó là `container` thì che mất lượt thật. Không đếm."""
    sb = Truth([_pr("T1", None), _pr("T2", "")], lead_stub(), HumanGate(), NOW).sandbox()
    assert sb == {"window_h": 24, "runs": 0, "unsandboxed": 0, "mode": None, "by_name": {}, "last_at": None}
