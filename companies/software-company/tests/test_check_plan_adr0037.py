"""ADR-0037 PR-1: `_check_plan` phải chặn mọi khoá "Code gửi kèm" của gate plan cũ (kích thước ticket, risk_tags,
threat model, architecture/api-contract trên blackboard) TRƯỚC khi plan tới người duyệt — vì PR-2 bỏ hẳn gate
plan và các khoá này sẽ không còn ai kiểm nếu không nằm trong `_check_plan`
(`docs/DAC-TA-TRIEN-KHAI-ADR-0037.md` §2)."""

from __future__ import annotations

import json

import company.orch.guards as guards
from company.bus import InMemoryBus
from company.events import Envelope, ReviewResult, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator


def _orch() -> Orchestrator:
    return Orchestrator(InMemoryBus(), FakeClient())


def _task(**kw) -> Task:
    base = dict(
        ticket_id="T1",
        project_id="P1",
        requirement_id="REQ-1",
        assignee="builder",
        stack="backend",
        title="x",
        acceptance=["given/when/then"],
        estimate_tokens=4_000,
        budget_tokens=6_000,
    )
    base.update(kw)
    return Task(**base)


def _satisfy_threat_and_blackboard(o: Orchestrator, project: str = "P1") -> None:
    o.bus.publish(
        Envelope(
            topic="review-results",
            key=f"SPEC-{project}",
            actor="security",
            payload=ReviewResult(ticket_id=f"SPEC-{project}", source="security", verdict="pass").model_dump(),
        )
    )
    o.blackboard.write("product", "architecture", "docs/c4.md", "L1-L2", project_id=project)
    o.blackboard.write("product", "api-contract", "openapi.yaml", "v1", project_id=project)


def _baseline_ok(o: Orchestrator, project: str = "P1") -> list[Task]:
    _satisfy_threat_and_blackboard(o, project)
    return [_task()]


# ---------- thiếu `stack` (ADR-0037 §4.2, PR-5e) ----------


def test_ticket_thieu_stack_bi_tu_choi(monkeypatch):
    """`stack` chọn bộ skill của `builder` cho lượt ấy (`routes.phase_for`), nên ticket thiếu `stack` được làm
    bằng prompt CHUNG — mất skill của mảng mà không ai đỏ. Kiểm ở `_check_plan` chứ không `required` trong
    `tasks.json`: bus từ chối một ticket là kế hoạch chết giữa chừng, ở đây cả kế hoạch quay về cho `product`."""
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(stack=None)
    assert "T1 thiếu stack" in o._check_plan(tickets, "P1")
    # bật lại: cùng ticket, chỉ thêm `stack` → problem biến mất (không phải một problem khác che mất)
    tickets[0] = _task(stack="frontend")
    assert not any("thiếu stack" in p for p in o._check_plan(tickets, "P1"))
    # tắt bản sửa: bỏ đúng dòng kiểm → ticket thiếu `stack` đi lọt, chứng minh test đo đúng dòng đó
    goc = guards._check_plan

    def khong_kiem_stack(o_, tickets_, project):
        return [p for p in goc(o_, tickets_, project) if "thiếu stack" not in p]

    monkeypatch.setattr(guards, "_check_plan", khong_kiem_stack)
    assert not any("thiếu stack" in p for p in khong_kiem_stack(o, [_task(stack=None)], "P1"))


# ---------- ticket quá 1 ngày / 200k token ----------


def test_ticket_qua_lon_bi_tu_choi():
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(estimate_tokens=250_000, budget_tokens=400_000)
    problems = o._check_plan(tickets, "P1")
    assert any("quá 1 ngày/200k token" in p for p in problems)

    tickets[0] = _task(estimate_tokens=100_000, budget_tokens=200_000)
    problems = o._check_plan(tickets, "P1")
    assert not any("quá 1 ngày/200k token" in p for p in problems)


