"""ADR-0063: gate ký văn bản khách — reviewer ký số một văn bản của khách bằng gate có chữ ký, rồi xuất đúng byte đã ký.

`request`: reviewer (cờ bật, phạm vi `toan-bo`) xin; coordinator mở gate escalation mang dấu `ky:<principal>` và
`brief:<sha256>` — four-eyes giữ nguyên (người mở khác người ký), audit `sign.requested` ghi đúng ai xin. Ký bằng
`gate_reviewer decide` như mọi gate: dấu chặn sai người, sai hồ sơ ở cả chiều ghi lẫn chiều tin (`sign_marks`).
`export`: bản ghi `gate.decide` đáng tin mới nhất → phong bì `{record, signatures}` và khoá công khai base64 32 byte,
định dạng repo khách đọc. Private key không rời máy hub.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import gate_reviewer as gr
from .events import AuditLog, Envelope
from .gates import GateRequest
from .roles import LEAD_ACTOR

if TYPE_CHECKING:
    from .gate_cli import PersistentGate

REQUESTED = "sign.requested"
DECIDED = "sign.decided"
RESERVED = ("REL-", "SPEC-", "UAT-")  # RC, spec, nghiệm thu: subject của các nhánh orchestrator khác
_SUBJECT = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+")


def signer_of(req: GateRequest) -> str | None:
    return m[0] if (m := gr.sign_marks(req)) else None


def brief_of(req: GateRequest) -> str | None:
    return m[1] if (m := gr.sign_marks(req)) else None


def request(gate: PersistentGate, subject: str, by: str, brief: Path) -> GateRequest:
    """Mở gate ký `subject` cho đúng `by`, trên đúng byte của `brief`."""
    if not by.startswith(gr.PREFIX):
        raise PermissionError(f"người ký phải là reviewer ({gr.PREFIX}<id>), không phải {by!r}")
    by = gr._principal(by)
    if why := gr.cr_actor_refusal(by):
        raise PermissionError(why)
    if not _SUBJECT.fullmatch(subject) or subject.startswith(RESERVED):
        raise ValueError(f"{subject!r}: subject phải là mã viết hoa có gạch nối, không phải {'/'.join(RESERVED)}*")
    if subject in gate.pending:
        raise ValueError(f"{subject}: đã có gate đang chờ")
    if any(h.subject_id == subject and not gr.sign_marks(h) for h in gate.history):
        raise ValueError(f"{subject}: trùng subject của một gate không phải gate ký")
    sha = hashlib.sha256(brief.read_bytes()).hexdigest()
    checklist = ["root_cause", "decision:approve|reject", "hint", f"{gr.SIGN_MARK}{by}", f"{gr.BRIEF_MARK}{sha}"]
    req = GateRequest(kind="escalation", subject_id=subject, created_by=LEAD_ACTOR, checklist=checklist)
    gate.request(req)
    ev = {"subject_id": subject, "by": by, "brief_sha256": sha, "brief": str(brief)}
    gate.bus.publish(
        Envelope(
            topic="audit-log",
            key=by,
            actor=by,
            payload=AuditLog(actor=by, action=REQUESTED, evidence=json.dumps(ev, ensure_ascii=False)).model_dump(),
        )
    )
    return req


def trusted_record(bus: Any, gate: PersistentGate, subject: str) -> dict[str, Any] | None:
    """Bản ghi `gate.decide` mới nhất của gate ký `subject` mà nhánh tin cậy chấp nhận."""
    gates = {gr.generation_of(h): h for h in gate.history if h.subject_id == subject and gr.sign_marks(h)}
    out = None
    for env in bus.replay(topic="audit-log"):
        try:
            gen = json.loads(env.payload.get("evidence") or "{}").get("generation")
        except (ValueError, TypeError, AttributeError):
            continue
        if (req := gates.get(gen)) is not None and (d := gr.trusted_reviewer(env, req, gate.history)) is not None:
            out = d
    return out


def export(bus: Any, gate: PersistentGate, subject: str, signature: Path, keys: Path) -> tuple[Path, Path]:
    """Ghi phong bì chữ ký và `<key_id>.pub`; không có bản ghi đáng tin thì không ghi gì (`LookupError`)."""
    d = trusted_record(bus, gate, subject)
    if d is None:
        raise LookupError(f"{subject}: không có bản ghi gate.decide đáng tin của gate ký")
    key = next(k for k in gr.load_registry(gr.registry_path())[d["by"]] if k.key_id == d["key_id"])
    env = {
        "record": base64.b64encode(gr._message(d)).decode("ascii"),
        "signatures": [
            {"key_id": d["key_id"], "signature": base64.b64encode(bytes.fromhex(d["signature"])).decode("ascii")}
        ],
    }
    signature.parent.mkdir(parents=True, exist_ok=True)
    keys.mkdir(parents=True, exist_ok=True)
    signature.write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    (keys / f"{d['key_id']}.pub").write_text(base64.b64encode(key.public_key).decode("ascii") + "\n", encoding="ascii")
    return signature, keys


def main(argv: list[str] | None = None) -> int:
    from .gate_cli import PersistentGate
    from .sqlite_bus import SQLiteBus

    ap = argparse.ArgumentParser(description="Gate ký văn bản khách (ADR-0063)")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    rq = sub.add_parser("request")
    rq.add_argument("subject")
    rq.add_argument("--by", required=True)
    rq.add_argument("--brief", type=Path, required=True)
    ex = sub.add_parser("export")
    ex.add_argument("subject")
    ex.add_argument("--signature", type=Path, required=True)
    ex.add_argument("--keys", type=Path, required=True)
    ns = ap.parse_args(argv)
    bus = SQLiteBus(ns.db)
    try:
        gate = PersistentGate(bus)
        if ns.cmd == "request":
            try:
                req = request(gate, ns.subject, ns.by, ns.brief)
            except (ValueError, PermissionError, OSError) as e:
                print(f"từ chối: {e}", file=sys.stderr)
                return 2
            print(f"{ns.subject}: gate ký đã mở, chờ {signer_of(req)} ký hồ sơ sha256 {brief_of(req)}")
            return 0
        try:
            sig, keys = export(bus, gate, ns.subject, ns.signature, ns.keys)
        except LookupError as e:
            print(f"từ chối: {e}", file=sys.stderr)
            return 1
        print(f"{ns.subject}: đã xuất {sig} và khoá công khai vào {keys}")
        return 0
    finally:
        bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
