"""Governed sufficient-observation policy foundation.

This module evaluates content-addressed contract evidence.  It cannot approve a
REAL policy, admit a provider, close a gate, or establish external truth.
"""

from __future__ import annotations

import datetime as dt
import json
import unicodedata
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.ibkr_external_attestation import ProvisioningState
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "governed-sufficient-observation-policy-v4"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{1,127}$"
OPAQUE = r"^opaque:v1:[0-9a-f]{64}$"
COUNTING_SEMANTICS_VERSION = "canonical-upstream-event-required-v4"
SOURCE_EVENT_RESOLVER_VERSION = "canonical-upstream-source-event-resolver-v2"
DEPENDENCY_RESOLVER_VERSION = "canonical-upstream-dependency-resolver-v2"
DEPENDENCY_CONTRACTS = {
    "TRUST_VERIFIER": ("external-trust-attestation-independent-verifier", "v1"),
    "AUTHORITY_REGISTRY": ("trust-anchor-authority-contract", "v1"),
    "LEGAL_RIGHT": ("licensing-legal-governance", "v2"),
    "CUSTODY_WORM_REPLAY": ("durable-custody-worm-replay", "v1"),
}


class ObservationPolicyError(ValueError):
    """Untrusted policy material failed closed without reflecting its contents."""


class PolicyStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_FOR_EVIDENCE_COLLECTION = "APPROVED_FOR_EVIDENCE_COLLECTION"


class ObservationClass(StrEnum):
    REAL_MARKET = "REAL_MARKET"
    FX = "FX"
    SHARES_OUTSTANDING_PIT = "SHARES_OUTSTANDING_PIT"
    HISTORICAL_COVERAGE = "HISTORICAL_COVERAGE"
    OPERATIONS = "OPERATIONS"
    CUSTODY_REPLAY = "CUSTODY_REPLAY"
    LEGAL_LICENSING = "LEGAL_LICENSING"


