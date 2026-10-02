"""`scripts/ecc_vendor.py` — vendor ECC chọn lọc vào `.claude/` có tiền tố `ecc-`, ghim commit + sha256 (ADR-0028).

Mọi ca dựng một "ECC giả" là một repo git thật trong `tmp_path`: script kiểm `HEAD == revision` nên không giả được
bằng thư mục trơn. Không gọi mạng — `fetch` đi qua URI `file://`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "ecc_vendor.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ecc_vendor", SCRIPT)
    assert spec and spec.loader, f"Không tải được script {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def V() -> ModuleType:
    return _load()


SKILL = """---
name: alpha-skill
description: Alpha skill. Pair with `beta-cmd` and gamma-agent.
---

# Alpha

Run /beta-cmd then ask the gamma-agent agent. See `alpha-skill` and **alpha-skill**.
Also skill: alpha-skill, skills/alpha-skill/extra.md and agents/gamma-agent.md.
Plain words: alpha-skill stays, /not-vendored stays, `not-vendored` stays, delta-agent stays.
Kind mismatch stays: commands/alpha-skill.
"""

EXTRA = "# Extra\n\nSee /beta-cmd.\n"

COMMAND = """---
description: Beta command dispatches gamma-agent.
---

Use `alpha-skill`.
"""

AGENT = """---
name: gamma-agent
description: Gamma agent.
tools: Read, Grep
model: sonnet
---

