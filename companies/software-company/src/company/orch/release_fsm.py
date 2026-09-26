"""Máy trạng thái RELEASE: merge RC vào nhánh tích hợp, gọi release-engineer (staging/production), giao hàng
thật (tag + fast-forward `company/release`), rollback, huỷ RC xung đột/vượt, mở lại release bị pause vì
ngân sách (ADR-0034, tách khỏi orchestrator.py).

Mỗi hàm nhận `o: Orchestrator` làm tham số đầu, gán làm method trên `Orchestrator`
(`_release = release_fsm._release`, …) — bề mặt gọi cũ không đổi.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..bus import REVIEWER_PREFIX
from ..delivery import DONE_STATES
from ..events import Envelope
from ..gate_risk import request_gate
from ..gates import GateRequest
from ..github_pr import PrRecord, open_pr
from ..roles import ROLE
from ..workspace import Integration, WorkspaceError
from .fsm import Transition
from .routes import PROD_ROUTE, RELEASE_CHECK_ROUTE, STAGING_ROUTE, Route

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def _integrate(o: Orchestrator, rc: Envelope, res: StepResult) -> bool:
    """Mọi ticket của RC phải nằm trên nhánh tích hợp (thường đã merge lúc approved). Trả về False nếu RC bị huỷ."""
    if not o._has_integration(): return True
    rid = rc.payload["release_id"]
    if rid in o.void_releases: return False
    for tid in rc.payload.get("tickets", []):
        if tid in o.integrated and not o._branch_ahead(tid): continue
        if o.lead.state.get(tid) not in {"approved", "merged"}:  # đã bị trả về (xung đột lúc approved): RC vô nghĩa
            o._audit("release.void", {"release_id": rid, "ticket_id": tid, "reason": f"ticket đang {o.lead.state.get(tid)}"}, ticket_id=tid)
            o._void(rid); res.actions.append(f"void:{rid}")
            return False
        if not o._merge_ticket(tid, res, release_id=rid):
            o._audit("release.void", {"release_id": rid, "ticket_id": tid}, ticket_id=tid)
            o._void(rid)
            return False
    return True

def _void(o: Orchestrator, rid: str) -> None:
    o.void_releases.add(rid)
    o.lead.void_release(rid)  # gom release: ticket approved trong RC huỷ phải vào RC kế tiếp

def _release(o: Orchestrator, agent: str, rc: Envelope, r: Route) -> Envelope:
    """release-engineer nhận RC kèm `target_env`; đầu ra phải đúng env và release_id, nếu không thì coi là invalid."""
    rid = rc.payload["release_id"]
    integ = o._integration_of_release(rc)
    extra: dict[str, Any] = ({"integration_branch": integ.branch, "integration_sha": integ.sha()}
                             if integ is not None else {})
    if r.target_env == "production":
        # `gate_release` CHỈ có nghĩa với production: Gate 3 gác cửa production, không gác staging.
        # Trước đây gửi cho cả hai env và staging luôn thấy `false` (Gate 3 chưa thể duyệt vì chưa có qa hồi quy),
        # release-engineer đọc đó là "chưa được phép" nên TỪ CHỐI deploy staging — khoá kín cả dây chuyền:
        # staging không `deployed` → qa hồi quy không chạy → Gate 3 không đủ nguồn để mở → `gate_release` mãi
        # false. Đo được 2026-09-06 (QLKH): 18/18 release-candidate chết ở đây, 0 lần ra production, 0 tag giao
        # hàng, dù 14/14 ticket đã vào nhánh tích hợp. Staging là nơi QA hồi quy TRƯỚC khi xin Gate 3 (ADR-0006).
        extra["gate_release"] = o.gate.is_approved(rid)
        # Lượt production phải THẤY bằng chứng staging/QA/security/gate ngay trong payload: agent không có tool
        # đọc bus; thiếu thì nó "không được tự suy diễn" và dừng chờ người. Đo được 2026-09-06 (REL-025): staging
        # deployed 06:01, QA pass 06:02, Gate 3 ký 06:04 — lượt production 06:04 vẫn trả pending_human với lý do
        # "chưa qua deploy staging thật".
        extra["evidence"] = o._release_evidence(rid)
    inp = rc.model_copy(update={"payload": {**rc.payload, "target_env": r.target_env, **extra}})
    if r.target_env == "staging" and integ is not None and (full := integ.rev(integ.branch)):
        # Sha mà QA sẽ hồi quy — và sha sẽ được giao khi production duyệt (ADR-0027). Ghi audit để bền qua restart.
        with o._lock: o.release_sha[rid] = full
        o._audit("release.staged", {"release_id": rid, "sha": full, "branch": integ.branch}, project_id=o.project_for(rc))
    g = o.runner.generate(agent, inp, r.topic_out, phase=r.phase)
    p = g.payloads[0]
    if p.get("env") != r.target_env or p.get("release_id") != rid:
        # `env` và `release_id` là của ROUTE và của RC, KHÔNG phải lời khai của model — cùng nguyên tắc với
        # `version` ngay dưới. Trước đây output lệch bị ném RunnerError: agent trả `env=staging` ở lượt
        # production (nhầm lẫn dễ hiểu vì hai lượt nhận payload gần giống nhau) → invalid_output → escalation,
        # và bước CUỐI của dây chuyền giao hàng chết ngay sau khi người đã ký Gate 3. Đo được 2026-09-06
        # (QLKH REL-019): hai lần liên tiếp, không deploy được production dù mọi cổng đã qua.
        o._audit("release.env_overridden", {"release_id": rid, "expected_env": r.target_env,
                                               "claimed_env": p.get("env"), "claimed_release_id": p.get("release_id")},
                    actor=agent, tokens=g.tokens)
        p = {**p, "env": r.target_env, "release_id": rid}
    if (want := rc.payload.get("version")) and p.get("version") != want:
        # Phiên bản là của RC (delivery-lead suy từ nội dung release), không phải lời khai của model.
        o._audit("release.version_overridden", {"release_id": rid, "claimed": p.get("version"), "version": want}, actor=agent)
        p = {**p, "version": want}
    if r.target_env == "staging" and p.get("status") == "deployed":
        p = o._smoke(agent, rc, rid, p, integ)
    if p.get("status") == "deployed" and r.target_env is not None:
        # ADR-0039: lời khai `deployed` mới chỉ là yêu cầu đi tiếp. Orchestrator dựng compose file của khách rồi
        # TỰ kết luận (`deployed` | `deploy_failed`); `skipped` giữ nguyên hành vi cũ. `r.target_env` là env của
        # ROUTE — production chỉ tới đây qua `PROD_ROUTE` (sau Gate 3), không có cổng nào khác.
        p = o._deploy_release(agent, rc, rid, p, integ, r.target_env)
    return o.runner.publish(agent, rc, r.topic_out, p, key=rid, tokens=g.tokens, model=g.model, generated=g)

def _deliver(o: Orchestrator, env: Envelope, res: StepResult) -> None:
    """Production đã deploy và gate release đã duyệt → tag `v<version>` + fast-forward `company/release` trong repo của
    dự án. Tắt (`--deliver` không bật) hoặc không có repo thì không làm gì; đã giao rồi thì không giao lại."""
    if not o.deliver: return
    rid = env.key
    if rid in o.delivered: return
    integ = o._integration_of_release(env)
    if integ is None or integ.rev(integ.branch) is None:
        o._audit("delivery.skipped", {"release_id": rid, "reason": "không có nhánh tích hợp (dự án chạy không repo)"},
                    project_id=o.project_for(env), once=f"delivery.skipped:{rid}:{env.event_id}")
        return
    if not o.gate.is_approved(rid):  # delivery-lead đã chặn trước (PermissionError); đây là lớp sau, không tin lời khai
        o._audit("delivery.skipped", {"release_id": rid, "reason": "gate release chưa duyệt"}, project_id=o.project_for(env))
        return
    version = str(env.payload.get("version") or "")
    tickets = o.lead.release_tickets.get(rid, [])
    message = f"release {rid} v{version}\n\ntickets: {', '.join(tickets) or '-'}\nintegration: {integ.branch}"
    try:
        r = integ.deliver(version, message, sha=o.release_sha.get(rid), push_remote=o.push_remote)
    except WorkspaceError as e:
        o._audit("delivery.error", {"release_id": rid, "version": version, "error": str(e)[:300]}, project_id=o.project_for(env))
        res.actions.append(f"delivery_error:{rid}"); return
    prinfo = _delivery_pr(o, integ, rid, version, tickets, r.pushed, r.tag)
    rec = {"release_id": rid, "version": version, "tag": r.tag, "sha": r.sha, "short": r.short, "branch": r.branch,
           "previous": r.previous, "tag_created": r.tag_created, "branch_moved": r.branch_moved, "problems": r.problems,
           "pushed": r.pushed, "push_error": r.push_error, "repo": str(integ.repo), "pr": prinfo}
    with o._lock: o.delivered[rid] = rec
    o._audit("delivery.done", rec, project_id=o.project_for(env))
    if prinfo is not None:  # ADR-0038: một dòng audit riêng cho PR để console/diagnose thấy ngay, không bới evidence
        kind_ = ("pr_skipped" if "skipped" in prinfo else "pr_failed" if "error" in prinfo
                 else "pr_opened" if prinfo.get("created") else "pr_reused")
        o._audit(f"delivery.{kind_}", {"release_id": rid, **prinfo}, project_id=o.project_for(env))
    for pr in r.problems:  # mỗi vấn đề một dòng audit riêng để `diagnose`/console thấy ngay, không phải bới evidence
        kind_, _, detail = pr.partition(":")
        o._audit(f"delivery.{kind_}", {"release_id": rid, "tag": r.tag, "detail": detail}, project_id=o.project_for(env))
    if r.pushed is False:
        o._audit("delivery.push_failed", {"release_id": rid, "remote": o.push_remote, "error": r.push_error},
                    project_id=o.project_for(env))
    res.actions.append(f"delivered:{rid}@{r.tag}" + (f"({','.join(r.problems)})" if r.problems else ""))

def _delivery_pr(o: Orchestrator, integ: Integration, rid: str, version: str, tickets: list[str],
                 pushed: bool | None, tag: str) -> PrRecord | None:
    """ADR-0038: PR thật `release_branch → base` trên GitHub của khách, mở sau khi bản giao đã push. None khi
    `--deliver-pr` tắt. Không có gì để mở (chưa push, remote không phải GitHub, base không phải nhánh) →
    `{"skipped": lý do}`; gh lỗi → `{"error": lý do}`; còn lại `{"url", "number", "created", "slug", "base", "head"}`.
    Kết quả nằm TRONG `delivery.done` nên mở lại bus dựng lại được, không mở PR lần hai."""
    if not o.deliver_pr: return None
    if not o.push_remote: return {"skipped": "cần --push-remote: PR chỉ mở được trên nhánh đã push"}
    if pushed is not True: return {"skipped": "push chưa thành công, chưa có gì trên remote để mở PR"}
    base = integ.base_branch()
    if base is None: return {"skipped": f"--base `{integ.base}` không phải nhánh: PR cần nhánh đích thật"}
    url = integ.remote_url(o.push_remote)
    title = f"release {rid} {tag}"
    body = (f"Bản giao `{tag}` của release `{rid}` (ADR-0038 — orchestrator mở PR, không merge).\n\n"
            f"- tickets: {', '.join(tickets) or '-'}\n- head: `{integ.release_branch}` (con trỏ đang chạy production)\n"
            f"- base: `{base}`\n\nReview ở đây rồi ký gate `UAT-{rid}`. Đưa vào `{base}` là quyết định của khách.")
    r = open_pr(integ.repo, url, head=integ.release_branch, base=base, title=title, body=body)
    if not r.ok and r.slug == "": return {"skipped": r.reason}  # remote không phải GitHub: không phải lỗi
    rec: PrRecord = {**r.record(), "base": base, "head": integ.release_branch}
    return rec


def _rollback_delivery(o: Orchestrator, env: Envelope, res: StepResult) -> None:
    """Production rolled_back/failed của một release đã giao → `company/release` lùi về lần giao trước; tag giữ nguyên."""
    if not o.deliver: return
    rid = env.key
    d = o.delivered.get(rid)
    if d is None: return
    integ = o._integration_of_release(env)
    if integ is None: return
    try:
        r = integ.rollback_delivery(d.get("previous"), expected=str(d["sha"]), push_remote=o.push_remote)
    except WorkspaceError as e:
        o._audit("delivery.error", {"release_id": rid, "error": str(e)[:300]}, project_id=o.project_for(env))
        res.actions.append(f"rollback_error:{rid}"); return
    with o._lock: o.delivered.pop(rid, None)
    o._audit("delivery.rolled_back", {"release_id": rid, "from": d["sha"], "to": d.get("previous"), "tag": d["tag"],
                                         "branch": r.branch, "problems": r.problems, "pushed": r.pushed,
                                         "push_error": r.push_error, "status": env.payload.get("status")},
                project_id=o.project_for(env))
    if r.pushed is False:
        o._audit("delivery.push_failed", {"release_id": rid, "remote": o.push_remote, "error": r.push_error},
                    project_id=o.project_for(env))
    res.actions.append(f"rolled_back:{rid}" + (f"({','.join(r.problems)})" if r.problems else ""))

def redeploy(o: Orchestrator, release_id: str, by: str) -> Envelope:
    """Chạy lại lượt STAGING cho một release-candidate đã có — dùng khi dây chuyền từng kẹt vì lỗi hạ tầng và
    RC nằm lại giữa đường.

    Sự kiện `release-candidates` chỉ được xử lý MỘT lần (`processed`), nên sau khi sửa một lỗi hạ tầng, các RC
    đang kẹt không có đường nào chạy lại: chỉ RC mới mới hưởng bản vá, mà RC mới chỉ sinh ra khi có ticket
    approved chưa nằm trong RC nào. Đo được 2026-09-06 (QLKH): sau khi vá deadlock `gate_release` ở staging,
    18 RC cũ vẫn kẹt vĩnh viễn vì 14/14 ticket đều đã nằm trong một RC hợp lệ — không gì sinh RC mới nữa.

    Người vận hành gọi lệnh này (bus không cho người tự phát `release-candidates`: topic đó của delivery-lead)."""
    from ..orchestrator import StepResult  # nhập lười: orchestrator.py nhập module này trước khi định nghĩa StepResult
    if not by.split(":", 1)[0] == "human": raise ValueError("by phải là human:<tên>")
    rc = o.latest("release-candidates", release_id)
    if rc is None: raise ValueError(f"không có release-candidate {release_id}")
    if release_id in o.void_releases: raise ValueError(f"{release_id}: RC đã bị huỷ, không chạy lại")
    o._audit("release.redeploy", {"release_id": release_id, "by": by}, actor=by,
                project_id=o.project_for(rc))
    res = StepResult(rc.event_id, rc.topic, rc.key)
    o._recall(ROLE.OPS, rc)
    o._call(ROLE.OPS, rc, STAGING_ROUTE, res)  # cùng route như lượt đầu, chỉ khác là do người gọi
    return rc

def recheck(o: Orchestrator, release_id: str, by: str) -> Envelope:
    """Chấm lại release-check của security cho một RC đã có, với bằng chứng máy dựng MỚI (ADR-0047 §5) — dùng
    sau khi bản vá bằng chứng (SBOM/license ADR-0046, DAST ADR-0047) merge. Cùng lý do tồn tại với `redeploy`:
    RC chỉ được xử lý một lần, nên RC cũ bị chặn không có đường nào được chấm lại (CAMPUS-UNI REL-007,
    2026-09-27). Chỉ lượt security; staging là việc của `redeploy`.

    Không đụng quyết định đã có: waiver (`release_waived`) giữ nguyên; review mới thay review cũ trong
    `release_reviews` nên người ký Gate 3 thấy verdict/finding mới. `reviewer:` được gọi như người: chấm lại
    là yêu cầu một lượt model, không phải ký gate."""
    from ..orchestrator import StepResult  # nhập lười: như `redeploy`
    if not by.startswith(("human:", REVIEWER_PREFIX)): raise ValueError("by phải là human:<tên> hoặc reviewer:<id>")
    rc = o.latest("release-candidates", release_id)
    if rc is None: raise ValueError(f"không có release-candidate {release_id}")
    if release_id in o.void_releases: raise ValueError(f"{release_id}: RC đã bị huỷ, không chấm lại")
    if release_id in o.delivered: raise ValueError(f"{release_id}: RC đã giao, chấm lại không đổi được gì")
    if not o.lead.release_needs_security(release_id):
        raise ValueError(f"{release_id}: RC không cần security (không ticket nào có risk_tags)")
    o._audit("release.recheck", {"release_id": release_id, "by": by}, actor=by, project_id=o.project_for(rc))
    res = StepResult(rc.event_id, rc.topic, rc.key)
    o._recall(ROLE.SECURITY, rc)
    o._call(ROLE.SECURITY, rc, RELEASE_CHECK_ROUTE, res)
    return rc

def _check_paused_releases(o: Orchestrator) -> None:
    """Quét mọi RC mà release-event CUỐI là `pending_human` và không gate nào chờ → mở gate escalation. Cần vì
    `_release_paused` chỉ chạy lúc XỬ LÝ event: RC kẹt từ trước bản vá (event đã `processed`) hay orchestrator
    mở lại sau khi gate đã quyết mà lượt chạy lại vẫn dừng — không có sweep thì chúng nằm im mãi như cũ."""
    for rid in list(o.lead.releases):
        if rid in o.void_releases or rid in o.gate.pending: continue
        last = o.latest("release-events", rid)
        if last is None or last.payload.get("status") != "pending_human": continue
        key = f"release.pending_human:{rid}:{last.event_id}"
        if key in o.once: continue
        o._remember(key)
        o._audit("release.pending_human", {"release_id": rid, "env": last.payload.get("env"),
                                              "summary": str(last.payload.get("summary") or "")[:300]},
                    actor=ROLE.OPS, project_id=o.project_for(last))
        request_gate(o.gate, GateRequest(kind="escalation", subject_id=rid, created_by=ROLE.OPS,
                                      checklist=["root_cause", "decision:redeploy|close", "hint"]))

def _superseded_release(o: Orchestrator, rid: str) -> bool:
    """RC chưa giao, nhưng mọi ticket của nó đã ở nhánh tích hợp (hoặc đã xong) và đã có một bản giao SAU nó →
    nội dung RC này đã tới tay khách trong bản giao đó; RC chỉ còn là sổ sách."""
    if rid in o.delivered or rid not in o.lead.release_tickets: return False
    if rid not in o.lead.releases: return False
    tickets = o.lead.release_tickets[rid]
    # RC TRÙNG: mọi ticket của nó đã nằm trong một bản giao KHÁC — trước hay sau đều tính. Bản đầu chỉ xét "có bản
    # giao SAU", nên RC trùng nằm CUỐI danh sách (sinh bởi `flush_releases` cho ticket đã giao) không bao giờ được
    # nhận là trùng: từ chối escalation → `rework_release_tickets` đá ticket đã xong về `changes_requested`.
    # Đo 2026-09-10 (QLKH), `TRAPS.md` "chưa vá" tới 2026-09-22.
    da_giao = {t for d, tids in o.lead.release_tickets.items() if d != rid and d in o.delivered for t in tids}
    if tickets and all(t in da_giao for t in tickets): return True
    later = [d for d in o.delivered if d in o.lead.releases and o.lead.releases.index(d) > o.lead.releases.index(rid)]
    if not later: return False
    return all(t in o.integrated or o.lead.state.get(t) in DONE_STATES for t in tickets)

def _release_paused(o: Orchestrator, env: Envelope, res: StepResult) -> None:
    """release-engineer TỰ DỪNG (`status=pending_human`): xem `_check_paused_releases` — sweep đó chạy ở mọi nhịp
    (kể cả ngay sau lượt vừa phát event này, trước khi event được lấy khỏi hàng đợi), nên ở đây chỉ còn ghi
    hành động để `orchestrated` của event nói rõ gate đã mở."""
    rid = str(env.payload.get("release_id") or env.key)
    o._check_paused_releases()
    if rid in o.gate.pending: res.actions.append(f"gate:escalation:{rid}")

def _recall(o: Orchestrator, agent: str, env: Envelope) -> None:
    """Cho phép gọi LẠI một agent trên cùng event một cách chủ ý. `partial[event_id]` ghi agent đã chạy để event
    bị hoãn transient không chạy lại — nhưng nó cũng nuốt mọi lần gọi lại có chủ đích trên cùng envelope (RC):
    Gate 3 ký lần hai, chạy lại lượt release-engineer vừa tự dừng. Đo được 2026-09-06: lead ký lại Gate 3
    REL-019 lúc 03:06 chỉ chạy được vì orchestrator vừa restart (partial trong RAM trống)."""
    with o._lock:
        # `partial` khoá theo "<agent>:<topic_out>" (ADR-0037 PR-5b, xem `_call`); recall không biết route cụ
        # thể nên bỏ MỌI slot của agent này trên event — đủ để `_call` chạy lại route đang cần, và slot của
        # route khác (nếu có) tự tính lại đúng như cũ khi nó chạy.
        if env.event_id in o.partial:
            o.partial[env.event_id] = {s for s in o.partial[env.event_id] if not s.startswith(f"{agent}:")}

def _rerun_release(o: Orchestrator, rid: str, by: str, reason: str, res: StepResult) -> bool:
    """Chạy lại lượt release-engineer mà nó vừa tự dừng: env lấy từ release-event cuối; production chỉ khi Gate 3
    đã ký. Lý do người duyệt đi vào payload làm `human_hint`. Trả False nếu không có gì để chạy lại."""
    last = o.latest("release-events", rid); rc = o.latest("release-candidates", rid)
    if last is None or rc is None or last.payload.get("status") != "pending_human": return False
    env_ = last.payload.get("env")
    route = STAGING_ROUTE if env_ == "staging" else PROD_ROUTE
    if route is PROD_ROUTE and not o.lead._gate_kind_approved(rid, "release"): return False
    o._audit("release.rerun", {"release_id": rid, "env": env_, "by": by}, actor=by, project_id=o.project_for(rc))
    inp = rc.model_copy(update={"payload": {**rc.payload, "human_hint": reason}}) if reason else rc
    o._recall(ROLE.OPS, rc)
    o._call(ROLE.OPS, inp, route, res)
    return True


# ---------- bảng chuyển giao (K1.7, orch/fsm.py) — dùng bởi Orchestrator.process() ----------
# phase="pre": chạy TRƯỚC vòng lặp ROUTES trong process(); "post": chạy SAU.

def _act_integrate_rc(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    if o._integrate(env, res): return False  # mọi ticket của RC đã ở nhánh tích hợp: đi tiếp bình thường
    o._mark(env, res); return True  # RC huỷ vì xung đột: ticket đã được giao lại, không deploy — dừng ngay


def _act_integrate_approved(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    # Ticket approved lên nhánh tích hợp TRƯỚC khi ticket phụ thuộc (đã được delivery-lead dispatch ngay lúc
    # approve, nên đứng trước review-results trong hàng đợi) tạo worktree.
    o._integrate_approved(res)
    return False


def _act_production_deploy_or_rollback(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    status = env.payload.get("status")
    if status == "deployed":
        o._deliver(env, res)
        o._open_acceptance_gate(env.key, res, env.event_id)
    elif status in {"rolled_back", "failed"}:
        o._rollback_delivery(env, res)
    return False


def _act_release_pending_human(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    o._release_paused(env, res)
    return False


def _act_acceptance_close(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    o._close_acceptance_gate(env, res)
    o._record_lessons(env.payload["release_id"])
    return False


RELEASE_TRANSITIONS: list[Transition] = [
    Transition("integrate_rc", frozenset({"release-candidates"}), _act_integrate_rc, phase="pre"),
    Transition("integrate_approved", frozenset({"tasks", "review-results"}), _act_integrate_approved, phase="pre"),
    Transition("production_deploy_or_rollback", frozenset({"release-events"}), _act_production_deploy_or_rollback,
               guard=lambda env, o: env.payload.get("env") == "production", phase="post"),
    Transition("release_pending_human", frozenset({"release-events"}), _act_release_pending_human,
               guard=lambda env, o: env.payload.get("status") == "pending_human", phase="post"),
    Transition("acceptance_close", frozenset({"acceptance-results"}), _act_acceptance_close, phase="post"),
]
