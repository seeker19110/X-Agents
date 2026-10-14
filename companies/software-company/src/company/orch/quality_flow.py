"""Nối nghiệm thu quality contract vào orchestrator (ADR gốc 0021, gói N1 của `docs/thi-hanh/pe2.md`).

- Người ghim ProjectProfile lúc ký spec (`gate_cli approve SPEC-<pid> --quality-profile`); `note_profile` ghi nhận.
- `sync_quality` là BỘ ĐỐI CHIẾU, gọi ở cuối `scheduler._mark` (điểm gọi duy nhất): đăng ký một run cho kế hoạch
  approved-specs đầu tiên sau khi ghim, rồi chiếu `lead.state` sang journal bằng `event_id` tất định — mở lại
  tiến trình thì event đã có được bỏ qua, event thiếu được ghi thêm. `lead.state` vẫn là nguồn sự thật của ticket
  (ADR-0034); journal chỉ là phép chiếu, cộng chủ sở hữu duy nhất của kết quả `quality:accept`.
- `quality:accept` không bao giờ là `Task` trên topic `tasks`: không agent nào nhận được. Nó được mở (TASK_STARTED
  mang bindings do coordinator điền) khi mọi ticket của run đã `SUCCEEDED` và có RC đã staged phủ đủ chúng;
  candidate = sha đã staged của RC (quyết định 4). Kết quả chỉ vào journal qua `submit_quality` →
  `commit_quality_result`, từ `TrustedDriver` hoặc CLI `quality_execution commit`.
- Không đụng `TICKET_TRANSITIONS`/`RELEASE_TRANSITIONS` hay bảng trạng thái ticket (ADR-0034, luật K8.3).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

from xagents_core.bus import is_human
from xagents_core.execution import (
    Complexity,
    ExecutionEvent,
    ExecutionEventKind,
    ExecutionJournal,
    ExecutionJournalError,
    ExecutionTransitionError,
    RunSpec,
    RunState,
    TaskResult,
    TaskSpec,
    TaskStatus,
)

from ..delivery import DONE_STATES
from ..events import Envelope
from ..product_quality import LEGACY_SCHEMES, ProjectProfile, Receipt, _read_trust, allowed_schemes, compile_contract
from ..quality_execution import (
    QUALITY_TASK_ID,
    QualityBindings,
    _safe_component,
    base_attempt_id,
    bindings_from_journal,
    candidate_attempt_id,
    commit_quality_result,
    compile_execution,
    fresh_attempt_id,
    last_attempt_id,
    pinned_profile_path,
    result_event_id,
)
from ..quality_floor import PROFILE_ACTION
from ..spec_approval import BusApprovalLookup
from ..workspace import _git_ok

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

K = ExecutionEventKind
_SYNC_ERRORS = (ExecutionJournalError, ExecutionTransitionError, sqlite3.Error, OSError, ValueError)
Payload = dict[str, object]
Emit = Callable[[ExecutionEventKind, "str | None", str, Payload], None]


class QualityPin(TypedDict):
    """Profile người ghim kèm chữ ký spec (evidence của `quality.profile_set`) + mốc chọn kế hoạch."""

    run_id: str
    profile_sha256: str
    contract_hash: str
    plans_before: int


class TrustedDriver(Protocol):
    """Driver tin cậy (browser/restore thật là H3–H7, ngoài N1): chạy các check trên candidate đã ghim, trả kết quả
    kèm receipt đã ký. Nó đọc bindings qua `active_bindings`, không nhận chúng từ worker."""

    def run(self, run_id: str, checks: tuple[str, ...]) -> tuple[TaskResult, list[Receipt]]: ...


# ---------- đường dẫn: cạnh bus, ngoài mọi worktree ----------

def _db(o: Orchestrator) -> Path:
    path = getattr(o.bus, "path", None)
    if path is None:
        raise ValueError("quality cần bus SQLite bền (--db): journal và kho profile nằm cạnh nó")
    return Path(path)


def journal_path(o: Orchestrator) -> Path:
    """`<db>.quality.sqlite` — N3 (console) suy ra được từ `--db`."""
    return _db(o).with_suffix(".quality.sqlite")


def evidence_root(o: Orchestrator, run_id: str) -> Path:
    """`<db>.artifacts/quality/runs/<run_id>/` — namespace riêng với kho profile (`quality/profiles/<pid>/`)."""
    return _db(o).with_suffix(".artifacts") / "quality" / "runs" / _safe_component(run_id)


def _outside_worktrees(o: Orchestrator, *paths: Path) -> None:
    repos = [Path(r) for r in (o.repo, *(i.repo for i in o.project_repos.values())) if r is not None]
    for p in paths:
        real = Path(p).resolve()
        for repo in repos:
            if real.is_relative_to((repo / ".worktrees").resolve()):
                raise ValueError(f"{p} nằm trong worktree của repo khách — journal/registry/evidence phải ngoài tầm agent")


# ---------- profile đã ghim ----------

def note_profile(o: Orchestrator, d: Mapping[str, object]) -> None:
    """Ghi nhận profile người ghim (từ replay hoặc từ event sống). Mốc `plans_before` chọn kế hoạch của run."""
    pid = str(d.get("project_id") or "")
    if not pid: return
    before = sum(1 for p in o.plans.values() if p.get("project_id") == pid)
    o.quality_profiles[pid] = QualityPin(run_id=str(d.get("run_id") or ""), plans_before=before,
                                         profile_sha256=str(d.get("profile_sha256") or ""),
                                         contract_hash=str(d.get("contract_hash") or ""))


def note_env(o: Orchestrator, env: Envelope) -> None:
    if env.topic != "audit-log" or env.payload.get("action") != PROFILE_ACTION or not is_human(env.actor): return
    try:
        d = json.loads(env.payload.get("evidence") or "{}")
    except (TypeError, ValueError):
        return
    if isinstance(d, dict): note_profile(o, d)


def _load_profile(o: Orchestrator, pid: str) -> ProjectProfile | None:
    """Đọc lại file đã ghim, băm lại; lệch hash/run/contract ⇒ audit `quality.profile_invalid` một lần, None."""
    pin = o.quality_profiles[pid]
    try:
        raw = pinned_profile_path(_db(o), pid, pin["profile_sha256"]).read_bytes()
        profile = ProjectProfile.model_validate_json(raw)
        ok = (hashlib.sha256(raw).hexdigest() == pin["profile_sha256"] and profile.project_id == pid
              and profile.run_id == pin["run_id"] and compile_contract(profile)["contract_hash"] == pin["contract_hash"])
        why = "" if ok else "hash/run/contract lệch bản người ký"
    except (OSError, ValueError) as e:
        why = f"{type(e).__name__}: {str(e)[:200]}"
    if not why: return profile
    o._audit("quality.profile_invalid", {"project_id": pid, "profile_sha256": pin["profile_sha256"], "reason": why},
             project_id=pid, once=f"quality.profile_invalid:{pid}:{pin['profile_sha256']}")
    return None


def _plan_for(o: Orchestrator, pid: str) -> str | None:
    """Kế hoạch approved-specs ĐẦU TIÊN dự án nhận sau khi ghim (ADR gốc 0021 §a). CR/incident không vào run này."""
    plans = [p for p in o.plans.values() if p.get("project_id") == pid]
    for p in plans[o.quality_profiles[pid]["plans_before"]:]:
        if p.get("source_topic") != "approved-specs" or p.get("source_key", pid) != pid: continue  # spec của CR: không
        if not p.get("plan_id"): raise ExecutionJournalError(f"kế hoạch approved-specs của {pid} thiếu plan_id")
        return str(p["plan_id"])
    return None


def _plan_tickets(o: Orchestrator, plan_id: str) -> list[Mapping[str, Any]]:
    """Ticket của kế hoạch; ticket thiếu `ticket_id` ⇒ lỗi đồng bộ có thông điệp, không KeyError làm vỡ `_mark`."""
    tickets = list(o.plans[plan_id].get("tickets") or [])
    if any(not isinstance(t, Mapping) or not t.get("ticket_id") for t in tickets):
        raise ExecutionJournalError(f"{plan_id}: có ticket thiếu ticket_id — không dựng được DAG của run")
    return tickets


# ---------- API ----------

def register_quality_run(o: Orchestrator, plan_id: str, profile: ProjectProfile) -> None:
    """Một profile ⇔ một run ⇔ DAG cố định = ticket của `plan_id` + `quality:accept`. Lặp lại thì idempotent."""
    if allowed_schemes(profile) == LEGACY_SCHEMES:
        raise ValueError("run mới phải ghim evidence_policy.allowed_schemes (ADR-0020 §3): profile legacy chỉ để kiểm lại")
    plan = o.plans[plan_id]
    if profile.project_id != plan.get("project_id"):
        raise ValueError(f"profile của {profile.project_id!r}, kế hoạch của {plan.get('project_id')!r}")
    trust = (o.quality_trust,) if o.quality_trust is not None else ()
    _outside_worktrees(o, journal_path(o), evidence_root(o, profile.run_id), *trust)
    tickets = _plan_tickets(o, plan_id)
    ids = {str(t["ticket_id"]) for t in tickets}
    work = RunSpec(profile.run_id, profile.goal, tuple(
        TaskSpec(task_id=str(t["ticket_id"]), objective=str(t.get("title") or t["ticket_id"]),
                 dependencies=tuple(str(d) for d in t.get("depends_on") or () if str(d) in ids),
                 complexity=Complexity.C2, acceptance=tuple(str(a) for a in t.get("acceptance") or ()))
        for t in tickets))
    spec = compile_execution(profile, work)
    with ExecutionJournal(journal_path(o)) as journal:
        # Run đăng ký trước N5 (không cờ reopenable) được giữ nguyên, không migrate (ADR gốc 0022, câu hỏi 2).
        if journal.load_spec(profile.run_id) != compile_execution(profile, work, reopenable=False):
            journal.register(spec)
    o._audit("quality.registered", {"project_id": profile.project_id, "plan_id": plan_id, "run_id": profile.run_id,
                                    "contract_hash": compile_contract(profile)["contract_hash"]},
             project_id=profile.project_id, once=f"quality.registered:{profile.run_id}:{plan_id}")


def active_bindings(o: Orchestrator, run_id: str) -> QualityBindings | None:
    """Bindings của attempt `quality:accept` mới nhất — cho driver tin cậy, không cho worker."""
    with ExecutionJournal(journal_path(o)) as journal:
        try:
            return bindings_from_journal(journal, run_id)
        except ExecutionJournalError:
            return None


def submit_quality(o: Orchestrator, run_id: str, result: TaskResult, receipts: list[Receipt]) -> RunState:
    """Kết quả driver → `commit_quality_result` với bindings đọc từ journal. Nộp lại cùng kết quả thì ACK."""
    pid = next((p for p, pin in o.quality_profiles.items() if pin["run_id"] == run_id), None)
    profile = _load_profile(o, pid) if pid is not None else None
    if pid is None or profile is None:
        raise ValueError(f"run {run_id} không có profile hợp lệ đã ghim")
    if o.quality_trust is None:
        raise ValueError("thiếu registry khoá công khai (quality_trust) — không nghiệm thu được")
    issuers = _read_trust(o.quality_trust)
    with ExecutionJournal(journal_path(o)) as journal:
        b = bindings_from_journal(journal, run_id)
        state = commit_quality_result(journal, profile, result, receipts,
                                      event_id=result_event_id(run_id, b.expected_attempt_id), bindings=b,
                                      trusted_issuers=issuers, evidence_root=evidence_root(o, run_id),
                                      approval_lookup=o.quality_lookup or BusApprovalLookup(o.bus, _db(o)))
    o._audit("quality.result", {"run_id": run_id, "attempt_id": b.expected_attempt_id,
                                "status": state.tasks[QUALITY_TASK_ID].value,
                                "reason": state.failures.get(QUALITY_TASK_ID, "")}, project_id=pid)
    return state


# ---------- bộ đối chiếu ----------

def sync_quality(o: Orchestrator) -> None:
    """Chiếu `lead.state` sang journal của mọi run quality; không có profile nào ⇒ trả về ngay."""
    if not o.quality_profiles: return
    # no-ky-thuat: quét toàn bộ ticket của run mỗi lần _mark, ổn tới ~500 ticket/run, quay lại khi _mark chậm quá 50ms
    with o._quality_lock:
        for pid in sorted(o.quality_profiles):
            try:
                _sync_project(o, pid)
            except _SYNC_ERRORS as e:
                _sync_error(o, pid, f"{type(e).__name__}: {str(e)[:300]}")


def _sync_error(o: Orchestrator, pid: str, why: str) -> None:
    """Một lần mỗi (run, thông điệp, lần người xử lý escalation). Không run_id ⇒ chỉ audit (không pause cả dự án)."""
    run = o.quality_profiles[pid]["run_id"]
    digest = hashlib.sha256(why.encode("utf-8")).hexdigest()[:16]
    key = f"quality.sync_error:{run or pid}:{digest}:{o.escalation_decided[run] if run else 0}"
    o._audit("quality.sync_error", {"project_id": pid, "run_id": run, "error": why}, project_id=pid, once=key)
    if run:  # escalate theo run_id, không theo dự án: pause dự án là chặn vòng ticket; release bị chặn ở N2.
        o.supervisor.escalate_gate(run, f"quality sync lỗi: {why[:200]}", once_key=key)


def _sync_project(o: Orchestrator, pid: str) -> None:
    plan_id = _plan_for(o, pid)
    if plan_id is None: return
    profile = _load_profile(o, pid)
    if profile is None: return
    run = profile.run_id
    cand = _candidate(o, [str(t["ticket_id"]) for t in _plan_tickets(o, plan_id)])
    if cand is not None and o._quality_done.get(run) == candidate_attempt_id(*cand): return  # đã kết thúc ở đúng candidate này
    register_quality_run(o, plan_id, profile)
    with ExecutionJournal(journal_path(o)) as journal:
        spec = _registered(journal, run)
        emit = _emitter(journal, spec)
        emit(K.RUN_STARTED, None, f"{run}:run:start", {})
        work = [t.task_id for t in spec.tasks if t.task_id != QUALITY_TASK_ID]
        while any(_step_ticket(o, journal, spec, tid, emit) for tid in work):
            pass
        _step_quality(o, journal, spec, profile, plan_id, work, emit)
        q = journal.resume(run).tasks[QUALITY_TASK_ID]
        attempt = last_attempt_id(journal, run)
    _note_done(o, run, q, attempt, cand)
    if q is not TaskStatus.RUNNING or o.quality_driver is None: return
    # Attempt này đã hỏng ở driver/commit và escalation chưa được người xử lý ⇒ không chạy lại (tránh vòng vô hạn).
    if o._quality_stuck.get(run) == attempt and run in o.paused: return
    o._quality_stuck.pop(run, None)
    # Attempt đang RUNNING (vừa mở, hoặc mở trước lần restart) ⇒ driver chạy lại với CÙNG attempt/bindings.
    checks = next(t.acceptance for t in spec.tasks if t.task_id == QUALITY_TASK_ID)
    try:
        try:
            result, receipts = o.quality_driver.run(run, checks)
        except Exception as e:  # driver là mã ngoài: lỗi của nó thành sync_error, không giết vòng _mark
            raise ExecutionJournalError(f"driver: {type(e).__name__}: {e}") from e
        state = submit_quality(o, run, result, receipts)
    except _SYNC_ERRORS:
        o._quality_stuck[run] = attempt
        raise
    _note_done(o, run, state.tasks[QUALITY_TASK_ID], attempt, cand)


def _registered(journal: ExecutionJournal, run: str) -> RunSpec:
    if (spec := journal.load_spec(run)) is None: raise ExecutionJournalError(f"run {run} chưa đăng ký ngay sau register")
    return spec


def _note_done(o: Orchestrator, run: str, q: TaskStatus, attempt: str, cand: tuple[str, str] | None) -> None:
    """Nhớ (trong RAM) run đã kết thúc ở đúng candidate hiện tại: các `_mark` sau không mở journal nữa."""
    key = candidate_attempt_id(*cand) if cand is not None else None
    if q in {TaskStatus.SUCCEEDED, TaskStatus.FAILED} and base_attempt_id(attempt) == key:
        o._quality_done[run] = key
    else: o._quality_done.pop(run, None)  # attempt khác đang mở (ADR gốc 0022): cache cũ không còn đúng


def _emitter(journal: ExecutionJournal, spec: RunSpec) -> Emit:
    def emit(kind: ExecutionEventKind, task_id: str | None, event_id: str, payload: Payload) -> None:
        events = journal.events(spec.run_id)
        if any(e.event_id == event_id for e in events): return  # tất định: đã ghi (kể cả trước restart) ⇒ bỏ qua
        journal.transition(ExecutionEvent(spec.run_id, kind, task_id, payload=payload, event_id=event_id),
                           expected_count=len(events))
    return emit


def _last_started(journal: ExecutionJournal, run: str, task_id: str) -> ExecutionEvent | None:
    return next((e for e in reversed(journal.events(run)) if e.task_id == task_id and e.kind is K.TASK_STARTED), None)


def _step_ticket(o: Orchestrator, journal: ExecutionJournal, spec: RunSpec, tid: str, emit: Emit) -> bool:
    """Một bước chiếu cho một ticket; True nếu vừa ghi event (vòng ngoài đọc lại state và chạy tiếp)."""
    run = spec.run_id
    state = journal.resume(run)
    cur, n = state.tasks[tid], state.attempts[tid]
    st = o.lead.state.get(tid)
    latest = o.latest("tasks", tid)
    done = st in DONE_STATES and tid in o.lead.integrated
    active = latest is not None and st not in {None, "draft", "waiting", "changes_requested"}
    if cur is TaskStatus.READY and (done or active):
        emit(K.TASK_STARTED, tid, f"{run}:{tid}:start:{n}",
             {"attempt_id": f"{tid}#{n}", "task_event": latest.event_id if latest is not None else None})
        return True
    if cur is not TaskStatus.RUNNING: return False
    if done:
        emit(K.TASK_SUCCEEDED, tid, f"{run}:{tid}:ok", {})
        return True
    started = _last_started(journal, run, tid)
    redispatched = latest is not None and started is not None and started.payload.get("task_event") != latest.event_id
    if st == "changes_requested" or redispatched:
        emit(K.TASK_FAILED, tid, f"{run}:{tid}:fail:{n - 1}", {"reason": f"ticket {st}"})
        emit(K.TASK_RETRIED, tid, f"{run}:{tid}:retry:{n - 1}", {})
        return True
    return False


def _candidate(o: Orchestrator, tickets: list[str]) -> tuple[str, str] | None:
    """RC đã staged mới nhất mà các RC (không huỷ) tính tới nó phủ đủ ticket của run: nhánh tích hợp chỉ nhận thêm
    merge, nên sha staged của nó chứa mọi ticket đã merge trước đó (quyết định 4: candidate = sha đã staged)."""
    need, covered, best = set(tickets), set[str](), None
    for rid in o.lead.releases:
        if rid in o.void_releases: continue
        covered |= set(o.lead.release_tickets.get(rid, []))
        if need <= covered and rid in o.release_sha: best = (rid, o.release_sha[rid])
    return best


def _step_quality(o: Orchestrator, journal: ExecutionJournal, spec: RunSpec, profile: ProjectProfile,
                  plan_id: str, tickets: list[str], emit: Emit) -> None:
    run = spec.run_id
    q = journal.resume(run).tasks[QUALITY_TASK_ID]
    if q not in {TaskStatus.READY, TaskStatus.FAILED, TaskStatus.SUCCEEDED}: return
    cand = _candidate(o, tickets)
    if cand is None: return
    rid, sha = cand
    if q is not TaskStatus.READY:
        prev = last_attempt_id(journal, run)
        if base_attempt_id(prev) == candidate_attempt_id(*cand): return  # đã chấm đúng candidate này: chờ sha mới
        barrier = next(t for t in spec.tasks if t.task_id == QUALITY_TASK_ID)
        if q is TaskStatus.SUCCEEDED and not barrier.reopenable: return  # run trước N5: R6 chặn, người xử lý
        # Hỏng ⇒ retry; đã đạt ở candidate cũ ⇒ mở lại (ADR gốc 0022). Lịch sử attempt cũ giữ nguyên.
        kind, verb = (K.TASK_RETRIED, "retry") if q is TaskStatus.FAILED else (K.TASK_REOPENED, "reopen")
        emit(kind, QUALITY_TASK_ID, f"{run}:quality:{verb}:{prev}", {"reason": f"candidate đổi: {prev} → {candidate_attempt_id(*cand)}"})
    attempt = fresh_attempt_id(journal, run, candidate_attempt_id(*cand))
    bindings = _bindings(o, profile, plan_id, rid, sha, tickets, attempt)
    emit(K.TASK_STARTED, QUALITY_TASK_ID, f"{run}:quality:start:{attempt}", {"attempt_id": attempt, "bindings": bindings})


def _bindings(o: Orchestrator, profile: ProjectProfile, plan_id: str, rid: str, sha: str, tickets: list[str],
              attempt: str) -> Payload:
    """Pins do coordinator điền (ADR gốc 0021 §b) — không trường nào lấy từ kết quả của worker."""
    integ = o._integration_of_ticket(tickets[0])
    if integ is None: raise ValueError(f"{rid}: không có nhánh tích hợp để tính base/diff")
    ok, base = _git_ok(integ.repo, "merge-base", integ.base, sha)
    ok, diff = _git_ok(integ.repo, "diff", f"{base}..{sha}") if ok else (False, base)
    if not ok: raise ValueError(f"{rid}: không tính được gốc/diff của candidate: {diff[:200]}")
    contract = str(compile_contract(profile)["contract_hash"])
    context = json.dumps({"contract_hash": contract, "plan_id": plan_id, "release_id": rid, "tickets": sorted(tickets)},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    need = set(tickets)
    authors = sorted({e.actor for topic in ("pull-requests", "test-suites") for e in o.bus.replay(topic=topic)
                      if str(e.payload.get("ticket_id") or e.key) in need})
    return {"expected_attempt_id": attempt, "expected_base_sha": base,
            "expected_diff_hash": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            "expected_contract_hash": contract, "candidate_sha": sha,
            "context_hash": hashlib.sha256(context.encode("utf-8")).hexdigest(), "author_principals": authors}
