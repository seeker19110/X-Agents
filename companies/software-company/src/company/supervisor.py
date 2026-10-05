from __future__ import annotations

import copy
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from xagents_core.supervisor import DEBT_HINT as DEBT_HINT
from xagents_core.supervisor import DEBT_RE as DEBT_RE
from xagents_core.supervisor import Budget as Budget
from xagents_core.supervisor import SupervisorBase
from xagents_core.supervisor import debt_ids as debt_ids
from xagents_core.ticket_model import Budgeted

from .bus import InMemoryBus
from .events import NAMESPACE_OWNERS, AuditLog, Envelope, SupervisorAction, Task
from .guard import scan
from .roles import ROLE

# F16: token của 3 lượt review (mỗi lượt mang system prompt + blackboard) không tính vào ngân sách ticket — delivery-lead
# ước lượng công của engineer, còn review là chi phí cố định của quy trình; cộng chung thì mọi ticket đều bị cắt.
REVIEW_ACTORS = frozenset({ROLE.QA, ROLE.SECURITY})
#: Lý do escalate của `check_timeouts` — `replay` nhận ra nó để dựng lại mốc chống lặp `last_seen`.
IDLE_REASON = "không hoạt động >"

# `Budget`, `DEBT_RE`, `DEBT_HINT`, `debt_ids` và cơ chế đếm nợ (`_count_debt`/`debt_table`) ở
# `xagents_core.supervisor` từ K3.7; re-export giữ nguyên chỗ nhập của mọi nơi gọi và của test.


