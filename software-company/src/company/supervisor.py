from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .bus import InMemoryBus
from .events import NAMESPACE_OWNERS, AuditLog, Envelope, SupervisorAction, Task
from .guard import scan

# F16: token của 3 lượt review (mỗi lượt mang system prompt + blackboard) không tính vào ngân sách ticket — delivery-lead
# ước lượng công của engineer, còn review là chi phí cố định của quy trình; cộng chung thì mọi ticket đều bị cắt.
REVIEW_ACTORS = frozenset({"reviewer", "qa-debugger", "security-engineer"})


@dataclass
class Budget:
    limit: int
    used: int = 0            # token của agent làm ticket (so với `limit`)
    review_used: int = 0     # token của reviewer/QA/security cho ticket — theo dõi, không trừ vào `limit`
    limit_usd: float | None = None  # trần tiền của ticket (Task.budget_usd), ngoài trần token
    cost_usd: float = 0.0
    @property
    def ratio(self) -> float: return self.used / self.limit if self.limit else 0.0
    @property
    def ratio_usd(self) -> float: return self.cost_usd / self.limit_usd if self.limit_usd else 0.0

class Supervisor:
    """Watchdog + cost controller + knowledge base. Subscribe mọi topic.

    Ngân sách đo hai đơn vị (ADR-0012): token (như trước) và USD từ `audit-log.cost_usd` — token của model mạnh và model
    rẻ khác giá nhiều lần, chỉ đếm token thì không biết đang đốt bao nhiêu tiền. Trần theo ticket (`Task.budget_usd`)
    và theo dự án (`project_budget_usd`, từ llm.yaml `budget_usd`): chạm 80% → warn, chạm 100% → budget_cut ticket /
    pause dự án. Lời gọi không có giá (`unpriced`) được đếm riêng để không ai tưởng là miễn phí."""
    WARN_AT, CUT_AT = 0.8, 1.0

    def __init__(self, bus: InMemoryBus, max_retries: int = 3, ticket_timeout: timedelta = timedelta(hours=4),
                 project_budget_usd: float | None = None):
        self.bus, self.max_retries, self.ticket_timeout = bus, max_retries, ticket_timeout
        self.project_budget_usd = project_budget_usd
        self.budgets: dict[str, Budget] = {}
        self.project_cost: dict[str, float] = defaultdict(float)
        self.project_warned: set[str] = set(); self.project_paused: set[str] = set()
        self.unpriced = 0
        self.last_seen: dict[str, datetime] = {}
        self.error_signatures: dict[str, list[str]] = defaultdict(list)
        self.actions: list[SupervisorAction] = []
        self.knowledge: list[dict] = []
        self._escalated_once: set[str] = set()
        self.replaying = False  # dựng lại từ log: cộng dồn ngân sách/chữ ký lỗi nhưng không phát lại supervisor-actions
        bus.subscribe("*", self._on)

    def _act(self, target: str, action: str, reason: str, evidence: str | None = None) -> None:
        a = SupervisorAction(target=target, action=action, reason=reason, evidence=evidence)  # type: ignore[arg-type]
        self.actions.append(a)
        if not self.replaying:
            self.bus.publish(Envelope(topic="supervisor-actions", key=target, actor="supervisor", payload=a.model_dump()))

    def replay(self, env: Envelope) -> None:
        prev, self.replaying = self.replaying, True
        try:
            self._on(env)
        finally:
            self.replaying = prev

    def _on(self, env: Envelope) -> None:
        if env.actor == "supervisor":
            return
        self.last_seen[env.key] = env.ts
        if env.topic == "tasks":
            t = Task.model_validate(env.payload)
            self.budgets.setdefault(t.ticket_id, Budget(t.budget_tokens, limit_usd=t.budget_usd))
            if t.retry >= self.max_retries:
                self._act(t.ticket_id, "escalate", f"retry {t.retry} ≥ {self.max_retries}")
        elif env.topic == "audit-log":
            a = AuditLog.model_validate(env.payload)
            if a.action.startswith("produced:") and '"unpriced": true' in (a.evidence or ""):
                self.unpriced += 1
            if a.ticket_id and a.ticket_id in self.budgets:
                b = self.budgets[a.ticket_id]; b.cost_usd += a.cost_usd
                if a.actor in REVIEW_ACTORS: b.review_used += a.tokens
                else: b.used += a.tokens
                if b.ratio >= self.CUT_AT: self._act(a.ticket_id, "budget_cut", f"dùng {b.used}/{b.limit} token")
                elif b.limit_usd and b.ratio_usd >= self.CUT_AT:
                    self._act(a.ticket_id, "budget_cut", f"dùng {b.cost_usd:.2f}/{b.limit_usd:.2f} USD")
                elif b.ratio >= self.WARN_AT: self._act(a.ticket_id, "warn", f"đã dùng {b.ratio:.0%} ngân sách token")
                elif b.limit_usd and b.ratio_usd >= self.WARN_AT:
                    self._act(a.ticket_id, "warn", f"đã dùng {b.ratio_usd:.0%} ngân sách tiền ({b.cost_usd:.2f} USD)")
            if a.project_id and a.cost_usd:
                self.project_cost[a.project_id] += a.cost_usd
                self._check_project(a.project_id)
        elif env.topic == "review-results" and env.payload.get("verdict") in {"fail", "block"}:
            sig = env.payload.get("root_cause") or " | ".join(f["text"] for f in env.payload.get("findings", []))
            sigs = self.error_signatures[env.key]; sigs.append(sig)
            if sigs.count(sig) >= 2:
                self._act(env.key, "escalate", "cùng lỗi lặp ≥ 2 lần", evidence=sig)
        elif env.topic == "shared-context":
            if env.actor not in NAMESPACE_OWNERS.get(env.payload["namespace"], set()):
                self._act(env.actor, "pause", "ghi sai namespace")

    def _check_project(self, pid: str) -> None:
        if not self.project_budget_usd: return
        cost = self.project_cost[pid]; ratio = cost / self.project_budget_usd
        if ratio >= self.CUT_AT and pid not in self.project_paused:
            self.project_paused.add(pid)
            self._act(pid, "pause", f"dự án dùng {cost:.2f}/{self.project_budget_usd:.2f} USD — cần người cấp thêm rồi resume")
        elif ratio >= self.WARN_AT and pid not in self.project_warned:
            self.project_warned.add(pid)
            self._act(pid, "warn", f"dự án đã dùng {ratio:.0%} ngân sách tiền ({cost:.2f} USD)")

    def escalate_gate(self, subject_id: str, reason: str, once_key: str | None = None) -> None:
        """Gate quá hạn: người duyệt im lặng cũng là một dạng bế tắc, phải hiện ra như mọi bế tắc khác."""
        key = once_key or f"gate:{subject_id}"
        if key in self._escalated_once: return
        self._escalated_once.add(key)
        self._act(subject_id, "escalate", reason)

    def check_timeouts(self, now: datetime | None = None, active: set[str] | None = None) -> list[str]:
        """Escalate key im lặng quá ticket_timeout. `active` (ticket đang chạy, từ delivery-lead) giới hạn phạm vi
        để không escalate ticket đã đóng; mỗi key chỉ escalate một lần cho tới khi có event mới."""
        now = now or datetime.now(UTC); stuck = []
        for key, ts in self.last_seen.items():
            if active is not None and key not in active: continue
            if now - ts > self.ticket_timeout:
                stuck.append(key); self.last_seen[key] = now
                self._act(key, "escalate", f"không hoạt động > {self.ticket_timeout}")
        return stuck

    def detect_injection(self, text: str) -> bool:
        return not scan(text).clean

    def record_lesson(self, context: str, problem: str, solution: str, evidence: str) -> None:
        self.knowledge.append({"context": context, "problem": problem, "solution": solution, "evidence": evidence})

    def lessons(self) -> list[dict]:
        """Mọi bài học estimate-vs-actual đã ghi lên blackboard `knowledge` (bền vững qua bus, không chỉ bộ nhớ)."""
        out = []
        for env in self.bus.replay(topic="shared-context", key="knowledge"):
            if not str(env.payload.get("content_ref", "")).startswith("audit-log:lesson:"): continue
            try: d = json.loads(env.payload.get("summary") or "{}")
            except json.JSONDecodeError: continue
            if isinstance(d, dict) and d.get("ticket_id"): out.append(d)
        return out

    def calibration(self) -> dict[str, dict]:
        """Hệ số hiệu chỉnh ước lượng theo assignee: median(actual/estimate) và số mẫu, từ bài học đã ghi.
        Delivery-lead nhận bảng này khi lập kế hoạch để ước lượng lần sau sát hơn (vòng học đóng lại ở đây)."""
        by: dict[str, list[float]] = defaultdict(list)
        for d in self.lessons():
            if d.get("ratio") and d.get("assignee"): by[d["assignee"]].append(float(d["ratio"]))
        return {a: {"ratio_median": round(statistics.median(v), 2), "samples": len(v)} for a, v in sorted(by.items())}

    def sprint_report(self) -> dict:
        """Estimate vs actual token/tiền mỗi ticket, tỷ lệ làm lại, tỷ lệ review bắt lỗi, chi phí theo agent/model,
        tổng hành động — cho retrospective."""
        tickets: dict[str, dict[str, Any]] = {}
        for env in self.bus.replay(topic="tasks"):
            t = Task.model_validate(env.payload); b = self.budgets.get(t.ticket_id)
            tickets[t.ticket_id] = {"estimate_tokens": t.estimate_tokens, "budget_tokens": t.budget_tokens,
                                    "retry": t.retry, "actual_tokens": b.used if b else 0,
                                    "review_tokens": b.review_used if b else 0,
                                    "budget_usd": t.budget_usd, "cost_usd": round(b.cost_usd, 4) if b else 0.0}
        for row in tickets.values():
            est = row["estimate_tokens"]
            row["ratio"] = round(row["actual_tokens"] / est, 2) if est else None
        actions: defaultdict[str, int] = defaultdict(int)
        for act in self.actions: actions[act.action] += 1
        cost_by_agent: dict[str, float] = defaultdict(float); cost_by_model: dict[str, float] = defaultdict(float)
        for e in self.bus.replay(topic="audit-log"):
            log = e.payload
            if not str(log.get("action", "")).startswith("produced:"): continue
            cost_by_agent[log["actor"]] += float(log.get("cost_usd") or 0.0)
            try: model = json.loads(log.get("evidence") or "{}").get("model") or "?"
            except (json.JSONDecodeError, AttributeError): model = "?"
            cost_by_model[model] += float(log.get("cost_usd") or 0.0)
        reviews = [e.payload for e in self.bus.replay(topic="review-results")]
        caught = sum(1 for r in reviews if r.get("verdict") != "pass")
        prs = sum(1 for _ in self.bus.replay(topic="pull-requests"))
        unverified = sum(1 for e in self.bus.replay(topic="pull-requests")
                         if (e.payload.get("local_checks") or {}).get("verified_by") != "workspace")
        return {"tickets": tickets, "actions": dict(actions), "lessons": len(self.knowledge),
                "rework_rate": round(sum(1 for r in tickets.values() if r["retry"]) / len(tickets), 2) if tickets else None,
                "review_catch_rate": round(caught / len(reviews), 2) if reviews else None,
                "prs": prs, "prs_unverified": unverified, "calibration": self.calibration(),
                "cost_usd_total": round(sum(cost_by_agent.values()), 4),
                "cost_by_agent": {k: round(v, 4) for k, v in sorted(cost_by_agent.items())},
                "cost_by_model": {k: round(v, 4) for k, v in sorted(cost_by_model.items())},
                "project_cost_usd": {k: round(v, 4) for k, v in sorted(self.project_cost.items())},
                "project_budget_usd": self.project_budget_usd, "unpriced_calls": self.unpriced}
