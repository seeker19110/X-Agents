"""ADR keeper 0001 — bằng chứng hai chiều gắn với DANH TÍNH patch, và đo lại hỏng thì thu hồi BỀN qua bus.

Hai nợ cố ý mà ADR trả (`orchestrator.py` trước ADR: marker `no-ky-thuat` ở `record_verification`):

1. `VerificationReport` không nói nó đo nội dung nào. Ticket đã `verified` rồi patch bị sửa tiếp thì cổng
   `evidence` vẫn mở — PR mang code chưa đo.
2. `record_verification` đo lại mà không đạt thì ném TRƯỚC khi lên bus: `verified` của báo cáo trước đứng nguyên,
   và mở lại bus thì replay dựng lại nó từ báo cáo cũ.

Ca cổng dùng danh tính GIẢ tiêm vào orchestrator (`patch_identity`, khuôn `runner: CommandRunner`) để không cần
git; một nhóm ca riêng chạy git THẬT trong `tmp_path` cho `worktree.content_tree` và đường mặc định. Không ca nào
rẽ theo `os.name` hay biến môi trường.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from keeper.events import Envelope, RunOutcome, Signal, Ticket
from keeper.evidence import (
    SELF_CLAIM_FIELDS,
    TRUSTED_VERIFIER,
    EvidenceError,
    TwoWayEvidence,
    collect_two_way,
    verification_report,
)
from keeper.fakes import FakeGitHub
from keeper.orchestrator import CODE_ACTOR, REJECT_ACTION, KeeperOrchestrator
from keeper.worktree import WorktreeError, content_tree, open_worktree

NOW = datetime(2026, 10, 4, tzinfo=UTC)
CMD = "uv run pytest -q"
CI_ARGV = ("uv", "run", "pytest", "-q")
CAY_DA_DO = "a" * 40  # danh tính nội dung lúc đo
CAY_DA_SUA = "b" * 40  # danh tính sau khi patch bị sửa tiếp


class _GH(FakeGitHub):
    """Ngân sách RỘNG — cổng `budget` không che cổng `evidence` đang đo."""

    def open_prs(self) -> list:
        return []

    def merged_prs(self, since: str) -> list:
        return []


class _Cay:
    """Danh tính worktree giả, đổi được giữa chừng. Ghi lại ai đã hỏi, để ca "không chặn" chứng minh được cổng
    THẬT SỰ hỏi danh tính chứ không xanh vì chẳng kiểm gì."""

    def __init__(self, cay: str | None = CAY_DA_DO) -> None:
        self.cay = cay
        self.hoi: list[str] = []

    def __call__(self, ticket_id: str) -> str | None:
        self.hoi.append(ticket_id)
        return self.cay


def _orc(tmp_path: Path, cay: _Cay) -> KeeperOrchestrator:
    return KeeperOrchestrator(tmp_path / "keeper.sqlite", tmp_path / "repo", _GH(), patch_identity=cay)


def _ev(*, ok: bool = True, patch_id: str | None = CAY_DA_DO) -> TwoWayEvidence:
    return TwoWayEvidence(
        cmd=CMD,
        before=RunOutcome(cmd=CMD, exit_code=1 if ok else 0),
        after=RunOutcome(cmd=CMD, exit_code=0),
        verified_by=TRUSTED_VERIFIER,
        patch_id=patch_id,
    )


def _ticket(o: KeeperOrchestrator) -> Ticket:
    """Ticket tier `medium`, không cần gate — chỉ còn `evidence` (và `budget`, đã mở rộng) đứng chắn."""
    o.submit_signal(Signal(subject="requests", kind="dependency", detail="bump"))
    (t,) = o.tick(now=NOW).tickets
    assert not t.requires_gate
    return t


def _rejects(o: KeeperOrchestrator) -> list[Envelope]:
    return [
        a for a in o.bus.replay(topic="audit-log") if a.payload["action"] == REJECT_ACTION and a.actor == CODE_ACTOR
    ]


# ---------- (1)(2) cổng `evidence` so danh tính hiện tại với danh tính đã đo ----------


def test_patch_sua_sau_khi_verified_thi_cong_evidence_chan(tmp_path: Path):
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())
    assert t.ticket_id in o.verified

    cay.cay = CAY_DA_SUA  # patch bị sửa tiếp SAU lần đo
    assert "evidence" in o.pr_blockers(t)
    assert o.open_pr(t) is None and o.notes == {}


def test_patch_khong_doi_thi_cong_evidence_mo_va_co_hoi_danh_tinh(tmp_path: Path):
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())

    assert o.pr_blockers(t) == []
    assert t.ticket_id in cay.hoi, "cổng phải HỎI danh tính hiện tại, không mở chỉ vì từng verified"
    assert o.open_pr(t) is not None


def test_khong_do_duoc_danh_tinh_hien_tai_thi_cong_dong(tmp_path: Path):
    """Worktree không còn (đã dọn) / git lỗi → `None` — không bao giờ bằng một danh tính đã đo (fail closed)."""
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())
    cay.cay = None
    assert "evidence" in o.pr_blockers(t)


# ---------- (3) danh tính do CODE đo, lời khai của model bị bỏ ----------


def test_patch_id_nam_trong_truong_tu_khai():
    assert "patch_id" in SELF_CLAIM_FIELDS


def test_payload_tu_khai_patch_id_bi_bo_so_do_thang():
    payload = {"ticket_id": "T-1", "patch_id": CAY_DA_SUA}
    assert verification_report(payload, evidence=_ev(patch_id=CAY_DA_DO)).patch_id == CAY_DA_DO
    # Lớp 2 (hợp nhất `{**clean, **measured}`) vẫn giữ khi lớp 1 (bộ lọc) bị tắt.
    tat_loc = verification_report(payload, evidence=_ev(patch_id=CAY_DA_DO), fields=frozenset())
    assert tat_loc.patch_id == CAY_DA_DO


def test_model_khai_dung_danh_tinh_hien_tai_khong_mo_duoc_cong(tmp_path: Path):
    """Đòn thật: patch đã bị sửa (`CAY_DA_SUA`), model khai `patch_id` = danh tính MỚI để mua cổng bằng bằng
    chứng đo trên nội dung CŨ. Số đo phải thắng, cổng đóng."""
    cay = _Cay(CAY_DA_SUA)
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id, "patch_id": CAY_DA_SUA}, _ev(patch_id=CAY_DA_DO))
    assert o.reports[t.ticket_id].patch_id == CAY_DA_DO
    assert "evidence" in o.pr_blockers(t)


# ---------- (4)(5) đo lại hỏng ⇒ thu hồi BỀN qua bus; đo lại đạt ⇒ cấp lại ----------


def test_do_lai_hong_thu_hoi_verified_ben_qua_bus_va_nem_cho_caller(tmp_path: Path):
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())
    assert t.ticket_id in o.verified

    with pytest.raises(EvidenceError, match="before-must-fail"):
        o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev(ok=False))
    assert t.ticket_id not in o.verified and t.ticket_id not in o.reports
    assert "evidence" in o.pr_blockers(t)

    mo_lai = _orc(tmp_path, cay)  # replay từ CÙNG file SQLite
    assert t.ticket_id not in mo_lai.verified, "replay không được hồi sinh verified từ báo cáo cũ"
    assert "evidence" in mo_lai.pr_blockers(t)
    assert len(_rejects(_orc(tmp_path, cay))) == 1, "một lần đo hỏng = đúng một bản ghi từ chối"


def test_do_lai_hong_vi_bao_cao_ra_ho_loi_cung_thu_hoi_ben(tmp_path: Path):
    """Thu hồi bền phải phủ MỌI lý do `record_verification` từ chối, không chỉ hàng kiểm hai chiều: đường nạp
    chạy đúng phép kiểm của đường dựng, kể cả `require_family_report`."""
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())

    with pytest.raises(EvidenceError, match="họ lỗi"):
        o.record_verification(
            t.ticket_id, {"ticket_id": t.ticket_id, "family_hits": ["src/a.py"], "family_safe": []}, _ev()
        )
    assert t.ticket_id not in o.verified
    assert t.ticket_id not in _orc(tmp_path, cay).verified


def test_do_lai_dat_sau_khi_thu_hoi_thi_cap_lai_ca_sau_replay(tmp_path: Path):
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())
    with pytest.raises(EvidenceError):
        o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev(ok=False))
    assert t.ticket_id not in o.verified

    report = o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())
    assert report.patch_id == CAY_DA_DO
    assert t.ticket_id in o.verified and o.pr_blockers(t) == []
    mo_lai = _orc(tmp_path, cay)
    assert t.ticket_id in mo_lai.verified and mo_lai.pr_blockers(t) == []


def test_bang_chung_khong_gan_danh_tinh_thi_nem_va_khong_mo_cong(tmp_path: Path):
    """`TwoWayEvidence` dựng tay (không qua `collect_two_way`) không mang danh tính → không biết nó đo nội dung
    nào → không thành `verified` được, và lần đo ấy vẫn để lại dấu thu hồi trên bus."""
    cay = _Cay()
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev())
    with pytest.raises(EvidenceError, match="patch_id"):
        o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, _ev(patch_id=None))
    assert t.ticket_id not in o.verified and t.ticket_id not in _orc(tmp_path, cay).verified


# ---------- (6) báo cáo trên bus cũ (trước ADR keeper 0001) không có trường danh tính ----------


def test_bao_cao_cu_khong_co_patch_id_tren_bus_khong_mo_cong_va_tu_choi_mot_lan(tmp_path: Path):
    """Đúng hình dạng payload trước ADR keeper 0001: không có khoá `patch_id`. Báo cáo ấy đạt cả hai chiều, nhưng
    không nói nó đo nội dung nào — ADR quyết định: từ chối (fail closed), ghi đúng một bản ghi từ chối, và
    replay cho cùng kết quả. Chấp nhận nó là để bất kỳ ai ghi được topic mở cổng chỉ bằng cách BỎ trường."""
    cay = _Cay()
    o1 = _orc(tmp_path, cay)
    t = _ticket(o1)
    cu = {
        "ticket_id": t.ticket_id,
        "before": {"cmd": CMD, "exit_code": 1},
        "after": {"cmd": CMD, "exit_code": 0},
        "verified_by": TRUSTED_VERIFIER,
    }
    o1.bus.publish(Envelope(topic="verification-reports", key=t.ticket_id, actor="regression-guard", payload=cu))
    assert t.ticket_id not in o1.verified
    assert "evidence" in o1.pr_blockers(t)

    o2 = _orc(tmp_path, cay)
    assert t.ticket_id not in o2.verified
    assert len(_rejects(_orc(tmp_path, cay))) == 1


def test_danh_tinh_none_khong_bao_gio_khop_ke_ca_bao_cao_none_da_lot_vao_verified(tmp_path: Path, monkeypatch):
    """Lớp thứ hai của (6): kể cả khi báo cáo `patch_id=None` lọt vào `verified` (tắt kiểm đường nạp), worktree
    không đo được (`None`) cũng không được "khớp" với nó — `None == None` không phải một lần đo."""
    monkeypatch.setattr(KeeperOrchestrator, "VERIFY_ON_APPLY", False)
    cay = _Cay(None)
    o = _orc(tmp_path, cay)
    t = _ticket(o)
    cu = {
        "ticket_id": t.ticket_id,
        "before": {"cmd": CMD, "exit_code": 1},
        "after": {"cmd": CMD, "exit_code": 0},
        "verified_by": TRUSTED_VERIFIER,
    }
    o.bus.publish(Envelope(topic="verification-reports", key=t.ticket_id, actor="regression-guard", payload=cu))
    assert t.ticket_id in o.verified
    assert "evidence" in o.pr_blockers(t)


# ---------- `collect_two_way` tự đo danh tính ----------


class _GitGia:
    """`git stash` giả có ĐỘ SÂU (khuôn `_FakeGit` của `test_evidence.py`): lệnh CI đỏ khi đang stash (bản sửa
    TẮT), xanh khi đã pop. Ghi thứ tự lệnh vào `nhat_ky` chung với phép đo danh tính."""

    def __init__(self, nhat_ky: list[str]) -> None:
        self.depth = 0
        self.nhat_ky = nhat_ky

    def __call__(self, argv, cwd, **kw) -> RunOutcome:
        argv = tuple(argv)
        cmd = " ".join(argv)
        self.nhat_ky.append(cmd)
        if argv[:3] == ("git", "stash", "list"):
            return RunOutcome(cmd=cmd, exit_code=0, output_tail="\n".join("stash" for _ in range(self.depth)))
        if argv[:3] == ("git", "stash", "push"):
            self.depth += 1
        elif argv[:3] == ("git", "stash", "pop"):
            self.depth -= 1
        else:
            return RunOutcome(cmd=cmd, exit_code=1 if self.depth else 0)
        return RunOutcome(cmd=cmd, exit_code=0)


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@x", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "khoi tao")
    return root


@pytest.fixture
def wt(repo: Path) -> Path:
    """Worktree PHỤ — thứ `collect_two_way` được phép chạm."""
    return open_worktree("T-1", repo=repo).path


def test_collect_two_way_do_danh_tinh_truoc_khi_tat_ban_sua(wt: Path):
    nhat_ky: list[str] = []

    def do(path: Path) -> str:
        nhat_ky.append(f"do:{path}")
        return CAY_DA_DO

    ev = collect_two_way(CI_ARGV, wt, runner=_GitGia(nhat_ky), identify=do)
    assert ev.patch_id == CAY_DA_DO
    assert nhat_ky[0] == f"do:{wt}", "danh tính phải đo TRƯỚC khi stash tắt bản sửa"
    assert nhat_ky.count(f"do:{wt}") == 2 and nhat_ky[-1] == f"do:{wt}", "đo lại sau lần chạy `after`"


def test_collect_two_way_noi_dung_doi_trong_luc_do_thi_nem(wt: Path):
    """Pop không trả đúng nội dung, hay chính lệnh CI ghi đè file: hai lần chạy không còn đo CÙNG một nội dung —
    không có danh tính nào để gắn báo cáo vào."""
    lan = iter([CAY_DA_DO, CAY_DA_SUA])
    with pytest.raises(EvidenceError, match="đổi trong lúc đo"):
        collect_two_way(CI_ARGV, wt, runner=_GitGia([]), identify=lambda _p: next(lan))


# ---------- `worktree.content_tree`: git THẬT ----------


def test_content_tree_xac_dinh_va_worktree_sach_bang_cay_head(wt: Path):
    assert content_tree(wt) == content_tree(wt) == _git(wt, "rev-parse", "HEAD^{tree}")


def test_content_tree_doi_khi_sua_file_da_track_tro_lai_khi_hoan_tac(wt: Path):
    goc = content_tree(wt)
    (wt / "a.py").write_text("x = 2\n", encoding="utf-8")
    sua = content_tree(wt)
    assert sua != goc
    (wt / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert content_tree(wt) == goc


def test_content_tree_tinh_ca_file_chua_track_bo_file_bi_ignore(wt: Path):
    goc = content_tree(wt)
    (wt / "debug.log").write_text("rác do lệnh sinh\n", encoding="utf-8")
    assert content_tree(wt) == goc, "file bị .gitignore không thuộc patch"
    (wt / "test_moi.py").write_text("def test_x(): pass\n", encoding="utf-8")
    assert content_tree(wt) != goc, "file test MỚI (chưa track) là một phần của patch — stash cũng cất nó"


def test_content_tree_khong_doi_khi_commit_dung_noi_dung_da_do_va_khong_cham_index_that(wt: Path):
    (wt / "a.py").write_text("x = 2\n", encoding="utf-8")
    (wt / "test_moi.py").write_text("def test_x(): pass\n", encoding="utf-8")
    truoc_commit = content_tree(wt)
    assert _git(wt, "diff", "--cached", "--name-only") == "", "đo danh tính không được stage gì vào index thật"
    _git(wt, "add", "-A")
    _git(wt, "commit", "-m", "va")
    assert content_tree(wt) == truoc_commit == _git(wt, "rev-parse", "HEAD^{tree}")


def test_content_tree_thu_muc_khong_ton_tai_thi_nem(tmp_path: Path):
    with pytest.raises(WorktreeError):
        content_tree(tmp_path / "khong-co")


# ---------- đầu-cuối: git THẬT, danh tính mặc định của orchestrator ----------


def test_dau_cuoi_sua_patch_tren_worktree_that_thi_dong_hoan_tac_thi_mo(repo: Path):
    o = KeeperOrchestrator(repo.parent / "keeper.sqlite", repo, _GH())
    t = _ticket(o)
    w = open_worktree(t.ticket_id, repo=repo)
    (w.path / "a.py").write_text("x = 2\n", encoding="utf-8")  # patch, chưa commit
    ev = collect_two_way(CI_ARGV, w.path, runner=_GitGia([]))
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, ev)
    assert o.pr_blockers(t) == []

    (w.path / "a.py").write_text("x = 3\n", encoding="utf-8")  # sửa tiếp sau khi đo
    assert "evidence" in o.pr_blockers(t)
    (w.path / "a.py").write_text("x = 2\n", encoding="utf-8")  # đúng nội dung đã đo
    assert o.pr_blockers(t) == []

    w.close()  # worktree đã dọn: không đo được
    assert "evidence" in o.pr_blockers(t)
