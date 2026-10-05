"""Selective, offline projects-template adapter; no execution or approval authority.

Ready now checks that the approver is not an author, that approval preceded evidence, that the
spec artifact hash still matches under `evidence_root`, and that a coordinator-supplied
ApprovalLookup confirms the approval record; a missing lookup fails closed, never open.
Done/Complete is checked within the existing authenticated quality receipt pipeline.
Commands and references are data only. Existing quality checks cannot be waived here.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import parse_qs, urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

# Ceiling for the spec artifact readability check; independent of any evidence policy.
_MAX_SPEC_ARTIFACT_BYTES = 64 * 1024 * 1024

TEMPLATE_REVISION = "23accce8a4b830eb07690cbd39dded8bf3bc94ce"
_SOURCE_DOCUMENTS = {
    "docs/framework/standard-delivery.md": "a238bac5c0c44bda14eb4c12e77a4c7c8b664334",
    "docs/framework/quality-gates-by-profile.md": "094d17f6acaa255097266d73777056bc8bb53826",
    "docs/framework/templates/FEATURE-SPEC.template.md": "e5985682e122cea2720d8a9041c6df8e620b7f78",
    "docs/framework/ui-ux-intelligence-provider.md": "ed8c161c928257a592a6cc6965f65d05f876f17f",
    "docs/framework/adopt-from-outside.md": "bad5c8f0ea6bd761ef1a578e11064a28a257f1b6",
}
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)]
_Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_FIGMA_NODE_ID_PATTERN = r"^I?\d+[:\-]\d+(?:;\d+[:\-]\d+)*$"
_FigmaNodeId = Annotated[str, StringConstraints(pattern=_FIGMA_NODE_ID_PATTERN)]
_Level = Literal["done", "complete"]


def adopted_source() -> dict[str, Any]:
    """Fresh metadata, not a network fetch; changing the reviewed pin changes the contract."""
    return {"repository": "seeker19110/projects-template", "repository_id": 1283493926,
            "revision": TEMPLATE_REVISION, "adapter_policy": "template-delivery/1",
            "documents": dict(sorted(_SOURCE_DOCUMENTS.items()))}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class ApprovedSpec(_Strict):
    state: Literal["Approved for implementation"]
    artifact_ref: _Text
    artifact_sha256: _Digest
    approval_record: _Text
    approved_by: _Text
    approved_at: AwareDatetime


class AcceptanceTest(_Strict):
    acceptance_id: _Text
    test_ref: _Text


class FigmaContextArtifact(_Strict):
    """A frame's external source and the exact local snapshot used by delivery."""

    source_url: _Text
    node_id: _FigmaNodeId
    artifact_ref: _Text
    artifact_sha256: _Digest

    @field_validator("source_url")
    @classmethod
    def valid_figma_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port
            query = parse_qs(parsed.query, keep_blank_values=True)
        except ValueError as error:
            raise ValueError("invalid Figma source URL") from error
        if (
            parsed.scheme != "https"
            or host not in {"figma.com", "www.figma.com"}
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.fragment
            or re.fullmatch(r"/(?:design|file)/[A-Za-z0-9]+(?:/[^?#]*)?", parsed.path) is None
        ):
            raise ValueError("source URL must be an HTTPS Figma design or file URL")
        if set(query) - {"node-id"} or any(len(values) != 1 or not values[0] for values in query.values()):
            raise ValueError("Figma source URL may contain only one node-id query")
        if "node-id" in query and re.fullmatch(_FIGMA_NODE_ID_PATTERN, query["node-id"][0].replace("-", ":")) is None:
            raise ValueError("Figma source URL contains an invalid node-id")
        return value

    @model_validator(mode="after")
    def node_matches_url(self) -> FigmaContextArtifact:
        query = parse_qs(urlsplit(self.source_url).query)
        if query and query["node-id"][0].replace("-", ":") != self.node_id.replace("-", ":"):
            raise ValueError("Figma URL node-id must match the manifest node_id")
        return self


