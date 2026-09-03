"""Hai lỗi thật đã tái hiện được:

1. `Completion.json()` cắt nhầm ở code fence NẰM GIỮA JSON (research findings có trích đoạn config bọc ```),
   làm đầu ra hợp lệ của model bị chặt cụt.
2. `pull-requests` schema bắt `local_checks.verified_by` phải là "workspace" nếu có mặt, nên agent trung thực
   khai `null` (không chạy được lint/test) bị bus từ chối — phạt đúng hành vi mình muốn.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from company.bus import BusError, InMemoryBus
from company.events import Envelope
from company.llm import Completion, LLMError
from company.supervisor import Supervisor

RECORDINGS = Path(__file__).resolve().parents[1] / "evals" / "recordings"


def _c(text: str) -> Completion:
    return Completion(text=text, input_tokens=0, output_tokens=0, model="m")


@pytest.mark.parametrize("text", [
    '{"a": 1}',                                   # không fence
    '```{"a": 1}```',                             # fence một dòng, không xuống dòng
    '```json\n{"a": 1}\n```',                     # fence có ngôn ngữ
    '```\n{"a": 1}\n```   \n\n',                  # khoảng trắng thừa sau fence đóng
    '```json {"a": 1}```',                        # fence một dòng có ngôn ngữ
    '```json\n{"a": 1}',                          # thiếu fence đóng
])
def test_strip_fence_giu_moi_dang_boc(text):
    assert _c(text).json() == {"a": 1}


def test_fence_ben_trong_chuoi_khong_bi_cat():
    """Fence nằm trong giá trị chuỗi là nội dung thật, không phải fence đóng."""
    inner = "cấu hình:\\n```yaml\\nkey: value\\n```\\nhết"
    text = '```json\n{"note": "' + inner + '", "cuoi": true}\n```'
    assert _c(text).json()["cuoi"] is True


def test_recording_researcher_that_parse_duoc():
    """Đầu ra researcher ĐÃ GHI LẠI (8 lần xuất hiện ```) từng làm json() ném lỗi; giờ phải parse được."""
    cases = json.loads(RECORDINGS.joinpath("researcher.json").read_text(encoding="utf-8"))["cases"]
    text = next(iter(cases.values()))["text"]
    assert text.count("```") > 2, "recording này phải còn fence bên trong thì test mới có nghĩa"
    assert isinstance(_c(text).json(), dict)


def test_loi_json_chi_trich_doan_quanh_vi_tri_loi():
    with pytest.raises(LLMError) as e:
        _c('{"a": 1, "b": ' + "x" * 2000).json()
    assert "gần vị trí lỗi" in str(e.value) and len(str(e.value)) < 600


# ---------- verified_by ----------

def _pr(verified_by: object) -> Envelope:
    return Envelope(topic="pull-requests", key="T1", actor="data", payload={
        "ticket_id": "T1", "branch": "b", "pr_ref": "abc1234", "summary": "s",
        "local_checks": {"lint": False, "tests": False, "verified_by": verified_by}})


def test_verified_by_null_hop_le_va_workspace_hop_le():
    bus = InMemoryBus(enforce_owners=False)
    bus.validate("pull-requests", _pr(None).payload)
    bus.validate("pull-requests", _pr("workspace").payload)


def test_verified_by_gia_bi_tu_choi():
    bus = InMemoryBus(enforce_owners=False)
    with pytest.raises(BusError):
        bus.validate("pull-requests", _pr("tôi tự thấy ổn").payload)


def test_supervisor_tinh_null_la_chua_xac_minh():
    bus = InMemoryBus(enforce_owners=False)
    sup = Supervisor(bus)
    bus.publish(_pr(None))
    bus.publish(Envelope(topic="pull-requests", key="T2", actor="backend", payload={
        "ticket_id": "T2", "branch": "b2", "pr_ref": "def5678", "summary": "s",
        "local_checks": {"lint": True, "tests": True, "verified_by": "workspace"}}))
    r = sup.sprint_report()
    assert r["prs"] == 2 and r["prs_unverified"] == 1
