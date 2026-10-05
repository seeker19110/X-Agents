"""Đọc trạng thái software-company + keeper + gateway thành MỘT dict thuần cho trang console.

Nguyên tắc:

- **Chỉ đọc.** SQLite mở bằng URI `mode=ro`: không tạo file, không chạy DDL, không đổi journal mode. Vì vậy không dùng
  `SQLiteBus` ở đây (constructor của nó `CREATE TABLE` + `PRAGMA journal_mode=WAL` — ghi vào DB của công ty đang chạy).
  Envelope đọc lên được nạp thẳng vào `InMemoryBus` thật của công ty rồi replay qua chính DeliveryLead / Supervisor /
  PersistentGate của họ — trạng thái ticket/gate suy ra đúng như orchestrator, không chép lại máy trạng thái ở đây.
- **Không bao giờ ném.** DB thiếu hoặc hỏng là trạng thái bình thường (chưa chạy công ty đó bao giờ): `sources[...]`
  mang `ok=false` + lý do tiếng Việt, phần dữ liệu của xưởng đó rỗng.
- Ngưỡng `sev` của gate lấy từ `HumanGate.timeout` / `HumanGate.remind_at` của chính công ty, không viết số ở đây.

Hợp đồng cấu trúc trả về: `console/API.md`.
"""
from __future__ import annotations

import json
import math
import shutil
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
from company.delivery import DONE_STATES, DeliveryLead
from company.events import Envelope as CompanyEnvelope
from company.events import Task
from company.orch.guards import pending_clarifications
from company.registry import load_agents as load_company_agents
from company.supervisor import Supervisor as CompanySupervisor
from keeper.budget import WINDOW_DAYS as KEEPER_WINDOW_DAYS
from keeper.budget import max_pr_per_week
from keeper.bus import KeeperMemoryBus
from keeper.core import CORE as KEEPER_CORE
from keeper.events import DebtEntry
from keeper.events import Envelope as KeeperEnvelope
from keeper.events import ReleaseNote as KeeperNote
from keeper.events import Ticket as KeeperTicket
from keeper.gates import PersistentGate as KeeperGate
from keeper.ledger import Ledger

from console.git_truth import INTEGRATION_BRANCH, ahead_count
from console.quality import contracts as quality_contracts
from console.truth import Truth, gate_effect, gate_next_agent, gate_reject_effect

_LOOPS_EMPTY = {"turns_p50": None, "turns_p90": None, "turns_max": None, "capped_ratio": None,
                "no_progress_ratio": None, "retry_max_ratio": None, "n": 0, "empty": True}

