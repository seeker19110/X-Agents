"""Mỗi trường của `OrchState` phải có đường dựng lại từ bus — và test phải BIẾT trường mới xuất hiện.

Khuôn lỗi đã gặp nhiều lần khi chạy thật: thêm một biến trạng thái vào `Orchestrator.__init__`, quên dòng
tương ứng trong `rehydrate.py`, và sau restart hệ thống im lặng quên mất một phần việc — `status` vẫn xanh.
Test bất biến cũ (`test_moi_trang_thai_nghiep_vu_song_sot_qua_restart`) chỉ bắt được cái nó ĐI QUA: nó chạy
một vòng đời và so hai bản, nên trường nào kịch bản không chạm thì rỗng ở cả hai bên và lọt.

Ở đây đi hướng ngược lại: duyệt `fields(OrchState)` (ADR-0034). Mỗi trường phải khai trong `SEED` cách gieo
dữ liệu vào bus, và sau khi mở lại orchestrator trường đó phải KHÁC RỖNG. Trường chỉ sống trong phiên khai
`RAM_ONLY` trong metadata và được miễn — nhưng vẫn phải khai, nên thêm trường mà không nghĩ đến khôi phục là
CI đỏ ngay tại `test_moi_truong_deu_khai_nguon_dung_lai`.
"""
from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from company.events import Envelope
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.llm import FakeClient
from company.orch.routes import ACTOR
from company.orch.state import RAM_ONLY, OrchState
from company.orchestrator import Orchestrator
from company.roles import ROLE
from company.sqlite_bus import SQLiteBus

E1 = "e1111111111111111111111111111111"


def _audit(bus, action, evidence, actor=ACTOR):
    bus.publish(Envelope(topic="audit-log", key=actor, actor=actor,
                         payload={"actor": actor, "action": action, "evidence": json.dumps(evidence)}))


