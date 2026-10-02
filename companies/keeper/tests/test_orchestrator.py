"""BT7 — vòng lặp `watch → triage → patch → verify → gate? → release`.

Mọi ca dựng bus SQLite trong `tmp_path` và dùng `FakeGitHub` (không chạm mạng, không gọi `gh`). Không ca nào
rẽ theo `os.name` hay biến môi trường.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from keeper.events import Envelope, RunOutcome, Signal, VerificationReport
from keeper.evidence import TRUSTED_VERIFIER, EvidenceError, TwoWayEvidence
from keeper.fakes import FakeGitHub
from keeper.gates import request_gate
from keeper.github import GitHubWriteAttempt
from keeper.orchestrator import CODE_ACTOR, HUMAN_ONLY, REJECT_ACTION, KeeperOrchestrator

NOW = datetime(2026, 9, 9, tzinfo=UTC)


class _GH(FakeGitHub):
    """Ngân sách RỘNG: không PR nào đang mở, không PR nào đã gộp trong tuần."""

    def __init__(self, open_prs: int = 0) -> None:
        super().__init__()
        self._open = open_prs

    def open_prs(self):
        return super().open_prs()[: self._open]

    def merged_prs(self, since: str):
        super().merged_prs(since)
        return []


def _orc(tmp_path: Path, gh: _GH | None = None) -> KeeperOrchestrator:
    return KeeperOrchestrator(tmp_path / "keeper.sqlite", tmp_path / "repo", gh or _GH())


def _signal(**kw) -> Signal:
    base = {"subject": "requests", "kind": "dependency", "detail": "bump", "semver_jump": "major"}
    base.update(kw)
    return Signal.model_validate(base)


def _evidence(ok: bool = True) -> TwoWayEvidence:
    cmd = "uv run pytest -q"
    return TwoWayEvidence(
        cmd=cmd,
        before=RunOutcome(cmd=cmd, exit_code=1 if ok else 0),
        after=RunOutcome(cmd=cmd, exit_code=0),
        verified_by=TRUSTED_VERIFIER,
    )


def _verify(o: KeeperOrchestrator, ticket_id: str) -> None:
    o.record_verification(ticket_id, {"ticket_id": ticket_id}, _evidence())


# ---------- triage ----------

def test_signal_thanh_ticket_mot_lan_du_phat_lai(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    o.submit_signal(_signal())
    assert [t.risk_tier for t in o.tick(now=NOW).tickets] == ["high"]
    assert o.tick(now=NOW).tickets == []


def test_signal_cham_agents_thanh_ticket_high_cho_nguoi(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(subject="software-company/agents/builder.md", kind="drift", semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    assert t.risk_tier == "high" and t.requires_gate and HUMAN_ONLY in o.pr_blockers(t)


# ---------- cổng gate: tier high phải có gate approved ----------

def test_tier_high_chua_co_gate_approved_thi_khong_mo_pr(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    (t,) = o.tick(now=NOW).tickets
    _verify(o, t.ticket_id)
    assert "gate" in o.pr_blockers(t)
    assert o.open_pr(t) is None and o.notes == {}
    assert t.ticket_id in o.gate.pending, "gate phải được XIN, không im lặng bỏ ticket"


def test_tier_high_da_approve_thi_mo_pr(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    (t,) = o.tick(now=NOW).tickets
    _verify(o, t.ticket_id)
    o.tick(now=NOW)  # xin gate
    o.gate.decide(t.ticket_id, "approve", by="human:pm", reason="đã soi bằng chứng hai chiều")
    assert o.pr_blockers(t) == []
    note = o.open_pr(t)
    assert note is not None and note.ticket_id == t.ticket_id and o.notes[t.ticket_id] == note


def test_tier_thap_khong_can_gate(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    assert t.risk_tier == "medium" and not t.requires_gate
    _verify(o, t.ticket_id)
    assert o.pr_blockers(t) == [] and o.open_pr(t) is not None


# ---------- cổng bằng chứng hai chiều (I2) ----------

def test_thieu_bang_chung_thi_ticket_khong_roi_pha_quality(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    assert "evidence" in o.pr_blockers(t) and o.open_pr(t) is None


def test_bang_chung_hong_bi_tu_choi_va_ticket_van_ket(tmp_path: Path):
    """`before.exit_code == 0` = tắt bản sửa mà CI vẫn xanh ⇒ báo cáo vô hiệu (I2)."""
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    with pytest.raises(EvidenceError):
        o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _evidence(ok=False))
    assert "evidence" in o.pr_blockers(t) and o.open_pr(t) is None


# ---------- cổng ngân sách (I3) ----------

def test_ngan_sach_het_cho_thi_khong_mo_pr_du_moi_thu_khac_san_sang(tmp_path: Path):
    o = _orc(tmp_path, _GH(open_prs=1))
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    _verify(o, t.ticket_id)
    assert o.pr_blockers(t) == ["budget"] and o.open_pr(t) is None


# ---------- đường cấm: agents/skills không tự làm ----------

def test_ticket_cham_agents_khong_bao_gio_mo_pr_du_gate_da_approve(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(subject="keeper/skills/va-loi.md", kind="drift", semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    _verify(o, t.ticket_id)
    o.tick(now=NOW)
    o.gate.decide(t.ticket_id, "approve", by="human:pm", reason="người sẽ tự làm bảy bước")
    assert o.pr_blockers(t) == [HUMAN_ONLY] and o.open_pr(t) is None


# ---------- resume ----------

def test_resume_tu_cung_file_sqlite_giu_nguyen_trang_thai(tmp_path: Path):
    o1 = _orc(tmp_path)
    o1.submit_signal(_signal(semver_jump=None))
    (t,) = o1.tick(now=NOW).tickets
    _verify(o1, t.ticket_id)
    o1.open_pr(t)

    o2 = _orc(tmp_path)
    assert set(o2.tickets) == set(o1.tickets)
    assert o2.verified == o1.verified
    assert set(o2.notes) == set(o1.notes)
    assert o2.triage.seen == o1.triage.seen
    assert o2.tick(now=NOW).tickets == [], "signal cũ không được thành ticket lần hai sau restart"
    assert set(o2.tickets) == set(o1.tickets), "replay không được sinh ticket thứ hai cho cùng envelope"


def test_resume_giu_gate_dang_cho(tmp_path: Path):
    o1 = _orc(tmp_path)
    o1.submit_signal(_signal())
    (t,) = o1.tick(now=NOW).tickets
    o1.tick(now=NOW)
    assert t.ticket_id in o1.gate.pending
    o2 = _orc(tmp_path)
    assert t.ticket_id in o2.gate.pending


# ---------- vòng tick / watch ----------

def test_tick_mo_pr_khi_moi_cong_da_qua(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    _verify(o, t.ticket_id)
    res = o.tick(now=NOW)
    assert res.notes and res.notes[0].ticket_id == t.ticket_id
    assert o.tick(now=NOW).notes == [], "một ticket chỉ mở PR một lần"


def test_watch_chay_du_so_nhip(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    o.watch(interval=0.0, max_ticks=2)
    assert o.tickets and o.ticks == 2


def test_mot_nhip_loi_khong_giet_vong_watch(tmp_path: Path, monkeypatch):
    o = _orc(tmp_path)
    goi: list[int] = []

    def _no(now=None):
        goi.append(1)
        raise RuntimeError("bus hỏng")

    monkeypatch.setattr(o, "tick", _no)
    o.watch(interval=0.0, max_ticks=2)
    assert len(goi) == 2
    actions = [a.payload["action"] for a in o.bus.replay(topic="audit-log")]
    assert "tick_error" in actions


def test_request_gate_chi_xin_mot_lan(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    (t,) = o.tick(now=NOW).tickets
    o.tick(now=NOW)
    seq = o.gate.pending[t.ticket_id].seq
    o.tick(now=NOW)
    assert o.gate.pending[t.ticket_id].seq == seq


def test_gate_da_xin_boi_nguoi_thi_orchestrator_khong_xin_lai(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    (t,) = o.tick(now=NOW).tickets
    request_gate(o.gate, "patch", t.ticket_id, created_by="human:seeker")
    o.tick(now=NOW)
    assert o.gate.pending[t.ticket_id].created_by == "human:seeker"


# ---------- nối vào CLI ----------

def test_cli_watch_dung_orchestrator_va_khong_cham_gh(tmp_path: Path, monkeypatch, capsys):
    """`keeper watch` phải dựng `GitHubReader` (chỉ đọc) và gọi `watch()`. Ca này thay cả hai bằng bản giả:
    không tiến trình `gh` nào được sinh ra, và không ca nào phụ thuộc `gh auth` của máy."""
    from keeper import cli as cli_mod

    goi: dict[str, object] = {}

    class _Reader:
        def __init__(self, repo):
            goi["repo"] = repo

    class _Orc:
        def __init__(self, db, repo, gh):
            goi["db"], goi["gh"] = db, gh

        def watch(self, interval, max_ticks):
            goi["watch"] = (interval, max_ticks)

    monkeypatch.setattr("keeper.github.GitHubReader", _Reader)
    monkeypatch.setattr("keeper.orchestrator.KeeperOrchestrator", _Orc)
    rc = cli_mod.main(["watch", "--db", str(tmp_path / "k.sqlite"), "--repo", str(tmp_path),
                       "--interval", "0", "--max-ticks", "1"])
    assert rc == 0 and goi["watch"] == (0.0, 1) and isinstance(goi["gh"], _Reader)


# ---------- CHẶN-1: chống trùng theo danh tính event, không theo thế hệ ----------

def test_signal_moi_sau_khi_vong_truoc_hoan_tat_van_ra_ticket_thu_hai(tmp_path: Path):
    """Chiều thuận của CHẶN-1: một vòng đã HOÀN TẤT (có `release-notes`) rồi cùng `(kind, subject)` phát lại
    bằng một envelope MỚI → phải có ticket thứ hai, id khác. Trước bản sửa, thế hệ vĩnh viễn = 0 nên khoá cũ
    nuốt mọi lần sau."""
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t1,) = o.tick(now=NOW).tickets
    _verify(o, t1.ticket_id)
    assert o.tick(now=NOW).notes, "vòng một phải hoàn tất (có release-notes)"

    o.submit_signal(_signal(semver_jump=None))
    tickets = o.tick(now=NOW).tickets
    assert len(tickets) == 1, "signal mới sau khi vòng trước xong KHÔNG được bị nuốt"
    assert tickets[0].ticket_id != t1.ticket_id


def test_ticket_mang_danh_tinh_event_da_tieu_thu(tmp_path: Path):
    o = _orc(tmp_path)
    env = o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    assert t.signal_event_ids == [env.event_id] and t.ticket_id == f"KEEP:{env.event_id}"


def test_publish_ticket_loi_giua_nhip_thi_nhip_sau_van_ra_ticket(tmp_path: Path, monkeypatch):
    """Sổ `seen` chỉ được ghi khi ticket ĐÃ lên bus. Nhịp lỗi lúc publish (SQLite bận vì gate CLI là tiến
    trình khác, đĩa đầy...) mà id đã vào sổ thì nhịp sau bỏ qua signal đó — nuốt im lặng tới khi mở lại
    tiến trình (`TRAPS.md` khuôn 1)."""
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    that = o._publish

    def _ban(topic, key, actor, payload):
        if topic == "maintenance-tickets":
            raise OSError("database is locked")
        return that(topic, key, actor, payload)

    monkeypatch.setattr(o, "_publish", _ban)
    with pytest.raises(OSError):
        o.tick(now=NOW)
    monkeypatch.setattr(o, "_publish", that)
    assert len(o.tick(now=NOW).tickets) == 1, "signal chưa thành ticket nào thì không được coi là đã tiêu thụ"


# ---------- CHẶN-2: cổng evidence đứng ở ĐƯỜNG TIÊU THỤ, không chỉ ở hàm dựng ----------

def _bad_report(ticket_id: str) -> VerificationReport:
    cmd = "uv run pytest -q"
    return VerificationReport(
        ticket_id=ticket_id,
        before=RunOutcome(cmd=cmd, exit_code=0),   # tắt bản sửa mà CI vẫn XANH ⇒ vô hiệu (I2)
        after=RunOutcome(cmd=cmd, exit_code=0),
        verified_by=TRUSTED_VERIFIER,
    )


def _publish_bad_report(o: KeeperOrchestrator, ticket_id: str) -> Envelope:
    """Đi THẲNG lên bus, không qua `record_verification` — đúng hình dạng event của một tiến trình khác."""
    return o.bus.publish(Envelope(topic="verification-reports", key=ticket_id, actor="regression-guard",
                                  payload=_bad_report(ticket_id).model_dump()))


def test_bao_cao_khong_dat_hai_chieu_den_thang_tu_bus_khong_mo_cong_evidence(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    _publish_bad_report(o, t.ticket_id)
    assert t.ticket_id not in o.verified and t.ticket_id not in o.reports
    assert "evidence" in o.pr_blockers(t) and o.open_pr(t) is None
    actions = [a.payload["action"] for a in o.bus.replay(topic="audit-log")]
    assert REJECT_ACTION in actions, "từ chối phải ghi lý do, không nuốt im lặng"


def test_tat_kiem_o_duong_nap_thi_cong_evidence_mo_ra(tmp_path: Path, monkeypatch):
    """Chiều ngược: TẮT chính bản sửa (`VERIFY_ON_APPLY = False`) rồi đo lại trên CÙNG event — cổng mở."""
    monkeypatch.setattr(KeeperOrchestrator, "VERIFY_ON_APPLY", False)
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    _publish_bad_report(o, t.ticket_id)
    assert t.ticket_id in o.verified
    assert "evidence" not in o.pr_blockers(t) and o.open_pr(t) is not None


def test_bao_cao_hong_trong_bus_cu_bi_tu_choi_lai_khi_mo_va_chi_ghi_audit_mot_lan(tmp_path: Path):
    """Event hỏng đã nằm sẵn trong `keeper.sqlite`: mở lại phải VẪN chặn, và audit không nhân lên mỗi lần mở."""
    o1 = _orc(tmp_path)
    o1.submit_signal(_signal(semver_jump=None))
    (t,) = o1.tick(now=NOW).tickets
    _publish_bad_report(o1, t.ticket_id)

    o2 = _orc(tmp_path)
    assert t.ticket_id not in o2.verified
    o3 = _orc(tmp_path)
    rejects = [a for a in o3.bus.replay(topic="audit-log") if a.payload["action"] == REJECT_ACTION]
    assert len(rejects) == 1, "một event hỏng = đúng một bản ghi từ chối, dù mở lại bao nhiêu lần"


def test_tu_choi_gia_mao_khong_nuot_duoc_ban_ghi_tu_choi_that(tmp_path: Path):
    """Anh em của `pr.blocked` giả mạo: `_audited_rejects` dựng từ `verification.rejected` trên topic MỞ. Bản giả
    mang `key` = event_id của một báo cáo hỏng ghi lúc orchestrator đang tắt thì lần mở sau coi như đã ghi từ
    chối, báo cáo hỏng bị chặn trong im lặng. Chỉ bản ghi của `CODE_ACTOR` được tính. Đo hai chiều: bỏ kiểm
    actor thì assert đỏ."""
    from keeper.bus import KeeperBus
    from keeper.core import CORE
    from keeper.events import AuditLog
    o1 = _orc(tmp_path)
    o1.submit_signal(_signal(semver_jump=None))
    (t,) = o1.tick(now=NOW).tickets
    o1.bus.close()

    bus = KeeperBus(CORE, tmp_path / "keeper.sqlite")  # tiến trình khác, orchestrator đang tắt
    hong = Envelope(topic="verification-reports", key=t.ticket_id, actor="regression-guard",
                    payload=_bad_report(t.ticket_id).model_dump())
    bus.publish(Envelope(topic="audit-log", key=hong.event_id, actor="human:mallory",
                         payload=AuditLog(actor=CODE_ACTOR, action=REJECT_ACTION, ticket_id=t.ticket_id,
                                          evidence="{}").model_dump()))
    bus.publish(hong)
    bus.close()

    o2 = _orc(tmp_path)
    assert t.ticket_id not in o2.verified
    that = [a for a in o2.bus.replay(topic="audit-log") if a.payload["action"] == REJECT_ACTION and a.actor == CODE_ACTOR]
    assert [a.key for a in that] == [hong.event_id], "báo cáo hỏng phải có bản ghi từ chối thật của code"


# ---------- CHẶN-3: I3 trong CÙNG một nhịp ----------

def _hai_ticket_du_cong(o: KeeperOrchestrator) -> list:
    o.submit_signal(_signal(subject="requests", semver_jump=None))
    o.submit_signal(_signal(subject="httpx", semver_jump=None))
    tickets = o.tick(now=NOW).tickets
    assert len(tickets) == 2
    for t in tickets:
        _verify(o, t.ticket_id)
    return tickets


def test_hai_ticket_du_cong_trong_mot_nhip_chi_ra_mot_release_note(tmp_path: Path):
    o = _orc(tmp_path)
    t1, t2 = _hai_ticket_du_cong(o)
    res = o.tick(now=NOW)
    assert len(res.notes) == 1 and res.notes[0].ticket_id == t1.ticket_id
    assert o.pr_blockers(t2) == ["budget"], "ticket thứ hai bị chặn bởi ĐÚNG cổng ngân sách"


def test_tat_kiem_y_dinh_thi_mot_nhip_ra_hai_release_note(tmp_path: Path, monkeypatch):
    """Chiều ngược: TẮT chính bản sửa (`INTENT_GUARD = False`) → I3 thủng trong một nhịp, hai `release-notes`."""
    monkeypatch.setattr(KeeperOrchestrator, "INTENT_GUARD", False)
    o = _orc(tmp_path)
    _hai_ticket_du_cong(o)
    assert len(o.tick(now=NOW).notes) == 2


def test_y_dinh_mo_pr_dung_lai_duoc_tu_bus(tmp_path: Path):
    o1 = _orc(tmp_path)
    o1.submit_signal(_signal(semver_jump=None))
    (t,) = o1.tick(now=NOW).tickets
    _verify(o1, t.ticket_id)
    o1.tick(now=NOW)
    o2 = _orc(tmp_path)
    assert o2.outstanding_pr_intents() == {t.ticket_id}


# ---------- audit: code không mượn tên agent, tên action không phải lời khai ----------

def test_audit_cua_code_ghi_duoi_actor_rieng_va_action_la_y_dinh(tmp_path: Path):
    o = _orc(tmp_path)
    o.submit_signal(_signal(semver_jump=None))
    (t,) = o.tick(now=NOW).tickets
    _verify(o, t.ticket_id)
    o.tick(now=NOW)
    ghi = [a for a in o.bus.replay(topic="audit-log") if a.payload["action"] == "pr.intent"]
    assert ghi and all(a.actor == CODE_ACTOR for a in ghi)
    assert CODE_ACTOR != "keeper-supervisor", "code không được ghi audit dưới tên một vai agent"
    actions = {a.payload["action"] for a in o.bus.replay(topic="audit-log")}
    assert "pr.open" not in actions, "BT7 chưa gọi `gh pr create` — không được gọi ý định là `pr.open`"


def _blocked(o: KeeperOrchestrator) -> list[list[str]]:
    import json
    return [json.loads(a.payload["evidence"])["blockers"] for a in o.bus.replay(topic="audit-log")
            if a.payload["action"] == "pr.blocked"]


def test_pr_blocked_chi_ghi_khi_cong_chan_doi_khong_ghi_moi_nhip(tmp_path: Path):
    """`watch` mặc định 5 giây một nhịp: ticket chờ người duyệt gate một ngày = ~17k dòng `pr.blocked` y hệt
    nhau, và `bus.replay()` lúc mở đọc lại hết. Ghi khi tập cổng chặn ĐỔI là đủ để người biết vì sao."""
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    o.tick(now=NOW)
    o.tick(now=NOW)
    o.tick(now=NOW)
    assert _blocked(o) == [["evidence", "gate"]]

    (t,) = o.tickets.values()
    _verify(o, t.ticket_id)
    o.tick(now=NOW)
    assert _blocked(o) == [["evidence", "gate"], ["gate"]], "cổng chặn đổi thì phải ghi lại"


def test_pr_blocked_khong_ghi_lai_sau_khi_mo_lai_bus(tmp_path: Path):
    """Khoá chống lặp phải dựng lại từ `audit-log`, không phải biến RAM (`TRAPS.md` khuôn 2)."""
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    o.tick(now=NOW)
    _orc(tmp_path).tick(now=NOW)
    assert _blocked(_orc(tmp_path)) == [["evidence", "gate"]]


def test_pr_blocked_gia_mao_khong_nuot_duoc_dong_that(tmp_path: Path):
    """`audit-log` là topic MỞ (ai cũng ghi). Khoá chống lặp đọc `pr.blocked` mà không kiểm `env.actor` thì một
    bản ghi giả mang đúng `evidence` kế tiếp làm dòng thật không bao giờ được ghi — người không biết vì sao PR
    nằm im. Chỉ dòng do code ghi (`CODE_ACTOR`) mới được làm khoá. Khoá dựng lại lúc replay, nên bản giả cắn sau
    khi mở lại bus. Đo hai chiều: bỏ kiểm actor thì assert đỏ."""
    import json

    from keeper.events import AuditLog
    o = _orc(tmp_path)
    o.submit_signal(_signal())
    o.tick(now=NOW)
    (t,) = o.tickets.values()
    gia = json.dumps({"ticket_id": t.ticket_id, "blockers": ["gate"]}, ensure_ascii=False)
    o.bus.publish(Envelope(topic="audit-log", key="x", actor="human:mallory",
                           payload=AuditLog(actor=CODE_ACTOR, action="pr.blocked", ticket_id=t.ticket_id,
                                            evidence=gia).model_dump()))
    o = _orc(tmp_path)
    _verify(o, t.ticket_id)
    o.tick(now=NOW)
    that = [json.loads(a.payload["evidence"])["blockers"] for a in o.bus.replay(topic="audit-log")
            if a.payload["action"] == "pr.blocked" and a.actor == CODE_ACTOR]
    assert that == [["evidence", "gate"], ["gate"]], "bản ghi giả không được thay dòng thật của code"


# ---------- I1: lỗi ghi GitHub không được nuốt vào tick_error ----------

def test_watch_khong_nuot_gitub_write_attempt(tmp_path: Path, monkeypatch):
    o = _orc(tmp_path)

    def _no(now=None):
        raise GitHubWriteAttempt("gh pr create: thao tác ghi bị cấm (bất biến I1)")

    monkeypatch.setattr(o, "tick", _no)
    with pytest.raises(GitHubWriteAttempt):
        o.watch(interval=0.0, max_ticks=2)


def test_apply_bo_qua_topic_khong_thuoc_chuoi_trang_thai(tmp_path: Path):
    """Nhánh cuối của `_apply`: topic không khớp mệnh đề nào thì rơi ra ngoài, KHÔNG nổ.

    `_apply` chạy cho cả replay lẫn event mới, nên một topic lạ trên bus (do phiên bản sau thêm, hay do công
    ty khác dùng chung bus) phải là việc bình thường — nổ ở đây là sập replay của cả orchestrator."""
    o = _orc(tmp_path)
    truoc = (dict(o.reports), dict(o.notes))

    o._apply(Envelope(topic="patch-proposals", key="T-1", actor=CODE_ACTOR, payload={"gi-do": 1}))

    assert (dict(o.reports), dict(o.notes)) == truoc