class MarketDataMode(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DELAYED = "DELAYED"
    REALTIME = "REALTIME"


class DependencyState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_PROVISIONED = "NOT_PROVISIONED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONTRACT_TEST_VALIDATED = "CONTRACT_TEST_VALIDATED"
    EXTERNALLY_VERIFIED = "EXTERNALLY_VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DependencyKind(StrEnum):
    TRUST_VERIFIER = "TRUST_VERIFIER"
    AUTHORITY_REGISTRY = "AUTHORITY_REGISTRY"
    LEGAL_RIGHT = "LEGAL_RIGHT"
    CUSTODY_WORM_REPLAY = "CUSTODY_WORM_REPLAY"


class DependencyAssurance(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


class SourceEventAssurance(StrEnum):
    SYNTHETIC_TEST_EVENT_IDENTITY = "SYNTHETIC_TEST_EVENT_IDENTITY"
    CANONICAL_UPSTREAM_OBSERVATION = "CANONICAL_UPSTREAM_OBSERVATION"


class EvaluationState(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUFFICIENT_FOR_EXTERNAL_VERIFICATION = "SUFFICIENT_FOR_EXTERNAL_VERIFICATION"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class ReasonCode(StrEnum):
    NO_OBSERVATIONS = "NO_OBSERVATIONS"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    SAME_WINDOW_CONFLICT = "SAME_WINDOW_CONFLICT"
    PROVIDER_MISMATCH = "PROVIDER_MISMATCH"
    DATASET_MISMATCH = "DATASET_MISMATCH"
    MODE_MISMATCH = "MODE_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    POLICY_VERSION_MISMATCH = "POLICY_VERSION_MISMATCH"
    BEFORE_POLICY_EFFECTIVE = "BEFORE_POLICY_EFFECTIVE"
    OUTSIDE_POLICY_WINDOW = "OUTSIDE_POLICY_WINDOW"
    FUTURE_OBSERVATION = "FUTURE_OBSERVATION"
    EVIDENCE_NOT_AVAILABLE_AS_OF = "EVIDENCE_NOT_AVAILABLE_AS_OF"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    TRUST_NOT_PROVISIONED = "TRUST_NOT_PROVISIONED"
    TRUST_REVIEW_REQUIRED = "TRUST_REVIEW_REQUIRED"
    LEGAL_NOT_PROVISIONED = "LEGAL_NOT_PROVISIONED"
    LEGAL_REVIEW_REQUIRED = "LEGAL_REVIEW_REQUIRED"
    CUSTODY_NOT_PROVISIONED = "CUSTODY_NOT_PROVISIONED"
    CUSTODY_REVIEW_REQUIRED = "CUSTODY_REVIEW_REQUIRED"
    DEPENDENCY_BINDING_MISMATCH = "DEPENDENCY_BINDING_MISMATCH"
    DEPENDENCY_NOT_AVAILABLE_AS_OF = "DEPENDENCY_NOT_AVAILABLE_AS_OF"
    SOURCE_EVENT_NOT_PROVISIONED = "SOURCE_EVENT_NOT_PROVISIONED"
    SOURCE_EVENT_REVIEW_REQUIRED = "SOURCE_EVENT_REVIEW_REQUIRED"
    DEPENDENCY_ARTIFACT_NOT_PROVISIONED = "DEPENDENCY_ARTIFACT_NOT_PROVISIONED"
    DEPENDENCY_ARTIFACT_REVIEW_REQUIRED = "DEPENDENCY_ARTIFACT_REVIEW_REQUIRED"
    COUNT_BELOW_MINIMUM = "COUNT_BELOW_MINIMUM"
    DISTINCT_SESSIONS_BELOW_MINIMUM = "DISTINCT_SESSIONS_BELOW_MINIMUM"
    DISTINCT_DATES_BELOW_MINIMUM = "DISTINCT_DATES_BELOW_MINIMUM"
    TIME_SPAN_BELOW_MINIMUM = "TIME_SPAN_BELOW_MINIMUM"
    MISSINGNESS_EXCEEDED = "MISSINGNESS_EXCEEDED"
    POLICY_NOT_COLLECTION_APPROVED = "POLICY_NOT_COLLECTION_APPROVED"
    EXTERNAL_POLICY_APPROVAL_NOT_PROVISIONED = "EXTERNAL_POLICY_APPROVAL_NOT_PROVISIONED"
    READY_FOR_EXTERNAL_VERIFICATION = "READY_FOR_EXTERNAL_VERIFICATION"


CLASS_GATE = {
    ObservationClass.REAL_MARKET: EvidenceGate.HISTORICAL_PIT_SECURITY_MASTER,
    ObservationClass.FX: EvidenceGate.REAL_FX,
    ObservationClass.SHARES_OUTSTANDING_PIT: EvidenceGate.SHARES_OUTSTANDING_PIT,
    ObservationClass.HISTORICAL_COVERAGE: EvidenceGate.HISTORICAL_COMPLETENESS,
    ObservationClass.OPERATIONS: EvidenceGate.OPERATIONS_MONITORING,
    ObservationClass.CUSTODY_REPLAY: EvidenceGate.RETENTION_WORM,
    ObservationClass.LEGAL_LICENSING: EvidenceGate.LICENSING_LEGAL,
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - hostile input may contain secrets
            raise ObservationPolicyError("invalid sufficient-observation value") from None

    def __repr_args__(self):
        return [("redacted", True)]

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False):
        raw = BaseModel.model_dump(self, mode="python")
        if update:
            raw.update(update)
        del deep
        return type(self).model_validate(raw)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any):
        del _fields_set
        return cls.model_validate(values)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        try:
            return super().model_validate(obj, **kwargs)
        except BaseException:  # noqa: BLE001
            raise ObservationPolicyError("invalid sufficient-observation value") from None

    @classmethod
    def model_validate_json(cls, value: str | bytes | bytearray, **kwargs: Any):
        try:
            return super().model_validate_json(value, **kwargs)
        except BaseException:  # noqa: BLE001
            raise ObservationPolicyError("invalid sufficient-observation value") from None


class GateCriterion(_Model):
    criterion_id: str = Field(pattern=IDENTIFIER)
    gate: EvidenceGate
    observation_class: ObservationClass
    capability_id: str = Field(pattern=IDENTIFIER)
    allowed_provider_refs: tuple[str, ...]
    allowed_dataset_refs: tuple[str, ...]
    allowed_modes: tuple[MarketDataMode, ...]
    allow_cross_provider_aggregation: bool = False
    allow_cross_dataset_aggregation: bool = False
    minimum_observation_count: int = Field(ge=1)
    minimum_distinct_sessions: int = Field(ge=1)
    minimum_distinct_dates: int = Field(ge=1)
    minimum_time_span: dt.timedelta = Field(ge=dt.timedelta(0))
    maximum_age: dt.timedelta = Field(gt=dt.timedelta(0))
    maximum_missing_fraction_ppm: int = Field(ge=0, le=1_000_000)
    required_provenance_fields: tuple[str, ...]
    minimum_trust_state: Literal[DependencyState.CONTRACT_TEST_VALIDATED]
    require_authority_registry: bool
    require_legal_rights: bool
    require_custody_worm_replay: bool
    allow_grandfathering: bool = False
    rationale_digest: str = Field(pattern=SHA256)
    criterion_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.criterion_id, self.capability_id, *self.allowed_provider_refs,
             *self.allowed_dataset_refs, *self.required_provenance_fields)
        _opaque_values(*self.allowed_provider_refs, *self.allowed_dataset_refs)
        if CLASS_GATE[self.observation_class] is not self.gate:
            raise ValueError
        if not self.allowed_provider_refs or not self.allowed_dataset_refs or not self.allowed_modes:
            raise ValueError
        if len(set(self.allowed_provider_refs)) != len(self.allowed_provider_refs):
            raise ValueError
        if len(set(self.allowed_dataset_refs)) != len(self.allowed_dataset_refs):
            raise ValueError
        if len(set(self.allowed_modes)) != len(self.allowed_modes):
            raise ValueError
        if not self.required_provenance_fields:
            raise ValueError
        _hash(self, "criterion_hash")
        return self


class SufficientObservationPolicy(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    counting_semantics_version: Literal[COUNTING_SEMANTICS_VERSION] = COUNTING_SEMANTICS_VERSION
    source_event_resolver_version: Literal[SOURCE_EVENT_RESOLVER_VERSION] = (
        SOURCE_EVENT_RESOLVER_VERSION
    )
    dependency_resolver_version: Literal[DEPENDENCY_RESOLVER_VERSION] = (
        DEPENDENCY_RESOLVER_VERSION
    )
    status: PolicyStatus
    created_at: dt.datetime
    reviewed_at: dt.datetime | None = None
    effective_from: dt.datetime
    effective_to: dt.datetime | None = None
    jurisdiction_context_ref: str = Field(pattern=OPAQUE)
    use_context_ref: str = Field(pattern=OPAQUE)
    criteria: tuple[GateCriterion, ...]
    maker_actor_hash: str = Field(pattern=SHA256)
    reviewer_actor_hash: str | None = Field(default=None, pattern=SHA256)
    approver_actor_hash: str | None = Field(default=None, pattern=SHA256)
    review_evidence_digest: str | None = Field(default=None, pattern=SHA256)
    exception_policy_ref: str = Field(pattern=IDENTIFIER)
    replacement_policy_hash: str | None = Field(default=None, pattern=SHA256)
    revoked_at: dt.datetime | None = None
    revocation_evidence_digest: str | None = Field(default=None, pattern=SHA256)
    real_approval_state: Literal[ProvisioningState.NOT_PROVISIONED] = (
        ProvisioningState.NOT_PROVISIONED
    )
    content_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.policy_id, self.policy_version, self.counting_semantics_version,
             self.source_event_resolver_version, self.dependency_resolver_version,
             self.exception_policy_ref)
        _opaque_values(self.jurisdiction_context_ref, self.use_context_ref)
        for value in (self.created_at, self.reviewed_at, self.effective_from, self.effective_to,
                      self.revoked_at):
            if value is not None:
                _utc(value)
        if self.created_at > self.effective_from:
            raise ValueError
        if self.effective_to is not None and self.effective_from >= self.effective_to:
            raise ValueError
        if self.revoked_at is not None and self.revoked_at < self.effective_from:
            raise ValueError
        if bool(self.revoked_at) != bool(self.revocation_evidence_digest):
            raise ValueError
        if ({item.observation_class for item in self.criteria} != set(ObservationClass)
                or {item.gate for item in self.criteria} != set(CLASS_GATE.values())):
            raise ValueError
        if tuple(sorted(self.criteria, key=lambda item: item.gate.value)) != self.criteria:
            raise ValueError
        actors = tuple(x for x in (
            self.maker_actor_hash, self.reviewer_actor_hash, self.approver_actor_hash
        ) if x is not None)
        if self.status is PolicyStatus.DRAFT:
            if self.reviewed_at is not None or len(actors) != 1 or self.review_evidence_digest:
                raise ValueError
        elif self.status is PolicyStatus.REVIEW_REQUIRED:
            if self.approver_actor_hash is not None or self.review_evidence_digest is not None:
                raise ValueError
        else:
            if (self.reviewed_at is None or len(actors) != 3 or len(set(actors)) != 3
                    or self.review_evidence_digest is None):
                raise ValueError
            if not self.created_at <= self.reviewed_at <= self.effective_from:
                raise ValueError
        _hash(self, "content_hash")
        return self


class SourceEventIdentityRecord(_Model):
    """Synthetic Step5 fixture index; never authority for event independence."""

    resolver_version: Literal[SOURCE_EVENT_RESOLVER_VERSION] = SOURCE_EVENT_RESOLVER_VERSION
    assurance: Literal[SourceEventAssurance.SYNTHETIC_TEST_EVENT_IDENTITY]
    canonical_upstream_observation_digest: None = None
    provider_ref: str = Field(pattern=OPAQUE)
    instrument_ref: str = Field(pattern=OPAQUE)
    dataset_ref: str = Field(pattern=OPAQUE)
    observation_type: str = Field(pattern=IDENTIFIER)
    provider_event_key_ref: str = Field(pattern=OPAQUE)
    canonical_event_key: str = Field(pattern=SHA256)
    session_ref: str = Field(pattern=IDENTIFIER)
    session_date: dt.date
    window_start: dt.datetime
    window_end: dt.datetime
    available_at: dt.datetime
    market_data_mode: MarketDataMode
    payload_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    attestation_ref_digest: str = Field(pattern=SHA256)
    custody_lineage_digest: str = Field(pattern=SHA256)
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    counting_semantics_version: Literal[COUNTING_SEMANTICS_VERSION]
    aliases: tuple[str, ...] = ()
    record_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.observation_type, self.session_ref, self.policy_id, self.policy_version,
             self.counting_semantics_version, self.resolver_version)
        _opaque_values(self.provider_ref, self.instrument_ref, self.dataset_ref,
                       self.provider_event_key_ref)
        _utc(self.window_start)
        _utc(self.window_end)
        _utc(self.available_at)
        if self.window_start > self.window_end or self.available_at < self.window_end:
            raise ValueError
        if self.session_date != self.window_start.date():
            raise ValueError
        if len(set(self.aliases)) != len(self.aliases) or self.record_digest in self.aliases:
            raise ValueError
        if any(not _is_sha256(value) for value in self.aliases):
            raise ValueError
        expected_key = typed_hash({
            "provider": self.provider_ref,
            "instrument": self.instrument_ref,
            "dataset": self.dataset_ref,
            "observation_type": self.observation_type,
            "provider_event_key": self.provider_event_key_ref,
        })
        if self.canonical_event_key != expected_key:
            raise ValueError
        _hash(self, "record_digest")
        return self


