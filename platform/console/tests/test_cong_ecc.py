"""Cổng offline cho tập ECC (`affaan-m/ECC`) vendor vào `.claude/` — ADR gốc 0028 (thay đường plugin của 0027).

Vì sao cần cổng riêng ngoài `scripts/ecc_vendor.py check`: bước `check` cần tải ECC từ GitHub nên chỉ chạy trong một
job CI riêng; cổng này chạy ở mọi máy, không mạng, và **không dùng lại mã của script** — một lỗi trong script không
che được chính nó. Nó canh bốn chuyện mà sửa tay sẽ làm lệch im lặng:

1. tệp `ecc-*` trên đĩa đúng tập và đúng sha256 ghi trong lock (sửa tay một tệp là đỏ ngay, không chờ CI);
2. tên mang tiền tố `ecc-`, frontmatter đủ để Claude Code liệt kê, tổng mô tả trong ngân sách;
3. không còn plugin, hook hay biến môi trường ECC nào trong settings (hai nguồn sự thật = skill hiện hai lần);
4. nội dung đi qua cùng bộ quét tài sản prompt của công ty (`company.assetscan`, ADR-0022), miễn trừ phải có lý do.

Đặt ở `platform/console/tests/` theo lối các phép canh cấp gốc khác (`test_cong_khung.py`, `test_cong_repo.py`).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from company.assetscan import SEVERITY, scan_text

ROOT = Path(__file__).resolve().parents[3]
CLAUDE = ROOT / ".claude"
SETTINGS = CLAUDE / "settings.json"
LOCK = ROOT / "docs" / "integrations" / "ecc.lock.json"
LICENSE = ROOT / "docs" / "integrations" / "ecc.LICENSE"
ADR = ROOT / "docs" / "adr" / "0028-vendor-ecc-chon-loc-vao-claude.md"
KINDS = ("skills", "commands", "agents")


def _lock() -> dict[str, Any]:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def _settings() -> dict[str, Any]:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _vendored() -> list[str]:
    """Mọi tệp mang tiền tố `ecc-` trong ba thư mục Claude Code tự quét, cộng giấy phép — quét đĩa, không đọc lock."""
    found = [p for p in (CLAUDE / "skills").glob("ecc-*/**/*") if p.is_file()]
    found += [p for kind in ("commands", "agents") for p in (CLAUDE / kind).glob("ecc-*.md")]
    found += [LICENSE] if LICENSE.exists() else []
    return sorted(p.relative_to(ROOT).as_posix() for p in found)


def _main_files() -> dict[str, tuple[str, str]]:
    """Tệp Claude Code liệt kê → (loại, tên mục không tiền tố)."""
    out: dict[str, tuple[str, str]] = {}
    for kind, names in _lock()["select"].items():
        for name in names:
            rel = f".claude/skills/ecc-{name}/SKILL.md" if kind == "skills" else f".claude/{kind}/ecc-{name}.md"
            out[rel] = (kind, name)
    return out


def _frontmatter(rel: str) -> dict[str, Any]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{rel}: thiếu frontmatter — Claude Code không liệt kê"
    meta = yaml.safe_load(m.group(1))
    assert isinstance(meta, dict), f"{rel}: frontmatter không phải ánh xạ YAML"
    return meta


def test_lock_ghim_dung_mot_commit() -> None:
    lock = _lock()
    assert lock["repository"] == "affaan-m/ECC" and lock["license"] == "MIT"
    assert re.fullmatch(r"[0-9a-f]{40}", lock["revision"]), "sha đủ 40 ký tự hex — tag có thể bị đẩy lại"
    assert lock["adr"] == ADR.relative_to(ROOT).as_posix() and ADR.is_file()


def test_tep_ecc_tren_dia_dung_tap_va_dung_sha256_cua_lock() -> None:
    """Sửa tay một tệp vendor, thêm hay xoá một tệp `ecc-*` đều đỏ ở đây — không phải đợi job CI có mạng."""
    files = {f["path"]: f["sha256"] for f in _lock()["files"]}
    assert _vendored() == sorted(files), "tập tệp `ecc-*` trên đĩa khác lock: chạy `make ecc-vendor`, không sửa tay"
    lech = [
        rel
        for rel, sha in files.items()
        if hashlib.sha256((ROOT / rel).read_text(encoding="utf-8").encode("utf-8")).hexdigest() != sha
    ]
    assert lech == [], f"tệp vendor bị sửa tay (sha256 khác lock): {lech}"


def test_moi_muc_da_chon_co_tep_chinh_va_khong_tep_nao_mo_coi() -> None:
    mains = _main_files()
    vendored = set(_vendored())
    assert set(mains) <= vendored, f"mục trong `select` chưa sinh: {sorted(set(mains) - vendored)}"
    owners = {rel.split("/")[2] for rel in mains if rel.startswith(".claude/skills/")}
    mo_coi = [
        rel
        for rel in vendored - set(mains)
        if rel != LICENSE.relative_to(ROOT).as_posix() and rel.split("/")[2] not in owners
    ]
    assert mo_coi == [], f"tệp `ecc-*` không thuộc mục nào trong `select`: {mo_coi}"


@pytest.mark.parametrize("rel", sorted(_main_files()))
def test_ten_mang_tien_to_va_frontmatter_du(rel: str) -> None:
    kind, name = _main_files()[rel]
    meta = _frontmatter(rel)
    if kind != "commands":
        assert meta.get("name") == f"ecc-{name}", f"{rel}: `name` phải là `ecc-{name}` — mất tiền tố là đụng tên"
    assert isinstance(meta.get("description"), str) and meta["description"].strip(), f"{rel}: thiếu description"


def test_tong_mo_ta_trong_ngan_sach_va_khop_so_do() -> None:
    """Toàn bộ ECC là 116 816 ký tự mô tả (ADR-0027) — vượt ngân sách liệt kê skill nên skill hiếm dùng mất mô tả."""
    lock = _lock()
    total = sum(len(_frontmatter(rel)["description"]) for rel in _main_files())
    assert total <= lock["budget_description_chars"]
    assert total == lock["measured"]["description_chars"]


def test_moi_tep_vendor_mang_ghi_chu_nguon_va_luat_repo_thang() -> None:
    rev = _lock()["revision"]
    for rel in _vendored():
        if rel.endswith(".md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert f"@{rev} (" in text and "không sửa tay" in text, f"{rel}: thiếu ghi chú nguồn"
            assert "`AGENTS.md` thắng khi trùng" in text and "fail_under = 100" in text, rel


def test_chon_va_loai_khong_giao_nhau_va_deu_co_ly_do() -> None:
    lock = _lock()
    chon = {name: why for kind in KINDS for name, why in lock["select"].get(kind, {}).items()}
    assert set(lock["select"]) <= set(KINDS)
    # `rejected` nhận mẫu (`orch-*`): chọn một thành viên của họ đã loại cũng là giao nhau.
    giao = [n for n in chon if any(fnmatch.fnmatchcase(n, mau) for mau in lock["rejected"])]
    assert giao == [], f"vừa chọn vừa loại: {giao}"
    ngan = [n for n, why in {**chon, **lock["rejected"]}.items() if len(why) < 20]
    assert ngan == [], f"chọn/loại mà không nói vì sao (< 20 ký tự): {ngan}"


def test_giay_phep_mit_di_kem() -> None:
    text = LICENSE.read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Affaan Mustafa" in text


def test_khong_con_plugin_hook_hay_env_ecc() -> None:
    """Plugin và vendor song song = cùng skill hiện hai lần (`ecc:x`, `ecc-x`) và hook node không ghim chạy lại."""
    s = _settings()
    assert not [k for k in s.get("extraKnownMarketplaces", {}) if "ecc" in k.lower()]
    assert not [k for k in s.get("env", {}) if k.startswith("ECC_")]
    # Máy đã cài theo hướng dẫn cũ (ADR-0027) hoặc cài bản chính chủ trôi theo `main` của họ: project scope tắt cả hai.
    assert s["enabledPlugins"] == {"ecc@xagents-ecc": False, "ecc@ecc": False}
    lenh = [h["command"] for groups in s["hooks"].values() for g in groups for h in g["hooks"]]
    assert all(c.startswith("${CLAUDE_PROJECT_DIR}/.claude/hooks/") for c in lenh), lenh
    assert not (CLAUDE / "rules").exists(), "rule ECC (coverage 80%, commit không scope) trái AGENTS.md"


def test_qua_bo_quet_tai_san_prompt_cua_cong_ty() -> None:
    """Tệp vendor đi thẳng vào phiên Claude Code như `.claude/agents/sc-*` — cùng bộ mẫu `guard.PATTERNS` (ADR-0022).
    Miễn trừ ghi trong lock theo khoá `<đường dẫn>::<luật>`, có lý do; miễn trừ không còn khớp gì là đỏ."""
    waivers = _lock()["assetscan_waivers"]
    assert all(len(why) >= 20 for why in waivers.values()), "miễn trừ không lý do"
    high = {
        f"{rel}::{f.rule}": f
        for rel in _vendored()
        for f in scan_text((ROOT / rel).read_text(encoding="utf-8"), rel)
        if SEVERITY[f.rule] == "high"
    }
    assert sorted(set(high) - set(waivers)) == [], [high[k] for k in sorted(set(high) - set(waivers))]
    assert sorted(set(waivers) - set(high)) == [], "miễn trừ không còn khớp phát hiện nào — xoá khỏi lock"


def test_adr_va_claude_md_tro_dung_cach_dung() -> None:
    assert _lock()["revision"] in ADR.read_text(encoding="utf-8")
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "0028" in claude_md and "/ecc-" in claude_md
    assert "/ecc:" not in claude_md, "tiền tố plugin cũ: lệnh `/ecc:` không còn tồn tại"
