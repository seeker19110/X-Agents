"""Cổng cấu hình auto-compact 500k; không giả làm phép đo Claude Code/model thật.

Cùng vị trí với test_cong_khung.py: console chứa các cổng cấp repo.
Chỉ đọc file, không gọi mạng, model, git write hoặc bộ compact tự chế.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.cong_repo   # đọc file ngoài gói console → hook chạy cả ở chế độ nhanh (F6)
SETTINGS = ROOT / ".claude" / "settings.json"
GUIDE = ROOT / "docs" / "AUTO-COMPACT.md"
WINDOW_ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"


def test_auto_compact_bat_tuong_minh() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert settings.get("autoCompactEnabled") is True


def test_cua_so_la_500000_token_dang_chuoi_khong_phai_500k() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert settings.get("env", {}).get(WINDOW_ENV) == "500000"


def test_khong_tat_compact_hay_gia_nang_cua_so_model() -> None:
    env = json.loads(SETTINGS.read_text(encoding="utf-8")).get("env", {})
    for name in ("DISABLE_AUTO_COMPACT", "DISABLE_COMPACT", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"):
        assert name not in env, f"không thêm {name} để ép mốc 500k"


def test_giu_hang_rao_git_bi_mat_va_hook_cu() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    deny = set(settings["permissions"]["deny"])
    assert {"Bash(git push --force *)", "Bash(git reset --hard *)", "Read(./**/llm.yaml)", "Read(./.env)"} <= deny
    expected = {
        ("PreToolUse", "Bash", "block-dangerous-git.sh"),
        ("PreToolUse", "Bash", "pre-commit-gate.sh"),
        ("PostToolUse", "Edit|Write", "auto-format.sh"),
    }
    actual = {
        (event, group.get("matcher"), hook["command"].rsplit("/", 1)[-1])
        for event, groups in settings["hooks"].items()
        for group in groups
        for hook in group["hooks"]
        if hook.get("type") == "command"
    }
    assert expected <= actual


def test_khong_che_lenh_compact_native() -> None:
    for command in ("compact", "autocompact"):
        assert not (ROOT / ".claude" / "commands" / f"{command}.md").exists()
        assert not (ROOT / ".claude" / "skills" / command / "SKILL.md").exists()


def test_claude_co_chi_dan_giu_va_doc_lai_trang_thai_ben() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Compact Instructions\n" in text
    instructions = text.split("## Compact Instructions\n", 1)[1].split("\n## ", 1)[0]
    for required in ("docs/AUTO-COMPACT.md", "docs/thi-hanh/", "docs/sessions/", "HEAD", "spec", "quyền", "bằng chứng"):
        assert required in instructions
    assert "đọc lại" in instructions.lower()


def test_vi_du_cau_hinh_trong_huong_dan_khop_file_that() -> None:
    assert GUIDE.is_file(), "cần hướng dẫn kiểm tra CLI thật và giới hạn phép đo offline"
    examples = re.findall(r"```json\n(.*?)\n```", GUIDE.read_text(encoding="utf-8"), re.DOTALL)
    assert len(examples) == 1
    example = json.loads(examples[0])
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert example["env"][WINDOW_ENV] == settings["env"][WINDOW_ENV] == "500000"
    assert example["autoCompactEnabled"] is settings["autoCompactEnabled"] is True
