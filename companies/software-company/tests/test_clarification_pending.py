"""Câu hỏi làm rõ đang chờ người phải HIỆN ra ở `status`, không được im lặng.

Đo được 2026-09-22 (CAMPUS-UNI-20260922): `product` đăng `clarification-questions` vòng 1 lúc 13:11 UTC, chưa có
`clarification-answers`. `status` trả `warnings: []`, `gates_pending: {}`, `waiting: {}` — xanh vì rỗng, đúng khuôn
"chế độ hỏng không tự khai báo" (`TRAPS.md`). Lý do: `_deadlock_warnings` thoát sớm khi chưa có ticket, nên mọi
kẹt ở pha intake/research/spec đều vô hình; và không trường nào của `status()` đọc `clarification-questions`.

Tính từ bus, không từ RAM (khuôn 2): mở lại tiến trình vẫn phải thấy."""

from __future__ import annotations

import json

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _pub, handler

_Q = [
    {"id": "Q-01", "req_id": "FR-1", "text": "A hay B?", "options": ["A", "B"], "default": "A"},
    {"id": "Q-02", "req_id": "FR-2", "text": "Có cần SSO không?", "options": ["có", "không"], "default": "không"},
]


def _orch():
    bus = InMemoryBus()
    return bus, Orchestrator(bus, FakeClient(handler=handler))


def _hoi(bus, pid="P1", round_=1, questions=_Q, orch=None):
    e = _pub(
        bus, "clarification-questions", pid, "product", {"project_id": pid, "round": round_, "questions": questions}
    )
    if orch is not None:
        orch.run()  # như chạy thật: event không actionable được đánh dấu, `queue` về 0
    return e


def test_status_bao_cau_hoi_lam_ro_dang_cho_nguoi():
    bus, orch = _orch()
    assert orch.status()["clarifications_pending"] == {}
    _hoi(bus, orch=orch)
    st = orch.status()
    assert st["tickets"] == {}, "kịch bản phải là pha TRƯỚC ticket — đúng vùng mù đã đo"
    p = st["clarifications_pending"]
    assert set(p) == {"P1"} and p["P1"]["round"] == 1 and p["P1"]["unanswered"] == ["Q-01", "Q-02"]
    assert p["P1"]["since"], "phải mang thời điểm hỏi để console tính giờ chờ"
    assert st["warnings"] and "P1" in st["warnings"][0] and "cau hoi lam ro" in st["warnings"][0], (
        f"chờ người mà không gate nào hỏi ai thì phải kêu, nhận được: {st['warnings']}"
    )


def test_tra_loi_du_thi_het_cho_tra_loi_thieu_thi_con_cho_dung_cau():
    bus, orch = _orch()
    _hoi(bus)
    _pub(
        bus,
        "clarification-answers",
        "P1",
        "human:owner",
        {"project_id": "P1", "answers": [{"question_id": "Q-01", "answer": "A"}]},
    )
    p = orch.status()["clarifications_pending"]
    assert p["P1"]["unanswered"] == ["Q-02"], "câu trả lời TÍCH LUỸ trong vòng, chỉ còn câu thiếu"
    _pub(
        bus,
        "clarification-answers",
        "P1",
        "human:owner",
        {"project_id": "P1", "answers": [{"question_id": "Q-02", "answer": "không"}]},
    )
    st = orch.status()
    assert st["clarifications_pending"] == {} and st["warnings"] == []


def test_cau_tra_loi_vong_truoc_khong_thoa_man_vong_sau():
    """id câu hỏi có thể trùng giữa hai vòng; câu trả lời cũ (trước `q.ts`) không được tính cho vòng mới."""
    bus, orch = _orch()
    _hoi(bus, round_=1, questions=_Q[:1])
    _pub(
        bus,
        "clarification-answers",
        "P1",
        "human:owner",
        {"project_id": "P1", "answers": [{"question_id": "Q-01", "answer": "A"}]},
    )
    assert orch.status()["clarifications_pending"] == {}
    _hoi(bus, round_=2, questions=_Q[:1])
    p = orch.status()["clarifications_pending"]
    assert p["P1"]["round"] == 2 and p["P1"]["unanswered"] == ["Q-01"]


