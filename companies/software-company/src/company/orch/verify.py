"""Smoke/regression/evidence: bằng chứng do CODE chạy, không phải lời khai của model (ADR-0029, tách khỏi
orchestrator.py theo ADR-0034). Mỗi hàm nhận `o: Orchestrator` làm tham số đầu — được gán làm method trên
`Orchestrator` (`_smoke = verify.smoke`, …) nên `self` tự bind qua descriptor của Python, gọi `o._smoke(...)`
trong test cũ không đổi.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import dast, supply_chain
from ..deploy import DeployError, project_name
from ..events import Envelope
from ..gate_risk import request_gate
from ..gates import GateRequest
from ..roles import ROLE
from ..smoke import VERIFIED_BY, parse_runtime, run_smoke, unverified
from ..workspace import Integration
from .guards import _dict_of

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator
    from .routes import Route

# Trạng thái release-events mới của ADR-0039: đã THỬ dựng môi trường chạy và KHÔNG dựng được. Cố ý không gộp vào
# `failed`: `failed` (ADR-0029) trả ticket của RC về `changes_requested` vì sản phẩm hỏng, còn `deploy_failed` nói
# "chưa deploy được" — có thể là hạ tầng máy trực, không phải code — nên ticket nằm yên chờ người quyết ở gate
# escalation. Phân biệt được hai thứ đó chính là điều REL-019 thiếu (ADR-0039 "Bối cảnh").
DEPLOY_FAILED = "deploy_failed"


def release_evidence(o: Orchestrator, rid: str) -> dict[str, Any]:
    staging = next((e for e in reversed(list(o.bus.replay(topic="release-events", key=rid)))
                    if e.payload.get("env") == "staging"), None)
    reviews = {s: {"verdict": x.verdict, "findings": len(x.findings)} for s, x in o.lead.release_reviews.get(rid, {}).items()}
    gate = next((g for g in reversed(o.gate.history) if g.subject_id == rid and g.kind == "release"), None)
    return {"staging": ({"status": staging.payload.get("status"), "version": staging.payload.get("version"),
                         "at": staging.ts.isoformat(timespec="seconds"),
                         "smoke": staging.payload.get("smoke")} if staging is not None else None),
            "reviews": reviews, "waived": sorted(o.lead.release_waived.get(rid, set())),
            "gate_release_by": (gate.decided_by if gate is not None else None),
            "gate_release_reason": ((gate.reason or "")[:300] if gate is not None else None),
            "delivered_sha": o.release_sha.get(rid)}


def _du_an_legacy(o: Orchestrator, pid: str | None) -> bool:
    """Cờ `legacy: true` trong `research-requests.payload` — người mở dự án tự khai "dự án này có TRƯỚC ADR-0031,
    đừng đòi nó khai `runtime`". Khai một lần lúc mở dự án, không phải cờ mà agent tự bật giữa chừng: nó nằm ở
    topic của con người (`research-requests`), không nằm ở spec do model viết."""
    if pid is None: return False
    rr = o.latest("research-requests", pid)
    return rr is not None and rr.payload.get("legacy") is True


def smoke(o: Orchestrator, agent: str, rc: Envelope, rid: str, p: dict[str, Any], integ: Integration | None) -> dict[str, Any]:
    """`status=deployed` ở staging là LỜI KHAI của release-engineer (nó không có tool deploy). ADR-0029: orchestrator
    tự khởi động sản phẩm theo `runtime` của spec trong worktree tích hợp và gọi một request thật; kết quả vào
    `payload.smoke` (`verified_by=orchestrator`). Có `runtime` mà khởi động không được / không trả lời đúng →
    status thành `failed`: bốn gate xanh không được phép che một sản phẩm không chạy (đo được 2026-09-06 QLKH:
    25 release, 0 điểm vào).

    Không smoke được (thiếu `runtime`, thiếu worktree) thì tuỳ LOẠI sản phẩm (K1.5 kịch bản B):
    `library`/`docs` — hoặc dự án khai `legacy: true` — vẫn đi tiếp, bằng chứng nói rõ là chưa kiểm; còn
    `kind=application` (mặc định khi spec thiếu `kind`) thì `unverified` là **failed**, đi đúng đường của smoke
    fail. ADR-0031 đã chặn ở gate spec: spec ứng dụng thiếu `runtime` không được mở Gate 1. Đây là lớp SAU —
    dự án được duyệt trước ADR-0031, hay `integ` biến mất giữa chừng, vẫn tới được đây; và "không kiểm được"
    của một sản phẩm-phải-chạy-được không phải là một trạng thái trung lập để đi tiếp."""
    pid = o.project_for(rc)
    spec = o.latest("approved-specs", pid) if pid else None
    kind = (spec.payload.get("kind") if spec is not None else None) or "application"
    rt = parse_runtime(spec.payload if spec is not None else None)
    if rt is None or integ is None or not integ.path.exists():
        # Hai nguyên nhân, MỘT chỗ quyết: tách ra hai nhánh song song thì sớm muộn chúng xử lý khác nhau.
        smoke = unverified("spec không khai `runtime` (lệnh khởi động, cổng, đường health)" if rt is None
                           else "không có worktree tích hợp (dự án chạy không repo)")
        o._audit("release.smoke_unverified", {"release_id": rid, "reason": smoke["reason"], "spec_kind": kind},
                    project_id=pid, once=f"smoke.unverified:{rid}:{rc.event_id}")
        if kind != "application" or _du_an_legacy(o, pid):
            return {**p, "smoke": smoke}
        o._audit("release.smoke_blocked", {"release_id": rid, "claimed_status": p.get("status"),
                                              "spec_kind": kind, "reason": smoke["reason"]}, project_id=pid)
        if rid not in o.gate.pending:   # cùng đường với smoke fail bên dưới: RC failed không có route nào tiếp
            request_gate(o.gate, GateRequest(kind="escalation", subject_id=rid, created_by=ROLE.OPS,
                                          checklist=["root_cause", "decision:redeploy|close", "hint"]))
        return {**p, "status": "failed", "smoke": smoke}
    if rt.deploy:
        # ADR-0041: `runtime.command` chạy TRẦN bằng subprocess của chính orchestrator — không hợp với app cần
        # cài dependency riêng (venv/bắc cầu WSL) trước khi chạy được, đo thật trên QLKH: mọi lệnh đều fail cùng
        # lý do bất kể nội dung. Spec đã khai `runtime.deploy` (ADR-0039/0040) thì bằng chứng thật đến từ
        # `deploy_release()` chạy NGAY SAU (nó tự cài đặt trước khi start) — không chạy smoke trần chồng lấn,
        # không mở gate ở đây (mở cả hai bước là hỏi người hai lần cho cùng một lượt).
        smoke = unverified("runtime.deploy đã khai (ADR-0039/0040) — bằng chứng thật do deploy() cung cấp, "
                           "không chạy smoke trần")
        o._audit("release.smoke_unverified", {"release_id": rid, "reason": smoke["reason"], "spec_kind": kind},
                    project_id=pid, once=f"smoke.unverified:{rid}:{rc.event_id}")
        return {**p, "smoke": smoke}
    smoke = run_smoke(integ.path, rt, sandbox=o.sandbox)
    o._audit("release.smoke", {"release_id": rid, **smoke}, actor=agent, project_id=pid)
    if smoke.get("ok"):
        return {**p, "smoke": smoke}
    o._audit("release.smoke_failed", {"release_id": rid, "claimed_status": p.get("status"),
                                         "http_status": smoke.get("http_status"), "exit_code": smoke.get("exit_code"),
                                         "error": smoke.get("error")}, project_id=pid)
    # RC `failed` ở staging không có route nào tiếp: không mở gate thì nó nằm im như `pending_human` từng nằm.
    if rid not in o.gate.pending:
        request_gate(o.gate, GateRequest(kind="escalation", subject_id=rid, created_by=ROLE.OPS,
                                      checklist=["root_cause", "decision:redeploy|close", "hint"]))
    return {**p, "status": "failed", "smoke": smoke}


def _escalate(o: Orchestrator, rid: str) -> None:
    """RC không đi tiếp được thì phải có người được hỏi — cùng đường với smoke fail ở trên: không mở gate thì RC
    nằm im đúng như `pending_human` từng nằm im (TRAPS §"RC `pending_human`/`failed` không có route tiếp")."""
    if rid not in o.gate.pending:
        request_gate(o.gate, GateRequest(kind="escalation", subject_id=rid, created_by=ROLE.OPS,
                                      checklist=["root_cause", "decision:redeploy|close", "hint"]))


def _release_root(o: Orchestrator, rid: str, integ: Integration) -> Path:
    """Thư mục chứa ĐÚNG thứ đã staged cho `rid`: `release_sha[rid]` (thứ QA hồi quy, người ký Gate 3 và `deliver`
    gắn tag). Đầu nhánh tích hợp thì KHÔNG: `integrate_approved` merge ngay mọi ticket vừa approved, nên sau staging
    nó có thể chứa code chưa qua staging/QA/Gate 3 (audit 2026-09-23). Chưa staged (không có sha) → worktree
    tích hợp như cũ."""
    sha = o.release_sha.get(rid)
    return integ.checkout_at(sha) if sha else integ.path


def deploy_release(o: Orchestrator, agent: str, rc: Envelope, rid: str, p: dict[str, Any],
                   integ: Integration | None, target_env: str) -> dict[str, Any]:
    """ADR-0039: `deployed` là **container đang chạy**, không phải lời khai. `p["status"] == "deployed"` lúc vào đây
    chỉ là yêu cầu đi tiếp của agent `ops`; orchestrator tự dựng compose file của khách rồi TỰ kết luận:

    - đủ ba phần (`up -d` thoát 0 + mọi service `running` + smoke vào cổng đã map) → giữ `deployed`, kèm
      `evidence.deploy` có `container_ids`/`port`/`started_at`/`smoke`/`verified_by=orchestrator`;
    - thiếu bất kỳ phần nào → `status=deploy_failed`, evidence ghi phần nào hỏng + `logs_tail` (`deploy()` đã tự
      `down` — không gọi `down` lần hai ở đây), và mở gate escalation;
    - `skipped` (chưa bật `COMPANY_DEPLOY`, không có compose file, spec không khai `runtime`, không có worktree) →
      **giữ nguyên hành vi cũ**, chỉ ghi lý do vào evidence. Đây là đường lùi để repo đang chạy không gãy —
      `skipped` KHÔNG phải thành công, nhưng cũng không phải bằng chứng hỏng.

    `env` là của ROUTE (`STAGING_ROUTE`/`PROD_ROUTE`), không phải `payload.env` của model: `_release` đã ghi đè
    lời khai trước khi gọi hàm này, và `deploy()` từ chối env ngoài `staging|production`. Production vẫn CHỈ tới
    được đây qua `PROD_ROUTE` sau Gate 3 — ADR-0039 quyết định 5 không thêm cổng nào.
    """
    pid = o.project_for(rc)
    spec = o.latest("approved-specs", pid) if pid else None
    rt = parse_runtime(spec.payload if spec is not None else None)
    ev = _dict_of(p.get("evidence"))
    # Bản ghi tối thiểu khi CHƯA gọi được `deploy()`: hình dạng phải giống `DeployRecord.record()` để chỗ đọc
    # (console, gate_brief, người trực) chỉ phải biết MỘT hình.
    d = {"project": project_name(pid or rid, target_env), "env": target_env, "ok": False, "verified_by": VERIFIED_BY}
    detail = None   # None = chưa hỏng; dict = hỏng, và đây là phần ghi vào audit
    if rt is None:
        d["skipped"] = "spec không khai `runtime` (không biết dựng gì, probe đường nào)"
    elif integ is None or not integ.path.exists():
        d["skipped"] = "không có worktree tích hợp (dự án chạy không repo)"
    else:
        try:
            rec = o.deploy_fn(_release_root(o, rid, integ), pid or rid, target_env, rt)
        except DeployError as e:
            # Fail-closed của ADR-0039 quyết định 4 (`COMPANY_DEPLOY=compose` mà thiếu binary): người vận hành
            # khai đích danh nên đây là LỖI, không phải "coi như xong" — nhưng nó không được giết orchestrator.
            d["error"] = str(e)[:300]
            detail = {"error": d["error"]}
        else:
            d = rec.record()
            if o.release_sha.get(rid):  # `_release_root` đã chạy trên đúng sha này (ADR-0043: sàn đối chiếu sha)
                d["sha"] = o.release_sha[rid]
            if not rec.ok and not rec.skipped:
                detail = {"error": rec.error, "services": list(rec.services), "logs_tail": rec.logs_tail[-600:]}
    if detail is not None:
        o._audit("release.deploy_failed", {"release_id": rid, "env": target_env,
                                              "claimed_status": p.get("status"), **detail}, project_id=pid)
        _escalate(o, rid)
        return {**p, "status": DEPLOY_FAILED, "evidence": {**ev, "deploy": d}}
    if d.get("skipped"):
        o._audit("release.deploy_skipped", {"release_id": rid, "env": target_env, "reason": d["skipped"]},
                    project_id=pid, once=f"deploy.skipped:{rid}:{rc.event_id}:{target_env}")
    else:
        o._audit("release.deploy", {"release_id": rid, **d}, actor=agent, project_id=pid)
    return {**p, "evidence": {**ev, "deploy": d}}


def regression_run(o: Orchestrator, env: Envelope) -> dict[str, Any]:
    """ADR-0029 mục "regression-staging": trước lượt QA hồi quy, orchestrator TỰ khởi động sản phẩm theo `runtime`
    của spec trên worktree tích hợp (đúng sha RC đã staged) và gọi một request thật. Kết quả (lệnh, mã thoát, mã
    HTTP, `verified_by=orchestrator`) là `evidence.run` — bằng chứng của máy, đưa vào input để QA dẫn và đối chiếu
    với verdict sau lượt (`_verdict_with_run`). Không có `runtime`/worktree → `unverified` kèm lý do và `spec_kind`:
    spec khai `kind=application` mà không có `runtime` thì đó là lỗi của spec, không phải "chưa kiểm".
    Bằng chứng sống trong payload `review-results` trên bus, không giữ trong RAM; khoá `once` mang event_id của
    lượt deployed nên RC redeploy (lần hợp lệ thứ hai) vẫn được ghi lại."""
    rid = str(env.payload.get("release_id") or env.key)
    pid = o.project_for(env)
    spec = o.latest("approved-specs", pid) if pid else None
    kind = (spec.payload.get("kind") if spec is not None else None) or None
    rt = parse_runtime(spec.payload if spec is not None else None)
    integ = o._integration_of_release(env)
    if rt is None:
        run = {**unverified("spec không khai `runtime` (lệnh khởi động, cổng, đường health)"), "spec_kind": kind}
    elif integ is None or not integ.path.exists():
        run = {**unverified("không có worktree tích hợp (dự án chạy không repo)"), "spec_kind": kind}
    elif rt.deploy:
        # ADR-0041: cùng lý do với `smoke()` — `runtime.command` chạy trần không hợp với app cần cài dependency
        # riêng; spec đã khai `runtime.deploy` thì bằng chứng thật đến từ `deploy_release()`, không phải hồi quy
        # smoke trần ở đây. `deploy_declared=True` để `verdict_with_run` không hạ verdict QA xuống `fail` vì lý
        # do không liên quan tới chất lượng PR.
        run = {**unverified("runtime.deploy đã khai (ADR-0039/0040) — bằng chứng thật do deploy() cung cấp, "
                           "không chạy smoke trần"), "spec_kind": kind, "deploy_declared": True}
    else:
        run = {**run_smoke(_release_root(o, rid, integ), rt, sandbox=o.sandbox), "sha": o.release_sha.get(rid) or integ.sha(),
               "spec_kind": kind}
        o._audit("regression.run", {"release_id": rid, **run}, project_id=pid)
        return run
    o._audit("regression.run_unverified", {"release_id": rid, "reason": run["reason"], "spec_kind": kind},
                project_id=pid, once=f"regression.unverified:{rid}:{env.event_id}")
    return run


def verdict_with_run(o: Orchestrator, agent: str, env: Envelope, p: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Gắn `evidence.run` do orchestrator chạy vào verdict QA (ghi đè mọi `evidence.run` model tự khai) và đối chiếu:
    smoke fail → verdict `fail`; `unverified` với spec `kind=application` → `fail` (spec phải khai `runtime`);
    `unverified` với kind khác (library, hoặc chưa khai) → giữ verdict, bằng chứng nói thẳng là chưa kiểm.
    Ba kết cục, không có kết cục thứ tư — như `_smoke` với `deployed`."""
    rid = str(env.payload.get("release_id") or env.key)
    pid = o.project_for(env)
    ev = _dict_of(p.get("evidence"))
    if "run" in ev:  # model tự khai `evidence.run`: bỏ, ghi lại — bằng chứng chạy chỉ có một nguồn là orchestrator
        o._audit("regression.run_claimed_ignored", {"release_id": rid, "claimed": ev.get("run")}, actor=agent, project_id=pid)
    p = {**p, "evidence": {**ev, "run": run}}
    if run.get("ok"):
        return p
    if run.get("unverified"):
        if run.get("spec_kind") != "application" or run.get("deploy_declared"):
            return p
        reason = f"spec khai kind=application nhưng không smoke được: {run.get('reason')} — RC không đi tiếp cho tới khi spec khai `runtime`"
    else:
        reason = (f"smoke do orchestrator chạy trên worktree RC không đạt: http_status={run.get('http_status')} "
                  f"exit_code={run.get('exit_code')} error={run.get('error')} — lệnh {run.get('command')}")
    o._audit("regression.run_failed", {"release_id": rid, "claimed_verdict": p.get("verdict"), "reason": reason},
                project_id=pid)
    if p.get("verdict") == "pass":
        o._audit("regression.verdict_overridden", {"release_id": rid, "claimed": "pass", "verdict": "fail", "reason": reason},
                    actor=agent, project_id=pid)
        p = {**p, "verdict": "fail", "root_cause": p.get("root_cause") or reason,
             "findings": [*(p.get("findings") or []), {"level": "block", "location": run.get("url"), "text": reason}]}
    return p


