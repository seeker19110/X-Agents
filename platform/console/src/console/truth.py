"""Sự thật giao hàng của software-company — phần mà bảng trạng thái FSM che mất.

Đêm 2026-09-05/06 vận hành QLKH mất hàng giờ vì đọc SAI trạng thái, không phải vì hệ chạy sai: `status` xanh toàn tập
(`queue 0, blocked [], gates {}`) trong khi 18/19 release không đi đâu được; `delivery: {}` là "chưa giao gì" nhưng
nhìn như một dict rỗng vô hại; duyệt gate `escalation` tưởng là giao hàng; quyết định ký lúc 01:34 áp lúc 01:48 mà
trang không nói gì. Module này tính, từ chính log của bus, những câu trả lời một người trực ban cần:

- **Đã giao chưa?** `delivery`: bao nhiêu RC, bao nhiêu ra production, tag/sha mới nhất, và phễu RC đứng ở bậc nào.
- **Ai đang chờ ai?** `pending_decisions`: quyết định người đã ký mà orchestrator chưa áp (nằm sau lượt model dài).
- **Có đang chạy không?** `running`: hàng đợi còn gì, event đầu hàng đợi chờ bao lâu, lần cuối có bản ghi là khi nào.
- **Bế tắc im lặng?** `deadlocks`: kẹt mà không gate nào chờ — không phải "đang chờ người", là không ai được hỏi.

Chỉ đọc, chỉ suy từ envelope đã có; không đụng git (console không có repo khách). Ngưỡng và tên trạng thái lấy từ
`company.delivery`/`company.orchestrator`, không viết lại ở đây.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from company.delivery import DONE_STATES
from company.roles import ROLE, SOURCE

ORCHESTRATOR = "orchestrator"
CONTROL_TOPICS = frozenset({"audit-log", "shared-context", "supervisor-actions"})
REVIEW_AGENT = {SOURCE.REVIEWER: ROLE.QA, SOURCE.QA: ROLE.QA, SOURCE.SECURITY: ROLE.SECURITY}
STUCK_STATES = frozenset({"blocked", "escalated"})
# K2.7: cửa sổ nhìn lại của ô "lệnh khách chạy ở đâu". 24h = một ca trực; dài hơn thì một lượt cũ
# kéo cảnh báo sáng mãi sau khi người vận hành đã bật container.
SANDBOX_WINDOW_H = 24

# Bậc của phễu release, theo thứ tự đi tới. Mỗi RC đứng đúng một bậc; `n` đếm theo bậc là câu "RC chết ở đâu".
# Khoá `gate3*` giữ nguyên chữ (JS `static/js/truth.js::TONE` và deep-link dùng chúng); NHÃN thì bỏ số thứ tự —
# ADR-0037 bỏ gate plan nên `gates/checklists.md` đánh lại "Gate 2 — Duyệt release production", nói "Gate 3"
# với người trực là chỉ họ sang một mục không tồn tại.
FUNNEL = [
    ("void", "Bị huỷ"),
    ("rc", f"Chờ {ROLE.OPS}[deploy]"),
    ("staging_failed", "Staging thất bại"),
    # ADR-0039: `deploy_failed` KHÁC `failed` — đã thử dựng container và không dựng được (hoặc smoke vào cổng đã
    # map không qua). Ticket của RC KHÔNG bị trả về làm lại, nên gộp vào ô "thất bại" là nói sai với người trực:
    # họ sẽ đi tìm ticket rework không tồn tại thay vì mở `evidence.deploy` xem `logs_tail`.
    ("staging_deploy_failed", "Staging: deploy hỏng (container không chạy)"),
    ("staging_pending_human", "Staging: agent dừng chờ người"),
    ("staging_deployed", "Staging xong, chờ QA hồi quy"),
    ("qa_failed", "QA hồi quy chặn"),
    ("gate3_missing", "QA xong nhưng gate release KHÔNG mở"),
    ("gate3", "Chờ gate release"),
    ("gate3_approved", "Gate release đã ký, chờ deploy"),
    ("production_failed", "Production thất bại"),
    ("production_deploy_failed", "Production: deploy hỏng (container không chạy)"),
    ("production_pending_human", "Production: agent dừng chờ người"),
    ("production", "Đã lên production"),
    ("delivered", "Đã giao (tag + push)"),
]
FUNNEL_LABEL = dict(FUNNEL)

# Bậc của phễu SẢN PHẨM (C1): câu hỏi "yêu cầu của khách đã đi tới đâu", không phải "RC nào chết ở đâu".
# Mỗi bậc đếm hiện vật CÓ THẬT trên bus. Ô bằng 0 là ô XÁM (`empty=True`) — không bao giờ xanh: đêm 05/09 mọi ô
# xanh vì rỗng là hiểu nhầm số 1 (TRAPS §2, §3).
PRODUCT_STAGES = [
    ("request", "Yêu cầu khách"),
    ("spec", "Đặc tả đã duyệt"),
    ("ticket", "Ticket"),
    ("rc", "Release-candidate"),
    ("staging", "Staging (smoke)"),
    ("production", "Production (smoke)"),
    ("acceptance", "Khách nghiệm thu"),
]

# Mẫu lý do duyệt (C6): lý do người ghi được gửi THẲNG cho agent làm hint. "ok" là bảo nó không có gì để sửa.
HINT_TEMPLATE = "root_cause: \ndecision: \nhint: "

# Agent chạy lại sau khi DUYỆT từng loại gate — người trực phải biết mình vừa đánh thức ai (C2).
# ADR-0037: software-company không còn gate `plan` (kế hoạch do `_check_plan` cho đi thẳng).
NEXT_AGENT = {"release": ROLE.OPS, "spec": f"{ROLE.SECURITY} + {ROLE.PRODUCT}",
              "acceptance": ROLE.OPS, "escalation": "agent đang giữ ticket"}


def gate_next_agent(kind: str) -> str:
    return NEXT_AGENT.get(kind, "")


def gate_reject_effect(kind: str, subject_id: str) -> str:
    """Từ chối thì ticket/RC về đâu — nửa còn thiếu của "hậu quả" (C2). Duyệt được nói rồi; từ chối thì đêm 05/09
    không ai biết việc rơi về trạng thái nào, nên không ai dám từ chối."""
    if kind == "release":
        return "Từ chối = RC dừng tại đây, không deploy; ticket của RC quay về `changes_requested` cho kỹ sư làm lại."
    if kind == "escalation":
        if subject_id.startswith("REL-"):
            return "Từ chối = finding vẫn chặn; RC nằm nguyên bậc hiện tại cho tới khi có RC mới."
        return "Từ chối = ticket ĐÓNG hẳn (`closed`), không ai làm tiếp — không phải \"để đó tính sau\"."
    if kind == "spec":
        return "Từ chối = `product` (pha spec) viết lại PRD; chưa có ticket nào tồn tại để mà quay về."
    if kind == "acceptance":
        return "Từ chối = release không được nghiệm thu; ticket của release mở lại chờ sửa."
    return ""


# Hậu quả của việc DUYỆT từng loại gate — hiện ngay trên nút, vì duyệt `escalation` cho REL-xxx KHÔNG deploy gì cả.
def gate_effect(kind: str, subject_id: str) -> str:
    if kind == "release":
        return "Duyệt = `ops` (pha deploy) deploy production, tag phiên bản, push. Đây là bước GIAO HÀNG."
    if kind == "escalation":
        if subject_id.startswith("REL-"):
            return "Duyệt = chấp nhận finding đang chặn release này (waive), KHÔNG deploy gì. Từ chối = trả ticket về làm lại."
        return "Duyệt = mở lại ticket với lý do bạn ghi làm hint cho agent, cấp thêm một ngân sách. Từ chối = đóng ticket."
    if kind == "spec":
        return "Duyệt = security viết threat model, `product` (pha plan) chia ticket và GIAO NGAY (ADR-0037: không còn gate plan)."
    if kind == "acceptance":
        return "Duyệt = khách ký nghiệm thu, ticket của release đóng."
    return ""


def _evidence(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        d = json.loads(payload.get("evidence") or "{}")
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _minutes(ts: datetime, now: datetime) -> int:
    return max(0, int((now - ts).total_seconds() // 60))


class Truth:
    """Một lần quét envelope của software-company, rồi trả lời từng câu."""

    def __init__(self, envelopes: list[Any], lead: Any, gate: Any, now: datetime) -> None:
        self.env = envelopes
        self.lead, self.gate, self.now = lead, gate, now
        self.audits = [e for e in envelopes if e.topic == "audit-log"]
        self.processed: set[str] = set()
        self.integrated: dict[str, str] = {}          # ticket_id → sha ngắn (audit integration.merged)
        self.void: dict[str, str] = {}                 # release_id → lý do
        self.staged_sha: dict[str, str] = {}           # release_id → sha (audit release.staged)
        self.delivered: dict[str, dict[str, Any]] = {}  # release_id → {tag, sha}
        self.trimmed: list[Any] = []                   # audit context_trimmed
        self.produced_by_event: dict[str, Any] = {}    # event_id đầu ra → audit produced:*
        self.gate_requests: dict[str, str] = {}        # subject_id → kind (mới nhất)
        for e in self.audits:
            p = e.payload; a = str(p.get("action", "")); d = _evidence(p)
            if a == "orchestrated" and p.get("actor") == ORCHESTRATOR and d.get("event_id"):
                self.processed.add(str(d["event_id"]))
            elif a == "integration.merged" and d.get("ticket_id"):
                self.integrated[str(d["ticket_id"])] = str(d.get("sha") or "")[:7]
            elif a == "release.void" and d.get("release_id"):
                self.void[str(d["release_id"])] = str(d.get("reason") or "")
            elif a == "release.staged" and d.get("release_id"):
                self.staged_sha[str(d["release_id"])] = str(d.get("sha") or "")[:7]
            elif a == "delivery.done" and d.get("release_id"):
                self.delivered[str(d["release_id"])] = {"tag": d.get("tag"), "sha": str(d.get("sha") or d.get("detail") or "")[:40], "ts": e.ts}
            elif a == "context_trimmed":
                self.trimmed.append(e)
            elif a.startswith("produced:") and d.get("event"):
                self.produced_by_event[str(d["event"])] = e
            elif a == "gate.request" and d.get("subject_id"):
                self.gate_requests[str(d["subject_id"])] = str(d.get("kind") or "")

    def gate_kind(self, sid: str) -> str | None:
        """Loại gate của một subject: đang chờ → từ `pending`; đã quyết → gate cuối trong `history`; không có → audit."""
        r = self.gate.pending.get(sid)
        if r is not None: return str(r.kind)
        for g in reversed(self.gate.history):
            if g.subject_id == sid: return str(g.kind)
        return self.gate_requests.get(sid)

    # ---- phễu release ----

    def _release_stage(self, rid: str) -> tuple[str, dict[str, Any]]:
        """Bậc hiện tại của một RC và bản ghi release-event cuối (để hiện lý do agent dừng)."""
        if rid in self.delivered: return "delivered", {}
        if rid in self.void: return "void", {"summary": self.void[rid]}
        last: Any = None
        for e in self.env:
            if e.topic == "release-events" and e.payload.get("release_id") == rid: last = e
        if last is None: return "rc", {}
        p = last.payload; env_, status = p.get("env"), p.get("status")
        info = {"summary": (p.get("summary") or "")[:400], "runbook": (p.get("runbook_ref") or "")[:200],
                "ts": last.ts.astimezone().strftime("%H:%M"), "version": p.get("version")}
        if env_ == "production":
            if status == "deployed": return "production", info
            if status == "deploy_failed": return "production_deploy_failed", info
            if status == "failed" or status == "rolled_back": return "production_failed", info
            return "production_pending_human", info
        if status == "deploy_failed": return "staging_deploy_failed", info
        if status == "failed" or status == "rolled_back": return "staging_failed", info
        if status != "deployed": return "staging_pending_human", info
        # staging deployed: QA hồi quy / gate release quyết bậc tiếp
        reviews = self.lead.release_reviews.get(rid, {})
        qa = reviews.get(SOURCE.QA)
        if qa is not None and qa.verdict != "pass" and SOURCE.QA not in self.lead.release_waived.get(rid, set()):
            return "qa_failed", info
        if any(g.subject_id == rid and g.kind == "release" and g.decision == "approve" for g in self.gate.history):
            return "gate3_approved", info
        if rid in self.gate.pending and self.gate.pending[rid].kind == "release": return "gate3", info
        if qa is not None and rid not in self.gate.pending:
            # QA đã pass mà không gate nào mở: thiếu nguồn review khác (security) hoặc review ghi sai subject —
            # đo được 2026-09-06 (REL-024: security block ghi ticket_id=ticket thay vì release). Không phải "chờ QA".
            return "gate3_missing", info
        return "staging_deployed", info

    def _release_next(self, rid: str, stage: str) -> str:
        pending = rid in self.gate.pending
        if stage == "delivered": return ""
        if stage == "void": return "Không đi tiếp — RC trùng ticket với RC khác."
        if stage == "rc": return f"Chờ `{ROLE.OPS}` (pha deploy) chạy lượt staging."
        if stage == "staging_deployed": return f"Chờ `{ROLE.QA}` (pha review) hồi quy trên staging."
        if stage == "gate3": return "Chờ NGƯỜI ký gate release (kind=release) — duyệt là deploy production."
        if stage == "gate3_approved": return f"Chờ `{ROLE.OPS}` (pha deploy) chạy lượt production."
        if stage == "production": return "Chờ tag + push (delivery) rồi khách ký nghiệm thu."
        if stage in {"staging_deploy_failed", "production_deploy_failed"}:
            # ADR-0039: đứng TRƯỚC nhánh `pending` vì deploy hỏng luôn mở escalation — "chờ người quyết gate" là
            # đúng nhưng vô dụng: người trực cần biết chỗ đọc bằng chứng. Khác `*_failed`: ticket KHÔNG bị trả về.
            return ("Deploy hỏng: đọc `evidence.deploy` (phần nào hỏng + `logs_tail`) của release-event cuối. "
                    "Container đã được `compose down`; sửa hạ tầng/compose rồi quyết gate escalation.")
        if pending: return f"Chờ người quyết gate `{self.gate.pending[rid].kind}` của RC này."
        if stage in {"staging_pending_human", "production_pending_human"}:
            return "Agent tự dừng, KHÔNG gate nào mở: không ai được hỏi. Người phải xử lý nợ agent nêu rồi request gate release lại."
        if stage == "qa_failed": return "QA chặn mà không gate escalation nào chờ — kiểm tra."
        if stage == "gate3_missing":
            return "QA hồi quy đã pass nhưng gate release không mở: thiếu nguồn review (security) hoặc review ghi sai subject. Request gate release tay."
        return "Thất bại — ticket của RC đã bị trả về làm lại; theo dõi ticket."

    def releases(self) -> list[dict[str, Any]]:
        out = []
        rcs = {e.payload.get("release_id") or e.key: e for e in self.env if e.topic == "release-candidates"}
        for rid in self.lead.releases:
            stage, info = self._release_stage(rid)
            rc = rcs.get(rid)
            out.append({"id": rid, "stage": stage, "label": FUNNEL_LABEL.get(stage, stage),
                        "version": info.get("version") or (rc.payload.get("version") if rc is not None else None),
                        "tickets": list(self.lead.release_tickets.get(rid, [])),
                        "sha": self.staged_sha.get(rid), "gate": self.gate_kind(rid) if rid in self.gate.pending else None,
                        "at": info.get("ts"), "summary": info.get("summary", ""), "runbook": info.get("runbook", ""),
                        "next": self._release_next(rid, stage)})
        return out

    def delivery(self) -> dict[str, Any]:
        rels = self.releases()
        counts: dict[str, int] = defaultdict(int)
        for r in rels: counts[r["stage"]] += 1
        live = [r for r in rels if r["stage"] != "void"]
        latest = max(self.delivered.items(), key=lambda kv: kv[1]["ts"]) if self.delivered else None
        integ_sha = None
        for e in reversed(self.audits):
            d = _evidence(e.payload)
            if e.payload.get("action") in {"integration.merged", "release.staged"} and d.get("sha"):
                integ_sha = str(d["sha"])[:7]; break
        return {
            "releases_total": len(rels), "releases_live": len(live), "void": counts["void"],
            "production": counts["production"] + counts["delivered"], "delivered": len(self.delivered),
            "latest_tag": latest[1]["tag"] if latest else None, "latest_release": latest[0] if latest else None,
            "integration_sha": integ_sha, "integrated_tickets": len(self.integrated),
            "funnel": [{"stage": k, "label": lbl, "n": counts[k], "ids": [r["id"] for r in rels if r["stage"] == k]}
                       for k, lbl in FUNNEL],
            "releases": rels,
        }

    # ---- phễu SẢN PHẨM (C1) ----

    def _release_smoke(self, rid: str, env_name: str) -> str:
        """`ok` | `unverified` | `fail` | `""` cho lượt deploy cuối của một RC ở một môi trường.

        Lấy từ `payload.smoke` mà orchestrator gắn vào release-event (ADR-0029) — KHÔNG tin `status` của agent:
        "deployed" là lời khai, `smoke` là bằng chứng máy sinh."""
        last: Any = None
        for e in self.env:
            p = e.payload
            if e.topic == "release-events" and p.get("release_id") == rid and p.get("env") == env_name: last = e
        if last is None: return ""
        sm = last.payload.get("smoke")
        if not isinstance(sm, dict): return ""
        if sm.get("unverified"): return "unverified"
        return "ok" if sm.get("ok") else "fail"

    def _project_of_release(self, rid: str) -> str | None:
        for tid in self.lead.release_tickets.get(rid, []):
            t = self.lead.tickets.get(tid)
            if t is not None: return str(t.project_id)
        return None

    def product_funnel(self) -> list[dict[str, Any]]:
        """Một phễu cho MỖI sản phẩm: yêu cầu → spec → ticket → RC → staging(smoke) → production(smoke) → nghiệm thu.

        Phễu release cũ (`delivery().funnel`) trả lời "RC chết ở bậc nào"; phễu này trả lời câu người trả tiền hỏi:
        "yêu cầu của tôi đã đi tới đâu". Ô `n == 0` mang `empty=True` để trang tô XÁM: một hàng toàn số 0 mà xanh là
        đúng cái bẫy đã ăn mất một đêm."""
        counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys([k for k, _ in PRODUCT_STAGES], 0))
        smoke: dict[str, dict[str, str]] = defaultdict(dict)
        topic_stage = {"research-requests": "request", "approved-specs": "spec", "acceptance-results": "acceptance"}
        for e in self.env:
            stage = topic_stage.get(e.topic)
            if stage is None: continue
            pid = str(e.payload.get("project_id") or "?")
            counts[pid][stage] += 1
        for t in self.lead.tickets.values():
            counts[str(t.project_id)]["ticket"] += 1   # đếm theo Task trên bus, không theo nhánh git
        for r in self.releases():
            pid = self._project_of_release(r["id"]) or "?"
            if r["stage"] == "void": continue
            counts[pid]["rc"] += 1
            for env_name, stage in (("staging", "staging"), ("production", "production")):
                v = self._release_smoke(r["id"], env_name)
                if v:
                    counts[pid][stage] += 1
                    prev = smoke[pid].get(stage)
                    if prev != "fail": smoke[pid][stage] = v if prev is None or v == "fail" else prev
        out = []
        for pid in sorted(counts):
            stages = [{"stage": k, "label": lbl, "n": counts[pid][k], "empty": counts[pid][k] == 0,
                       "smoke": smoke[pid].get(k, "")} for k, lbl in PRODUCT_STAGES]
            out.append({"project_id": pid, "stages": stages,
                        "delivered": counts[pid]["production"] > 0 and counts[pid]["acceptance"] > 0})
        return out

    # ---- người đã ký, máy chưa áp ----

    def pending_decisions(self) -> list[dict[str, Any]]:
        out = []
        for e in self.audits:
            p = e.payload
            if p.get("action") != "gate.decide" or e.event_id in self.processed: continue
            d = _evidence(p)
            out.append({"id": str(d.get("subject_id") or ""), "decision": str(d.get("decision") or ""),
                        "by": str(d.get("by") or p.get("actor") or ""), "kind": self.gate_kind(str(d.get("subject_id") or "")) or "",
                        "minutes": _minutes(e.ts, self.now), "reason": str(d.get("reason") or "")[:200]})
        return out

    # ---- hàng đợi ----

    def running(self) -> dict[str, Any]:
        queue = []
        for e in self.env:
            actionable = (e.payload.get("action") == "gate.decide") if e.topic == "audit-log" else e.topic not in CONTROL_TOPICS
            if actionable and e.event_id not in self.processed: queue.append(e)
        head = queue[0] if queue else None
        last = max((e.ts for e in self.audits), default=None)
        return {"queue": len(queue),
                "head": {"topic": head.topic, "key": head.key, "minutes": _minutes(head.ts, self.now)} if head else None,
                "last_event_minutes": _minutes(last, self.now) if last else None,
                "topics": sorted({e.topic for e in queue})}

    # ---- bế tắc im lặng ----

    def deadlocks(self) -> list[dict[str, Any]]:
        out = []
        pending = set(self.gate.pending)
        for tid, st in self.lead.state.items():
            if st in STUCK_STATES and tid not in pending:
                out.append({"kind": "ticket", "id": tid, "state": st,
                            "why": "Ticket kẹt mà không gate escalation nào chờ — không ai được hỏi.",
                            "integrated": tid in self.integrated})
        for r in self.releases():
            if r["stage"] in {"staging_pending_human", "production_pending_human", "qa_failed", "gate3_missing"} and r["id"] not in pending:
                out.append({"kind": "release", "id": r["id"], "state": r["stage"], "why": r["next"], "integrated": False})
        run = self.running()
        unfinished = [t for t, s in self.lead.state.items() if s not in DONE_STATES]
        undelivered = [r for r in self.releases() if r["stage"] not in {"delivered", "void"}]
        if run["queue"] == 0 and not pending and (unfinished or undelivered):
            out.append({"kind": "idle", "id": "-", "state": "idle",
                        "why": f"Hàng đợi rỗng, không gate nào chờ, nhưng còn {len(unfinished)} ticket chưa xong và "
                               f"{len(undelivered)} release chưa giao — không có việc nào tự chạy tiếp.", "integrated": False})
        return out

    # ---- làm giàu ticket / review ----

    def pending_decision_of(self, subject_id: str) -> dict[str, Any] | None:
        """Quyết định người đã ký cho subject này mà orchestrator CHƯA áp (C3). Trang gắn badge lên đúng ticket/RC
        đó thay vì để người tưởng chữ ký của mình vô tác dụng (đo được 01:34 ký / 01:48 áp, đêm 05/09)."""
        for d in self.pending_decisions():
            if d["id"] == subject_id: return d
        return None

    def ticket_extra(self, tid: str) -> dict[str, Any]:
        t = self.lead.tickets.get(tid)
        return {"integrated": tid in self.integrated, "sha": self.integrated.get(tid),
                "human_hint": (getattr(t, "human_hint", None) or "") if t else "",
                "hint": (getattr(t, "hint", None) or "") if t else "",
                "pending_decision": self.pending_decision_of(tid),
                "gate": self.gate_kind(tid) if tid in self.gate.pending else None}

    def silent_ticket_deadlocks(self) -> list[dict[str, Any]]:
        """Chỉ ticket `blocked`/`escalated` mà KHÔNG gate nào chờ (C4). Đây không phải "đang chờ người" — không ai
        được hỏi. Tách khỏi `deadlocks()` để trang đặt được một cảnh báo đỏ riêng ở đầu trang, đếm số."""
        return [d for d in self.deadlocks() if d["kind"] == "ticket"]

    def review_trimmed_sources(self, review_env: Any) -> list[dict[str, Any]]:
        """Đúng những nguồn bị cắt của lượt chấm này: tên namespace/artifact và số ký tự mất (C5).

        `review_trimmed()` trả một câu để nhét vào ô bảng; cái này trả danh sách để trang liệt kê CẠNH VERDICT —
        "security chặn vì thiếu diff" hoá ra là openapi 804 dòng ăn hết hạn mức, và không ai thấy điều đó."""
        prod = self.produced_by_event.get(review_env.event_id)
        if prod is None: return []
        agent = str(prod.payload.get("actor") or "")
        dur_ms = float(_evidence(prod.payload).get("duration_ms") or 0)
        start = prod.ts.timestamp() - dur_ms / 1000 - 5
        for e in reversed(self.trimmed):
            if e.payload.get("actor") != agent or e.ts > prod.ts or e.ts.timestamp() < start: continue
            d = _evidence(e.payload)
            out = [{"src": str(k), "chars": int(v)} for k, v in (d.get("trimmed_context") or {}).items()]
            if d.get("trimmed_payload"): out.append({"src": "payload", "chars": int(d["trimmed_payload"])})
            return out
        return []

    def review_trimmed(self, review_env: Any) -> str:
        """Agent chấm review này đã bị cắt ngữ cảnh gì — verdict dựa trên bằng chứng thiếu thì người phải thấy."""
        prod = self.produced_by_event.get(review_env.event_id)
        if prod is None: return ""
        agent = str(prod.payload.get("actor") or "")
        dur_ms = float(_evidence(prod.payload).get("duration_ms") or 0)
        start = prod.ts.timestamp() - dur_ms / 1000 - 5
        for e in reversed(self.trimmed):
            if e.payload.get("actor") != agent or e.ts > prod.ts or e.ts.timestamp() < start: continue
            d = _evidence(e.payload)
            cut = {**(d.get("trimmed_context") or {})}
            if d.get("trimmed_payload"): cut["payload"] = d["trimmed_payload"]
            if not cut: return ""
            return "cắt " + ", ".join(f"{k} {int(v):,} ký tự".replace(",", ".") for k, v in cut.items())
        return ""

    # ---------- K2.7: lệnh của khách chạy trong lớp bảo vệ nào ----------

    def sandbox(self, hours: int = SANDBOX_WINDOW_H) -> dict[str, Any]:
        """Đếm các lượt CHẠY MÃ CỦA KHÁCH trong `hours` giờ gần nhất, theo tên sandbox đã dùng (ADR-0035).

        Ba nguồn, đúng ba chỗ code điền bằng chứng (không đọc cấu hình — cấu hình lúc đọc lại có thể đã khác
        lúc chạy): `pull-requests.local_checks.sandbox` (lint/test của PR), `release-events.smoke.sandbox`
        (lệnh khởi động), audit `tools_used` (tool `run` của model).

        Lượt CŨ HƠN cửa sổ bị bỏ có chủ ý: câu người trực cần trả lời là "ngay bây giờ, máy này, lệnh của khách
        đang chạy ở đâu" — một lượt subprocess từ tháng trước không nói gì về hôm nay.
        """
        cut = self.now - timedelta(hours=hours)
        dem: dict[str, int] = defaultdict(int)
        moi_nhat: datetime | None = None
        mode: str | None = None
        for e in self.env:
            if e.topic == "audit-log" and e.actor == "orchestrator" and e.payload.get("action") == "sandbox.mode":
                value = _evidence(e.payload).get("mode")
                if isinstance(value, str): mode = value
            ts = getattr(e, "ts", None)
            if ts is None or ts < cut: continue
            p = e.payload
            if e.topic == "pull-requests": ten = (p.get("local_checks") or {}).get("sandbox")
            elif e.topic == "release-events": ten = (p.get("smoke") or {}).get("sandbox")
            elif e.topic == "audit-log" and p.get("action") == "tools_used": ten = _evidence(p).get("sandbox")
            else: continue
            if not isinstance(ten, str) or not ten: continue
            dem[ten] += 1
            if moi_nhat is None or ts > moi_nhat: moi_nhat = ts
        ngoai = sum(n for ten, n in dem.items() if not ten.startswith("container"))
        return {"window_h": hours, "runs": sum(dem.values()), "unsandboxed": ngoai, "mode": mode,
                "by_name": dict(sorted(dem.items())),
                "last_at": moi_nhat.isoformat(timespec="seconds") if moi_nhat else None}