class DeliveryGate(_Strict):
    id: _Id
    phase: _Level
    mechanism: Literal["command", "inspection"]
    applicable: bool
    command: tuple[_Text, ...] = ()
    scope_reason: str = Field(default="", max_length=12000)

    @model_validator(mode="after")
    def coherent(self) -> DeliveryGate:
        if not self.applicable and not self.scope_reason.strip():
            raise ValueError("not-applicable scope requires a prior justification")
        if self.applicable and self.mechanism == "command" and not self.command:
            raise ValueError("an applicable command gate must be configured before implementation")
        if self.mechanism == "inspection" and self.command:
            raise ValueError("an inspection gate does not execute a command")
        return self


class DeliveryContract(_Strict):
    source_revision: _Text = TEMPLATE_REVISION
    adoption: Literal["greenfield", "brownfield"]
    completion_level: _Level
    spec: ApprovedSpec
    research_refs: tuple[_Text, ...] = Field(min_length=1)
    no_change_rationale: _Text
    alternatives_and_tradeoffs: _Text
    baseline_ref: _Text | None = None
    blocking_decisions: tuple[_Text, ...] = ()
    figma_contexts: tuple[FigmaContextArtifact, ...] = Field(default_factory=tuple, max_length=8)
    acceptance_tests: tuple[AcceptanceTest, ...] = Field(min_length=1)
    gates: tuple[DeliveryGate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ready(self) -> DeliveryContract:
        if self.source_revision != TEMPLATE_REVISION:
            raise ValueError("source revision has not been adopted; update the adapter through review")
        if self.adoption == "brownfield" and self.baseline_ref is None:
            raise ValueError("incremental adoption requires an existing-system baseline")
        if self.blocking_decisions:
            raise ValueError("blocking decisions must be resolved before implementation")
        values = (
            [g.id for g in self.gates],
            [a.acceptance_id for a in self.acceptance_tests],
            [(item.source_url, item.node_id) for item in self.figma_contexts],
        )
        for identifiers in values:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("gate, acceptance, and Figma context IDs must be unique")
        phases = {g.phase for g in self.gates if g.applicable}
        if "done" not in phases or (self.completion_level == "complete" and "complete" not in phases):
            raise ValueError("every required delivery level needs an applicable gate")
        return self

    @model_serializer(mode="wrap")
    def serialize_contract(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if not self.figma_contexts:
            document.pop("figma_contexts", None)
        return document

    def validate_acceptance(self, identifiers: set[str]) -> None:
        if {a.acceptance_id for a in self.acceptance_tests} != identifiers:
            raise ValueError("delivery acceptance mapping must match the complete profile acceptance set")


class GateObservation(_Strict):
    id: _Id
    status: Literal["PASS", "FAIL", "NOT_CONFIGURED", "NOT_APPLICABLE"]
    checks_executed: int = Field(ge=0)
    command: tuple[_Text, ...] = ()
    exit_code: int | None = None
    evidence_ref: _Text


class DeliveryReport(_Strict):
    level: _Level
    target: Literal["verified", "merged", "staging", "production"]
    gates: tuple[GateObservation, ...]
    open_required_items: int = Field(ge=0)
    blocking_findings: int = Field(ge=0)
    goals_measured: bool
    guardrails_met: bool
    out_of_scope_items: int = Field(ge=0)

    @model_validator(mode="after")
    def unique_observations(self) -> DeliveryReport:
        ids = [item.id for item in self.gates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate gate observations must be reconciled")
        return self


def artifact_matches(root: Path, rel_path: str, sha256: str, max_bytes: int) -> bool:
    """Shared path-safety + digest check used for both evidence and spec artifacts."""
    path = PurePosixPath(rel_path)
    if path.is_absolute() or ".." in path.parts or "\\" in rel_path or ":" in rel_path:
        return False
    try:
        base = root.resolve(strict=True)
        artifact = (base / str(path)).resolve(strict=True)
        if not artifact.is_relative_to(base) or not artifact.is_file():
            return False
        size = artifact.stat().st_size
        if size <= 0 or size > max_bytes:
            return False
        digest = hashlib.sha256()
        with artifact.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        return hmac.compare_digest(digest.hexdigest(), sha256)
    except (OSError, ValueError, RuntimeError):
        return False


class ApprovalLookup(Protocol):
    """Trusted, out-of-band source of truth for who actually approved a spec record."""

    def approved(self, record: str, artifact_sha256: str) -> str | None:
        """Return the approving principal for this record+artifact, or None if unverifiable."""
        ...


def _principal(value: str) -> str:
    """Normalize a principal identifier for comparison: trim, then case-fold."""
    return value.strip().casefold()


def ready_gaps(
    contract: DeliveryContract,
    *,
    authors: frozenset[str],
    now: datetime,
    earliest_evidence: datetime,
    evidence_root: Path,
    lookup: ApprovalLookup | None,
) -> tuple[str, ...]:
    """Ready is authenticated approval of a spec, never structural shape alone.

    A missing/absent lookup can never be treated as approved (fail closed).
    """
    spec = contract.spec
    gaps: list[str] = []
    if _principal(spec.approved_by) in {_principal(author) for author in authors}:
        gaps.append("spec_self_approval")
    if spec.approved_at > now:
        gaps.append("spec_approved_in_future")
    if spec.approved_at > earliest_evidence:
        gaps.append("spec_approved_after_evidence")
    if not artifact_matches(evidence_root, spec.artifact_ref, spec.artifact_sha256, _MAX_SPEC_ARTIFACT_BYTES):
        gaps.append("spec_artifact_changed")
    approver = None if lookup is None else lookup.approved(spec.approval_record, spec.artifact_sha256)
    if lookup is None or approver is None or _principal(approver) != _principal(spec.approved_by):
        gaps.append("approval_record_unverified")
    return tuple(gaps)


def _gate_gap(gate: DeliveryGate, observation: GateObservation) -> str:
    if not gate.applicable:
        if observation.status != "NOT_APPLICABLE" or observation.checks_executed or observation.command or observation.exit_code is not None:
            return "scope_mismatch"
        return ""
    if observation.status != "PASS":
        return observation.status
    if observation.checks_executed == 0:
        return "no_checks"
    if gate.mechanism == "command":
        if observation.command != gate.command or observation.exit_code != 0:
            return "command_mismatch_or_failure"
    elif observation.command or observation.exit_code is not None:
        return "inspection_must_not_claim_command"
    return ""


def delivery_gaps(contract: DeliveryContract, report: DeliveryReport | None, target: str) -> tuple[str, ...]:
    """Check a report AFTER identity/signature/revision verification by the existing assessor.

    A configured command returning zero is insufficient: it must execute checks.
    Non-applicability is a contract decision, never a reporter's late waiver.
    Counts/observations are collected by trusted drivers, not inferred from prose.
    """
    if report is None:
        return ("report_missing",)
    gaps: list[str] = []
    if report.level != contract.completion_level or report.target != target:
        gaps.append("incomplete_level_or_target")
    if report.blocking_findings:
        gaps.append("blocking_findings")
    if not report.guardrails_met:
        gaps.append("guardrail_regression")
    if contract.completion_level == "complete":
        if report.open_required_items:
            gaps.append("required_work_open")
        if not report.goals_measured:
            gaps.append("goal_measurement_missing")
    expected = {g.id: g for g in contract.gates if g.phase == "done" or contract.completion_level == "complete"}
    observed = {g.id: g for g in report.gates}
    gaps.extend(f"{key}:unexpected_gate" for key in sorted(observed.keys() - expected.keys()))
    for key, gate in expected.items():
        if key not in observed:
            gaps.append(f"{key}:missing")
            continue
        reason = _gate_gap(gate, observed[key])
        if reason:
            gaps.append(f"{key}:{reason}")
    return tuple(gaps)