class DependencyArtifactRecord(_Model):
    """Legacy local wrapper. It is never accepted as resolver membership or truth."""

    resolver_version: Literal[DEPENDENCY_RESOLVER_VERSION] = DEPENDENCY_RESOLVER_VERSION
    assurance: Literal[DependencyAssurance.CONTRACT_TEST_ONLY]
    kind: DependencyKind
    source_contract: str = Field(pattern=IDENTIFIER)
    source_contract_version: str = Field(pattern=IDENTIFIER)
    canonical_schema: str = Field(pattern=IDENTIFIER)
    provider_ref: str = Field(pattern=OPAQUE)
    dataset_ref: str = Field(pattern=OPAQUE)
    route_ref: str = Field(pattern=OPAQUE)
    entity_ref: str = Field(pattern=OPAQUE)
    capability_id: str = Field(pattern=IDENTIFIER)
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    source_event_ref_digest: str = Field(pattern=SHA256)
    payload_digest: str = Field(pattern=SHA256)
    available_at: dt.datetime
    effective_at: dt.datetime
    verified_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    contract_provenance_digest: str = Field(pattern=SHA256)
    artifact_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.resolver_version, self.source_contract, self.source_contract_version,
             self.canonical_schema, self.capability_id, self.policy_id, self.policy_version)
        expected_contract = DEPENDENCY_CONTRACTS[self.kind]
        if (self.source_contract, self.source_contract_version) != expected_contract:
            raise ValueError
        if self.canonical_schema != f"{self.source_contract}.{self.source_contract_version}":
            raise ValueError
        expected_provenance = typed_hash({
            "kind": self.kind,
            "source_contract": self.source_contract,
            "source_contract_version": self.source_contract_version,
            "canonical_schema": self.canonical_schema,
            "assurance": DependencyAssurance.CONTRACT_TEST_ONLY,
        })
        if self.contract_provenance_digest != expected_provenance:
            raise ValueError
        _opaque_values(self.provider_ref, self.dataset_ref, self.route_ref, self.entity_ref)
        for value in (self.available_at, self.effective_at, self.verified_at,
                      self.expires_at, self.revoked_at):
            if value is not None:
                _utc(value)
        if not self.available_at <= self.effective_at <= self.verified_at < self.expires_at:
            raise ValueError
        if self.revoked_at is not None and self.revoked_at < self.available_at:
            raise ValueError
        _hash(self, "artifact_digest")
        return self