COMPANY = "software-company"
KEEPER = "keeper"
#: Chữ thay cho MỌI con số của tab `keeper` khi công ty bảo trì chưa chạy lần nào (BT8, `DAC-TA-KEEPER.md` §10).
#: Một số 0 màu xanh và một hệ thống chưa từng chạy nhìn giống hệt nhau — nên khi chưa chạy thì không có số nào,
#: kể cả "0 ticket quá hạn". Đo từ đêm vận hành QLKH 05/09 (`console/TRAPS.md`).
KEEPER_EMPTY_NOTE = "chưa chạy lần nào"
#: Bốn ô của tab `keeper`, THỨ TỰ CỐ ĐỊNH: nhãn + ghi chú khi chưa chạy. Khoá đi riêng ở `KEEPER_KEYS` để bản
#: "đã chạy" và bản "chưa chạy" không thể lệch số ô — lệch là một ô im lặng biến mất.
KEEPER_KEYS = ("queue", "budget", "overdue", "gates")
KEEPER_CARDS = (("Hàng đợi ticket", KEEPER_EMPTY_NOTE), ("Ngân sách còn lại", KEEPER_EMPTY_NOTE),
                ("Nợ quá hạn", KEEPER_EMPTY_NOTE), ("Gate đang chờ", KEEPER_EMPTY_NOTE))
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
        except NotImplementedError:
            raise  # lớp con thiếu _read/_replay là lỗi lập trình, không phải nguồn hỏng
        except Exception as e:
            # Một event sai schema (KeyError, pydantic ValidationError...) trong replay: chỉ nguồn NÀY hỏng —
            # thoát ra ngoài thì `collect()` ném, `/api/state` 500 và hàng gate của xưởng kia mất theo.
            self.envelopes, self.gate = [], None
            self.error = f"replay hỏng ({type(e).__name__}): {str(e)[:NOTE_WIDTH]}"

    def _read(self) -> list[Any]:
        raise NotImplementedError

    def _replay(self) -> None:
        raise NotImplementedError

    @property
    def source(self) -> dict[str, Any]:
        return {"ok": self.ok, "db": str(self.db) if (self.db and self.ok) else None,
                "events": len(self.envelopes), "error": self.error,
                "sandbox_available": _co_container_runtime()}

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
                        "effect": self.gate_effect(r), "reject": self.gate_reject(r), "agent": self.gate_agent(r),
                        "title": self.gate_title(r), "facts": self.gate_facts(r),
                        "cl": [[item, self.checklist_note(r, item)] for item in r.checklist],
                        "decidable": True})
        out.sort(key=lambda g: -g["hours"])
        return out

    def gate_title(self, r: Any) -> str:
        return f"{r.kind} · {r.subject_id}"

    def gate_effect(self, r: Any) -> str:
        """Hậu quả của việc duyệt — mỗi xưởng tự nói; mặc định không nói gì còn hơn nói sai."""
        return ""

    def gate_reject(self, r: Any) -> str:
        """Hậu quả của việc TỪ CHỐI (C2) — nửa còn thiếu; không biết thì im, không đoán."""
        return ""

    def gate_agent(self, r: Any) -> str:
        """Duyệt xong thì AI chạy lại (C2)."""
        return ""

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
        """(ts, dòng log) — ts để gộp theo đúng thứ tự thời gian, không phải theo chuỗi giờ:phút."""
        rows: list[tuple[datetime, dict[str, Any]]] = []
        for e in reversed(self.audits()):
            p = e.payload
            if not str(p.get("action", "")).startswith("produced:"): continue
            rows.append((e.ts, {"t": e.ts.astimezone().strftime("%H:%M"), "a": p.get("actor", "?"),
                                "ac": p.get("action", ""), "k": p.get("ticket_id") or e.key,
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
                t = Task.tu_log(env.payload)
                if t.ticket_id not in self.lead.tickets:
                    self.lead.tickets[t.ticket_id] = t
                    self.lead.state[t.ticket_id] = "dispatched"
            elif env.topic == "audit-log":
                # `DeliveryLead.replay()` không có handler cho topic `audit-log` (xem `DeliveryLead.handlers`), nên
                # ba hành động dưới đây — chỉ sống trong RAM của orchestrator lúc chạy thật, được `orch/rehydrate.py`
                # dựng lại từ audit-log khi mở lại tiến trình — chưa từng được áp lại ở đây. Hậu quả đo được
                # 2026-09-10: TCK-CR-STAGE-001-02 blocked → escalation approve → `mark_done_already_integrated` đưa
                # thẳng về `merged` (đúng, orchestrator báo đúng) nhưng console vẫn coi là `blocked` mãi mãi vì state
                # đó chỉ tồn tại trong RAM của orchestrator, không tự "xảy ra lại" khi console replay từ đầu — sinh
                # cảnh báo "bế tắc im lặng" giả cho một ticket đã xong từ nhiều ngày trước.
                a, d = env.payload, _evidence(env.payload)
                if a.get("action") == "ticket.blocked" and d.get("ticket_id"):
                    self.lead.state[str(d["ticket_id"])] = "blocked"
                elif a.get("action") == "ticket.already_integrated" and d.get("state"):
                    self.lead.state[str(d["ticket_id"])] = str(d["state"])
                elif a.get("action") == "integration.merged" and d.get("ticket_id"):
                    prev_r, self.lead.replaying = self.lead.replaying, True
                    try: self.lead.mark_integrated(str(d["ticket_id"]))
                    finally: self.lead.replaying = prev_r
            self.lead.replay(env)
            self.sup.replay(env)
        self.report = self.sup.sprint_report()
        self.metrics = company_metrics.collect(self.bus)
        self.truth = Truth(self.envelopes, self.lead, self.gate, datetime.now(UTC))
        # C7: đường dẫn repo và tên nhánh tích hợp đến TỪ BUS (audit `project.repo` / `integration.merged`), không
        # từ cấu hình riêng của console — console không giữ nguồn sự thật nào của riêng nó (C10).
        self.repos: dict[str, Path] = {}
        self.integration_branch = INTEGRATION_BRANCH
        for e in self.audits():
            p, d = e.payload, _evidence(e.payload)
            if p.get("action") == "project.repo" and d.get("repo"):
                self.repos[str(d.get("project_id") or "")] = Path(str(d["repo"]))
            elif p.get("action") == "integration.merged" and d.get("branch"):
                self.integration_branch = str(d["branch"])

    def tiers(self) -> dict[str, str]:
        try:
            return {a: spec.model_tier for a, spec in load_company_agents(check_owners=False).items()}
        except Exception:
            return {}

    def gates(self, now: datetime) -> list[dict[str, Any]]:
        """Gate thật + câu hỏi làm rõ đang chờ người (`kind=clarification`, `decidable=False`). Đo 2026-09-22
        (CAMPUS-UNI): `product` hỏi vòng 1, không ai trả lời, hàng đợi in "Sạch hàng đợi" — người trực không có
        chỗ nào để biết dự án đang đứng im chờ mình. Câu hỏi đi CHUNG hàng đợi vì đây là chỗ duy nhất người trực
        nhìn; nó không phải `HumanGate` nên không duyệt được, chỉ trỏ tới form trả lời."""
        out = super().gates(now)
        if not self.ok or self.bus is None: return out
        signed = self.gate.reviewer_signed_pending()
        for row in out:
            if row["id"] in signed:
                row["reviewer_signed"] = signed[row["id"]]
                row["title"] = f"Đã ký bởi {signed[row['id']]['by']} (cờ tắt, chưa áp) · {row['title']}"
                row["sev"] = "signed"
                row["decidable"] = False
        over_h = self.gate.timeout.total_seconds() / 3600
        warn_h = self.gate.remind_at.total_seconds() / 3600
        for pid, c in sorted(pending_clarifications(self.bus).items()):
            h = _hours(datetime.fromisoformat(c["since"]), now)
            sev = "over" if h >= over_h else ("warn" if h >= warn_h else "calm")
            out.append({"id": f"CLARIFY-{pid}", "xuong": self.name, "kind": "clarification", "by": c["asked_by"],
                        "trigger": "", "hours": h, "sev": sev,
                        "effect": f"Trả lời ở màn Giao việc → «Trả lời câu hỏi làm rõ» (topic clarification-answers, "
                                  f"project_id={pid}, theo question_id). Dự án đứng im tới khi trả lời đủ "
                                  f"{len(c['unanswered'])} câu; sau đó product viết PRD.",
                        "reject": "", "agent": "product",
                        "title": f"câu hỏi làm rõ · {pid} · vòng {c['round']}",
                        "facts": [["project_id", pid], ["round", str(c["round"])], ["asked_by", c["asked_by"]],
                                  ["since", c["since"]], ["unanswered", ", ".join(c["unanswered"])]],
                        "cl": [[f"{q['id']}: {q['text']}",
                                (f"lựa chọn: {' | '.join(q['options'])}" if q["options"] else "")
                                + (f" · mặc định: {q['default']}" if q["default"] else "")]
                               for q in c["questions"]],
                        "decidable": False})
        out.sort(key=lambda g: -g["hours"])
        return out

    def gate_title(self, r: Any) -> str:
        t = self.lead.tickets.get(r.subject_id)
        return t.title if t else f"{r.kind} · {r.subject_id}"

    def gate_effect(self, r: Any) -> str:
        return gate_effect(r.kind, r.subject_id)

    def gate_reject(self, r: Any) -> str:
        return gate_reject_effect(r.kind, r.subject_id)

    def gate_agent(self, r: Any) -> str:
        return gate_next_agent(r.kind)

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
                        # `used` = TỔNG token (input+output) của agent làm ticket; ngân sách ticket tính theo token ĐẦU RA
                        # (`out`). Trang so `out` với `bud`; so `used` với `bud` là so hai đại lượng khác nhau.
                        "used": b.used if b else 0, "out": b.output_used if b else 0, "bud": t.budget_tokens if t else 0,
                        "est": (t.estimate_tokens or 0) if t else 0, "retry": t.retry if t else 0,
                        "ahead": self._ahead(tid, t, st), **self.truth.ticket_extra(tid)})
        return out

    def _ahead(self, tid: str, task: Any, state: str) -> int | None:
        """C7: commit của `ticket/<id>` chưa có trên nhánh tích hợp. Bỏ qua ticket đã xong (nhánh của chúng đã gộp
        hoặc đã xoá) để không bắn một tiến trình git cho mỗi ticket mỗi lần bus đổi."""
        if task is None or state in DONE_STATES: return None
        repo = self.repos.get(str(task.project_id))
        return None if repo is None else ahead_count(repo, tid, self.integration_branch)

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
                        "f": f"{p.get('verdict', '?')} · {detail}" if detail else str(p.get("verdict", "?")),
                        "trim": self.truth.review_trimmed(e), "trim_src": self.truth.review_trimmed_sources(e),
                        "at": e.ts.astimezone().strftime("%H:%M")})
        return out

    def quality(self) -> list[dict[str, Any]] | None:
        """Quality contract (ADR-0021 §f): đọc `<db>.quality.sqlite` CHỈ ĐỌC, cạnh bus, độc lập với việc bus của
        công ty có replay được hay không — journal là nguồn riêng của nó. `None` = chưa có profile nào được ký
        (chưa có file), trang hiện "không có profile"; console không tự tạo file để trả lời câu hỏi này."""
        return quality_contracts(Path(self.db).with_suffix(".quality.sqlite")) if self.db else None

    def truth_block(self) -> dict[str, Any]:
        """Sự thật giao hàng (console/truth.py). Xưởng chưa đọc được → mọi phần rỗng nhưng vẫn đủ khoá."""
        if not self.ok:
            return {"delivery": None, "pending_decisions": [], "running": None, "deadlocks": [],
                    "product_funnel": [], "silent_deadlocks": [], "sandbox": None, "quality": self.quality()}
        return {"delivery": self.truth.delivery(), "pending_decisions": self.truth.pending_decisions(),
                "running": self.truth.running(), "deadlocks": self.truth.deadlocks(),
                "product_funnel": self.truth.product_funnel(),
                "silent_deadlocks": self.truth.silent_ticket_deadlocks(),
                "sandbox": self.truth.sandbox(), "quality": self.quality()}

    def stuck(self) -> int:
        return sum(1 for st in self.lead.state.values() if st in STUCK_STATES) if self.ok else 0


