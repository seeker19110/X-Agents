"""Metrics từ bus (ADR-0012): đọc `audit-log` + topic, không cần hạ tầng ngoài.

Trước đây muốn biết agent nào chậm, tốn, hay lỗi phải tự truy SQLite. `collect(bus)` trả về một dict cho người và
`orchestrator metrics`; `prometheus(m)` xuất text exposition (đặt vào node_exporter textfile collector hay scrape qua
file) để nối dashboard sẵn có. Nguồn số liệu:

- audit `produced:*` (evidence JSON: model, duration_ms, cache_hit, turns, tool_calls) → gọi, token, chi phí, thời gian
- audit `llm_error|invalid_output|budget_exhausted|injection_*|llm_retry|context_trimmed` → sức khoẻ
- audit `gate.request` / `gate.decide` → thời gian chờ người
- topic `tasks` (đầu) → trạng thái cuối theo audit/ticket → lead time ticket
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from .bus import InMemoryBus

HEALTH = ("llm_error", "invalid_output", "budget_exhausted", "injection_detected", "injection_sanitized", "llm_retry",
          "context_trimmed", "handler_error", "tools_used", "local_checks.unverified")


def _ev(a: dict[str, Any]) -> dict[str, Any]:
    try: d = json.loads(a.get("evidence") or "{}")
    except json.JSONDecodeError: return {}
    return d if isinstance(d, dict) else {}


def _stat() -> dict[str, Any]:
    return {"calls": 0, "tokens": 0, "cost_usd": 0.0, "duration_ms": 0, "errors": 0, "retries": 0, "cache_hit_sum": 0.0,
            "tool_calls": 0, "unpriced": 0}


def collect(bus: InMemoryBus) -> dict[str, Any]:
    agents: dict[str, dict[str, Any]] = defaultdict(_stat)
    models: dict[str, dict[str, Any]] = defaultdict(_stat)
    tickets: dict[str, dict[str, Any]] = defaultdict(_stat)
    projects: dict[str, dict[str, Any]] = defaultdict(_stat)
    health: dict[str, int] = defaultdict(int)
    topics: dict[str, int] = defaultdict(int)
    gate_req: dict[str, datetime] = {}; gate_wait: list[tuple[str, str, float]] = []
    t_open: dict[str, datetime] = {}; t_close: dict[str, datetime] = {}
    for env in bus.replay():
        topics[env.topic] += 1
        if env.topic == "tasks":
            t_open.setdefault(env.key, env.ts)
        if env.topic == "acceptance-results" and env.payload.get("verdict") == "accepted":
            pass  # đóng ticket ghi ở audit của orchestrator (orchestrated) — dùng closed_at bên dưới
        if env.topic != "audit-log": continue
        a = env.payload; act = a.get("action", ""); d = _ev(a)
        if act.startswith("produced:"):
            for bucket in (agents[a["actor"]], models[d.get("model") or "?"],
                           *( [tickets[a["ticket_id"]]] if a.get("ticket_id") else []),
                           *( [projects[a["project_id"]]] if a.get("project_id") else [])):
                bucket["calls"] += 1; bucket["tokens"] += int(a.get("tokens") or 0)
                bucket["cost_usd"] += float(a.get("cost_usd") or 0.0)
                bucket["duration_ms"] += int(d.get("duration_ms") or 0)
                bucket["cache_hit_sum"] += float(d.get("cache_hit") or 0.0)
                bucket["tool_calls"] += int(d.get("tool_calls") or 0)
                if d.get("unpriced"): bucket["unpriced"] += 1
        elif act in HEALTH:
            health[act] += 1
            if act in {"llm_error", "invalid_output", "budget_exhausted", "handler_error"}:
                agents[a["actor"]]["errors"] += 1
                if a.get("ticket_id"): tickets[a["ticket_id"]]["errors"] += 1
            if act == "llm_retry":
                agents[a["actor"]]["retries"] += int(d.get("attempts") or 1)
        elif act == "gate.request":
            gate_req[d.get("subject_id", "")] = env.ts
        elif act == "gate.decide":
            sid = d.get("subject_id", "")
            if sid in gate_req: gate_wait.append((sid, d.get("decision", ""), (env.ts - gate_req.pop(sid)).total_seconds()))
        elif act == "orchestrated" and d.get("topic") == "acceptance-results":
            pass
        if act == "ticket.closed" and a.get("ticket_id"):
            t_close[a["ticket_id"]] = env.ts

    def finish(m: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out = {}
        for k, s in sorted(m.items()):
            s = dict(s); n = s["calls"] or 1
            s["cache_hit_avg"] = round(s.pop("cache_hit_sum") / n, 3)
            s["duration_ms_avg"] = round(s["duration_ms"] / n)
            s["cost_usd"] = round(s["cost_usd"], 4)
            out[k] = s
        return out
    total = _stat()
    for s in agents.values():
        for k in ("calls", "tokens", "cost_usd", "duration_ms", "errors", "retries", "tool_calls", "unpriced"): total[k] += s[k]
    total.pop("cache_hit_sum"); total["cost_usd"] = round(total["cost_usd"], 4)
    lead = {tid: round((t_close[tid] - t_open[tid]).total_seconds()) for tid in t_close if tid in t_open}
    return {"total": total, "agents": finish(agents), "models": finish(models), "tickets": finish(tickets),
            "projects": finish(projects), "health": dict(sorted(health.items())), "topics": dict(sorted(topics.items())),
            "gates": {"decided": len(gate_wait), "pending": len(gate_req),
                      "wait_seconds_avg": round(sum(w for _, _, w in gate_wait) / len(gate_wait)) if gate_wait else None,
                      "wait_seconds_max": round(max((w for _, _, w in gate_wait), default=0))},
            "ticket_lead_seconds": lead}


def prometheus(m: dict[str, Any], prefix: str = "company") -> str:
    """Text exposition format (một gauge/counter mỗi dòng), nhãn theo agent/model/ticket."""
    lines: list[str] = []
    def emit(name: str, value: Any, help_: str, labels: dict[str, str] | None = None, kind: str = "gauge") -> None:
        full = f"{prefix}_{name}"
        if not any(ln.startswith(f"# HELP {full} ") for ln in lines):
            lines.append(f"# HELP {full} {help_}"); lines.append(f"# TYPE {full} {kind}")
        lab = "{" + ",".join(f'{k}="{str(v).replace(chr(34), "")}"' for k, v in (labels or {}).items()) + "}" if labels else ""
        lines.append(f"{full}{lab} {value}")
    for k in ("calls", "tokens", "cost_usd", "errors", "retries", "tool_calls", "duration_ms"):
        emit(f"total_{k}", m["total"][k], f"tổng {k} toàn công ty", kind="counter")
    for dim in ("agents", "models", "tickets", "projects"):
        label = dim[:-1]
        for key, s in m[dim].items():
            for k in ("calls", "tokens", "cost_usd", "errors", "duration_ms"):
                emit(f"{label}_{k}", s[k], f"{k} theo {label}", {label: key}, kind="counter")
            emit(f"{label}_cache_hit_avg", s["cache_hit_avg"], f"tỉ lệ cache hit trung bình theo {label}", {label: key})
    for act, n in m["health"].items():
        emit("health_events", n, "số sự kiện sức khoẻ theo action", {"action": act}, kind="counter")
    for topic, n in m["topics"].items():
        emit("topic_events", n, "số event theo topic", {"topic": topic}, kind="counter")
    g = m["gates"]
    emit("gates_pending", g["pending"], "gate đang chờ người")
    emit("gates_decided", g["decided"], "gate đã quyết", kind="counter")
    if g["wait_seconds_avg"] is not None: emit("gate_wait_seconds_avg", g["wait_seconds_avg"], "thời gian chờ gate trung bình")
    for tid, sec in m["ticket_lead_seconds"].items():
        emit("ticket_lead_seconds", sec, "lead time ticket (tasks đầu → closed)", {"ticket": tid})
    return "\n".join(lines) + "\n"
