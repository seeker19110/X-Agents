"""Human gate CLI: con người duyệt spec / plan / release / escalation; mọi quyết định ghi vào `audit-log`.

Trạng thái gate không lưu riêng: dựng lại từ replay `audit-log` (action gate.request / gate.decide) trên bus bền vững.

    python -m company.gate_cli list [--db company.sqlite]
    python -m company.gate_cli request plan PLAN-1 --by delivery-lead --checklist c4,contract
    python -m company.gate_cli approve PLAN-1 --by human:pm --reason "ok"
    python -m company.gate_cli reject|request_changes|hold|rollback <id> --by <ai> --reason <lý do>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import get_args

from .bus import InMemoryBus
from .events import AuditLog, Envelope
from .gates import Decision, GateKind, GateRequest, HumanGate

DECISIONS: tuple[str, ...] = ("approve", "request_changes", "reject", "hold", "rollback")


class PersistentGate(HumanGate):
    """HumanGate + ghi mọi request/decision lên bus (audit-log) và dựng lại từ replay khi mở."""

    def __init__(self, bus: InMemoryBus, **kw):
        super().__init__(**kw)
        self.bus = bus
        for env in bus.replay(topic="audit-log"):
            self.apply(env)
        bus.subscribe("audit-log", self.apply)  # quyết định từ tiến trình khác (gate CLI) đến qua bus.poll()

    def apply(self, env: Envelope) -> None:
        """Áp một bản ghi gate.request/gate.decide vào trạng thái; idempotent (bỏ qua nếu đã áp)."""
        if env.topic != "audit-log": return
        a = AuditLog.model_validate(env.payload)
        if a.action not in {"gate.request", "gate.decide"}:
            return
        # Bản ghi dị thường (evidence hỏng hoặc thiếu khoá) chỉ bị bỏ qua: một dòng log xấu
        # không được làm sập replay của cả gate — `gate_cli list` và console đều đi qua đây.
        try: d = json.loads(a.evidence or "{}")
        except (ValueError, TypeError): return
        if not isinstance(d, dict): return
        sid = d.get("subject_id")
        if not isinstance(sid, str) or not sid: return
        if a.action == "gate.request":
            if not isinstance(d.get("kind"), str): return
            if sid not in self.pending and not any(r.subject_id == sid and r.created_at == env.ts for r in self.history):
                super().request(GateRequest(kind=d["kind"], subject_id=sid, checklist=d.get("checklist", []),
                                            created_by=d.get("created_by"), created_at=env.ts))
        elif sid in self.pending:
            if not isinstance(d.get("decision"), str) or not isinstance(d.get("by"), str): return
            super().decide(sid, d["decision"], by=d["by"], reason=d.get("reason", ""))

    def _log(self, actor: str, action: str, data: dict) -> None:
        a = AuditLog(actor=actor, action=action, evidence=json.dumps(data, ensure_ascii=False))
        self.bus.publish(Envelope(topic="audit-log", key=actor, actor=actor, payload=a.model_dump()))

    def request(self, req: GateRequest) -> GateRequest:
        r = super().request(req)
        self._log(req.created_by or "human", "gate.request",
                  {"kind": req.kind, "subject_id": req.subject_id, "checklist": req.checklist, "created_by": req.created_by})
        return r

    def decide(self, subject_id: str, decision: Decision, by: str, reason: str = "") -> GateRequest:
        r = super().decide(subject_id, decision, by=by, reason=reason)
        self._log(by, "gate.decide", {"subject_id": subject_id, "decision": decision, "by": by, "reason": reason})
        return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Human gate")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    rq = sub.add_parser("request"); rq.add_argument("kind", choices=get_args(GateKind)); rq.add_argument("subject_id")
    rq.add_argument("--by", required=True); rq.add_argument("--checklist", default="")
    for d in DECISIONS:
        p = sub.add_parser(d); p.add_argument("subject_id"); p.add_argument("--by", required=True); p.add_argument("--reason", default="")
    ns = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")  # Windows console cp1252

    from .sqlite_bus import SQLiteBus
    bus = SQLiteBus(ns.db); gate = PersistentGate(bus)
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
        gate.request(GateRequest(kind=ns.kind, subject_id=ns.subject_id, created_by=ns.by, checklist=items))
        print(f"requested {ns.kind} {ns.subject_id}"); return 0
    try:
        r = gate.decide(ns.subject_id, ns.cmd, by=ns.by, reason=ns.reason)
    except KeyError:
        print(f"không có gate chờ: {ns.subject_id}", file=sys.stderr); return 2
    except PermissionError as e:
        print(str(e), file=sys.stderr); return 3
    print(f"{r.subject_id}: {r.decision} by {r.decided_by}"); return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
