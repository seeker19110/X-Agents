"""Đọc trạng thái hai công ty (software-company, Studio-creators) + gateway thành MỘT dict thuần cho trang console.

Nguyên tắc:

- **Chỉ đọc.** SQLite mở bằng URI `mode=ro`: không tạo file, không chạy DDL, không đổi journal mode. Vì vậy không dùng
  `SQLiteBus` ở đây (constructor của nó `CREATE TABLE` + `PRAGMA journal_mode=WAL` — ghi vào DB của công ty đang chạy).
  Envelope đọc lên được nạp thẳng vào `InMemoryBus` thật của từng công ty rồi replay qua chính DeliveryLead /
  ProductionDesk / Supervisor / PersistentGate của họ — trạng thái ticket/video/gate suy ra đúng như orchestrator, không
  chép lại máy trạng thái ở đây.
- **Không bao giờ ném.** DB thiếu hoặc hỏng là trạng thái bình thường (chưa chạy công ty đó bao giờ): `sources[...]`
  mang `ok=false` + lý do tiếng Việt, phần dữ liệu của xưởng đó rỗng.
- Ngưỡng `sev` của gate lấy từ `HumanGate.timeout` / `HumanGate.remind_at` của chính công ty, không viết số ở đây.

Hợp đồng cấu trúc trả về: `console/API.md`.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from company import gate_cli as company_gate_cli
from company import llm as company_llm
from company import metrics as company_metrics
from company import routing as company_routing
from company.bus import InMemoryBus as CompanyBus
from company.delivery import DeliveryLead
from company.events import Envelope as CompanyEnvelope
from company.events import Task
from company.registry import load_agents as load_company_agents
from company.supervisor import Supervisor as CompanySupervisor
from studio import gate_cli as studio_gate_cli
from studio import llm as studio_llm
from studio import routing as studio_routing
from studio.bus import InMemoryBus as StudioBus
from studio.desk import ProductionDesk
from studio.events import Envelope as StudioEnvelope
from studio.registry import load_agents as load_studio_agents
from studio.supervisor import Supervisor as StudioSupervisor

COMPANY = "software-company"
STUDIO = "Studio-creators"
TIERS = ("strong", "standard", "light")
CONTROL_TOPICS = frozenset({"audit-log", "shared-context", "supervisor-actions"})  # như CONTROL_TOPICS của hai orchestrator
ORCHESTRATOR = "orchestrator"
LOG_LIMIT = 200        # API.md: `log` tối đa 200 bản ghi
COST_WINDOW_DAYS = 14  # API.md: `cost_days` = 14 ngày gần nhất
TOP_AGENTS = 10
STUCK_STATES = frozenset({"blocked", "escalated"})
GATEWAY_TIMEOUT_S = 1.0  # gateway chết không được làm chậm cả trang quá ~1s
NOTE_WIDTH = 120


class _SourceError(Exception):
    """Không đọc được một nguồn — thông điệp tiếng Việt, hiện thẳng trong `sources[...].error`."""


# ---------- đọc SQLite (chỉ đọc) ----------

def _bodies(db: Path | None) -> list[str]:
    if db is None: raise _SourceError("chưa cấu hình đường dẫn DB")
    p = Path(db)
    if not p.exists(): raise _SourceError("chưa có file DB")
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=GATEWAY_TIMEOUT_S)
        try:
            return [row[0] for row in con.execute("SELECT body FROM events ORDER BY seq")]
        finally:
            con.close()
    except sqlite3.Error as e:
        raise _SourceError(f"không đọc được DB: {e}") from e


def _envelopes(db: Path | None, model: Any) -> list[Any]:
    out = []
    for body in _bodies(db):
        try:
            out.append(model.model_validate_json(body))
        except Exception as e:  # hàng hỏng: DB không còn đọc được đến nơi đến chốn, báo rõ thay vì trả nửa vời
            raise _SourceError(f"log hỏng, không đọc được envelope: {str(e)[:120]}") from e
    return out


def _load_bus(bus: Any, envelopes: list[Any]) -> Any:
    """Nạp log đã đọc vào bus thật mà KHÔNG publish (publish sẽ kiểm quyền, gọi subscriber và — với bus bền vững — ghi)."""
    bus._log = list(envelopes)
    return bus


def _evidence(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        d = json.loads(payload.get("evidence") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _check(value: Any) -> str:
    """`local_checks.lint/tests` là boolean trong schema; trang hiện chữ."""
    if value is None: return "?"
    return "pass" if value else "fail"


def _hours(created_at: datetime, now: datetime) -> int:
    return max(0, math.floor((now - created_at).total_seconds() / 3600))


def _queue(envelopes: list[Any]) -> int:
    """Số event còn trong hàng đợi orchestrator: `_actionable` và chưa có audit `orchestrated` — cùng luật với cả hai
    orchestrator (CONTROL_TOPICS bị bỏ qua, trừ `gate.decide`)."""
    processed = {_evidence(e.payload).get("event_id") for e in envelopes
                 if e.topic == "audit-log" and e.payload.get("actor") == ORCHESTRATOR
                 and e.payload.get("action") == "orchestrated"}
    n = 0
    for e in envelopes:
        actionable = (e.payload.get("action") == "gate.decide") if e.topic == "audit-log" else e.topic not in CONTROL_TOPICS
        if actionable and e.event_id not in processed: n += 1
    return n


# ---------- khung nhìn một công ty ----------

class _View:
    """Trạng thái đã replay của một xưởng. `ok=False` thì mọi danh sách rỗng và `error` nói vì sao."""

    def __init__(self, name: str, db: Path | None) -> None:
        self.name, self.db = name, db
        self.ok: bool = False
        self.error: str | None = None
        self.envelopes: list[Any] = []
        self.metrics: dict[str, Any] = {"total": {"calls": 0, "tokens": 0, "cost_usd": 0.0, "tool_calls": 0, "unpriced": 0},
                                        "agents": {}}
        self.gate: Any = None
        try:
            self.envelopes = self._read()
            self._replay()
            self.ok, self.error = True, None
        except _SourceError as e:
            self.error = str(e)

    def _read(self) -> list[Any]:
        raise NotImplementedError

    def _replay(self) -> None:
        raise NotImplementedError

    @property
    def source(self) -> dict[str, Any]:
        return {"ok": self.ok, "db": str(self.db) if (self.db and self.ok) else None,
                "events": len(self.envelopes), "error": self.error}

    # ---- phần dùng chung cho cả hai xưởng ----

    def gates(self, now: datetime) -> list[dict[str, Any]]:
        if not self.ok or self.gate is None: return []
        over_h = self.gate.timeout.total_seconds() / 3600
        warn_h = self.gate.remind_at.total_seconds() / 3600
        out = []
        for sid, r in self.gate.pending.items():
            h = _hours(r.created_at, now)
            sev = "over" if h >= over_h else ("warn" if h >= warn_h else "calm")
            out.append({"id": sid, "xuong": self.name, "kind": r.kind, "by": r.created_by or "-",
                        "trigger": getattr(r, "triggered_by", None) or "", "hours": h, "sev": sev,
                        "title": self.gate_title(r), "facts": self.gate_facts(r),
                        "cl": [[item, self.checklist_note(r, item)] for item in r.checklist]})
        out.sort(key=lambda g: -g["hours"])
        return out

    def gate_title(self, r: Any) -> str:
        return f"{r.kind} · {r.subject_id}"

    def gate_facts(self, r: Any) -> list[list[str]]:
        return [["kind", r.kind], ["subject_id", r.subject_id], ["created_by", r.created_by or "-"]]

    def checklist_note(self, r: Any, item: str) -> str:
        """Mô tả ngắn cho một mục checklist: mục dạng `review:<nguồn>:<verdict>` lấy nguyên nhân từ review thật."""
        parts = item.split(":")
        if parts[0] == "review" and len(parts) >= 2:
            note = self.review_note(r.subject_id, parts[1])
            if note: return note[:NOTE_WIDTH]
        return ""

    def _review_note(self, id_field: str, subject_id: str, source: str) -> str:
        """Kết luận review mới nhất của một nguồn cho subject — dùng làm mô tả ngắn của mục checklist."""
        for e in reversed(self.envelopes):
            p = e.payload
            if e.topic != "review-results" or p.get(id_field) != subject_id or p.get("source") != source: continue
            detail = p.get("root_cause") or "; ".join(f.get("text", "") for f in p.get("findings", []))
            return f"{p.get('verdict', '?')} · {detail}" if detail else str(p.get("verdict", "?"))
        return ""

    def review_note(self, subject_id: str, source: str) -> str:
        return ""

    def audits(self) -> list[Any]:
        return [e for e in self.envelopes if e.topic == "audit-log"]

    def log(self) -> list[tuple[datetime, dict[str, Any]]]:
        """(ts, dòng log) — ts để gộp hai xưởng theo đúng thứ tự thời gian, không phải theo chuỗi giờ:phút."""
        rows: list[tuple[datetime, dict[str, Any]]] = []
        for e in reversed(self.audits()):
            p = e.payload
            if not str(p.get("action", "")).startswith("produced:"): continue
            rows.append((e.ts, {"t": e.ts.astimezone().strftime("%H:%M"), "a": p.get("actor", "?"),
                                "ac": p.get("action", ""), "k": p.get("ticket_id") or p.get("video_id") or e.key,
                                "tok": int(p.get("tokens") or 0), "c": round(float(p.get("cost_usd") or 0.0), 4)}))
            if len(rows) >= LOG_LIMIT: break
        return rows

    def supervisor_actions(self) -> list[dict[str, Any]]:
        return [{"t": e.payload.get("target", ""), "a": e.payload.get("action", ""), "r": e.payload.get("reason", ""),
                 "w": e.ts.astimezone().strftime("%H:%M")}
                for e in reversed(self.envelopes) if e.topic == "supervisor-actions"]

    def tiers(self) -> dict[str, str]:
        return {}

    def latest_by(self, topic: str, keyfn: Any) -> dict[Any, Any]:
        out: dict[Any, Any] = {}
        for e in self.envelopes:
            if e.topic == topic: out[keyfn(e)] = e
        return out


class CompanyView(_View):
    """software-company: DeliveryLead + Supervisor + PersistentGate thật, replay trên log đã đọc."""

    def _read(self) -> list[Any]:
        return _envelopes(self.db, CompanyEnvelope)

    def _replay(self) -> None:
        self.bus = _load_bus(CompanyBus(enforce_owners=False), self.envelopes)
        self.gate = company_gate_cli.PersistentGate(self.bus)
        self.lead = DeliveryLead(self.bus, self.gate)
        self.sup = CompanySupervisor(self.bus)
        for env in self.envelopes:
            # Khi chạy thật, ticket được `DeliveryLead.dispatch()` đăng ký từ plan; replay chỉ có topic `tasks`, nên
            # ticket lần đầu xuất hiện được đăng ký ở đây đúng như `_publish_task` để handler PR/review chạy tiếp.
            if env.topic == "tasks":
                t = Task.model_validate(env.payload)
                if t.ticket_id not in self.lead.tickets:
                    self.lead.tickets[t.ticket_id] = t
                    self.lead.state[t.ticket_id] = "dispatched"
            self.lead.replay(env)
            self.sup.replay(env)
        self.report = self.sup.sprint_report()
        self.metrics = company_metrics.collect(self.bus)

    def tiers(self) -> dict[str, str]:
        try:
            return {a: spec.model_tier for a, spec in load_company_agents(check_owners=False).items()}
        except Exception:
            return {}

    def gate_title(self, r: Any) -> str:
        t = self.lead.tickets.get(r.subject_id)
        return t.title if t else f"{r.kind} · {r.subject_id}"

    def gate_facts(self, r: Any) -> list[list[str]]:
        facts = super().gate_facts(r)
        t = self.lead.tickets.get(r.subject_id)
        if t: facts += [["ticket_id", t.ticket_id], ["assignee", t.assignee], ["state", self.lead.state.get(t.ticket_id, "?")]]
        return facts

    def review_note(self, subject_id: str, source: str) -> str:
        return self._review_note("ticket_id", subject_id, source)

    def tickets(self) -> list[dict[str, Any]]:
        if not self.ok: return []
        out = []
        for tid, st in self.lead.state.items():
            t = self.lead.tickets.get(tid)
            b = self.sup.budgets.get(tid)
            out.append({"id": tid, "st": st, "who": t.assignee if t else "?", "t": t.title if t else tid,
                        "used": b.used if b else 0, "bud": t.budget_tokens if t else 0,
                        "est": (t.estimate_tokens or 0) if t else 0, "retry": t.retry if t else 0})
        return out

    def prs(self) -> list[dict[str, Any]]:
        if not self.ok: return []
        out = []
        for e in self.latest_by("pull-requests", lambda e: e.payload.get("ticket_id") or e.key).values():
            p = e.payload; checks = p.get("local_checks") or {}
            out.append({"id": p.get("ticket_id") or e.key, "br": p.get("branch", ""), "s": p.get("summary", ""),
                        "lint": _check(checks.get("lint")), "tests": _check(checks.get("tests")),
                        "v": str(checks.get("verified_by") or "unverified")})
        return out

    def reviews(self) -> list[dict[str, Any]]:
        if not self.ok: return []
        out = []
        for e in reversed(list(self.latest_by("review-results",
                                              lambda e: (e.payload.get("ticket_id"), e.payload.get("source"))).values())):
            p = e.payload
            blocking = [f.get("text", "") for f in p.get("findings", []) if f.get("level") == "block"]
            detail = p.get("root_cause") or ("; ".join(blocking) if blocking else "")
            out.append({"id": p.get("ticket_id") or e.key, "src": p.get("source", "?"), "v": p.get("verdict", "?"),
                        "f": f"{p.get('verdict', '?')} · {detail}" if detail else str(p.get("verdict", "?"))})
        return out

    def stuck(self) -> int:
        return sum(1 for st in self.lead.state.values() if st in STUCK_STATES) if self.ok else 0


class StudioView(_View):
    """Studio-creators: ProductionDesk + Supervisor + PersistentGate thật."""

    def _read(self) -> list[Any]:
        return _envelopes(self.db, StudioEnvelope)

    def _replay(self) -> None:
        self.bus = _load_bus(StudioBus(enforce_owners=False), self.envelopes)
        self.gate = studio_gate_cli.PersistentGate(self.bus)
        self.desk = ProductionDesk(self.bus)
        self.sup = StudioSupervisor(self.bus)
        for env in self.envelopes:
            self.desk.replay(env)
            self.sup.replay(env)
        self.report = self.sup.report()
        # `studio` không có module metrics riêng; `company.metrics` chỉ đọc envelope + audit-log (cùng hình dạng) nên
        # dùng lại thay vì chép logic đếm call/token/tool sang đây.
        self.metrics = company_metrics.collect(self.bus)

    def tiers(self) -> dict[str, str]:
        try:
            return {a: spec.model_tier for a, spec in load_studio_agents().items()}
        except Exception:
            return {}

    def _video_of(self, subject_id: str) -> str:
        return subject_id.split("-", 1)[1] if subject_id.startswith(("PUB-", "PLAN-", "REP-")) else subject_id

    def gate_title(self, r: Any) -> str:
        b = self.desk.briefs.get(self._video_of(r.subject_id))
        return b.working_title if b else f"{r.kind} · {r.subject_id}"

    def gate_facts(self, r: Any) -> list[list[str]]:
        facts = super().gate_facts(r)
        vid = self._video_of(r.subject_id)
        b = self.desk.briefs.get(vid)
        if b: facts += [["video_id", vid], ["format", b.format], ["state", self.desk.state.get(vid, "?")]]
        return facts

    def review_note(self, subject_id: str, source: str) -> str:
        return self._review_note("video_id", self._video_of(subject_id), source)

    def videos(self) -> list[dict[str, Any]]:
        if not self.ok: return []
        out = []
        for vid, st in self.desk.state.items():
            b = self.desk.briefs.get(vid)
            bud = self.sup.budgets.get(vid)
            out.append({"id": vid, "st": st, "t": b.working_title if b else vid, "fmt": b.format if b else "long",
                        "used": bud.used if bud else 0, "bud": b.budget_tokens if b else 0})
        return out

    def perf(self) -> list[dict[str, Any]]:
        if not self.ok: return []
        return [{"id": e.payload.get("video_id") or e.key, "imp": int(e.payload.get("impressions") or 0),
                 "views": int(e.payload.get("views") or 0), "ctr": float(e.payload.get("ctr") or 0.0),
                 "avd": round(float(e.payload.get("avg_view_duration_s") or 0.0))}
                for e in self.latest_by("performance-snapshots", lambda e: e.payload.get("video_id") or e.key).values()]

    def retention(self) -> dict[str, Any]:
        if not self.ok: return {"video_id": None, "points": []}
        for e in reversed(self.envelopes):
            if e.topic != "performance-snapshots": continue
            curve = e.payload.get("retention_curve") or []
            if curve:
                return {"video_id": e.payload.get("video_id") or e.key,
                        "points": [[p.get("t"), p.get("pct")] for p in curve]}
        return {"video_id": None, "points": []}

    def stuck(self) -> int:
        return sum(1 for st in self.desk.state.values() if st in STUCK_STATES) if self.ok else 0


# ---------- backends: llm.yaml (routing.status) rồi mới đến gateway ----------

def _routing_status() -> list[dict[str, Any]] | None:
    """`routing.status()` thật dựng từ `llm.yaml` của một trong hai công ty (nếu có file). Client không được tạo ở đây —
    console chỉ hỏi trạng thái, không gọi model — nên mỗi backend dùng `FakeClient` làm chỗ giữ chỗ."""
    for llm_mod, routing_mod in ((company_llm, company_routing), (studio_llm, studio_routing)):
        path = getattr(llm_mod, "CONFIG_FILE", None)
        if not path or not Path(path).exists(): continue
        try:
            cfg = llm_mod.load_config(Path(path))
            if not cfg.backends: continue
            backends = []
            for data in cfg.backends:
                bc = cfg.backend_config(data)
                backends.append(routing_mod.Backend(
                    name=bc.name, client=llm_mod.FakeClient(), tiers=bc.tiers_configured(),
                    supports_tools=bool(data.get("supports_tools", bc.provider not in ("claude-code", "codex")))))
            r = cfg.routing
            client = routing_mod.RoutingClient(backends, cooldown_s=float(r.get("cooldown_s", 3600)),
                                               transient_cooldown_s=float(r.get("transient_cooldown_s", 60)),
                                               prefer={str(k): str(v) for k, v in (r.get("prefer") or {}).items()})
            return [{"n": b["name"], "tiers": " · ".join(b["tiers"]), "tools": "có" if b.get("tools", True) else "không",
                     "ok": bool(b["ready"]), "st": "Sẵn sàng" if b["ready"] else f"Nghỉ {b['cooldown_remaining']}s",
                     "calls": b["calls"], "fail": b["failures"], "note": b["reason"]} for b in client.status()]
        except Exception:
            continue
    return None


def _gateway_status(url: str, token_file: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    """Pool tài khoản của gateway qua `GET /auth/status`. Trả (backends, lỗi); timeout ngắn để gateway chết không treo trang."""
    req = urllib.request.Request(url.rstrip("/") + "/auth/status", headers={"Accept": "application/json"})
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
            if token: req.add_header("Authorization", f"Bearer {token}")
        except OSError:
            pass
    try:
        with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return [], f"không hỏi được gateway: {str(e)[:120]}"
    out = []
    for a in data.get("accounts", []):
        cooldown = int(a.get("cooldown_remaining") or 0)
        ok = cooldown == 0 and not a.get("is_expired")
        out.append({"n": a.get("email") or "?", "tiers": "", "tools": "không", "ok": ok,
                    "st": "Sẵn sàng" if ok else (f"Nghỉ {cooldown}s" if cooldown else "Hết hạn token"),
                    "calls": 0, "fail": int(a.get("last_failure_status") or 0),
                    "note": str(a.get("source") or "")})
    return out, None


# ---------- tổng hợp ----------

def _cost_days(views: list[_View], now: datetime) -> dict[str, Any]:
    """Chi phí audit-log 14 ngày gần nhất, gộp theo ngày và theo tier của agent (front matter `model_tier`)."""
    today = now.date()
    days = [today - timedelta(days=i) for i in range(COST_WINDOW_DAYS - 1, -1, -1)]
    buckets: dict[date, list[float]] = {d: [0.0, 0.0, 0.0] for d in days}
    for v in views:
        tiers = v.tiers()
        for e in v.audits():
            p = e.payload
            if not str(p.get("action", "")).startswith("produced:"): continue
            d = e.ts.astimezone().date()
            if d not in buckets: continue
            tier = tiers.get(str(p.get("actor", "")), "standard")
            buckets[d][TIERS.index(tier) if tier in TIERS else 1] += float(p.get("cost_usd") or 0.0)
    return {"days": [f"{d.day}/{d.month}" for d in days],
            "series": [[round(x, 4) for x in buckets[d]] for d in days]}


def _today_totals(views: list[_View], now: datetime) -> tuple[float, int]:
    today = now.astimezone().date()
    cost, tokens = 0.0, 0
    for v in views:
        for e in v.audits():
            p = e.payload
            if not str(p.get("action", "")).startswith("produced:"): continue
            if e.ts.astimezone().date() != today: continue
            cost += float(p.get("cost_usd") or 0.0); tokens += int(p.get("tokens") or 0)
    return round(cost, 4), tokens


def _agents(views: list[_View]) -> list[list[Any]]:
    cost: dict[str, float] = defaultdict(float)
    for v in views:
        for agent, stat in v.metrics.get("agents", {}).items():
            cost[agent] += float(stat.get("cost_usd") or 0.0)
    return [[a, round(c, 4)] for a, c in sorted(cost.items(), key=lambda kv: -kv[1])[:TOP_AGENTS]]


def _calibration(company: CompanyView) -> float | None:
    if not company.ok: return None
    vals = [row["ratio_median"] for row in company.report.get("calibration", {}).values() if row.get("ratio_median")]
    return round(statistics.median(vals), 2) if vals else None


def _tiles(company: CompanyView, studio: StudioView, views: list[_View], now: datetime) -> dict[str, Any]:
    tickets, videos = company.tickets(), studio.videos()
    cost_today, tokens_today = _today_totals(views, now)
    totals = [v.metrics["total"] for v in views]
    creport = company.report if company.ok else {}
    sreport = studio.report if studio.ok else {}
    rework = creport.get("rework_rate")
    catch = creport.get("review_catch_rate")
    return {
        "events": sum(len(v.envelopes) for v in views),
        "queue": sum(_queue(v.envelopes) for v in views),
        "model_calls": sum(int(t.get("calls") or 0) for t in totals),
        "tool_calls": sum(int(t.get("tool_calls") or 0) for t in totals),
        "tokens": sum(int(t.get("tokens") or 0) for t in totals),
        "project_budget_tokens": sum(t["bud"] for t in tickets) + sum(v["bud"] for v in videos),
        "rework_rate": rework if rework is not None else sreport.get("rework_rate"),
        "review_catch_rate": catch if catch is not None else sreport.get("review_catch_rate"),
        "prs_unverified": int(creport.get("prs_unverified") or 0),
        "cost_today_usd": cost_today,
        "tokens_today": tokens_today,
        "stuck_tickets": company.stuck() + studio.stuck(),
        "project_cost_usd": round(sum(creport.get("project_cost_usd", {}).values()), 4),
        "project_budget_usd": company.sup.project_budget_usd if company.ok else None,
        "unpriced_calls": sum(int(t.get("unpriced") or 0) for t in totals),
        "calibration": _calibration(company),
    }


def collect(company_db: Path | None, studio_db: Path | None,
            gateway_token_file: Path | None = None,
            gateway_url: str = "http://127.0.0.1:8100") -> dict[str, Any]:
    """Trạng thái hợp nhất của hai công ty + gateway (xem `console/API.md`). Không bao giờ ném: nguồn nào hỏng thì
    `sources[<nguồn>].ok = false` kèm lý do và phần dữ liệu của nguồn đó rỗng."""
    now = datetime.now(UTC).astimezone()
    company, studio = CompanyView(COMPANY, company_db), StudioView(STUDIO, studio_db)
    views: list[_View] = [company, studio]

    backends = _routing_status()
    if backends is None:
        backends, gateway_error = _gateway_status(gateway_url, gateway_token_file)
        if gateway_error: backends = []
    else:
        gateway_error = None  # backend lấy từ llm.yaml, không cần hỏi gateway

    log = [row for _, row in sorted((r for v in views for r in v.log()), key=lambda r: r[0], reverse=True)[:LOG_LIMIT]]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "sources": {COMPANY: company.source, STUDIO: studio.source,
                    "gateway": {"ok": gateway_error is None, "url": gateway_url, "error": gateway_error}},
        "tiles": _tiles(company, studio, views, now),
        "gates": company.gates(now) + studio.gates(now),
        "tickets": company.tickets(),
        "prs": company.prs(),
        "reviews": company.reviews(),
        "videos": studio.videos(),
        "perf": studio.perf(),
        "retention": studio.retention(),
        "cost_days": _cost_days(views, now),
        "agents": _agents(views),
        "backends": backends,
        "supervisor": [a for v in views for a in v.supervisor_actions()],
        "log": log,
    }
