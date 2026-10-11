"""Cổng offline cho mọi tập skill vendor vào `.claude/` — ADR gốc 0028 (ECC), 0030 (đa nguồn).

Mỗi nguồn là một lock `docs/integrations/<tên>.lock.json` có khoá `select`, mang tiền tố riêng (`ecc-`, `mp-`). Mọi
phép canh dưới đây chạy cho từng lock.

Vì sao cần cổng riêng ngoài `scripts/vendor_skills.py check`: bước `check` cần tải nguồn từ GitHub nên chỉ chạy trong
một job CI riêng; cổng này chạy ở mọi máy, không mạng, và **không dùng lại mã của script** — một lỗi trong script không
che được chính nó. Nó canh bốn chuyện mà sửa tay sẽ làm lệch im lặng:

1. tệp `<tiền tố>*` trên đĩa đúng tập và đúng sha256 ghi trong lock (sửa tay một tệp là đỏ ngay, không chờ CI);
2. tên mang tiền tố, frontmatter đủ để Claude Code liệt kê, tổng mô tả trong ngân sách của lock và trần chung;
3. không còn plugin, hook hay biến môi trường của nguồn nào trong settings (hai nguồn sự thật = skill hiện hai lần);
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
pytestmark = pytest.mark.cong_repo   # đọc file ngoài gói console → hook chạy cả ở chế độ nhanh (F6)
CLAUDE = ROOT / ".claude"
SETTINGS = CLAUDE / "settings.json"
KINDS = ("skills", "commands", "agents")
LOCKS = [
    p
    for p in sorted((ROOT / "docs" / "integrations").glob("*.lock.json"))
    if "select" in json.loads(p.read_text(encoding="utf-8"))
]
# Trần chung cho mô tả skill + lệnh của cả `.claude/` (vendor lẫn của repo). Nguồn thứ cấp nói Claude Code cắt danh
# sách mô tả quanh ~15,5–16k ký tự; chưa có tài liệu chính thức nên lấy nửa (ADR gốc 0030 §"Đo").
BUDGET_TOTAL = 8000


def _lock(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _settings() -> dict[str, Any]:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _vendored(lock: dict[str, Any]) -> list[str]:
    """Mọi tệp mang tiền tố của lock trong ba thư mục Claude Code tự quét, cộng giấy phép — quét đĩa, không đọc lock."""
    prefix, lic = lock["prefix"], ROOT / lock["license_path"]
    found = [p for p in (CLAUDE / "skills").glob(f"{prefix}*/**/*") if p.is_file()]
    found += [p for kind in ("commands", "agents") for p in (CLAUDE / kind).glob(f"{prefix}*.md")]
    found += [lic] if lic.exists() else []
    return sorted(p.relative_to(ROOT).as_posix() for p in found)


def _main_files(lock: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Tệp Claude Code liệt kê → (loại, tên mục không tiền tố)."""
    prefix = lock["prefix"]
    out: dict[str, tuple[str, str]] = {}
    for kind, names in lock["select"].items():
        for name in names:
            rel = f".claude/skills/{prefix}{name}/SKILL.md" if kind == "skills" else f".claude/{kind}/{prefix}{name}.md"
            out[rel] = (kind, name)
    return out


def _frontmatter(rel: str) -> dict[str, Any]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{rel}: thiếu frontmatter — Claude Code không liệt kê"
    meta = yaml.safe_load(m.group(1))
    assert isinstance(meta, dict), f"{rel}: frontmatter không phải ánh xạ YAML"
    return meta


