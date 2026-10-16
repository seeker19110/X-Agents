"""release-engineer tự dừng (`status=pending_human`) thì phải có người được hỏi, và duyệt là chạy lại được ngay.

Trước đây không có gì xử lý trạng thái này: không gate nào mở, `status` xanh, RC nằm im vô hạn; muốn chạy lại phải
DỪNG orchestrator để gọi `redeploy` (lease). Đo được 2026-09-06 (QLKH): 10 RC kẹt đúng kiểu này (7 staging, 3
production), `gates_pending={}`.
"""
from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _agent_of, _drive_to_plan, _inp, handler


def _pausing_release_engineer(pause_envs: dict[str, int]):
    """release-engineer trả `pending_human` `n` lần đầu cho mỗi (env, release) rồi mới `deployed`."""
    seen: dict[str, int] = {}
    def h(system, user):
        a, p = _agent_of(system), _inp(user)
        # ADR-0037 PR-5b: "ops" cũng chạy pha docs/account trên cùng test (vd. release-events production →
        # ghi docs) — payload của các pha đó không có `target_env`, nên chỉ chặn đúng lượt deploy.
        if a == "ops" and "target_env" in p:
            env = p["target_env"]; k = f"{env}:{p['release_id']}"; seen[k] = seen.get(k, 0) + 1
            if seen[k] <= pause_envs.get(env, 0):
                return {"release_id": p["release_id"], "version": "1.0.0", "env": env, "status": "pending_human",
                        "summary": f"dừng {env}: chờ người ({p.get('human_hint') or 'không hint'})"}
        return handler(system, user)
    h.seen = seen  # type: ignore[attr-defined]
    return h


def _events(bus, rid, env):
    return [e.payload["status"] for e in bus.replay(topic="release-events") if e.key == rid and e.payload["env"] == env]


def test_staging_pending_human_mo_gate_va_duyet_thi_chay_lai():
    h = _pausing_release_engineer({"staging": 1})
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    assert _events(bus, "REL-001", "staging") == ["pending_human"]
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation" and g.created_by == "ops", \
        "agent tự dừng mà không ai được hỏi = bế tắc im lặng; phải mở gate escalation cho chính release"
    assert "decision:redeploy|close" in g.checklist
    assert any(e.payload["action"] == "release.pending_human" for e in bus.replay(topic="audit-log"))

    orch.gate.decide("REL-001", "approve", by="human:lead", reason="nợ đã đóng, chạy lại staging"); orch.run()
    assert _events(bus, "REL-001", "staging") == ["pending_human", "deployed"], "duyệt = chạy lại lượt staging, không cần dừng orchestrator"
    assert any(e.payload["action"] == "release.rerun" for e in bus.replay(topic="audit-log"))
    # lý do người duyệt tới tay agent làm hint (lượt thứ hai mới deployed nên summary của lượt đó không còn; kiểm qua lượt pending)
    assert orch.lead.state["T1"] == "merged", "staging deployed → ticket merged → QA hồi quy chạy → Gate 3"
    assert "REL-001" in orch.gate.pending and orch.gate.pending["REL-001"].kind == "release"


def test_production_pending_human_mo_gate_va_duyet_thi_chay_lai_production():
    h = _pausing_release_engineer({"production": 1})
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()  # Gate 3
    assert _events(bus, "REL-001", "production") == ["pending_human"]
    assert orch.gate.pending["REL-001"].kind == "escalation"
    orch.gate.decide("REL-001", "approve", by="human:lead", reason="runbook đã có, deploy"); orch.run()
    assert _events(bus, "REL-001", "production") == ["pending_human", "deployed"]
    assert orch.lead.state["T1"] == "released"


def test_tu_choi_escalation_cua_release_dang_pending_thi_tra_ticket_ve_lam_lai():
    h = _pausing_release_engineer({"staging": 5})
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    assert orch.gate.pending["REL-001"].kind == "escalation"
    # T1 chưa merged (staging chưa deployed) nên rework không đổi được state — nhưng không được chạy lại
    orch.gate.decide("REL-001", "reject", by="human:lead", reason="nội dung sai thật"); orch.run()
    assert _events(bus, "REL-001", "staging") == ["pending_human"], "từ chối thì KHÔNG chạy lại"
    assert "REL-001" not in orch.gate.pending


