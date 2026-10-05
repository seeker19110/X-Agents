"""ADR-0031: `runtime` là điều kiện cần của Gate 1.

Đo được 2026-09-06 (QLKH): bốn gate xanh, 0 điểm vào chạy được — câu "chạy cho tôi xem" chưa từng được hỏi. Từ ADR này
spec `kind=application` không có `runtime` hợp lệ thì orchestrator KHÔNG mở gate spec: trả lại spec-writer với lý do
(như `request_changes` của người), quá một lần thì hỏi người qua escalation cấp dự án. Test đo hai chiều: thiếu → không
gate, có request_changes; có runtime → gate mở như cũ; `kind=library` không runtime → gate mở."""
from __future__ import annotations

from company import gate_brief as GB
from company.bus import InMemoryBus
from company.events import Envelope
from company.llm import FakeClient, TransientError
from company.orchestrator import SPEC_RUNTIME_REWORKS, Orchestrator, spec_runtime_gap
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _inp, _product_phase, _pub, _thuoc_tinh_lech, handler

RUNTIME = {"command": "python -m app --port {port}", "port": 0, "health": "/health", "dependencies": ["sqlite"]}
ARTIFACTS = {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}


def _spec(pid: str, **extra) -> dict:
    return {"payload": {"project_id": pid, "status": "pending_human", "artifacts": ARTIFACTS, **extra},
            "context_writes": [{"namespace": "prd", "content_ref": "docs/prd.md", "summary": "PRD v1"}]}


def _handler_with(spec_fn):
    """`handler` của test_orchestrator nhưng lượt VIẾT SPEC do test quyết; ghi lại từng đầu vào nó nhận.

    ADR-0037 PR-5e: `product` chạy cả bốn pha, nên chỉ chặn đúng lượt pha `spec` sinh `approved-specs` (đầu vào
    là bản draft hoặc câu trả lời) — chặn cả agent thì lượt bóc đề bài cũng trả ra một `approved-specs`."""
    seen: list[dict] = []

    def h(system, user):
        p = _inp(user)
        if _agent_of(system) == "product" and _product_phase(system) == "spec" and p.get("kind") != "researcher":
            seen.append(p)
            return spec_fn(p, len(seen))
        return handler(system, user)
    return h, seen


def _to_spec(bus, orch):
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"}); orch.run()
    _pub(bus, "clarification-answers", "P1", "human:po", {"project_id": "P1", "answers": [{"question_id": "Q1", "answer": "a"}]})
    orch.run()


def _acts(bus):
    return [e.payload["action"] for e in bus.replay(topic="audit-log")]


# ---------- spec_runtime_gap: đơn vị ----------

def test_gap_thieu_kind_tinh_la_ung_dung_va_thieu_runtime():
    gap = spec_runtime_gap({"project_id": "P", "status": "pending_human", "artifacts": ARTIFACTS})
    assert gap is not None and "thiếu `runtime`" in gap and "library|docs" in gap


def test_gap_runtime_hong_noi_ro_hong_gi():
    gap = spec_runtime_gap({"kind": "application", "runtime": {"command": "", "port": 0}})
    assert gap is not None and "rỗng" in gap
    gap2 = spec_runtime_gap({"kind": "application", "runtime": {"command": ["x"], "port": "abc"}})
    assert gap2 is not None and "không phải số" in gap2


def test_gap_kind_la_thi_bi_tu_choi():
    gap = spec_runtime_gap({"kind": "service"})
    assert gap is not None and "'service'" in gap


def test_khong_gap_khi_library_docs_hoac_ung_dung_co_runtime():
    assert spec_runtime_gap({"kind": "library"}) is None
    assert spec_runtime_gap({"kind": "docs"}) is None
    assert spec_runtime_gap({"kind": "application", "runtime": RUNTIME}) is None
    assert spec_runtime_gap({"runtime": RUNTIME}) is None, "thiếu kind = application; có runtime là đủ"


# ---------- orchestrator: hai chiều ----------

