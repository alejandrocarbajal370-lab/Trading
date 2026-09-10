"""Governed sufficient-observation policy foundation.

This module evaluates content-addressed contract evidence.  It cannot approve a
REAL policy, admit a provider, close a gate, or establish external truth.
"""

from __future__ import annotations

import datetime as dt
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.ibkr_external_attestation import ProvisioningState
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "governed-sufficient-observation-policy-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{1,127}$"


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
    STALE_OBSERVATION = "STALE_OBSERVATION"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    TRUST_NOT_PROVISIONED = "TRUST_NOT_PROVISIONED"
    TRUST_REVIEW_REQUIRED = "TRUST_REVIEW_REQUIRED"
    LEGAL_NOT_PROVISIONED = "LEGAL_NOT_PROVISIONED"
    LEGAL_REVIEW_REQUIRED = "LEGAL_REVIEW_REQUIRED"
    CUSTODY_NOT_PROVISIONED = "CUSTODY_NOT_PROVISIONED"
    CUSTODY_REVIEW_REQUIRED = "CUSTODY_REVIEW_REQUIRED"
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
    counting_semantics_version: str = Field(pattern=IDENTIFIER)
    status: PolicyStatus
    created_at: dt.datetime
    reviewed_at: dt.datetime | None = None
    effective_from: dt.datetime
    effective_to: dt.datetime | None = None
    jurisdiction_context_ref: str = Field(pattern=IDENTIFIER)
    use_context_ref: str = Field(pattern=IDENTIFIER)
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
             self.jurisdiction_context_ref, self.use_context_ref, self.exception_policy_ref)
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


class ObservationEvidence(_Model):
    observation_ref: str = Field(pattern=IDENTIFIER)
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    policy_hash: str = Field(pattern=SHA256)
    counting_semantics_version: str = Field(pattern=IDENTIFIER)
    gate: EvidenceGate
    observation_class: ObservationClass
    capability_id: str = Field(pattern=IDENTIFIER)
    provider_ref: str = Field(pattern=IDENTIFIER)
    instrument_ref: str = Field(pattern=IDENTIFIER)
    dataset_ref: str = Field(pattern=IDENTIFIER)
    observation_type: str = Field(pattern=IDENTIFIER)
    session_ref: str = Field(pattern=IDENTIFIER)
    session_date: dt.date
    window_start: dt.datetime
    window_end: dt.datetime
    market_data_mode: MarketDataMode
    payload_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    attestation_ref_digest: str = Field(pattern=SHA256)
    source_event_ref_digest: str = Field(pattern=SHA256)
    local_wrapper_digest: str = Field(pattern=SHA256)
    present_provenance_fields: tuple[str, ...]
    missing_fraction_ppm: int = Field(ge=0, le=1_000_000)
    trust_state: DependencyState
    authority_registry_state: DependencyState
    legal_state: DependencyState
    custody_state: DependencyState
    dependency_valid_from: dt.datetime
    dependency_valid_to: dt.datetime | None = None
    dependency_revoked_at: dt.datetime | None = None
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.observation_ref, self.policy_id, self.policy_version,
             self.counting_semantics_version, self.capability_id, self.provider_ref,
             self.instrument_ref, self.dataset_ref, self.observation_type, self.session_ref,
             *self.present_provenance_fields)
        for value in (self.window_start, self.window_end, self.dependency_valid_from,
                      self.dependency_valid_to, self.dependency_revoked_at):
            if value is not None:
                _utc(value)
        if self.window_start > self.window_end:
            raise ValueError
        if self.session_date != self.window_start.date():
            raise ValueError
        if self.dependency_valid_to is not None and self.dependency_valid_from >= self.dependency_valid_to:
            raise ValueError
        if CLASS_GATE[self.observation_class] is not self.gate:
            raise ValueError
        _hash(self, "evidence_hash")
        return self

    def semantic_identity(self) -> str:
        """Underlying event identity; local wrapper and caller alias are intentionally absent."""
        return typed_hash({
            "contract": CONTRACT_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "counting_semantics_version": self.counting_semantics_version,
            "provider": self.provider_ref,
            "instrument": self.instrument_ref,
            "dataset": self.dataset_ref,
            "type": self.observation_type,
            "session": self.session_ref,
            "session_date": self.session_date,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "mode": self.market_data_mode,
            "payload": self.payload_digest,
            "provenance": self.provenance_digest,
            "attestation": self.attestation_ref_digest,
            "source_event": self.source_event_ref_digest,
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
    contract_validation_state: Literal["CONTRACT_TEST_VALIDATED"]
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
    *, policy: Any, observations: tuple[Any, ...], assessed_at: dt.datetime
) -> SufficiencyAssessment:
    """Deterministically evaluate contract evidence without making a REAL admission."""
    try:
        rule = _deep(SufficientObservationPolicy, policy)
        evidence = tuple(_deep(ObservationEvidence, item) for item in observations)
        _utc(assessed_at)
        results = tuple(
            sorted(
                (_evaluate_gate(rule, criterion, evidence, assessed_at)
                 for criterion in rule.criteria),
                key=lambda item: item.gate.value,
            )
        )
        states = {item.state for item in results}
        if EvaluationState.NOT_PROVISIONED in states:
            overall = EvaluationState.NOT_PROVISIONED
        elif EvaluationState.REVIEW_REQUIRED in states:
            overall = EvaluationState.REVIEW_REQUIRED
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
            contract_validation_state="CONTRACT_TEST_VALIDATED",
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


def _evaluate_gate(policy, criterion, evidence, now):
    reasons: set[ReasonCode] = set()
    candidates: list[ObservationEvidence] = []
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
        item_reasons = _observation_reasons(policy, criterion, item, now)
        reasons.update(item_reasons)
        if not item_reasons and not policy_unavailable:
            candidates.append(item)
    if not evidence:
        reasons.add(ReasonCode.NO_OBSERVATIONS)
    providers = {item.provider_ref for item in candidates}
    datasets = {item.dataset_ref for item in candidates}
    if len(providers) > 1 and not criterion.allow_cross_provider_aggregation:
        reasons.add(ReasonCode.PROVIDER_MISMATCH)
        candidates = []
    if len(datasets) > 1 and not criterion.allow_cross_dataset_aggregation:
        reasons.add(ReasonCode.DATASET_MISMATCH)
        candidates = []
    by_identity: dict[str, ObservationEvidence] = {}
    for item in sorted(candidates, key=lambda x: (x.semantic_identity(), x.evidence_hash)):
        identity = item.semantic_identity()
        if identity in by_identity:
            reasons.add(ReasonCode.DUPLICATE_OBSERVATION)
        else:
            by_identity[identity] = item
    unique = list(by_identity.values())
    windows: dict[tuple[Any, ...], set[str]] = {}
    for item in unique:
        key = (item.provider_ref, item.instrument_ref, item.dataset_ref, item.observation_type,
               item.window_start, item.window_end, item.market_data_mode)
        windows.setdefault(key, set()).add(item.payload_digest)
    conflicting = {key for key, payloads in windows.items() if len(payloads) > 1}
    if conflicting:
        reasons.add(ReasonCode.SAME_WINDOW_CONFLICT)
        unique = [item for item in unique if (
            item.provider_ref, item.instrument_ref, item.dataset_ref, item.observation_type,
            item.window_start, item.window_end, item.market_data_mode
        ) not in conflicting]
    identities = tuple(sorted(item.semantic_identity() for item in unique))
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
        ReasonCode.CUSTODY_NOT_PROVISIONED,
    ))
    review = any(code in reasons for code in (
        ReasonCode.TRUST_REVIEW_REQUIRED, ReasonCode.LEGAL_REVIEW_REQUIRED,
        ReasonCode.CUSTODY_REVIEW_REQUIRED, ReasonCode.POLICY_VERSION_MISMATCH,
        ReasonCode.SAME_WINDOW_CONFLICT, ReasonCode.POLICY_NOT_COLLECTION_APPROVED,
        ReasonCode.OUTSIDE_POLICY_WINDOW,
    ))
    insufficient = any(code in reasons for code in (
        ReasonCode.NO_OBSERVATIONS, ReasonCode.COUNT_BELOW_MINIMUM,
        ReasonCode.DISTINCT_SESSIONS_BELOW_MINIMUM, ReasonCode.DISTINCT_DATES_BELOW_MINIMUM,
        ReasonCode.TIME_SPAN_BELOW_MINIMUM,
    ))
    state = (EvaluationState.NOT_PROVISIONED if dependency_not_provisioned else
             EvaluationState.REVIEW_REQUIRED if review else
             EvaluationState.INSUFFICIENT if insufficient else
             EvaluationState.SUFFICIENT_FOR_EXTERNAL_VERIFICATION)
    return GateEvaluation(
        gate=criterion.gate, state=state,
        reason_codes=tuple(sorted(reasons, key=str)), accepted_count=len(unique),
        distinct_sessions=sessions, distinct_dates=dates,
        duplicate_count=len(candidates) - len(by_identity),
        accepted_identity_digests=identities,
    )


