"""Human gate CLI: con người duyệt spec / plan / release / escalation; mọi quyết định ghi vào `audit-log`.

Trạng thái gate không lưu riêng: dựng lại từ replay `audit-log` (action gate.request / gate.decide) trên bus bền vững.

    python -m company.gate_cli list [--db company.sqlite]
    python -m company.gate_cli request plan PLAN-1 --by delivery-lead --checklist c4,contract
    python -m company.gate_cli approve PLAN-1 --by human:pm --reason "ok"
    python -m company.gate_cli reject|request_changes|hold|rollback <id> --by <ai> --reason <lý do>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast, get_args

from xagents_core.bus import is_human
from xagents_core.gate_cli import SYSTEM_GATE_ACTOR as SYSTEM_GATE_ACTOR
from xagents_core.gate_cli import PersistentGate as CorePersistentGate
from xagents_core.gate_cli import trusted_decision as trusted_decision

from . import gate_risk
from .bus import InMemoryBus
from .events import AuditLog, Envelope
from .gate_reviewer import trusted_reviewer
from .gate_risk import AUTOAPPROVE_ACTOR, AUTOAPPROVE_REASON_PREFIX
from .gates import GateKind, GateRequest, HumanGate, gate_approvers, gate_autoapprove_enabled
from .product_quality import LEGACY_SCHEMES, ProjectProfile, allowed_schemes, compile_contract
from .quality_execution import pinned_profile_path
from .quality_floor import BAR_ACTION, PROFILE_ACTION, parse_bar
from .roles import LEAD_ACTOR, LEGACY_GATE_ACTORS, ROLE

DECISIONS: tuple[str, ...] = ("approve", "request_changes", "reject", "hold", "rollback")
SPEC_PREFIX = "SPEC-"  # subject gate spec = SPEC-<project_id> (`orch/ticket_fsm.py`)

# `SYSTEM_GATE_ACTOR` và `trusted_decision` ở `xagents_core.gate_cli` từ K3.7: cùng một allowlist tồn tại hai
# bản ở hai công ty đã phải vá cùng một lỗ hổng hai lần (2026-09-09). Re-export giữ nguyên chỗ nhập của mọi
# nơi gọi (`orch/scheduler.py`, console, test).


def trusted_autoapprove(env: Envelope, kind: str | None = None) -> dict[str, Any] | None:
    """Quyết định `gate.decide` do CODE tự động qua gate rủi ro thấp (ADR-0011 §4 giai đoạn 3,
    `docs/thi-hanh/adr113.md` mục D) — nhánh tin cậy RIÊNG, tách khỏi `trusted_decision` (core, không đổi:
    core không biết `AUTOAPPROVE_ACTOR`/`RISK_RULES` của company, ADR-0001 §2).

    Chỉ tin khi CẢ BỐN: actor đúng `AUTOAPPROVE_ACTOR` ("code"); `reason` mang đúng tiền tố
    `AUTOAPPROVE_REASON_PREFIX` (đánh dấu bản ghi đi qua `gate_risk.request_gate`, không phải actor giả mạo
    tên "code" tự ghi thẳng lên bus); `by` trong evidence cũng là `AUTOAPPROVE_ACTOR` (khớp actor, như
    `trusted_decision` đòi `env.actor == by` cho người); và cờ `COMPANY_GATE_AUTOAPPROVE` đang bật NGAY LÚC
    hàm này chạy — đọc lại mỗi lần `apply()`, không cache: bật/tắt cờ giữa hai lần mở tiến trình không đổi
    bản ghi CŨ trong lịch sử (nó đã `apply` rồi), nhưng bản ghi MỚI luôn theo cờ hiện tại của tiến trình đang
    replay/subscribe."""
    if env.topic != "audit-log" or env.payload.get("action") != "gate.decide": return None
    if env.actor != AUTOAPPROVE_ACTOR or not gate_autoapprove_enabled(): return None
    try: d = json.loads(env.payload.get("evidence") or "{}")
    except (ValueError, TypeError): return None
    if not isinstance(d, dict): return None
    sid = d.get("subject_id")
    if not isinstance(sid, str) or not sid: return None
    if d.get("by") != AUTOAPPROVE_ACTOR: return None
    if not isinstance(d.get("decision"), str): return None
    reason = d.get("reason")
    if not isinstance(reason, str) or not reason.startswith(AUTOAPPROVE_REASON_PREFIX): return None
    # Tên hàng phải khớp một hàng THẬT ĐANG CÓ trong `RISK_RULES` lúc replay này chạy (đọc `gate_risk.RISK_RULES`
    # qua module, không `from .gate_risk import RISK_RULES` — tên import trực tiếp đóng băng giá trị tại thời
    # điểm nhập module, không thấy bảng đổi sau đó, kể cả khi test monkeypatch bảng). Thiếu bước này, một
    # envelope `reason="auto-risk:<tên bịa>"` vẫn được tin nếu chỉ đúng tiền tố — tiền tố là hằng công khai
    # trong mã nguồn, không phải bí mật (sc-security, adr113 2026-09-10).
    rule_name = reason[len(AUTOAPPROVE_REASON_PREFIX):]
    # Hàng gắn `kind` chỉ đóng được gate ĐÚNG loại đó (`kind` = loại của gate đang chờ, do `_trusted` tra): không
    # thì tên `release-quality-floor` đóng được cả gate `spec` (sc-security 2026-09-23; ADR-0043 §4).
    if not any(r.name == rule_name and (r.kind is None or r.kind == kind) for r in gate_risk.RISK_RULES): return None
    return d


def _json_evidence(env: Envelope) -> dict[str, Any]:
    try: d = json.loads(env.payload.get("evidence") or "{}")
    except (ValueError, TypeError): return {}
    return d if isinstance(d, dict) else {}


class PersistentGate(CorePersistentGate[Envelope, AuditLog], HumanGate):
    """HumanGate + ghi mọi request/decision lên bus (audit-log) và dựng lại từ replay khi mở.

    Cơ chế ở core; ở đây chỉ nói core dùng LỚP nào của company (`Envelope`, `AuditLog`, `GateRequest`) — nếu
    không, `replay()` trả về envelope core và mọi kiểm tra `topic: Topic` biến mất."""

    #: Vai được mở gate ở công ty gia công (ADR-0008), đo từ chính các call site `gate.request`:
    #: `product` (gate `spec`, `orch/ticket_fsm.py`), `supervisor` (gate `escalation`, `orch/gates_flow.py`),
    #: `ops` (gate `acceptance` + escalation của `release_fsm`), `delivery-lead` (gate `release`, `delivery.py`).
    #: Người (`human:*`) không cần có tên ở đây — gate CLI là đường của người.
    #: `LEGACY_GATE_ACTORS`: tên trước ADR-0037 còn trong bus cũ — đo trên `company.sqlite` thật, xem `roles.py`.
    REQUEST_ACTORS = frozenset({ROLE.PRODUCT, ROLE.SUPERVISOR, ROLE.OPS, LEAD_ACTOR}) | LEGACY_GATE_ACTORS

    def _trusted(self, env: Envelope) -> dict[str, Any] | None:
        """Điểm mở duy nhất của phép kiểm tin cậy (core): thử đường cũ (người / orchestrator+UAT) trước, rồi
        thử nhánh MỚI của company (`trusted_autoapprove`) — thứ tự này cố ý, không được đảo: `AUTOAPPROVE_ACTOR`
        không phải người và không phải `"orchestrator"` nên không bao giờ khớp đường cũ, nhưng giữ thứ tự rõ
        ràng để đọc code không phải suy luận."""
        if (d := trusted_decision(env, uat_prefix=self.UAT_PREFIX)) is not None:
            return d
        # Loại gate: đang chờ (lúc `apply` replay) hoặc thế hệ mới nhất đã quyết (lúc scheduler hỏi lại SAU khi
        # quyết định đã áp). Không tìm thấy gate nào ⇒ `None` ⇒ hàng có `kind` không khớp ⇒ không tin.
        sid = _json_evidence(env).get("subject_id")
        g = self.pending.get(sid) or next((h for h in reversed(self.history) if h.subject_id == sid), None) \
            if isinstance(sid, str) else None
        # ADR gốc 0024: reviewer có chữ ký — sau cùng, nhánh tự kiểm actor `reviewer:*` nên không khớp nhánh nào ở trên.
        return trusted_autoapprove(env, g.kind if g is not None else None) or trusted_reviewer(env, g, self.history)

    def decide(self, subject_id: str, decision: str, by: str, reason: str = "", actor: str | None = None,
               *, enforce: bool = True) -> GateRequest:
        """`by=AUTOAPPROVE_ACTOR` chỉ hợp lệ khi chính `request_gate` ghi (actor cũng là `"code"`). Người/CLI/console
        ký dưới tên đó thì nhánh "máy nghiệm thu" đóng ticket mà không sàn nào được chấm (sc-security 2026-09-23)."""
        if by == AUTOAPPROVE_ACTOR and actor != AUTOAPPROVE_ACTOR:
            raise PermissionError(f"'{AUTOAPPROVE_ACTOR}' là tên của máy tự duyệt (ADR-0043) — không ký tay dưới tên này")
        # `request_cls=GateRequest` (company) ⇒ phần tử trả về là GateRequest của company; core khai lớp cơ sở.
        return cast(GateRequest, super().decide(subject_id, decision, by=by, reason=reason, actor=actor, enforce=enforce))

    def decide_signed(self, subject_id: str, by: str, reason: str, signed: dict[str, Any],
                      decision: str = "approve") -> GateRequest:
        """Quyết định của reviewer (ADR gốc 0024; `reject` chỉ phạm vi `rong`, ADR gốc 0025): như `decide`, nhưng bản ghi mang các trường chữ ký — đường ghi của
        core chỉ có bốn trường. Chỉ `gate_reviewer.decide` gọi, sau khi đã tự kiểm bằng nhánh tin cậy."""
        r = cast(GateRequest, super(CorePersistentGate, self).decide(subject_id, decision, by=by, reason=reason))
        self._log(by, "gate.decide", {"subject_id": subject_id, "decision": decision, "by": by, "reason": reason,
                                      **signed}, by=by)
        return r

    def __init__(self, bus: InMemoryBus, **kw):
        super().__init__(bus, envelope_cls=Envelope, audit_cls=AuditLog, request_cls=GateRequest, **kw)


def has_quality_profile(bus: InMemoryBus, project_id: str) -> bool:
    """Dự án đã từng được người ghim quality profile chưa (ADR gốc 0021, quyết định 2)."""
    return any(e.payload.get("action") == PROFILE_ACTION and is_human(e.actor)
               and _json_evidence(e).get("project_id") == project_id for e in bus.replay(topic="audit-log"))


def require_profile_for_spec(bus: InMemoryBus, subject_id: str, decision: str, has_profile_arg: bool) -> str | None:
    """Quyết định 2 (ADR gốc 0021), MỘT chỗ cho cả `gate_cli` và console: dự án đã có profile mà ký SPEC không kèm
    profile ⇒ trả lý do từ chối (hỏng thì đóng). None ⇒ được ký. Chỉ lần `approve SPEC-*` cần profile."""
    if decision != "approve" or not subject_id.startswith(SPEC_PREFIX) or has_profile_arg: return None
    if not has_quality_profile(bus, subject_id[len(SPEC_PREFIX):]): return None
    return (f"dự án đã có quality profile: ký {subject_id} phải kèm profile — "
            f"dùng `python -m company.gate_cli approve {subject_id} --quality-profile <file> --by human:<ai>`")


def _pin_profile(db: Path, subject_id: str, path: Path, by: str) -> dict[str, Any]:
    """Kiểm profile TRƯỚC khi ký rồi chép vào kho định danh theo nội dung; trả evidence cho `PROFILE_ACTION`.
    Hỏng ở bất kỳ bước nào ⇒ `ValueError`/`OSError`, spec chưa ký."""
    raw = path.read_bytes()
    profile = ProjectProfile.model_validate_json(raw)
    pid = subject_id[len(SPEC_PREFIX):]
    if profile.project_id != pid:
        raise ValueError(f"profile.project_id={profile.project_id!r} khác dự án {pid!r}")
    if allowed_schemes(profile) == LEGACY_SCHEMES:
        raise ValueError("run mới phải ghim evidence_policy.allowed_schemes (ADR-0020 §3)")
    sha = hashlib.sha256(raw).hexdigest()
    dest = pinned_profile_path(db, pid, sha)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return {"project_id": pid, "run_id": profile.run_id, "profile_sha256": sha,
            "contract_hash": compile_contract(profile)["contract_hash"], "by": by}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Human gate")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    rq = sub.add_parser("request"); rq.add_argument("kind", choices=get_args(GateKind)); rq.add_argument("subject_id")
    rq.add_argument("--by", required=True); rq.add_argument("--checklist", default="")
    for d in DECISIONS:
        p = sub.add_parser(d); p.add_argument("subject_id"); p.add_argument("--by", required=True); p.add_argument("--reason", default="")
        p.add_argument("--quality-bar", default="",
                       help="chỉ với approve SPEC-<dự án>: mức nâng chất lượng k=v[,k=v] (ADR-0043 §2)")
        p.add_argument("--quality-profile", type=Path, default=None,
                       help="chỉ với approve SPEC-<dự án>: ProjectProfile người ký kèm spec (ADR gốc 0021)")
    ns = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")  # Windows console cp1252

    from .sqlite_bus import SQLiteBus, missing_bus
    if ns.cmd != "request" and (loi := missing_bus(ns.db)):  # chỉ `request` được bắt đầu bus mới (audit B3)
        print(loi, file=sys.stderr); return 2
    bus = SQLiteBus(ns.db); gate = PersistentGate(bus, approvers=gate_approvers())
    if ns.cmd == "list":
        remind, overdue = gate.due()
        for sid, r in gate.pending.items():
            flag = " OVERDUE" if sid in overdue else (" remind" if sid in remind else "")
            print(f"{sid:<12} {r.kind:<10} by={r.created_by or '-':<16} checklist={','.join(r.checklist)}{flag}")
        if not gate.pending: print("(không có gate chờ)")
        return 0
    if ns.cmd == "request":
        items = [c.strip() for c in ns.checklist.split(",") if c.strip()]
        if not ns.subject_id.strip():
            print("subject_id không được rỗng", file=sys.stderr); return 2
        if not items:  # gate không có gì để kiểm thì việc duyệt chỉ là bấm nút
            print("cần --checklist (danh sách mục người duyệt phải kiểm, ngăn cách bằng dấu phẩy)", file=sys.stderr)
            return 2
        try:  # `--by` là vai không có quyền mở gate (ADR-0008): báo như mọi lỗi quyền khác, không traceback
            gate.request(GateRequest(kind=ns.kind, subject_id=ns.subject_id, created_by=ns.by, checklist=items))
        except PermissionError as e:
            print(str(e), file=sys.stderr); return 3
        print(f"requested {ns.kind} {ns.subject_id}"); return 0
    # Đường của NGƯỜI (audit 2026-09-27, F-A): `by` không hình người thì bản ghi hoặc bị ACL bus chặn (traceback),
    # hoặc lọt bus (`reviewer:*`, `orchestrator`) rồi bị `_trusted` bỏ ở mọi tiến trình khác — in "approve" mà gate
    # vẫn chờ. Chặn TRƯỚC `_pin_profile` (bước đầu có ghi đĩa); cùng chốt với `keeper gate` (`keeper/cli.py`).
    if not is_human(ns.by):
        print(f"{ns.by} không phải người (`human` / `human:<tên>`) — gate_cli chỉ ghi quyết định của người; reviewer "
              "có chữ ký dùng `python -m company.gate_reviewer decide` (ADR gốc 0024)", file=sys.stderr); return 3
    bar: dict[str, str] | None = None
    if ns.quality_bar:
        # Kiểm TRƯỚC khi ký: mức nâng hỏng thì spec chưa ký — không để một chữ ký spec đi kèm mức nâng không ghi được.
        if ns.cmd != "approve" or not ns.subject_id.startswith(SPEC_PREFIX):
            print(f"--quality-bar chỉ đi cùng approve {SPEC_PREFIX}<dự án>", file=sys.stderr); return 2
        try:
            bar = dict(kv.split("=", 1) for kv in (x.strip() for x in ns.quality_bar.split(",")) if kv)
            parse_bar(bar)
        except ValueError as e:
            print(f"--quality-bar không hợp lệ: {e}", file=sys.stderr); return 2
    pin: dict[str, Any] | None = None
    spec_approve = ns.cmd == "approve" and ns.subject_id.startswith(SPEC_PREFIX)
    if ns.quality_profile is not None:
        if not spec_approve:
            print(f"--quality-profile chỉ đi cùng approve {SPEC_PREFIX}<dự án>", file=sys.stderr); return 2
        try:
            pin = _pin_profile(ns.db, ns.subject_id, ns.quality_profile, ns.by)
        except (OSError, ValueError) as e:
            print(f"--quality-profile không hợp lệ: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr); return 2
    elif (why := require_profile_for_spec(bus, ns.subject_id, ns.cmd, has_profile_arg=False)) is not None:
        # Quyết định 2: không để một lần ký spec mới lọt qua mà không có hợp đồng nghiệm thu (hỏng thì đóng).
        print(why, file=sys.stderr); return 2
    try:
        done = gate.decide(ns.subject_id, ns.cmd, by=ns.by, reason=ns.reason)
    except KeyError:
        print(f"không có gate chờ: {ns.subject_id}", file=sys.stderr); return 2
    except PermissionError as e:
        print(str(e), file=sys.stderr); return 3
    if bar is not None:
        gate._log(ns.by, BAR_ACTION, {"project_id": ns.subject_id[len(SPEC_PREFIX):], "bar": bar, "by": ns.by}, by=ns.by)
    if pin is not None:
        gate._log(ns.by, PROFILE_ACTION, pin, by=ns.by)
    print(f"{done.subject_id}: {done.decision} by {done.decided_by}"); return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