def test_ung_dung_thieu_runtime_thi_khong_mo_gate_ma_tra_lai_spec_writer_roi_escalate():
    h, seen = _handler_with(lambda p, n: _spec(p.get("project_id", "P1"), kind="application"))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert "SPEC-P1" not in orch.gate.pending and not any(g.subject_id == "SPEC-P1" for g in orch.gate.history)
    assert not orch.deferred and not orch.plans, "không gate spec thì cũng không hoãn, không plan"
    # lần 1: trả lại spec-writer với lý do — nó nhận `hint` + `previous_spec`, chạy trên đúng event nguồn
    assert len(seen) == 1 + SPEC_RUNTIME_REWORKS
    assert "hint" not in seen[0] and "runtime" in seen[1]["hint"] and seen[1]["previous_spec"]["kind"] == "application"
    assert "requirements_draft" in seen[1], "gọi lại qua clarification-answers phải kèm draft như route gốc"
    acts = _acts(bus)
    assert acts.count("spec.runtime_missing") == 1 + SPEC_RUNTIME_REWORKS
    # lần 2 vẫn thiếu: không lặp mãi, không im lặng — escalation cấp dự án cho người quyết
    assert "spec.runtime_escalated" in acts and "P1" in orch.gate.pending
    assert orch.gate.pending["P1"].kind == "escalation" and "spec_runtime" in orch.gate.pending["P1"].checklist
    assert orch.unhandled["P1"]["agent"] == "product" and orch.spec_runtime_reworks["P1"] == 1 + SPEC_RUNTIME_REWORKS
    assert orch.gate.pending["P1"].created_by == "product"


def test_thieu_runtime_ma_luot_viet_lai_gap_transient_thi_hoan_khong_mat_luot():
    """Lượt trả spec về spec-writer gặp `TransientError`: `_act_plan` trả True nên `process()` không tự hoãn — event
    spec từng bị đánh dấu xong, không gate, không escalation, dự án đứng im. Hoãn thôi chưa đủ: bộ đếm
    `spec_runtime_reworks` (dựng lại từ audit `spec.runtime_missing`) không được ăn mất lượt sửa duy nhất vì một
    lần backend nghỉ — không thì lần thử lại đi thẳng tới escalation dù spec-writer chưa từng được sửa.
    Đo hai chiều: bỏ nhánh hoãn thì assert hoãn đỏ; hoãn mà vẫn đếm trước lời gọi thì assert escalation đỏ."""
    def spec_fn(p, n):
        if n == 2: raise TransientError("mọi backend đều đang nghỉ, thử lại sau 1515s")
        return _spec("P1", kind="application", **({"runtime": RUNTIME} if n > 2 else {}))
    h, seen = _handler_with(spec_fn)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert len(seen) == 2 and orch.deferred, "transient ở lượt viết lại phải hoãn event spec, không đánh dấu xong"
    assert "SPEC-P1" not in orch.gate.pending and "spec.runtime_missing" not in _acts(bus)
    orch.tick()
    assert len(seen) == 2, "backend đã hẹn 1515s thì nhịp kế không hỏi lại"
    for k in orch.defer_until: orch.defer_until[k] = 0.0
    orch.tick()
    assert len(seen) == 3 and "SPEC-P1" in orch.gate.pending, "backend về: viết lại xong, spec có runtime lên gate"
    acts = _acts(bus)
    assert acts.count("spec.runtime_missing") == 1 and "spec.runtime_escalated" not in acts
    assert orch.spec_runtime_reworks["P1"] == 1


def test_escalate_lan_hai_khi_gate_da_pending_khong_mo_gate_trung():
    """ticket_fsm.py 173->176: dự án đã escalate vì thiếu runtime (gate `P1` đang `pending`), một spec khác lại
    thiếu runtime lần nữa (vd. spec-writer publish tay, không qua vòng rework) → không mở gate `escalation` thứ
    hai cho cùng dự án, chỉ ghi audit + cập nhật sổ `unhandled`."""
    from company.orch.ticket_fsm import _spec_runtime_missing
    from company.orchestrator import StepResult

    h, _seen = _handler_with(lambda p, n: _spec(p.get("project_id", "P1"), kind="application"))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert "P1" in orch.gate.pending and orch.gate.pending["P1"].kind == "escalation"
    n_truoc = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request"
                  and '"subject_id": "P1"' in (e.payload.get("evidence") or ""))
    env2 = Envelope(topic="approved-specs", key="P1", actor="product",
                     payload={"project_id": "P1", "kind": "application", "status": "pending_human"})
    res = StepResult(env2.event_id, env2.topic, env2.key)
    _spec_runtime_missing(orch, env2, "P1", "thiếu `runtime` (lần nữa)", res)
    n_sau = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request"
                and '"subject_id": "P1"' in (e.payload.get("evidence") or ""))
    assert n_sau == n_truoc, "gate escalation đã pending cho P1 thì không mở lần hai"