class KeeperView(_View):
    """`keeper` (công ty bảo trì): ticket bảo trì + sổ nợ + gate, replay trên log đã đọc.

    KHÔNG dựng `KeeperOrchestrator`: constructor của nó mở `KeeperBus` (SQLite bền vững) — tức `CREATE TABLE` +
    đổi journal mode trên chính DB của công ty đang chạy, đúng thứ mà nguyên tắc "chỉ đọc" ở đầu file cấm. Cùng
    lý do console không dùng `SQLiteBus` cho hai công ty kia. Máy trạng thái thì vẫn là của `keeper`:
    `PersistentGate` của `keeper` cho sổ gate, `Ledger.overdue` của `keeper` cho nợ quá hạn.

    Ngân sách hiện ở đây là ngân sách ĐỌC ĐƯỢC TỪ BUS: hạn mức tuần (`KEEPER_MAX_PR_PER_WEEK`), số dòng release
    đã soạn trong 7 ngày, và số ý định mở PR chưa có số PR (`ReleaseNote.pr_number is None`). Số PR đang mở
    THẬT là câu trả lời của `gh` (`budget.can_open_pr`, bất biến I3) — console không gọi `gh`, nên nó không
    được phép nói con số ấy.
    """

    def _read(self) -> list[Any]:
        return _envelopes(self.db, KeeperEnvelope)

    def _replay(self) -> None:
        self.bus = _load_bus(KeeperMemoryBus(KEEPER_CORE, enforce_owners=False), self.envelopes)
        self.gate = KeeperGate(self.bus)
        self.ledger = Ledger()
        self.mtickets: dict[str, KeeperTicket] = {}
        self.mnotes: dict[str, tuple[datetime, KeeperNote]] = {}
        for env in self.envelopes:
            if env.topic == "maintenance-tickets":
                t = KeeperTicket.model_validate(env.payload)
                self.mtickets[t.ticket_id] = t
            elif env.topic == "debt-ledger":
                self.ledger.add(DebtEntry.model_validate(env.payload))
            elif env.topic == "release-notes":
                n = KeeperNote.model_validate(env.payload)
                self.mnotes[n.ticket_id] = (env.ts, n)

    @property
    def ran(self) -> bool:
        """Đã chạy lần nào chưa. `ok` mà log RỖNG vẫn là chưa chạy — đó chính là chỗ số 0 màu xanh sinh ra."""
        return self.ok and bool(self.envelopes)

    def tickets(self) -> list[dict[str, Any]]:
        """Hàng đợi: ticket chưa có dòng release nào (`release-notes` là dấu "đã xong một vòng",
        `orchestrator.tick`) — không đọc `status == "closed"`, không mã nào trong `keeper/src/` đặt trạng thái ấy."""
        return [{"id": t.ticket_id, "subject": t.subject, "tier": t.risk_tier, "due": t.due_at or "",
                 "gate": t.requires_gate, "st": t.status}
                for t in self.mtickets.values() if t.ticket_id not in self.mnotes]

    def debts(self, now: datetime) -> list[dict[str, Any]]:
        return [{"subject": d.subject, "reason": d.reason, "due": d.due_at, "tier": d.tier}
                for d in self.ledger.overdue(now)]

    def budget(self, now: datetime) -> dict[str, Any]:
        window = now - timedelta(days=KEEPER_WINDOW_DAYS)
        week = sum(1 for ts, _ in self.mnotes.values() if ts >= window)
        cap = max_pr_per_week()
        return {"max_per_week": cap, "notes_week": week, "left": max(0, cap - week),
                "intents": sum(1 for _, n in self.mnotes.values() if n.pr_number is None)}

    def block(self, now: datetime) -> dict[str, Any]:
        """Khối `keeper` của `/api/state`. Chưa chạy lần nào → mọi `v` là `null` và trang in `empty_note`;
        KHÔNG có ô nào mang số 0."""
        if not self.ran:
            return {"ran": False, "empty_note": KEEPER_EMPTY_NOTE, "tickets": [], "debts": [], "gates": [],
                    "cards": [{"k": k, "v": None, "n": n} for k, n in KEEPER_CARDS]}
        tickets, debts, gates, bud = self.tickets(), self.debts(now), self.gates(now), self.budget(now)
        values = {"queue": len(tickets), "budget": bud["left"], "overdue": len(debts), "gates": len(gates)}
        notes = {"queue": f"{len(self.mtickets)} ticket bảo trì đã mở", "budget": f"trần {bud['max_per_week']}/tuần"
                 + (f" · {bud['intents']} ý định PR chưa có số" if bud["intents"] else ""),
                 "overdue": f"{len(self.ledger.entries)} mục trong sổ nợ", "gates": "cần người ký"}
        return {"ran": True, "empty_note": KEEPER_EMPTY_NOTE, "tickets": tickets, "debts": debts, "gates": gates,
                "cards": [{"k": k, "v": values[key], "n": notes[key]} for key, (k, _) in zip(KEEPER_KEYS, KEEPER_CARDS, strict=True)]}


