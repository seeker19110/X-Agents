"""Golden tests cho 20 agent (ADR-0004: prompt là code; quân số theo ADR-0009).

Mỗi agent có một file golden `tests/golden/agents/<id>.md` chứa system prompt đã biên dịch
(front matter tóm tắt + prompt + skill). `tests/golden/registry.json` là "hợp đồng" của cả
công ty: topic đọc/ghi, namespace, skill, hạn mức. Bất kỳ thay đổi nào ở agents/ hoặc skills/
đều phải đi kèm cập nhật golden, và nếu nội dung prompt đổi thì `version` phải tăng.

Cập nhật golden sau khi cố ý sửa prompt/skill:
    UPDATE_GOLDEN=1 uv run pytest tests/test_golden_agents.py    # hoặc: make golden
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import get_args

import pytest

from company.events import NAMESPACE_OWNERS, Topic
from company.registry import AgentSpec, load_agents

GOLDEN_DIR = Path(__file__).parent / "golden"
AGENT_GOLDEN_DIR = GOLDEN_DIR / "agents"
REGISTRY_GOLDEN = GOLDEN_DIR / "registry.json"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"

TOPICS = set(get_args(Topic))
# Giá trị reads/writes hợp lệ nhưng không phải topic trên bus: subscribe mọi topic, nguồn ngoài, kho tri thức.
NON_TOPIC_CHANNELS = {"*", "knowledge-base"}
BLOCKS = {"research", "delivery", "engineering", "quality", "operations", "supervision"}
MODEL_TIERS = {"standard", "strong"}
REQUIRED_SECTIONS = ["## Vai trò", "## Bạn PHẢI", "## Bạn KHÔNG ĐƯỢC", "## Đầu vào", "## Đầu ra", "## Definition of done"]

_HEADER = re.compile(r"^<!-- golden agent=(?P<id>[\w-]+) version=(?P<version>\d+) -->\n", re.MULTILINE)

AGENTS = load_agents()
IDS = sorted(AGENTS)


def render(a: AgentSpec) -> str:
    """Nội dung golden: header máy đọc được + system prompt đầy đủ."""
    return f"<!-- golden agent={a.id} version={a.version} -->\n{a.system_prompt().rstrip()}\n"


def contract(a: AgentSpec) -> dict:
    return {
        "block": a.block, "model_tier": a.model_tier, "version": a.version,
        "reads": a.reads, "writes": a.writes, "context_namespace_write": a.context_namespace_write,
        "skills": a.skills, "skills_core": a.skills_core, "budget_tokens_per_task": a.budget_tokens_per_task,
        "max_retries": a.max_retries, "timeout_minutes": a.timeout_minutes,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# ---------- golden: system prompt từng agent ----------

@pytest.mark.parametrize("agent_id", IDS)
def test_agent_prompt_matches_golden(agent_id: str):
    a = AGENTS[agent_id]
    path = AGENT_GOLDEN_DIR / f"{agent_id}.md"
    expected = render(a)
    if UPDATE:
        _write(path, expected)
        return
    assert path.exists(), f"thiếu golden cho {agent_id}; chạy: UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}"
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return
    m = _HEADER.match(actual)
    old_version = int(m.group("version")) if m else None
    if old_version is not None and old_version >= a.version:
        pytest.fail(
            f"[{agent_id}] prompt hoặc skill đã đổi nhưng version vẫn là {a.version} (golden ghi {old_version}). "
            f"ADR-0004: tăng `version` trong front matter rồi chạy UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}"
        )
    pytest.fail(
        f"[{agent_id}] golden lệch (version {old_version} → {a.version}). Xem diff rồi cập nhật: "
        f"UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}"
    )


def test_no_stale_golden_files():
    """Golden của agent đã bị xóa/đổi tên phải được dọn."""
    on_disk = {p.stem for p in AGENT_GOLDEN_DIR.glob("*.md")}
    stale = on_disk - set(IDS)
    if UPDATE:
        for s in stale:
            (AGENT_GOLDEN_DIR / f"{s}.md").unlink()
        return
    assert not stale, {"stale": stale}


# ---------- golden: hợp đồng toàn công ty ----------

def test_registry_contract_matches_golden():
    expected = {aid: contract(AGENTS[aid]) for aid in IDS}
    text = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if UPDATE:
        _write(REGISTRY_GOLDEN, text)
        return
    assert REGISTRY_GOLDEN.exists(), "thiếu tests/golden/registry.json; chạy UPDATE_GOLDEN=1"
    actual = json.loads(REGISTRY_GOLDEN.read_text(encoding="utf-8"))
    diff = {k: (actual.get(k), expected[k]) for k in expected if actual.get(k) != expected[k]}
    assert actual == expected, {"changed (golden, hiện tại)": diff, "removed": set(actual) - set(expected)}


# ---------- bất biến cấu trúc (không phụ thuộc golden) ----------

@pytest.mark.parametrize("agent_id", IDS)
def test_front_matter_is_well_formed(agent_id: str):
    a = AGENTS[agent_id]
    assert a.block in BLOCKS, a.block
    assert a.model_tier in MODEL_TIERS, a.model_tier
    for ch in a.reads + a.writes:
        assert ch in TOPICS | NON_TOPIC_CHANNELS, f"{agent_id}: kênh lạ `{ch}`"
    assert a.reads and a.writes, "agent phải có ít nhất một topic đọc và một topic ghi"
    assert a.max_retries >= 0 and a.timeout_minutes > 0
    assert len(a.all_skills) == len(set(a.all_skills)), "skill trùng lặp giữa skills/skills_core"
    assert a.skills, "agent phải sở hữu ít nhất một skill ở mức đầy đủ"


@pytest.mark.parametrize("agent_id", IDS)
def test_prompt_has_required_sections_in_order(agent_id: str):
    p = AGENTS[agent_id].prompt
    assert p.startswith(f"# {agent_id}\n"), "tiêu đề H1 phải là id agent"
    positions = [p.find(s) for s in REQUIRED_SECTIONS]
    missing = [s for s, i in zip(REQUIRED_SECTIONS, positions, strict=True) if i < 0]
    assert not missing, {"thiếu mục": missing}
    assert positions == sorted(positions), "các mục phải theo đúng thứ tự chuẩn"


@pytest.mark.parametrize("agent_id", IDS)
def test_prompt_mentions_its_topics_and_namespace(agent_id: str):
    """Prompt phải nhắc tới các topic nó ghi và namespace nó sở hữu, để LLM không tự bịa kênh."""
    a = AGENTS[agent_id]
    for t in a.writes:
        if t in TOPICS and t != "audit-log":
            assert t in a.prompt, f"{agent_id}: prompt không nhắc topic ghi `{t}`"
    for ns in a.namespaces_write:
        assert ns in a.prompt, f"{agent_id}: prompt không nhắc namespace `{ns}`"


def test_every_namespace_has_exactly_the_declared_owners():
    """Chiều ngược của test_registry: mọi owner trong events.py phải khai báo namespace đó trong front matter
    (front matter nhận danh sách từ ADR-0006)."""
    declared = {a.id: set(a.namespaces_write) for a in AGENTS.values()}
    for ns, owners in NAMESPACE_OWNERS.items():
        for o in owners:
            assert ns in declared.get(o, set()), f"{o} là owner của `{ns}` trong events.py nhưng front matter không khai báo"


def test_every_topic_has_a_writer_and_a_reader():
    """Không có topic mồ côi: mỗi topic (trừ topic human/ngoài) có ít nhất một agent ghi và một agent đọc."""
    readers = {t for a in AGENTS.values() for t in a.reads} | {"*"}
    writers = {t for a in AGENTS.values() for t in a.writes}
    human_written = {"clarification-answers", "research-requests", "approved-specs", "shared-context", "external-feedback"}  # account-manager ghi change-requests/acceptance-results
    human_read = {"clarification-questions", "release-events", "supervisor-actions", "shared-context", "audit-log"}
    for t in TOPICS:
        assert t in writers or t in human_written, f"không ai ghi `{t}`"
        assert t in readers or t in human_read or "*" in readers, f"không ai đọc `{t}`"