def test_khong_mo_gate_trung_khi_da_co_gate_cho_release():
    h = _pausing_release_engineer({"staging": 1})
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    n = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request"
            and '"subject_id": "REL-001"' in (e.payload.get("evidence") or ""))
    assert n == 1
    # Cùng event pending_human xử lý lại (replay) → `once` chặn, không mở gate thứ hai
    ev = next(e for e in bus.replay(topic="release-events") if e.key == "REL-001")
    orch.gate.decide("REL-001", "approve", by="human:lead", reason="ok chạy lại"); orch.run()
    orch.processed.discard(ev.event_id); orch.queue.append(ev); orch.run()
    n2 = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request"
             and '"subject_id": "REL-001"' in (e.payload.get("evidence") or "") and '"escalation"' in (e.payload.get("evidence") or ""))
    assert n2 == 1, "event cũ phát lại không được mở gate escalation lần hai"


def test_rerun_khong_lam_gi_khi_khong_pending_human():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _drive_to_plan(bus, orch); orch.run()
    from company.orchestrator import StepResult
    res = StepResult("x", "audit-log", "REL-001")
    assert orch._rerun_release("REL-001", "human:lead", "", res) is False  # staging deployed rồi
    assert orch._rerun_release("REL-999", "human:lead", "", res) is False  # không có RC


def test_rerun_khong_chay_production_khi_gate_release_chua_duyet():
    """release_fsm.py 256->exit: release-event cuối `pending_human` ở env `production` nhưng Gate 3 CHƯA duyệt
    (sổ sách lệch, hoặc người gọi rerun trước khi ký gate) → không chạy lại, trả False — không được tự vượt qua
    cổng người duyệt."""
    from company.events import Envelope as _Env
    from company.orchestrator import StepResult
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    bus.publish(_Env(topic="release-candidates", key="REL-1", actor="delivery-lead",
                       payload={"release_id": "REL-1", "project_id": "P1", "version": "0.1.0", "tickets": []}))
    bus.publish(_Env(topic="release-events", key="REL-1", actor="ops",
                       payload={"release_id": "REL-1", "version": "0.1.0", "env": "production",
                                "status": "pending_human", "summary": "chờ người"}))
    assert not orch.lead._gate_kind_approved("REL-1", "release")
    res = StepResult("x", "audit-log", "REL-1")
    assert orch._rerun_release("REL-1", "human:lead", "", res) is False


def test_ky_lai_gate_3_chay_lai_duoc_luot_production_khong_can_restart():
    """`partial[rc.event_id]` ghi release-engineer sau lượt production đầu; ký lại Gate 3 (như lead làm 03:06
    2026-09-06 cho REL-019) trước đây chỉ chạy được vì orchestrator vừa restart."""
    h = _pausing_release_engineer({"production": 1})
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    assert _events(bus, "REL-001", "production") == ["pending_human"]
    # đóng escalation bằng cách ký LẠI Gate 3 (request + approve kind=release) thay vì duyệt escalation
    orch.gate.decide("REL-001", "reject", by="human:lead", reason="đóng escalation, sẽ ký lại gate release"); orch.run()
    from company.gates import GateRequest
    orch.gate.request(GateRequest(kind="release", subject_id="REL-001", created_by="delivery-lead", checklist=["tests"]))
    orch.gate.decide("REL-001", "approve", by="human:lead", reason="ký lại"); orch.run()
    assert _events(bus, "REL-001", "production") == ["pending_human", "deployed"]


def test_mo_lai_bus_thi_rc_dang_pending_human_tu_truoc_van_duoc_mo_gate(tmp_path):
    """RC kẹt `pending_human` từ TRƯỚC bản vá (event đã processed, không gate): mở lại orchestrator phải thấy gate,
    không cần chờ event mới. Và gate đã quyết rồi mà lượt chạy lại vẫn dừng → gate mới (khoá theo event_id)."""
    from company.sqlite_bus import SQLiteBus
    h = _pausing_release_engineer({"staging": 2})
    bus = SQLiteBus(tmp_path / "c.sqlite"); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    assert orch.gate.pending["REL-001"].kind == "escalation"
    # giả lập "trước bản vá": xoá gate khỏi RAM và khoá once, rồi mở lại bus bằng orchestrator mới
    bus.close()
    bus2 = SQLiteBus(tmp_path / "c.sqlite"); orch2 = Orchestrator(bus2, FakeClient(handler=h))
    assert "REL-001" in orch2.gate.pending, "gate bền qua restart (replay audit)"
    orch2.gate.decide("REL-001", "approve", by="human:lead", reason="chạy lại"); orch2.run()
    # lượt chạy lại (lần 2) vẫn pending_human → gate MỚI cho event mới, không bị `once` của event cũ nuốt
    assert _events(bus2, "REL-001", "staging") == ["pending_human", "pending_human"]
    assert orch2.gate.pending["REL-001"].kind == "escalation"
    orch2.gate.decide("REL-001", "approve", by="human:lead", reason="chạy lại lần nữa"); orch2.run()
    assert _events(bus2, "REL-001", "staging") == ["pending_human", "pending_human", "deployed"]