def test_spec_writer_sua_theo_hint_thi_gate_mo_nhu_cu():
    h, seen = _handler_with(lambda p, n: _spec("P1", kind="application", **({"runtime": RUNTIME} if "hint" in p else {})))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert len(seen) == 2 and "SPEC-P1" in orch.gate.pending and "P1" not in orch.gate.pending
    assert next(iter(orch.deferred.values()))[1] == "gate:SPEC-P1"
    assert _acts(bus).count("spec.runtime_missing") == 1 and "spec.runtime_escalated" not in _acts(bus)
    assert bus.latest("approved-specs", "P1").payload["runtime"] == RUNTIME
    # duyệt thì đi tiếp bình thường: plan được lập (ADR-0037: lập xong là giao luôn, không gate plan)
    orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    assert "PLAN-P1-1" in orch.plans


def test_co_runtime_ngay_tu_dau_thi_gate_mo_khong_goi_lai():
    h, seen = _handler_with(lambda p, n: _spec("P1", kind="application", runtime=RUNTIME))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert len(seen) == 1 and "SPEC-P1" in orch.gate.pending and "spec.runtime_missing" not in _acts(bus)


def test_library_khong_runtime_van_mo_gate_nhung_phai_khai_ro():
    h, seen = _handler_with(lambda p, n: _spec("P1", kind="library"))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert len(seen) == 1 and "SPEC-P1" in orch.gate.pending and "spec.runtime_missing" not in _acts(bus)


def test_tat_ban_sua_thi_do__thieu_kind_khong_phai_mien_tru():
    """Đối chứng của chiều "mở gate": spec KHÔNG khai kind và KHÔNG có runtime là đúng hình dạng QLKH từng đi qua —
    phải bị chặn, không được coi như library."""
    h, _ = _handler_with(lambda p, n: _spec("P1"))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert "SPEC-P1" not in orch.gate.pending and "spec.runtime_missing" in _acts(bus)


def test_spec_publish_tay_khong_co_draft_thi_escalate_ngay_voi_ly_do():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    _pub(bus, "approved-specs", "P9", "product", {"project_id": "P9", "status": "pending_human", "artifacts": ARTIFACTS})
    orch.run()
    assert "SPEC-P9" not in orch.gate.pending and "P9" in orch.gate.pending
    esc = next(e for e in bus.replay(topic="audit-log") if e.payload["action"] == "spec.runtime_escalated")
    assert "không có requirements-draft" in esc.payload["evidence"] and "P9" not in orch.unhandled


def test_gate_spec_da_duyet_truoc_adr_khong_bi_cham():
    """Kiểm chỉ chạy lúc MỞ gate: dự án cũ có spec đã duyệt (không kind, không runtime) đi tiếp lập plan như trước."""
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    orch.gate.request(__import__("company.gates", fromlist=["GateRequest"]).GateRequest(
        kind="spec", subject_id="SPEC-P1", created_by="product", checklist=["prd"]))
    orch.gate.decide("SPEC-P1", "approve", by="human:po")
    _pub(bus, "approved-specs", "P1", "product", {"project_id": "P1", "status": "approved", "artifacts": ARTIFACTS})
    orch.run()
    assert "PLAN-P1-1" in orch.plans and "spec.runtime_missing" not in _acts(bus)


# ---------- người quyết escalation → chạy lại, bộ đếm về 0 ----------

