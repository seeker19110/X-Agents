"""Cổng cho tích hợp ECC (`affaan-m/ECC`) vào phiên Claude Code của repo — ADR gốc 0027.

Vì sao cần cổng: ECC nạp qua `.claude/settings.json` dưới dạng plugin, nên mọi thứ quan trọng của nó (bản nào chạy,
hook nào tắt vì trái luật repo) nằm trong MỘT file JSON mà không ai đọc lại. Ghim lệch khỏi lock, quên tắt
`block-no-verify`, hay bật song song bản `ecc@ecc` trôi theo `main` của họ đều không làm gì đỏ — phiên vẫn mở, chỉ
là chạy thứ khác với thứ ADR đã đo. Cùng khuôn `test_cong_khung.py`: hàng rào trỏ sai là cổng chết im lặng.

Đặt ở `platform/console/tests/` theo lối các phép canh cấp gốc khác (`test_cong_khung.py`, `test_cong_repo.py`).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SETTINGS = ROOT / ".claude" / "settings.json"
LOCK = ROOT / "docs" / "integrations" / "ecc.lock.json"
ADR = ROOT / "docs" / "adr" / "0027-tich-hop-ecc-plugin-ghim.md"
MARKETPLACE = "xagents-ecc"
HOOK_PROFILES = {"minimal", "standard", "strict"}


def _settings() -> dict[str, Any]:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _lock() -> dict[str, Any]:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def _plugin() -> dict[str, Any]:
    src = _settings()["extraKnownMarketplaces"][MARKETPLACE]["source"]
    assert src["source"] == "settings" and src["name"] == MARKETPLACE, "marketplace khai tại chỗ, không trỏ repo ngoài"
    return next(p for p in src["plugins"] if p["name"] == "ecc")


def test_ecc_ghim_dung_mot_commit_va_khop_lock() -> None:
    """Nguồn plugin là một SHA đầy đủ, không phải nhánh hay tag trôi được — và đúng SHA mà ADR đã đo."""
    src, lock = _plugin()["source"], _lock()
    assert src["source"] == "github" and src["repo"] == lock["repository"] == "affaan-m/ECC"
    assert re.fullmatch(r"[0-9a-f]{40}", src["sha"]), "sha phải đủ 40 ký tự hex — tag có thể bị đẩy lại"
    assert src["sha"] == lock["revision"], "settings và lock lệch nhau: một trong hai đang nói dối về bản đang chạy"
    assert src["ref"] == lock["tag"]


def test_bat_ban_ghim_va_tat_ban_tha_noi() -> None:
    """`ecc@ecc` là marketplace chính chủ, trôi theo `main` của họ. Ai đã cài nó ở scope user thì phiên trong repo
    này sẽ chạy HAI bộ hook ECC chồng nhau — project scope tắt nó đi để chỉ còn bản ghim."""
    en = _settings()["enabledPlugins"]
    assert en[f"ecc@{MARKETPLACE}"] is True
    assert en["ecc@ecc"] is False


def test_hook_ecc_trai_luat_repo_bi_tat_va_moi_hook_tat_co_ly_do() -> None:
    env, lock = _settings()["env"], _lock()
    assert env["ECC_HOOK_PROFILE"] in HOOK_PROFILES and env["ECC_HOOK_PROFILE"] == lock["hook_profile"]
    tat = {h.strip() for h in env["ECC_DISABLED_HOOKS"].split(",") if h.strip()}
    assert tat == set(lock["disabled_hooks"]), "hook tắt trong settings phải là đúng tập đã ghi lý do trong lock"
    assert all(len(ly_do) >= 20 for ly_do in lock["disabled_hooks"].values()), "tắt hook mà không nói vì sao"
    # AGENTS.md "Hàng rào thi hành": `--no-verify` là đường thoát TƯỜNG MINH của repo; block-no-verify của ECC chặn
    # đúng đường đó (đo: rc=2 khi bật). Còn đường thoát ấy trong luật thì hook này phải tắt.
    if "--no-verify" in (ROOT / "AGENTS.md").read_text(encoding="utf-8"):
        assert "pre:bash:block-no-verify" in tat
    # Auto-compact native 300k là chính sách của repo (`test_auto_compact_config.py`); ECC nhắc /compact thủ công.
    assert "pre:edit-write:suggest-compact" in tat


def test_khong_chep_tep_nao_cua_ecc_vao_repo() -> None:
    """Tích hợp là ghim plugin, không vendor: rule của ECC (coverage 80%, commit không scope) trái `AGENTS.md`, còn
    skill/agent của nó đã có namespace `ecc:` qua plugin. Chép vào `.claude/` là mất cả ghim lẫn namespace."""
    tracked = subprocess.run(
        ["git", "ls-files", ".claude"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [p for p in tracked if re.search(r"(^|/)(ecc|everything-claude-code)([-_/.]|$)", p, re.I)] == []
    assert not (ROOT / ".claude" / "rules").exists()


def test_adr_va_claude_md_noi_ro_luat_repo_thang_ecc() -> None:
    adr = ADR.read_text(encoding="utf-8")
    assert "affaan-m/ECC" in adr and _lock()["revision"] in adr
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "0027" in claude_md and "/ecc:" in claude_md
