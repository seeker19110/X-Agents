"""ADR keeper 0002 — `publish()` từ chối khi thứ sắp push khác nội dung đã đo.

ADR keeper 0001 gắn bằng chứng hai chiều vào `patch_id` (cây nội dung worktree lúc đo) và cổng `evidence` so
danh tính lúc `open_pr`. Khoảng `open_pr → publish` thì không ai so: sửa code sau `open_pr` rồi `keeper publish`
vẫn push code chưa đo — lỗ I2 ở đúng bước ra ngoài máy (marker `no-ky-thuat` cũ ở `publish()`).

Luật mới: cây sắp push được khác cây đã đo ĐÚNG ở các dòng release của chính note ticket (`release.record` →
`release.fill_pr_number`), trong `CHANGELOG.md` / `docs/sessions/<ngày>.md`, và chỉ bằng cách THÊM dòng. Mọi
khác biệt khác, worktree bẩn, worktree mất, báo cáo không `patch_id` ⇒ `EvidenceError`, không push, không `gh`.

Repo git THẬT trong `tmp_path`, remote là repo bare local (không mạng); `gh pr create` giả bằng cách thay
`subprocess.run` trong `keeper.publish` — khuôn `test_orchestrator_publish.py`. Không ca nào rẽ theo `os.name`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import keeper.orchestrator as orch_mod
from keeper import publish as publish_mod
from keeper.cli import main
from keeper.events import Envelope, RunOutcome, Signal
from keeper.evidence import TRUSTED_VERIFIER, EvidenceError, TwoWayEvidence
from keeper.fakes import FakeGitHub
from keeper.orchestrator import VERIFIER_ACTOR, KeeperOrchestrator
from keeper.release import PR_PLACEHOLDER, record, unmeasured_changes
from keeper.worktree import KeeperWorktree, content_tree, open_worktree

NOW = datetime(2026, 9, 12, tzinfo=UTC)
NGAY = NOW.strftime("%Y-%m-%d")
CMD = "uv run pytest -q"
_GOC_RUN = subprocess.run


class _GH(FakeGitHub):
    """Ngân sách RỘNG — cổng `budget` không che thứ đang đo."""

    def open_prs(self) -> list:
        return []


@dataclass
class _RunSpy:
    """Chỉ giả lệnh `gh`; `git` (worktree, push) chạy THẬT."""

    script: list[tuple[int, str, str]]
    calls: list[list[str]]

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] != "gh":
            return _GOC_RUN(argv, **kw)
        self.calls.append(argv)
        code, out, err = self.script[len(self.calls) - 1]
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _commit(path: Path, msg: str = "vá") -> None:
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@x")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n- cũ (#1)\n", encoding="utf-8")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    _commit(root, "khoi tao")
    return root


@pytest.fixture
def remote(tmp_path: Path, repo: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(bare.parent, "init", "--bare", "-b", "main", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", "main")
    return bare


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _RunSpy:
    s = _RunSpy(script=[(0, "https://github.com/o/r/pull/9\n", "")], calls=[])
    monkeypatch.setattr(publish_mod.subprocess, "run", s)
    return s


def _da_do(
    repo: Path, *, sua: dict[str, str] | None = None, patch_identity: Any = None
) -> tuple[KeeperOrchestrator, KeeperWorktree]:
    """Ticket qua hết cổng: patch `sua` (mặc định sửa `app.py`) ghi vào worktree, ĐO (danh tính thật), rồi
    `tick` mở ý định PR. Trả orchestrator + worktree; chưa có dòng release nào trong worktree."""
    o = KeeperOrchestrator(repo.parent / "keeper.sqlite", repo, _GH(), patch_identity=patch_identity)
    o.submit_signal(
        Signal.model_validate({"subject": "requests", "kind": "dependency", "detail": "bump", "semver_jump": None})
    )
    (t,) = o.tick(now=NOW).tickets
    wt = open_worktree(t.ticket_id, repo=repo)
    for rel, text in (sua if sua is not None else {"app.py": "x = 2\n"}).items():
        (wt.path / rel).write_text(text, encoding="utf-8")
    patch_id = patch_identity(t.ticket_id) if patch_identity else content_tree(wt.path)
    o.record_verification(
        t.ticket_id,
        {"ticket_id": t.ticket_id},
        TwoWayEvidence(
            cmd=CMD,
            before=RunOutcome(cmd=CMD, exit_code=1),
            after=RunOutcome(cmd=CMD, exit_code=0),
            verified_by=TRUSTED_VERIFIER,
            patch_id=patch_id,
        ),
    )
    assert o.tick(now=NOW).notes, "ticket phải đủ cổng (kể cả danh tính) để có release-notes"
    return o, wt


def _ghi_release_va_commit(o: KeeperOrchestrator, wt: KeeperWorktree) -> None:
    """Đường thiết kế sau lần đo: `release.record` ghi dòng CHANGELOG + nhật ký mang `(#PR)`, rồi commit."""
    record(wt.path, o.notes[wt.ticket_id], session_date=NGAY)
    _commit(wt.path)


def _nhanh_tren_remote(remote: Path, wt: KeeperWorktree) -> str:
    return subprocess.run(["git", "ls-remote", str(remote), wt.branch], capture_output=True, text=True).stdout


def _khong_push_khong_gh(spy: _RunSpy, remote: Path, wt: KeeperWorktree, o: KeeperOrchestrator) -> None:
    assert spy.calls == [], "gh pr create không được gọi"
    assert wt.branch not in _nhanh_tren_remote(remote, wt), "nhánh không được lên remote"
    assert o.notes[wt.ticket_id].pr_number is None


# ---------- đối chứng: đường thiết kế vẫn đi ----------


def test_publish_di_khi_sau_lan_do_chi_them_dong_release_cua_note(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """Đối chứng (xanh cả trước bản sửa): dòng CHANGELOG + nhật ký phiên do `release.record` ghi SAU lần đo là
    khác biệt DUY NHẤT được phép — không có nó thì luật mới chặn oan mọi publish theo thiết kế."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)

    pr = o.publish(wt.ticket_id, wt, now=NOW)

    assert pr is not None and pr.number == 9
    assert "(#9)" in _git(wt.path, "show", "HEAD:CHANGELOG.md")
    assert "(#9)" in _git(wt.path, "show", f"HEAD:docs/sessions/{NGAY}.md")
    assert _nhanh_tren_remote(remote, wt).startswith(_git(wt.path, "rev-parse", "HEAD"))


