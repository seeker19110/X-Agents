from company.registry import load_agents

EXPECTED = {"intake","domain","codebase","tech-scout","synthesizer","risk","clarifier","spec-writer",
            "delivery-lead","backend","frontend","mobile","database","reviewer","qa-debugger",
            "release-engineer","support-docs","supervisor"}

def test_all_18_agents_load():
    agents = load_agents()
    assert set(agents) == EXPECTED

def test_prompts_have_skills_and_dod():
    for a in load_agents().values():
        assert "Definition of done" in a.prompt
        assert a.skill_text, a.id
        assert a.budget_tokens_per_task > 0
