"""ADR gốc 0024: người duyệt gate không phải người — actor `reviewer:<id>`, tin theo chữ ký Ed25519.

Một phiên Claude TÁCH RIÊNG (skill `/gate-review`, chỉ đọc hồ sơ `gate_brief`) quyết định, rồi gọi CLI này để ký
và ghi `gate.decide`. Code — không phải lời hứa của phiên — giữ ba ranh giới:

1. **Chữ ký**: tin khi và chỉ khi chữ ký Ed25519 khớp một public key của đúng principal trong registry (ngoài repo,
   khuôn ADR gốc 0020), trên nội dung gồm cả THẾ HỆ gate — chữ ký của gate cũ không dùng lại được cho gate mới.
2. **Phạm vi (S2)**: chỉ `approve` gate `escalation` có checklist `decision:reopen|close` (ticket) hoặc
   `decision:retry|close` (dự án), subject không phải release. Release (`approve` = waive finding), nợ kiến trúc
   (`decision:adr|waive`), spec, reject/close: người. Phạm vi `rong` (ADR gốc 0025) nới tới mọi gate trừ spec;
   `toan-bo` (ADR gốc 0033) gồm cả spec.
3. **Trần**: mỗi subject một lần. Lần chặn sau về người — reviewer không bao giờ duyệt lại hint do chính nó viết.

Cờ `COMPANY_GATE_REVIEWER` đọc lại mỗi lần kiểm, như `COMPANY_GATE_AUTOAPPROVE`: tắt = không ký mới, và bản ghi
reviewer không được áp khi replay (gate hiện lại chờ người — hỏng thì đóng).

ADR gốc 0034: `run` là **agent duyệt tự động** (`reviewer:tu-dong`) — tiến trình riêng, không tool, không hội thoại;
đọc hồ sơ `gate_brief`, hỏi model (`gates/reviewer-tu-dong.md`), rồi đi đúng `decide()` ở trên. Không quyết được thì
ghi `reviewer.hold` (một lượt mỗi thế hệ gate) để phiên chính can thiệp — `held()` là thứ `gate_cli list` in ra.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .bus import REVIEWER_PREFIX, is_human
from .events import AuditLog, Envelope
from .gate_risk import AUTOAPPROVE_ACTOR
from .gates import GateRequest
from .product_quality import IssuerKey
from .registry import ROOT, split_front_matter

if TYPE_CHECKING:
    from .gate_cli import PersistentGate

FLAG_ENV = "COMPANY_GATE_REVIEWER"
SCOPE_ENV = "COMPANY_GATE_REVIEWER_SCOPE"
SCOPE_RONG = "rong"  # ADR gốc 0025: mọi gate trừ `spec`, approve lẫn reject, không trần
SCOPE_TOAN_BO = "toan-bo"  # ADR gốc 0033: như `rong` cộng gate `spec`
REGISTRY_ENV = "COMPANY_GATE_REVIEWER_REGISTRY"
PREFIX = REVIEWER_PREFIX
DEFAULT_REGISTRY = Path.home() / ".config" / "xagents" / "gate-reviewers.json"
DEFAULT_KEY_DIR = Path.home() / ".config" / "xagents" / "gate-reviewer"
SCOPE_CHECKLIST = frozenset({"decision:reopen|close", "decision:retry|close"})
RELEASE_PREFIX = "REL-"  # `DeliveryLead`: release_id = f"REL-{n:03d}"
REASON_PARTS = ("root_cause", "decision", "hint")
_SIGNED = ("subject_id", "decision", "by", "reason", "generation", "brief_sha256", "signed_at", "key_id")
# ADR gốc 0034: agent duyệt tự động.
PROMPT_PATH = ROOT / "gates" / "reviewer-tu-dong.md"
HOLD_ACTION = "reviewer.hold"
MAX_PER_TICK_ENV = "COMPANY_GATE_REVIEWER_MAX_PER_TICK"
DECISIONS = ("approve", "reject", "hold")
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"decision": {"type": "string", "enum": list(DECISIONS)}, "root_cause": {"type": "string"},
                   "hint": {"type": "string"}},
    "required": ["decision", "root_cause", "hint"], "additionalProperties": False,
}
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def enabled() -> bool:
    return os.environ.get(FLAG_ENV, "").strip().lower() in {"1", "true", "yes"}


def scope_rong() -> bool:
    """Phạm vi ADR gốc 0025 (hoặc rộng hơn, `toan-bo` của ADR gốc 0033), đọc lại mỗi lần như cờ: bỏ biến là quyết
    định ngoài S2 thôi được tin khi replay."""
    return os.environ.get(SCOPE_ENV, "").strip().lower() in {SCOPE_RONG, SCOPE_TOAN_BO}


def scope_toan_bo() -> bool:
    """ADR gốc 0033: `rong` cộng gate `spec`. Đọc lại mỗi lần, về `rong` là spec reviewer đã duyệt thôi được tin."""
    return os.environ.get(SCOPE_ENV, "").strip().lower() == SCOPE_TOAN_BO


def cr_actor_refusal(actor: str) -> str:
    """ADR gốc 0035: vì sao `actor` KHÔNG được nộp/quyết change request qua CLI; "" = được. Người luôn được; reviewer
    chỉ khi cờ bật và phạm vi `toan-bo` — đọc lại mỗi lần như `refusal()`, một chỗ cho cả chiều ghi và chiều tin."""
    if is_human(actor):
        return ""
    if not actor.startswith(PREFIX):
        return f"phải là người (human:<tên>) hoặc reviewer ({PREFIX}<id>, ADR gốc 0035), không phải {actor!r}"
    if not enabled():
        return f"{FLAG_ENV} chưa bật — reviewer không được nộp/quyết change request (ADR gốc 0035)"
    if not scope_toan_bo():
        return f"{SCOPE_ENV} phải là {SCOPE_TOAN_BO!r} (ADR gốc 0035) — reviewer mới được nộp/quyết change request"
    return ""


def cr_trusted(env: Envelope) -> bool:
    """Chiều tin: change request do `reviewer:*` ghi chỉ được orchestrator áp khi cờ + phạm vi đang bật; actor khác
    (người, ops, delivery-lead) giữ như cũ — ACL bus lúc publish là chốt."""
    return not env.actor.startswith(PREFIX) or cr_actor_refusal(env.actor) == ""


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
    # Đọc registry TRƯỚC khi sinh khoá: chỉ file chưa có mới được tạo mới. File hỏng thì ném lỗi và giữ nguyên —
    # trước đây `except (OSError, ValueError): raw = {}` rồi ghi đè, mọi reviewer đã đăng ký mất im lặng (audit
    # 2026-10-10). `load_registry` lười là để không tin ai khi đọc, không phải để xoá sổ khi ghi.
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except ValueError as e:
        raise ValueError(f"registry {registry} hỏng, không ghi đè: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"registry {registry} hỏng, không ghi đè: không phải object JSON")
    pk = Ed25519PrivateKey.generate()
    key_dir.mkdir(parents=True, exist_ok=True)
    path = key_dir / f"{principal.removeprefix(PREFIX)}.pem"
    path.write_bytes(
        pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    path.chmod(0o600)  # Windows chỉ đổi cờ read-only; trần đã biết ghi ở ADR gốc 0024 (cùng user OS đọc được)
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
    if scope_rong():  # ADR gốc 0025: chủ dự án giữ lại đúng một quyết định — duyệt spec; 0033 (`toan-bo`) trao nốt
        if decision not in {"approve", "reject"}:
            return f"ngoài phạm vi: decision {decision!r} — reviewer chỉ approve/reject"
        if req.kind == "spec" and not scope_toan_bo():
            return "ngoài phạm vi: spec là của người ở phạm vi `rong` (ADR gốc 0025; `toan-bo` là ADR gốc 0033)"
        return ""
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
    env: Envelope, req: GateRequest | None, history: list[GateRequest], *, now: datetime | None = None,
    for_display: bool = False,
) -> dict[str, Any] | None:
    """Xác minh chữ ký reviewer; `for_display` bỏ cờ/phạm vi hiện tại, tuyệt đối không dùng để áp gate."""
    if env.topic != "audit-log" or env.payload.get("action") != "gate.decide" or not env.actor.startswith(PREFIX):
        return None
    if req is None or (not enabled() and not for_display):
        return None
    try:
        d = json.loads(env.payload.get("evidence") or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or d.get("by") != env.actor or d.get("subject_id") != req.subject_id:
        return None
    reason = d.get("reason")
    if (
        (not for_display and refusal(req, history, d.get("decision")))
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


# ---------- ADR gốc 0034: agent duyệt tự động ----------

def load_prompt() -> tuple[int, str]:
    """`(version, thân)` của `gates/reviewer-tu-dong.md` — prompt là code: có version, test cổng kiểm cấu trúc."""
    fm, body = split_front_matter(PROMPT_PATH.read_text(encoding="utf-8"))
    return int(fm.get("version", 0)), body.strip()


def held(gate: PersistentGate) -> dict[str, dict[str, Any]]:
    """Gate đang chờ mà agent duyệt đã GIỮ ở đúng thế hệ này: {subject: evidence của `reviewer.hold`}. Thế hệ khác
    (gate đóng rồi mở lại) không tính — hold cũ không nói gì về gate mới."""
    out: dict[str, dict[str, Any]] = {}
    for env in gate.bus.replay(topic="audit-log"):
        if env.payload.get("action") != HOLD_ACTION or not env.actor.startswith(PREFIX):
            continue
        try:
            d = json.loads(env.payload.get("evidence") or "{}")
        except (ValueError, TypeError):
            continue
        req = gate.pending.get(str(d.get("subject_id")))
        if req is not None and d.get("generation") == generation_of(req):
            out[req.subject_id] = {**d, "by": env.actor}
    return out


def _hold(gate: PersistentGate, req: GateRequest, principal: str, reason: str, usage: dict[str, Any]) -> str:
    data = {"subject_id": req.subject_id, "kind": req.kind, "generation": generation_of(req), "reason": reason[:600],
            **usage}
    gate.bus.publish(Envelope(topic="audit-log", key=principal, actor=principal,
                              payload=AuditLog(actor=principal, action=HOLD_ACTION,
                                               evidence=json.dumps(data, ensure_ascii=False)).model_dump()))
    return "hold"


def review_one(gate: PersistentGate, subject_id: str, brief_md: str, brief_json: Path, client: Any,
               principal: str, key: Path) -> str:
    """Một lượt duyệt cho một gate: hỏi model trên hồ sơ, rồi `approve`/`reject` qua `decide()` (chữ ký, `refusal()`,
    hash hồ sơ) hoặc `hold` (ghi `reviewer.hold`). Trả về quyết định đã ghi. Lỗi model, đầu ra hỏng, ngoài phạm vi đều
    là `hold` kèm lý do — phiên chính đọc lý do đó. Riêng `TransientError` (429 hết phiên, quá tải) thì NÉM lên, không
    ghi gì: hold là vĩnh viễn ở thế hệ gate này, còn lỗi tạm thời tự hết — vòng `run` nghỉ tới mốc reset rồi hỏi lại."""
    from .llm import LLMError, TransientError  # nhập lười: module này được gate_cli nhập, llm nặng

    req = gate.pending[subject_id]
    _, body = load_prompt()
    system = f"{body}\n\nPhạm vi đang bật: {os.environ.get(SCOPE_ENV) or 'S2 (chỉ escalation ticket/dự án, chỉ approve)'}."
    head = f"GATE {subject_id} ({req.kind}); checklist của code: {', '.join(req.checklist)}\n\n"
    # `max_input_chars` là trần cho PHẦN HỒ SƠ (prompt hệ thống tĩnh và nhỏ); hồ sơ dài hơn thì cắt đuôi và nói rõ.
    limit = max(200, int(getattr(client, "max_input_chars", 120_000)) - len(head))
    user = head + (brief_md if len(brief_md) <= limit else brief_md[:limit] + "\n…(hồ sơ bị cắt theo max_input_chars)")
    usage: dict[str, Any] = {}
    try:
        c = client.complete(system=system, user=user, schema=OUTPUT_SCHEMA, model_tier="strong")
        usage = {"tokens": c.input_tokens + c.output_tokens, "model": c.model}
        out = c.json()
    except TransientError:
        raise
    except LLMError as e:
        return _hold(gate, req, principal, f"model lỗi: {e}", usage)
    decision, rc, hint = out.get("decision"), out.get("root_cause"), out.get("hint")
    if decision not in DECISIONS or not isinstance(rc, str) or not isinstance(hint, str):
        return _hold(gate, req, principal, f"đầu ra không hợp lệ: {json.dumps(out, ensure_ascii=False)[:200]}", usage)
    if decision == "hold":
        return _hold(gate, req, principal, f"máy giữ: {rc}" + (f"; hint: {hint}" if hint else ""), usage)
    reason = f"root_cause: {rc}; decision: {decision}; hint: {hint or 'không cần'}"
    try:
        decide(gate, subject_id, principal, reason, key, brief_json, decision)
    except (KeyError, PermissionError, ValueError, OSError) as e:
        return _hold(gate, req, principal, f"code từ chối {decision}: {e}", usage)
    return decision


def _replan_cua(bus: Any, req: GateRequest) -> tuple[str, str] | None:
    """(mã CR, quyết định mới nhất) của lựa chọn `replan:<cid>` trên checklist gate, hoặc None khi gate không có nó."""
    cid = next((c.split(":", 1)[1] for c in req.checklist if c.startswith("replan:")), None)
    if cid is None:
        return None
    last = None
    for e in bus.replay(topic="change-requests", key=cid):
        last = e
    return cid, str(last.payload.get("decision", "pending")) if last is not None else "pending"


def _dong_vi_replan(gate: PersistentGate, sid: str, cid: str, brief_json: Path, principal: str, key: Path) -> str:
    """CR replan đã `accepted`: ticket cũ thay bằng kế hoạch mới — ký `reject` đóng gate (điều `decide-change` dặn
    reviewer), không hỏi model. Code từ chối thì giữ, như `review_one`."""
    reason = (f"root_cause: {cid} đã accepted — ticket thay bằng kế hoạch mới; decision: reject; "
              f"hint: không mở lại {sid}, làm theo ticket của {cid}")
    try:
        decide(gate, sid, principal, reason, key, brief_json, "reject")
    except (KeyError, PermissionError, ValueError, OSError) as e:
        return _hold(gate, gate.pending[sid], principal, f"code từ chối reject theo {cid}: {e}", {})
    return "reject"


def _brief_cua(db: Path, repo: Path | None) -> Any:
    """`brief_fn(orch, sid) -> (md, json_path)` mặc định: dựng hồ sơ thật và ghi ra đĩa như người đọc."""
    from .gate_brief import build, default_out, render_md, write

    def f(orch: Any, sid: str) -> tuple[str, Path]:
        b = build(orch, sid, repo=repo)
        pj, _ = write(b, default_out(db, b))
        return render_md(b), pj
    return f


def run_tick(db: Path, principal: str, key: Path, client: Any, *, repo: Path | None = None,
             brief_fn: Any = None, max_per_tick: int | None = None) -> list[tuple[str, str]]:
    """Một vòng: mọi gate chờ chưa có lượt ở thế hệ này (chưa `hold`, chưa có chữ ký chờ áp) → `review_one`; rồi ở
    phạm vi `toan-bo`, change request máy nộp đã có impact (ADR gốc 0037, `cr_reviewer`). Trần `max_per_tick` lượt một
    vòng, chung cho gate và CR (`COMPANY_GATE_REVIEWER_MAX_PER_TICK`, mặc định 5) — ngân sách là hard stop."""
    from .gate_brief import load_state
    from .gate_cli import PersistentGate
    from .sqlite_bus import SQLiteBus

    cap = max_per_tick if max_per_tick is not None else int(os.environ.get(MAX_PER_TICK_ENV, "5") or 5)
    principal = _principal(principal)
    bus = SQLiteBus(db)
    done: list[tuple[str, str]] = []
    try:
        gate = PersistentGate(bus)
        skip = set(held(gate)) | set(gate.reviewer_signed_pending())
        cr = {sid: d for sid in gate.pending if (d := _replan_cua(bus, gate.pending[sid])) is not None}
        # ADR-0051 + 0037: gate có lựa chọn `replan:<cid>` thì đường CR quyết trước — CR còn chờ thì bỏ qua (duyệt
        # mở lại trước là chạy đua: hub 2026-10-14 DDCSV-35 mở lại 17:33, replan chấp nhận 17:37, việc làm đôi).
        todo = [sid for sid in sorted(gate.pending) if sid not in skip and cr.get(sid, ("", ""))[1] != "pending"][:cap]
        if todo:
            orch = load_state(db, repo=repo) if brief_fn is None else None
            brief = brief_fn or _brief_cua(db, repo)
            for sid in todo:
                md, pj = brief(orch, sid)
                if sid in cr and cr[sid][1] == "accepted":
                    done.append((sid, _dong_vi_replan(gate, sid, cr[sid][0], pj, principal, key)))
                    continue
                done.append((sid, review_one(gate, sid, md, pj, client, principal, key)))
        if scope_toan_bo():
            from . import cr_reviewer
            prompt = f"{load_prompt()[1]}\n\nĐang xét: change request máy nộp (ADR gốc 0037)."
            for cid in cr_reviewer.pending_machine(bus)[:cap - len(done)]:
                done.append((cid, cr_reviewer.review_cr(bus, cid, client, principal, prompt)))
    finally:
        bus.close()
    return done


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
    r = sub.add_parser("run", help="ADR gốc 0034: agent duyệt tự động — đọc hồ sơ, hỏi model, ký; không quyết được thì giữ")
    r.add_argument("--id", required=True)
    r.add_argument("--key", type=Path, default=None)
    r.add_argument("--repo", type=Path, default=None, help="repo khách (hồ sơ đọc worktree/diff)")
    r.add_argument("--watch", type=float, default=None, help="chạy liên tục, mỗi N giây một vòng")
    r.add_argument("--once", action="store_true", help="một vòng rồi thoát")
    sub.add_parser("holds", help="gate đang chờ mà agent duyệt đã giữ (việc của phiên chính)")
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
    if ns.cmd == "holds":
        from .cr_reviewer import held as cr_held
        from .cr_reviewer import pending_machine
        bus = SQLiteBus(ns.db)
        try:
            hs = held(PersistentGate(bus))
            pending_crs = {e.key for e in bus.replay(topic="change-requests")
                           if e.payload.get("decision", "pending") == "pending"} - set(pending_machine(bus))
            hs |= {cid: {**h, "kind": "change-req"} for cid, h in cr_held(bus).items() if cid in pending_crs}
        finally:
            bus.close()
        for sid, h in hs.items():
            print(f"{sid:<12} {h.get('kind', '?'):<10} {h['by']}: {h.get('reason', '')}")
        if not hs:
            print("(agent duyệt không giữ gate nào)")
        return 0
    if ns.cmd == "run":
        from xagents_core.routing import reset_clock_seconds, retry_after_seconds

        from .llm import TransientError, make_client

        key = ns.key or DEFAULT_KEY_DIR / f"{_principal(ns.id).removeprefix(PREFIX)}.pem"
        client = make_client()
        try:
            while True:
                nghi = ns.watch
                try:
                    for sid, out in run_tick(ns.db, ns.id, key, client, repo=ns.repo):
                        print(f"{sid}: {out} bởi {_principal(ns.id)}", flush=True)
                except TransientError as e:
                    # Backend tạm hết (429 hết phiên "resets 6:30pm", quá tải): không giữ gate nào, nghỉ tới mốc của
                    # backend rồi hỏi lại — hỏi mỗi nhịp chỉ tốn thêm một dòng lỗi (hub 2026-10-13).
                    hen = reset_clock_seconds(str(e), time.time()) or retry_after_seconds(str(e)) or 0.0
                    nghi = max(hen, ns.watch or 0.0)
                    print(f"model tạm lỗi, nghỉ {int(nghi)}s: {str(e)[:200]}", flush=True)
                if ns.once or ns.watch is None:
                    return 0
                time.sleep(nghi)
        except KeyboardInterrupt:  # unit systemd dừng bằng SIGINT (cùng khuôn `orchestrator run`): thoát sạch, không traceback
            return 0
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