def _quyet_da_xu_ly(bus):
    # Gate thật rồi chữ ký thật: `gate.decide` không đóng gate nào thì không phải một quyết định (O4, 2026-10-02).
    gate = PersistentGate(bus)
    gate.request(GateRequest(kind="escalation", subject_id="T1", checklist=["c"], created_by=ROLE.SUPERVISOR))
    gate.decide("T1", "approve", by="human:lead", reason="đã xem root cause, cho chạy lại")
    env = next(e for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.decide")
    _audit(bus, "orchestrated", {"event_id": env.event_id, "topic": "audit-log", "actions": []})


def _viec(bus, event_id=E1):
    """Một event actionable chưa `orchestrated` → nó phải nằm trong hàng đợi sau khi mở lại."""
    bus.publish(Envelope(topic="research-requests", key="P1", actor="human", event_id=event_id,
                         payload={"project_id": "P1", "description": "x"}))


def _hen(bus):
    _viec(bus)
    _audit(bus, "defer.until", {"event_id": E1, "until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                                "reason": "transient:quota"})


def _repo_that(tmp_path, ten):
    p = tmp_path / ten
    (p / ".git").mkdir(parents=True)
    return p


# Trường → cách gieo dữ liệu vào bus. Giá trị là hàm nhận (bus, tmp_path).
SEED = {
    "processed": lambda bus, tmp: _audit(bus, "orchestrated", {"event_id": E1}),
    "queue": lambda bus, tmp: _viec(bus),
    "partial": lambda bus, tmp: bus.publish(Envelope(topic="approved-specs", key="P1", actor="product",
                                                     causation_id=E1,
                                                     payload={"project_id": "P1", "status": "approved",
                                                              "artifacts": {"prd": "prd.md", "requirements": "req.md"}})),
    "deferred": lambda bus, tmp: _hen(bus),
    "defer_until": lambda bus, tmp: _hen(bus),
    "once": lambda bus, tmp: _audit(bus, "once", {"key": "gate.remind:PLAN-1"}),
    # ADR-0037: `plan.proposed` vừa dựng `plans` vừa giao lại ticket, nên seed phải mang khoá `tickets`
    "plans": lambda bus, tmp: _audit(bus, "plan.proposed", {"plan_id": "PLAN-P1-1", "project_id": "P1", "tickets": []}),
    "integrated": lambda bus, tmp: _audit(bus, "integration.merged", {"ticket_id": "T1"}),
    "conflict_retries": lambda bus, tmp: _audit(bus, "integration.conflict", {"ticket_id": "T1"}),
    "turn_continuations": lambda bus, tmp: _audit(bus, "ticket.continued", {"ticket_id": "T1", "attempt": 1}),
    "missing_threat_model": lambda bus, tmp: _audit(bus, "threat_model.missing", {"subject_id": "P1"}),
    "spec_runtime_reworks": lambda bus, tmp: _audit(bus, "spec.runtime_missing", {"project_id": "P1"}),
    "plan_reworks": lambda bus, tmp: _audit(bus, "plan.rework", {"project_id": "P1", "source_event": E1, "attempt": 1}),
    "release_sha": lambda bus, tmp: _audit(bus, "release.staged", {"release_id": "REL-1", "sha": "a" * 40}),
    "delivered": lambda bus, tmp: _audit(bus, "delivery.done", {"release_id": "REL-1", "version": "0.1.0"}),
    "void_releases": lambda bus, tmp: _audit(bus, "release.void", {"release_id": "REL-1"}),
    # ADR gốc 0021: chỉ NGƯỜI ghim được profile — bus chặn agent, replay kiểm lại actor
    "quality_profiles": lambda bus, tmp: _audit(bus, "quality.profile_set",
                                                {"project_id": "P1", "run_id": "run-P1", "profile_sha256": "a" * 64,
                                                 "contract_hash": "b" * 64, "by": "human:po"}, actor="human:po"),
    "stalled": lambda bus, tmp: _audit(bus, "project.stalled", {"project_id": "P1", "event_id": E1,
                                                                "agent": "builder", "topic": "tasks"}),
    "stall_count": lambda bus, tmp: _audit(bus, "project.stalled", {"project_id": "P1", "event_id": E1,
                                                                    "agent": "builder", "topic": "tasks"}),
    "unhandled": lambda bus, tmp: _audit(bus, "agent_error_unhandled", {"subject": "P1", "event_id": E1,
                                                                        "agent": "builder", "topic": "tasks"}),
    # chỉ quyết định ĐÃ xử lý (`orchestrated`) mới được đếm lại — decide còn trong hàng đợi do `_on_gate_decide` đếm
    "escalation_decided": lambda bus, tmp: _quyet_da_xu_ly(bus),
    "debt_gate": lambda bus, tmp: _audit(bus, "debt.escalated", {"project_id": "P1", "n": 3}),
    "paused": lambda bus, tmp: bus.publish(Envelope(topic="supervisor-actions", key="T1", actor="supervisor",
                                                    payload={"action": "pause", "target": "T1", "reason": "x"})),
    "project_repos": lambda bus, tmp: bus.publish(
        Envelope(topic="research-requests", key="P1", actor="human",
                 payload={"project_id": "P1", "description": "x",
                          "repo": str(_repo_that(tmp, "kho-tot"))})),
    "bad_repos": lambda bus, tmp: bus.publish(
        Envelope(topic="research-requests", key="P2", actor="human",
                 payload={"project_id": "P2", "description": "x",
                          "repo": str(tmp / "khong-phai-git")})),
}

_CAN_DUNG_LAI = [f.name for f in fields(OrchState) if f.metadata["rehydrate"] != RAM_ONLY]


def test_moi_truong_deu_khai_nguon_dung_lai():
    """Trường mới của `OrchState` phải khai `metadata['rehydrate']` VÀ có mục trong `SEED`.

    Đây là chốt chặn thật của file này: nó đỏ ngay khi ai đó thêm trạng thái mà chưa nghĩ đến restart, thay
    vì để một dự án chạy thật phát hiện hộ vài ngày sau."""
    thieu_metadata = [f.name for f in fields(OrchState) if "rehydrate" not in f.metadata]
    assert not thieu_metadata, f"trường thiếu metadata['rehydrate']: {thieu_metadata}"
    thieu_seed = [ten for ten in _CAN_DUNG_LAI if ten not in SEED]
    assert not thieu_seed, (
        f"trường khai dựng lại từ bus nhưng chưa có kịch bản gieo trong SEED: {thieu_seed} — "
        "thêm mục vào SEED (và dòng tương ứng trong orch/rehydrate.py) thay vì bỏ qua")
    thua = [ten for ten in SEED if ten not in _CAN_DUNG_LAI]
    assert not thua, f"SEED có trường không còn trong OrchState hoặc đã thành RAM_ONLY: {thua}"


@pytest.mark.parametrize("ten", _CAN_DUNG_LAI)
def test_truong_song_sot_qua_restart(ten, tmp_path):
    """Gieo đúng dấu vết của một trường vào bus, mở orchestrator mới, trường đó phải khác rỗng.

    Bỏ dòng khôi phục của bất kỳ trường nào trong `orch/rehydrate.py` → đúng một ca ở đây đỏ, và tên ca chỉ
    thẳng trường bị mất."""
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    SEED[ten](bus, tmp_path)

    o = Orchestrator(SQLiteBus(db), FakeClient())
    assert getattr(o, ten), f"`{ten}` rỗng sau khi mở lại bus — thiếu đường khôi phục trong orch/rehydrate.py"


def test_bi_danh_ghi_xuyen_xuong_state():
    """`o.processed` là property hai chiều, không phải bản sao: ghi qua bí danh phải thấy ở `o.state`.

    Nếu `install_aliases` chỉ có getter thì mọi `o.processed.add(...)` vẫn chạy (mutate tại chỗ) nhưng
    `o.queue = [...]`/`o.partial = {...}` trong `rehydrate` lại tạo thuộc tính instance che mất property —
    trạng thái tách làm hai bản, im lặng."""
    o = Orchestrator(SQLiteBus(":memory:"), FakeClient())
    o.processed = {"x"}
    assert o.state.processed == {"x"}
    o.state.reload_on_change = True
    assert o.reload_on_change is True
