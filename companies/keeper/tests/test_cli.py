"""BT5 — `keeper run --dry-run`: in kế hoạch mà KHÔNG chạm file nào.

Chiều thuận: hash cả cây thư mục trước/sau `--dry-run` phải BẰNG nhau.
Chiều ngược: bỏ `--dry-run` (chạy thật) → hash ĐỔI. Nếu hash không đổi ở chiều ngược thì phép đo vô nghĩa,
nên ca chiều ngược assert cả nội dung file đã đổi, không chỉ assert hash khác.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from keeper.cli import Plan, main, plan_for
from keeper.drift import CHANGELOG_RULE_CUTOFF
from keeper.events import Signal, Ticket


def cay_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts or not p.is_file():
            continue
        h.update(str(p.relative_to(root)).replace("\\", "/").encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    r = tmp_path / "chung"
    (r / "docs" / "sessions").mkdir(parents=True)
    (r / "docs" / "sessions" / ".gitkeep").write_text("", encoding="utf-8")
    (r / "CHANGELOG.md").write_text("# Nhật ký thay đổi\n\n- dòng cũ\n", encoding="utf-8")
    (r / "pyproject.toml").write_text('dependencies = ["pydantic>=2.6"]\n', encoding="utf-8")
    _git(r, "init", "-b", "main")
    _git(r, "add", "-A")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "khoi tao")
    return r


@pytest.fixture
def root(main_repo: Path) -> Path:
    """CLI chỉ ghi được trong worktree phụ (CHẶN-1)."""
    wt = main_repo.parent / "wt"
    _git(main_repo, "worktree", "add", "-b", "chore/keeper-t", str(wt), "HEAD")
    return wt


def _ticket(ticket_id: str, subject: str, tier: str = "low") -> dict:
    return Ticket(ticket_id=ticket_id, subject=subject, risk_tier=tier).model_dump()  # type: ignore[arg-type]


@pytest.fixture
def tickets(tmp_path: Path) -> Path:
    """File ticket nằm NGOÀI `root` để nó không lọt vào hash cây thư mục."""
    f = tmp_path / "tickets.json"
    f.write_text(json.dumps([
        _ticket("T-doc", "CHANGELOG.md"),
        _ticket("T-dep", "pydantic"),
        _ticket("T-golden", "tests/golden/x.json"),
        _ticket("T-prompt", "software-company/agents/builder.md", tier="high"),
    ]), encoding="utf-8")
    return f


def test_plan_for_xep_dung_thao_tac():
    assert plan_for(Ticket(ticket_id="a", subject="CHANGELOG.md", risk_tier="low")).operation == "fix_docs"
    assert plan_for(Ticket(ticket_id="a", subject="pydantic", risk_tier="medium")).operation == "bump_dependency"
    assert plan_for(Ticket(ticket_id="a", subject="tests/golden/x.json", risk_tier="low")).operation == "regen_derived"
    p = plan_for(Ticket(ticket_id="a", subject="keeper/skills/x.md", risk_tier="low"))
    assert p.operation == "needs_human"
    assert plan_for(Ticket(ticket_id="a", subject="pydantic", risk_tier="high")).operation == "needs_human"


def test_dry_run_in_ke_hoach_va_khong_cham_file_nao(root: Path, tickets: Path, capsys):
    truoc = cay_hash(root)
    assert main(["run", "--dry-run", "--tickets", str(tickets), "--root", str(root)]) == 0
    sau = cay_hash(root)
    assert sau == truoc
    out = capsys.readouterr().out
    for phan in ("T-doc", "fix_docs", "CHANGELOG.md", "T-dep", "bump_dependency", "T-golden", "regen_derived",
                 "T-prompt", "needs_human"):
        assert phan in out
    assert "CHẠY KHÔ" in out


def test_chieu_nguoc_chay_that_thi_hash_DOI(root: Path, tmp_path: Path, capsys):
    f = tmp_path / "mot.json"
    f.write_text(json.dumps([_ticket("T-doc", "CHANGELOG.md")]), encoding="utf-8")
    truoc = cay_hash(root)
    assert main(["run", "--tickets", str(f), "--root", str(root)]) == 0
    assert cay_hash(root) != truoc
    assert "T-doc" in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_chay_that_bo_qua_thao_tac_chua_noi_vao_cli(root: Path, tickets: Path, capsys):
    truoc = cay_hash(root)
    assert main(["run", "--tickets", str(tickets), "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "bỏ qua" in out
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") != ""
    assert cay_hash(root) != truoc  # chỉ T-doc được thi hành


def test_ticket_hong_thi_bao_loi_khong_no(root: Path, tmp_path: Path, capsys):
    f = tmp_path / "hong.json"
    f.write_text(json.dumps([{"ticket_id": "x"}]), encoding="utf-8")
    assert main(["run", "--dry-run", "--tickets", str(f), "--root", str(root)]) == 2
    assert "không đọc được" in capsys.readouterr().err


def test_khong_co_lenh_thi_tra_ma_khac_0(capsys):
    with pytest.raises(SystemExit):
        main([])


def test_plan_la_dataclass_doc_duoc():
    p = Plan(ticket_id="a", operation="fix_docs", files=["CHANGELOG.md"], reason="")
    assert "fix_docs" in str(p)


def test_root_la_bat_buoc_khong_con_mac_dinh_cham(tmp_path: Path, capsys):
    """CHẶN-1: `--root` không còn mặc định `"."` — gõ thiếu là lỗi tham số, không phải ghi vào thư mục hiện tại."""
    f = tmp_path / "t.json"
    f.write_text(json.dumps([_ticket("T-doc", "CHANGELOG.md")]), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["run", "--tickets", str(f)])
    assert e.value.code != 0
    assert "--root" in capsys.readouterr().err


def test_cli_tu_choi_ghi_vao_checkout_chung(main_repo: Path, tmp_path: Path, capsys):
    f = tmp_path / "t.json"
    f.write_text(json.dumps([_ticket("T-doc", "CHANGELOG.md")]), encoding="utf-8")
    truoc = cay_hash(main_repo)
    assert main(["run", "--tickets", str(f), "--root", str(main_repo)]) == 3
    assert cay_hash(main_repo) == truoc
    assert "worktree" in capsys.readouterr().err


def test_chieu_nguoc_cung_lenh_do_tren_worktree_phu_thi_GHI_THAT(root: Path, tmp_path: Path):
    """Chiều ngược của ca trên: đổi đúng một biến (checkout chung → worktree phụ) thì lệnh chạy và ghi thật."""
    f = tmp_path / "t2.json"
    f.write_text(json.dumps([_ticket("T-doc", "CHANGELOG.md")]), encoding="utf-8")
    assert main(["run", "--tickets", str(f), "--root", str(root)]) == 0
    assert "T-doc" in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_run_root_la_thu_muc_con_cua_worktree_ghi_tu_goc_worktree(root: Path, tmp_path: Path):
    """`--root` trỏ vào thư mục con của worktree phụ: đường dẫn trong ticket là đường dẫn repo, nên patch phải
    rơi vào đúng chỗ tính từ GỐC worktree. Chốt `refuse_shared_checkout` hỏi git (git tự dò lên gốc, nên qua) —
    file thì trước đây ghép từ `--root` nguyên văn, và lệnh ghi một `CHANGELOG.md` lạc vào thư mục con."""
    f = tmp_path / "t3.json"
    f.write_text(json.dumps([_ticket("T-doc", "CHANGELOG.md")]), encoding="utf-8")
    con = root / "docs" / "sessions"
    assert main(["run", "--tickets", str(f), "--root", str(con)]) == 0
    assert "T-doc" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not (con / "CHANGELOG.md").exists()


# ---------- CHẶN-4: đường cho NGƯỜI duyệt gate (`keeper gate`) ----------

@pytest.fixture
def khong_allowlist(monkeypatch):
    """Không ca gate nào được rẽ theo biến môi trường của máy đang chạy."""
    from keeper.core import CORE
    monkeypatch.delenv(CORE.approvers_env, raising=False)


def _orc_ticket_high(db: Path, repo: Path):
    """Một ticket `risk_tier=high` đã đủ bằng chứng, đang kẹt ở cổng `gate` — công ty tự khoá chính mình nếu
    không có đường cho người."""
    from datetime import UTC, datetime

    from keeper.events import RunOutcome
    from keeper.evidence import TRUSTED_VERIFIER, TwoWayEvidence
    from keeper.fakes import FakeGitHub
    from keeper.orchestrator import KeeperOrchestrator

    class _GH(FakeGitHub):
        def open_prs(self):
            return []

        def merged_prs(self, since):
            return []

    o = KeeperOrchestrator(db, repo, _GH())
    o.submit_signal(Signal(subject="requests", kind="dependency", detail="bump", semver_jump="major"))
    (t,) = o.tick(now=datetime(2026, 9, 9, tzinfo=UTC)).tickets
    cmd = "uv run pytest -q"
    o.record_verification(t.ticket_id, {"ticket_id": t.ticket_id}, TwoWayEvidence(
        cmd=cmd, before=RunOutcome(cmd=cmd, exit_code=1), after=RunOutcome(cmd=cmd, exit_code=0),
        verified_by=TRUSTED_VERIFIER))
    o.tick(now=datetime(2026, 9, 9, tzinfo=UTC))  # xin gate
    assert "gate" in o.pr_blockers(t)
    return o, t


def test_gate_list_rong(tmp_path: Path, khong_allowlist, capsys):
    assert main(["gate", "--db", str(tmp_path / "k.sqlite"), "list"]) == 0
    assert "không có gate chờ" in capsys.readouterr().out


def test_nguoi_duyet_qua_cli_thi_ticket_high_het_bi_chan(tmp_path: Path, khong_allowlist, capsys):
    db = tmp_path / "k.sqlite"
    o, t = _orc_ticket_high(db, tmp_path / "repo")
    assert main(["gate", "--db", str(db), "list"]) == 0
    assert t.ticket_id in capsys.readouterr().out
    assert main(["gate", "--db", str(db), "approve", t.ticket_id, "--by", "human:pm",
                 "--reason", "đã soi bằng chứng hai chiều"]) == 0
    o.bus.poll()
    assert "gate" not in o.pr_blockers(t), "quyết định của người phải tới được orchestrator qua bus"


def test_gate_decide_boi_actor_khong_phai_nguoi_bi_tu_choi(tmp_path: Path, khong_allowlist, capsys):
    """`trusted_decision`: chỉ NGƯỜI quyết được. Một actor máy khai `--by patcher` không đóng được gate."""
    db = tmp_path / "k.sqlite"
    o, t = _orc_ticket_high(db, tmp_path / "repo")
    assert main(["gate", "--db", str(db), "approve", t.ticket_id, "--by", "patcher", "--reason", "x"]) == 3
    assert "không phải người" in capsys.readouterr().err
    o.bus.poll()
    assert "gate" in o.pr_blockers(t) and t.ticket_id in o.gate.pending


def test_gate_decide_subject_khong_ton_tai(tmp_path: Path, khong_allowlist, capsys):
    assert main(["gate", "--db", str(tmp_path / "k.sqlite"), "reject", "KEEP:khong-co",
                 "--by", "human:pm", "--reason", "x"]) == 2
    assert "không có gate chờ" in capsys.readouterr().err


def test_gate_decide_vi_pham_four_eyes(tmp_path: Path, khong_allowlist, capsys):
    db = tmp_path / "k.sqlite"
    assert main(["gate", "--db", str(db), "request", "patch", "KEEP:x", "--by", "human:pm"]) == 0
    assert main(["gate", "--db", str(db), "approve", "KEEP:x", "--by", "human:pm", "--reason", "tự duyệt"]) == 3
    assert "four-eyes" in capsys.readouterr().err


def test_gate_request_boi_vai_ngoai_allowlist_bi_tu_choi(tmp_path: Path, khong_allowlist, capsys):
    assert main(["gate", "--db", str(tmp_path / "k.sqlite"), "request", "patch", "KEEP:x",
                 "--by", "patcher"]) == 3
    assert "quyền" in capsys.readouterr().err


# --- lệnh `drift`: cổng máy cho luật cấm §5 + luật bắt buộc §10 (bộ dò đã có từ BT-keeper nhưng
# --- không workflow nào gọi, nên #192/#208/#209 merge thiếu dòng CHANGELOG mà CI vẫn xanh).

def _repo_sach(tmp_path: Path) -> Path:
    """Repo tối thiểu mà cả ba phép của `drift.scan` đều không có gì để nói."""
    repo = tmp_path / "repo"
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / "companies" / "software-company" / "tests" / "golden" / "agents").mkdir(parents=True)
    (repo / "companies" / "software-company" / "agents").mkdir(parents=True)
    (repo / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    return repo


def test_drift_doc_cong_ty_o_companies_software_company(tmp_path: Path, capsys):
    """ADR-0011 dời công ty xuống `companies/software-company/`. `drift` phải theo đường dẫn mới, nếu không nó
    không thấy file nguồn nào và báo mọi bản dẫn xuất là lệch — báo động giả làm CI đỏ mãi."""
    repo = _repo_sach(tmp_path)
    (repo / "companies" / "software-company" / "agents" / "engineering").mkdir(parents=True)
    (repo / "companies" / "software-company" / "agents" / "engineering" / "builder.md").write_text(
        "---\nid: builder\nversion: 3\n---\n", encoding="utf-8")
    (repo / ".claude" / "agents" / "sc-builder.md").write_text(
        "<!-- SINH TỰ ĐỘNG từ agents/engineering/builder.md version=3 -->\n", encoding="utf-8")
    assert main(["drift", "--repo", str(repo)]) == 0
    assert "sạch" in capsys.readouterr().out


def test_drift_sach_thi_thoat_0(tmp_path: Path, capsys):
    repo = _repo_sach(tmp_path)
    assert main(["drift", "--repo", str(repo)]) == 0
    assert "sạch" in capsys.readouterr().out


def test_drift_co_tin_hieu_thi_thoat_1_va_in_ra(tmp_path: Path, capsys):
    """Chiều ngược: bản dẫn xuất trỏ nguồn không tồn tại → thoát KHÁC 0 để CI đỏ.

    Đây đúng hình dạng bug thật đã sửa cùng gói: `sc-supervisor.md` trỏ `agents/supervision/` trong khi thư
    mục thật là `agents/supervisor/`."""
    repo = _repo_sach(tmp_path)
    (repo / ".claude" / "agents" / "sc-foo.md").write_text(
        "<!-- SINH TỰ ĐỘNG từ agents/supervision/foo.md version=1 — sửa nguồn rồi chạy make subagents -->\n",
        encoding="utf-8")

    assert main(["drift", "--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "DRIFT sc-foo.md" in out
    assert "1 tín hiệu lệch" in out


def test_drift_tu_thu_muc_con_ra_dung_ket_qua_nhu_o_goc(tmp_path: Path, capsys):
    """`--repo` là thư mục con (mặc định `.` khi đứng ở `companies/keeper`) phải soi đúng repo như ở gốc.

    Trước đây `git log` tự dò lên gốc còn mọi đường dẫn file ghép từ `--repo` nguyên văn. Đo 2026-09-28 từ
    `companies/keeper`: 200 tín hiệu "thiếu dòng CHANGELOG" giả, còn ba phép kia lặng lẽ không soi gì. Ca này
    có đủ hai chiều hỏng: một lệch THẬT chỉ phép (a) thấy (mất nó là âm tính giả) và một PR ĐÃ có
    dòng CHANGELOG (báo thiếu là dương tính giả)."""
    repo = _repo_sach(tmp_path)
    (repo / ".claude" / "agents" / "sc-foo.md").write_text(
        "<!-- SINH TỰ ĐỘNG từ agents/supervision/foo.md version=1 -->\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n- feat: x (#7)\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    ngay = (CHANGELOG_RULE_CUTOFF + timedelta(days=1)).isoformat()
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "feat: x (#7)", "--date", ngay)

    assert main(["drift", "--repo", str(repo)]) == 1
    o_goc = capsys.readouterr().out
    assert "DRIFT sc-foo.md" in o_goc and "pr-7" not in o_goc
    assert main(["drift", "--repo", str(repo / "companies" / "software-company")]) == 1
    assert capsys.readouterr().out == o_goc
