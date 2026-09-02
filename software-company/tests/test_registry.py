from company.events import NAMESPACE_OWNERS
from company.registry import SKILLS_DIR, _split, load_agents

EXPECTED = {
    # research (9)
    "intake", "domain", "ux-designer", "codebase", "tech-scout", "synthesizer", "risk", "clarifier", "spec-writer",
    # delivery (1)
    "delivery-lead",
    # engineering (6)
    "backend", "frontend", "mobile", "database", "platform", "data",
    # quality (3)
    "reviewer", "qa-debugger", "security-engineer",
    # operations (2)
    "release-engineer", "support-docs",
    # supervision (1)
    "supervisor",
}

def test_all_22_agents_load():
    agents = load_agents()
    assert set(agents) == EXPECTED
    assert len(agents) == 22

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
        if a.context_namespace_write:
            assert a.id in NAMESPACE_OWNERS[a.context_namespace_write], (a.id, a.context_namespace_write)

def test_every_namespace_owner_is_a_real_agent():
    agents = set(load_agents())
    for ns, owners in NAMESPACE_OWNERS.items():
        assert owners <= agents, (ns, owners - agents)

def test_skill_front_matter_name_matches_filename():
    for p in SKILLS_DIR.glob("*.md"):
        fm, _ = _split(p.read_text(encoding="utf-8"))
        assert fm["name"] == p.stem, p.name

def test_no_orphan_skill():
    used = {s for a in load_agents().values() for s in a.skills}
    on_disk = {p.stem for p in SKILLS_DIR.glob("*.md")}
    assert on_disk == used, {"unused": on_disk - used, "missing": used - on_disk}