def evidence_before(o: Orchestrator, r: Route, inp: Envelope) -> tuple[Envelope, str | None]:
    """Bằng chứng do ORCHESTRATOR chạy trước lượt chấm, đưa vào input để agent dẫn — không phải lời khai của model:
    smoke trước QA hồi quy (ADR-0029 mục "regression-staging"), SBOM + license + DAST tối thiểu trước release-check
    của security (ADR-0046/0047: `release-candidates` không mang gì, security được dặn không đoán nên trước đây chặn
    mọi RC — CAMPUS-UNI REL-004, REL-007). Trả input mới và tên bằng chứng để `evidence_after` đối chiếu đúng thứ
    đã đưa (`supply_chain` là cặp supply_chain + dast của release-check)."""
    if r.topic_out != "review-results" or inp.topic not in {"release-events", "release-candidates"}: return inp, None
    if inp.topic == "release-events":
        if r.tools != "ro": return inp, None
        kind, ev = "run", {"run": regression_run(o, inp)}
    else:
        rid, pid = str(inp.payload.get("release_id") or inp.key), o.project_for(inp)
        integ = o._integration_of_release(inp)
        if integ is None or not integ.path.exists():
            ev = dict.fromkeys(("supply_chain", "dast"), unverified("không có worktree tích hợp (dự án chạy không repo)"))
        else:
            root, sha = _release_root(o, rid, integ), o.release_sha.get(rid) or integ.sha()
            spec = o.latest("approved-specs", pid) if pid else None
            ev = {"supply_chain": supply_chain.evidence(root, o.sandbox, sha=sha),
                  "dast": dast.evidence(root, spec.payload if spec is not None else None, o.sandbox,
                                        o.blackboard.content("api-contract", pid), sha)}
        # audit không kèm toàn văn SBOM / checks: chúng đi trong `review-results`
        for action, ev1, big in (("supply_chain.run", ev["supply_chain"], "sbom"), ("dast.run", ev["dast"], "checks")):
            o._audit(action, {"release_id": rid, **{k: v for k, v in ev1.items() if k != big}}, project_id=pid)
        kind = "supply_chain"
    return inp.model_copy(update={"payload": {**inp.payload, "evidence": {**_dict_of(inp.payload.get("evidence")), **ev}}}), kind