def _observation_reasons(policy, criterion, item, now):
    reasons: set[ReasonCode] = set()
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
    _dependency_reason(reasons, item.trust_state, "trust", required=True)
    if criterion.require_authority_registry:
        _dependency_reason(reasons, item.authority_registry_state, "trust", required=True)
    if criterion.require_legal_rights:
        _dependency_reason(reasons, item.legal_state, "legal", required=True)
    if criterion.require_custody_worm_replay:
        _dependency_reason(reasons, item.custody_state, "custody", required=True)
    if (item.dependency_valid_from > item.window_end
            or item.dependency_valid_to is not None and now >= item.dependency_valid_to
            or item.dependency_revoked_at is not None and now >= item.dependency_revoked_at):
        reasons.add(ReasonCode.TRUST_REVIEW_REQUIRED)
    return reasons


def _dependency_reason(reasons, state, kind, *, required):
    if not required:
        return
    if state in {DependencyState.NOT_PROVISIONED, DependencyState.NOT_REQUIRED}:
        reasons.add(getattr(ReasonCode, f"{kind.upper()}_NOT_PROVISIONED"))
    elif state not in {
        DependencyState.CONTRACT_TEST_VALIDATED,
        DependencyState.EXTERNALLY_VERIFIED,
    }:
        reasons.add(getattr(ReasonCode, f"{kind.upper()}_REVIEW_REQUIRED"))


def admit_real_policy(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise ObservationPolicyError("REAL sufficient-observation policy is NOT_PROVISIONED")


T = TypeVar("T", bound=BaseModel)


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


_SEAL_FIELDS: dict[type[BaseModel], str] = {
    GateCriterion: "criterion_hash",
    SufficientObservationPolicy: "content_hash",
    ObservationEvidence: "evidence_hash",
    SufficiencyAssessment: "assessment_hash",
}
