"""Hồ sơ bằng chứng cho nửa "Người tự kiểm thêm" của một human gate (đặc tả `docs/dac-ta-tro-ly-kiem-duyet.md` §5).

`gate_cli list` chỉ hiện nửa "Code gửi kèm" của checklist. Nửa còn lại người duyệt phải tự đi tìm bằng chứng trong
bus, blackboard, artifact, worktree — bằng tay, mỗi lần. Lệnh này làm đúng việc đó, và CHỈ việc đó:

- **Chỉ đọc** (I3): mở SQLite bằng `mode=ro`, không publish, không tạo WAL; trạng thái gate/ticket/ngân sách dựng lại
  bằng đúng đường replay mà `orchestrator status` dùng (`Orchestrator` với `FakeClient`, không gọi model).
- **Không phán quyết** (I6): `verdict` của từng mục chỉ nhận `ok` / `gap` / `unknown`, và chỉ phần rút dữ liệu
  ĐỊNH LƯỢNG được mới đặt `ok`/`gap`; mục không định lượng được là `unknown` kèm `facts` để người (hay trợ lý
  `sc-gate-<kind>`) đọc mà tự nhận xét. Không có giá trị nào mang nghĩa "duyệt".
- **Trích tối đa 200 ký tự** mỗi nguồn (§7): hồ sơ có thể chứa PII từ PRD hay dữ liệu khách, không sao chép nguyên khối.

    python -m company.gate_brief <subject_id> [--db company.sqlite] [--repo DIR] [--format md|json] [--out DIR] [--closed]
    python -m company.gate_brief --all [--db company.sqlite]        # mọi gate đang chờ

Kết quả ghi ra `<db>.artifacts/<project>/gate-brief/<subject>.{json,md}` (đổi bằng `--out`) và in ra stdout.
Exit 2 khi subject không có trong hàng đợi gate (gate đã đóng chỉ dựng được với `--closed`), 3 khi không có DB.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .bus import InMemoryBus
from .events import Envelope
from .gate_checklists import GateSection, SelfItem
from .gate_checklists import load as load_gates
from .gates import GateRequest
from .llm import FakeClient
from .orchestrator import Orchestrator, _evidence, spec_runtime_gap
from .runner import artifact_store
from .smoke import parse_runtime, run_smoke
from .workspace import NO_HOOKS, RAW_PATHS, TicketWorkspace, clean_env

SCHEMA_VERSION = 1
EXCERPT = 200          # §7: trích tối đa 200 ký tự mỗi nguồn
ERROR_WINDOW = timedelta(days=30)
ERROR_ACTIONS = frozenset({"llm_error", "invalid_output", "handler_error", "pr.rejected_local_checks", "budget_exhausted",
                           "agent_error_unhandled", "ticket.blocked", "integration.conflict", "workspace_reset", "workspace_kept",
                           "budget.extended", "project.stalled", "project.retried"})
LOCKFILES = re.compile(r"(^|/)(uv\.lock|poetry\.lock|Pipfile\.lock|requirements[^/]*\.txt|package-lock\.json|yarn\.lock|"
                       r"pnpm-lock\.yaml|go\.sum|Cargo\.lock|Gemfile\.lock|composer\.lock)$")
_MEASURE = re.compile(r"\d+([.,]\d+)?\s*(%|(ms|s|giây|phút|rps|req/s|qps|tps|mb|gb|kb|người|users?|ccu|lần)\b)|\bp9\d\b", re.I)
_NFR_HEAD = re.compile(r"nfr|phi\s+chức\s+năng|non[- ]functional", re.I)
_OOS_HEAD = re.compile(r"out[- ]?of[- ]?scope|ngoài\s+phạm\s+vi|không\s+làm|non[- ]goals?", re.I)
_RT_HEAD = re.compile(r"chạy\s+ở\s+đâu|runtime", re.I)
_PII = re.compile(r"\bpii\b|dữ liệu cá nhân|thông tin cá nhân|cccd|cmnd|email|số điện thoại|sđt|phone|địa chỉ|ngày sinh|"
                  r"personal data", re.I)
_DEP = re.compile(r"dependency|dependencies|phụ thuộc|thư viện|library|libraries|package|license|licence|giấy phép|sdk|"
                  r"third[- ]party|bên thứ ba|api ngoài|external api|dịch vụ ngoài", re.I)
_REQ = re.compile(r"\bREQ-[A-Za-z0-9._-]+")
_ENDPOINT = re.compile(r"^\s*(?:(get|post|put|patch|delete|head|options)\s+)?(/[^\s:'\"]*)\s*:?\s*$", re.I | re.M)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)


class BriefError(Exception): ...


class NotPending(BriefError): ...


# ---------- mở bus chỉ đọc ----------

def open_read_only(db: Path) -> InMemoryBus:
    """Nạp toàn bộ log SQLite vào một InMemoryBus qua kết nối `mode=ro`. Không có bước ghi nào: không DDL, không
    PRAGMA journal_mode, không publish. Replay/latest/len chạy trên bản sao trong bộ nhớ."""
    if not db.is_file():
        raise BriefError(f"không có bus SQLite: {db}")
    con = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT body FROM events ORDER BY seq").fetchall()
    finally:
        con.close()
    bus = InMemoryBus(enforce_owners=False)
    bus._log = [Envelope.model_validate_json(body) for (body,) in rows]
    return bus


def load_state(db: Path, repo: Path | None = None, artifacts: Path | None = None) -> Orchestrator:
    """Trạng thái gate/ticket/ngân sách/blackboard dựng lại từ log — đúng đường `orchestrator status` đi (không gọi model)."""
    bus = open_read_only(db)
    return Orchestrator(bus, FakeClient(), repo=repo, artifacts=artifacts or artifact_store(db))


# ---------- tiện ích ----------

def excerpt(text: Any, n: int = EXCERPT) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _section(content: str, head: re.Pattern[str]) -> str | None:
    """Thân của heading markdown đầu tiên khớp `head` (tới heading cùng cấp hoặc cao hơn); None nếu không có."""
    marks = list(_HEADING.finditer(content))
    for i, m in enumerate(marks):
        if not head.search(m.group(2)): continue
        level = len(m.group(1))
        end = next((x.start() for x in marks[i + 1:] if len(x.group(1)) <= level), len(content))
        return content[m.end():end]
    return None


def _ns(orch: Orchestrator, namespace: str, pid: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """(toàn văn, nguồn) của bản mới nhất một namespace trong phạm vi dự án."""
    sc = orch.blackboard.read(namespace, pid)
    if sc is None: return None, None
    # Chỉ nêu đường dẫn mirror khi thật sự có toàn văn: bản ghi chỉ có con trỏ thì không có file nào để mở.
    p = orch.blackboard.path(namespace, project_id=pid) if sc.content is not None else None
    src = {"kind": "namespace", "ref": namespace, "version": sc.version, "path": str(p) if p else None,
           "content_ref": sc.content_ref}
    return sc.content, src


def _topic_src(topic: str, key: str, envs: list[Envelope]) -> dict[str, Any]:
    return {"kind": "topic", "ref": topic, "key": key, "event_ids": [e.event_id for e in envs][-20:]}


def _item(it: SelfItem, verdict: str, facts: list[str], sources: list[dict[str, Any]]) -> dict[str, Any]:
    assert verdict in {"ok", "gap", "unknown"}
    return {"id": it.id, "question": it.text, "sources": sources, "facts": facts, "verdict": verdict}


def _by_id(g: GateSection) -> dict[str, SelfItem]:
    return {it.id: it for it in g.self_checks}


def _project_of(orch: Orchestrator, kind: str, subject: str) -> str | None:
    if kind == "spec" and subject.startswith("SPEC-"): return subject[5:]
    if kind == "release":
        tids = orch.lead.release_tickets.get(subject, [])
        t = orch.lead.tickets.get(tids[0]) if tids else None
        return t.project_id if t else None
    if kind == "acceptance":
        return _project_of(orch, "release", subject[4:] if subject.startswith("UAT-") else subject)
    if kind == "escalation":
        if subject in orch.stalled: return subject
        t = orch.lead.tickets.get(subject)
        return t.project_id if t else (subject if subject in {p["project_id"] for p in orch.plans.values()} else None)
    return None


# ---------- gate `spec` (§5.3) ----------

def _brief_spec(orch: Orchestrator, g: GateSection, subject: str, pid: str | None) -> tuple[list[dict], list[dict], dict]:
    items = _by_id(g); out: list[dict[str, Any]] = []; unavailable: list[dict[str, Any]] = []
    prd, prd_src = _ns(orch, "prd", pid)
    srcs = [prd_src] if prd_src else []

    it = items["spec.nfr-co-so-do"]
    if prd is None:
        out.append(_item(it, "unknown", ["chưa có prd trên blackboard (hoặc chỉ có con trỏ, không có toàn văn)"], srcs))
    else:
        sec = _section(prd, _NFR_HEAD)
        if sec is None:
            hits = [ln for ln in prd.splitlines() if _MEASURE.search(ln)]
            out.append(_item(it, "unknown", ["prd không có mục NFR/phi chức năng riêng",
                                             f"{len(hits)} dòng trong toàn PRD có số đo kèm đơn vị"]
                             + [f"vd: {excerpt(x, 120)}" for x in hits[:3]], srcs))
        else:
            lines = [ln for ln in sec.splitlines() if ln.strip()]
            hits = [ln for ln in lines if _MEASURE.search(ln)]
            out.append(_item(it, "ok" if hits else "gap",
                             [f"mục NFR có {len(lines)} dòng, {len(hits)} dòng có ngưỡng/đơn vị"]
                             + [f"vd: {excerpt(x, 120)}" for x in hits[:3]], srcs))

    it = items["spec.out-of-scope"]
    if prd is None:
        out.append(_item(it, "unknown", ["chưa có prd"], srcs))
    else:
        sec = _section(prd, _OOS_HEAD)
        if sec is None:
            out.append(_item(it, "gap", ["prd không có heading Out of scope / Ngoài phạm vi / Không làm"], srcs))
        else:
            bullets = [ln for ln in sec.splitlines() if _BULLET.match(ln)]
            out.append(_item(it, "ok" if bullets else "gap",
                             [f"mục ngoài phạm vi có {len(bullets)} mục"] + [f"vd: {excerpt(x, 120)}" for x in bullets[:3]], srcs))

    it = items["spec.pii"]
    facts: list[str] = []; pii_src = list(srcs)
    if prd is None:
        facts.append("chưa có prd")
    else:
        hits = [ln for ln in prd.splitlines() if _PII.search(ln)]
        facts.append(f"prd có {len(hits)} dòng nhắc PII/dữ liệu cá nhân")
        facts += [f"vd: {excerpt(x, 120)}" for x in hits[:2]]
    tm, tm_src = _ns(orch, "threat-model", pid)
    if tm_src: pii_src.append(tm_src)
    if tm is None:
        facts.append("chưa có threat-model trên blackboard")
    else:
        facts.append("threat-model " + ("có" if re.search(r"phân loại|classif|dpia", tm, re.I) else "không") +
                     " nhắc phân loại dữ liệu/DPIA")
    pii_tickets = sorted(tid for tid, t in orch.lead.tickets.items() if t.project_id == pid and "pii" in t.risk_tags)
    facts.append(f"ticket mang risk_tags pii: {', '.join(pii_tickets) if pii_tickets else 'chưa có ticket nào'}")
    out.append(_item(it, "unknown", facts, pii_src))

    it = items["spec.cau-hoi-mo"]
    qs = [e for e in orch.bus.replay(topic="clarification-questions") if (e.payload.get("project_id") or e.key) == pid]
    ans = [e for e in orch.bus.replay(topic="clarification-answers") if (e.payload.get("project_id") or e.key) == pid]
    asked = {str(q.get("id")) for e in qs for q in e.payload.get("questions", []) if isinstance(q, dict)}
    answered = {str(a.get("question_id")) for e in ans for a in e.payload.get("answers", []) if isinstance(a, dict)}
    open_q = sorted(asked - answered)
    facts = [f"{len(asked)} câu hỏi làm rõ qua {len(qs)} vòng, {len(answered)} đã trả lời, {len(open_q)} chưa"]
    if open_q: facts.append("chưa trả lời: " + ", ".join(open_q[:10]))
    out.append(_item(it, "gap" if open_q else "ok", facts,
                     [_topic_src("clarification-questions", pid or "", qs), _topic_src("clarification-answers", pid or "", ans)]))

    # ADR-0031: câu "chạy cho tôi xem" hỏi ở Gate 1. Code đã chặn spec application thiếu runtime trước khi gate mở;
    # ở đây người ký thấy đúng lệnh/cổng/health/phụ thuộc mà orchestrator sẽ dùng để smoke (ADR-0029).
    it = items["spec.runtime"]
    spec = orch.latest("approved-specs", pid) if pid else None
    rt_src: list[dict[str, Any]] = ([_topic_src("approved-specs", pid or "", [spec])] if spec is not None else []) + srcs
    if spec is None:
        out.append(_item(it, "unknown", ["chưa có approved-specs cho dự án"], rt_src))
    else:
        p = spec.payload; kind = p.get("kind") or "application"; rt = parse_runtime(p)
        gap = spec_runtime_gap(p); facts = [f"kind={kind}" + ("" if p.get("kind") else " (spec không khai, mặc định application)")]
        if gap is not None:
            facts.append(gap)
        elif rt is None:
            facts.append(f"kind={kind}: miễn runtime, đã khai rõ")
        else:
            facts.append(f"command: {' '.join(rt.command)}; port: {rt.port or 'tự chọn'}; health: GET {rt.path} → {rt.expect_status}")
            deps = (p.get("runtime") or {}).get("dependencies") or []
            facts.append("phụ thuộc ngoài: " + (", ".join(map(str, deps)) if deps else "không khai (chạy in-memory?)"))
        if prd is not None:
            facts.append("prd " + ("có" if _section(prd, _RT_HEAD) is not None else "không có") + " mục 8b `Chạy ở đâu`")
        n_miss = sum(1 for e in orch.bus.replay(topic="audit-log") if e.payload.get("action") == "spec.runtime_missing"
                     and _evidence(e.payload).get("project_id") == pid)
        if n_miss: facts.append(f"spec từng bị trả lại vì thiếu runtime: {n_miss} lần")
        out.append(_item(it, "gap" if gap is not None else "ok", facts, rt_src))
    return out, unavailable, {}


# ---------- hai mục dời từ gate `plan` cũ (ADR-0037) ----------

def _brief_estimates(orch: Orchestrator, items: dict[str, SelfItem], pid: str | None,
                     tickets: list[dict[str, Any]], plan_ids: list[str]) -> list[dict[str, Any]]:
    """Ước lượng và ngân sách token — trước ADR-0037 là hai mục người-tự-kiểm của gate plan; nay đo trên chính
    các ticket của release đang xin ký. Nguồn vẫn là audit `plan.proposed` (kế hoạch sinh ra chúng) cộng
    `knowledge`, đúng các `id` cũ `plan.uoc-luong-co-so` / `plan.ngan-sach-token`."""
    out: list[dict[str, Any]] = []
    plan_ev = [e for e in orch.bus.replay(topic="audit-log")
               if e.payload.get("action") == "plan.proposed" and _evidence(e.payload).get("plan_id") in plan_ids]
    plan_src = _topic_src("audit-log", "plan.proposed", plan_ev)
    _kn, kn_src = _ns(orch, "knowledge", None)

    it = items["plan.uoc-luong-co-so"]
    ests = [int(t["estimate_tokens"]) for t in tickets if t.get("estimate_tokens")]
    cal = orch.supervisor.calibration(); lessons = orch.supervisor.lessons()
    facts = [f"{len(ests)}/{len(tickets)} ticket có estimate_tokens"]
    if ests:
        facts.append(f"estimate min/median/max = {min(ests)}/{int(statistics.median(ests))}/{max(ests)} token")
    facts.append(f"knowledge có {len(lessons)} bài học estimate-vs-actual; hiệu chỉnh: "
                 + (", ".join(f"{a}×{c['ratio_median']} ({c['samples']} mẫu)" for a, c in cal.items()) or "chưa có"))
    assignees = {str(t.get("assignee")) for t in tickets}
    missing_cal = sorted(assignees - set(cal))
    if not tickets: verdict = "unknown"
    elif len(ests) < len(tickets): verdict = "gap"
    elif not lessons: verdict = "unknown"; facts.append("dự án đầu: chưa có bài học để đối chiếu")
    elif missing_cal: verdict = "unknown"; facts.append("assignee chưa có hiệu chỉnh: " + ", ".join(missing_cal))
    else: verdict = "ok"
    out.append(_item(it, verdict, facts, [plan_src] + ([kn_src] if kn_src else [])))

    it = items["plan.ngan-sach-token"]
    sum_est = sum(ests); sum_budget = sum(int(t.get("budget_tokens") or 0) for t in tickets)
    facts = [f"{len(tickets)} ticket: tổng estimate {sum_est} token, tổng budget {sum_budget} token"]
    over_cap = [f"{t['ticket_id']}({t.get('budget_tokens')}>{cap})" for t in tickets
                if (spec := orch.agents.get(str(t.get("assignee")))) and (cap := spec.budget_tokens_per_task)
                and int(t.get("budget_tokens") or 0) > cap]
    under = [str(t["ticket_id"]) for t in tickets
             if t.get("estimate_tokens") and int(t.get("budget_tokens") or 0) < int(t["estimate_tokens"]) * 1.5]
    if over_cap: facts.append("budget vượt budget_tokens_per_task của agent: " + ", ".join(over_cap))
    if under: facts.append("budget < estimate × 1.5: " + ", ".join(under))
    pb = orch.supervisor.project_budget_usd
    facts.append(f"trần tiền dự án (llm.yaml budget_usd): {pb if pb is not None else 'chưa đặt'}"
                 + (f"; đã dùng {orch.supervisor.project_cost.get(pid or '', 0.0):.2f} USD" if pid else ""))
    out.append(_item(it, "gap" if (over_cap or under) else "unknown", facts, [plan_src]))
    return out


# ---------- gate `release` / `acceptance` (§5.5) ----------

def _endpoints(contract: str) -> list[str]:
    seen: list[str] = []
    for m in _ENDPOINT.finditer(contract):
        path = m.group(2).rstrip(":")
        if len(path) > 1 and path not in seen: seen.append(path)
    return seen


def _git(repo: Path, *args: str) -> str | None:
    # RAW_PATHS: tên non-ASCII escape thành `"docs/h\341..."` thì `startswith("docs/")` sai — xem `workspace.RAW_PATHS`
    r = subprocess.run(["git", "-C", str(repo), *NO_HOOKS, *RAW_PATHS, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=clean_env())
    return r.stdout.strip() if r.returncode == 0 else None


def _brief_release(orch: Orchestrator, g: GateSection, subject: str, pid: str | None,
                   req: GateRequest) -> tuple[list[dict], list[dict], dict]:
    items = _by_id(g); out: list[dict[str, Any]] = []; unavailable: list[dict[str, Any]] = []
    tids = orch.lead.release_tickets.get(subject, [])

    # Đọc trạng thái TIẾN TRÌNH, không đọc lời khai của agent: `--deliver` tắt thì `_deliver()` không bao giờ
    # chạy, nên release ký ở đây sẽ không tới repo khách (sự cố 2026-09-10, ADR-0027).
    it = items["release.giao-hang-duoc"]
    d_src = [{"kind": "process", "ref": "orchestrator", "url": None}]
    if getattr(orch, "deliver", False):
        remote = getattr(orch, "push_remote", None)
        dat = f"`--deliver` bật; push lên remote `{remote}`" if remote else \
              "`--deliver` bật; KHÔNG `--push-remote` — tag và nhánh release chỉ nằm ở bản sao cục bộ của repo khách"
        out.append(_item(it, "ok" if remote else "gap", [dat], d_src))
    else:
        out.append(_item(it, "gap", [
            "`--deliver` TẮT: ký gate này xong `_deliver()` vẫn không chạy — release sẽ không được tag và không "
            "tới repo khách. Bật lại orchestrator kèm `--deliver --push-remote <remote>` (console: "
            "`--deliver-remote <remote>`) rồi mới ký."], d_src))

    it = items["release.dashboard-alert"]
    contract, c_src = _ns(orch, "api-contract", pid); infra, i_src = _ns(orch, "infra", pid)
    srcs = [s for s in (c_src, i_src) if s]
    if contract is None:
        out.append(_item(it, "unknown", ["chưa có api-contract"], srcs))
    else:
        eps = _endpoints(contract)
        if infra is None:
            facts = ([f"api-contract có {len(eps)} endpoint; chưa có namespace infra để đối chiếu", f"endpoint: {', '.join(eps[:8])}"]
                     if eps else ["api-contract không đọc ra endpoint nào"])
            out.append(_item(it, "unknown", facts, srcs))
        else:
            missing = [e for e in eps if e not in infra]
            facts = [f"{len(eps)} endpoint trong api-contract, {len(eps) - len(missing)} được nhắc trong infra"]
            if missing: facts.append("không thấy trong infra: " + ", ".join(missing[:10]))
            facts.append("infra " + ("có" if re.search(r"dashboard|alert|cảnh báo|runbook", infra, re.I) else "không")
                         + " nhắc dashboard/alert/runbook")
            out.append(_item(it, "gap" if missing else ("ok" if eps else "unknown"), facts, srcs))

    it = items["release.changelog-docs-notice"]
    integ = orch.integration_for(pid)
    if integ is None or not integ.repo.exists() or not _git(integ.repo, "rev-parse", "--verify", integ.branch):
        unavailable.append({"id": it.id, "reason": "không có repo/nhánh tích hợp để xem diff (chạy lại với --repo)"})
    else:
        base = _git(integ.repo, "merge-base", integ.base, integ.branch) or integ.base
        changed = (_git(integ.repo, "diff", "--name-only", f"{base}..{integ.branch}") or "").splitlines()
        has = {"changelog": any(re.search(r"(^|/)changelog", f, re.I) for f in changed),
               "docs": any(f.lower().startswith("docs/") or "/docs/" in f.lower() for f in changed),
               "notice": any(re.search(r"(^|/)notice", f, re.I) for f in changed)}
        locks = [f for f in changed if LOCKFILES.search(f)]
        facts = [f"{len(changed)} file đổi trên {integ.branch} so với {integ.base}",
                 "CHANGELOG: " + ("có" if has["changelog"] else "không") + "; docs/: " + ("có" if has["docs"] else "không")
                 + "; NOTICE: " + ("có" if has["notice"] else "không")]
        if locks: facts.append("lockfile đổi: " + ", ".join(locks[:5]))
        verdict = "gap" if (locks and not has["notice"]) or not (has["changelog"] or has["docs"]) else "ok"
        out.append(_item(it, verdict, facts, [{"kind": "worktree", "ref": integ.branch, "path": str(integ.path),
                                               "base": integ.base}]))

    it = items["release.error-budget"]
    now = datetime.now(UTC)
    inc = [e for e in orch.bus.replay(topic="incidents") if (pid is None or e.payload.get("project_id") in {pid, None})
           and now - e.ts <= ERROR_WINDOW and str(e.payload.get("severity", "")).upper() in {"SEV1", "SEV2", "P1", "P2"}]
    bad = [e for e in orch.bus.replay(topic="release-events") if e.payload.get("status") in {"rolled_back", "failed"}
           and now - e.ts <= ERROR_WINDOW]
    unavailable.append({"id": it.id, "reason": f"repo không định nghĩa SLO/error budget; 30 ngày qua: {len(inc)} incident "
                                              f"SEV1/SEV2, {len(bad)} release rolled_back/failed"})

    it = items["release.four-eyes"]
    out.append(_item(it, "ok", [f"gate do `{req.created_by}` tạo; code từ chối quyết định của chính actor đó (four-eyes)"],
                     [{"kind": "gate", "ref": subject, "created_by": req.created_by}]))

    # Hai mục dời từ gate plan cũ (ADR-0037): đo trên chính ticket của release này.
    rel_tickets = [t.model_dump() for tid in tids if (t := orch.lead.tickets.get(tid)) is not None]
    plan_ids = sorted({orch.lead.plan_of[tid] for tid in tids if tid in orch.lead.plan_of})
    out += _brief_estimates(orch, items, pid, rel_tickets, plan_ids)

    reviews = [e for e in orch.bus.replay(topic="review-results") if e.payload.get("ticket_id") == subject]
    extra = {"tickets": tids, "version": next((e.payload.get("version") for e in orch.bus.replay(topic="release-candidates", key=subject)), None),
             "staging_reviews": [{"source": e.payload.get("source"), "verdict": e.payload.get("verdict"),
                                  "metrics": excerpt(json.dumps(e.payload.get("metrics") or {}, ensure_ascii=False)),
                                  "run": _run_summary(e.payload)} for e in reviews]}
    return out, unavailable, extra


def _smoke_for_brief(orch: Orchestrator, pid: str | None, rid: str) -> dict[str, Any]:
    """B4 / ADR-0029: hồ sơ acceptance TỰ khởi động sản phẩm theo `runtime` của spec trong worktree tích hợp của dự án
    (cùng chỗ orchestrator chạy smoke lúc deploy staging) và gọi một request thật. Khách ký trên thứ vừa chạy, không
    trên lời khai `deployed`. Không có `runtime` hay không có worktree → nói thẳng `unverified` kèm lý do — không im lặng.
    Tiến trình bị giết khi xong; không ghi bus, không ghi repo (I3 vẫn giữ: lệnh chỉ đọc bus, chạy sản phẩm chỉ để đo)."""
    spec = orch.latest("approved-specs", pid) if pid else None
    rt = parse_runtime(spec.payload if spec is not None else None)
    if rt is None:
        return {"unverified": True, "reason": "spec không có `runtime` (lệnh khởi động, cổng, đường health), không thể chạy",
                "verified_by": "orchestrator"}
    integ = orch.integration_for(pid)
    if integ is None or not integ.path.exists():
        return {"unverified": True, "reason": "không có worktree tích hợp để khởi động sản phẩm (chạy lại với --repo)",
                "verified_by": "orchestrator"}
    # `orch` ở đây do `gate_brief` tự dựng (lệnh chỉ đọc) nên `sandbox` của nó là `SubprocessSandbox` mặc
    # định trừ khi người gọi đã cấu hình — dùng lại chính nó thay vì dựng riêng, để hồ sơ gate và lượt
    # smoke thật của orchestrator chạy CÙNG lớp bảo vệ (bằng chứng so được với nhau).
    res = run_smoke(integ.path, rt, sandbox=orch.sandbox)
    res["ref"] = _git(integ.path, "rev-parse", "--short", "HEAD")
    res["release_id"] = rid
    return res


def _smoke_facts(sm: dict[str, Any]) -> list[str]:
    if sm.get("unverified"):
        return [f"KHÔNG THỂ CHẠY: {sm['reason']}"]
    facts = [f"lệnh: {excerpt(' '.join(sm.get('command') or []), 160)}",
             f"cwd={sm.get('cwd')} ref={sm.get('ref')} url={sm.get('url')}",
             f"mã HTTP: {sm.get('http_status')}; mã thoát: {sm.get('exit_code')}; {sm.get('elapsed_s')}s; "
             f"verified_by={sm.get('verified_by')}"]
    if sm.get("error"): facts.append(f"lỗi: {excerpt(sm['error'], 160)}")
    if sm.get("stderr_tail"): facts.append(f"stderr: {excerpt(sm['stderr_tail'], 160)}")
    return facts


def _run_summary(payload: dict[str, Any]) -> str | None:
    """`evidence.run` của review hồi quy (ADR-0029 mục regression-staging): một dòng người đọc được, hoặc None."""
    ev = payload.get("evidence")
    run = ev.get("run") if isinstance(ev, dict) else None
    if not isinstance(run, dict): return None
    if run.get("unverified"): return f"unverified — {run.get('reason')}"
    return f"ok={run.get('ok')} http={run.get('http_status')} exit={run.get('exit_code')} ({run.get('verified_by')})"


def _brief_acceptance(orch: Orchestrator, g: GateSection, subject: str, pid: str | None) -> tuple[list[dict], list[dict], dict]:
    items = _by_id(g); out: list[dict[str, Any]] = []; unavailable: list[dict[str, Any]] = []
    rid = subject[4:] if subject.startswith("UAT-") else subject
    events = list(orch.bus.replay(topic="release-events", key=rid))
    last = events[-1].payload if events else None
    contract, k_src = _ns(orch, "contract", pid)
    smoke = _smoke_for_brief(orch, pid, rid)
    ran = not smoke.get("unverified")

    it = items["acceptance.moi-truong"]
    facts = []
    if last is None: facts.append("chưa có release-events cho release này")
    else: facts.append(f"release-events mới nhất: env={last.get('env')} status={last.get('status')} version={last.get('version')}")
    if contract is None: facts.append("chưa có contract trên blackboard")
    else:
        hits = [ln for ln in contract.splitlines() if re.search(r"dữ liệu|data|staging|production|uat", ln, re.I)]
        facts.append(f"contract: {len(hits)} dòng nhắc dữ liệu/môi trường UAT")
        facts += [f"vd: {excerpt(x, 120)}" for x in hits[:2]]
    prod = last is not None and last.get("env") == "production" and last.get("status") == "deployed"
    # `status=deployed` là lời khai của release-engineer; khi hồ sơ tự chạy được sản phẩm thì verdict theo máy, không theo lời.
    if prod and ran: verdict = "ok" if smoke.get("ok") else "gap"; facts.append("mục `acceptance.da-chay`: " + _smoke_facts(smoke)[2])
    elif prod: verdict = "ok"
    elif contract and re.search(r"staging", contract, re.I) and last and last.get("env") == "staging": verdict = "unknown"
    else: verdict = "gap"
    out.append(_item(it, verdict, facts, [_topic_src("release-events", rid, events)] + ([k_src] if k_src else [])))

    it = items["acceptance.da-chay"]
    sm_src: list[dict[str, Any]] = [{"kind": "smoke", "ref": rid, "verified_by": "orchestrator",
                                     "cwd": smoke.get("cwd"), "url": smoke.get("url")}]
    if ran:
        out.append(_item(it, "ok" if smoke.get("ok") else "gap", _smoke_facts(smoke), sm_src))
    else:
        out.append(_item(it, "unknown", _smoke_facts(smoke), sm_src))
        unavailable.append({"id": it.id, "reason": smoke["reason"]})

    it = items["acceptance.pr-giao-hang"]  # ADR-0038: PR thật để khách review — đọc từ `delivery.done`, không từ lời khai
    pr = (orch.delivered.get(rid) or {}).get("pr")
    pr_src: list[dict[str, Any]] = [{"kind": "delivery", "ref": rid, "url": (pr or {}).get("url")}]
    if pr is None:
        out.append(_item(it, "unknown", ["không có PR giao hàng: chưa bật `--deliver-pr` hoặc release chưa giao — "
                                         "khách xem tag/nhánh release trực tiếp"], pr_src))
    elif "url" in pr:
        out.append(_item(it, "ok", [f"PR #{pr.get('number')} {pr['url']} ({pr.get('base')} ← {pr.get('head')}; "
                                    + ("mới mở" if pr.get("created") else "đang mở, dùng lại") + ")"], pr_src))
    else:
        out.append(_item(it, "gap", [f"PR không mở được: {pr.get('skipped') or pr.get('error')}"], pr_src))

    it = items["acceptance.truy-vet"]
    acc = list(orch.bus.replay(topic="acceptance-results", key=rid))
    prd, p_src = _ns(orch, "prd", pid)
    req_ids = set(_REQ.findall(prd or ""))
    srcs = [_topic_src("acceptance-results", rid, acc)] + ([p_src] if p_src else [])
    if not acc:
        out.append(_item(it, "unknown", ["khách chưa ký acceptance-results cho release này",
                                         f"prd có {len(req_ids)} requirement_id (REQ-…)"], srcs))
    else:
        findings = [f for e in acc for f in e.payload.get("findings", []) if isinstance(f, dict)]
        untraced = [f for f in findings if not _REQ.search(f"{f.get('text', '')} {f.get('location', '')}")]
        unknown_req = sorted({r for f in findings for r in _REQ.findall(f"{f.get('text', '')} {f.get('location', '')}")} - req_ids)
        crs = [e for e in orch.bus.replay(topic="change-requests") if e.payload.get("release_id") == rid]
        facts = [f"{len(acc)} bản ký, verdict mới nhất: {acc[-1].payload.get('verdict')} bởi {acc[-1].payload.get('signed_by')}",
                 f"{len(findings)} finding, {len(untraced)} không truy vết được requirement_id",
                 f"{len(crs)} change-request sinh từ nghiệm thu"]
        if untraced: facts += [f"vd: {excerpt(f.get('text'), 120)}" for f in untraced[:3]]
        if unknown_req: facts.append("REQ không có trong prd: " + ", ".join(unknown_req[:5]))
        out.append(_item(it, "gap" if untraced or unknown_req else "ok", facts, srcs))

    # 3b: hai câu về MÃ của bản giao (nơi đọc của thứ mới sinh, khả năng đứng sau stub). Bus không mang bằng chứng
    # cho chúng; im lặng bỏ mục là để người ký tưởng đã kiểm, nên hồ sơ nói thẳng `unknown` và chỗ phải đọc.
    for sid in ("acceptance.noi-doc", "acceptance.khong-stub"):
        it = items[sid]
        reason = "bus không mang bằng chứng về mã của bản giao — đọc diff release theo nguồn của mục"
        out.append(_item(it, "unknown", [reason], [{"kind": "code", "ref": rid}]))
        unavailable.append({"id": it.id, "reason": reason})
    return out, unavailable, {"release_id": rid, "tickets": orch.lead.release_tickets.get(rid, []), "smoke": smoke}


# ---------- gate `escalation` (§5.6) ----------

def _hints_used(orch: Orchestrator, subject: str) -> list[dict[str, Any]]:
    """Mọi quyết định escalation trước của cùng subject (hint đã dùng) + comment giữa vòng của người."""
    out = [{"by": r.decided_by, "decision": r.decision, "reason": excerpt(r.reason), "at": r.created_at.isoformat()}
           for r in orch.gate.history if r.subject_id == subject and r.kind == "escalation"]
    for e in orch.bus.replay(topic="audit-log"):
        if e.payload.get("action") == "human.comment" and e.payload.get("ticket_id") == subject:
            out.append({"by": e.actor, "decision": "comment", "reason": excerpt(_evidence(e.payload).get("text")), "at": e.ts.isoformat()})
    return out


def _brief_escalation(orch: Orchestrator, g: GateSection, subject: str, pid: str | None,
                      repo: Path | None) -> tuple[list[dict], list[dict], dict]:
    items = _by_id(g); it = items["escalation.ngan-sach"]
    unavailable: list[dict[str, Any]] = []
    hints = _hints_used(orch, subject)
    dup = sorted({h["reason"] for h in hints if h["reason"] and sum(1 for x in hints if x["reason"] == h["reason"]) > 1})

    if subject in orch.stalled or subject not in orch.lead.tickets:
        st = orch.stalled.get(subject, {})
        phist = [{"at": e.ts.isoformat(), "action": e.payload.get("action"), "detail": excerpt(_evidence(e.payload).get("error")
                  or _evidence(e.payload).get("reason") or e.payload.get("evidence"))}
                 for e in orch.bus.replay(topic="audit-log")
                 if e.payload.get("project_id") == subject and e.payload.get("action") in ERROR_ACTIONS]
        cost = orch.supervisor.project_cost.get(subject, 0.0); pb = orch.supervisor.project_budget_usd
        facts = [f"dự án đã tiêu {cost:.2f} USD; trần dự án: {pb if pb is not None else 'chưa đặt'}"]
        verdict = "unknown" if pb is None else ("ok" if cost < pb else "gap")
        item = _item(it, verdict, facts, [_topic_src("audit-log", subject, [])])
        extra = {"scope": "project", "stalled": st, "history": phist[-30:], "hints_used": hints, "duplicate_hints": dup,
                 "budget": {"cost_usd": round(cost, 4), "project_budget_usd": pb}}
        return [item], unavailable, extra

    t = orch.lead.tickets[subject]
    # Thứ tự ghi vào bus (`seq`) là thứ tự nhân quả duy nhất đáng tin: hai event có thể trùng dấu thời gian tới
    # micro giây (ghi trong cùng một lượt), và khi ấy xếp theo `ts` không phải thứ tự toàn phần — lịch sử lật giữa
    # hai cách sắp xếp tuỳ đồng hồ có nhích hay không, và người đọc thấy "tasks retry=2" TRƯỚC lỗi gây ra nó.
    seq = {e.event_id: i for i, e in enumerate(orch.bus.replay())}
    history: list[dict[str, Any]] = []
    for e in orch.bus.replay(topic="tasks", key=subject):
        history.append({"_seq": seq.get(e.event_id, 0), "at": e.ts.isoformat(), "action": f"tasks retry={e.payload.get('retry', 0)}", "detail": excerpt(e.payload.get("hint"))})
    for e in orch.bus.replay(topic="review-results", key=subject):
        p = e.payload
        if p.get("verdict") in {"block", "fail"}:
            detail = p.get("root_cause") or "; ".join(f.get("text", "") for f in p.get("findings", []) if isinstance(f, dict) and f.get("level") == "block")
            history.append({"_seq": seq.get(e.event_id, 0), "at": e.ts.isoformat(), "action": f"review {p.get('source')} {p.get('verdict')}", "detail": excerpt(detail)})
    for e in orch.bus.replay(topic="audit-log"):
        p = e.payload
        if p.get("ticket_id") == subject and p.get("action") in ERROR_ACTIONS:
            d = _evidence(p)
            history.append({"_seq": seq.get(e.event_id, 0), "at": e.ts.isoformat(), "action": f"{p.get('actor')}: {p.get('action')}",
                            "detail": excerpt(d.get("error") or d.get("hint") or d.get("failed") or d.get("conflicts") or p.get("evidence"))})
    for e in orch.bus.replay(topic="supervisor-actions", key=subject):
        history.append({"_seq": seq.get(e.event_id, 0), "at": e.ts.isoformat(), "action": f"supervisor {e.payload.get('action')}", "detail": excerpt(e.payload.get("reason"))})
    history.sort(key=lambda h: (str(h["at"]), h["_seq"]))
    for h in history: del h["_seq"]

    b = orch.supervisor.budgets.get(subject)
    if b is None:
        item = _item(it, "unknown", ["supervisor chưa có ngân sách cho ticket này (chưa có event tasks?)"], [])
        budget: dict[str, Any] = {}
    else:
        left = b.limit - b.output_used
        facts = [f"đầu ra {b.output_used}/{b.limit} token (còn {left}); tổng kể cả input {b.used}; review {b.review_used}; "
                 f"{b.cost_usd:.4f} USD" + (f"/{b.limit_usd:.2f}" if b.limit_usd else "")]
        item = _item(it, "ok" if left > 0 and (not b.limit_usd or b.cost_usd < b.limit_usd) else "gap", facts,
                     [_topic_src("audit-log", subject, [e for e in orch.bus.replay(topic="audit-log") if e.payload.get("ticket_id") == subject])])
        budget = {"limit": b.limit, "output_used": b.output_used, "used": b.used, "review_used": b.review_used,
                  "cost_usd": round(b.cost_usd, 4), "limit_usd": b.limit_usd, "retry": t.retry, "state": orch.lead.state.get(subject)}

    worktree: dict[str, Any] = {}
    # KHÔNG gọi `orch.workspace()`: nó `ensure()` nhánh tích hợp (tạo branch/worktree nếu thiếu) — một lệnh chỉ đọc
    # không được để lại dấu vết nào trong repo khách. Chỉ nhìn worktree đã có sẵn.
    integ = orch._integration_of_ticket(subject) if orch._has_integration() else None
    ws = TicketWorkspace(integ.repo, subject, base=integ.branch) if integ is not None else None
    if ws is not None and ws.path.exists():
        base = _git(ws.repo, "merge-base", ws.base, ws.branch) or ws.base
        stat = _git(ws.path, "diff", "--stat", base) or ""
        worktree = {"path": str(ws.path), "branch": ws.branch, "diff_stat": excerpt(stat.replace("\n", " | "), 600)}
    else:
        unavailable.append({"id": "escalation.worktree", "reason": "không có worktree của ticket (chạy lại với --repo, "
                                                                    "hoặc ticket chưa từng chạy trong repo)"})
    try:
        from .metrics import diagnose
        vong = diagnose(orch.bus, top=30)["ticket_quay_vong"].get(subject)
    except Exception:  # chẩn đoán hỏng không được làm hỏng hồ sơ
        vong = None
    extra = {"scope": "ticket", "ticket": {"title": excerpt(t.title), "assignee": t.assignee, "retry": t.retry, "risk_tags": t.risk_tags,
                                            "state": orch.lead.state.get(subject), "hint": excerpt(t.hint)},
             "history": history[-40:], "hints_used": hints, "duplicate_hints": dup, "budget": budget, "worktree": worktree,
             "diagnose": vong}
    return [item], unavailable, extra


# ---------- dựng hồ sơ ----------

def build(orch: Orchestrator, subject: str, *, closed: bool = False, now: datetime | None = None,
          repo: Path | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    req = orch.gate.pending.get(subject)
    if req is None:
        if not closed:
            raise NotPending(f"{subject} không có trong hàng đợi gate (gate đã đóng thì thêm --closed)")
        req = next((r for r in reversed(orch.gate.history) if r.subject_id == subject), None)
        if req is None: raise NotPending(f"{subject}: không có gate nào (chờ hay đã đóng) với subject này")
    g = load_gates()[req.kind]
    pid = _project_of(orch, req.kind, subject)
    if req.kind == "spec": checks, unavailable, extra = _brief_spec(orch, g, subject, pid)
    elif req.kind == "release": checks, unavailable, extra = _brief_release(orch, g, subject, pid, req)
    elif req.kind == "acceptance": checks, unavailable, extra = _brief_acceptance(orch, g, subject, pid)
    else: checks, unavailable, extra = _brief_escalation(orch, g, subject, pid, repo)
    # ADR-0030: quyết định agent tự đưa ra trong dự án — người ký gate phải thấy, vì đó là những chỗ KHÔNG ai hỏi họ.
    extra = {**extra, "rulings": (orch.rulings(project_id=pid) if pid else orch.rulings())[-30:]}
    remind, overdue = orch.gate.due(now)
    age = (now - req.created_at).total_seconds() / 3600
    return {"schema_version": SCHEMA_VERSION, "subject_id": subject, "kind": req.kind, "project_id": pid,
            "status": req.decision, "created_by": req.created_by, "created_at": req.created_at.isoformat(),
            "age_hours": round(age, 1), "due": "overdue" if subject in overdue else ("remind" if subject in remind else "ok"),
            "code_checklist": list(req.checklist),
            "self_check": checks, "unavailable": unavailable, "extra": extra}


TAG = {"ok": "[ok]     ", "gap": "[gap]    ", "unknown": "[unknown]"}


def render_md(b: dict[str, Any]) -> str:
    lines = [f"# GATE {b['subject_id']} ({b['kind']}) — hồ sơ bằng chứng, không phải khuyến nghị", "",
             f"- dự án: `{b['project_id'] or '?'}` · tạo bởi `{b['created_by']}` lúc {b['created_at']} · "
             f"{b['age_hours']} giờ · hạn: {b['due']} · trạng thái: {b['status']}", "",
             f"## Nửa của code (có trong `gate_cli list`, người duyệt tự xác nhận): {len(b['code_checklist'])} mục", "",
             *[f"- `{c}`" for c in b["code_checklist"]], "", "## Nửa của người", ""]
    for it in b["self_check"]:
        lines.append(f"{TAG[it['verdict']]} **{it['question']}** (`{it['id']}`)")
        lines += [f"  - {f}" for f in it["facts"]]
        for s in it["sources"]:
            ref = s.get("ref", "?")
            if s.get("kind") == "namespace":
                where = s.get("path") or f"(chỉ có con trỏ {s.get('content_ref')!r}, không có toàn văn)"
                lines.append(f"  - nguồn: {ref}@v{s.get('version')} → {where}")
            elif s.get("kind") == "topic": lines.append(f"  - nguồn: topic {ref} key={s.get('key')} ({len(s.get('event_ids', []))} event)")
            else: lines.append(f"  - nguồn: {s.get('kind')} {ref} " + " ".join(f"{k}={v}" for k, v in s.items() if k not in {'kind', 'ref'}))
    if b["unavailable"]:
        lines += ["", "## Không có nguồn để rút", ""] + [f"- `{u['id']}` — {u['reason']}" for u in b["unavailable"]]
    ex = b.get("extra") or {}
    if b["kind"] == "escalation":
        if ex.get("ticket"): lines += ["", "## Ticket", "", "- " + ", ".join(f"{k}={v}" for k, v in ex["ticket"].items())]
        if ex.get("stalled"): lines += ["", "## Dự án kẹt", "", f"- {excerpt(json.dumps(ex['stalled'], ensure_ascii=False), 400)}"]
        lines += ["", "## Lịch sử thất bại", ""] + ([f"- {h['at']} — {h['action']}: {h['detail']}" for h in ex.get("history", [])] or ["- (trống)"])
        lines += ["", "## Hint đã dùng", ""] + ([f"- {h['at']} — {h['by']} {h['decision']}: {h['reason']}" for h in ex.get("hints_used", [])] or ["- (chưa có)"])
        if ex.get("duplicate_hints"): lines.append("- hint lặp lại y hệt: " + " | ".join(ex["duplicate_hints"]))
        if ex.get("budget"): lines += ["", "## Ngân sách", "", "- " + ", ".join(f"{k}={v}" for k, v in ex["budget"].items())]
        if ex.get("worktree"): lines += ["", "## Worktree", "", f"- {ex['worktree']['path']} ({ex['worktree']['branch']})", f"- {ex['worktree']['diff_stat']}"]
        if ex.get("diagnose"): lines += ["", "## Chẩn đoán (metrics)", "", "- " + ", ".join(f"{k}={v}" for k, v in ex["diagnose"].items())]
    elif ex.get("tickets"):
        lines += ["", "## Ticket trong phạm vi", ""]
        lines += [f"- {json.dumps(t, ensure_ascii=False)}" if isinstance(t, dict) else f"- {t}" for t in ex["tickets"]]
        if ex.get("version"): lines.append(f"- phiên bản: {ex['version']}")
        for r in ex.get("staging_reviews", []): lines.append(f"- review staging {r['source']}: {r['verdict']} — {r['metrics']} — chạy: {r.get('run') or 'không có evidence.run'}")
    if b["kind"] == "acceptance":
        sm = ex.get("smoke") or {}
        lines += ["", "## Đã chạy — hồ sơ tự khởi động sản phẩm theo `runtime` của spec (ADR-0029, B4)", ""]
        if sm.get("unverified"):
            lines.append(f"- KHÔNG THỂ CHẠY: {sm.get('reason')} — dưới đây khách chỉ ký trên lời khai; hỏi \"chạy cho tôi xem\" trước")
        else:
            lines += ["- " + f for f in _smoke_facts(sm)]
            lines.append(f"- kết luận máy: {'ok' if sm.get('ok') else 'KHÔNG ĐẠT'} (mã HTTP kỳ vọng do spec đặt)")
    rul = ex.get("rulings") or []
    lines += ["", f"## Sổ Ruling — agent đã tự quyết {len(rul)} việc thay vì hỏi người (ADR-0030)", ""]
    lines += [f"- {r['at']} `{r['by']}` [{r.get('ticket_id') or r.get('project_id') or '-'}] **{r['decision']}** — vì: {r['why']} — sai thì: {r['cost_if_wrong']}"
              for r in rul] or ["- (chưa có ruling nào — hoặc agent vẫn dừng chờ người ở chỗ đáng lẽ phải tự quyết)"]
    lines += ["", "---", "Hồ sơ này chỉ nêu bằng chứng và chỗ thiếu bằng chứng. Quyết định là của người ký gate.", ""]
    return "\n".join(lines)


def write(b: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pj, pm = out_dir / f"{b['subject_id']}.json", out_dir / f"{b['subject_id']}.md"
    pj.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    pm.write_text(render_md(b), encoding="utf-8", newline="\n")
    return pj, pm


def default_out(db: Path, b: dict[str, Any]) -> Path:
    return artifact_store(db) / (b["project_id"] or "_") / "gate-brief"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Hồ sơ bằng chứng cho nửa 'người tự kiểm thêm' của một human gate (chỉ đọc)")
    ap.add_argument("subject", nargs="?", help="subject của gate (SPEC-P1, REL-001, UAT-REL-001, T1, P1)")
    ap.add_argument("--all", action="store_true", help="mọi gate đang chờ")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    ap.add_argument("--repo", type=Path, help="repo khách (để đọc worktree ticket / diff nhánh tích hợp)")
    ap.add_argument("--artifacts", type=Path, help="artifact store của blackboard (mặc định <db>.artifacts/)")
    ap.add_argument("--out", type=Path, help="thư mục ghi hồ sơ (mặc định <db>.artifacts/<project>/gate-brief/)")
    ap.add_argument("--format", choices=["md", "json"], default="md", help="in ra stdout dạng nào")
    ap.add_argument("--closed", action="store_true", help="cho phép dựng hồ sơ của gate đã đóng")
    ap.add_argument("--no-write", action="store_true", help="chỉ in, không ghi file")
    ns = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows console cp1252
        if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8")
    if not ns.subject and not ns.all:
        print("cần <subject> hoặc --all", file=sys.stderr); return 2
    try:
        orch = load_state(ns.db, repo=ns.repo, artifacts=ns.artifacts)
    except (BriefError, ValueError) as e:
        print(str(e), file=sys.stderr); return 3
    subjects = sorted(orch.gate.pending) if ns.all else [ns.subject]
    if ns.all and not subjects:
        print("(không có gate chờ)"); return 0
    rc = 0
    for sid in subjects:
        try:
            b = build(orch, sid, closed=ns.closed, repo=ns.repo)
        except NotPending as e:
            print(str(e), file=sys.stderr); rc = 2; continue
        if not ns.no_write:
            pj, pm = write(b, ns.out or default_out(ns.db, b))
            print(f"đã ghi {pj} và {pm}", file=sys.stderr)
        print(json.dumps(b, ensure_ascii=False, indent=2) if ns.format == "json" else render_md(b))
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