def evidence_after(o: Orchestrator, agent: str, inp: Envelope, p: dict[str, Any], kind: str | None) -> dict[str, Any]:
    """Sau lượt: bằng chứng của orchestrator ghi đè mọi bản model tự khai. Smoke hỏng hạ verdict (`verdict_with_run`);
    SBOM và DAST thì KHÔNG (ADR-0046 §3, ADR-0047 §3) — license hợp lệ hay thiếu CSP có chặn không là chính sách
    của dự án, máy chỉ đưa số. `dast_summary` là lời đọc của model, giữ nguyên."""
    if kind is None: return p
    mine = _dict_of(inp.payload.get("evidence"))
    ev = mine[kind]
    if kind == "run": return verdict_with_run(o, agent, inp, p, ev)
    ev_p = _dict_of(p.get("evidence"))
    claimed = {k: v for k, v in (("supply_chain", ev_p.get("supply_chain")), ("sbom_ref", p.get("sbom_ref"))) if v is not None}
    rid = str(inp.payload.get("release_id") or inp.key)
    for action, c in (("supply_chain.claimed_ignored", claimed or None), ("dast.claimed_ignored", ev_p.get("dast"))):
        if c is not None:
            o._audit(action, {"release_id": rid, "claimed": c}, actor=agent, project_id=o.project_for(inp))
    return {**p, "evidence": {**ev_p, "supply_chain": ev, "dast": mine["dast"]}, "sbom_ref": ev.get("sbom_ref")}