def test_duyet_escalation_thi_spec_writer_chay_lai_va_duoc_them_mot_luot_sua():
    calls = {"n": 0}

    def spec_fn(p, n):
        calls["n"] = n
        return _spec("P1", kind="application", **({"runtime": RUNTIME} if n >= 4 else {}))
    h, seen = _handler_with(spec_fn)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    assert "P1" in orch.gate.pending and len(seen) == 2
    orch.gate.decide("P1", "approve", by="human:po", reason="spec-writer làm lại, ghi runtime theo README của khách")
    orch.run()
    # approve = chạy lại event nguồn (lần 3, không hint) → thiếu → bộ đếm đã về 0 nên được sửa tự động lần 4 (có hint) → đủ
    assert len(seen) == 4 and "hint" not in seen[2] and "hint" in seen[3]
    assert "SPEC-P1" in orch.gate.pending and "P1" not in orch.gate.pending
    assert "event.retried" in _acts(bus) and orch.spec_runtime_reworks["P1"] == 1


def test_tu_choi_escalation_thi_bo_su_kien_khong_lap():
    h, seen = _handler_with(lambda p, n: _spec("P1", kind="application"))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, orch)
    orch.gate.decide("P1", "reject", by="human:po", reason="dự án dừng"); orch.run()
    assert len(seen) == 2 and "event.abandoned" in _acts(bus) and "P1" not in orch.unhandled and not orch.gate.pending


# ---------- khuôn 2: state sống sót qua restart ----------

def test_bo_dem_va_unhandled_song_sot_qua_restart(tmp_path):
    h, _ = _handler_with(lambda p, n: _spec("P1", kind="application"))
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db); o = Orchestrator(bus, FakeClient(handler=h))
    _to_spec(bus, o)
    assert o.spec_runtime_reworks["P1"] == 2 and "P1" in o.unhandled
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=h))
    lech = _thuoc_tinh_lech(o, o2)
    assert not lech, " | ".join(lech)
    assert o2.spec_runtime_reworks["P1"] == 2 and o2.unhandled["P1"]["agent"] == "product"
    # sau khi người cho chạy lại, mở lại bus cũng phải thấy bộ đếm về 0
    o2.gate.decide("P1", "approve", by="human:po", reason="làm lại"); o2.run()
    o3 = Orchestrator(SQLiteBus(db), FakeClient(handler=h))
    assert o3.spec_runtime_reworks["P1"] == o2.spec_runtime_reworks["P1"]


# ---------- gate_brief: người ký thấy runtime ----------

def _brief_item(orch, subject="SPEC-P1"):
    b = GB.build(orch, subject)
    return next(it for it in b["self_check"] if it["id"] == "spec.runtime")


def test_gate_brief_spec_in_lenh_cong_health_phu_thuoc():
    h, _ = _handler_with(lambda p, n: _spec("P1", kind="application", **({"runtime": RUNTIME} if "hint" in p else {})))
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=h)); _to_spec(bus, orch)
    it = _brief_item(orch)
    assert it["verdict"] == "ok"
    facts = " | ".join(it["facts"])
    assert "kind=application" in facts and "python -m app --port {port}" in facts and "GET /health" in facts
    assert "sqlite" in facts and "trả lại vì thiếu runtime: 1 lần" in facts
    assert any(s["ref"] == "approved-specs" for s in it["sources"])


def test_gate_brief_spec_library_noi_mien_runtime_da_khai_ro():
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler)); _to_spec(bus, orch)
    it = _brief_item(orch)
    assert it["verdict"] == "ok" and any("miễn runtime" in f for f in it["facts"])


def test_gate_brief_spec_gap_khi_gate_mo_tay_cho_spec_thieu_runtime():
    """Gate mở tay (gate_cli request) cho spec thiếu runtime — hồ sơ phải nói `gap`, không im."""
    from company.gates import GateRequest
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    bus.publish(Envelope(topic="approved-specs", key="P1", actor="product",
                         payload={"project_id": "P1", "status": "pending_human", "artifacts": ARTIFACTS}))
    orch.gate.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by="human:po", checklist=["prd"]))
    it = _brief_item(orch)
    assert it["verdict"] == "gap" and any("mặc định application" in f for f in it["facts"])


def test_gate_brief_spec_chua_co_spec_thi_unknown():
    from company.gates import GateRequest
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    orch.gate.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by="human:po", checklist=["prd"]))
    assert _brief_item(orch)["verdict"] == "unknown"