# ---------- lỗ chính: code đổi sau lần đo ----------


def test_publish_tu_choi_khi_code_doi_sau_lan_do(repo: Path, remote: Path, spy: _RunSpy) -> None:
    o, wt = _da_do(repo)
    (wt.path / "app.py").write_text("x = 3  # chưa đo\n", encoding="utf-8")
    _ghi_release_va_commit(o, wt)

    with pytest.raises(EvidenceError, match=r"app\.py"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_khi_them_file_moi_sau_lan_do(repo: Path, remote: Path, spy: _RunSpy) -> None:
    o, wt = _da_do(repo)
    (wt.path / "moi.py").write_text("import os\n", encoding="utf-8")
    _ghi_release_va_commit(o, wt)

    with pytest.raises(EvidenceError, match=r"moi\.py"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


# ---------- tập loại trừ không phải cửa sau ----------


def test_publish_tu_choi_dong_changelog_khong_phai_cua_note(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """Đường dẫn được phép KHÔNG có nghĩa nội dung tuỳ ý: dòng thêm phải là dòng của chính note."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    cl = wt.path / "CHANGELOG.md"
    cl.write_text(cl.read_text(encoding="utf-8") + "- dòng lạ không ai đo\n", encoding="utf-8")
    _commit(wt.path)

    with pytest.raises(EvidenceError, match=r"CHANGELOG\.md"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_khi_sua_dong_co_san_cua_changelog(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """Patch chỉ-tài-liệu (đúng các file được phép) vẫn bị gắn: sau lần đo chỉ được THÊM, không sửa/xoá — dòng
    đã đo của patch (ở đây là `- cũ (#1)` của nền) không được đổi."""
    o, wt = _da_do(repo, sua={"CHANGELOG.md": "# Changelog\n\n- cũ (#1)\n- vá tài liệu (đã đo)\n"})
    _ghi_release_va_commit(o, wt)
    cl = wt.path / "CHANGELOG.md"
    cl.write_text(cl.read_text(encoding="utf-8").replace("- vá tài liệu (đã đo)", "- vá khác"), encoding="utf-8")
    _commit(wt.path)

    with pytest.raises(EvidenceError, match=r"CHANGELOG\.md"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_khi_chi_xoa_dong_da_do_cua_changelog(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """Xoá thuần (không thêm dòng lạ nào để phép "dòng của note" bắt): chỉ phép "cây đã đo là dãy con" thấy."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    cl = wt.path / "CHANGELOG.md"
    cl.write_text(cl.read_text(encoding="utf-8").replace("- cũ (#1)\n", ""), encoding="utf-8")
    _commit(wt.path)

    with pytest.raises(EvidenceError, match="sửa/xoá dòng đã đo"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_khi_xoa_file_duoc_phep(repo: Path, remote: Path, spy: _RunSpy) -> None:
    o, wt = _da_do(repo)
    (wt.path / "CHANGELOG.md").unlink()
    _commit(wt.path)

    with pytest.raises(EvidenceError, match=r"CHANGELOG\.md"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_nhat_ky_sai_ten_ngay(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """`docs/sessions/` chỉ được phép dưới dạng `<YYYY-MM-DD>.md` — thư mục con hay tên khác là đường dẫn lạ."""
    o, wt = _da_do(repo)
    lech = wt.path / "docs" / "sessions" / "x" / f"{NGAY}.md"
    lech.parent.mkdir(parents=True)
    lech.write_text(o.notes[wt.ticket_id].session_line + "\n", encoding="utf-8")
    _commit(wt.path)

    with pytest.raises(EvidenceError, match="docs/sessions/x/"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


# ---------- thứ được push phải đúng thứ được so ----------


def test_publish_tu_choi_khi_worktree_con_thay_doi_chua_commit(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """`publish` push NHÁNH, và bước điền số PR `commit -a` vơ mọi file đã track: code sửa mà chưa commit sau
    lần đo sẽ lên PR ở commit thứ hai. So cây của nhánh thôi là chưa đủ — worktree phải sạch."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    (wt.path / "app.py").write_text("x = 4  # chưa commit, chưa đo\n", encoding="utf-8")

    with pytest.raises(EvidenceError, match="chưa commit"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_kiem_lai_truoc_lan_push_thu_hai(
    monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path, spy: _RunSpy
) -> None:
    """Lần push thứ hai mang commit điền số PR (`commit -a`). Code lọt vào worktree giữa hai lần push không được
    đi theo commit đó: kiểm lại trước push thứ hai, và note KHÔNG mang số PR lên bus."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    goc_fill = orch_mod.fill_pr_number

    def fill_lot_code(*a: Any, **kw: Any) -> Any:
        moi = goc_fill(*a, **kw)
        (wt.path / "app.py").write_text("x = 5  # lọt vào giữa hai lần push\n", encoding="utf-8")
        return moi

    monkeypatch.setattr(orch_mod, "fill_pr_number", fill_lot_code)
    dau = _git(wt.path, "rev-parse", "HEAD")

    with pytest.raises(EvidenceError, match=r"app\.py"):
        o.publish(wt.ticket_id, wt, now=NOW)
    assert _nhanh_tren_remote(remote, wt).startswith(dau), "remote phải dừng ở commit đầu, không mang code lọt"
    assert o.notes[wt.ticket_id].pr_number is None


def test_publish_lan_hai_sau_khi_da_dien_so_van_qua(monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path) -> None:
    """Dòng release đã mang `(#9)` (lần publish trước điền + commit rồi push hỏng) vẫn là dòng của note: `(#PR)`
    hoặc `(#<số>)` đều khớp."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    goc_push = orch_mod.push_branch
    lan = {"n": 0}

    def push_hong_lan_hai(w: Any, **kw: Any) -> None:
        lan["n"] += 1
        if lan["n"] == 2:
            raise publish_mod.PublishError("mạng rớt")
        goc_push(w, **kw)

    monkeypatch.setattr(orch_mod, "push_branch", push_hong_lan_hai)
    monkeypatch.setattr(
        publish_mod.subprocess,
        "run",
        _RunSpy(
            script=[
                (0, "https://github.com/o/r/pull/9\n", ""),
                (1, "", "a pull request for branch already exists: https://github.com/o/r/pull/9\n"),
            ],
            calls=[],
        ),
    )
    with pytest.raises(publish_mod.PublishError):
        o.publish(wt.ticket_id, wt, now=NOW)

    pr = o.publish(wt.ticket_id, wt, now=NOW)

    assert pr is not None and pr.number == 9 and o.notes[wt.ticket_id].pr_number == 9


# ---------- fail closed ----------


def test_publish_tu_choi_khi_worktree_mat(repo: Path, remote: Path, spy: _RunSpy) -> None:
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    _git(repo, "worktree", "remove", "--force", str(wt.path))

    with pytest.raises(EvidenceError, match="không đo được"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_khi_cay_da_do_khong_con_trong_kho(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """`patch_id` không tra được trong kho object (gc đã dọn, hay báo cáo mang id lạ) ⇒ không so được ⇒ từ chối."""
    o, wt = _da_do(repo, patch_identity=lambda _tid: "f" * 40)
    _ghi_release_va_commit(o, wt)

    with pytest.raises(EvidenceError, match="không đo được"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_khi_bao_cao_moi_nhat_khong_co_patch_id(repo: Path, remote: Path, spy: _RunSpy) -> None:
    """Báo cáo MỚI HƠN không mang `patch_id` lên bus sau `open_pr` thu hồi `verified` (ADR keeper 0001, b) —
    publish phải thấy sự thu hồi ấy, không chỉ tin rằng `release-notes` đã có."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    bao_cao = o.reports[wt.ticket_id].model_dump() | {"patch_id": None}
    o.bus.publish(Envelope(topic="verification-reports", key=wt.ticket_id, actor=VERIFIER_ACTOR, payload=bao_cao))
    assert wt.ticket_id not in o.verified

    with pytest.raises(EvidenceError, match="patch_id"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


def test_publish_tu_choi_bao_cao_khong_patch_id_ca_khi_tat_kiem_luc_nap(
    monkeypatch: pytest.MonkeyPatch, repo: Path, remote: Path, spy: _RunSpy
) -> None:
    """Chốt của publish tự đứng được: tắt phép kiểm ở đường nạp (`VERIFY_ON_APPLY`) để báo cáo không
    `patch_id` lọt vào `reports`, publish vẫn từ chối."""
    o, wt = _da_do(repo)
    _ghi_release_va_commit(o, wt)
    monkeypatch.setattr(KeeperOrchestrator, "VERIFY_ON_APPLY", False)
    bao_cao = o.reports[wt.ticket_id].model_dump() | {"patch_id": None}
    o.bus.publish(Envelope(topic="verification-reports", key=wt.ticket_id, actor=VERIFIER_ACTOR, payload=bao_cao))
    assert o.reports[wt.ticket_id].patch_id is None

    with pytest.raises(EvidenceError, match="patch_id"):
        o.publish(wt.ticket_id, wt, now=NOW)
    _khong_push_khong_gh(spy, remote, wt, o)


# ---------- CLI ----------


def test_cli_publish_tu_choi_code_chua_do_ma_loi_4(
    repo: Path, remote: Path, spy: _RunSpy, capsys: pytest.CaptureFixture[str]
) -> None:
    o, wt = _da_do(repo)
    (wt.path / "app.py").write_text("x = 3  # chưa đo\n", encoding="utf-8")
    _ghi_release_va_commit(o, wt)

    code = main(["publish", "--db", str(repo.parent / "keeper.sqlite"), "--repo", str(repo), wt.ticket_id])

    assert code == 4
    err = capsys.readouterr().err
    assert "app.py" in err and PR_PLACEHOLDER not in err
    assert spy.calls == [] and wt.branch not in _nhanh_tren_remote(remote, wt)


def test_unmeasured_changes_tu_choi_doi_kieu_file_du_noi_dung_y_het(repo: Path) -> None:
    """`CHANGELOG.md` đổi từ file thường thành symlink có đích là ĐÚNG dòng release của note: `diff-tree` báo `T`,
    và nếu coi nó như file mới thì mọi "dòng" của nó là dòng của note ⇒ lọt. Trạng thái `T` phải tự nó là lý do
    từ chối. Dựng hai cây bằng `mktree` (không cần quyền tạo symlink của hệ điều hành)."""
    o, wt = _da_do(repo)
    dong = o.notes[wt.ticket_id].changelog_line
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=dong,
                          capture_output=True, text=True, check=True).stdout.strip()

    def cay(mode: str) -> str:
        return subprocess.run(["git", "-C", str(repo), "mktree"], input=f"{mode} blob {blob}\tCHANGELOG.md\n",
                              capture_output=True, text=True, check=True).stdout.strip()

    assert unmeasured_changes(repo, cay("100644"), cay("120000"), o.notes[wt.ticket_id]) == ["T CHANGELOG.md"]