def test_ticket_qua_1_ngay_bi_tu_choi():
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(estimate_days=1.5)
    problems = o._check_plan(tickets, "P1")
    assert any("quá 1 ngày/200k token" in p for p in problems)

    tickets[0] = _task(estimate_days=1)
    problems = o._check_plan(tickets, "P1")
    assert not any("quá 1 ngày/200k token" in p for p in problems)


def test_thieu_estimate_tokens_bi_tu_choi():
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(estimate_tokens=None)
    problems = o._check_plan(tickets, "P1")
    assert any("thiếu estimate_tokens" in p for p in problems)


def test_tat_kiem_token_thi_khong_con_problem(monkeypatch):
    """Chiều ngược: tắt trần token thì ticket vượt token (nhưng estimate_days bình thường) không còn bị chặn."""
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(estimate_tokens=250_000, budget_tokens=400_000)
    monkeypatch.setattr(guards, "MAX_TICKET_TOKENS", 10**9)
    problems = o._check_plan(tickets, "P1")
    assert not any("quá 1 ngày/200k token" in p for p in problems)


# ---------- risk_tags ----------


def test_risk_hint_khong_tag_tu_dong_gan_thay_vi_tu_choi():
    """Trước: ticket chạm từ khoá rủi ro mà quên khai risk_tags làm CẢ kế hoạch bị `plan_rejected`, dự án
    đứng lại chờ người duyệt gate `escalation`, rồi `product` phải sinh lại TOÀN BỘ kế hoạch từ đầu (một lượt
    model tốn tiền/thời gian) — dù việc thiếu chỉ là một khoá suy được thẳng từ `RISK_HINTS`. Đo thật
    2026-09-22 (CAMPUS-UNI): plan bị từ chối 2 lần liên tiếp, mỗi lần một ticket khác nhau thiếu risk_tags.
    Nay: gắn tag suy được và AUDIT lại (`risk_tags_autofixed`), không còn là `problems` — an toàn hơn hiện
    trạng (tag được THÊM chứ không bớt, security review vẫn chạy), không tốn thêm lượt model nào."""
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(title="Đăng nhập OAuth")
    problems = o._check_plan(tickets, "P1")
    assert not any("không có risk_tags" in p for p in problems)
    assert tickets[0].risk_tags == ["auth"]
    fixed = [
        json.loads(e.payload["evidence"])
        for e in o.bus.replay(topic="audit-log")
        if e.payload.get("action") == "risk_tags_autofixed"
    ]
    assert fixed and fixed[0]["ticket_id"] == "T1" and fixed[0]["risk_tags"] == ["auth"]

    tickets[0] = _task(title="Đăng nhập OAuth", risk_tags=["auth"])
    problems = o._check_plan(tickets, "P1")
    assert not any("không có risk_tags" in p for p in problems)
    assert tickets[0].risk_tags == ["auth"]  # đã có sẵn thì không đụng vào, không autofix thừa


def test_risk_hint_khong_map_duoc_van_bi_tu_choi(monkeypatch):
    """`HINT_TO_TAG` chưa phủ hết `RISK_HINTS` (bẫy đồng bộ hai bảng) → không đoán bừa, vẫn trả về `problems`
    như hành vi cũ, để không lặng lẽ bỏ qua một hint không suy được tag."""
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(title="Đăng nhập OAuth")
    monkeypatch.setattr(guards, "HINT_TO_TAG", {})
    problems = o._check_plan(tickets, "P1")
    assert any("không có risk_tags" in p for p in problems)


def test_tat_risk_hints_thi_khong_con_problem(monkeypatch):
    o = _orch()
    tickets = _baseline_ok(o)
    tickets[0] = _task(title="Đăng nhập OAuth")
    monkeypatch.setattr(guards, "RISK_HINTS", frozenset())
    problems = o._check_plan(tickets, "P1")
    assert not any("không có risk_tags" in p for p in problems)


# ---------- threat model ----------