Body mentions gamma-agent.
"""

LICENSE = "MIT License\n\nCopyright (c) 2026 Affaan Mustafa\n"


def _git(cwd: Path, *a: str) -> str:
    kq = subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8")
    return kq.stdout.strip()


def _write(base: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))


def _commit(src: Path) -> str:
    _git(src, "add", "-A")
    _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    return _git(src, "rev-parse", "HEAD")


@pytest.fixture
def src(tmp_path: Path) -> Path:
    s = tmp_path / "ecc"
    s.mkdir()
    _git(s, "init", "-q", "-b", "main")
    _write(
        s,
        {
            "skills/alpha-skill/SKILL.md": SKILL,
            "skills/alpha-skill/extra.md": EXTRA,
            "skills/not-vendored/SKILL.md": "---\nname: not-vendored\ndescription: N.\n---\n",
            "commands/beta-cmd.md": COMMAND,
            "agents/gamma-agent.md": AGENT,
            "agents/delta-agent.md": "---\nname: delta-agent\ndescription: D.\n---\n",
            "LICENSE": LICENSE,
        },
    )
    _commit(s)
    return s


def _lock_for(src: Path, **override: object) -> dict:
    lock: dict = {
        "repository": "x/ECC",
        "tag": "v0",
        "revision": _git(src, "rev-parse", "HEAD"),
        "version": "0",
        "license": "MIT",
        "adr": "docs/adr/0028-vendor-ecc-chon-loc-vao-claude.md",
        "budget_description_chars": 1000,
        "select": {
            "skills": {"alpha-skill": "lý do chọn alpha"},
            "commands": {"beta-cmd": "lý do chọn beta"},
            "agents": {"gamma-agent": "lý do chọn gamma"},
        },
        "rejected": {"not-vendored": "lý do loại đủ dài để đọc được"},
    }
    lock.update(override)
    return lock


@pytest.fixture
def root(tmp_path: Path, src: Path) -> Path:
    r = tmp_path / "repo"
    (r / "docs" / "integrations").mkdir(parents=True)
    (r / "docs" / "integrations" / "ecc.lock.json").write_text(json.dumps(_lock_for(src)), encoding="utf-8")
    return r


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


# --- render: đổi tên, đổi tham chiếu, ghi chú nguồn ---------------------------------------------------------------

EXPECTED = {
    ".claude/skills/ecc-alpha-skill/SKILL.md": "skills/alpha-skill/SKILL.md",
    ".claude/skills/ecc-alpha-skill/extra.md": "skills/alpha-skill/extra.md",
    ".claude/commands/ecc-beta-cmd.md": "commands/beta-cmd.md",
    ".claude/agents/ecc-gamma-agent.md": "agents/gamma-agent.md",
    "docs/integrations/ecc.LICENSE": "LICENSE",
}


def test_render_chi_chep_muc_da_chon_vao_dung_cho(V: ModuleType, src: Path) -> None:
    out = V.render(src, _lock_for(src))
    assert {rel: source for rel, (source, _) in out.items()} == EXPECTED
    assert out["docs/integrations/ecc.LICENSE"][1] == LICENSE


def test_render_doi_ten_frontmatter_skill_va_agent(V: ModuleType, src: Path) -> None:
    out = V.render(src, _lock_for(src))
    assert out[".claude/skills/ecc-alpha-skill/SKILL.md"][1].startswith("---\nname: ecc-alpha-skill\n")
    assert out[".claude/agents/ecc-gamma-agent.md"][1].startswith("---\nname: ecc-gamma-agent\n")
    assert "\nmodel: sonnet\n" in out[".claude/agents/ecc-gamma-agent.md"][1], "giữ nguyên trường khác"


def test_render_doi_tham_chieu_dang_tuong_minh(V: ModuleType, src: Path) -> None:
    out = V.render(src, _lock_for(src))
    skill = out[".claude/skills/ecc-alpha-skill/SKILL.md"][1]
    for doi in (
        "Run /ecc-beta-cmd then ask the ecc-gamma-agent agent.",
        "See `ecc-alpha-skill` and **ecc-alpha-skill**.",
        "Also skill: ecc-alpha-skill, .claude/skills/ecc-alpha-skill/extra.md and .claude/agents/ecc-gamma-agent.md.",
        "description: Alpha skill. Pair with `ecc-beta-cmd` and ecc-gamma-agent.",
    ):
        assert doi in skill
    assert "See /ecc-beta-cmd." in out[".claude/skills/ecc-alpha-skill/extra.md"][1]
    assert "description: Beta command dispatches ecc-gamma-agent." in out[".claude/commands/ecc-beta-cmd.md"][1]
    assert "Use `ecc-alpha-skill`." in out[".claude/commands/ecc-beta-cmd.md"][1]
    assert "Body mentions ecc-gamma-agent." in out[".claude/agents/ecc-gamma-agent.md"][1]


def test_render_khong_doi_tu_thuong_va_muc_khong_vendor(V: ModuleType, src: Path) -> None:
    """Tên skill viết trơn có thể là từ thường ("error-handling patterns") — chỉ dạng tường minh mới đổi."""
    skill = V.render(src, _lock_for(src))[".claude/skills/ecc-alpha-skill/SKILL.md"][1]
    assert "Plain words: alpha-skill stays, /not-vendored stays, `not-vendored` stays, delta-agent stays." in skill
    assert "Kind mismatch stays: commands/alpha-skill." in skill
    assert "ecc-ecc-" not in skill


def test_render_ghi_chu_nguon_ngay_sau_frontmatter(V: ModuleType, src: Path) -> None:
    lock = _lock_for(src)
    for rel, (source, text) in V.render(src, lock).items():
        if rel.endswith("LICENSE"):
            continue
        body = text.partition("\n---\n")[2] if text.startswith("---\n") else text
        dong = body.lstrip("\n").splitlines()
        assert dong[0].startswith("<!-- Sinh bởi scripts/ecc_vendor.py"), rel
        assert lock["revision"] in dong[0] and f"({source})" in dong[0], rel
        assert any("`AGENTS.md`" in d and "fail_under = 100" in d for d in dong[1:4]), rel


def test_render_chuan_hoa_crlf_cua_nguon(V: ModuleType, src: Path) -> None:
    """Checkout trên Windows (`core.autocrlf=true`): commit vẫn LF, đĩa là CRLF. Không commit bản CRLF — autocrlf
    chuẩn hoá nó về đúng blob cũ, `git commit` báo "nothing to commit" (đỏ trên runner Windows của #377)."""
    _write(src, {"commands/beta-cmd.md": COMMAND.replace("\n", "\r\n")})
    assert "\r" not in V.render(src, _lock_for(src))[".claude/commands/ecc-beta-cmd.md"][1]


# --- render: từ chối -----------------------------------------------------------------------------------------------


def _loi(V: ModuleType, src: Path, lock: dict) -> str:
    with pytest.raises(V.VendorError) as e:
        V.render(src, lock)
    return str(e.value)


def test_head_khac_revision_bi_tu_choi(V: ModuleType, src: Path) -> None:
    assert "revision" in _loi(V, src, _lock_for(src, revision="0" * 40))


def test_muc_chon_khong_ton_tai_bi_tu_choi(V: ModuleType, src: Path) -> None:
    lock = _lock_for(src)
    lock["select"]["agents"]["khong-co"] = "lý do"
    assert "khong-co" in _loi(V, src, lock)


def test_muc_vua_chon_vua_loai_bi_tu_choi(V: ModuleType, src: Path) -> None:
    lock = _lock_for(src)
    lock["rejected"]["beta-cmd"] = "lý do loại"
    assert "beta-cmd" in _loi(V, src, lock)


def test_muc_khop_mau_loai_bi_tu_choi(V: ModuleType, src: Path) -> None:
    """`rejected` nhận mẫu (`orch-*`, `hookify*`): loại cả họ một lần, chọn nhầm một thành viên vẫn bị chặn."""
    lock = _lock_for(src)
    lock["rejected"]["beta-*"] = "lý do loại cả họ beta"
    assert "beta-cmd" in _loi(V, src, lock)


def test_trung_ten_giua_hai_loai_bi_tu_choi(V: ModuleType, src: Path) -> None:
    """Skill và lệnh cùng tên đều thành `/ecc-<tên>` — một cái sẽ che cái kia."""
    _write(src, {"commands/alpha-skill.md": "---\ndescription: trùng.\n---\n"})
    lock = _lock_for(src, revision=_commit(src))
    lock["select"]["commands"]["alpha-skill"] = "lý do"
    assert "alpha-skill" in _loi(V, src, lock)


@pytest.mark.parametrize(
    "dong",
    [
        "node ${CLAUDE_PLUGIN_ROOT}/x.js",
        "cat ~/.claude/settings.json",
        "write to .claude/reviews/out.md",
        "node scripts/setup.js",
        "npx -y some-tool",
        "npx --yes some-tool",
        "run /ecc:plan first",
    ],
)
def test_dau_hieu_chi_chay_khi_la_plugin_bi_tu_choi(V: ModuleType, src: Path, dong: str) -> None:
    _write(src, {"skills/alpha-skill/extra.md": EXTRA + dong + "\n"})
    lock = _lock_for(src, revision=_commit(src))
    assert "skills/alpha-skill/extra.md" in _loi(V, src, lock)


def test_tep_khong_phai_md_bi_tu_choi(V: ModuleType, src: Path) -> None:
    _write(src, {"skills/alpha-skill/run.py": "print(1)\n"})
    lock = _lock_for(src, revision=_commit(src))
    assert "run.py" in _loi(V, src, lock)


def test_symlink_bi_tu_choi(V: ModuleType, src: Path) -> None:
    (src / "skills" / "alpha-skill" / "link.md").symlink_to(src / "LICENSE")
    lock = _lock_for(src, revision=_commit(src))
    assert "link.md" in _loi(V, src, lock)


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("skills/alpha-skill/SKILL.md", "# không có frontmatter\n"),
        ("skills/alpha-skill/SKILL.md", "---\nname: ten-khac\ndescription: x.\n---\n"),
        ("skills/alpha-skill/SKILL.md", '---\nname: "alpha-skill"\ndescription: x.\n---\n'),
        ("agents/gamma-agent.md", "---\nname: gamma-agent\n---\n"),
        ("commands/beta-cmd.md", "---\ndescription: ''\n---\n"),
        ("commands/beta-cmd.md", "---\n- danh sách\n---\n"),
    ],
)
def test_frontmatter_sai_bi_tu_choi(V: ModuleType, src: Path, rel: str, text: str) -> None:
    _write(src, {rel: text})
    lock = _lock_for(src, revision=_commit(src))
    assert rel in _loi(V, src, lock)


