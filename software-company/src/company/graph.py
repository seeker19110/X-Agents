"""LangGraph wiring (tùy chọn). Import lazily để test không cần langgraph.

Mỗi agent là một node; edge là subscribe/publish trên bus. Node LLM gọi model theo
`AgentSpec.model_tier`; token dùng được phát qua `audit-log.tokens` để supervisor cộng dồn.
"""
from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import Any

from .registry import AgentSpec, load_agents


def build_graph(llm_factory: Callable[[AgentSpec], Callable[[str], str]]) -> Any:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("cài langgraph để dùng graph: uv add langgraph") from e
    agents = load_agents()
    g = StateGraph(dict)
    for aid, spec in agents.items():
        llm = llm_factory(spec)
        def node(state: dict, _llm=llm, _spec=spec) -> dict:
            out = _llm(_spec.system_prompt() + "\n\n# Input\n" + str(state.get("input", "")))
            return {**state, "last_agent": _spec.id, "output": out}
        g.add_node(aid, node)
    order = ["intake", "domain", "ux-designer", "codebase", "tech-scout", "synthesizer", "risk", "clarifier",
             "spec-writer", "security-engineer", "delivery-lead"]
    g.set_entry_point(order[0])
    for a, b in pairwise(order):
        g.add_edge(a, b)
    g.add_edge(order[-1], END)
    return g.compile()