class Supervisor(SupervisorBase):
    """Watchdog + cost controller + knowledge base. Subscribe mọi topic.

    Ngân sách đo hai đơn vị (ADR-0012): token (như trước) và USD từ `audit-log.cost_usd` — token của model mạnh và model
    rẻ khác giá nhiều lần, chỉ đếm token thì không biết đang đốt bao nhiêu tiền. Trần theo ticket (`Task.budget_usd`)
    và theo dự án (`project_budget_usd`, từ llm.yaml `budget_usd`): chạm 80% → warn, chạm 100% → budget_cut ticket /
    pause dự án. Lời gọi không có giá (`unpriced`) được đếm riêng để không ai tưởng là miễn phí."""
    def __init__(self, bus: InMemoryBus, max_retries: int = 3, ticket_timeout: timedelta = timedelta(hours=4),
                 project_budget_usd: float | None = None, debt_threshold: int = 3):
        super().__init__(debt_threshold=debt_threshold)
        self.bus, self.max_retries, self.ticket_timeout = bus, max_retries, ticket_timeout
        self.project_budget_usd = project_budget_usd
        # ADR-0032 (`debt`, `debt_due`, `ticket_project`, `debt_threshold`) ở `SupervisorBase`: mọi thứ ấy là
        # hàm thuần của bus (đếm lại khi replay) — không có gì chỉ sống trong RAM (khuôn 2, TRAPS.md).
        self.budgets: dict[str, Budget] = {}
        self.project_cost: dict[str, float] = defaultdict(float)
        self.project_warned: set[str] = set(); self.project_paused: set[str] = set()
        self.project_granted: dict[str, float] = defaultdict(float)  # mốc chi phí lúc người cho chạy tiếp
        self.ticket_warned: set[str] = set(); self.ticket_cut: set[str] = set()  # mỗi ticket một lần, tới khi cấp thêm
        self.unpriced = 0
        self.unpriced_warned: set[str] = set()   # mỗi (dự án | ticket) báo một lần, xem `_check_unpriced`
        self.last_seen: dict[str, datetime] = {}
        self.error_signatures: dict[str, list[str]] = defaultdict(list)
        self.actions: list[SupervisorAction] = []
        self.knowledge: list[dict] = []
        self._report_cache: tuple[tuple[int, int, int], dict] | None = None  # (len(bus), số action, số bài học) → báo cáo
        self.replaying = False  # dựng lại từ log: cộng dồn ngân sách/chữ ký lỗi nhưng không phát lại supervisor-actions
        bus.subscribe("*", self._on)

    def _budget(self, item: Budgeted, limit_usd: float | None = None) -> Budget:
        """Sổ ngân sách của một đơn vị công việc có trần token. `Budgeted` là Protocol CẤU TRÚC
        (`xagents_core.ticket_model`): `Task` không kế thừa gì, nó chỉ có `budget_tokens` — cùng lý do
        `VideoBrief` của studio đi vừa chữ ký này mà không phải mang `project_id` của company."""
        return Budget(item.budget_tokens, limit_usd=limit_usd)

    def _act(self, target: str, action: str, reason: str, evidence: str | None = None) -> None:
        a = SupervisorAction(target=target, action=action, reason=reason, evidence=evidence)  # type: ignore[arg-type]
        self.actions.append(a)
        if not self.replaying:
            self.bus.publish(Envelope(topic="supervisor-actions", key=target, actor=ROLE.SUPERVISOR, payload=a.model_dump()))

    def replay(self, env: Envelope) -> None:
        # Hành động của chính supervisor phải được DỰNG LẠI, không được bỏ qua. `_on` mở đầu bằng
        # `if env.actor == ROLE.SUPERVISOR: return` — đúng cho đường chạy sống (không tự phản ứng với hành động của
        # mình, tránh vòng lặp), nhưng khi replay thì nó nuốt luôn `self.actions`.
        #
        # Hệ quả dây chuyền, đo được khi chạy thật (2026-09-04): bus có 5 event escalate/budget_cut cho
        # QLKH-001 nhưng sau restart đếm được 0. `_check_escalations` tạo gate theo điều kiện
        # `state == "blocked" or n`; ticket đang `paused` ở trạng thái `in_review` với n=0 nên KHÔNG có gate nào
        # được mở — không ai gỡ được pause, dự án đứng im 6 phút mà `stalled` và `gates_pending` đều rỗng.
        if env.topic == "supervisor-actions" and env.actor == ROLE.SUPERVISOR:
            a = SupervisorAction.model_validate(env.payload); self.actions.append(a)
            # `check_timeouts` chống lặp bằng `last_seen[key] = now`: dựng lại đúng mốc đó, không thì mỗi lần mở lại
            # bus cùng một sự im lặng bị escalate thêm một lần (nhật ký 2026-10-02).
            if a.action == "escalate" and a.reason.startswith(IDLE_REASON): self.last_seen[a.target] = env.ts
            return
        prev, self.replaying = self.replaying, True
        try:
            self._on(env)
        finally:
            self.replaying = prev

    def _on(self, env: Envelope) -> None:
        if env.actor == ROLE.SUPERVISOR:
            return
        self.last_seen[env.key] = env.ts
        if env.topic == "supervisor-actions" and env.payload.get("action") == "resume":
            # Người cho chạy tiếp một dự án đã chạm trần: coi như CẤP THÊM một ngân sách dự án nữa, đối xứng với
            # `budget.extended` của ticket. Không thể chỉ xoá `project_paused`: chi phí chỉ tăng nên tỉ lệ vẫn
            # ≥ CUT_AT, và pause sẽ bật lại ngay lập tức thành vòng pause/resume vô tận.
            #
            # Trước đây `project_paused` không bao giờ được gỡ, nên sau lần resume đầu dự án KHÔNG BAO GIỜ bị
            # pause lần nữa — đo được: chi phí 99 → 9999 (gấp 100 lần trần) mà supervisor chỉ sinh đúng một
            # `pause` của lần đầu. Trần ngân sách dự án chỉ có tác dụng đúng một lần trong cả vòng đời.
            pid = env.key
            if pid in self.project_paused and self.project_budget_usd:
                self.project_granted[pid] = self.project_cost[pid]
                self.project_paused.discard(pid); self.project_warned.discard(pid)
        elif env.topic == "tasks":
            # `_on` chạy cho cả event mới lẫn `replay()` lúc rehydrate — dùng đường khoan dung.
            t = Task.tu_log(env.payload)
            self.ticket_project[t.ticket_id] = t.project_id
            self.budgets.setdefault(t.ticket_id, self._budget(t, t.budget_usd))
            if t.retry >= self.max_retries:
                self._act(t.ticket_id, "escalate", f"retry {t.retry} ≥ {self.max_retries}")
        elif env.topic == "audit-log":
            a = AuditLog.model_validate(env.payload)
            if a.action.startswith("produced:") and '"unpriced": true' in (a.evidence or ""):
                self.unpriced += 1
                self._check_unpriced(a)
            if a.ticket_id and a.action == "budget.extended":  # người cấp thêm ngân sách: ngưỡng được báo lại từ đầu
                self.ticket_warned.discard(a.ticket_id); self.ticket_cut.discard(a.ticket_id)
            if a.ticket_id and a.ticket_id in self.budgets:
                b = self.budgets[a.ticket_id]; b.cost_usd += a.cost_usd
                if a.actor in REVIEW_ACTORS: b.review_used += a.tokens
                else: b.used += a.tokens; b.output_used += a.output_tokens
                self._check_ticket(a.ticket_id, b)
            if a.project_id and a.cost_usd:
                self.project_cost[a.project_id] += a.cost_usd
                self._check_project(a.project_id)
        elif env.topic == "review-results":
            self._count_debt(env)
            if env.payload.get("verdict") in {"fail", "block"}:
                sig = env.payload.get("root_cause") or " | ".join(f["text"] for f in env.payload.get("findings", []))
                sigs = self.error_signatures[env.key]; sigs.append(sig)
                if sigs.count(sig) >= 2:
                    self._act(env.key, "escalate", "cùng lỗi lặp ≥ 2 lần", evidence=sig)
        elif env.topic == "shared-context":
            if env.actor not in NAMESPACE_OWNERS.get(env.payload["namespace"], set()):
                self._act(env.actor, "pause", "ghi sai namespace")

    def _check_ticket(self, tid: str, b: Budget) -> None:
        """Chạm 100% → budget_cut, 80% → warn; mỗi ngưỡng chỉ báo một lần cho tới khi `budget.extended` (như dự án):
        sau ngưỡng mọi audit của ticket (kể cả 0 token) đều lặp lại hành động thì gate escalation mở đi mở lại."""
        if tid not in self.ticket_cut and b.ratio >= self.CUT_AT:
            self.ticket_cut.add(tid); self._act(tid, "budget_cut", f"đầu ra {b.output_used}/{b.limit} token (tổng kể cả input: {b.used})")
        elif tid not in self.ticket_cut and b.limit_usd and b.ratio_usd >= self.CUT_AT:
            self.ticket_cut.add(tid); self._act(tid, "budget_cut", f"dùng {b.cost_usd:.2f}/{b.limit_usd:.2f} USD")
        elif tid not in self.ticket_warned and b.ratio >= self.WARN_AT:
            self.ticket_warned.add(tid); self._act(tid, "warn", f"đã dùng {b.ratio:.0%} ngân sách token")
        elif tid not in self.ticket_warned and b.limit_usd and b.ratio_usd >= self.WARN_AT:
            self.ticket_warned.add(tid); self._act(tid, "warn", f"đã dùng {b.ratio_usd:.0%} ngân sách tiền ({b.cost_usd:.2f} USD)")

    def _check_unpriced(self, a: AuditLog) -> None:
        """Trần TIỀN được đặt nhưng lời gọi không có giá → nói ra, đúng một lần cho mỗi đơn vị.

        `Pricing` trả `cost_usd = 0.0` khi tên model không khớp bảng `prices` trong `llm.yaml`, và đánh dấu
        `unpriced` để "không ai tưởng là miễn phí". Nhưng trước 2026-09-09 dấu ấy chỉ được ĐẾM
        (`self.unpriced`) rồi in trong báo cáo — không có hành động nào. Nghĩa là ai đặt `budget_usd` hoặc
        `project_budget_usd` mà đi một backend không có giá thì `_check_ticket`/`_check_project` cộng dồn
        `0.0` mãi mãi: trần không bao giờ chạm, `budget_cut` và `pause` không bao giờ nổ. Guardrail ngân sách
        tiền thành no-op **im lặng** — đúng khuôn "chế độ hỏng không tự khai báo".

        Đo trên dữ liệu chạy thật (QLKH, 2026-09-09): 137 318 818 token, tổng chi phí ghi nhận **0,0000 USD**.

        Chỉ báo khi CÓ trần tiền: không đặt trần thì `unpriced` chỉ là thông tin, không phải chế độ hỏng."""
        tid = a.ticket_id
        if tid and (b := self.budgets.get(tid)) is not None and b.limit_usd and tid not in self.unpriced_warned:
            self.unpriced_warned.add(tid)
            self._act(tid, "escalate", f"trần {b.limit_usd:.2f} USD không đo được: model không có giá trong "
                                       "`prices` của llm.yaml nên mọi lời gọi tính 0 USD")
        pid = a.project_id
        if pid and self.project_budget_usd and pid not in self.unpriced_warned:
            self.unpriced_warned.add(pid)
            self._act(pid, "escalate", f"trần dự án {self.project_budget_usd:.2f} USD không đo được: model "
                                       "không có giá trong `prices` của llm.yaml nên mọi lời gọi tính 0 USD")

    def _check_project(self, pid: str) -> None:
        if not self.project_budget_usd: return
        # Trần đo từ mốc lần cấp thêm gần nhất: mỗi lần người resume là thêm đúng một `project_budget_usd` nữa.
        cost = self.project_cost[pid] - self.project_granted[pid]; ratio = cost / self.project_budget_usd
        if ratio >= self.CUT_AT and pid not in self.project_paused:
            self.project_paused.add(pid)
            self._act(pid, "pause", f"dự án dùng {cost:.2f}/{self.project_budget_usd:.2f} USD — cần người cấp thêm rồi resume")
        elif ratio >= self.WARN_AT and pid not in self.project_warned:
            self.project_warned.add(pid)
            self._act(pid, "warn", f"dự án đã dùng {ratio:.0%} ngân sách tiền ({cost:.2f} USD)")

    def check_timeouts(self, now: datetime | None = None, active: set[str] | None = None) -> list[str]:
        """Escalate key im lặng quá ticket_timeout. `active` (ticket đang chạy, từ delivery-lead) giới hạn phạm vi
        để không escalate ticket đã đóng; mỗi key chỉ escalate một lần cho tới khi có event mới."""
        now = now or datetime.now(UTC); stuck = []
        for key, ts in self.last_seen.items():
            if active is not None and key not in active: continue
            if now - ts > self.ticket_timeout:
                stuck.append(key); self.last_seen[key] = now
                self._act(key, "escalate", f"{IDLE_REASON} {self.ticket_timeout}")
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
        tổng hành động — cho retrospective. Kết quả được cache theo (số event trên bus, số action, số bài học): `status`
        gọi hàm này mỗi nhịp và trên bus SQLite mỗi lần là replay + parse lại cả log; bus không đổi thì báo cáo không đổi."""
        stamp = (len(self.bus), len(self.actions), len(self.knowledge))
        if self._report_cache is not None and self._report_cache[0] == stamp:
            return copy.deepcopy(self._report_cache[1])
        report = self._sprint_report()
        self._report_cache = (stamp, copy.deepcopy(report))
        return report

    def _sprint_report(self) -> dict:
        tickets: dict[str, dict[str, Any]] = {}
        for env in self.bus.replay(topic="tasks"):
            t = Task.tu_log(env.payload); b = self.budgets.get(t.ticket_id)   # duyệt lại CẢ lịch sử `tasks`
            tickets[t.ticket_id] = {"estimate_tokens": t.estimate_tokens, "budget_tokens": t.budget_tokens,
                                    "retry": t.retry, "actual_tokens": b.used if b else 0,
                                    "output_tokens": b.output_used if b else 0,
                                    "review_tokens": b.review_used if b else 0,
                                    "budget_usd": t.budget_usd, "cost_usd": round(b.cost_usd, 4) if b else 0.0}
        for row in tickets.values():
            row["ratio"] = round(row["output_tokens"] / row["budget_tokens"], 2) if row["budget_tokens"] else None
        actions: defaultdict[str, int] = defaultdict(int)
        for act in self.actions: actions[act.action] += 1
        cost_by_agent: dict[str, float] = defaultdict(float); cost_by_model: dict[str, float] = defaultdict(float)
        for e in self.bus.replay(topic="audit-log"):
            log = e.payload
            if not log.get("cost_usd"): continue
            cost_by_agent[log["actor"]] += float(log.get("cost_usd") or 0.0)
            try: model = json.loads(log.get("evidence") or "{}").get("model") or "?"
            except (json.JSONDecodeError, AttributeError): model = "?"
            cost_by_model[model] += float(log.get("cost_usd") or 0.0)
        reviews = [e.payload for e in self.bus.replay(topic="review-results")]
        caught = sum(1 for r in reviews if r.get("verdict") != "pass")
        prs = sum(1 for _ in self.bus.replay(topic="pull-requests"))
        unverified = sum(1 for e in self.bus.replay(topic="pull-requests")
                         if (e.payload.get("local_checks") or {}).get("verified_by") != "workspace")
        # Đếm bài học từ BLACKBOARD, không từ `self.knowledge`: danh sách trong RAM không được dựng lại khi mở
        # lại bus, nên sau restart báo cáo hiện `lessons: 0` dù bài học vẫn còn nguyên trên blackboard — người
        # đọc sẽ tưởng vòng học không chạy. `lessons()` đọc thẳng nguồn bền vững.
        return {"tickets": tickets, "actions": dict(actions), "lessons": len(self.lessons()),
                "rework_rate": round(sum(1 for r in tickets.values() if r["retry"]) / len(tickets), 2) if tickets else None,
                "review_catch_rate": round(caught / len(reviews), 2) if reviews else None,
                "prs": prs, "prs_unverified": unverified, "calibration": self.calibration(),
                "cost_usd_total": round(sum(cost_by_agent.values()), 4),
                "cost_by_agent": {k: round(v, 4) for k, v in sorted(cost_by_agent.items())},
                "cost_by_model": {k: round(v, 4) for k, v in sorted(cost_by_model.items())},
                "project_cost_usd": {k: round(v, 4) for k, v in sorted(self.project_cost.items())},
                "project_budget_usd": self.project_budget_usd, "unpriced_calls": self.unpriced,
                "architecture_debt": self.debt_table()}  # ADR-0032: nợ treo phải có mặt trong báo cáo, không chỉ trong gate
