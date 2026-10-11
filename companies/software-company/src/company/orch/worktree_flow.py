"""Vòng đời worktree: repo theo dự án, tạo worktree ticket, gọi agent kỹ thuật, gộp vào nhánh tích hợp
(tách khỏi orchestrator.py theo ADR-0034).

Mỗi hàm nhận `o: Orchestrator` làm tham số đầu và được gán làm method trên `Orchestrator`
(`_merge_ticket = worktree_flow.merge_ticket`, …), nên `self` tự bind qua descriptor của Python và mọi lời
gọi cũ (`o._engineer(...)`, `o.workspace(...)`) không đổi.

`_merge_lock` ở lại `Orchestrator.__init__`: nó khoá theo TIẾN TRÌNH, không theo module — nhiều orchestrator
trong cùng tiến trình (test dựng vài bản trên cùng bus) phải có khoá riêng, module-level RLock sẽ gộp chúng.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..events import Envelope, Task
from ..roles import LEAD_ACTOR, ROLE
from ..tools import ToolBox, WorkspaceTools
from ..workspace import Integration, TicketWorkspace, WorkspaceError, _git
from .routes import BLIND_STRIP, MAX_CONFLICT_RETRIES, Route, key_for
from .verify import _release_root

SAFE_TICKET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def learn_repo(o: Orchestrator, env: Envelope, replaying: bool = False) -> None:
    """`research-requests` mang `repo` (đường dẫn repo git của khách, tuyệt đối hoặc tương đối với cwd) và tuỳ chọn
    `base` → nhánh tích hợp riêng cho dự án đó. Không có `repo` thì dự án dùng `--repo` mặc định. Repo không phải git
    → không dừng dự án (nó vẫn chạy được không repo, PR ghi `unverified`), chỉ audit `project.repo_invalid` một lần."""
    raw = env.payload.get("repo")
    if not raw or not isinstance(raw, str): return
    pid = str(env.payload.get("project_id") or env.key)
    path = Path(raw).expanduser()
    if not (path / ".git").exists():
        if pid not in o.bad_repos:
            o.bad_repos.add(pid)
            if not replaying:
                o._audit("project.repo_invalid", {"project_id": pid, "repo": raw, "fallback": str(o.repo) if o.repo else None},
                            project_id=pid)
        return
    base = str(env.payload.get("base") or o.base)
    current = o.project_repos.get(pid)
    if current is not None and current.repo == path.resolve() and current.base == base: return
    o.project_repos[pid] = Integration(path.resolve(), o.integration_branch, base, o.release_branch)
    o.bad_repos.discard(pid)
    o.lead.require_integration = True
    if not replaying: o._audit("project.repo", {"project_id": pid, "repo": str(path.resolve()), "base": base}, project_id=pid)

def integration_for(o: Orchestrator, project_id: str | None) -> Integration | None:
    """Nhánh tích hợp của dự án: repo riêng của dự án nếu có, không thì repo mặc định `--repo` (có thể None)."""
    if project_id and project_id in o.project_repos: return o.project_repos[project_id]
    return o.integration

def project_of_ticket(o: Orchestrator, ticket_id: str) -> str | None:
    t = o.lead.tickets.get(ticket_id)
    return t.project_id if t is not None else None

def integration_of_ticket(o: Orchestrator, ticket_id: str) -> Integration | None:
    return o.integration_for(o._project_of_ticket(ticket_id))

def has_integration(o: Orchestrator) -> bool:
    return o.integration is not None or bool(o.project_repos)

def workspace(o: Orchestrator, ticket_id: str) -> TicketWorkspace | None:
    """Worktree của ticket, rẽ từ nhánh tích hợp của DỰ ÁN chứa ticket (tạo nhánh tích hợp nếu chưa có)."""
    # `ticket_id` do agent lập kế hoạch đặt, thành tên thư mục dưới `.worktrees/`: `..`/đường dẫn tuyệt đối sẽ
    # biến "worktree" thành chính checkout của khách (hoặc chỗ bất kỳ) — chỉ nhận một đoạn tên an toàn.
    if not SAFE_TICKET_ID.fullmatch(ticket_id): return None
    integ = o._integration_of_ticket(ticket_id)
    if integ is None or integ.repo is None: return None
    with o._ws_lock: integ.ensure()  # nhiều worker cùng tạo nhánh tích hợp lần đầu → tuần tự
    # ADR-0035 (K2.4): sandbox đi THEO WORKTREE. `WorkspaceTools(ws, ...)` trong `runner.py` đọc `ws.sandbox`
    # nên mọi lượt agent kỹ thuật nhận đúng backend mà không nơi nào phải truyền lại.
    return TicketWorkspace(integ.repo, ticket_id, base=integ.branch, sandbox=o.sandbox)

def integrate_approved(o: Orchestrator, res: StepResult) -> None:
    """Ticket vừa approved → merge ngay vào nhánh tích hợp, không đợi RC. Ticket phụ thuộc rẽ nhánh từ nhánh tích hợp,
    nên nếu chỉ merge lúc release (nhất là khi gom release) thì ticket sau không thấy code của ticket trước:
    DHCB-5 import `dhcb.layout` của DHCB-2 và đỏ ngay dù DHCB-2 đã approved."""
    if not o._has_integration(): return
    for tid, st in list(o.lead.state.items()):
        if st != "approved": continue
        # `tid in o.integrated` KHÔNG đủ để bỏ qua: ticket bị trả về làm lại (nghiệm thu rejected, review block)
        # rồi approved lần nữa thì branch có commit MỚI mà tập `integrated` vẫn nhớ lần trước → bản sửa không bao
        # giờ vào nhánh tích hợp, release sau vẫn mang code cũ. Đo được 2026-09-06 (TCK-CR-STAGE-001-02: bản sửa
        # deploy.sh nằm ở commit WIP trên branch, v0.18.2 vẫn là bản lỗi `uv sync --frozen`).
        if tid in o.integrated and not o._branch_ahead(tid): continue
        o._merge_ticket(tid, res, release_id=None)

def branch_ahead(o: Orchestrator, tid: str) -> bool:
    """Branch ticket có commit chưa nằm trong nhánh tích hợp? (làm lại sau khi đã merge một lần)."""
    integ = o._integration_of_ticket(tid); ws = o.workspace(tid)
    if integ is None or ws is None or not ws.path.exists(): return False
    try:
        return bool(integ.rev_list_count(ws.branch))
    except WorkspaceError:
        return False

def merge_ticket(o: Orchestrator, tid: str, res: StepResult, release_id: str | None) -> bool:
    """merge --no-ff branch ticket vào nhánh tích hợp. Xung đột → ticket về changes_requested với hint là file xung
    đột, worktree tạo lại từ nền mới; trả về False."""
    with o._merge_lock:
        return o._merge_ticket_locked(tid, res, release_id)

def merge_ticket_locked(o: Orchestrator, tid: str, res: StepResult, release_id: str | None) -> bool:
    with o._lock:
        already = tid in o.integrated
    if already and not o._branch_ahead(tid):
        return True  # thread khác vừa merge xong, hoặc branch không có gì mới so với nhánh tích hợp
    integration = o._integration_of_ticket(tid)
    ws = o.workspace(tid)
    if integration is None or ws is None or not ws.path.exists():
        # Khoá `once`: nhánh này KHÔNG đổi trạng thái gì (`return True` ngay), nên mỗi nhịp watch gọi lại
        # `merge_ticket` cho cùng ticket là ghi thêm một bản ghi y hệt. Đo trên `company.sqlite` của QLKH:
        # 13 399 / 17 278 bản ghi audit-log là `integration.skipped` — 78% cả DB, và `metrics`/`console` đọc
        # "sự thật" từ chính sổ này nên mọi thống kê bị pha loãng 4×. Các audit anh em cùng vòng lặp
        # (`gate.overdue`, `gate.escalate` trong scheduler.py) đã có khoá; chỗ này sót.
        o._audit("integration.skipped", {"release_id": release_id, "ticket_id": tid, "reason": "không có worktree"},
                 ticket_id=tid, once=f"integration.skipped:{release_id}:{tid}")
        return True
    t = o.lead.tickets.get(tid)
    before = integration.sha()
    m = integration.merge(ws.branch, f"merge({tid}): {t.title if t else tid}" + (f"\n\nrelease: {release_id}" if release_id else ""))
    if m.ok and m.sha == before:
        # Branch không có gì mới so với nhánh tích hợp (vd. vừa `fresh()` sau xung đột, chưa có PR mới) — nhưng
        # `tid` ĐANG NẰM TRÊN nhánh tích hợp đúng như merge thật sẽ để lại, không có gì mất khi coi là "đã tích
        # hợp": thêm vào `o.integrated` để nhịp watch SAU đi qua short-circuit ở đầu hàm
        # (`already and not _branch_ahead`), không gọi lại `integration.merge()` (lệnh git thật) vô ích mỗi 3
        # giây. Trước bản vá này: khoá `once` (PR #291) chỉ chặn được BẢN GHI audit-log trùng, không chặn việc
        # gọi lại — đo trên QLKH thật, orchestrator vẫn đứng yên ở TCK-033 sau khi vá #291
        # (`test_merge_ticket_noop_them_tid_vao_integrated_khong_goi_lai_git_merge`).
        with o._lock: o.integrated.add(tid)
        o._audit("integration.noop", {"release_id": release_id, "ticket_id": tid, "sha": before}, ticket_id=tid,
                 once=f"integration.noop:{release_id}:{tid}:{before}")
        res.actions.append(f"integration_noop:{tid}"); return True
    if m.ok:
        with o._lock: o.integrated.add(tid)
        o._audit("integration.merged", {"release_id": release_id, "ticket_id": tid, "sha": m.sha, "branch": integration.branch,
                                           "repo": str(integration.repo)}, ticket_id=tid)
        res.actions.append(f"integrated:{tid}@{m.sha}")
        started = o.lead.mark_integrated(tid)  # F15: ticket phụ thuộc bắt đầu trên nền đã có code này
        o._record_lesson(tid)
        if started: res.actions.append("dispatch:" + ",".join(started))
        return True
    if not m.conflicts:
        # Merge hỏng KHÔNG vì xung đột (file chưa track trong worktree tích hợp, index khoá...): lỗi môi trường,
        # không phải của ticket. Coi là xung đột thì `ws.fresh()` xoá nhánh ticket ĐÃ DUYỆT và đá nó về rework
        # (audit 2026-09-23). Giữ nguyên nhánh + trạng thái, báo người một lần; nhịp sau tự thử lại khi đã dọn.
        rec = {"release_id": release_id, "ticket_id": tid, "branch": integration.branch, "error": m.error}
        o._audit("integration.failed", rec, ticket_id=tid, once=f"integration.failed:{tid}:{before}:{m.error}")
        o.supervisor.escalate_gate(tid, f"merge {tid} vào {integration.branch} hỏng (không phải xung đột): {m.error[:200]}",
                                   once_key=f"integration.failed:{tid}:{before}:{m.error}")
        res.actions.append(f"integration_failed:{tid}")
        return False
    hint = f"xung đột với nhánh tích hợp {integration.branch} ở: {', '.join(m.conflicts or [])}. Làm lại trên nền mới."
    o._audit("integration.conflict", {"release_id": release_id, "ticket_id": tid, "conflicts": m.conflicts}, ticket_id=tid)
    with o._lock: o.conflict_retries[tid] += 1; n = o.conflict_retries[tid]
    try:
        ws.fresh()
        # Dưới ngưỡng: xung đột do thua cuộc đua merge, không tính vào retry nội dung (xem docstring
        # `request_changes_no_retry_bump`). Vượt ngưỡng: lặp quá nhiều lần là dấu hiệu bế tắc cấu trúc
        # (nhiều ticket cùng sửa một file interface) — tính vào retry nội dung như cũ để cuối cùng mở gate.
        if n > MAX_CONFLICT_RETRIES:
            o.lead.request_changes(tid, hint)
        else:
            o.lead.request_changes_no_retry_bump(tid, hint)
    except (ValueError, WorkspaceError) as e:
        o._audit("handler_error", {"agent": LEAD_ACTOR, "error": str(e)[:300]}, ticket_id=tid)
    res.actions.append(f"conflict:{tid}")
    with o._lock: o.stats["conflicts"] += 1
    return False

def read_only_tools(o: Orchestrator, inp: Envelope) -> ToolBox | None:
    """Tool chỉ đọc cho QA: worktree của ticket (review PR) hoặc worktree tích hợp (hồi quy sau khi deploy staging —
    release không có ticket riêng, nhưng code vừa deploy chính là nhánh tích hợp). Không có repo → không tool."""
    if not o._has_integration(): return None
    tid = inp.payload.get("ticket_id") or (inp.key if inp.topic in {"tasks", "pull-requests"} else None)
    if tid and (ws := o.workspace(str(tid))) is not None and ws.path.exists():
        return WorkspaceTools(ws, allow_write=False).toolbox()
    integ = o._integration_of_release(inp) if inp.payload.get("release_id") else None
    if integ is not None and integ.path.exists():
        # Gốc là `Path` (worktree tích hợp, không phải worktree của ticket) nên không có `ws.sandbox` để
        # đi theo — truyền tường minh, nếu không QA hồi quy sẽ chạy lệnh khách ngoài sandbox.
        # Đọc ĐÚNG sha đã staged, không phải đầu nhánh tích hợp (cùng họ lỗi với `verify._release_root`).
        root = _release_root(o, str(inp.payload["release_id"]), integ)
        return WorkspaceTools(root, allow_write=False, sandbox=o.sandbox).toolbox()
    return None

def author_tests(o: Orchestrator, agent: str, task: Envelope, r: Route, phase: str | None = None) -> Envelope | None:
    """ADR-0028: lượt viết test MÙ. Đầu vào bị cắt còn đặc tả — không `hint`, không diff, không nhắc gì tới
    cách cài đặt — vì test viết theo cách cài đặt là test không ràng buộc được gì."""
    tid = str(task.payload.get("ticket_id") or task.key)
    ws = o.workspace(tid)
    if ws is None: return None
    # Chỉ lượt đi từ `tasks` mới mù; lượt tranh chấp (`pull-requests` mang `test_dispute`) ĐƯỢC xem diff.
    inp = task if task.topic != "tasks" else task.model_copy(
        update={"payload": {k: v for k, v in task.payload.items() if k not in BLIND_STRIP}})
    g, status = o.runner.author_tests(agent, inp, ws, max_turns=o.max_turns, phase=phase)
    p = g.payloads[0]
    if status == "green":
        # Test xanh khi code chưa có: có thể là test rỗng/assert vô nghĩa. Không chặn (bộ test vẫn có thể
        # đúng — ticket sửa lỗi trên hành vi đã tồn tại), nhưng cờ đi theo PR để reviewer đọc được.
        o._audit("tests_green_before_code", {"ticket_id": tid, "agent": agent, "files": p.get("files", [])},
                    actor=agent, ticket_id=tid, project_id=task.payload.get("project_id"))
    return o.runner.publish(agent, task, r.topic_out, p, key=key_for(r.topic_out, p, task.key),
                               tokens=g.tokens, model=g.model, context_writes=g.context_writes, generated=g)

def engineer(o: Orchestrator, agent: str, task: Envelope, r: Route, phase: str | None = None) -> Envelope | None:
    """Ticket → PR. Có repo: agent làm trong worktree, bằng chứng do code điền. Không repo: PR đi tiếp nhưng
    `local_checks` của model bị thay bằng `{"unverified": true}` và ghi audit — không có bằng chứng giả."""
    tid = task.payload.get("ticket_id") or task.key
    budget = o.lead.tickets[tid].budget_tokens if tid in o.lead.tickets else task.payload.get("budget_tokens")
    if (b := o.supervisor.budgets.get(tid)) is not None:
        # Lần làm lại chỉ còn phần ngân sách chưa đốt (supervisor cộng dồn theo audit, kể cả phần đã cấp thêm).
        # Trừ theo ĐẦU RA cho khớp với guard trong `_turns`: trừ theo tổng token thì ticket dùng tool luôn thấy
        # ngân sách bằng 0 ngay từ lần làm lại đầu tiên (đo được: output 18868 nhưng tổng 734862).
        budget = max(b.limit - b.output_used, 0)
    ws = o.workspace(tid)
    # ADR-0028: đi từ `test-suites` nghĩa là bộ test đã do `qa` (pha `author`) viết — `builder` viết code cho tới
    # khi xanh nhưng KHÔNG ghi (và không xoá) được file test. Đi thẳng từ `tasks` thì bộ test vẫn là của chính nó.
    doc_lap = task.topic == "test-suites"
    if ws is not None:
        g = o.runner.generate_in_workspace(agent, task, ws, budget=budget, max_turns=o.max_turns,
                                              write_scope="src" if doc_lap else "all", phase=phase)
        p = g.payloads[0]
        lc = p["local_checks"]
        if lc.get("lint") is False or lc.get("tests") is False:
            # Máy đã biết PR đỏ: không đưa qua reviewer/QA/security (tốn ba lượt để nghe lại), trả thẳng về ticket.
            bad = [k for k in ("lint", "tests") if lc.get(k) is False]
            hint = f"{'/'.join(bad)} local fail (retry {task.payload.get('retry', 0)}):\n" + \
                   "\n".join((lc.get({"lint": "lint_output", "tests": "test_output"}[k]) or "")[-1500:] for k in bad)
            o._audit("pr.rejected_local_checks", {"ticket_id": tid, "agent": agent, "failed": bad, "commit": p.get("pr_ref"),
                                                     "files": p.get("impact", {}).get("files", [])},
                        actor=agent, tokens=g.tokens, cost=g.cost_usd, ticket_id=tid, project_id=task.payload.get("project_id"))
            if tid in o.lead.tickets: o.lead.rework(tid, hint)
            return None
    else:
        g = o.runner.generate(agent, task, r.topic_out, phase=phase)
        p = {**g.payloads[0], "local_checks": {"unverified": True}}
        o._audit("local_checks.unverified", {"ticket_id": tid, "agent": agent, "claimed": g.payloads[0].get("local_checks")},
                    actor=agent, ticket_id=tid)
    p = {**p, "tests_authored_by": ROLE.QA if doc_lap else "assignee"}
    return o.runner.publish(agent, task, r.topic_out, p, key=key_for(r.topic_out, p, task.key),
                               tokens=g.tokens, model=g.model, context_writes=g.context_writes, generated=g)

def comment(o: Orchestrator, ticket_id: str, by: str, text: str) -> Task:
    """Nhận xét của người cho ticket đang chạy: ghi audit `human.comment` và phát lại task với hint = nhận xét
    (delivery-lead không tính retry). Ticket blocked/escalated dùng gate escalation."""
    if not by.split(":", 1)[0] == "human": raise ValueError("by phải là human:<tên>")
    t = o.lead.tickets.get(ticket_id)
    if t is None: raise ValueError(f"không có ticket {ticket_id}")
    o._audit("human.comment", {"ticket_id": ticket_id, "by": by, "text": text[:2000], "state": o.lead.state.get(ticket_id)},
                actor=by, ticket_id=ticket_id, project_id=t.project_id)
    return o.lead.human_hint(ticket_id, text)

def takeover(o: Orchestrator, ticket_id: str, by: str, message: str | None = None) -> Envelope:
    """Người sửa tay trong worktree `ticket/<id>` rồi giao lại: CODE chạy lint/test thật, commit (nếu còn thay đổi chưa
    commit), publish `pull-requests` dưới tên người với `local_checks.verified_by=workspace`; reviewer/QA/security review
    như PR của agent. Ticket đang `in_review` thì PR này thay PR của agent (vòng review làm lại)."""
    if not by.split(":", 1)[0] == "human": raise ValueError("by phải là human:<tên>")
    t = o.lead.tickets.get(ticket_id); st = o.lead.state.get(ticket_id)
    if t is None: raise ValueError(f"không có ticket {ticket_id}")
    if st not in {"dispatched", "in_progress", "in_review"}:
        raise ValueError(f"{ticket_id}: chỉ tiếp quản ticket dispatched/in_review (đang {st})")
    ws = o.workspace(ticket_id)
    if ws is None or not ws.path.exists():
        raise ValueError(f"{ticket_id}: không có worktree (cần --repo; worktree ở <repo>/.worktrees/{ticket_id})")
    if not ws.has_changes(): raise ValueError(f"{ticket_id}: worktree không có thay đổi so với nhánh tích hợp")
    checks = ws.run_checks()
    sha = ws.commit_all(message or f"feat({ticket_id}): {by} tiếp quản — {t.title}"[:72]) if _git(ws.path, "status", "--porcelain") \
        else _git(ws.path, "rev-parse", "--short", "HEAD")
    files = ws.changed_files()
    p = {"ticket_id": ticket_id, "branch": ws.branch, "pr_ref": sha, "summary": message or f"{by} tiếp quản ticket",
         "impact": {"files": files}, "local_checks": {**checks, "verified_by": "workspace"}}
    o._audit("human.takeover", {"ticket_id": ticket_id, "by": by, "commit": sha, "files": files,
                                   "lint": checks["lint"], "tests": checks["tests"]}, actor=by, ticket_id=ticket_id, project_id=t.project_id)
    # Con của PR gần nhất (chưa có PR thì của `tasks` — ticket dispatched luôn đã có nó trên bus): giữ `correlation_id`
    # của ticket thay vì mở một gốc nhân quả mới (ib1-quansat Q1).
    cause = o.bus.latest("pull-requests", ticket_id) or o.bus.latest("tasks", ticket_id)
    make = cause.child if cause is not None else Envelope
    return o.bus.publish(make(topic="pull-requests", key=ticket_id, actor=by, payload=p))  # type: ignore[arg-type]  # child() khai kiểu Envelope của core
