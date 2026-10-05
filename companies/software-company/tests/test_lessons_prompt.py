"""Prompt supervisor mô tả đúng thời điểm và đường đọc bài học của ADR-0004."""

from pathlib import Path


def test_supervisor_prompt_noi_bai_hoc_co_ngay_sau_merge_va_loc_nam_ban():
    source = Path(__file__).resolve().parents[1] / "agents" / "supervisor" / "supervisor.md"
    prompt = source.read_text(encoding="utf-8")
    assert "ngay sau khi merge" in prompt
    assert "tối đa 5 bài học" in prompt
    assert "Supervisor.lessons_for(ticket)" in prompt