def test_thieu_giay_phep_bi_tu_choi(V: ModuleType, src: Path) -> None:
    (src / "LICENSE").unlink()
    lock = _lock_for(src, revision=_commit(src))
    assert "LICENSE" in _loi(V, src, lock)


def test_vuot_ngan_sach_mo_ta_bi_tu_choi(V: ModuleType, src: Path) -> None:
    assert "budget_description_chars" in _loi(V, src, _lock_for(src, budget_description_chars=10))


# --- build / check -------------------------------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def test_build_ghi_tep_lock_va_don_tep_ecc_cu(V: ModuleType, src: Path, root: Path) -> None:
    _write(
        root,
        {
            ".claude/skills/ecc-old/SKILL.md": "cũ",
            ".claude/commands/ecc-old.md": "cũ",
            ".claude/agents/ecc-old.md": "cũ",
            ".claude/agents/sc-qa.md": "của repo",
            ".claude/commands/gate.md": "của repo",
            ".claude/skills/khac/SKILL.md": "của repo",
        },
    )
    lock = V.build(root, src)
    assert not (root / ".claude/skills/ecc-old").exists()
    assert not (root / ".claude/commands/ecc-old.md").exists()
    assert not (root / ".claude/agents/ecc-old.md").exists()
    for giu in (".claude/agents/sc-qa.md", ".claude/commands/gate.md", ".claude/skills/khac/SKILL.md"):
        assert _read(root, giu) == "của repo"
    assert [f["path"] for f in lock["files"]] == sorted(EXPECTED)
    for f in lock["files"]:
        assert f["source"] == EXPECTED[f["path"]]
        assert f["sha256"] == _sha(_read(root, f["path"]))
    assert json.loads(_read(root, "docs/integrations/ecc.lock.json")) == lock
    assert lock["select"] == _lock_for(src)["select"] and lock["rejected"] == _lock_for(src)["rejected"]
    m = lock["measured"]
    assert (m["skills"], m["commands"], m["agents"], m["files"]) == (1, 1, 1, 5)
    assert m["upstream"] == {"skills": 2, "commands": 1, "agents": 2}
    assert m["bytes"] == sum(len(_read(root, rel).encode("utf-8")) for rel in EXPECTED)
    assert m["description_chars"] == len("Alpha skill. Pair with `ecc-beta-cmd` and ecc-gamma-agent.") + len(
        "Beta command dispatches ecc-gamma-agent."
    ) + len("Gamma agent.")