class SourceEventResolver(Protocol):
    resolver_version: str

    def resolve(self, reference: str) -> SourceEventIdentityRecord | None: ...


class DependencyArtifactResolver(Protocol):
    resolver_version: str

    def resolve(self, reference: str) -> DependencyArtifactRecord | None: ...


class ContractTestSourceEventResolver:
    resolver_version = SOURCE_EVENT_RESOLVER_VERSION

    def __init__(self, records: tuple[SourceEventIdentityRecord, ...]):
        resolved = tuple(_deep(SourceEventIdentityRecord, item) for item in records)
        index: dict[str, SourceEventIdentityRecord] = {}
        canonical: dict[str, SourceEventIdentityRecord] = {}
        for item in resolved:
            prior = canonical.get(item.canonical_event_key)
            if prior is not None and prior != item:
                raise ObservationPolicyError("conflicting canonical source-event registry")
            canonical[item.canonical_event_key] = item
            for reference in (item.record_digest, *item.aliases):
                if reference in index and index[reference] != item:
                    raise ObservationPolicyError("conflicting source-event alias")
                index[reference] = item
        self._records = MappingProxyType(index)

    def resolve(self, reference: str) -> SourceEventIdentityRecord | None:
        return self._records.get(reference)


class ContractTestDependencyArtifactResolver:
    resolver_version = DEPENDENCY_RESOLVER_VERSION

    def __init__(self, canonical_artifacts: tuple[Any, ...]):
        """Accept only owning-module artifacts; current APIs lack Step5's full bindings.

        The owning validators and hashes are checked here.  None of the PR38--42
        artifacts currently carries every provider/dataset/route/entity/capability/
        policy/source-event/payload binding required by Step5, so they are deliberately
        not promoted to resolver membership.  This is an explicit fail-closed adapter.
        """
        from governance.durable_custody import RestoreVerificationEvidence
        from governance.external_trust_verifier import (
            AuthorityRegistryEvidence,
            IndependentVerificationResult,
        )
        from governance.legal_governance import (
            LegalAdmissionDecision,
            validate_legal_admission_decision,
        )

        validators = {
            IndependentVerificationResult: ("result_hash", IndependentVerificationResult.model_validate),
            AuthorityRegistryEvidence: ("evidence_hash", AuthorityRegistryEvidence.model_validate),
            LegalAdmissionDecision: ("decision_hash", validate_legal_admission_decision),
            RestoreVerificationEvidence: ("evidence_hash", RestoreVerificationEvidence.model_validate),
        }
        checked: list[str] = []
        try:
            for supplied in canonical_artifacts:
                artifact_type = type(supplied)
                if artifact_type not in validators:
                    raise TypeError
                hash_field, validator = validators[artifact_type]
                canonical = validator(BaseModel.model_dump(supplied, mode="json"))
                _hash(canonical, hash_field)
                checked.append(getattr(canonical, hash_field))
        except BaseException:  # noqa: BLE001
            raise ObservationPolicyError("invalid canonical dependency artifact") from None
        self._unsupported_canonical_digests = tuple(sorted(checked))

    def resolve(self, reference: str) -> DependencyArtifactRecord | None:
        del reference
        return None


class DependencyArtifactReference(_Model):
    """Typed, scoped reference to independently validated contract-test evidence.

    It deliberately has no externally-verified state: repository-local material can
    only establish contract-test semantics.
    """
    kind: DependencyKind
    source_contract: str = Field(pattern=IDENTIFIER)
    source_contract_version: str = Field(pattern=IDENTIFIER)
    artifact_digest: str = Field(pattern=SHA256)
    source_event_ref_digest: str = Field(pattern=SHA256)
    payload_digest: str = Field(pattern=SHA256)
    provider_ref: str = Field(pattern=OPAQUE)
    dataset_ref: str = Field(pattern=OPAQUE)
    route_ref: str = Field(pattern=OPAQUE)
    entity_ref: str = Field(pattern=OPAQUE)
    capability_id: str = Field(pattern=IDENTIFIER)
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    available_at: dt.datetime
    effective_at: dt.datetime
    verified_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    assurance: Literal[DependencyAssurance.CONTRACT_TEST_ONLY]
    reference_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.source_contract, self.source_contract_version, self.capability_id,
             self.policy_id, self.policy_version)
        if (self.source_contract, self.source_contract_version) != DEPENDENCY_CONTRACTS[self.kind]:
            raise ValueError
        _opaque_values(self.provider_ref, self.dataset_ref, self.route_ref, self.entity_ref)
        for value in (self.available_at, self.effective_at, self.verified_at,
                      self.expires_at, self.revoked_at):
            if value is not None:
                _utc(value)
        if not self.available_at <= self.effective_at <= self.verified_at < self.expires_at:
            raise ValueError
        if self.revoked_at is not None and self.revoked_at < self.available_at:
            raise ValueError
        _hash(self, "reference_hash")
        return self