# ---------- backends: llm.yaml (routing.status) rồi mới đến gateway ----------

def _routing_status() -> list[dict[str, Any]] | None:
    """`routing.status()` thật dựng từ `llm.yaml` của công ty (nếu có file). Client không được tạo ở đây —
    console chỉ hỏi trạng thái, không gọi model — nên mỗi backend dùng `FakeClient` làm chỗ giữ chỗ."""
    for llm_mod, routing_mod in ((company_llm, company_routing),):
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


def _co_container_runtime(which: Any = shutil.which) -> bool:
    """Máy ĐANG CHẠY CONSOLE có docker/podman không (K2.7, cờ `sources.<công ty>.sandbox_available`).

    Console và orchestrator thường chạy trên cùng máy nên đây là xấp xỉ đủ tốt — và là xấp xỉ AN TOÀN theo hướng
    đúng: nếu console chạy ở máy khác *không* có docker, cờ `false` chỉ làm ô cảnh báo im, chứ không bịa ra một
    cảnh báo sai. Ngược lại (console có docker, orchestrator không) thì cảnh báo vẫn đúng việc cần làm: đi kiểm
    máy chạy orchestrator."""
    return any(which(x) for x in ("docker", "podman"))


def _tiles(company: CompanyView, views: list[_View], now: datetime) -> dict[str, Any]:
    tickets = company.tickets()
    cost_today, tokens_today = _today_totals(views, now)
    totals = [v.metrics["total"] for v in views]
    creport = company.report if company.ok else {}
    return {
        "events": sum(len(v.envelopes) for v in views),
        "queue": sum(_queue(v.envelopes) for v in views),
        "model_calls": sum(int(t.get("calls") or 0) for t in totals),
        "tool_calls": sum(int(t.get("tool_calls") or 0) for t in totals),
        "tokens": sum(int(t.get("tokens") or 0) for t in totals),
        "project_budget_tokens": sum(t["bud"] for t in tickets),
        "rework_rate": creport.get("rework_rate"),
        "review_catch_rate": creport.get("review_catch_rate"),
        "prs_unverified": int(creport.get("prs_unverified") or 0),
        "cost_today_usd": cost_today,
        "tokens_today": tokens_today,
        "stuck_tickets": company.stuck(),
        "project_cost_usd": round(sum(creport.get("project_cost_usd", {}).values()), 4),
        "project_budget_usd": company.sup.project_budget_usd if company.ok else None,
        "unpriced_calls": sum(int(t.get("unpriced") or 0) for t in totals),
        "calibration": _calibration(company),
    }


