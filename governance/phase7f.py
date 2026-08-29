"""Provider-neutral Phase 7F external trust-boundary contracts.

All implementations here are CONTRACT_TEST_ONLY. They validate mechanics but
cannot authenticate real evidence, reviewers, providers, or Phase 7E gates.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

PHASE7F_CONTRACT_VERSION = "phase7f-external-trust-boundary-v1"
SHA256 = r"^[0-9a-f]{64}$"


class Phase7FContractError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactClass(StrEnum):
    EVIDENCE = "EVIDENCE"
    POLICY = "POLICY"
    REVIEW_DECISION = "REVIEW_DECISION"
    IDENTITY_REGISTRY = "IDENTITY_REGISTRY"
    CUSTODY_AUDIT = "CUSTODY_AUDIT"


class ReviewerRole(StrEnum):
    MAKER = "MAKER"
    CHECKER = "CHECKER"
    INDEPENDENT_AUDITOR = "INDEPENDENT_AUDITOR"


class AdmissionStep(StrEnum):
    CANDIDATE_DECLARED = "CANDIDATE_DECLARED"
    AUTHORITY_RESOLVED = "AUTHORITY_RESOLVED"
    EVIDENCE_RESOLVED = "EVIDENCE_RESOLVED"
    REVIEWERS_RESOLVED = "REVIEWERS_RESOLVED"
    BINDINGS_VALIDATED = "BINDINGS_VALIDATED"
    MAKER_CHECKER_VALIDATED = "MAKER_CHECKER_VALIDATED"
    GATE_DERIVED = "GATE_DERIVED"
    AGGREGATE_AUDIT_REQUIRED = "AGGREGATE_AUDIT_REQUIRED"


CANONICAL_ADMISSION_ORDER = tuple(AdmissionStep)


class TrustAnchor(ContractModel):
    version: Literal["phase7f-trust-anchor-v1"] = "phase7f-trust-anchor-v1"
    anchor_id: str = Field(min_length=1)
    source_system_id: str = Field(min_length=1)
    authority_id: str = Field(min_length=1)
    artifact_classes: tuple[ArtifactClass, ...]
    activated_at: datetime.datetime
    revoked_at: datetime.datetime | None = None
    authority_provenance_hash: str = Field(pattern=SHA256)
    anchor_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self) -> TrustAnchor:
        if not self.artifact_classes or len(set(self.artifact_classes)) != len(
            self.artifact_classes
        ):
            raise ValueError("artifact classes must be non-empty and unique")
        if self.revoked_at is not None and self.revoked_at <= self.activated_at:
            raise ValueError("revocation must follow activation")
        if self.anchor_hash != typed_hash(self.model_dump(mode="json", exclude={"anchor_hash"})):
            raise ValueError("anchor hash mismatch")
        return self


class ContractTrustAnchorRegistry(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    version: Literal["phase7f-anchor-registry-v1"] = "phase7f-anchor-registry-v1"
    anchors: tuple[TrustAnchor, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self) -> ContractTrustAnchorRegistry:
        identities = [(a.anchor_id, a.source_system_id) for a in self.anchors]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate trust anchor identity")
        expected = typed_hash(self.model_dump(mode="json", exclude={"registry_hash"}))
        if self.registry_hash != expected:
            raise ValueError("anchor registry hash mismatch")
        return self


class ReviewerIdentity(ContractModel):
    actor_id: str = Field(min_length=1)
    aliases: tuple[str, ...]
    roles: tuple[ReviewerRole, ...]
    valid_from: datetime.datetime
    valid_until: datetime.datetime | None = None
    revoked_at: datetime.datetime | None = None
    authority_provenance_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def valid(self) -> ReviewerIdentity:
        names = [_canonical_name(value) for value in (self.actor_id, *self.aliases)]
        if any(not value for value in names) or len(names) != len(set(names)):
            raise ValueError("reviewer names and aliases must be non-empty and unique")
        if not self.roles or len(self.roles) != len(set(self.roles)):
            raise ValueError("reviewer roles must be non-empty and unique")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("invalid reviewer validity window")
        return self


class ContractReviewerIdentityRegistry(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    version: Literal["phase7f-reviewer-registry-v1"] = "phase7f-reviewer-registry-v1"
    identities: tuple[ReviewerIdentity, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self) -> ContractReviewerIdentityRegistry:
        claimed = [
            _canonical_name(name) for i in self.identities for name in (i.actor_id, *i.aliases)
        ]
        if len(claimed) != len(set(claimed)):
            raise ValueError("reviewer alias is ambiguous")
        expected = typed_hash(self.model_dump(mode="json", exclude={"registry_hash"}))
        if self.registry_hash != expected:
            raise ValueError("reviewer registry hash mismatch")
        return self


class ProviderDatasetCandidate(ContractModel):
    version: Literal["phase7f-onboarding-v1"] = "phase7f-onboarding-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    candidate_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_hash: str = Field(pattern=SHA256)
    required_anchor_ids: tuple[str, ...]
    required_gates: tuple[EvidenceGate, ...]
    declared_at: datetime.datetime
    candidate_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self) -> ProviderDatasetCandidate:
        if not self.required_anchor_ids or len(set(self.required_anchor_ids)) != len(
            self.required_anchor_ids
        ):
            raise ValueError("required anchors must be non-empty and unique")
        if self.required_gates != tuple(EvidenceGate):
            raise ValueError("candidate must declare all canonical Phase 7E gates in order")
        expected = typed_hash(self.model_dump(mode="json", exclude={"candidate_hash"}))
        if self.candidate_hash != expected:
            raise ValueError("candidate hash mismatch")
        return self


class ArtifactRequest(ContractModel):
    version: Literal["phase7f-artifact-request-v1"] = "phase7f-artifact-request-v1"
    request_id: str = Field(min_length=1)
    candidate_hash: str = Field(pattern=SHA256)
    anchor_id: str = Field(min_length=1)
    source_system_id: str = Field(min_length=1)
    canonical_source_id: str = Field(min_length=1)
    artifact_class: ArtifactClass
    artifact_version: str = Field(min_length=1)
    gate: EvidenceGate
    provider_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    policy_hash: str = Field(pattern=SHA256)
    as_of: datetime.datetime


class ResolvedArtifact(ContractModel):
    version: Literal["phase7f-resolved-artifact-v1"] = "phase7f-resolved-artifact-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    request_hash: str = Field(pattern=SHA256)
    anchor_hash: str = Field(pattern=SHA256)
    canonical_source_id: str = Field(min_length=1)
    artifact_version: str = Field(min_length=1)
    retrieved_at: datetime.datetime
    custody_record_id: str = Field(min_length=1)
    custody_hash: str = Field(pattern=SHA256)
    source_bytes_hex: str = Field(pattern=r"^(?:[0-9a-f]{2})+$")
    source_sha256: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def integrity(self) -> ResolvedArtifact:
        if hashlib.sha256(bytes.fromhex(self.source_bytes_hex)).hexdigest() != self.source_sha256:
            raise ValueError("resolved source integrity mismatch")
        return self


class ReviewDecision(ContractModel):
    version: Literal["phase7f-review-decision-v1"] = "phase7f-review-decision-v1"
    candidate_hash: str = Field(pattern=SHA256)
    request_hash: str = Field(pattern=SHA256)
    artifact_hash: str = Field(pattern=SHA256)
    gate: EvidenceGate
    provider_id: str
    dataset_id: str
    dataset_version: str
    scope_id: str
    policy_hash: str = Field(pattern=SHA256)
    maker_claim: str
    checker_claim: str
    decided_at: datetime.datetime
    decision: Literal["ACCEPT", "REJECT"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self) -> ReviewDecision:
        expected = typed_hash(self.model_dump(mode="json", exclude={"decision_hash"}))
        if self.decision_hash != expected:
            raise ValueError("decision hash mismatch")
        return self


class ContractAdmissionResult(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    steps: tuple[AdmissionStep, ...]
    mechanics_valid: bool
    gate: EvidenceGate
    real_gate_state: Literal[GateState.OPEN_EXTERNAL] = GateState.OPEN_EXTERNAL
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"

    @model_validator(mode="after")
    def coherent(self) -> ContractAdmissionResult:
        if self.steps != CANONICAL_ADMISSION_ORDER:
            raise ValueError("admission steps must be complete and canonical")
        return self


class ExternalEvidenceResolver(Protocol):
    """Future adapter; its implementation must live outside repository trust."""

    def resolve(self, request: ArtifactRequest) -> ResolvedArtifact: ...


ModelT = TypeVar("ModelT", bound=BaseModel)


def _canonical_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise Phase7FContractError("input is not canonically serializable") from exc


def _revalidate(expected: type[ModelT], value: Any, label: str) -> ModelT:
    try:
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError) as exc:
        raise Phase7FContractError(f"invalid {label}") from exc


def _resolve_actor(registry, claim, role, at):
    canonical = _canonical_name(claim)
    for identity in registry.identities:
        names = {_canonical_name(value) for value in (identity.actor_id, *identity.aliases)}
        active = (
            identity.valid_from <= at
            and (identity.valid_until is None or at <= identity.valid_until)
            and (identity.revoked_at is None or at < identity.revoked_at)
        )
        if canonical in names and role in identity.roles and active:
            return identity.actor_id
    return None


def verify_contract_admission(
    candidate: Any,
    anchors: Any,
    reviewers: Any,
    request: Any,
    artifact: Any,
    decision: Any,
    *,
    verifier_time: datetime.datetime,
) -> ContractAdmissionResult:
    """Revalidate a synthetic admission path and keep the real gate closed."""
    candidate = _revalidate(ProviderDatasetCandidate, candidate, "candidate")
    anchors = _revalidate(ContractTrustAnchorRegistry, anchors, "anchor registry")
    reviewers = _revalidate(ContractReviewerIdentityRegistry, reviewers, "reviewer registry")
    request = _revalidate(ArtifactRequest, request, "artifact request")
    artifact = _revalidate(ResolvedArtifact, artifact, "resolved artifact")
    decision = _revalidate(ReviewDecision, decision, "review decision")
    if verifier_time.tzinfo is None:
        raise Phase7FContractError("verifier time must be timezone-aware")
    matching = [
        a
        for a in anchors.anchors
        if a.anchor_id == request.anchor_id and a.source_system_id == request.source_system_id
    ]
    if len(matching) != 1:
        raise Phase7FContractError("trust anchor is unknown or ambiguous")
    anchor = matching[0]
    active = anchor.activated_at <= verifier_time and (
        anchor.revoked_at is None or verifier_time < anchor.revoked_at
    )
    if not active or request.artifact_class not in anchor.artifact_classes:
        raise Phase7FContractError("trust anchor is inactive or unauthorized")
    request_hash = typed_hash(request.model_dump(mode="json"))
    artifact_hash = typed_hash(artifact.model_dump(mode="json"))
    candidate_bindings = (
        request.candidate_hash == candidate.candidate_hash
        and request.anchor_id in candidate.required_anchor_ids
        and request.gate in candidate.required_gates
        and (
            request.provider_id,
            request.dataset_id,
            request.dataset_version,
            request.scope_id,
            request.policy_hash,
        )
        == (
            candidate.provider_id,
            candidate.dataset_id,
            candidate.dataset_version,
            candidate.scope_id,
            candidate.policy_hash,
        )
    )
    artifact_bindings = (
        artifact.request_hash == request_hash
        and artifact.anchor_hash == anchor.anchor_hash
        and artifact.canonical_source_id == request.canonical_source_id
        and artifact.artifact_version == request.artifact_version
        and request.as_of <= verifier_time
        and artifact.retrieved_at <= verifier_time
    )
    decision_bindings = (
        decision.decision == "ACCEPT"
        and decision.candidate_hash == candidate.candidate_hash
        and decision.request_hash == request_hash
        and decision.artifact_hash == artifact_hash
        and decision.gate == request.gate
        and (
            decision.provider_id,
            decision.dataset_id,
            decision.dataset_version,
            decision.scope_id,
            decision.policy_hash,
        )
        == (
            candidate.provider_id,
            candidate.dataset_id,
            candidate.dataset_version,
            candidate.scope_id,
            candidate.policy_hash,
        )
        and decision.decided_at <= verifier_time
    )
    maker = _resolve_actor(reviewers, decision.maker_claim, ReviewerRole.MAKER, decision.decided_at)
    checker = _resolve_actor(
        reviewers, decision.checker_claim, ReviewerRole.CHECKER, decision.decided_at
    )
    mechanics_valid = bool(
        candidate_bindings
        and artifact_bindings
        and decision_bindings
        and maker
        and checker
        and maker != checker
    )
    return ContractAdmissionResult(
        steps=CANONICAL_ADMISSION_ORDER, mechanics_valid=mechanics_valid, gate=request.gate
    )
