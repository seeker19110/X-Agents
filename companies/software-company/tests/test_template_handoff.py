"""Native handoff preparation is not approval, execution, or completion."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from company import template_handoff as bridge
from company.delivery_contract import DeliveryContract, adopted_source, delivery_gaps, ready_gaps

SPEC = b"# Feature spec: Handoff\n\nAC-1: prepare data only.\n"


@pytest.fixture
def bundle(tmp_path: Path) -> dict:
    (tmp_path / "spec.md").write_bytes(SPEC)
    return {"protocol": bridge.PROTOCOL, "policy_sha256": hashlib.sha256(
        bridge.canonical(bridge.policy_document())).hexdigest(), "delivery": {
        "source_revision": adopted_source()["revision"], "adoption": "brownfield", "completion_level": "done",
        "spec": {"state": "Approved for implementation", "artifact_ref": "spec.md",
                 "artifact_sha256": hashlib.sha256(SPEC).hexdigest(), "approval_record": "fixture:not-authority",
                 "approved_by": "human:reviewer", "approved_at": "2026-09-26T00:00:00Z"},
        "research_refs": ["research:fixture"], "baseline_ref": "baseline:fixture",
        "no_change_rationale": "Manual transfers drift.", "alternatives_and_tradeoffs": "Reuse native policy.",
        "acceptance_tests": [{"acceptance_id": "AC-1", "test_ref": "tests/test_template_handoff.py"}],
        "gates": [{"id": "unit", "phase": "done", "mechanism": "command", "applicable": True,
                   "command": ["python", "-m", "unittest"]}]}}


def prepare(bundle: dict, root: Path, **kwargs) -> DeliveryContract:
    raw = bridge.canonical(bundle)
    return bridge.prepare_handoff(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                                  acceptance_ids={"AC-1"}, evidence_root=root, **kwargs)


def test_policy_is_derived_from_native_schema_and_reviewed_source() -> None:
    policy = bridge.policy_document()
    assert policy == {"protocol": bridge.PROTOCOL, "source": adopted_source(),
                      "delivery_schema": DeliveryContract.model_json_schema(),
                      "max_spec_bytes": bridge.MAX_DOCUMENT_BYTES}
    policy["source"]["revision"] = "modified"
    assert bridge.policy_document()["source"]["revision"] == adopted_source()["revision"]


def test_prepares_native_contract_without_mutation(bundle: dict, tmp_path: Path) -> None:
    before = copy.deepcopy(bundle)
    native = prepare(bundle, tmp_path)
    assert isinstance(native, DeliveryContract)
    assert native.spec.artifact_sha256 == hashlib.sha256(SPEC).hexdigest()
    assert bundle == before
    assert prepare(bundle, tmp_path) == native
    assert "figma_contexts" not in native.model_dump()


def test_prepares_only_pinned_figma_context_artifacts(bundle: dict, tmp_path: Path) -> None:
    context = b"# Checkout frame\n\nLayout: vertical, 16px gap.\n"
    (tmp_path / "figma.md").write_bytes(context)
    bundle["delivery"]["figma_contexts"] = [
        {
            "source_url": "https://www.figma.com/design/Abc123/App?node-id=12-34",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": hashlib.sha256(context).hexdigest(),
        }
    ]
    native = prepare(bundle, tmp_path)
    assert len(native.figma_contexts) == 1
    assert native.figma_contexts[0].artifact_sha256 == hashlib.sha256(context).hexdigest()
    assert native.model_dump()["figma_contexts"][0]["artifact_ref"] == "figma.md"


@pytest.mark.parametrize(
    "context",
    [
        {
            "source_url": "http://www.figma.com/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://figma.example/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://user@www.figma.com/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com:444/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com:bad/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/proto/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App#private",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App?t=secret",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App?node-id=bad",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App?node-id=",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App?node-id=12-34&node-id=12-34",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App?node-id=12-34",
            "node_id": "56:78",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App",
            "node_id": "bad",
            "artifact_ref": "figma.md",
            "artifact_sha256": "0" * 64,
        },
        {
            "source_url": "https://www.figma.com/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "../figma.md",
            "artifact_sha256": "0" * 64,
        },
    ],
)
def test_rejects_untrusted_figma_context_metadata(bundle: dict, tmp_path: Path, context: dict) -> None:
    (tmp_path / "figma.md").write_bytes(b"snapshot")
    bundle["delivery"]["figma_contexts"] = [context]
    with pytest.raises(ValueError):
        prepare(bundle, tmp_path)


def test_rejects_changed_or_missing_figma_context_snapshot(bundle: dict, tmp_path: Path) -> None:
    (tmp_path / "figma.md").write_bytes(b"changed snapshot")
    bundle["delivery"]["figma_contexts"] = [
        {
            "source_url": "https://www.figma.com/file/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": hashlib.sha256(b"original").hexdigest(),
        }
    ]
    with pytest.raises(ValueError, match="Figma context"):
        prepare(bundle, tmp_path)


def test_rejects_missing_and_empty_figma_context_snapshot(bundle: dict, tmp_path: Path) -> None:
    bundle["delivery"]["figma_contexts"] = [
        {
            "source_url": "https://www.figma.com/file/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "missing.md",
            "artifact_sha256": hashlib.sha256(b"missing").hexdigest(),
        }
    ]
    with pytest.raises(ValueError, match="Figma context"):
        prepare(bundle, tmp_path)


def test_rejects_oversized_figma_context_snapshot(bundle: dict, tmp_path: Path) -> None:
    snapshot = b"x" * (1024 * 1024 + 1)
    (tmp_path / "figma.md").write_bytes(snapshot)
    bundle["delivery"]["figma_contexts"] = [
        {
            "source_url": "https://www.figma.com/file/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "figma.md",
            "artifact_sha256": hashlib.sha256(snapshot).hexdigest(),
        }
    ]
    with pytest.raises(ValueError, match="Figma context"):
        prepare(bundle, tmp_path)
    (tmp_path / "empty.md").write_bytes(b"")
    bundle["delivery"]["figma_contexts"][0]["artifact_ref"] = "empty.md"
    bundle["delivery"]["figma_contexts"][0]["artifact_sha256"] = hashlib.sha256(b"").hexdigest()
    with pytest.raises(ValueError, match="Figma context"):
        prepare(bundle, tmp_path)


def test_context_limit_and_identifiers_are_enforced(bundle: dict, tmp_path: Path) -> None:
    snapshot = b"frame"
    (tmp_path / "figma.md").write_bytes(snapshot)
    context = {
        "source_url": "https://www.figma.com/design/Abc123/App",
        "node_id": "12:34",
        "artifact_ref": "figma.md",
        "artifact_sha256": hashlib.sha256(snapshot).hexdigest(),
    }
    bundle["delivery"]["figma_contexts"] = [context] * 9
    with pytest.raises(ValueError):
        prepare(bundle, tmp_path)
    bundle["delivery"]["figma_contexts"] = [context, context]
    with pytest.raises(ValueError, match="unique"):
        prepare(bundle, tmp_path)


def test_rejects_figma_context_symlink_escape(bundle: dict, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-figma.md"
    outside.write_bytes(b"private frame")
    (tmp_path / "linked-figma.md").symlink_to(outside)
    bundle["delivery"]["figma_contexts"] = [
        {
            "source_url": "https://www.figma.com/design/Abc123/App",
            "node_id": "12:34",
            "artifact_ref": "linked-figma.md",
            "artifact_sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        }
    ]
    with pytest.raises(ValueError, match="Figma context"):
        prepare(bundle, tmp_path)


def test_preparation_never_grants_approval_or_completion(bundle: dict, tmp_path: Path) -> None:
    native = prepare(bundle, tmp_path)
    now = datetime(2026, 9, 26, 12, tzinfo=UTC)
    assert "approval_record_unverified" in ready_gaps(native, authors=frozenset({"human:author"}),
        now=now, earliest_evidence=now, evidence_root=tmp_path, lookup=None)
    assert delivery_gaps(native, None, "verified") == ("report_missing",)
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("pin", ["", "main", "0" * 63, "A" * 64, "0" * 64, None, 42])
def test_requires_independently_pinned_bundle(bundle: dict, tmp_path: Path, pin: str) -> None:
    with pytest.raises(ValueError, match="pin"):
        bridge.prepare_handoff(bridge.canonical(bundle), expected_sha256=pin,
                               acceptance_ids={"AC-1"}, evidence_root=tmp_path)


@pytest.mark.parametrize("key,value", [("protocol", "future/2"), ("policy_sha256", "f" * 64),
                                       ("policy_sha256", None), ("policy_sha256", 42), ("policy_sha256", "không")])
def test_protocol_and_local_policy_are_pinned(bundle: dict, tmp_path: Path, key: str, value) -> None:
    bundle[key] = value
    with pytest.raises(ValueError):
        prepare(bundle, tmp_path)


@pytest.mark.parametrize("remove", ["protocol", "policy_sha256", "delivery"])
def test_missing_envelope_field(bundle: dict, tmp_path: Path, remove: str) -> None:
    bundle.pop(remove)
    with pytest.raises(ValueError):
        prepare(bundle, tmp_path)


def test_unknown_field_is_not_an_authority_extension(bundle: dict, tmp_path: Path) -> None:
    bundle["autoapprove"] = True
    with pytest.raises(ValueError):
        prepare(bundle, tmp_path)


@pytest.mark.parametrize("raw", [b'[]', b'null', b'bad', b'\xff', b'{"x":1,"x":2}', b'{"x":NaN}',
                                  b'{"x":Infinity}', b' ' * (1048576 + 1),
                                  b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'],
                         ids=["array", "null", "invalid-json", "invalid-utf8", "duplicate-key", "nan",
                              "infinity", "oversized", "deeply-nested"])
def test_strict_bounded_json(raw: bytes, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        bridge.prepare_handoff(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                               acceptance_ids={"AC-1"}, evidence_root=tmp_path)


@pytest.mark.parametrize("change", ["extra", "baseline", "blocking", "source", "empty_command", "waiver",
                                    "complete", "duplicate", "bad_type", "naive_time"])
def test_existing_native_validators_cannot_be_bypassed(bundle: dict, tmp_path: Path, change: str) -> None:
    contract = bundle["delivery"]
    if change == "extra":
        contract["autoapprove"] = True
    elif change == "baseline":
        contract.pop("baseline_ref")
    elif change == "blocking":
        contract["blocking_decisions"] = ["Open scope"]
    elif change == "source":
        contract["source_revision"] = "0" * 40
    elif change == "empty_command":
        contract["gates"][0]["command"] = []
    elif change == "waiver":
        contract["gates"][0]["applicable"] = False
    elif change == "complete":
        contract["completion_level"] = "complete"
    elif change == "duplicate":
        contract["gates"] *= 2
    elif change == "bad_type":
        contract["gates"][0]["applicable"] = "true"
    else:
        contract["spec"]["approved_at"] = "2026-09-26T00:00:00"
    with pytest.raises(ValueError):
        prepare(bundle, tmp_path)


def test_acceptance_set_must_match_coordinator_profile(bundle: dict, tmp_path: Path) -> None:
    raw = bridge.canonical(bundle)
    with pytest.raises(ValueError, match="acceptance"):
        bridge.prepare_handoff(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                               acceptance_ids={"AC-1", "AC-2"}, evidence_root=tmp_path)


@pytest.mark.parametrize("ref", ["../spec.md", "/spec.md", "C:/spec.md", "..\\spec.md", "missing.md", "."])
def test_spec_path_cannot_escape_root(bundle: dict, tmp_path: Path, ref: str) -> None:
    bundle["delivery"]["spec"]["artifact_ref"] = ref
    with pytest.raises(ValueError, match="artifact"):
        prepare(bundle, tmp_path)


def test_changed_spec_invalidates_preparation(bundle: dict, tmp_path: Path) -> None:
    (tmp_path / "spec.md").write_bytes(SPEC + b"changed")
    with pytest.raises(ValueError, match="artifact"):
        prepare(bundle, tmp_path)


def test_commands_are_data_only(bundle: dict, tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
    bundle["delivery"]["gates"][0]["command"] = argv
    assert prepare(bundle, tmp_path).gates[0].command == tuple(argv)
    assert not marker.exists()


def test_main_policy_and_prepare(bundle: dict, tmp_path: Path, capsys) -> None:
    assert bridge.main(["policy"]) == 0
    assert json.loads(capsys.readouterr().out) == bridge.policy_document()
    path = tmp_path / "bundle.json"
    raw = bridge.canonical(bundle)
    path.write_bytes(raw)
    args = ["prepare", str(path), "--sha256", hashlib.sha256(raw).hexdigest(),
            "--evidence-root", str(tmp_path), "--acceptance-id", "AC-1"]
    assert bridge.main(args) == 0
    captured = capsys.readouterr()
    assert DeliveryContract.model_validate_json(captured.out) == prepare(bundle, tmp_path)
    assert "not approval" in captured.err
    path.unlink()
    assert bridge.main(args) == 2
    assert "handoff:" in capsys.readouterr().err


def test_main_invalid_document(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bundle.json"
    path.write_bytes(b"{}")
    assert bridge.main(["prepare", str(path), "--sha256", "0" * 64, "--evidence-root", str(tmp_path),
                        "--acceptance-id", "AC-1"]) == 2
    assert "handoff:" in capsys.readouterr().err


def test_module_entrypoint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["template_handoff", "policy"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("company.template_handoff", run_name="__main__")
    assert result.value.code == 0
    assert json.loads(capsys.readouterr().out)["protocol"] == bridge.PROTOCOL


def test_parser_recursion_is_normalized(bundle: dict, tmp_path: Path, monkeypatch) -> None:
    raw = bridge.canonical(bundle)
    def excessive_nesting(*args, **kwargs):
        raise RecursionError("too deep")
    monkeypatch.setattr(bridge.json, "loads", excessive_nesting)
    with pytest.raises(ValueError, match="deeply"):
        bridge.prepare_handoff(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                               acceptance_ids={"AC-1"}, evidence_root=tmp_path)


def test_json_numeric_overflow_is_rejected() -> None:
    with pytest.raises(ValueError, match="nonfinite"):
        bridge._document(b'{"x":1e999}')
    # Exercise OUR depth limit below CPython's recursion limit on both 3.11 and 3.13.
    at_limit = b'{"x":' + b'[' * 63 + b'0' + b']' * 63 + b'}'
    assert isinstance(bridge._document(at_limit), dict)
    beyond_limit = b'{"x":' + b'[' * 64 + b'0' + b']' * 64 + b'}'
    with pytest.raises(ValueError, match="deeply"):
        bridge._document(beyond_limit)
