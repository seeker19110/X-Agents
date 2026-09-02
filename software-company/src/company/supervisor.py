from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .bus import InMemoryBus
from .events import NAMESPACE_OWNERS, AuditLog, Envelope, SupervisorAction, Task


@dataclass
class Budget:
    limit: int
    used: int = 0
    @property
    def ratio(self) -> float: return self.used / self.limit if self.limit else 0.0

class Supervisor:
    """Watchdog + cost controller + knowledge base. Subscribe mọi topic."""
    WARN_AT, CUT_AT = 0.8, 1.0

    def __init__(self, bus: InMemoryBus, max_retries: int = 3, ticket_timeout: timedelta = timedelta(hours=4),
                 project_budget_tokens: int | None = None):
        self.bus, self.max_retries, self.ticket_timeout = bus, max_retries, ticket_timeout
        # Hạn mức cả dự án: ngân sách theo ticket không chặn được trường hợp nhiều ticket cùng đốt token.
        self.project_budget_tokens = project_budget_tokens
        self.budgets: dict[str, Budget] = {}
        self.project_budgets: dict[str, Budget] = {}
        self.last_seen: dict[str, datetime] = {}
        self.error_signatures: dict[str, list[str]] = defaultdict(list)
        self.actions: list[SupervisorAction] = []
        self.knowledge: list[dict] = []
        self._escalated_once: set[str] = set()
        self.project_of: dict[str, str] = {}  # ticket → dự án, để quy token của ticket về đúng ngân sách dự án
        self.replaying = False  # dựng lại từ log: cộng dồn ngân sách/chữ ký lỗi nhưng không phát lại supervisor-actions
        bus.subscribe("*", self._on)

    def _act(self, target: str, action: str, reason: str, evidence: str | None = None) -> None:
        a = SupervisorAction(target=target, action=action, reason=reason, evidence=evidence)
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
            self.budgets.setdefault(t.ticket_id, Budget(t.budget_tokens))
            self.project_of[t.ticket_id] = t.project_id
            if t.retry >= self.max_retries:
                self._act(t.ticket_id, "escalate", f"retry {t.retry} ≥ {self.max_retries}")
        elif env.topic == "audit-log":
            a = AuditLog.model_validate(env.payload)
            if a.ticket_id and a.ticket_id in self.budgets:
                b = self.budgets[a.ticket_id]; b.used += a.tokens
                if b.ratio >= self.CUT_AT: self._act(a.ticket_id, "budget_cut", f"dùng {b.used}/{b.limit} token")
                elif b.ratio >= self.WARN_AT: self._act(a.ticket_id, "warn", f"đã dùng {b.ratio:.0%} ngân sách")
            self._charge_project(a.project_id or self.project_of.get(a.ticket_id or ""), a.tokens)
        elif env.topic == "review-results" and env.payload.get("verdict") in {"fail", "block"}:
            sig = env.payload.get("root_cause") or " | ".join(f["text"] for f in env.payload.get("findings", []))
            sigs = self.error_signatures[env.key]; sigs.append(sig)
            if sigs.count(sig) >= 2:
                self._act(env.key, "escalate", "cùng lỗi lặp ≥ 2 lần", evidence=sig)
        elif env.topic == "shared-context":
            if env.actor not in NAMESPACE_OWNERS.get(env.payload["namespace"], set()):
                self._act(env.actor, "pause", "ghi sai namespace")

    def escalate_gate(self, subject_id: str, reason: str, once_key: str | None = None) -> None:
        """Gate quá hạn: người duyệt im lặng cũng là một dạng bế tắc, phải hiện ra như mọi bế tắc khác."""
        key = once_key or f"gate:{subject_id}"
        if key in self._escalated_once: return
        self._escalated_once.add(key)
        self._act(subject_id, "escalate", reason)

    def _charge_project(self, project_id: str | None, tokens: int) -> None:
        """Cộng dồn token theo dự án. Vượt hạn mức dự án thì cắt cả dự án, không chỉ một ticket:
        mười ticket mỗi cái trong ngân sách vẫn có thể đốt hết tiền của khách."""
        if not project_id or not self.project_budget_tokens or not tokens: return
        b = self.project_budgets.setdefault(project_id, Budget(self.project_budget_tokens))
        b.used += tokens
        if b.ratio >= self.CUT_AT: self._act(project_id, "budget_cut", f"dự án dùng {b.used}/{b.limit} token")
        elif b.ratio >= self.WARN_AT and f"project.warn:{project_id}" not in self._escalated_once:
            self._escalated_once.add(f"project.warn:{project_id}")
            self._act(project_id, "warn", f"dự án đã dùng {b.ratio:.0%} ngân sách")

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
        needles = ("ignore previous instructions", "ignore all prior", "you are now", "system prompt:", "bỏ qua hướng dẫn trước")
        return any(n in text.lower() for n in needles)

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
        """Estimate vs actual token mỗi ticket, tỷ lệ làm lại, tỷ lệ review bắt lỗi, tổng hành động — cho retrospective."""
        tickets = {}
        for env in self.bus.replay(topic="tasks"):
            t = Task.model_validate(env.payload)
            tickets[t.ticket_id] = {"estimate_tokens": t.estimate_tokens, "budget_tokens": t.budget_tokens,
                                    "retry": t.retry, "actual_tokens": self.budgets[t.ticket_id].used if t.ticket_id in self.budgets else 0}
        for row in tickets.values():
            est = row["estimate_tokens"]
            row["ratio"] = round(row["actual_tokens"] / est, 2) if est else None
        actions = defaultdict(int)
        for a in self.actions: actions[a.action] += 1
        reviews = [e.payload for e in self.bus.replay(topic="review-results")]
        caught = sum(1 for r in reviews if r.get("verdict") != "pass")
        prs = sum(1 for _ in self.bus.replay(topic="pull-requests"))
        unverified = sum(1 for e in self.bus.replay(topic="pull-requests")
                         if (e.payload.get("local_checks") or {}).get("verified_by") != "workspace")
        return {"tickets": tickets, "actions": dict(actions), "lessons": len(self.knowledge),
                "projects": {p: {"used": b.used, "limit": b.limit} for p, b in sorted(self.project_budgets.items())},
                "rework_rate": round(sum(1 for r in tickets.values() if r["retry"]) / len(tickets), 2) if tickets else None,
                "review_catch_rate": round(caught / len(reviews), 2) if reviews else None,
                "prs": prs, "prs_unverified": unverified, "calibration": self.calibration()}