def collect(company_db: Path | None, keeper_db: Path | None = None,
            gateway_token_file: Path | None = None,
            gateway_url: str = "http://127.0.0.1:1123") -> dict[str, Any]:
    """Trạng thái hợp nhất của software-company + keeper + gateway (xem `console/API.md`). Không bao giờ ném:
    nguồn nào hỏng thì `sources[<nguồn>].ok = false` kèm lý do và phần dữ liệu của nguồn đó rỗng."""
    now = datetime.now(UTC).astimezone()
    company = CompanyView(COMPANY, company_db)
    keeper = KeeperView(KEEPER, keeper_db)
    # `views` là danh sách nuôi các ô CHI PHÍ/TOKEN của trang Trực ban. `keeper` KHÔNG có tên trong đó: nó chưa
    # có `llm.yaml` nào và chưa gọi model lần nào, nên cộng nó vào chỉ thêm một số 0 vô nghĩa vào mẫu số.
    views: list[_View] = [company]

    backends = _routing_status()
    if backends is None:
        backends, gateway_error = _gateway_status(gateway_url, gateway_token_file)
        if gateway_error: backends = []
    else:
        gateway_error = None  # backend lấy từ llm.yaml, không cần hỏi gateway

    log = [row for _, row in sorted((r for v in views for r in v.log()), key=lambda r: r[0], reverse=True)[:LOG_LIMIT]]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "sources": {COMPANY: company.source, KEEPER: keeper.source,
                    "gateway": {"ok": gateway_error is None, "url": gateway_url, "error": gateway_error}},
        "tiles": _tiles(company, views, now),
        # Gate của `keeper` đi CHUNG hàng đợi Trực ban: người trực có một chỗ duy nhất để ký.
        "gates": company.gates(now) + keeper.gates(now),
        "keeper": keeper.block(now),
        "tickets": company.tickets(),
        "prs": company.prs(),
        "reviews": company.reviews(),
        "cost_days": _cost_days(views, now),
        "agents": _agents(views),
        "backends": backends,
        "supervisor": [a for v in views for a in v.supervisor_actions()],
        "log": log,
        # 4L-5: đo vòng tool (`company.metrics`, đặc tả L3 "cách đo") — xưởng phần mềm, giống truth_block().
        "loops": company.metrics.get("loops", _LOOPS_EMPTY) if company.ok else _LOOPS_EMPTY,
        **company.truth_block(),
    }