def test_sweep_mo_gate_cho_rc_pending_khong_co_gate(tmp_path):
    """Đường thẳng vào sweep: RC có event pending_human đã processed, không gate, once trống → tick mở gate."""
    from company.events import Envelope
    from company.sqlite_bus import SQLiteBus
    bus = SQLiteBus(tmp_path / "c.sqlite")
    bus.publish(Envelope(topic="release-candidates", key="REL-001", actor="delivery-lead",
                         payload={"release_id": "REL-001", "project_id": "P1", "tickets": ["T1"], "version": "1.0.0"}))
    bus.publish(Envelope(topic="release-events", key="REL-001", actor="ops",
                         payload={"release_id": "REL-001", "version": "1.0.0", "env": "staging", "status": "pending_human"}))
    orch = Orchestrator(bus, FakeClient(handler=handler))
    for e in list(bus.replay()): orch.processed.add(e.event_id)  # coi như đã xử lý hết từ trước bản vá
    orch.queue.clear()
    orch.tick()
    assert orch.gate.pending["REL-001"].kind == "escalation"
    assert sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.pending_human") == 1
    orch.tick()
    assert sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request") == 1, "không mở trùng"

def test_luot_production_nhan_bang_chung_staging_qa_gate_trong_payload():
    """Agent không có tool đọc bus; lượt production phải thấy staging deployed, QA pass, security, người ký Gate 3
    ngay trong payload. Đo được 2026-09-06 (REL-025): thiếu thì agent trả pending_human 'chưa qua deploy staging thật'."""
    seen: dict = {}
    def h(system, user):
        a, p = _agent_of(system), _inp(user)
        if a == "ops" and p.get("target_env") == "production": seen.update(p)
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="đủ điều kiện"); orch.run()
    ev = seen["evidence"]
    assert ev["staging"]["status"] == "deployed" and ev["staging"]["version"] and ev["staging"]["at"]  # version là của RC (delivery-lead), không phải lời khai model
    assert ev["reviews"]["qa"]["verdict"] == "pass" and ev["waived"] == []
    assert ev["gate_release_by"] == "human:release-manager" and ev["gate_release_reason"] == "đủ điều kiện"
    assert seen["gate_release"] is True


def test_tu_choi_escalation_cua_rc_da_bi_ban_giao_vuot_qua_thi_huy_rc_khong_lam_lai():
    """Sau bản giao, RC cũ pending_human mở gate; từ chối = huỷ RC (nội dung đã tới khách), KHÔNG trả ticket đã giao
    về làm lại như hành vi cũ."""
    h = _pausing_release_engineer({"staging": 9})  # REL-001 dừng mãi ở staging; REL-002 cũng dừng
    def h2(system, user):
        a, p = _agent_of(system), _inp(user)
        if a == "ops" and p.get("release_id") == "REL-002":  # REL-002 đi trót lọt và được giao
            return handler(system, user)
        return h(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h2))
    _drive_to_plan(bus, orch); orch.run()
    assert _events(bus, "REL-001", "staging") == ["pending_human"]
    # REL-002 (T2) chưa mở được vì T2 phụ thuộc T1 mà T1 chưa merged → dùng đường: coi REL-001 đã tích hợp và
    # có bản giao sau nó bằng cách ghi trực tiếp sổ sách như _rehydrate làm
    orch.integrated.add("T1")
    orch.lead.releases.append("REL-009"); orch.lead.release_tickets["REL-009"] = ["T9"]
    orch.delivered["REL-009"] = {"release_id": "REL-009", "tag": "v9"}
    assert orch._superseded_release("REL-001") is True
    orch.gate.decide("REL-001", "reject", by="human:lead", reason="đã nằm trong v9"); orch.run()
    assert "REL-001" in orch.void_releases
    assert orch.lead.state["T1"] != "changes_requested", "ticket đã giao không được trả về làm lại"
    voids = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.void"]
    assert voids and "bản giao" in voids[-1].payload["evidence"]
    # không có bản giao sau → không superseded → hành vi cũ
    assert orch._superseded_release("REL-009") is False and orch._superseded_release("REL-404") is False
    orch.delivered.clear()
    assert orch._superseded_release("REL-001") is False


