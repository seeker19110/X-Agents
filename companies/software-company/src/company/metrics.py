"""Metrics từ bus (ADR-0012): đọc `audit-log` + topic, không cần hạ tầng ngoài.

Trước đây muốn biết agent nào chậm, tốn, hay lỗi phải tự truy SQLite. `collect(bus)` trả về một dict cho người và
`orchestrator metrics`; `prometheus(m)` xuất text exposition (đặt vào node_exporter textfile collector hay scrape qua
file) để nối dashboard sẵn có. Nguồn số liệu:

- audit có số đo token/chi phí (kể cả lượt bị từ chối); `produced:*` (evidence JSON: model,
  duration_ms, cache_hit, turns, tool_calls) → số lượt hoàn thành và thời gian
- audit `llm_error|invalid_output|budget_exhausted|injection_*|llm_retry|context_trimmed` → sức khoẻ
- audit `gate.request` / `gate.decide` → thời gian chờ người
- topic `tasks` (đầu) → trạng thái cuối theo audit/ticket → lead time ticket
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

from .bus import InMemoryBus

HEALTH = ("llm_error", "invalid_output", "budget_exhausted", "injection_detected", "injection_sanitized", "llm_retry",
          "context_trimmed", "handler_error", "tools_used", "tools_trace", "local_checks.unverified",
          "no_progress_warn", "no_progress")  # 4L-3: vòng tool lặp không tiến bộ (cảnh báo / bị cắt)


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
    loop_records: list[dict[str, Any]] = []            # 4L-5: một bản ghi mỗi audit `tools_used`
    tickets_with_tasks: set[str] = set(); tickets_blocked: set[str] = set()
    for env in bus.replay():
        topics[env.topic] += 1
        if env.topic == "tasks":
            t_open.setdefault(env.key, env.ts)
            tickets_with_tasks.add(str(env.key))
        if env.topic == "acceptance-results" and env.payload.get("verdict") == "accepted":
            pass  # đóng ticket ghi ở audit của orchestrator (orchestrated) — dùng closed_at bên dưới
        if env.topic != "audit-log": continue
        a = env.payload; act = a.get("action", ""); d = _ev(a)
        # Cùng sổ token với Supervisor: lượt bị từ chối hoặc đầu ra hỏng vẫn tiêu token và có audit riêng.
        # `calls`/latency chỉ có ở `produced:*`; tổng token bao gồm mọi audit mang số đo token.
        if a.get("tokens") or a.get("cost_usd"):
            for bucket in (agents[a["actor"]], models[d.get("model") or "?"],
                           *([tickets[a["ticket_id"]]] if a.get("ticket_id") else []),
                           *([projects[a["project_id"]]] if a.get("project_id") else [])):
                bucket["tokens"] += int(a.get("tokens") or 0)
                bucket["cost_usd"] += float(a.get("cost_usd") or 0.0)
        if act.startswith("produced:"):
            for bucket in (agents[a["actor"]], models[d.get("model") or "?"],
                           *( [tickets[a["ticket_id"]]] if a.get("ticket_id") else []),
                           *( [projects[a["project_id"]]] if a.get("project_id") else [])):
                bucket["calls"] += 1
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
            if act == "tools_used":
                # `capped`/`max_turns` (4L-5) vắng mặt ở audit cũ (trước bản này) → coi là không chạm trần, không
                # phải lỗi thiếu dữ liệu — cùng cách `d.get(...)` vẫn dùng cho mọi trường tuỳ chọn khác trong file.
                loop_records.append({"turns": int(d.get("turns") or 0), "capped": bool(d.get("capped") or False),
                                     "has_calls": bool(d.get("calls"))})
        elif act == "ticket.blocked":
            tid = d.get("ticket_id") or a.get("ticket_id")
            if tid: tickets_blocked.add(str(tid))
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
            "ticket_lead_seconds": lead,
            "loops": _loops(loop_records, tickets_with_tasks, tickets_blocked)}


def _percentile(vals: list[int], p: int) -> float:
    """`p`-th percentile thuần `statistics` chuẩn (không numpy — kiểm `pyproject.toml` trước khi thêm phụ thuộc mới).
    `quantiles(n=100)` đòi ≥ 2 điểm dữ liệu; `n == 1` thì chính điểm đó là mọi percentile."""
    if len(vals) == 1: return float(vals[0])
    qs = statistics.quantiles(vals, n=100, method="inclusive")
    return qs[max(0, min(len(qs) - 1, p - 1))]


def _loops(records: list[dict[str, Any]], tickets_with_tasks: set[str], tickets_blocked: set[str]) -> dict[str, Any]:
    """Đặc tả L3 "cách đo": số vòng tới hội tụ (`turns_*`), tỉ lệ chạm trần (`capped_ratio`).

    `empty=True` khi không có bản ghi `tools_used` nào (`n == 0`) — KHÔNG suy ra từ `capped_ratio == 0`, vì
    `capped_ratio == 0` nhìn giống "0% chạm trần, tốt" trong khi thật ra là "không đo được gì" (bẫy "số xanh vì
    rỗng", console/TRAPS.md). Người đọc (kể cả console) phải luôn kiểm `empty` trước khi đọc bất kỳ số nào khác.
    """
    n = len(records)
    if n == 0:
        return {"turns_p50": None, "turns_p90": None, "turns_max": None, "capped_ratio": None,
                "no_progress_ratio": None, "retry_max_ratio": None, "n": 0, "empty": True}
    turns = [r["turns"] for r in records]
    capped = [r for r in records if r["capped"]]
    # "không tiến triển": chạm trần MÀ lượt cuối không gọi tool nào — hết lượt trong khi vẫn đứng yên, khác với
    # chạm trần nhưng ít nhất còn đang thử (có gọi tool). Xem TASK-PACK 4L-5 mục 5 (ràng buộc percentile thuần).
    no_progress = [r for r in capped if not r["has_calls"]]
    denom = len(tickets_with_tasks)
    return {
        "turns_p50": round(_percentile(turns, 50), 1),
        "turns_p90": round(_percentile(turns, 90), 1),
        "turns_max": max(turns),
        "capped_ratio": round(len(capped) / n, 4),
        "no_progress_ratio": round(len(no_progress) / len(capped), 4) if capped else 0.0,
        "retry_max_ratio": round(len(tickets_blocked & tickets_with_tasks) / denom, 4) if denom else None,
        "n": n,
        "empty": False,
    }


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
    lp = m["loops"]
    # `empty=True`: không phát gauge nào trong sáu gauge `loop_*` — 0/None giả làm "0% chạm trần, tốt" là đúng bẫy
    # "số xanh vì rỗng" (console/TRAPS.md); scrape thiếu các gauge này CHÍNH LÀ tín hiệu "chưa có dữ liệu vòng tool".
    if not lp["empty"]:
        emit("loop_turns_p50", lp["turns_p50"], "trung vị số vòng tool tới hội tụ (một lượt sản xuất)")
        emit("loop_turns_p90", lp["turns_p90"], "vòng tool p90 tới hội tụ")
        emit("loop_turns_max", lp["turns_max"], "vòng tool nhiều nhất quan sát được")
        emit("loop_capped_ratio", lp["capped_ratio"], "tỉ lệ lượt chạm trần max_turns")
        emit("loop_no_progress_ratio", lp["no_progress_ratio"], "tỉ lệ lượt chạm trần MÀ không gọi tool nào ở lượt cuối")
        if lp["retry_max_ratio"] is not None:
            emit("loop_retry_max_ratio", lp["retry_max_ratio"], "tỉ lệ ticket có task bị ticket.blocked")
    return "\n".join(lines) + "\n"


# ---------- chẩn đoán: 193 lỗi thô → vài khuôn lỗi đọc được ----------

_SO = re.compile(r"\d+")
_MA = re.compile(r"\b[0-9a-f]{8,}\b")
_BS = chr(92)  # viết bằng chr() để lớp thoát của shell/editor không nuốt mất dấu gạch chéo ngược
# `[{_BS}/]` KHÔNG đủ: trong lớp ký tự, `\/` là dấu thoát của `/` nên chỉ khớp `/`. Phải nhân đôi.
_DUONG_DAN = re.compile(rf"[A-Za-z]:[{_BS}{_BS}/][^\s\"']+|/[^\s\"']*/[^\s\"']+")


def chu_ky_loi(msg: str, dai: int = 120) -> str:
    """Rút thông điệp lỗi về CHỮ KÝ để nhóm được: bỏ số, mã hex, đường dẫn.

    `metrics` đếm được `errors: 193` nhưng không nói 193 lỗi đó là những lỗi gì, nên muốn biết phải tự truy
    SQLite — phiên 2026-09-04 tôi viết tay chừng mười lăm truy vấn như vậy. Chuẩn hoá là phần làm nên giá trị:
    "thử lại sau 1960s" và "thử lại sau 43s" là CÙNG một khuôn, còn đọc thô thì thành hai dòng khác nhau.
    """
    s = _DUONG_DAN.sub("<đường-dẫn>", str(msg or ""))
    s = _MA.sub("<mã>", s)
    s = _SO.sub("<số>", s)
    return " ".join(s.split())[:dai]


def diagnose(bus: InMemoryBus, top: int = 10) -> dict[str, Any]:
    """Khuôn lỗi lặp lại, ticket quay vòng, gate — cho người vận hành, không phải cho agent.

    Trả lời đúng những câu tôi phải hỏi thủ công suốt phiên 2026-09-04: lỗi nào lặp nhiều nhất, agent nào hỏng,
    ticket nào quay vòng mà không ai biết, gate nào mở mà không ai quyết.
    """
    khuon: dict[str, dict[str, Any]] = {}
    ticket: dict[str, dict[str, int]] = defaultdict(lambda: {"retry": 0, "blocked": 0, "reopen": 0, "review_block": 0})
    # Đếm riêng khỏi danh sách `dang_cho`: trộn int với list trong một dict làm mypy suy ra `dict[str, object]`
    # rồi `+= 1` thành lỗi kiểu. Ghép lại ở `return`.
    gate_dem: dict[str, int] = {"mo": 0, "quyet": 0, "qua_han": 0}
    mo_gate: dict[str, str] = {}

    for env in bus.replay():
        if env.topic == "tasks":
            t = env.payload
            ticket[env.key]["retry"] = max(ticket[env.key]["retry"], int(t.get("retry") or 0))
        elif env.topic == "review-results" and env.payload.get("verdict") in {"block", "fail"}:
            ticket[str(env.payload.get("ticket_id") or env.key)]["review_block"] += 1
        elif env.topic == "audit-log":
            a = env.payload; act = str(a.get("action", "")); d = _ev(a)
            if act in {"llm_error", "invalid_output", "budget_exhausted", "handler_error", "agent_error_unhandled"}:
                sig = chu_ky_loi(d.get("error") or a.get("evidence") or act)
                k = khuon.setdefault(sig, {"so_lan": 0, "action": act, "agents": set(), "tickets": set(),
                                           "dau": env.ts, "cuoi": env.ts, "vi_du": str(d.get("error") or a.get("evidence") or "")[:200]})
                k["so_lan"] += 1; k["cuoi"] = env.ts
                k["agents"].add(str(d.get("agent") or a.get("actor") or "?"))
                if a.get("ticket_id"): k["tickets"].add(str(a["ticket_id"]))
            elif act == "ticket.blocked" and d.get("ticket_id"):
                ticket[str(d["ticket_id"])]["blocked"] += 1
            elif act == "gate.request":
                gate_dem["mo"] += 1
                if d.get("subject_id"): mo_gate[str(d["subject_id"])] = str(d.get("kind") or "?")
            elif act == "gate.decide":
                gate_dem["quyet"] += 1; mo_gate.pop(str(d.get("subject_id")), None)
                if d.get("subject_id"): ticket[str(d["subject_id"])]["reopen"] += 1
            elif act == "gate.overdue":
                gate_dem["qua_han"] += 1

    xep = sorted(khuon.items(), key=lambda kv: -kv[1]["so_lan"])[:top]
    return {
        "loi_theo_khuon": [{"chu_ky": s, "so_lan": v["so_lan"], "action": v["action"],
                            "agents": sorted(v["agents"]), "tickets": sorted(v["tickets"])[:5],
                            "dau": v["dau"].isoformat(), "cuoi": v["cuoi"].isoformat(), "vi_du": v["vi_du"]}
                           for s, v in xep],
        "so_khuon": len(khuon),
        "ticket_quay_vong": {t: v for t, v in sorted(ticket.items())
                             if v["blocked"] or v["reopen"] or v["review_block"] >= 2},
        "gate": {**gate_dem, "dang_cho": [f"{sid}:{kind}" for sid, kind in sorted(mo_gate.items())]},
    }
