"""Phiên role-play đề xuất/phản biện TRƯỚC pha `research` của `product` (ADR-0050).

Lấy ý từ `RolePlayingWorker` của CAMEL (hai ChatAgent `assistant`/`user` thay phiên, `chat_turn_limit`, vai user
mới được nói `TASK_DONE`), nhưng đặt trong luật của repo này: **guardrail có hạn mức** (`turn_limit` lượt VÀ
`token_budget` token, chạm cái nào dừng cái đó), **model quyết định – code hành động** (phiên không ghi
blackboard, không phát event nghiệp vụ; kết quả là DỮ LIỆU `debate` trong payload của lượt research), và
**prompt là code** (hai vai là hai file `roleplay/*.md` có `version`, nằm trong `ASSET_DIRS` của assetscan).

Không chạy mặc định: `COMPANY_DEBATE_TURNS=<n>` hoặc `--debate n` bật. Mỗi dự án tốn tối đa `n` lượt model tier
`standard` một lần (pha research chạy một lần mỗi dự án; chạy lại event thì lấy audit `research.debate` cũ —
`orch/enrich._with_debate`).
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xagents_core.registry import split_front_matter

from .llm import LLMError, ModelClient
from .registry import ROOT

ROLEPLAY_DIR = ROOT / "roleplay"
ENV_TURNS = "COMPANY_DEBATE_TURNS"
ENV_BUDGET = "COMPANY_DEBATE_BUDGET"
DEFAULT_BUDGET = 60_000  # token cho cả phiên; 4 lượt tier standard thường ~10–20k
PROPOSER, CRITIC = "proposer", "critic"
TURN_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {"message": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}},
                   "open_questions": {"type": "array", "items": {"type": "string"}}, "done": {"type": "boolean"}},
    "required": ["message", "points", "open_questions", "done"],
}


@dataclass(frozen=True)
class Role:
    id: str
    version: int
    system: str


def load_roles(root: Path = ROLEPLAY_DIR) -> dict[str, Role]:
    """Hai vai bắt buộc `proposer.md`, `critic.md`; thiếu là lỗi lúc dựng, không phải lúc chạy."""
    out = {}
    for rid in (PROPOSER, CRITIC):
        p = root / f"{rid}.md"
        if not p.is_file():
            raise FileNotFoundError(f"thiếu vai role-play {rid}: {p}")
        fm, body = split_front_matter(p.read_text(encoding="utf-8"))
        out[rid] = Role(id=str(fm.get("id") or rid), version=int(fm.get("version") or 0), system=body.strip())
    return out


@dataclass
class Debate:
    turns: list[dict[str, Any]]
    proposals: list[str]
    objections: list[str]
    open_questions: list[str]
    tokens: int
    cost_usd: float
    stopped_by: str  # done | turn_limit | budget
    turn_limit: int = 0

    def summary(self) -> dict[str, Any]:
        """Phần đưa vào payload của lượt research: ý, không transcript (transcript nằm ở audit)."""
        return {"proposals": self.proposals, "objections": self.objections, "open_questions": self.open_questions,
                "turns": len(self.turns), "stopped_by": self.stopped_by, "tokens": self.tokens}

    def as_audit(self) -> dict[str, Any]:
        return {**self.summary(), "turns": self.turns, "turn_limit": self.turn_limit, "cost_usd": self.cost_usd}


class RolePlay:
    def __init__(self, client: ModelClient, roles: Mapping[str, Role] | None = None, *, turn_limit: int = 4,
                 token_budget: int = DEFAULT_BUDGET, model_tier: str = "standard", pricing: Any = None):
        if turn_limit < 1:
            raise ValueError(f"turn_limit phải ≥ 1, nhận {turn_limit}")
        self.client, self.roles = client, dict(roles or load_roles())
        self.turn_limit, self.token_budget, self.model_tier, self.pricing = turn_limit, token_budget, model_tier, pricing

    @classmethod
    def from_env(cls, client: ModelClient, env: Mapping[str, str] | None = None, *, turns: int | None = None,
                 pricing: Any = None) -> RolePlay | None:
        """`turns` (cờ CLI) thắng `COMPANY_DEBATE_TURNS`; 0/thiếu = tắt → `None`."""
        env = os.environ if env is None else env
        raw = str(turns) if turns is not None else env.get(ENV_TURNS, "").strip()
        if not raw:
            return None
        try:
            n = int(raw)
        except ValueError as e:
            raise ValueError(f"{ENV_TURNS} phải là số nguyên, nhận {raw!r}") from e
        if n <= 0:
            return None
        budget = int(env.get(ENV_BUDGET, "").strip() or DEFAULT_BUDGET)
        return cls(client, turn_limit=n, token_budget=budget, pricing=pricing)

    def run(self, task: Mapping[str, Any]) -> Debate:
        turns: list[dict[str, Any]] = []
        tokens, cost, stopped = 0, 0.0, "turn_limit"
        for i in range(self.turn_limit):
            rid = PROPOSER if i % 2 == 0 else CRITIC
            role = self.roles[rid]
            user = json.dumps({"task": task, "transcript": turns, "turn": i + 1, "turns_left": self.turn_limit - i - 1},
                              ensure_ascii=False)
            c = self.client.complete(system=role.system, user=user, schema=TURN_SCHEMA, model_tier=self.model_tier,
                                     cache_key=f"roleplay:{rid}")
            data = c.json()
            missing = [k for k in TURN_SCHEMA["required"] if k not in data]
            if missing:
                raise LLMError(f"role-play {rid} lượt {i + 1}: thiếu trường {missing} trong JSON")
            tokens += c.tokens
            if self.pricing is not None:
                cost += float(self.pricing.cost(c)[0])
            turns.append({"role": rid, "message": str(data["message"]), "points": [str(x) for x in data["points"]],
                          "open_questions": [str(x) for x in data["open_questions"]]})
            if rid == CRITIC and bool(data["done"]):
                stopped = "done"; break
            if tokens >= self.token_budget:
                stopped = "budget"; break
        return Debate(turns=turns,
                      proposals=[p for t in turns if t["role"] == PROPOSER for p in t["points"]],
                      objections=[p for t in turns if t["role"] == CRITIC for p in t["points"]],
                      open_questions=[q for t in turns for q in t["open_questions"]],
                      tokens=tokens, cost_usd=cost, stopped_by=stopped, turn_limit=self.turn_limit)
