from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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

    def __init__(self, bus: InMemoryBus, max_retries: int = 3, ticket_timeout: timedelta = timedelta(hours=4)):
        self.bus, self.max_retries, self.ticket_timeout = bus, max_retries, ticket_timeout
        self.budgets: dict[str, Budget] = {}
        self.last_seen: dict[str, datetime] = {}
        self.error_signatures: dict[str, list[str]] = defaultdict(list)
        self.actions: list[SupervisorAction] = []
        self.knowledge: list[dict] = []
        bus.subscribe("*", self._on)

    def _act(self, target: str, action: str, reason: str, evidence: str | None = None) -> None:
        a = SupervisorAction(target=target, action=action, reason=reason, evidence=evidence)
        self.actions.append(a)
        self.bus.publish(Envelope(topic="supervisor-actions", key=target, actor="supervisor", payload=a.model_dump()))

    def _on(self, env: Envelope) -> None:
        if env.actor == "supervisor":
            return
        self.last_seen[env.key] = env.ts
        if env.topic == "tasks":
            t = Task.model_validate(env.payload)
            self.budgets.setdefault(t.ticket_id, Budget(t.budget_tokens))
            if t.retry >= self.max_retries:
                self._act(t.ticket_id, "escalate", f"retry {t.retry} ≥ {self.max_retries}")
        elif env.topic == "audit-log":
            a = AuditLog.model_validate(env.payload)
            if a.ticket_id and a.ticket_id in self.budgets:
                b = self.budgets[a.ticket_id]; b.used += a.tokens
                if b.ratio >= self.CUT_AT: self._act(a.ticket_id, "budget_cut", f"dùng {b.used}/{b.limit} token")
                elif b.ratio >= self.WARN_AT: self._act(a.ticket_id, "warn", f"đã dùng {b.ratio:.0%} ngân sách")
        elif env.topic == "review-results" and env.payload.get("verdict") in {"fail", "block"}:
            sig = env.payload.get("root_cause") or " | ".join(f["text"] for f in env.payload.get("findings", []))
            sigs = self.error_signatures[env.key]; sigs.append(sig)
            if sigs.count(sig) >= 2:
                self._act(env.key, "escalate", "cùng lỗi lặp ≥ 2 lần", evidence=sig)
        elif env.topic == "shared-context":
            if env.actor not in NAMESPACE_OWNERS.get(env.payload["namespace"], set()):
                self._act(env.actor, "pause", "ghi sai namespace")

    def check_timeouts(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc); stuck = []
        for key, ts in self.last_seen.items():
            if now - ts > self.ticket_timeout:
                stuck.append(key); self._act(key, "escalate", f"không hoạt động > {self.ticket_timeout}")
        return stuck

    def detect_injection(self, text: str) -> bool:
        needles = ("ignore previous instructions", "ignore all prior", "you are now", "system prompt:", "bỏ qua hướng dẫn trước")
        return any(n in text.lower() for n in needles)

    def record_lesson(self, context: str, problem: str, solution: str, evidence: str) -> None:
        self.knowledge.append({"context": context, "problem": problem, "solution": solution, "evidence": evidence})