def _description_loose(p: Path) -> str:
    """Mô tả của mọi skill/lệnh trong `.claude/`, kể cả tệp của repo có frontmatter không phải YAML chuẩn
    (`argument-hint: [subject_id] [--id <tên>]` của `gate-review.md`) — Claude Code vẫn đọc được, cổng cũng phải đọc."""
    m = re.match(r"\A---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.DOTALL)
    if not m:
        return ""
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        line = re.search(r"^description:[ \t]*(.*)$", m.group(1), re.MULTILINE)
        return line.group(1).strip() if line else ""
    return str(meta.get("description") or "") if isinstance(meta, dict) else ""


lock_param = pytest.mark.parametrize("lock_path", LOCKS, ids=[p.name.split(".")[0] for p in LOCKS])


def test_co_du_hai_nguon_vendor() -> None:
    """Lọc theo `select` mà ra rỗng thì mọi phép canh parametrize dưới đây im lặng không chạy — xanh vì rỗng."""
    assert [p.name for p in LOCKS] == ["ecc.lock.json", "mattpocock.lock.json"]


@lock_param
def test_lock_ghim_dung_mot_commit(lock_path: Path) -> None:
    lock = _lock(lock_path)
    assert lock["license"] == "MIT" and lock["license_holder"]
    assert re.fullmatch(r"[0-9a-f]{40}", lock["revision"]), "sha đủ 40 ký tự hex — tag có thể bị đẩy lại"
    assert (ROOT / lock["adr"]).is_file(), lock["adr"]
    assert re.fullmatch(r"[a-z0-9]+-", lock["prefix"]) and lock["prefix"] != "sc-", lock["prefix"]


def test_tien_to_khong_long_nhau_giua_cac_lock() -> None:
    """Build xoá mọi `<tiền tố>*` cũ: hai lock lồng tiền tố thì build của lock này xoá tệp của lock kia."""
    prefixes = [_lock(p)["prefix"] for p in LOCKS] + ["sc-"]   # `sc-` của `make subagents`
    long = [(a, b) for i, a in enumerate(prefixes) for b in prefixes[i + 1 :] if a.startswith(b) or b.startswith(a)]
    assert long == [], f"tiền tố lồng nhau: {long}"


@lock_param
def test_tep_vendor_tren_dia_dung_tap_va_dung_sha256_cua_lock(lock_path: Path) -> None:
    """Sửa tay một tệp vendor, thêm hay xoá một tệp mang tiền tố đều đỏ ở đây — không phải đợi job CI có mạng."""
    lock = _lock(lock_path)
    files = {f["path"]: f["sha256"] for f in lock["files"]}
    rel_lock = lock_path.relative_to(ROOT).as_posix()
    assert _vendored(lock) == sorted(files), f"tập tệp `{lock['prefix']}*` khác lock: `make vendor LOCK={rel_lock}`"
    lech = [
        rel
        for rel, sha in files.items()
        if hashlib.sha256((ROOT / rel).read_text(encoding="utf-8").encode("utf-8")).hexdigest() != sha
    ]
    assert lech == [], f"tệp vendor bị sửa tay (sha256 khác lock): {lech}"


@lock_param
def test_moi_muc_da_chon_co_tep_chinh_va_khong_tep_nao_mo_coi(lock_path: Path) -> None:
    lock = _lock(lock_path)
    mains = _main_files(lock)
    vendored = set(_vendored(lock))
    assert set(mains) <= vendored, f"mục trong `select` chưa sinh: {sorted(set(mains) - vendored)}"
    owners = {rel.split("/")[2] for rel in mains if rel.startswith(".claude/skills/")}
    mo_coi = [
        rel for rel in vendored - set(mains) if rel != lock["license_path"] and rel.split("/")[2] not in owners
    ]
    assert mo_coi == [], f"tệp `{lock['prefix']}*` không thuộc mục nào trong `select`: {mo_coi}"


@pytest.mark.parametrize(
    ("lock_path", "rel"),
    [(p, rel) for p in LOCKS for rel in sorted(_main_files(_lock(p)))],
    ids=lambda v: v.name.split(".")[0] if isinstance(v, Path) else v,
)
def test_ten_mang_tien_to_va_frontmatter_du(lock_path: Path, rel: str) -> None:
    lock = _lock(lock_path)
    kind, name = _main_files(lock)[rel]
    meta = _frontmatter(rel)
    want = lock["prefix"] + name
    if kind != "commands":
        assert meta.get("name") == want, f"{rel}: `name` phải là `{want}` — mất tiền tố là đụng tên"
    assert isinstance(meta.get("description"), str) and meta["description"].strip(), f"{rel}: thiếu description"


@lock_param
def test_tong_mo_ta_trong_ngan_sach_va_khop_so_do(lock_path: Path) -> None:
    """Toàn bộ ECC là 116 816 ký tự mô tả (ADR-0027) — vượt ngân sách liệt kê skill nên skill hiếm dùng mất mô tả."""
    lock = _lock(lock_path)
    total = sum(len(_frontmatter(rel)["description"]) for rel in _main_files(lock))
    assert total <= lock["budget_description_chars"]
    assert total == lock["measured"]["description_chars"]


def test_tong_mo_ta_skill_va_lenh_toan_claude_duoi_tran_chung() -> None:
    """Trần riêng từng lock không chặn được tổng: thêm nguồn thứ ba, hay thêm lệnh của repo, đều cộng vào cùng một
    danh sách mà Claude Code nạp mỗi phiên."""
    files = [*(CLAUDE / "skills").glob("*/SKILL.md"), *(CLAUDE / "commands").glob("*.md")]
    total = sum(len(_description_loose(p)) for p in files)
    assert 0 < total <= BUDGET_TOTAL, f"mô tả skill + lệnh của `.claude/` cộng lại {total} > {BUDGET_TOTAL}"


@lock_param
def test_moi_tep_vendor_mang_ghi_chu_nguon_va_luat_repo_thang(lock_path: Path) -> None:
    lock = _lock(lock_path)
    for rel in _vendored(lock):
        if rel.endswith(".md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert f"@{lock['revision']} (" in text and "không sửa tay" in text, f"{rel}: thiếu ghi chú nguồn"
            assert "`AGENTS.md` thắng khi trùng" in text and "fail_under = 100" in text, rel


@lock_param
def test_chon_va_loai_khong_giao_nhau_va_deu_co_ly_do(lock_path: Path) -> None:
    lock = _lock(lock_path)
    chon = {name: why for kind in KINDS for name, why in lock["select"].get(kind, {}).items()}
    assert set(lock["select"]) <= set(KINDS)
    # `rejected` nhận mẫu (`orch-*`): chọn một thành viên của họ đã loại cũng là giao nhau.
    giao = [n for n in chon if any(fnmatch.fnmatchcase(n, mau) for mau in lock["rejected"])]
    assert giao == [], f"vừa chọn vừa loại: {giao}"
    ngan = [n for n, why in {**chon, **lock["rejected"]}.items() if len(why) < 20]
    assert ngan == [], f"chọn/loại mà không nói vì sao (< 20 ký tự): {ngan}"


@lock_param
def test_giay_phep_mit_di_kem(lock_path: Path) -> None:
    lock = _lock(lock_path)
    text = (ROOT / lock["license_path"]).read_text(encoding="utf-8")
    assert text.startswith("MIT License") and lock["license_holder"] in text


def test_khong_con_plugin_hook_hay_env_ecc() -> None:
    """Plugin và vendor song song = cùng skill hiện hai lần (`ecc:x`, `ecc-x`) và hook node không ghim chạy lại."""
    s = _settings()
    assert not [k for k in s.get("extraKnownMarketplaces", {}) if "ecc" in k.lower() or "mattpocock" in k.lower()]
    assert not [k for k in s.get("env", {}) if k.startswith("ECC_")]
    # Máy đã cài theo hướng dẫn cũ (ADR-0027) hoặc cài bản chính chủ trôi theo `main` của họ: project scope tắt cả hai.
    assert s["enabledPlugins"] == {"ecc@xagents-ecc": False, "ecc@ecc": False}
    assert not [k for k in s["enabledPlugins"] if "mattpocock" in k.lower()]
    lenh = [h["command"] for groups in s["hooks"].values() for g in groups for h in g["hooks"]]
    assert all(c.startswith("${CLAUDE_PROJECT_DIR}/.claude/hooks/") for c in lenh), lenh
    assert not (CLAUDE / "rules").exists(), "rule ECC (coverage 80%, commit không scope) trái AGENTS.md"


@lock_param
def test_qua_bo_quet_tai_san_prompt_cua_cong_ty(lock_path: Path) -> None:
    """Tệp vendor đi thẳng vào phiên Claude Code như `.claude/agents/sc-*` — cùng bộ mẫu `guard.PATTERNS` (ADR-0022).
    Miễn trừ ghi trong lock theo khoá `<đường dẫn>::<luật>`, có lý do; miễn trừ không còn khớp gì là đỏ."""
    lock = _lock(lock_path)
    waivers = lock["assetscan_waivers"]
    assert all(len(why) >= 20 for why in waivers.values()), "miễn trừ không lý do"
    high = {
        f"{rel}::{f.rule}": f
        for rel in _vendored(lock)
        for f in scan_text((ROOT / rel).read_text(encoding="utf-8"), rel)
        if SEVERITY[f.rule] == "high"
    }
    assert sorted(set(high) - set(waivers)) == [], [high[k] for k in sorted(set(high) - set(waivers))]
    assert sorted(set(waivers) - set(high)) == [], "miễn trừ không còn khớp phát hiện nào — xoá khỏi lock"


@lock_param
def test_adr_va_claude_md_tro_dung_cach_dung(lock_path: Path) -> None:
    lock = _lock(lock_path)
    assert lock["revision"] in (ROOT / lock["adr"]).read_text(encoding="utf-8")
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"/{lock['prefix']}" in claude_md
    assert "/ecc:" not in claude_md, "tiền tố plugin cũ: lệnh `/ecc:` không còn tồn tại"
