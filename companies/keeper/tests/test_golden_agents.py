"""Golden tests cho 10 agent của `keeper` (prompt là code, ADR-0004, khuôn `Studio-creators/tests/test_golden_agents.py`).
`DAC-TA-KEEPER.md` §9 nói "tám agent"; bảng README (theo tên, khớp `TOPIC_PRODUCERS`) có mười — xem
`test_dung_tam_agent` dưới đây cho lý do chọn mười.

`keeper` KHÔNG có `registry.py`/`AgentSpec` riêng (không có trường thêm như `tools` của studio) — nạp thẳng
`xagents_core.registry.load_agents` với `AgentSpec` của lõi. `keeper/skills/` chưa tồn tại (chưa agent nào có
`skills`/`skills_core` khai dùng) nên `check_owners=False`: bật cổng đó trước khi có skill thật là đỏ giả.

Mỗi agent có `tests/golden/agents/<id>.md` = system prompt đã biên dịch; `tests/golden/registry.json` là hợp
đồng cả sáu khối. Sửa `keeper/agents/` → phải tăng `version` và chạy:
UPDATE_GOLDEN=1 uv run pytest -q tests/test_golden_agents.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import get_args

import pytest
from xagents_core.registry import AgentSpec, load_agents

from keeper.core import CORE
from keeper.events import Topic

GOLDEN_DIR = Path(__file__).parent / "golden"
AGENT_GOLDEN_DIR = GOLDEN_DIR / "agents"
REGISTRY_GOLDEN = GOLDEN_DIR / "registry.json"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"

AGENTS_DIR = CORE.root / "agents"
SKILLS_DIR = CORE.root / "skills"

TOPICS = set(get_args(Topic))
NON_TOPIC_CHANNELS = {"*"}
BLOCKS = {"watch", "triage", "engineering", "quality", "release", "supervisor"}
MODEL_TIERS = {"light", "standard", "strong"}
REQUIRED_SECTIONS = ["## Vai trò", "## Bạn PHẢI", "## Bạn KHÔNG ĐƯỢC", "## Đầu vào", "## Đầu ra", "## Definition of done"]
_HEADER = re.compile(r"^<!-- golden agent=(?P<id>[\w-]+) version=(?P<version>\d+) -->\n", re.MULTILINE)

AGENTS = load_agents(AGENTS_DIR, SKILLS_DIR, AgentSpec, check_owners=False)
IDS = sorted(AGENTS)


def render(a: AgentSpec) -> str:
    return f"<!-- golden agent={a.id} version={a.version} -->\n{a.system_prompt().rstrip()}\n"


def contract(a: AgentSpec) -> dict:
    return {"block": a.block, "model_tier": a.model_tier, "version": a.version, "reads": a.reads, "writes": a.writes,
            "context_namespace_write": a.context_namespace_write, "skills": a.skills, "skills_core": a.skills_core,
            "budget_tokens_per_task": a.budget_tokens_per_task, "max_retries": a.max_retries,
            "timeout_minutes": a.timeout_minutes}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_dung_tam_agent():
    """Mâu thuẫn đo được (BT7.b): `DAC-TA-KEEPER.md` §9 nói "tám agent", nhưng bảng 6 khối của `README.md`
    liệt kê MƯỜI dòng agent (`watch` có ba: dependency-scout/health-monitor/drift-detector). Chọn phương án
    theo bảng README — nó là bảng có tên agent cụ thể, khớp `TOPIC_PRODUCERS` (`keeper/src/keeper/core.py`);
    "tám" ở §9 là số khối/nhóm chức năng bị gọi nhầm thành số agent. 10 agent, 6 khối."""
    assert len(IDS) == 10, IDS


@pytest.mark.parametrize("agent_id", IDS)
def test_agent_prompt_matches_golden(agent_id: str):
    a = AGENTS[agent_id]; path = AGENT_GOLDEN_DIR / f"{agent_id}.md"; expected = render(a)
    if UPDATE:
        _write(path, expected); return
    assert path.exists(), f"thiếu golden cho {agent_id}; chạy: UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}"
    actual = path.read_text(encoding="utf-8")
    if actual == expected: return
    m = _HEADER.match(actual); old_version = int(m.group("version")) if m else None
    if old_version is not None and old_version >= a.version:
        pytest.fail(f"[{agent_id}] prompt đã đổi nhưng version vẫn là {a.version} (golden ghi {old_version}). "
                    f"Tăng `version` rồi chạy UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}")
    pytest.fail(f"[{agent_id}] golden lệch (version {old_version} → {a.version}). Cập nhật: UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}")


def test_no_stale_golden_files():
    on_disk = {p.stem for p in AGENT_GOLDEN_DIR.glob("*.md")} if AGENT_GOLDEN_DIR.exists() else set()
    stale = on_disk - set(IDS)
    if UPDATE:
        for s in stale: (AGENT_GOLDEN_DIR / f"{s}.md").unlink()
        return
    assert not stale, {"stale": stale}


def test_registry_contract_matches_golden():
    expected = {aid: contract(AGENTS[aid]) for aid in IDS}
    text = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if UPDATE:
        _write(REGISTRY_GOLDEN, text); return
    assert REGISTRY_GOLDEN.exists(), "thiếu tests/golden/registry.json; chạy UPDATE_GOLDEN=1"
    actual = json.loads(REGISTRY_GOLDEN.read_text(encoding="utf-8"))
    diff = {k: (actual.get(k), expected[k]) for k in expected if actual.get(k) != expected[k]}
    assert actual == expected, {"changed (golden, hiện tại)": diff, "removed": set(actual) - set(expected)}


@pytest.mark.parametrize("agent_id", IDS)
def test_front_matter_is_well_formed(agent_id: str):
    a = AGENTS[agent_id]
    assert a.block in BLOCKS, a.block
    assert a.model_tier in MODEL_TIERS, a.model_tier
    for ch in a.reads + a.writes:
        assert ch in TOPICS | NON_TOPIC_CHANNELS, f"{agent_id}: kênh lạ `{ch}`"
    assert a.reads and a.writes
    assert a.max_retries >= 0 and a.timeout_minutes > 0


@pytest.mark.parametrize("agent_id", IDS)
def test_model_tier_dung_bang(agent_id: str):
    """`model_tier` mặc định `light`; chỉ `refactorer` là `strong`, chỉ `triager` là `standard` (§9)."""
    a = AGENTS[agent_id]
    if agent_id == "refactorer":
        assert a.model_tier == "strong"
    elif agent_id == "triager":
        assert a.model_tier == "standard"
    else:
        assert a.model_tier == "light", f"{agent_id}: model_tier mặc định phải là light"


@pytest.mark.parametrize("agent_id", IDS)
def test_prompt_has_required_sections_in_order(agent_id: str):
    p = AGENTS[agent_id].prompt
    assert p.startswith(f"# {agent_id}\n")
    positions = [p.find(s) for s in REQUIRED_SECTIONS]
    missing = [s for s, i in zip(REQUIRED_SECTIONS, positions, strict=True) if i < 0]
    assert not missing, {"thiếu mục": missing}
    assert positions == sorted(positions)


@pytest.mark.parametrize("agent_id", IDS)
def test_prompt_mentions_its_topics(agent_id: str):
    a = AGENTS[agent_id]
    for t in a.writes:
        if t in TOPICS and t != "audit-log":
            assert t in a.prompt, f"{agent_id}: prompt không nhắc topic ghi `{t}`"


def test_every_topic_has_a_writer_and_a_reader():
    from keeper.core import HUMAN_TOPICS, OPEN_TOPICS
    readers = {t for a in AGENTS.values() for t in a.reads} | {"*"}
    writers = {t for a in AGENTS.values() for t in a.writes}
    human_or_code_written = HUMAN_TOPICS | {"audit-log", "shared-context"}  # shared-context: orchestrator/runner ghi bằng code
    human_or_code_read = OPEN_TOPICS | {"audit-log", "release-notes", "supervisor-actions"}  # release-notes: tiêu thụ bởi người/PR; supervisor-actions: orchestrator đọc bằng code
    for t in TOPICS:
        assert t in writers or t in human_or_code_written, f"không ai ghi `{t}`"
        assert t in readers or t in human_or_code_read, f"không ai đọc `{t}`"


def test_cam_patcher_khong_tu_sua_agents_skills():
    """Câu cấm bắt buộc §9: patcher không tự sửa `agents/`/`skills/`."""
    p = AGENTS["patcher"].prompt
    assert "CONTRIBUTING.md" in p and "risk_tier=high" in p


def test_cam_regression_guard_khong_tu_khai_verified_by():
    """Câu cấm bắt buộc §9: regression-guard không bao giờ tự khai `verified_by`."""
    p = AGENTS["regression-guard"].prompt
    assert "verified_by" in p


def test_cam_regression_guard_khong_tu_khai_patch_id():
    """regression-guard biết `patch_id` và `before`/`after` do code đo (`evidence.SELF_CLAIM_FIELDS`, ADR keeper
    0001/0002), không tự khai; sửa worktree sau lần đo là bằng chứng cũ hết khớp, phải đo lại."""
    p = AGENTS["regression-guard"].prompt
    assert "patch_id" in p and "`before`/`after`" in p and "đo lại" in p.lower()


@pytest.mark.parametrize("agent_id", IDS)
def test_moi_agent_nhac_bat_bien_I1(agent_id: str):
    """Câu cấm bắt buộc §9: mọi agent — keeper không có quyền ghi ngoài tạo nhánh / commit trong worktree của
    chính nó / mở PR (bất biến I1)."""
    p = AGENTS[agent_id].prompt
    assert "bất biến I1" in p