class ObservationEvidence(_Model):
    observation_ref: str = Field(pattern=IDENTIFIER)
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    policy_hash: str = Field(pattern=SHA256)
    counting_semantics_version: str = Field(pattern=IDENTIFIER)
    gate: EvidenceGate
    observation_class: ObservationClass
    capability_id: str = Field(pattern=IDENTIFIER)
    provider_ref: str = Field(pattern=OPAQUE)
    instrument_ref: str = Field(pattern=OPAQUE)
    dataset_ref: str = Field(pattern=OPAQUE)
    route_ref: str = Field(pattern=OPAQUE)
    observation_type: str = Field(pattern=IDENTIFIER)
    session_ref: str = Field(pattern=IDENTIFIER)
    session_date: dt.date
    window_start: dt.datetime
    window_end: dt.datetime
    available_at: dt.datetime
    market_data_mode: MarketDataMode
    payload_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    attestation_ref_digest: str = Field(pattern=SHA256)
    custody_lineage_digest: str = Field(pattern=SHA256)
    source_event_ref_digest: str = Field(pattern=SHA256)
    local_wrapper_digest: str = Field(pattern=SHA256)
    present_provenance_fields: tuple[str, ...]
    missing_fraction_ppm: int = Field(ge=0, le=1_000_000)
    dependency_artifacts: tuple[DependencyArtifactReference, ...]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.observation_ref, self.policy_id, self.policy_version,
             self.counting_semantics_version, self.capability_id, self.provider_ref,
             self.observation_type, self.session_ref,
             *self.present_provenance_fields)
        _opaque_values(self.provider_ref, self.instrument_ref, self.dataset_ref, self.route_ref)
        object.__setattr__(self, "dependency_artifacts", tuple(
            _deep(DependencyArtifactReference, item) for item in self.dependency_artifacts
        ))
        for value in (self.window_start, self.window_end, self.available_at):
            if value is not None:
                _utc(value)
        if self.window_start > self.window_end:
            raise ValueError
        if self.session_date != self.window_start.date():
            raise ValueError
        if self.available_at < self.window_end:
            raise ValueError
        if len({item.kind for item in self.dependency_artifacts}) != len(self.dependency_artifacts):
            raise ValueError
        if CLASS_GATE[self.observation_class] is not self.gate:
            raise ValueError
        _hash(self, "evidence_hash")
        return self

    def underlying_event_identity(self) -> str:
        """Local grouping key only; it does not establish independent event identity."""
        return typed_hash({
            "contract": CONTRACT_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "counting_semantics_version": self.counting_semantics_version,
            "provider": self.provider_ref,
            "instrument": self.instrument_ref,
            "dataset": self.dataset_ref,
            "type": self.observation_type,
            "source_event": self.source_event_ref_digest,
        })

    def representation_identity(self) -> str:
        return typed_hash({
            "underlying": self.underlying_event_identity(),
            "provenance": self.provenance_digest,
            "attestation": self.attestation_ref_digest,
            "custody_lineage": self.custody_lineage_digest,
            "wrapper": self.local_wrapper_digest,
        })

    def conflict_identity(self) -> str:
        return typed_hash({
            "underlying": self.underlying_event_identity(), "session": self.session_ref,
            "session_date": self.session_date, "window_start": self.window_start,
            "window_end": self.window_end, "mode": self.market_data_mode,
            "payload": self.payload_digest,
        })


class GateEvaluation(_Model):
    gate: EvidenceGate
    state: EvaluationState
    reason_codes: tuple[ReasonCode, ...]
    accepted_count: int = Field(ge=0)
    distinct_sessions: int = Field(ge=0)
    distinct_dates: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    accepted_identity_digests: tuple[str, ...]


class SufficiencyAssessment(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    policy_hash: str = Field(pattern=SHA256)
    assessed_at: dt.datetime
    state: EvaluationState
    gate_results: tuple[GateEvaluation, ...]
    contract_validation_state: Literal["CONTRACT_MECHANICS_VALIDATED"]
    package_assurance: Literal["LOCAL_PACKAGE_COMPLETENESS_ONLY"]
    real_policy_approval: Literal[ProvisioningState.NOT_PROVISIONED]
    real_provider_admission: Literal[ProvisioningState.NOT_PROVISIONED]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]
    assessment_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _utc(self.assessed_at)
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError
        if tuple(sorted(self.gate_results, key=lambda item: item.gate.value)) != self.gate_results:
            raise ValueError
        _hash(self, "assessment_hash")
        return self


def evaluate_sufficiency(
    *, policy: Any, observations: tuple[Any, ...], assessed_at: dt.datetime,
    source_event_resolver: SourceEventResolver | None = None,
    dependency_artifact_resolver: DependencyArtifactResolver | None = None,
) -> SufficiencyAssessment:
    """Deterministically evaluate contract evidence without making a REAL admission."""
    try:
        # Dependency admission is disabled until a complete canonical upstream
        # adapter exists. The compatibility argument must never influence an
        # assessment through caller-controlled dispatch.
        del dependency_artifact_resolver
        rule = _deep(SufficientObservationPolicy, policy)
        evidence = tuple(_deep(ObservationEvidence, item) for item in observations)
        _utc(assessed_at)
        if (type(source_event_resolver) is not ContractTestSourceEventResolver
                or source_event_resolver.resolver_version != rule.source_event_resolver_version):
            source_event_resolver = None
        results = tuple(
            sorted(
                (_evaluate_gate(rule, criterion, evidence, assessed_at,
                                source_event_resolver)
                 for criterion in rule.criteria),
                key=lambda item: item.gate.value,
            )
        )
        states = {item.state for item in results}
        if EvaluationState.REVIEW_REQUIRED in states:
            overall = EvaluationState.REVIEW_REQUIRED
        elif EvaluationState.NOT_PROVISIONED in states:
            overall = EvaluationState.NOT_PROVISIONED
        elif EvaluationState.INSUFFICIENT in states:
            overall = EvaluationState.INSUFFICIENT
        else:
            overall = EvaluationState.SUFFICIENT_FOR_EXTERNAL_VERIFICATION
        return seal_contract_test(
            SufficiencyAssessment,
            "assessment_hash",
            policy_hash=rule.content_hash,
            assessed_at=assessed_at,
            state=overall,
            gate_results=results,
            contract_validation_state="CONTRACT_MECHANICS_VALIDATED",
            package_assurance="LOCAL_PACKAGE_COMPLETENESS_ONLY",
            real_policy_approval=ProvisioningState.NOT_PROVISIONED,
            real_provider_admission=ProvisioningState.NOT_PROVISIONED,
            gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
            real_route="QVM_NOT_READY",
            global_readiness="INSUFFICIENT_REAL_DATA",
            trade_decision="NO_TRADE",
            signals_generated=False,
            live_execution_enabled=False,
            backtesting="NOT_AUTHORIZED",
        )
    except ObservationPolicyError:
        raise
    except BaseException:  # noqa: BLE001
        raise ObservationPolicyError("invalid sufficient-observation evaluation") from None


