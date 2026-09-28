"""ADR gốc 0024: người duyệt gate không phải người — actor `reviewer:<id>`, tin theo chữ ký Ed25519.

Một phiên Claude TÁCH RIÊNG (skill `/gate-review`, chỉ đọc hồ sơ `gate_brief`) quyết định, rồi gọi CLI này để ký
và ghi `gate.decide`. Code — không phải lời hứa của phiên — giữ ba ranh giới:

1. **Chữ ký**: tin khi và chỉ khi chữ ký Ed25519 khớp một public key của đúng principal trong registry (ngoài repo,
   khuôn ADR gốc 0020), trên nội dung gồm cả THẾ HỆ gate — chữ ký của gate cũ không dùng lại được cho gate mới.
2. **Phạm vi (S2)**: chỉ `approve` gate `escalation` có checklist `decision:reopen|close` (ticket) hoặc
   `decision:retry|close` (dự án), subject không phải release. Release (`approve` = waive finding), nợ kiến trúc
   (`decision:adr|waive`), spec, reject/close: người.
3. **Trần**: mỗi subject một lần. Lần chặn sau về người — reviewer không bao giờ duyệt lại hint do chính nó viết.

Cờ `COMPANY_GATE_REVIEWER` đọc lại mỗi lần kiểm, như `COMPANY_GATE_AUTOAPPROVE`: tắt = không ký mới, và bản ghi
reviewer không được áp khi replay (gate hiện lại chờ người — hỏng thì đóng).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .bus import REVIEWER_PREFIX
from .events import AuditLog, Envelope
from .gate_risk import AUTOAPPROVE_ACTOR
from .gates import GateRequest
from .product_quality import IssuerKey

if TYPE_CHECKING:
    from .gate_cli import PersistentGate

FLAG_ENV = "COMPANY_GATE_REVIEWER"
SCOPE_ENV = "COMPANY_GATE_REVIEWER_SCOPE"
SCOPE_RONG = "rong"  # ADR gốc 0025: mọi gate trừ `spec`, approve lẫn reject, không trần
REGISTRY_ENV = "COMPANY_GATE_REVIEWER_REGISTRY"
PREFIX = REVIEWER_PREFIX
DEFAULT_REGISTRY = Path.home() / ".config" / "xagents" / "gate-reviewers.json"
DEFAULT_KEY_DIR = Path.home() / ".config" / "xagents" / "gate-reviewer"
SCOPE_CHECKLIST = frozenset({"decision:reopen|close", "decision:retry|close"})
RELEASE_PREFIX = "REL-"  # `DeliveryLead`: release_id = f"REL-{n:03d}"
REASON_PARTS = ("root_cause", "decision", "hint")
_SIGNED = ("subject_id", "decision", "by", "reason", "generation", "brief_sha256", "signed_at", "key_id")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def enabled() -> bool:
    return os.environ.get(FLAG_ENV, "").strip().lower() in {"1", "true", "yes"}


def scope_rong() -> bool:
    """Phạm vi ADR gốc 0025, đọc lại mỗi lần như cờ: bỏ biến là quyết định ngoài S2 thôi được tin khi replay."""
    return os.environ.get(SCOPE_ENV, "").strip().lower() == SCOPE_RONG


def machine_acceptor(actor: str) -> bool:
    """Actor máy được đóng gate nghiệm thu thay khách: sàn ADR-0043 hoặc reviewer (chỉ phạm vi `rong` mới tới được
    gate `acceptance` — `refusal`). Chỉ gọi trên envelope đã qua nhánh tin cậy (scheduler lọc `gate.decide` giả)."""
    return actor == AUTOAPPROVE_ACTOR or actor.startswith(PREFIX)


def registry_path() -> Path:
    return Path(os.environ.get(REGISTRY_ENV) or DEFAULT_REGISTRY)


def _principal(name_or_principal: str) -> str:
    name = name_or_principal.removeprefix(PREFIX)
    if not _NAME.fullmatch(name):
        raise ValueError(f"tên reviewer {name!r} không hợp lệ (chữ thường, số, gạch ngang)")
    return PREFIX + name


def load_registry(path: Path) -> dict[str, tuple[IssuerKey, ...]]:
    """principal → public key. Thiếu file hoặc hỏng ⇒ rỗng (không tin ai), không ném: replay không được sập."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {
            p: tuple(
                IssuerKey.from_pem(k["key_id"], k["public_key_pem"], datetime.fromisoformat(k["not_after"]))
                for k in keys
            )
            for p, keys in raw.items()
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _key_id(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def new_key(principal: str, registry: Path, key_dir: Path, *, days: int = 90, now: datetime | None = None) -> Path:
    """Sinh khoá mới: khoá bí mật vào `key_dir/<tên>.pem`, public key thêm vào `registry`. Trả đường dẫn khoá bí mật."""
    principal = _principal(principal)
    pk = Ed25519PrivateKey.generate()
    key_dir.mkdir(parents=True, exist_ok=True)
    path = key_dir / f"{principal.removeprefix(PREFIX)}.pem"
    path.write_bytes(
        pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    path.chmod(0o600)  # Windows chỉ đổi cờ read-only; trần đã biết ghi ở ADR gốc 0024 (cùng user OS đọc được)
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    pem = (
        pk.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )
    not_after = (now or datetime.now(UTC)) + timedelta(days=days)
    raw.setdefault(principal, []).append(
        {"key_id": _key_id(pk), "public_key_pem": pem, "not_after": not_after.isoformat()}
    )
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path}: không phải khoá Ed25519")
    return key


def generation_of(req: GateRequest) -> str:
    """Thế hệ của gate = mốc `created_at` của CHÍNH envelope `gate.request` (core gán trước khi publish)."""
    return req.created_at.isoformat()


def _message(fields: dict[str, Any]) -> bytes:
    return json.dumps(
        {k: fields[k] for k in _SIGNED}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def sign_decision(
    subject_id: str,
    decision: str,
    principal: str,
    reason: str,
    generation: str,
    brief_sha256: str,
    private_key: Ed25519PrivateKey,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Các trường ký kèm `gate.decide`: thế hệ gate, hash hồ sơ đã đọc, thời điểm ký, key_id, chữ ký."""
    fields = {
        "subject_id": subject_id,
        "decision": decision,
        "by": principal,
        "reason": reason,
        "generation": generation,
        "brief_sha256": brief_sha256,
        "signed_at": (now or datetime.now(UTC)).isoformat(),
        "key_id": _key_id(private_key),
    }
    return {k: fields[k] for k in ("generation", "brief_sha256", "signed_at", "key_id")} | {
        "signature": private_key.sign(_message(fields)).hex()
    }


def refusal(req: GateRequest, history: list[GateRequest], decision: object) -> str:
    """Lý do reviewer KHÔNG được quyết gate này; "" = trong phạm vi. Một chỗ cho cả chiều ghi (CLI) và chiều tin."""
    if scope_rong():  # ADR gốc 0025: chủ dự án giữ lại đúng một quyết định — duyệt spec
        if decision not in {"approve", "reject"}:
            return f"ngoài phạm vi: decision {decision!r} — reviewer chỉ approve/reject"
        return "ngoài phạm vi: spec luôn là của người (ADR gốc 0025)" if req.kind == "spec" else ""
    if decision != "approve":
        return "ngoài phạm vi: reviewer chỉ approve (mở lại/chạy lại); reject/close là của người"
    if (
        req.kind != "escalation"
        or req.subject_id.startswith(RELEASE_PREFIX)
        or not SCOPE_CHECKLIST & set(req.checklist)
    ):
        return (
            f"ngoài phạm vi: {req.kind} {req.subject_id} — reviewer chỉ quyết escalation ticket/dự án "
            "(không release, không nợ kiến trúc, không spec)"
        )
    gen = generation_of(req)
    if any(
        h.subject_id == req.subject_id and (h.decided_by or "").startswith(PREFIX) and generation_of(h) != gen
        for h in history
    ):
        return f"{req.subject_id}: reviewer đã duyệt subject này một lần; lần chặn sau là việc của người"
    return ""


def trusted_reviewer(
    env: Envelope, req: GateRequest | None, history: list[GateRequest], *, now: datetime | None = None
) -> dict[str, Any] | None:
    """Nhánh tin cậy cho `gate.decide` của reviewer; `None` = không tin (gate tiếp tục chờ)."""
    if env.topic != "audit-log" or env.payload.get("action") != "gate.decide" or not env.actor.startswith(PREFIX):
        return None
    if req is None or not enabled():
        return None
    try:
        d = json.loads(env.payload.get("evidence") or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or d.get("by") != env.actor or d.get("subject_id") != req.subject_id:
        return None
    reason = d.get("reason")
    if (
        refusal(req, history, d.get("decision"))
        or d.get("generation") != generation_of(req)
        or not isinstance(reason, str)
        or not all(p in reason for p in REASON_PARTS)
    ):
        return None
    key = next((k for k in load_registry(registry_path()).get(env.actor, ()) if k.key_id == d.get("key_id")), None)
    if key is None:
        return None
    try:
        signed_at = datetime.fromisoformat(str(d.get("signed_at")))
        if not (signed_at < key.not_after and signed_at <= (now or datetime.now(UTC))):
            return None
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(bytes.fromhex(str(d.get("signature"))), _message(d))
    except (ValueError, TypeError, KeyError, InvalidSignature):
        return None
    return d


def decide(
    gate: PersistentGate,
    subject_id: str,
    principal: str,
    reason: str,
    key: Path,
    brief: Path,
    decision: str = "approve",
) -> GateRequest:
    """Ký và ghi quyết định của reviewer (`reject` chỉ trong phạm vi `rong`). Tự kiểm lại bằng chính nhánh tin cậy TRƯỚC khi ghi: ghi một quyết định mà
    orchestrator sẽ không tin thì gate đóng ở tiến trình này mà vẫn chờ ở mọi tiến trình khác."""
    if not principal.startswith(PREFIX):
        raise ValueError(f"actor của reviewer phải mang tiền tố {PREFIX!r} (không ký dưới tên người)")
    principal = _principal(principal)
    if not enabled():
        raise PermissionError(f"{FLAG_ENV} chưa bật — reviewer không được ký")
    if missing := [p for p in REASON_PARTS if p not in reason]:
        raise ValueError(f"lý do thiếu {missing}: cần root_cause/decision/hint")
    req = gate.pending.get(subject_id)
    if req is None:
        raise KeyError(f"{subject_id}: không có gate đang chờ")
    if why := refusal(req, gate.history, decision):
        raise PermissionError(why)
    signed = sign_decision(
        subject_id,
        decision,
        principal,
        reason,
        generation_of(req),
        hashlib.sha256(brief.read_bytes()).hexdigest(),
        load_private_key(key),
    )
    data = {"subject_id": subject_id, "decision": decision, "by": principal, "reason": reason, **signed}
    env = Envelope(
        topic="audit-log",
        key=principal,
        actor=principal,
        payload=AuditLog(
            actor=principal, action="gate.decide", evidence=json.dumps(data, ensure_ascii=False)
        ).model_dump(),
    )
    if trusted_reviewer(env, req, gate.history) is None:
        raise PermissionError(f"chữ ký không qua registry {registry_path()} (khoá lạ, hết hạn, hoặc registry khác)")
    return gate.decide_signed(subject_id, principal, reason, signed, decision)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reviewer gate có chữ ký (ADR gốc 0024)")
    ap.add_argument("--db", type=Path, default=Path("company.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("init-key", help="sinh khoá reviewer, thêm public key vào registry")
    k.add_argument("--id", required=True)
    k.add_argument("--registry", type=Path, default=None)
    k.add_argument("--key-dir", type=Path, default=DEFAULT_KEY_DIR)
    k.add_argument("--days", type=int, default=90)
    d = sub.add_parser("decide", help="quyết một gate trong phạm vi, có chữ ký")
    d.add_argument("subject_id")
    d.add_argument("--decision", choices=("approve", "reject"), default="approve")
    d.add_argument("--id", required=True)
    d.add_argument("--reason", required=True)
    d.add_argument("--key", type=Path, default=None)
    d.add_argument("--brief", type=Path, required=True, help="hồ sơ gate_brief (.json) reviewer đã đọc")
    ns = ap.parse_args(argv)
    if ns.cmd == "init-key":
        path = new_key(ns.id, ns.registry or registry_path(), ns.key_dir, days=ns.days)
        print(f"khoá bí mật: {path}\nregistry: {ns.registry or registry_path()}")
        return 0
    from .gate_cli import PersistentGate  # nhập lười: gate_cli nhập module này cho nhánh tin cậy
    from .sqlite_bus import SQLiteBus, missing_bus

    if loi := missing_bus(ns.db):  # họ B3: quyết gate cần bus ĐÃ CÓ — không để lại bus rỗng ở sai thư mục
        print(loi, file=sys.stderr)
        return 2
    bus = SQLiteBus(ns.db)
    try:
        key = ns.key or DEFAULT_KEY_DIR / f"{_principal(ns.id).removeprefix(PREFIX)}.pem"
        decide(PersistentGate(bus), ns.subject_id, _principal(ns.id), ns.reason, key, ns.brief, ns.decision)
    except (KeyError, PermissionError, ValueError, OSError) as e:
        print(f"từ chối: {e}", file=sys.stderr)
        return 1
    finally:
        bus.close()
    print(f"{ns.subject_id}: {ns.decision} bởi {_principal(ns.id)} (có chữ ký)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
