"""Synthetic Phase 7F trust-boundary mechanics; never external authenticity."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

PHASE7F_CONTRACT_VERSION = "phase7f-external-trust-boundary-v2"
SHA256 = r"^[0-9a-f]{64}$"
OID = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


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


class AuthorityClass(StrEnum):
    GOVERNANCE = "SYNTHETIC_GOVERNANCE"
    CUSTODY = "SYNTHETIC_CUSTODY"
    IDENTITY = "SYNTHETIC_IDENTITY"
    AUDIT = "SYNTHETIC_AUDIT"


class AuthorityCapability(StrEnum):
    ANCHOR = "ISSUE_TRUST_ANCHOR"
    REVIEWERS = "ISSUE_REVIEWER_REGISTRY"
    CUSTODY = "ISSUE_CUSTODY_RECORD"
    POLICY = "ISSUE_POLICY"
    AUDIT = "ISSUE_AUDIT"


class ReviewerRole(StrEnum):
    MAKER = "MAKER"
    CHECKER = "CHECKER"
    INDEPENDENT_AUDITOR = "INDEPENDENT_AUDITOR"


class AdmissionStage(StrEnum):
    AUTHORITY_REGISTRY_VERIFIED = "AUTHORITY_REGISTRY_VERIFIED"
    TRUST_ANCHOR_VERIFIED = "TRUST_ANCHOR_VERIFIED"
    ONBOARDING_VERIFIED = "ONBOARDING_VERIFIED"
    ARTIFACT_CUSTODY_VERIFIED = "ARTIFACT_CUSTODY_VERIFIED"
    MAKER_CHECKER_VERIFIED = "MAKER_CHECKER_VERIFIED"
    INDEPENDENT_AUDIT_VERIFIED = "INDEPENDENT_AUDIT_VERIFIED"
    ADMISSION_COMPLETE = "ADMISSION_COMPLETE"


CANONICAL_ADMISSION_ORDER = tuple(AdmissionStage)


def _aware(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _active(start, end, revoked, at):
    return start <= at and (end is None or at < end) and (revoked is None or at < revoked)


def _alias(value: str) -> str:
    """Apply Unicode NFKC, whitespace folding, and casefold, in that order."""
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _unique(values, label):
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{label} must be non-empty and unique")


class AuthorityProvenance(ContractModel):
    version: Literal["phase7f-authority-provenance-v1"] = "phase7f-authority-provenance-v1"
    provenance_id: str = Field(pattern=OID)
    issuer: str = Field(min_length=1)
    issued_at: dt.datetime
    declaration: str = Field(min_length=1)
    provenance_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.issued_at, "issued_at")
        if self.provenance_hash != typed_hash(
            self.model_dump(mode="json", exclude={"provenance_hash"})
        ):
            raise ValueError("provenance hash mismatch")
        return self


class ContractAuthority(ContractModel):
    version: Literal["phase7f-authority-v1"] = "phase7f-authority-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    authority_id: str = Field(pattern=OID)
    authority_class: AuthorityClass
    capabilities: tuple[AuthorityCapability, ...]
    valid_from: dt.datetime
    valid_until: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    provenance: AuthorityProvenance
    authority_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _unique(self.capabilities, "capabilities")
        _aware(self.valid_from, "valid_from")
        if self.valid_until:
            _aware(self.valid_until, "authority valid_until")
        if self.revoked_at:
            _aware(self.revoked_at, "authority revoked_at")
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("invalid authority window")
        if self.revoked_at and self.revoked_at <= self.valid_from:
            raise ValueError("invalid authority revocation")
        if self.authority_hash != typed_hash(
            self.model_dump(mode="json", exclude={"authority_hash"})
        ):
            raise ValueError("authority hash mismatch")
        return self


class ContractAuthorityRegistry(ContractModel):
    version: Literal["phase7f-authority-registry-v1"] = "phase7f-authority-registry-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    registry_id: str = Field(pattern=OID)
    valid_from: dt.datetime
    valid_until: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    authorities: tuple[ContractAuthority, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.valid_from, "authority registry valid_from")
        if self.valid_until:
            _aware(self.valid_until, "authority registry valid_until")
        if self.revoked_at:
            _aware(self.revoked_at, "authority registry revoked_at")
        ids = tuple(x.authority_id for x in self.authorities)
        _unique(ids, "authority IDs")
        if ids != tuple(sorted(ids)):
            raise ValueError("authorities not canonically ordered")
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("invalid registry window")
        if self.registry_hash != typed_hash(
            self.model_dump(mode="json", exclude={"registry_hash"})
        ):
            raise ValueError("authority registry hash mismatch")
        return self


class AuthorityBinding(ContractModel):
    authority_id: str = Field(pattern=OID)
    authority_registry_version: Literal["phase7f-authority-registry-v1"]
    authority_registry_hash: str = Field(pattern=SHA256)
    authority_hash: str = Field(pattern=SHA256)
    provenance_hash: str = Field(pattern=SHA256)


class TrustAnchor(ContractModel):
    version: Literal["phase7f-trust-anchor-v2"] = "phase7f-trust-anchor-v2"
    anchor_id: str = Field(pattern=OID)
    source_system_id: str = Field(pattern=OID)
    authority: AuthorityBinding
    artifact_classes: tuple[ArtifactClass, ...]
    activated_at: dt.datetime
    valid_until: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    anchor_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.activated_at, "anchor activated_at")
        if self.valid_until:
            _aware(self.valid_until, "anchor valid_until")
        if self.revoked_at:
            _aware(self.revoked_at, "anchor revoked_at")
        _unique(self.artifact_classes, "artifact classes")
        if self.valid_until and self.valid_until <= self.activated_at:
            raise ValueError("invalid anchor window")
        if self.revoked_at and self.revoked_at <= self.activated_at:
            raise ValueError("invalid anchor revocation")
        if self.anchor_hash != typed_hash(self.model_dump(mode="json", exclude={"anchor_hash"})):
            raise ValueError("anchor hash mismatch")
        return self


class ContractTrustAnchorRegistry(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    version: Literal["phase7f-anchor-registry-v2"] = "phase7f-anchor-registry-v2"
    authority_registry_hash: str = Field(pattern=SHA256)
    anchors: tuple[TrustAnchor, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        keys = tuple((x.anchor_id, x.source_system_id) for x in self.anchors)
        _unique(tuple(x.anchor_id for x in self.anchors), "global anchor IDs")
        if keys != tuple(sorted(keys)):
            raise ValueError("anchors not canonically ordered")
        if self.registry_hash != typed_hash(
            self.model_dump(mode="json", exclude={"registry_hash"})
        ):
            raise ValueError("anchor registry hash mismatch")
        return self


class AnchorBinding(ContractModel):
    anchor_id: str = Field(pattern=OID)
    source_system_id: str = Field(pattern=OID)
    anchor_version: Literal["phase7f-trust-anchor-v2"]
    anchor_hash: str = Field(pattern=SHA256)
    anchor_registry_version: Literal["phase7f-anchor-registry-v2"]
    anchor_registry_hash: str = Field(pattern=SHA256)


class ReviewerIdentity(ContractModel):
    actor_id: str = Field(pattern=r"^actor_[a-z0-9]{8,64}$")
    aliases: tuple[str, ...]
    roles: tuple[ReviewerRole, ...]
    valid_from: dt.datetime
    valid_until: dt.datetime | None = None
    revoked_at: dt.datetime | None = None

    @model_validator(mode="after")
    def check(self):
        _aware(self.valid_from, "reviewer valid_from")
        if self.valid_until:
            _aware(self.valid_until, "reviewer valid_until")
        if self.revoked_at:
            _aware(self.revoked_at, "reviewer revoked_at")
        normalized = tuple(_alias(x) for x in self.aliases)
        _unique(normalized, "aliases")
        _unique(self.roles, "roles")
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("invalid reviewer window")
        return self


class ContractReviewerIdentityRegistry(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    version: Literal["phase7f-reviewer-registry-v2"] = "phase7f-reviewer-registry-v2"
    registry_id: str = Field(pattern=OID)
    authority: AuthorityBinding
    anchor: AnchorBinding
    valid_from: dt.datetime
    valid_until: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    identities: tuple[ReviewerIdentity, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.valid_from, "reviewer registry valid_from")
        if self.valid_until:
            _aware(self.valid_until, "reviewer registry valid_until")
        if self.revoked_at:
            _aware(self.revoked_at, "reviewer registry revoked_at")
        ids = tuple(x.actor_id for x in self.identities)
        _unique(ids, "actor IDs")
        if ids != tuple(sorted(ids)):
            raise ValueError("actors not canonically ordered")
        aliases = [_alias(a) for x in self.identities for a in x.aliases]
        if len(aliases) != len(set(aliases)):
            raise ValueError("reviewer alias is ambiguous after NFKC normalization")
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("invalid reviewer registry window")
        if self.registry_hash != typed_hash(
            self.model_dump(mode="json", exclude={"registry_hash"})
        ):
            raise ValueError("reviewer registry hash mismatch")
        return self


class ScopeCoverage(ContractModel):
    version: Literal["phase7f-scope-v1"] = "phase7f-scope-v1"
    scope_id: str = Field(pattern=OID)
    dimensions: tuple[str, ...]
    coverage_start: dt.datetime
    coverage_end: dt.datetime
    completeness_claim: Literal["DECLARED_ONLY"] = "DECLARED_ONLY"
    scope_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.coverage_start, "coverage_start")
        _aware(self.coverage_end, "coverage_end")
        _unique(self.dimensions, "dimensions")
        if self.dimensions != tuple(sorted(self.dimensions)):
            raise ValueError("dimensions not canonically ordered")
        if self.coverage_end < self.coverage_start:
            raise ValueError("invalid coverage window")
        if self.scope_hash != typed_hash(self.model_dump(mode="json", exclude={"scope_hash"})):
            raise ValueError("scope hash mismatch")
        return self


class ContractPolicy(ContractModel):
    version: Literal["phase7f-policy-v1"] = "phase7f-policy-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    policy_id: str = Field(pattern=OID)
    policy_version: str = Field(pattern=OID)
    authority: AuthorityBinding
    effective_from: dt.datetime
    effective_until: dt.datetime | None = None
    required_gates: tuple[EvidenceGate, ...]
    policy_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.effective_from, "policy effective_from")
        if self.effective_until:
            _aware(self.effective_until, "policy effective_until")
        if self.required_gates != tuple(EvidenceGate):
            raise ValueError("policy gates must be complete and canonical")
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("invalid policy window")
        if self.policy_hash != typed_hash(self.model_dump(mode="json", exclude={"policy_hash"})):
            raise ValueError("policy hash mismatch")
        return self


class ProviderDatasetCandidate(ContractModel):
    version: Literal["phase7f-onboarding-v2"] = "phase7f-onboarding-v2"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    candidate_id: str = Field(pattern=OID)
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope: ScopeCoverage
    policy_id: str = Field(pattern=OID)
    policy_version: str = Field(pattern=OID)
    policy_hash: str = Field(pattern=SHA256)
    required_anchors: tuple[AnchorBinding, ...]
    required_gates: tuple[EvidenceGate, ...]
    declared_at: dt.datetime
    candidate_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.declared_at, "candidate declared_at")
        keys = tuple((x.anchor_id, x.source_system_id) for x in self.required_anchors)
        _unique(keys, "anchor bindings")
        if keys != tuple(sorted(keys)):
            raise ValueError("anchor bindings not ordered")
        if self.required_gates != tuple(EvidenceGate):
            raise ValueError("candidate gates must be complete and canonical")
        if self.candidate_hash != typed_hash(
            self.model_dump(mode="json", exclude={"candidate_hash"})
        ):
            raise ValueError("candidate hash mismatch")
        return self


class ArtifactRequest(ContractModel):
    version: Literal["phase7f-request-v2"] = "phase7f-request-v2"
    request_id: str = Field(pattern=OID)
    candidate_id: str = Field(pattern=OID)
    candidate_hash: str = Field(pattern=SHA256)
    anchor: AnchorBinding
    canonical_source_id: str = Field(min_length=1)
    artifact_id: str = Field(pattern=OID)
    artifact_class: ArtifactClass
    artifact_version: str = Field(pattern=OID)
    gate: EvidenceGate
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    scope_hash: str = Field(pattern=SHA256)
    policy_id: str = Field(pattern=OID)
    policy_version: str = Field(pattern=OID)
    policy_hash: str = Field(pattern=SHA256)
    as_of: dt.datetime

    @model_validator(mode="after")
    def check(self):
        _aware(self.as_of, "request as_of")
        return self


class CustodyRecord(ContractModel):
    version: Literal["phase7f-custody-v1"] = "phase7f-custody-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    custody_record_id: str = Field(pattern=OID)
    authority: AuthorityBinding
    anchor: AnchorBinding
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    artifact_id: str = Field(pattern=OID)
    artifact_version: str = Field(pattern=OID)
    gate: EvidenceGate
    scope_id: str = Field(pattern=OID)
    as_of: dt.datetime
    effective_at: dt.datetime
    available_at: dt.datetime
    source_sha256: str = Field(pattern=SHA256)
    immutability_declaration: Literal["DECLARED_ONLY"] = "DECLARED_ONLY"
    object_lock_declaration: Literal["NOT_EXTERNALLY_PROVEN"] = "NOT_EXTERNALLY_PROVEN"
    custody_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.as_of, "custody as_of")
        _aware(self.effective_at, "custody effective_at")
        _aware(self.available_at, "custody available_at")
        if self.effective_at > self.available_at:
            raise ValueError("invalid custody time order")
        if self.custody_hash != typed_hash(self.model_dump(mode="json", exclude={"custody_hash"})):
            raise ValueError("custody hash mismatch")
        return self


class ResolvedArtifact(ContractModel):
    version: Literal["phase7f-artifact-v2"] = "phase7f-artifact-v2"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    request_hash: str = Field(pattern=SHA256)
    canonical_source_id: str = Field(min_length=1)
    artifact_id: str = Field(pattern=OID)
    artifact_version: str = Field(pattern=OID)
    retrieved_at: dt.datetime
    custody: CustodyRecord
    source_bytes_hex: str = Field(pattern=r"^(?:[0-9a-f]{2})+$")
    source_sha256: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.retrieved_at, "artifact retrieved_at")
        if hashlib.sha256(bytes.fromhex(self.source_bytes_hex)).hexdigest() != self.source_sha256:
            raise ValueError("source integrity mismatch")
        return self


class ReviewDecision(ContractModel):
    version: Literal["phase7f-decision-v2"] = "phase7f-decision-v2"
    candidate_id: str = Field(pattern=OID)
    candidate_hash: str = Field(pattern=SHA256)
    request_hash: str = Field(pattern=SHA256)
    artifact_hash: str = Field(pattern=SHA256)
    gate: EvidenceGate
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    scope_hash: str = Field(pattern=SHA256)
    policy_id: str = Field(pattern=OID)
    policy_version: str = Field(pattern=OID)
    policy_hash: str = Field(pattern=SHA256)
    reviewer_registry_hash: str = Field(pattern=SHA256)
    maker_claim: str
    checker_claim: str
    decided_at: dt.datetime
    decision: Literal["ACCEPT", "REJECT"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.decided_at, "decision decided_at")
        if self.decision_hash != typed_hash(
            self.model_dump(mode="json", exclude={"decision_hash"})
        ):
            raise ValueError("decision hash mismatch")
        return self


class IndependentAuditRecord(ContractModel):
    version: Literal["phase7f-audit-v1"] = "phase7f-audit-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    audit_id: str = Field(pattern=OID)
    auditor_claim: str
    audited_at: dt.datetime
    verifier_time: dt.datetime
    policy_version: str = Field(pattern=OID)
    snapshot_hash: str = Field(pattern=SHA256)
    verdict: Literal["APPROVE", "REJECT"]
    audit_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.audited_at, "audit audited_at")
        _aware(self.verifier_time, "audit verifier_time")
        if self.audit_hash != typed_hash(self.model_dump(mode="json", exclude={"audit_hash"})):
            raise ValueError("audit hash mismatch")
        return self


class AdmissionStageRecord(ContractModel):
    stage: AdmissionStage
    evidence_hash: str = Field(pattern=SHA256)


class ContractAdmissionResult(ContractModel):
    """Non-authoritative output DTO; verifier results must never be accepted as input."""

    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    stage_records: tuple[AdmissionStageRecord, ...]
    gate: EvidenceGate
    real_gate_state: Literal[GateState.OPEN_EXTERNAL] = GateState.OPEN_EXTERNAL
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"

    @model_validator(mode="after")
    def check(self):
        stages = tuple(x.stage for x in self.stage_records)
        if stages != CANONICAL_ADMISSION_ORDER[: len(stages)]:
            raise ValueError("stages must be canonical prefix")
        return self

    @computed_field
    @property
    def admission_complete(self) -> bool:
        return tuple(x.stage for x in self.stage_records) == CANONICAL_ADMISSION_ORDER

    @computed_field
    @property
    def mechanics_valid(self) -> bool:
        return self.admission_complete


T = TypeVar("T", bound=BaseModel)


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise Phase7FContractError("input is not canonically serializable") from exc


def _revalidate(expected: type[T], value: Any, label: str) -> T:
    try:
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError) as exc:
        raise Phase7FContractError(f"invalid {label}") from exc


def _authority(registry, binding, capability, at):
    if (
        binding.authority_registry_version != registry.version
        or binding.authority_registry_hash != registry.registry_hash
    ):
        return None
    found = [x for x in registry.authorities if x.authority_id == binding.authority_id]
    if len(found) != 1:
        return None
    item = found[0]
    if (
        binding.authority_hash != item.authority_hash
        or binding.provenance_hash != item.provenance.provenance_hash
        or capability not in item.capabilities
        or not _active(item.valid_from, item.valid_until, item.revoked_at, at)
    ):
        return None
    return item


def _anchor(registry, binding):
    if (
        binding.anchor_registry_version != registry.version
        or binding.anchor_registry_hash != registry.registry_hash
    ):
        return None
    found = [
        x
        for x in registry.anchors
        if (x.anchor_id, x.source_system_id) == (binding.anchor_id, binding.source_system_id)
    ]
    if len(found) != 1:
        return None
    item = found[0]
    return (
        item
        if (binding.anchor_version, binding.anchor_hash) == (item.version, item.anchor_hash)
        else None
    )


def _actor(registry, claim, role, at):
    name = _alias(claim)
    found = [
        x
        for x in registry.identities
        if name == x.actor_id or name in {_alias(a) for a in x.aliases}
    ]
    if len(found) != 1:
        return None
    item = found[0]
    return (
        item.actor_id
        if role in item.roles and _active(item.valid_from, item.valid_until, item.revoked_at, at)
        else None
    )


def admission_snapshot_hash(
    authorities, anchors, candidate, policy, request, artifact, decision, reviewers, verifier_time
):
    """Full canonical audit binding; consistency only, never authenticity."""
    return typed_hash(
        {
            "authority_registry": authorities.model_dump(mode="json"),
            "anchor_registry": anchors.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "reviewer_registry": reviewers.model_dump(mode="json"),
            "verifier_time": verifier_time.isoformat(),
            "contract_version": PHASE7F_CONTRACT_VERSION,
        }
    )


def _result(gate, stages):
    return ContractAdmissionResult(stage_records=tuple(stages), gate=gate)


def _stage(stages, kind, digest):
    stages.append(AdmissionStageRecord(stage=kind, evidence_hash=digest))


def verify_contract_admission(
    candidate: Any,
    authority_registry: Any,
    anchor_registry: Any,
    reviewer_registry: Any,
    policy: Any,
    request: Any,
    artifact: Any,
    decision: Any,
    audit: Any | None,
    *,
    verifier_time: dt.datetime,
) -> ContractAdmissionResult:
    """Revalidate primitive snapshots and derive an ordered, fail-closed stage prefix."""
    if verifier_time.tzinfo is None or verifier_time.utcoffset() is None:
        raise Phase7FContractError("verifier time must be timezone-aware")
    candidate = _revalidate(ProviderDatasetCandidate, candidate, "candidate")
    authorities = _revalidate(ContractAuthorityRegistry, authority_registry, "authority registry")
    anchors = _revalidate(ContractTrustAnchorRegistry, anchor_registry, "anchor registry")
    reviewers = _revalidate(
        ContractReviewerIdentityRegistry, reviewer_registry, "reviewer registry"
    )
    policy = _revalidate(ContractPolicy, policy, "policy")
    request = _revalidate(ArtifactRequest, request, "request")
    artifact = _revalidate(ResolvedArtifact, artifact, "artifact")
    decision = _revalidate(ReviewDecision, decision, "decision")
    audit = None if audit is None else _revalidate(IndependentAuditRecord, audit, "audit")
    stages = []
    if not _active(
        authorities.valid_from, authorities.valid_until, authorities.revoked_at, verifier_time
    ):
        return _result(request.gate, stages)
    _stage(stages, AdmissionStage.AUTHORITY_REGISTRY_VERIFIED, authorities.registry_hash)

    anchor = _anchor(anchors, request.anchor)
    if not (
        anchor
        and anchors.authority_registry_hash == authorities.registry_hash
        and _authority(authorities, anchor.authority, AuthorityCapability.ANCHOR, verifier_time)
        and _active(anchor.activated_at, anchor.valid_until, anchor.revoked_at, verifier_time)
        and request.artifact_class in anchor.artifact_classes
    ):
        return _result(request.gate, stages)
    _stage(stages, AdmissionStage.TRUST_ANCHOR_VERIFIED, anchors.registry_hash)

    onboarding = (
        _authority(authorities, policy.authority, AuthorityCapability.POLICY, verifier_time)
        and _active(policy.effective_from, policy.effective_until, None, verifier_time)
        and candidate.declared_at <= request.as_of <= verifier_time
        and candidate.scope.coverage_start <= request.as_of <= candidate.scope.coverage_end
        and request.anchor in candidate.required_anchors
        and request.gate in candidate.required_gates
        and (
            request.candidate_id,
            request.candidate_hash,
            request.provider_id,
            request.dataset_id,
            request.dataset_version,
            request.scope_id,
            request.scope_hash,
            request.policy_id,
            request.policy_version,
            request.policy_hash,
        )
        == (
            candidate.candidate_id,
            candidate.candidate_hash,
            candidate.provider_id,
            candidate.dataset_id,
            candidate.dataset_version,
            candidate.scope.scope_id,
            candidate.scope.scope_hash,
            candidate.policy_id,
            candidate.policy_version,
            candidate.policy_hash,
        )
        and (candidate.policy_id, candidate.policy_version, candidate.policy_hash)
        == (policy.policy_id, policy.policy_version, policy.policy_hash)
    )
    if not onboarding:
        return _result(request.gate, stages)
    _stage(stages, AdmissionStage.ONBOARDING_VERIFIED, candidate.candidate_hash)

    custody = artifact.custody
    request_hash = typed_hash(request.model_dump(mode="json"))
    artifact_hash = typed_hash(artifact.model_dump(mode="json"))
    custody_ok = (
        _authority(authorities, custody.authority, AuthorityCapability.CUSTODY, verifier_time)
        and _anchor(anchors, custody.anchor)
        and custody.anchor == request.anchor
        and artifact.request_hash == request_hash
        and artifact.canonical_source_id == request.canonical_source_id
        and (artifact.artifact_id, artifact.artifact_version)
        == (request.artifact_id, request.artifact_version)
        and artifact.source_sha256
        == custody.source_sha256
        == hashlib.sha256(bytes.fromhex(artifact.source_bytes_hex)).hexdigest()
        and (
            custody.provider_id,
            custody.dataset_id,
            custody.artifact_id,
            custody.artifact_version,
            custody.gate,
            custody.scope_id,
            custody.as_of,
        )
        == (
            request.provider_id,
            request.dataset_id,
            request.artifact_id,
            request.artifact_version,
            request.gate,
            request.scope_id,
            request.as_of,
        )
        and custody.available_at <= artifact.retrieved_at <= verifier_time
    )
    if not custody_ok:
        return _result(request.gate, stages)
    _stage(stages, AdmissionStage.ARTIFACT_CUSTODY_VERIFIED, custody.custody_hash)

    registry_ok = (
        _authority(authorities, reviewers.authority, AuthorityCapability.REVIEWERS, verifier_time)
        and _anchor(anchors, reviewers.anchor)
        and reviewers.anchor in candidate.required_anchors
        and _active(
            reviewers.valid_from, reviewers.valid_until, reviewers.revoked_at, decision.decided_at
        )
        and _active(
            reviewers.valid_from, reviewers.valid_until, reviewers.revoked_at, verifier_time
        )
    )
    maker_then = _actor(reviewers, decision.maker_claim, ReviewerRole.MAKER, decision.decided_at)
    checker_then = _actor(
        reviewers, decision.checker_claim, ReviewerRole.CHECKER, decision.decided_at
    )
    maker_now = _actor(reviewers, decision.maker_claim, ReviewerRole.MAKER, verifier_time)
    checker_now = _actor(reviewers, decision.checker_claim, ReviewerRole.CHECKER, verifier_time)
    decision_ok = (
        registry_ok
        and maker_then
        and checker_then
        and maker_now == maker_then
        and checker_now == checker_then
        and maker_now != checker_now
        and decision.decision == "ACCEPT"
        and decision.decided_at <= verifier_time
        and decision.reviewer_registry_hash == reviewers.registry_hash
        and (
            decision.candidate_id,
            decision.candidate_hash,
            decision.request_hash,
            decision.artifact_hash,
            decision.gate,
            decision.provider_id,
            decision.dataset_id,
            decision.dataset_version,
            decision.scope_id,
            decision.scope_hash,
            decision.policy_id,
            decision.policy_version,
            decision.policy_hash,
        )
        == (
            candidate.candidate_id,
            candidate.candidate_hash,
            request_hash,
            artifact_hash,
            request.gate,
            candidate.provider_id,
            candidate.dataset_id,
            candidate.dataset_version,
            candidate.scope.scope_id,
            candidate.scope.scope_hash,
            policy.policy_id,
            policy.policy_version,
            policy.policy_hash,
        )
    )
    if not decision_ok:
        return _result(request.gate, stages)
    _stage(stages, AdmissionStage.MAKER_CHECKER_VERIFIED, decision.decision_hash)

    auditor = (
        None
        if audit is None
        else _actor(reviewers, audit.auditor_claim, ReviewerRole.INDEPENDENT_AUDITOR, verifier_time)
    )
    snapshot = admission_snapshot_hash(
        authorities,
        anchors,
        candidate,
        policy,
        request,
        artifact,
        decision,
        reviewers,
        verifier_time,
    )
    audit_ok = (
        audit
        and auditor
        and auditor not in {maker_now, checker_now}
        and audit.verdict == "APPROVE"
        and decision.decided_at <= audit.audited_at <= verifier_time
        and audit.verifier_time == verifier_time
        and audit.policy_version == PHASE7F_CONTRACT_VERSION
        and audit.snapshot_hash == snapshot
    )
    if not audit_ok:
        return _result(request.gate, stages)
    _stage(stages, AdmissionStage.INDEPENDENT_AUDIT_VERIFIED, audit.audit_hash)
    _stage(
        stages,
        AdmissionStage.ADMISSION_COMPLETE,
        typed_hash([x.model_dump(mode="json") for x in stages]),
    )
    return _result(request.gate, stages)


def real_external_authority_verifier_unavailable() -> Literal[False]:
    """No duck-typed or caller-injectable REAL trust capability exists."""
    return False