def _evaluate_gate(policy, criterion, evidence, now, event_resolver):
    reasons: set[ReasonCode] = set()
    candidates: list[tuple[ObservationEvidence, SourceEventIdentityRecord]] = []
    conflicted_event_keys: set[str] = set()
    policy_unavailable = (
        now < policy.effective_from
        or policy.effective_to is not None and now >= policy.effective_to
        or policy.revoked_at is not None and now >= policy.revoked_at
        or policy.replacement_policy_hash is not None
    )
    if policy_unavailable:
        reasons.add(ReasonCode.OUTSIDE_POLICY_WINDOW)
    for item in evidence:
        if item.gate is not criterion.gate or item.observation_class is not criterion.observation_class:
            continue
        item_reasons, event = _observation_reasons(
            policy, criterion, item, now, event_resolver
        )
        reasons.update(item_reasons)
        if event is not None and ReasonCode.SOURCE_EVENT_REVIEW_REQUIRED in item_reasons:
            conflicted_event_keys.add(event.canonical_event_key)
        mechanics_only = item_reasons <= {
            ReasonCode.SOURCE_EVENT_NOT_PROVISIONED,
            ReasonCode.DEPENDENCY_ARTIFACT_NOT_PROVISIONED,
            ReasonCode.TRUST_NOT_PROVISIONED,
            ReasonCode.LEGAL_NOT_PROVISIONED,
            ReasonCode.CUSTODY_NOT_PROVISIONED,
        }
        if mechanics_only and not policy_unavailable and event is not None:
            candidates.append((item, event))
    if not evidence:
        reasons.add(ReasonCode.NO_OBSERVATIONS)
    candidates = [pair for pair in candidates if pair[1].canonical_event_key
                  not in conflicted_event_keys]
    providers = {item.provider_ref for item, _ in candidates}
    datasets = {item.dataset_ref for item, _ in candidates}
    if len(providers) > 1 and not criterion.allow_cross_provider_aggregation:
        reasons.add(ReasonCode.PROVIDER_MISMATCH)
        candidates = []
    if len(datasets) > 1 and not criterion.allow_cross_dataset_aggregation:
        reasons.add(ReasonCode.DATASET_MISMATCH)
        candidates = []
    by_event: dict[str, list[ObservationEvidence]] = {}
    for item, event in sorted(candidates, key=lambda x: (
        x[1].canonical_event_key, x[0].conflict_identity(), x[0].representation_identity(),
        x[0].evidence_hash,
    )):
        by_event.setdefault(event.canonical_event_key, []).append(item)
    unique: list[ObservationEvidence] = []
    duplicate_count = 0
    for event_identity, representations in sorted(by_event.items()):
        conflicts = {typed_hash({
            "canonical_event": event_identity, "session": item.session_ref,
            "session_date": item.session_date, "window_start": item.window_start,
            "window_end": item.window_end, "mode": item.market_data_mode,
            "payload": item.payload_digest,
        }) for item in representations}
        duplicate_count += len(representations) - 1
        if len(conflicts) > 1:
            reasons.add(ReasonCode.SAME_WINDOW_CONFLICT)
            continue
        if len(representations) > 1:
            reasons.add(ReasonCode.DUPLICATE_OBSERVATION)
        unique.append(min(representations, key=lambda item: (
            item.representation_identity(), item.evidence_hash
        )))
    identities = tuple(sorted(by_event_identity for by_event_identity, representations
                              in by_event.items() if any(item in unique for item in representations)))
    sessions = len({item.session_ref for item in unique})
    dates = len({item.session_date for item in unique})
    if len(unique) < criterion.minimum_observation_count:
        reasons.add(ReasonCode.COUNT_BELOW_MINIMUM)
    if sessions < criterion.minimum_distinct_sessions:
        reasons.add(ReasonCode.DISTINCT_SESSIONS_BELOW_MINIMUM)
    if dates < criterion.minimum_distinct_dates:
        reasons.add(ReasonCode.DISTINCT_DATES_BELOW_MINIMUM)
    if (not unique or max(item.window_end for item in unique) - min(item.window_start for item in unique)
            < criterion.minimum_time_span):
        reasons.add(ReasonCode.TIME_SPAN_BELOW_MINIMUM)
    if policy.status is not PolicyStatus.APPROVED_FOR_EVIDENCE_COLLECTION:
        reasons.add(ReasonCode.POLICY_NOT_COLLECTION_APPROVED)
    dependency_not_provisioned = any(code in reasons for code in (
        ReasonCode.TRUST_NOT_PROVISIONED, ReasonCode.LEGAL_NOT_PROVISIONED,
        ReasonCode.CUSTODY_NOT_PROVISIONED, ReasonCode.SOURCE_EVENT_NOT_PROVISIONED,
        ReasonCode.DEPENDENCY_ARTIFACT_NOT_PROVISIONED,
    ))
    review = any(code in reasons for code in (
        ReasonCode.TRUST_REVIEW_REQUIRED, ReasonCode.LEGAL_REVIEW_REQUIRED,
        ReasonCode.CUSTODY_REVIEW_REQUIRED, ReasonCode.POLICY_VERSION_MISMATCH,
        ReasonCode.SAME_WINDOW_CONFLICT, ReasonCode.POLICY_NOT_COLLECTION_APPROVED,
        ReasonCode.OUTSIDE_POLICY_WINDOW, ReasonCode.SOURCE_EVENT_REVIEW_REQUIRED,
        ReasonCode.DEPENDENCY_ARTIFACT_REVIEW_REQUIRED,
    ))
    insufficient = any(code in reasons for code in (
        ReasonCode.NO_OBSERVATIONS, ReasonCode.COUNT_BELOW_MINIMUM,
        ReasonCode.DISTINCT_SESSIONS_BELOW_MINIMUM, ReasonCode.DISTINCT_DATES_BELOW_MINIMUM,
        ReasonCode.TIME_SPAN_BELOW_MINIMUM,
    ))
    state = (EvaluationState.REVIEW_REQUIRED if review else
             EvaluationState.NOT_PROVISIONED if dependency_not_provisioned else
             EvaluationState.INSUFFICIENT if insufficient else
             EvaluationState.SUFFICIENT_FOR_EXTERNAL_VERIFICATION)
    return GateEvaluation(
        gate=criterion.gate, state=state,
        reason_codes=tuple(sorted(reasons, key=str)), accepted_count=len(unique),
        distinct_sessions=sessions, distinct_dates=dates,
        duplicate_count=duplicate_count,
        accepted_identity_digests=identities,
    )


