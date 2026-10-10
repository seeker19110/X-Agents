"""BT4 — `triage.py`: `maintenance-signals` → `maintenance-tickets`, chống trùng theo DANH TÍNH EVENT.

Ca cốt lõi (bug `once=` K1.7): cùng những envelope đó phát lại → không ticket mới; một envelope MỚI (dù cùng
`(kind, subject)`) → được phép ra ticket thứ hai.
"""
from datetime import UTC, datetime

import pytest

from keeper.events import Signal
from keeper.triage import (
    DUE_DAYS,
    ObservedSignal,
    TriageState,
    legacy_generation_key,
    triager,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _sig(subject="pydantic", **kw) -> Signal:
    kw.setdefault("kind", "dependency")
    kw.setdefault("detail", "Bump pydantic from 1.9.0 to 2.0.0")
    return Signal(subject=subject, **kw)


def _obs(event_id: str, subject="pydantic", **kw) -> ObservedSignal:
    return ObservedSignal(event_id, _sig(subject, **kw))


def test_mot_signal_thanh_mot_ticket():
    tickets = triager([_obs("e1", semver_jump="minor")], state=TriageState(), now=NOW)
    assert len(tickets) == 1
    t = tickets[0]
    assert t.subject == "pydantic"
    assert t.signal_subjects == ["pydantic"]
    assert t.signal_event_ids == ["e1"]
    assert t.status == "open"


def test_ticket_id_mang_danh_tinh_event():
    t = triager([_obs("e1", semver_jump="minor")], state=TriageState(), now=NOW)[0]
    assert t.ticket_id == "KEEP:e1"


def test_tier_high_dinh_kem_yeu_cau_gate():
    t = triager([_obs("e1", semver_jump="major")], state=TriageState(), now=NOW)[0]
    assert t.risk_tier == "high"
    assert t.requires_gate is True


def test_tier_khong_high_thi_khong_gate():
    t = triager([_obs("e1", semver_jump="patch", is_dev=True)], state=TriageState(), now=NOW)[0]
    assert t.risk_tier == "low"
    assert t.requires_gate is False


def test_due_at_theo_tier():
    t = triager([_obs("e1", semver_jump="major")], state=TriageState(), now=NOW)[0]
    assert t.due_at == "2026-09-10T00:00:00+00:00"
    assert DUE_DAYS["high"] == 1


def test_gop_trung_truoc_khi_ra_ticket():
    """Hai envelope KHÁC nhau, cùng `(kind, subject)`, cùng một lô → một ticket, tiêu thụ cả hai event."""
    tickets = triager([_obs("e1", semver_jump="minor"), _obs("e2", semver_jump="minor")],
                      state=TriageState(), now=NOW)
    assert len(tickets) == 1
    assert tickets[0].signal_event_ids == ["e1", "e2"]
    assert tickets[0].ticket_id == "KEEP:e2", "id lấy từ envelope MỚI NHẤT của nhóm"


def test_phat_lai_cung_envelope_khong_ra_ticket_lan_hai():
    state = TriageState()
    lo = [_obs("e1", semver_jump="minor")]
    first = triager(lo, state=state, now=NOW)
    second = triager(lo, state=state, now=NOW)
    assert len(first) == 1
    assert second == []


def test_envelope_moi_cung_kind_subject_duoc_phep_lan_hai():
    """Chiều ngược của ca trên: cùng nội dung signal, chỉ đổi DANH TÍNH event → ticket thứ hai được ra."""
    state = TriageState()
    first = triager([_obs("e1", semver_jump="minor")], state=state, now=NOW)
    second = triager([_obs("e2", semver_jump="minor")], state=state, now=NOW)
    assert len(first) == len(second) == 1
    assert first[0].ticket_id != second[0].ticket_id


def test_ticket_id_hop_le_voi_ID_PATTERN():
    t = triager([_obs("abc123", subject="xagents-core/src/xagents_core/supervisor.py", kind="drift",
                      detail="lệch")], state=TriageState(), now=NOW)[0]
    assert t.ticket_id == "KEEP:abc123"
    assert " " not in t.ticket_id


def test_nhieu_signal_ra_nhieu_ticket_giu_thu_tu():
    lo = [_obs("e1", "a", kind="drift", detail="x"), _obs("e2", "b", kind="drift", detail="y")]
    assert [t.subject for t in triager(lo, state=TriageState(), now=NOW)] == ["a", "b"]


def test_seen_count_cong_don_khi_gop():
    lo = [_obs("e1", semver_jump="minor"), _obs("e2", semver_jump="minor")]
    (t,) = triager(lo, state=TriageState(), now=NOW)
    assert t.signal_subjects == ["pydantic"] and len(t.signal_event_ids) == 2


def test_truc_cu_theo_kind_subject_nuot_signal_moi():
    """Chiều ngược của `test_envelope_moi_cung_kind_subject_duoc_phep_lan_hai`: ĐỔI đúng một biến — trục
    chống-trùng — về bản BT4 (`<thế hệ>:<kind>:<subject>`, thế hệ vĩnh viễn 0 vì không mã nào đóng ticket) rồi
    đo lại trên CÙNG hai envelope. Bản cũ nuốt envelope thứ hai; bản đang dùng thì không."""
    state = TriageState()
    first = triager([_obs("e1", semver_jump="minor")], state=state, now=NOW, key=legacy_generation_key)
    second = triager([_obs("e2", semver_jump="minor")], state=state, now=NOW, key=legacy_generation_key)
    assert len(first) == 1
    assert second == [], "trục cũ nuốt vĩnh viễn mọi signal hợp lệ phát sau vòng đầu"


# K3 (audit 2026-10-10): `dedupe` giữ NỘI DUNG của bản mới nhất; nếu tier cũng chỉ tính trên bản đó thì một bản
# trước nặng hơn (alert `critical` rồi bản sau `low`, bump `major` rồi `minor`, evidence chạm `agents/` rồi
# không) bị hạ tier → mất `requires_gate`. Mỗi ca: bản ĐẦU là `high`, bản CUỐI một mình không `high`.
@pytest.mark.parametrize(("dau", "cuoi"), [
    ({"kind": "security", "severity": "critical"}, {"kind": "security", "severity": "low"}),
    ({"semver_jump": "major"}, {"semver_jump": "minor"}),
    ({"kind": "drift", "evidence": "companies/software-company/agents/engineering/builder.md"},
     {"kind": "drift", "evidence": ""}),
], ids=["severity", "semver", "evidence"])
def test_gop_trung_khong_ha_tier_cua_ban_truoc(dau, cuoi):
    assert triager([_obs("e2", **cuoi)], state=TriageState(), now=NOW)[0].risk_tier != "high"  # đối chứng
    t = triager([_obs("e1", **dau), _obs("e2", **cuoi)], state=TriageState(), now=NOW)[0]
    assert t.risk_tier == "high"
    assert t.requires_gate is True
    assert t.due_at == "2026-09-10T00:00:00+00:00"
    assert t.ticket_id == "KEEP:e2"  # danh tính vẫn là bản mới nhất, chỉ tier lấy bậc cao nhất