def test_huy_rc_superseded_khong_de_ticket_lai_cho_flush_releases_tao_rc_trung():
    """Đo được 2026-09-10 (QLKH thật): huỷ một RC cũ vì superseded (nội dung đã nằm trong bản giao sau) đưa ticket
    về `unreleased()` — đúng chủ đích cho ca xung đột tích hợp (`void_release`, docstring "ticket phải vào RC kế
    tiếp"), nhưng SAI cho ca superseded: ticket không cần RC kế tiếp, nó đã giao rồi. `scheduler.tick()` (PR #251)
    gọi `flush_releases()` mỗi nhịp sẽ thấy ticket "approved, không có RC" và tạo NGAY một RC trùng, gửi nó qua một
    vòng staging/production MỚI — nếu vòng đó đụng lỗi thật (nhiễu backend, xung đột khác), `_on_release_event`
    (dòng ~322) đá ticket ĐÃ GIAO về `changes_requested` rồi hết retry → `blocked`, dù code chưa từng sai gì.

    Ticket sau khi huỷ RC vì superseded phải ở một DONE_STATE thật (không phải "approved" lửng lơ) và không còn
    xuất hiện trong `unreleased()` — không có gì cho `flush_releases` gom lại."""
    h = _pausing_release_engineer({"staging": 9})  # REL-001 (T1) không bao giờ deploy được — giữ T1 ở "approved"
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.state["T1"] == "approved", "tiền đề: ticket chưa từng deploy thành công, còn approved"

    orch.integrated.add("T1")
    orch.lead.releases.append("REL-009"); orch.lead.release_tickets["REL-009"] = ["T9"]
    orch.delivered["REL-009"] = {"release_id": "REL-009", "tag": "v9"}
    orch.gate.decide("REL-001", "reject", by="human:lead", reason="đã nằm trong v9"); orch.run()
    assert "REL-001" in orch.void_releases

    assert orch.lead.state["T1"] != "approved", "phải chuyển sang DONE_STATE thật, không để lửng lơ ở approved"
    assert "T1" not in orch.lead.unreleased("P1"), "ticket đã giao không được cho flush_releases gom lại"


def _rc_deploy_failed(env: str, *, gate3: bool):
    from company.events import Envelope as _Env
    from company.gates import GateRequest
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    bus.publish(_Env(topic="release-candidates", key="REL-1", actor="delivery-lead",
                     payload={"release_id": "REL-1", "project_id": "P1", "version": "0.1.0", "tickets": []}))
    if gate3:
        orch.gate.request(GateRequest(kind="release", subject_id="REL-1", created_by="delivery-lead", checklist=[]))
        orch.gate.decide("REL-1", "approve", by="human:release-manager")
    bus.publish(_Env(topic="release-events", key="REL-1", actor="ops",
                     payload={"release_id": "REL-1", "version": "0.1.0", "env": env, "status": "deploy_failed"}))
    return bus, orch


def test_duyet_redeploy_sau_deploy_failed_production_thi_chay_lai_production():
    """Hub thật 2026-10-16 (REL-119): Gate 3 đã ký, deploy production hỏng vì máy trực thiếu file env bí mật; người sửa
    cấu hình rồi duyệt escalation `decision:redeploy` — nhưng `_rerun_release` chỉ nhận `pending_human` ⇒ không chạy
    lại gì, RC nằm im dù gate đã đóng."""
    from company.orchestrator import StepResult
    bus, orch = _rc_deploy_failed("production", gate3=True)
    assert orch._rerun_release("REL-1", "reviewer:phien-chinh", "đã thêm file env", StepResult("x", "audit-log", "REL-1"))
    rr = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.rerun"]
    assert rr and '"env": "production"' in rr[-1].payload["evidence"]


def test_duyet_redeploy_sau_deploy_failed_staging_thi_chay_lai_staging():
    from company.orchestrator import StepResult
    _bus, orch = _rc_deploy_failed("staging", gate3=False)
    assert orch._rerun_release("REL-1", "reviewer:phien-chinh", "", StepResult("x", "audit-log", "REL-1"))


def test_deploy_failed_production_van_khong_vuot_gate_3():
    from company.orchestrator import StepResult
    _bus, orch = _rc_deploy_failed("production", gate3=False)
    assert orch._rerun_release("REL-1", "reviewer:phien-chinh", "", StepResult("x", "audit-log", "REL-1")) is False