def test_build_ghi_lf_va_lock_tat_dinh(V: ModuleType, src: Path, root: Path) -> None:
    V.build(root, src)
    lan1 = (root / "docs/integrations/ecc.lock.json").read_bytes()
    V.build(root, src)
    assert (root / "docs/integrations/ecc.lock.json").read_bytes() == lan1
    assert lan1.endswith(b"}\n") and b"\r" not in lan1
    assert all(b"\r" not in (root / rel).read_bytes() for rel in EXPECTED)


def test_check_sach_ngay_sau_build(V: ModuleType, src: Path, root: Path) -> None:
    V.build(root, src)
    assert V.check(root, src) == []


def test_check_chap_nhan_crlf_tren_dia(V: ModuleType, src: Path, root: Path) -> None:
    """Windows `core.autocrlf=true` checkout tệp `.md` thành CRLF — không phải trôi."""
    V.build(root, src)
    p = root / ".claude/commands/ecc-beta-cmd.md"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert V.check(root, src) == []


def test_check_bao_tep_sua_tay_thua_thieu_va_lock_lech(V: ModuleType, src: Path, root: Path) -> None:
    V.build(root, src)
    (root / ".claude/agents/ecc-gamma-agent.md").write_text("sửa tay\n", encoding="utf-8")
    (root / ".claude/skills/ecc-alpha-skill/extra.md").unlink()
    _write(root, {".claude/commands/ecc-la.md": "thừa\n", ".claude/skills/ecc-la/SKILL.md": "thừa\n"})
    lock_path = root / "docs/integrations/ecc.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["measured"]["files"] = 99
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    loi = "\n".join(V.check(root, src))
    for can in (
        "lệch: .claude/agents/ecc-gamma-agent.md",
        "thiếu: .claude/skills/ecc-alpha-skill/extra.md",
        "thừa: .claude/commands/ecc-la.md",
        "thừa: .claude/skills/ecc-la/SKILL.md",
        "lock lệch: measured",
    ):
        assert can in loi
    assert "lock lệch: files" not in loi


