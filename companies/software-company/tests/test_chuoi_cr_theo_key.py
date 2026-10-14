"""Chuỗi nghiên cứu của một change request được khoá bằng MÃ CR, không phải `project_id` — mọi tra cứu trong chuỗi phải
đi theo key của chuỗi.

Hub thật 2026-10-14 (QLKH-DD-CSV), CR-DDCSV-INFRA-002 (đổi requirement → intake → research → draft → câu hỏi làm rõ):
route giữ key của event nguồn, nên `research-findings`/`requirements-draft`/`clarification-questions` của CR mang
key `CR-DDCSV-INFRA-002` còn `payload.project_id` là `QLKH-DD-CSV`. Các tra cứu lại dùng `project_id or key`:

- `_with_intake` đính kèm intake CŨ của cả dự án (2026-10-12) — product ghi "đề nghị orchestrator đính kèm intake gốc
  của CR-DDCSV-INFRA-002";
- `enforce_round` đếm câu hỏi theo dự án → câu hỏi ĐẦU TIÊN của CR bị ghi `round: 2` (= vòng cuối, không được hỏi lại);
- `_answers_complete`/`_with_draft` đối chiếu với câu hỏi/bản nháp cũ của dự án → trả lời CR sẽ viết spec từ bản nháp
  10-12 của cả dự án.

Luật: tra cứu trong chuỗi nghiên cứu theo `key` của event (với dự án thường, key = project_id nên không đổi gì).
"""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orch.clarify_round import enforce_round
from company.orch.enrich import _with_draft, _with_intake
from company.orch.guards import _answers_complete, pending_clarifications
from company.orch.routes import ROUTES
from company.orchestrator import Orchestrator
from test_orchestrator import _pub, handler

CR = "CR-9"


def _q(qid: str) -> dict:
    return {"id": qid, "req_id": "R1", "text": f"câu {qid}?", "options": ["a", "b"], "default": "a"}


def _chuoi() -> tuple[InMemoryBus, Orchestrator]:
    bus = InMemoryBus()
    o = Orchestrator(bus, FakeClient(handler=handler))
    # chuỗi của DỰ ÁN (cũ, đã trả lời xong)
    _pub(
        bus,
        "research-findings",
        "P1",
        "product",
        {"project_id": "P1", "kind": "intake", "data": {"de_bai": "intake dự án"}},
    )
    _pub(bus, "requirements-draft", "P1", "product", {"project_id": "P1", "kind": "draft", "summary": "draft dự án", "risks": []})
    _pub(bus, "clarification-questions", "P1", "product", {"project_id": "P1", "round": 1, "questions": [_q("Q1")]})
    _pub(
        bus,
        "clarification-answers",
        "P1",
        "human:po",
        {"project_id": "P1", "answers": [{"question_id": "Q1", "answer": "a"}]},
    )
    # chuỗi của CR: key = mã CR, payload.project_id = dự án
    _pub(
        bus, "research-findings", CR, "product", {"project_id": "P1", "kind": "intake", "data": {"de_bai": "intake CR"}}
    )
    _pub(bus, "requirements-draft", CR, "product", {"project_id": "P1", "kind": "draft", "summary": "draft CR", "risks": []})
    return bus, o


def test_with_intake_va_with_draft_lay_cua_chuoi_cr():
    bus, o = _chuoi()
    rf = bus.latest("research-findings", CR)
    assert _with_intake(rf, o)["intake"] == {"de_bai": "intake CR"}
    ans = _pub(bus, "clarification-answers", CR, "reviewer:phien-chinh", {"project_id": "P1", "answers": []})
    assert _with_draft(ans, o)["requirements_draft"]["summary"] == "draft CR"


def test_cau_hoi_dau_tien_cua_cr_la_vong_1():
    bus, o = _chuoi()
    r = next(x for x in ROUTES if x.topic_out == "clarification-questions")
    draft = bus.latest("requirements-draft", CR)
    p = enforce_round(o, r, {"project_id": "P1", "round": 1, "questions": [_q("CQ-1")]}, draft, "product")
    assert p["round"] == 1, "dự án đã hỏi một vòng không làm CR mất vòng hỏi lại"


def test_tra_loi_cua_cr_doi_chieu_cau_hoi_cua_cr():
    bus, o = _chuoi()
    _pub(bus, "clarification-questions", CR, "product", {"project_id": "P1", "round": 1, "questions": [_q("CQ-1")]})
    assert pending_clarifications(bus)[CR]["unanswered"] == ["CQ-1"], "CR đang chờ trả lời, theo key của chuỗi"
    thieu = _pub(bus, "clarification-answers", CR, "human:po", {"project_id": "P1", "answers": []})
    assert not _answers_complete(thieu, o), "câu hỏi của CR chưa ai trả lời — không được viết spec"
    du = _pub(
        bus,
        "clarification-answers",
        CR,
        "human:po",
        {"project_id": "P1", "answers": [{"question_id": "CQ-1", "answer": "a"}]},
    )
    assert _answers_complete(du, o) and CR not in pending_clarifications(bus)
