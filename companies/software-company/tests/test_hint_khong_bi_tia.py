"""Lời người duyệt (`hint`, `human_hint`) đi vào prompt nguyên vẹn khi runner phải tỉa payload cho vừa hạn mức.

Hub thật 2026-10-15 (QLKH-DD-CSV): sau #513 lý do reject gate spec (~3.000 ký tự) tới `payload.hint` đủ, nhưng
payload product ~47k bị `fit` tỉa 4–5k và `trim_payload` cắt chuỗi DÀI NHẤT trước — chính là hint. PRD v5.3 và v8
tự ghi "hint bị cắt ~2.900 ký tự ở giữa", chỉ sửa mục đầu và mục cuối. Runner truyền `protect` để hint chỉ bị cắt
khi không còn chuỗi nào khác.
"""

from __future__ import annotations

import json

from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.llm import FakeClient
from company.runner import PROTECTED_PAYLOAD_KEYS, AgentRunner
from test_adr0012 import REVIEW, _pr_env

DUOI = "ĐUÔI-HINT-(f)"


def _chay(prd: str | None = None, **extra):
    bus = InMemoryBus()
    client = FakeClient(responses=[REVIEW])
    bb = None
    if prd is not None:
        bb = Blackboard(bus)
        bb.write("product", "prd", "docs/prd.md", "PRD", content=prd)
    runner = AgentRunner(bus, client, max_input_chars=200_000, blackboard=bb)
    spec = runner.agents["qa"]
    spec.max_input_chars = len(spec.system_prompt(None)) + 1_500 + 30_000
    runner.run("qa", _pr_env(**extra), "review-results")
    return bus, client


def test_hint_dai_nhat_van_toi_prompt_nguyen_ven():
    hint = "(a) " + "h" * 7_000 + " " + DUOI
    bus, client = _chay(hint=hint, **{f"ghi_chu_{i}": "n" * 5_000 for i in range(10)})
    rep = json.loads(
        next(e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "context_trimmed")
    )
    assert rep["trimmed_payload"] > 10_000, "payload thật sự bị tỉa"
    assert DUOI in client.calls[0]["user"] and "h" * 7_000 in client.calls[0]["user"], "hint không bị cắt giữa"


def test_khoa_duoc_bao_ve():
    assert {"hint", "human_hint", "answers"} <= PROTECTED_PAYLOAD_KEYS


def test_hint_va_dap_an_nguyen_ven_khi_phan_con_lai_la_chuoi_ngan():
    """Hub thật 2026-10-15 (sau #514): `requirements_draft` 52k ký tự gồm 604 chuỗi ngắn không cắt được; hết chuỗi
    thường để cắt thì vòng lặp quay sang cắt hint (−2.491) và đáp án làm rõ (−522/−479/−108) dù `room` còn chỗ."""
    hint = "(a) " + "h" * 3_000 + " " + DUOI
    answers = [{"question_id": f"Q-{i}", "answer": f"đáp án {i} " + "a" * 900 + f" HẾT-{i}"} for i in range(3)]
    draft = {"requirements": [{"id": f"R-{i:03d}", "text": "t" * 300} for i in range(60)]}  # ~20k chuỗi ngắn
    # room 30k: payload ~27k vượt phần chia mềm (0.6·room, vì blackboard có PRD 60k) nhưng chưa vượt room
    _bus, client = _chay(prd="p" * 60_000, hint=hint, answers=answers, requirements_draft=draft)
    user = client.calls[0]["user"]
    assert DUOI in user and "h" * 3_000 in user, "hint nguyên vẹn"
    assert all(f"đáp án {i} " + "a" * 900 + f" HẾT-{i}" in user for i in range(3)), "đáp án của khách nguyên vẹn"


def test_chu_ky_gate_spec_nguyen_ven_khi_tia_payload():
    """Chữ ký gate spec (`spec_gate_decision`, lý do của chủ dự án ~2k ký tự) đi vào lượt threat model trên một
    payload `approved-specs` ~36k (hub thật SPEC-CR-DDCSV-DPIA-004): là LỜI NGƯỜI, không được bị tỉa giữa."""
    ly_do = "root_cause: " + "r" * 7_000 + " " + DUOI
    gd = {"subject_id": "SPEC-P1", "decision": "approve", "by": "human:po", "reason": ly_do, "verified_by": "orchestrator"}
    _bus, client = _chay(spec_gate_decision=gd, **{f"ghi_chu_{i}": "n" * 5_000 for i in range(10)})
    assert DUOI in client.calls[0]["user"] and "r" * 7_000 in client.calls[0]["user"], "lý do ký không bị cắt giữa"
