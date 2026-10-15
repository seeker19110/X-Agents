"""Lời người duyệt (`hint`, `human_hint`) đi vào prompt nguyên vẹn khi runner phải tỉa payload cho vừa hạn mức.

Hub thật 2026-10-15 (QLKH-DD-CSV): sau #513 lý do reject gate spec (~3.000 ký tự) tới `payload.hint` đủ, nhưng
payload product ~47k bị `fit` tỉa 4–5k và `trim_payload` cắt chuỗi DÀI NHẤT trước — chính là hint. PRD v5.3 và v8
tự ghi "hint bị cắt ~2.900 ký tự ở giữa", chỉ sửa mục đầu và mục cuối. Runner truyền `protect` để hint chỉ bị cắt
khi không còn chuỗi nào khác.
"""

from __future__ import annotations

import json

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.runner import PROTECTED_PAYLOAD_KEYS, AgentRunner
from test_adr0012 import REVIEW, _pr_env

DUOI = "ĐUÔI-HINT-(f)"


def _chay(**extra):
    bus = InMemoryBus()
    client = FakeClient(responses=[REVIEW])
    runner = AgentRunner(bus, client, max_input_chars=200_000)
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
    assert {"hint", "human_hint"} <= PROTECTED_PAYLOAD_KEYS
