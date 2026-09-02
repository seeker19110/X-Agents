import pytest

from company.events import NAMESPACE_OWNERS
from company.registry import SKILLS_DIR, _split, load_agents

EXPECTED = {
    # research (6) — ADR-0006 gộp domain/ux-designer/codebase/tech-scout thành researcher
    "intake", "researcher", "synthesizer", "risk", "clarifier", "spec-writer",
    # delivery (1)
    "delivery-lead",
    # engineering (6)
    "backend", "frontend", "mobile", "database", "platform", "data",
    # quality (3)
    "reviewer", "qa-debugger", "security-engineer",
    # operations (3)
    "release-engineer", "support-docs", "account-manager",
    # supervision (1)
    "supervisor",
}

def test_all_20_agents_load():
    agents = load_agents()
    assert set(agents) == EXPECTED
    assert len(agents) == 20

def test_prompts_have_skills_and_dod():
    for a in load_agents().values():
        assert "Definition of done" in a.prompt
        assert a.skill_text, a.id
        assert a.budget_tokens_per_task > 0

def test_prompt_versions_at_least_1():
    """ADR-0004: prompt là code, mỗi agent có version ≥ 1."""
    for a in load_agents().values():
        assert isinstance(a.version, int) and a.version >= 1, a.id

def test_namespace_write_matches_events_owner():
    """Front matter `context_namespace_write` phải khớp NAMESPACE_OWNERS trong events.py."""
    for a in load_agents().values():
        for ns in a.namespaces_write:
            assert a.id in NAMESPACE_OWNERS[ns], (a.id, ns)

def test_every_namespace_owner_is_a_real_agent():
    agents = set(load_agents())
    for ns, owners in NAMESPACE_OWNERS.items():
        assert owners <= agents, (ns, owners - agents)

def test_skill_front_matter_name_matches_filename():
    for p in SKILLS_DIR.glob("*.md"):
        fm, _ = _split(p.read_text(encoding="utf-8"))
        assert fm["name"] == p.stem, p.name

def test_no_orphan_skill():
    used = {s for a in load_agents().values() for s in a.all_skills}
    on_disk = {p.stem for p in SKILLS_DIR.glob("*.md")}
    assert on_disk == used, {"unused": on_disk - used, "missing": used - on_disk}


def test_every_skill_has_an_owning_agent():
    """ADR-0008: skill chỉ xuất hiện ở `skills_core` thì phần Quy tắc/Ví dụ không tới tay model nào."""
    owned = {s for a in load_agents().values() for s in a.skills}
    on_disk = {p.stem for p in SKILLS_DIR.glob("*.md")}
    assert on_disk <= owned, sorted(on_disk - owned)


def test_load_agents_rejects_ownerless_skill(tmp_path, monkeypatch):
    import company.registry as reg

    monkeypatch.setattr(reg, "SKILLS_DIR", tmp_path)
    for p in SKILLS_DIR.glob("*.md"):
        (tmp_path / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "khong-ai-so-huu.md").write_text(
        "---\nname: khong-ai-so-huu\nversion: 1\n---\n# Skill\n\n## Quy trình\nx\n\n## Checklist\n- x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="chủ quản"):
        reg.load_agents()


def test_context_namespace_read_names_real_namespaces():
    """ADR-0020: mọi namespace trong context_namespace_read phải tồn tại; review/QA/ops có trần prompt riêng thấp hơn."""
    from company.events import NAMESPACE_OWNERS
    agents = load_agents()
    for spec in agents.values():
        assert spec.context_namespace_read is not None, f"{spec.id}: thiếu context_namespace_read"
        assert set(spec.context_namespace_read) <= set(NAMESPACE_OWNERS), spec.id
    for aid in ("reviewer", "qa-debugger", "security-engineer", "release-engineer", "support-docs", "supervisor"):
        assert agents[aid].max_input_chars and agents[aid].max_input_chars <= 70_000, aid