def test_khong_keu_khi_con_viec_dang_chay():
    """Cảnh báo bế tắc chỉ khi KHÔNG còn gì chạy được: hàng đợi còn event thì chỉ liệt kê, không kêu."""
    bus, orch = _orch()
    _hoi(bus, orch=orch)
    _pub(bus, "research-requests", "P2", "human:sales", {"project_id": "P2", "description": "làm web bán hàng"})
    orch.queue.extend(e for e in bus.replay(topic="research-requests"))
    st = orch.status()
    assert set(st["clarifications_pending"]) == {"P1"} and st["warnings"] == []


def test_vong_cuoi_da_tra_loi_mot_phan_thi_khong_con_cho():
    """Vòng cuối (`MAX_CLARIFY_ROUNDS`): `_spec_ready` cho đi tiếp ngay khi có BẤT KỲ câu trả lời nào (không hỏi
    thêm được nữa), nên dự án không còn "chờ người" dù vẫn thiếu câu — báo chờ ở đây là báo sai."""
    bus, orch = _orch()
    _hoi(bus, round_=2, orch=orch)
    assert set(orch.status()["clarifications_pending"]) == {"P1"}, "vòng cuối mà CHƯA ai trả lời thì vẫn chờ"
    _pub(bus, "clarification-answers", "P1", "human:owner",
         {"project_id": "P1", "answers": [{"question_id": "Q-01", "answer": "A"}]})
    assert orch.status()["clarifications_pending"] == {}


def _product_khai_vong(vong: int):
    """FakeClient như `handler`, nhưng lượt hỏi của `product` khai `round` cố định — mô phỏng model khai sai."""

    def h(system: str, user: str) -> dict:
        out = handler(system, user)
        return {**out, "round": vong} if "questions" in out and "round" in out else out

    return h


def _vong_da_hoi(bus, pid="P1"):
    return [e.payload["round"] for e in bus.replay(topic="clarification-questions", key=pid)]


def test_vong_hoi_dau_tien_la_1_du_model_khai_2():
    """Đo 2026-10-12 (QLKH-DD-CSV, model thật): lần hỏi ĐẦU TIÊN, `product` khai `round: 2` và ghi "(Hỏi lại)".
    `round` quyết `_answers_incomplete` có cho hỏi tiếp không (`>= MAX_CLARIFY_ROUNDS` là hết) — model khai vòng
    cuối là lặng lẽ xoá vòng hỏi lại. Vòng là identity của lượt (đếm trên bus), code điền như `source` của review."""
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_product_khai_vong(2)))
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    assert _vong_da_hoi(bus) == [1]
    vet = [json.loads(a.payload["evidence"]) for a in bus.replay(topic="audit-log")
           if a.payload.get("action") == "clarification.round_overridden"]
    assert vet and vet[0]["claimed_round"] == 2 and vet[0]["round"] == 1, "khai sai phải để lại vết"


def test_tra_loi_thieu_thi_vong_sau_la_2_du_model_khai_1():
    """Chiều ngược lại: model khai `round: 1` mãi thì `_answers_incomplete` không bao giờ thấy vòng cuối — trả lời
    thiếu là hỏi lại vô hạn. Vòng đếm từ bus thì lần hỏi lại là 2, và trả lời thiếu lần nữa đi thẳng tới spec."""
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=_product_khai_vong(1)))
    _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app đặt lịch"})
    orch.run()
    tra_loi_lac = {"project_id": "P1", "answers": [{"question_id": "Q-KHAC", "answer": "x"}]}
    _pub(bus, "clarification-answers", "P1", "human:po", tra_loi_lac)
    orch.run()
    assert _vong_da_hoi(bus) == [1, 2]
    _pub(bus, "clarification-answers", "P1", "human:po", tra_loi_lac)
    orch.run()
    assert _vong_da_hoi(bus) == [1, 2], "vòng cuối rồi: không hỏi thêm"
    assert "SPEC-P1" in orch.gate.pending