def _observation_reasons(policy, criterion, item, now, event_resolver):
    reasons: set[ReasonCode] = set()
    event = None if event_resolver is None else event_resolver.resolve(item.source_event_ref_digest)
    if event is None:
        reasons.add(ReasonCode.SOURCE_EVENT_NOT_PROVISIONED)
    else:
        event = _deep(SourceEventIdentityRecord, event)
        if event.assurance is SourceEventAssurance.SYNTHETIC_TEST_EVENT_IDENTITY:
            reasons.add(ReasonCode.SOURCE_EVENT_NOT_PROVISIONED)
        expected_event = (
            item.provider_ref, item.instrument_ref, item.dataset_ref, item.observation_type,
            item.session_ref, item.session_date, item.window_start, item.window_end,
            item.available_at, item.market_data_mode, item.payload_digest,
            item.provenance_digest, item.attestation_ref_digest, item.custody_lineage_digest,
            item.policy_id, item.policy_version, item.counting_semantics_version,
        )
        actual_event = (
            event.provider_ref, event.instrument_ref, event.dataset_ref, event.observation_type,
            event.session_ref, event.session_date, event.window_start, event.window_end,
            event.available_at, event.market_data_mode, event.payload_digest,
            event.provenance_digest, event.attestation_ref_digest, event.custody_lineage_digest,
            event.policy_id, event.policy_version, event.counting_semantics_version,
        )
        if expected_event != actual_event:
            reasons.add(ReasonCode.SOURCE_EVENT_REVIEW_REQUIRED)
            reasons.add(ReasonCode.SAME_WINDOW_CONFLICT)
    if (item.policy_id, item.policy_version, item.policy_hash, item.counting_semantics_version) != (
        policy.policy_id, policy.policy_version, policy.content_hash, policy.counting_semantics_version
    ):
        reasons.add(ReasonCode.POLICY_VERSION_MISMATCH)
    if item.capability_id != criterion.capability_id:
        reasons.add(ReasonCode.SCOPE_MISMATCH)
    if item.provider_ref not in criterion.allowed_provider_refs:
        reasons.add(ReasonCode.PROVIDER_MISMATCH)
    if item.dataset_ref not in criterion.allowed_dataset_refs:
        reasons.add(ReasonCode.DATASET_MISMATCH)
    if item.market_data_mode not in criterion.allowed_modes:
        reasons.add(ReasonCode.MODE_MISMATCH)
    if item.window_end > now:
        reasons.add(ReasonCode.FUTURE_OBSERVATION)
    if item.available_at > now:
        reasons.add(ReasonCode.EVIDENCE_NOT_AVAILABLE_AS_OF)
    if item.window_start < policy.effective_from and not criterion.allow_grandfathering:
        reasons.add(ReasonCode.BEFORE_POLICY_EFFECTIVE)
    if policy.effective_to is not None and item.window_end >= policy.effective_to:
        reasons.add(ReasonCode.OUTSIDE_POLICY_WINDOW)
    if policy.revoked_at is not None and now >= policy.revoked_at:
        reasons.add(ReasonCode.OUTSIDE_POLICY_WINDOW)
    if now - item.window_end > criterion.maximum_age:
        reasons.add(ReasonCode.STALE_OBSERVATION)
    if not set(criterion.required_provenance_fields) <= set(item.present_provenance_fields):
        reasons.add(ReasonCode.MISSING_PROVENANCE)
    if item.missing_fraction_ppm > criterion.maximum_missing_fraction_ppm:
        reasons.add(ReasonCode.MISSINGNESS_EXCEEDED)
    required = {DependencyKind.TRUST_VERIFIER}
    if criterion.require_authority_registry:
        required.add(DependencyKind.AUTHORITY_REGISTRY)
    if criterion.require_legal_rights:
        required.add(DependencyKind.LEGAL_RIGHT)
    if criterion.require_custody_worm_replay:
        required.add(DependencyKind.CUSTODY_WORM_REPLAY)
    artifacts = {artifact.kind: artifact for artifact in item.dependency_artifacts}
    for kind in required:
        # References remain mechanics diagnostics only. Current PR38--42 models
        # cannot establish membership, regardless of any supplied resolver.
        reasons.add(ReasonCode.DEPENDENCY_ARTIFACT_NOT_PROVISIONED)
        reasons.add(_dependency_code(kind, provisioned=False))
        artifact = artifacts.get(kind)
        if artifact is None:
            continue
        expected_binding = (
            item.provider_ref, item.dataset_ref, item.route_ref, item.instrument_ref,
            item.capability_id, item.policy_id, item.policy_version,
            event.canonical_event_key if event is not None else item.source_event_ref_digest,
            item.payload_digest,
        )
        wrapper_binding = (
            artifact.provider_ref, artifact.dataset_ref, artifact.route_ref,
            artifact.entity_ref, artifact.capability_id, artifact.policy_id,
            artifact.policy_version, artifact.source_event_ref_digest,
            artifact.payload_digest,
        )
        if event is not None and wrapper_binding != expected_binding:
            reasons.add(ReasonCode.DEPENDENCY_BINDING_MISMATCH)
            reasons.add(ReasonCode.DEPENDENCY_ARTIFACT_REVIEW_REQUIRED)
            reasons.add(_dependency_code(kind, provisioned=True))
            continue
        if artifact.available_at > now or artifact.verified_at > now:
            reasons.add(ReasonCode.DEPENDENCY_NOT_AVAILABLE_AS_OF)
            reasons.add(ReasonCode.DEPENDENCY_ARTIFACT_REVIEW_REQUIRED)
            reasons.add(_dependency_code(kind, provisioned=True))
            continue
        if (now < artifact.effective_at or now >= artifact.expires_at
                or artifact.revoked_at is not None and now >= artifact.revoked_at):
            reasons.add(ReasonCode.DEPENDENCY_ARTIFACT_REVIEW_REQUIRED)
            reasons.add(_dependency_code(kind, provisioned=True))
            continue
    return reasons, event


