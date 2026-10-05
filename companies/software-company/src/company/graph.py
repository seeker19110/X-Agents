"""LangGraph wiring (tùy chọn). Import lazily để test không cần langgraph.

Mỗi agent là một node; edge là subscribe/publish trên bus. Node LLM gọi model theo
`AgentSpec.model_tier`; token dùng được phát qua `audit-log.tokens` để supervisor cộng dồn.
"""
from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import Any, TypedDict

from .registry import AgentSpec, load_agents
from .roles import ROLE

# Chuỗi tuyến tính từ yêu cầu thô đến kế hoạch. `domain/ux-designer/codebase/tech-scout` của bản đầu đã bị ADR-0006
# gộp vào `researcher` và ADR-0009 bỏ hẳn `ux-designer`; ADR-0037 PR-5e gộp cả bảy vai nghiên cứu/spec/plan vào
# `product` (bốn PHA, xem `roles.PHASE`) nên chuỗi chỉ còn hai node: danh sách là tên agent thật, kiểm lúc dựng graph.
RESEARCH_ORDER: tuple[str, ...] = (ROLE.PRODUCT, ROLE.SECURITY)


class GraphState(TypedDict, total=False):
    """Trạng thái chảy qua các node. langgraph chỉ nhận TypedDict/dataclass/BaseModel làm schema, không nhận `dict` trần."""

    input: str
    last_agent: str
    output: str


def research_order(agents: dict[str, AgentSpec] | None = None) -> list[str]:
    """Thứ tự node, đã kiểm mọi id là agent có thật — graph lệch registry thì hỏng lúc dựng, không phải lúc chạy."""
    known = agents if agents is not None else load_agents()
    unknown = [a for a in RESEARCH_ORDER if a not in known]
    if unknown:
        raise ValueError(f"graph tham chiếu agent không tồn tại: {unknown}")
    return list(RESEARCH_ORDER)


def build_graph(llm_factory: Callable[[AgentSpec], Callable[[str], str]]) -> Any:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("cài langgraph để dùng graph: uv add langgraph") from e
    agents = load_agents()
    g = StateGraph(GraphState)
    for aid, spec in agents.items():
        llm = llm_factory(spec)
        def node(state: GraphState, _llm=llm, _spec=spec) -> GraphState:
            out = _llm(_spec.system_prompt() + "\n\n# Input\n" + str(state.get("input", "")))
            return {**state, "last_agent": _spec.id, "output": out}
        g.add_node(aid, node)
    order = research_order(agents)
    g.set_entry_point(order[0])
    for a, b in pairwise(order):
        g.add_edge(a, b)
    g.add_edge(order[-1], END)
    return g.compile()
