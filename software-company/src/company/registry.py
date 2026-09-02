from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR, SKILLS_DIR = ROOT / "agents", ROOT / "skills"
_FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

@dataclass
class AgentSpec:
    id: str
    block: str
    model_tier: str
    reads: list[str]
    writes: list[str]
    context_namespace_write: str | None
    skills: list[str]
    budget_tokens_per_task: int
    max_retries: int
    timeout_minutes: int
    prompt: str
    skill_text: str = field(default="")

    def system_prompt(self) -> str:
        return f"{self.prompt}\n\n# Skills\n{self.skill_text}"

def _split(text: str) -> tuple[dict, str]:
    m = _FM.match(text)
    if not m:
        raise ValueError("thiếu front matter")
    return yaml.safe_load(m.group(1)), text[m.end():]

def load_skill(name: str) -> str:
    p = SKILLS_DIR / f"{name}.md"
    _, body = _split(p.read_text(encoding="utf-8"))
    return body.strip()

def load_agents() -> dict[str, AgentSpec]:
    out: dict[str, AgentSpec] = {}
    for p in sorted(AGENTS_DIR.rglob("*.md")):
        fm, body = _split(p.read_text(encoding="utf-8"))
        spec = AgentSpec(prompt=body.strip(), **fm)
        spec.skill_text = "\n\n".join(load_skill(s) for s in spec.skills)
        out[spec.id] = spec
    return out