def test_thieu_threat_model():
    o = _orch()
    o.blackboard.write("product", "architecture", "docs/c4.md", "L1-L2", project_id="P1")
    o.blackboard.write("product", "api-contract", "openapi.yaml", "v1", project_id="P1")
    problems = o._check_plan([_task()], "P1")
    assert any("thiếu threat model" in p for p in problems)

    o.bus.publish(
        Envelope(
            topic="review-results",
            key="SPEC-P1",
            actor="security",
            payload=ReviewResult(ticket_id="SPEC-P1", source="security", verdict="pass").model_dump(),
        )
    )
    problems = o._check_plan([_task()], "P1")
    assert not any("thiếu threat model" in p for p in problems)


def test_missing_threat_model_set_cung_chan():
    o = _orch()
    _satisfy_threat_and_blackboard(o)
    o.missing_threat_model.add("SPEC-P1")
    problems = o._check_plan([_task()], "P1")
    assert any("thiếu threat model" in p for p in problems)


# ---------- blackboard architecture / api-contract ----------


def test_thieu_architecture_tren_blackboard():
    o = _orch()
    o.bus.publish(
        Envelope(
            topic="review-results",
            key="SPEC-P1",
            actor="security",
            payload=ReviewResult(ticket_id="SPEC-P1", source="security", verdict="pass").model_dump(),
        )
    )
    problems = o._check_plan([_task()], "P1")
    assert any("blackboard thiếu architecture" in p for p in problems)
    assert any("blackboard thiếu api-contract" in p for p in problems)

    o.blackboard.write("product", "architecture", "docs/c4.md", "L1-L2", project_id="P1")
    o.blackboard.write("product", "api-contract", "openapi.yaml", "v1", project_id="P1")
    problems = o._check_plan([_task()], "P1")
    assert not any("blackboard thiếu" in p for p in problems)


def test_khong_co_blackboard_thi_bo_qua_kiem_architecture():
    """Dự án không có blackboard (`o.blackboard is None`) → không kiểm `architecture`/`api-contract`, không sập."""
    o = _orch()
    o.blackboard = None  # dự án không có blackboard (đo được: khách không cấu hình lưu trữ chung)
    o.bus.publish(
        Envelope(
            topic="review-results",
            key="SPEC-P1",
            actor="security",
            payload=ReviewResult(ticket_id="SPEC-P1", source="security", verdict="pass").model_dump(),
        )
    )
    problems = o._check_plan([_task()], "P1")
    assert not any("blackboard thiếu" in p for p in problems)


def test_baseline_du_dieu_kien_khong_co_problem():
    o = _orch()
    tickets = _baseline_ok(o)
    assert o._check_plan(tickets, "P1") == []


# ---------- phụ thuộc ticket đã bị bỏ / đang bị thay (hub 2026-10-14) ----------


def test_phu_thuoc_ticket_bi_bo_hoac_dang_bi_thay_bi_tu_choi():
    """Hub thật 2026-10-14 (QLKH-DD-CSV): PLAN-QLKH-DD-CSV-19 cho DDCSV-89/90 `depends_on` DDCSV-73 — ticket đang
    `blocked` với REPLAN-DDCSV-73-1 đã `accepted` (sắp bị đóng). 13:36 nó bị đóng, 89/90 thành `blocked` + escalation.
    Ticket đóng vì đã XONG thì vẫn phụ thuộc được."""
    o = _orch()
    tasks = _baseline_ok(o)
    for tid in ("BO", "THAY", "XONG"):
        o.lead.tickets[tid] = _task(ticket_id=tid)
    o.lead.abandoned.add("BO")
    o.lead.state["BO"] = "closed"
    o.lead.state["THAY"] = "blocked"
    o.lead.replan_accepted["THAY"] = Envelope(
        topic="change-requests",
        key="REPLAN-THAY-1",
        actor="reviewer:tu-dong",
        payload={"change_id": "REPLAN-THAY-1", "decision": "accepted"},
    )
    o.lead.state["XONG"] = "closed"
    tasks[0].depends_on = ["BO", "THAY", "XONG"]
    problems = guards._check_plan(o, tasks, "P1")
    assert any("BO" in p and "THAY" in p and "bị bỏ" in p for p in problems), problems
    assert not any("XONG" in p for p in problems), "ticket đã xong vẫn là phụ thuộc hợp lệ"
