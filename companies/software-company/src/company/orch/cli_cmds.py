"""Từng subcommand của CLI, mỗi cái một hàm (K1.8 kịch bản B: `main` ≤ 60 dòng).

Trước đây cả 13 lệnh nằm trong một chuỗi `if ns.cmd == …` dài 162 dòng bên trong `main()`. Tách ra không đổi
hành vi một chữ nào — mục đích là để đọc được MỘT lệnh mà không phải cuộn qua mười hai lệnh khác, và để chỗ
dựng `Orchestrator` (đắt: cần client thật cho `run`/`redeploy`) hiện rõ là ranh giới giữa hai nhóm:

* **Nhóm bus** (`BUS_CMDS`) chỉ cần `SQLiteBus` — chạy trước khi dựng `Orchestrator`, nên `metrics`/`trace` trên
  một file bus của máy khác không đòi SDK hay API key.
* **Nhóm orchestrator** (`ORCH_CMDS`) cần đối tượng đã dựng.

Mỗi hàm trả **mã thoát** đúng như đường cũ: 0 xong, 1 lượt model của lệnh lỗi (`redeploy`/`recheck`), 2 lỗi của
người dùng (in ra stderr), 3 không lấy được lease.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..bus import is_human
from ..events import Envelope
from ..workspace import WorkspaceError

if TYPE_CHECKING:
    import argparse

    from ..orchestrator import Orchestrator, StepResult
    from ..sqlite_bus import SQLiteBus


# ---------- nhóm bus: chưa cần Orchestrator ----------

def publish(bus: SQLiteBus, ns: argparse.Namespace) -> int:
    if not is_human(ns.actor):  # CLI là cửa của người; giả danh agent/orchestrator từ đây là vượt quyền producer của bus
        print(f"--actor phải là người (human:<tên>), không phải {ns.actor!r}", file=sys.stderr); return 2
    payload = json.loads(ns.file.read_text(encoding="utf-8"))
    key = ns.key or payload.get("ticket_id") or payload.get("release_id") or payload.get("change_id") or payload.get("project_id")
    if not key: print("cần --key", file=sys.stderr); return 2
    env = bus.publish(Envelope(topic=ns.topic, key=key, actor=ns.actor, payload=payload))
    print(f"published {env.topic} key={env.key} event={env.event_id}"); return 0


def decide_change(bus: SQLiteBus, ns: argparse.Namespace) -> int:
    from ..orchestrator import _evidence
    if not is_human(ns.by):  # quyết định của khách (audit 2026-09-27 F-A): `--by ops` lọt ACL bus, vai khác nổ traceback
        print(f"--by phải là người (human:<tên>), không phải {ns.by!r}", file=sys.stderr); return 2
    cr = next(reversed(list(bus.replay(topic="change-requests", key=ns.change_id))), None)
    if cr is None: print(f"không có change-request {ns.change_id}", file=sys.stderr); return 2
    impact = next((_evidence(e.payload) for e in reversed(list(bus.replay(topic="audit-log")))
                   if e.payload.get("action") == "change.impact" and _evidence(e.payload).get("change_id") == ns.change_id), {})
    payload = {**cr.payload, "decision": ns.decision, "impact": {**cr.payload.get("impact", {}), **impact.get("impact", {}),
                                                                   "decided_by": ns.by, "reason": ns.reason}}
    env = bus.publish(Envelope(topic="change-requests", key=ns.change_id, actor=ns.by, payload=payload))
    print(f"{ns.change_id}: {ns.decision} by {ns.by} event={env.event_id}"); return 0


def metrics(bus: SQLiteBus, ns: argparse.Namespace) -> int:
    from ..metrics import collect, prometheus
    m = collect(bus)
    print(prometheus(m) if ns.prometheus else json.dumps(m, ensure_ascii=False, indent=2)); return 0


def diagnose(bus: SQLiteBus, ns: argparse.Namespace) -> int:
    from ..metrics import diagnose as run_diagnose
    print(json.dumps(run_diagnose(bus, top=ns.top), ensure_ascii=False, indent=2)); return 0


def trace(bus: SQLiteBus, ns: argparse.Namespace) -> int:
    from ..trace import run as trace_run
    return trace_run(bus, ns.subject, ns.json)


BUS_CMDS: dict[str, Callable[[Any, Any], int]] = {
    "publish": publish, "decide-change": decide_change, "metrics": metrics, "diagnose": diagnose, "trace": trace,
}


# ---------- nhóm orchestrator ----------

def status(orch: Orchestrator, ns: argparse.Namespace) -> int:
    print(json.dumps(orch.status(), ensure_ascii=False, indent=2)); return 0


def report(orch: Orchestrator, ns: argparse.Namespace) -> int:
    print(json.dumps(orch.supervisor.sprint_report(), ensure_ascii=False, indent=2)); return 0


def rulings(orch: Orchestrator, ns: argparse.Namespace) -> int:
    rows = orch.rulings(project_id=ns.project, ticket_id=ns.ticket)
    for ru in rows:
        who = ru.get("ticket_id") or ru.get("project_id") or "-"
        print(f"{ru['at']}  {ru['by']:<18} {who:<14} {ru['decision']}")
        print(f"{'':40} vì: {ru['why']}")
        print(f"{'':40} sai thì: {ru['cost_if_wrong']}")
    print(f"({len(rows)} ruling)"); return 0


def show(orch: Orchestrator, ns: argparse.Namespace) -> int:
    sc = orch.blackboard.read(ns.namespace, ns.project)
    if sc is None and ns.project is None:
        # Blackboard phân vùng theo dự án: không nêu --project thì chỉ đoán được khi đúng một dự án có namespace này.
        found = [c for (pid, nsp), c in orch.blackboard._latest.items() if nsp == ns.namespace]
        if len(found) == 1: sc = found[0]
        elif len(found) > 1:
            projects = ", ".join(sorted(str(c.project_id) for c in found))
            print(f"{ns.namespace} có ở nhiều dự án ({projects}); nêu --project", file=sys.stderr); return 2
    if sc is None: print(f"chưa có namespace {ns.namespace}", file=sys.stderr); return 2
    scope = f" [{sc.project_id}]" if sc.project_id else ""
    print(f"# {ns.namespace} v{sc.version}{scope} — {sc.content_ref}\n# {sc.summary}\n")
    print(sc.content if sc.content is not None else "(chỉ có con trỏ, không có toàn văn)"); return 0


def comment_or_takeover(orch: Orchestrator, ns: argparse.Namespace) -> int:
    try:
        if ns.cmd == "comment":
            t = orch.comment(ns.ticket_id, ns.by, ns.text); print(f"{t.ticket_id}: phát lại với hint (retry={t.retry})")
        else:
            env = orch.takeover(ns.ticket_id, ns.by, ns.message)
            print(f"{env.key}: PR {env.payload['pr_ref']} của {ns.by}, lint={env.payload['local_checks']['lint']} "
                  f"tests={env.payload['local_checks']['tests']} event={env.event_id}")
    except (ValueError, WorkspaceError) as e:
        print(str(e), file=sys.stderr); return 2
    return 0


def _with_lease(db: Path, body: Callable[[], int]) -> int:
    """Lease của file bus: hai tiến trình cùng ghi một `company.sqlite` là hỏng âm thầm. Trả 3 khi không lấy được."""
    from ..sqlite_bus import Lease, LeaseError
    try:
        lease = Lease(db); lease.acquire()
    except LeaseError as e:
        print(str(e), file=sys.stderr); return 3
    try:
        return body()
    finally:
        lease.release()  # trả lease TRƯỚC khi exec: tiến trình mới phải lấy được lease


def _step_failed(res: StepResult, what: str) -> bool:
    """Lượt model của lệnh vận hành LỖI thì nói ra và thoát 1 — trước đây CLI in "đã chạy lại" và thoát 0 cả khi
    `_call` ghi `error:`/`transient:`, script vận hành không phân biệt được (audit 2026-09-27 B1)."""
    loi = [a for a in res.actions if a.startswith(("error:", "handler_error:", "transient:"))]
    if loi: print(f"{res.key}: {what} lỗi — {'; '.join(loi)}", file=sys.stderr)
    return bool(loi)


def redeploy(orch: Orchestrator, ns: argparse.Namespace) -> int:
    def body() -> int:
        try:
            res = orch.redeploy(ns.release_id, ns.by)
        except ValueError as e:
            print(str(e), file=sys.stderr); return 2
        if _step_failed(res, "lượt staging"): return 1
        print(f"{res.key}: đã chạy lại lượt staging (by={ns.by})")
        return 0
    return _with_lease(ns.db, body)


def recheck(orch: Orchestrator, ns: argparse.Namespace) -> int:
    def body() -> int:
        try:
            res = orch.recheck(ns.release_id, ns.by)
        except ValueError as e:
            print(str(e), file=sys.stderr); return 2
        if _step_failed(res, "lượt security"): return 1
        print(f"{res.key}: đã chấm lại release-check của security (by={ns.by})")
        return 0
    return _with_lease(ns.db, body)


def run(orch: Orchestrator, ns: argparse.Namespace) -> int:
    """`run` là lệnh duy nhất chạy vòng lặp. `--watch` + mã nguồn đổi → `ReloadRequested` → khởi động lại tiến
    trình bằng `execv` SAU khi đã trả lease (tiến trình mới phải lấy được nó)."""
    from ..orchestrator import ReloadRequested
    from .cli import _fmt, _reexec
    reload = False

    def body() -> int:
        nonlocal reload
        if ns.watch:
            try: orch.watch(interval=ns.watch, reload=not ns.no_reload)
            except KeyboardInterrupt: pass
            except ReloadRequested: reload = True
        else:
            for r in orch.tick() if ns.max_steps is None else orch.run(ns.max_steps): print(_fmt(r))
        return 0

    rc = _with_lease(ns.db, body)
    if rc: return rc
    if reload:
        argv = [sys.executable, "-u", "-m", "company.orchestrator", *sys.argv[1:]]  # -u: stdout không bị buffer (URL/token/log)
        try:
            _reexec(argv)
        except OSError as e:
            # Audit 2026-09-23: execv hỏng ở đây là tiến trình chết SAU khi đã trả lease — cả đêm không ai chạy và
            # không gì nói. Chạy tiếp bằng mã cũ, tắt reload tới lần khởi động sau, ghi audit để người thấy.
            orch._audit("orchestrator.reload_failed", {"error": str(e)[:300], "argv": argv})
            print(f"khởi động lại thất bại ({e}); chạy tiếp mã cũ, tắt tự reload", file=sys.stderr)
            ns.no_reload = True
            return run(orch, ns)
    print(json.dumps(orch.status(), ensure_ascii=False))
    return 0


ORCH_CMDS: dict[str, Callable[[Any, Any], int]] = {
    "status": status, "report": report, "rulings": rulings, "show": show,
    "comment": comment_or_takeover, "takeover": comment_or_takeover, "redeploy": redeploy, "recheck": recheck,
    "run": run,
}
