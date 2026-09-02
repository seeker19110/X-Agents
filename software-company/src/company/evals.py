"""Eval prompt (ADR-0004): mỗi agent có `evals/<agent>.yaml` gồm các ca đầu vào + tiêu chí chấm xác định.
Chạy với model đã cấu hình (`python -m company.evals reviewer`) hoặc client giả trong test. Không gắn provider nào.

Tiêu chí (`expect`):
  equals:   {field: value}         trường bằng đúng
  contains: {field: substring}     chuỗi chứa (không phân biệt hoa thường)
  min_len:  {field: n}             list/chuỗi có độ dài ≥ n
  one_of:   {field: [v1, v2]}      giá trị nằm trong tập
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .blackboard import Blackboard
from .bus import InMemoryBus
from .events import Envelope
from .llm import LLMError, ModelClient
from .runner import AgentRunner, RunnerError

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"


@dataclass
class CaseResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    tokens: int = 0


def _get(d: Any, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        if isinstance(cur, list) and part.isdigit(): cur = cur[int(part)] if int(part) < len(cur) else None
        elif isinstance(cur, dict): cur = cur.get(part)
        else: return None
        if cur is None: return None
    return cur


def check(payload: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    for f, v in (expect.get("equals") or {}).items():
        if _get(payload, f) != v: fails.append(f"{f} == {v!r}, thực tế {_get(payload, f)!r}")
    for f, v in (expect.get("contains") or {}).items():
        if str(v).lower() not in str(_get(payload, f) or "").lower(): fails.append(f"{f} phải chứa {v!r}")
    for f, n in (expect.get("min_len") or {}).items():
        if len(_get(payload, f) or []) < n: fails.append(f"len({f}) ≥ {n}")
    for f, vs in (expect.get("one_of") or {}).items():
        if _get(payload, f) not in vs: fails.append(f"{f} ∈ {vs}")
    return fails


def load_cases(agent_id: str) -> list[dict[str, Any]]:
    p = EVALS_DIR / f"{agent_id}.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("cases", []) if p.exists() else []


def run_eval(agent_id: str, client: ModelClient) -> list[CaseResult]:
    results = []
    for case in load_cases(agent_id):
        bus = InMemoryBus(); bb = Blackboard(bus)
        for ctx in case.get("context", []):
            bb.write(ctx["actor"], ctx["namespace"], ctx["content_ref"], ctx.get("summary", ""))
        runner = AgentRunner(bus, client, blackboard=bb)
        i = case["input"]
        inp = Envelope(topic=i["topic"], key=i["key"], actor=i.get("actor", "human"), payload=i["payload"])
        try:
            r = runner.run(agent_id, inp, case["topic_out"])
        except (RunnerError, LLMError) as e:
            results.append(CaseResult(case["name"], False, [str(e)])); continue
        fails = check(r.output.payload, case.get("expect", {}))
        results.append(CaseResult(case["name"], not fails, fails, r.tokens))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chạy eval prompt của một agent với model đã cấu hình")
    ap.add_argument("agent")
    ns = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")  # Windows console cp1252
    from .llm import make_client
    res = run_eval(ns.agent, make_client())
    for r in res:
        print(f"{'PASS' if r.passed else 'FAIL'} {r.name} ({r.tokens} tok)" + "".join(f"\n   - {f}" for f in r.failures))
    print(f"{sum(r.passed for r in res)}/{len(res)} pass")
    return 0 if all(r.passed for r in res) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
