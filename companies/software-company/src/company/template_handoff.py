"""Offline, opt-in bridge to projects-template; preparation is NOT approval.

The native DeliveryContract and adopted_source remain authoritative. No commands,
network requests, journal transitions, file writes or new permissions occur here.
A coordinator pins the bundle separately, then uses the returned contract in its
normal profile/ApprovalLookup/authenticated-evidence pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from .delivery_contract import DeliveryContract, adopted_source, artifact_matches

PROTOCOL = "xagents-template-handoff/1"
MAX_DOCUMENT_BYTES = 1024 * 1024


def canonical(value: Any) -> bytes:
    """Deterministic ASCII JSON (also valid UTF-8), not a signature or RFC 8785 JCS."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def policy_document() -> dict[str, Any]:
    """Export the real consumer schema; producers must not vendor a second copy."""
    return {"protocol": PROTOCOL, "source": adopted_source(),
            "delivery_schema": DeliveryContract.model_json_schema(), "max_spec_bytes": MAX_DOCUMENT_BYTES}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ValueError("nonfinite JSON number")


def _bounded_values(result: Any) -> None:
    pending = [(result, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 64:
            raise ValueError("handoff document is too deeply nested")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)


def _document(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("handoff document is too large")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except RecursionError as error:
        raise ValueError("handoff document is too deeply nested") from error
    _bounded_values(result)
    if not isinstance(result, dict):
        raise ValueError("handoff must be a JSON object")
    return result


def prepare_handoff(
    raw: bytes,
    *,
    expected_sha256: str,
    acceptance_ids: set[str],
    evidence_root: Path,
) -> DeliveryContract:
    """Return a native contract, never a Ready/Done verdict.

    expected_sha256 and acceptance_ids come from a trusted coordinator, not from
    a worker's bundle. The evidence root must be stable during preparation; the
    existing assessor rechecks spec approval and bytes before accepting evidence.
    Already registered runs are not migrated or overwritten by this operation.
    """
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("a full independently supplied bundle pin is required")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise ValueError("bundle pin mismatch")
    document = _document(raw)
    if set(document) != {"protocol", "policy_sha256", "delivery"} or document["protocol"] != PROTOCOL:
        raise ValueError("unsupported handoff protocol or envelope fields")
    pin = document["policy_sha256"]
    if not isinstance(pin, str) or re.fullmatch(r"[0-9a-f]{64}", pin) is None:
        raise ValueError("invalid consumer policy pin")
    if not hmac.compare_digest(pin, hashlib.sha256(canonical(policy_document())).hexdigest()):
        raise ValueError("consumer policy changed; re-export and review the policy")
    contract = DeliveryContract.model_validate_json(canonical(document["delivery"]))
    contract.validate_acceptance(acceptance_ids)
    if not artifact_matches(
        evidence_root, contract.spec.artifact_ref, contract.spec.artifact_sha256, MAX_DOCUMENT_BYTES
    ):
        raise ValueError("spec artifact missing, changed, unsafe, empty or oversized")
    if any(
        not artifact_matches(evidence_root, item.artifact_ref, item.artifact_sha256, MAX_DOCUMENT_BYTES)
        for item in contract.figma_contexts
    ):
        raise ValueError("Figma context artifact missing, changed, unsafe, empty or oversized")
    return contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare template delivery data; never approve or execute it.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("policy", help="Export the current native delivery policy and schema")
    prepare = commands.add_parser("prepare", help="Check a separately pinned bundle and emit native delivery JSON")
    prepare.add_argument("bundle", type=Path)
    prepare.add_argument("--sha256", required=True, help="Bundle digest pinned out of band by the coordinator")
    prepare.add_argument("--evidence-root", type=Path, required=True)
    prepare.add_argument("--acceptance-id", action="append", required=True, help="Repeat for EVERY profile AC")
    args = parser.parse_args(argv)
    try:
        if args.command == "policy":
            result = policy_document()
        else:
            with args.bundle.open("rb") as stream:
                raw = stream.read(MAX_DOCUMENT_BYTES + 1)
            contract = prepare_handoff(raw, expected_sha256=args.sha256, acceptance_ids=set(args.acceptance_id),
                                       evidence_root=args.evidence_root)
            result = contract.model_dump(mode="json")
            print("Prepared data only: not approval, completion, merge or deployment authority.", file=sys.stderr)
        print(canonical(result).decode("ascii"))
        return 0
    except (OSError, ValueError) as error:
        # Native validation errors can include input values. Do not echo private spec/command data into logs.
        print(f"handoff: input rejected ({type(error).__name__}); check pin, policy, spec and native schema", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