def test_check_bao_hash_trong_lock_bi_sua(V: ModuleType, src: Path, root: Path) -> None:
    """Sửa cả tệp lẫn hash trong lock vẫn lộ: check so với bản sinh lại từ nguồn, không so với lock."""
    V.build(root, src)
    lock_path = root / "docs/integrations/ecc.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["files"][0]["sha256"] = "0" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert V.check(root, src) == ["lock lệch: files"]


# --- fetch / main --------------------------------------------------------------------------------------------------


def test_fetch_lay_dung_commit_ghim(V: ModuleType, src: Path, tmp_path: Path) -> None:
    sha = _git(src, "rev-parse", "HEAD")
    _write(src, {"commands/beta-cmd.md": COMMAND + "mới hơn bản ghim\n"})
    _commit(src)
    dest = V.fetch(src.as_uri(), sha, tmp_path / "lay")
    assert _git(dest, "rev-parse", "HEAD") == sha
    assert (dest / "commands/beta-cmd.md").read_text(encoding="utf-8") == COMMAND


def test_main_build_check_va_ma_thoat(V: ModuleType, src: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert V.main(["build", "--src", str(src), "--root", str(root)]) == 0
    assert "5 tệp" in capsys.readouterr().out
    assert V.main(["check", "--src", str(src), "--root", str(root)]) == 0
    (root / ".claude/commands/ecc-beta-cmd.md").write_text("sửa tay\n", encoding="utf-8")
    assert V.main(["check", "--src", str(src), "--root", str(root)]) == 1
    err = capsys.readouterr().err
    assert "lệch: .claude/commands/ecc-beta-cmd.md" in err and "make ecc-vendor" in err


def test_main_tu_fetch_khi_khong_co_src(V: ModuleType, src: Path, root: Path) -> None:
    assert V.main(["build", "--root", str(root), "--remote", src.as_uri()]) == 0
    assert V.main(["check", "--root", str(root), "--remote", src.as_uri()]) == 0


def test_main_loi_vendor_in_stderr_ma_1(
    V: ModuleType, src: Path, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = root / "docs/integrations/ecc.lock.json"
    lock_path.write_text(json.dumps(_lock_for(src, revision="0" * 40)), encoding="utf-8")
    assert V.main(["check", "--src", str(src), "--root", str(root)]) == 1
    assert "revision" in capsys.readouterr().err


def test_chay_nhu_script_tu_goc_repo(src: Path, root: Path) -> None:
    """Đúng lệnh `make ecc-vendor`/CI gọi: `python scripts/ecc_vendor.py …`, in tiếng Việt không vỡ mã hoá."""
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    kq = subprocess.run(
        [sys.executable, str(SCRIPT), "build", "--src", str(src), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert kq.returncode == 0, kq.stderr
    assert "tệp" in kq.stdout