def _dependency_code(kind: DependencyKind, *, provisioned: bool) -> ReasonCode:
    prefix = "LEGAL" if kind is DependencyKind.LEGAL_RIGHT else (
        "CUSTODY" if kind is DependencyKind.CUSTODY_WORM_REPLAY else "TRUST"
    )
    suffix = "REVIEW_REQUIRED" if provisioned else "NOT_PROVISIONED"
    return ReasonCode[f"{prefix}_{suffix}"]


def admit_real_policy(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise ObservationPolicyError("REAL sufficient-observation policy is NOT_PROVISIONED")


def build_contract_test_source_event_record(**values: Any) -> SourceEventIdentityRecord:
    """Build a synthetic mechanics fixture; it cannot establish event independence."""
    values = dict(values)
    values["resolver_version"] = SOURCE_EVENT_RESOLVER_VERSION
    values["assurance"] = SourceEventAssurance.SYNTHETIC_TEST_EVENT_IDENTITY
    values["canonical_upstream_observation_digest"] = None
    values["canonical_event_key"] = typed_hash({
        "provider": values["provider_ref"],
        "instrument": values["instrument_ref"],
        "dataset": values["dataset_ref"],
        "observation_type": values["observation_type"],
        "provider_event_key": values["provider_event_key_ref"],
    })
    return _seal_record(SourceEventIdentityRecord, "record_digest", values)


def build_contract_test_dependency_artifact(**values: Any) -> DependencyArtifactRecord:
    """Removed insecure factory: local metadata cannot mint dependency truth."""
    del values
    raise ObservationPolicyError("canonical upstream dependency artifact required")


T = TypeVar("T", bound=BaseModel)


def _seal_record(expected: type[T], hash_field: str, values: dict[str, Any]) -> T:
    try:
        raw = BaseModel.model_construct.__func__(expected, **values, **{hash_field: "0" * 64})
        digest = typed_hash(BaseModel.model_dump(
            raw, mode="json", exclude={hash_field}, warnings=False
        ))
        return expected(**values, **{hash_field: digest})
    except BaseException:  # noqa: BLE001
        raise ObservationPolicyError("invalid contract-test resolver record") from None


def seal_contract_test(expected: type[T], hash_field: str, **values: Any) -> T:
    try:
        if _SEAL_FIELDS.get(expected) != hash_field:
            raise TypeError
        raw = BaseModel.model_construct.__func__(
            expected, **values, **{hash_field: "0" * 64}
        )
        digest = typed_hash(BaseModel.model_dump(
            raw, mode="json", exclude={hash_field}, warnings=False
        ))
        return expected(**values, **{hash_field: digest})
    except BaseException:  # noqa: BLE001
        raise ObservationPolicyError("invalid sufficient-observation value") from None


def opaque_reference(raw: str) -> str:
    """Sanctioned boundary: immediately reduce a raw reference to an opaque digest."""
    try:
        if raw.startswith("opaque:v1:"):
            _opaque_values(raw)
            return raw
        return f"opaque:v1:{typed_hash(raw)}"
    except BaseException:  # noqa: BLE001
        raise ObservationPolicyError("invalid sensitive reference") from None


def _deep(expected: type[T], value: Any) -> T:
    try:
        if isinstance(value, BaseModel):
            if set(value.__dict__) - set(type(value).model_fields):
                raise ValueError
            value = BaseModel.model_dump(value, mode="json")
        elif isinstance(value, str):
            value = json.loads(value)
        elif not isinstance(value, dict):
            raise TypeError
        return expected.model_validate(json.loads(json.dumps(value, sort_keys=True)))
    except BaseException:  # noqa: BLE001
        raise ObservationPolicyError("invalid sufficient-observation value") from None


def _hash(value: BaseModel, field: str) -> None:
    if getattr(value, field) != typed_hash(BaseModel.model_dump(
        value, mode="json", exclude={field}, warnings=False
    )):
        raise ValueError


def _ids(*values: str) -> None:
    if any(not value.isascii() or value != value.casefold()
           or value != unicodedata.normalize("NFKC", value) for value in values):
        raise ValueError


def _utc(value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError


def _opaque_values(*values: str) -> None:
    if any(not value.startswith("opaque:v1:") or len(value) != 74
           or any(character not in "0123456789abcdef" for character in value[10:])
           for value in values):
        raise ValueError


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


_SEAL_FIELDS: dict[type[BaseModel], str] = {
    GateCriterion: "criterion_hash",
    SufficientObservationPolicy: "content_hash",
    ObservationEvidence: "evidence_hash",
    DependencyArtifactReference: "reference_hash",
    SufficiencyAssessment: "assessment_hash",
}
