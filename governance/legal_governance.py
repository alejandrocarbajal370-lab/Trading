"""Licensing/legal governance contracts; architecture is not legal truth."""

from __future__ import annotations

import datetime as dt
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "licensing-legal-governance-v2"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class LegalGovernanceError(ValueError):
    """Untrusted legal metadata failed closed without reflecting its contents."""


class LegalRole(StrEnum):
    LEGAL_EVIDENCE_OPERATOR = "LEGAL_EVIDENCE_OPERATOR"
    LEGAL_REVIEWER = "LEGAL_REVIEWER"
    LEGAL_APPROVER = "LEGAL_APPROVER"


class LegalScope(StrEnum):
    ENTITY = "ENTITY"
    USER = "USER"
    SYSTEM = "SYSTEM"
    ACTIVITY = "ACTIVITY"
    PROVIDER = "PROVIDER"
    DATA = "DATA"
    EXECUTION = "EXECUTION"
    ADVICE = "ADVICE"
    RESEARCH = "RESEARCH"


class RequirementType(StrEnum):
    LICENSE = "LICENSE"
    REGISTRATION = "REGISTRATION"
    DISCLOSURE = "DISCLOSURE"
    RECORDKEEPING = "RECORDKEEPING"
    DATA_RIGHTS = "DATA_RIGHTS"
    MARKETING = "MARKETING"
    ADVICE = "ADVICE"
    EXECUTION = "EXECUTION"


class RequirementStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    REQUIRES_EXTERNAL_REVIEW = "REQUIRES_EXTERNAL_REVIEW"
    NOT_PROVISIONED = "NOT_PROVISIONED"
    EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY = "EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY"


class LegalCapability(StrEnum):
    RECEIVE_ACCESS = "RECEIVE_ACCESS"
    INTERNAL_RESEARCH = "INTERNAL_RESEARCH"
    DURABLE_STORAGE = "DURABLE_STORAGE"
    RETENTION = "RETENTION"
    DERIVED_DATA_ARTIFACTS = "DERIVED_DATA_ARTIFACTS"
    REPLAY_AUDIT = "REPLAY_AUDIT"
    REDISTRIBUTION = "REDISTRIBUTION"
    PAPER_TRADING_USE = "PAPER_TRADING_USE"
    LIVE_EXECUTION_USE = "LIVE_EXECUTION_USE"


class RightStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"
    DENIED = "DENIED"
    GRANTED_CONTRACT_TEST_ONLY = "GRANTED_CONTRACT_TEST_ONLY"


class EvidenceSourceType(StrEnum):
    EXTERNAL_COUNSEL = "EXTERNAL_COUNSEL"
    REGULATOR = "REGULATOR"
    AUTHORITY_REGISTRY = "AUTHORITY_REGISTRY"
    OFFICIAL_FILING = "OFFICIAL_FILING"


class VerificationState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class RelianceClaimState(StrEnum):
    UNKNOWN = "UNKNOWN"
    REQUIRES_EXTERNAL_REVIEW = "REQUIRES_EXTERNAL_REVIEW"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class AdmissionState(StrEnum):
    NOT_PROVISIONED = "NOT_PROVISIONED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - input can contain hostile secrets
            raise LegalGovernanceError("invalid legal governance value") from None

    def __repr_args__(self):
        return [("redacted", True)]

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Public serialization is a disclosure boundary, not a persistence format."""
        return _redact(BaseModel.model_dump(self, **kwargs))

    def model_dump_json(self, **kwargs: Any) -> str:
        # Pydantic's serializer bypasses model_dump overrides, so redact explicitly.
        allowed = {"include", "exclude", "by_alias", "exclude_unset", "exclude_defaults",
                   "exclude_none", "round_trip", "warnings", "fallback", "serialize_as_any"}
        dump_kwargs = {key: value for key, value in kwargs.items() if key in allowed}
        raw = BaseModel.model_dump(self, mode="json", **dump_kwargs)
        return json.dumps(_redact(raw), separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        try:
            return super().model_validate(obj, **kwargs)
        except BaseException:  # noqa: BLE001
            raise LegalGovernanceError("invalid legal governance value") from None

    @classmethod
    def model_validate_json(cls, value: str | bytes | bytearray, **kwargs: Any):
        try:
            return super().model_validate_json(value, **kwargs)
        except BaseException:  # noqa: BLE001
            raise LegalGovernanceError("invalid legal governance value") from None


class LegalJurisdictionReference(_Model):
    jurisdiction_id: str = Field(pattern=IDENTIFIER)
    canonical_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.-]{1,31}$")
    scope: LegalScope
    subject_id: str = Field(pattern=IDENTIFIER)
    activity_id: str = Field(pattern=IDENTIFIER)
    provider_ref: str = Field(pattern=IDENTIFIER)
    dataset_ref: str = Field(pattern=IDENTIFIER)
    route_ref: str = Field(pattern=IDENTIFIER)
    effective_from: dt.datetime
    effective_to: dt.datetime | None = None
    source_version: str = Field(pattern=IDENTIFIER)
    source_digest: str = Field(pattern=SHA256)
    reference_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.jurisdiction_id, self.subject_id, self.activity_id, self.provider_ref,
             self.dataset_ref, self.route_ref, self.source_version)
        _utc(self.effective_from)
        if self.effective_to is not None:
            _utc(self.effective_to)
            if self.effective_from >= self.effective_to:
                raise ValueError
        _hash(self, "reference_hash")
        return self


class LegalRequirementRecord(_Model):
    requirement_id: str = Field(pattern=IDENTIFIER)
    requirement_version: str = Field(pattern=IDENTIFIER)
    jurisdiction_ref_hash: str = Field(pattern=SHA256)
    subject_id: str = Field(pattern=IDENTIFIER)
    activity_id: str = Field(pattern=IDENTIFIER)
    scope: LegalScope
    use_class: LegalCapability
    capability: LegalCapability
    requirement_type: RequirementType
    status: RequirementStatus
    right_status: RightStatus
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    policy_hash: str = Field(pattern=SHA256)
    provider_ref: str = Field(pattern=IDENTIFIER)
    dataset_ref: str = Field(pattern=IDENTIFIER)
    route_ref: str = Field(pattern=IDENTIFIER)
    authorized_issuer_id: str = Field(pattern=IDENTIFIER)
    authorized_authority_id: str = Field(pattern=IDENTIFIER)
    authorized_verifier_id: str = Field(pattern=IDENTIFIER)
    effective_from: dt.datetime
    effective_to: dt.datetime | None = None
    source_version: str = Field(pattern=IDENTIFIER)
    source_digest: str = Field(pattern=SHA256)
    record_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.requirement_id, self.requirement_version, self.subject_id, self.activity_id,
             self.policy_id, self.policy_version, self.provider_ref, self.dataset_ref,
             self.route_ref, self.authorized_issuer_id, self.authorized_authority_id,
             self.authorized_verifier_id, self.source_version)
        if self.use_class is not self.capability:
            raise ValueError
        _window(self.effective_from, self.effective_to)
        _hash(self, "record_hash")
        return self


class LegalEvidenceReference(_Model):
    evidence_id: str = Field(pattern=IDENTIFIER)
    evidence_version: str = Field(pattern=IDENTIFIER)
    source_type: EvidenceSourceType
    issuer_id: str = Field(pattern=IDENTIFIER)
    authority_id: str = Field(pattern=IDENTIFIER)
    verifier_id: str = Field(pattern=IDENTIFIER)
    requirement_id: str = Field(pattern=IDENTIFIER)
    requirement_version: str = Field(pattern=IDENTIFIER)
    requirement_hash: str = Field(pattern=SHA256)
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    policy_hash: str = Field(pattern=SHA256)
    jurisdiction_id: str = Field(pattern=IDENTIFIER)
    subject_id: str = Field(pattern=IDENTIFIER)
    activity_id: str = Field(pattern=IDENTIFIER)
    scope: LegalScope
    use_class: LegalCapability
    provider_ref: str = Field(pattern=IDENTIFIER)
    dataset_ref: str = Field(pattern=IDENTIFIER)
    route_ref: str = Field(pattern=IDENTIFIER)
    evidence_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    issued_at: dt.datetime
    valid_from: dt.datetime
    verified_at: dt.datetime
    expires_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    verification_state: VerificationState
    reference_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.evidence_id, self.evidence_version, self.issuer_id, self.authority_id,
             self.verifier_id, self.requirement_id, self.requirement_version, self.policy_id,
             self.policy_version, self.jurisdiction_id, self.subject_id, self.activity_id,
             self.provider_ref, self.dataset_ref, self.route_ref)
        for value in (self.issued_at, self.valid_from, self.verified_at,
                      self.expires_at, self.revoked_at):
            if value is not None:
                _utc(value)
        if self.issued_at > self.verified_at:
            raise ValueError
        if self.expires_at is not None and self.valid_from >= self.expires_at:
            raise ValueError
        _hash(self, "reference_hash")
        return self


class LegalRelianceClaim(_Model):
    """A claimed exemption/reliance to review, never an encoded legal conclusion."""

    claim_id: str = Field(pattern=IDENTIFIER)
    jurisdiction_ref_hash: str = Field(pattern=SHA256)
    requirement_record_hash: str = Field(pattern=SHA256)
    subject_id: str = Field(pattern=IDENTIFIER)
    activity_id: str = Field(pattern=IDENTIFIER)
    scope: LegalScope
    claim_state: RelianceClaimState
    source_version: str = Field(pattern=IDENTIFIER)
    source_digest: str = Field(pattern=SHA256)
    claim_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.claim_id, self.subject_id, self.activity_id, self.source_version)
        _hash(self, "claim_hash")
        return self


class LegalAssessmentEvidence(_Model):
    assessment_id: str = Field(pattern=IDENTIFIER)
    assessed_at: dt.datetime
    jurisdiction_hashes: tuple[str, ...] = Field(min_length=1)
    requirement_hashes: tuple[str, ...] = Field(min_length=1)
    evidence_hashes: tuple[str, ...] = Field(min_length=1)
    reliance_claim_hashes: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    reviewer_id: str = Field(pattern=IDENTIFIER)
    reviewer_role: Literal[LegalRole.LEGAL_REVIEWER]
    state: Literal[VerificationState.CONTRACT_TEST_ONLY]
    assessment_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _ids(self.assessment_id, self.reviewer_id, *self.unresolved_conflicts,
             *self.missing_evidence)
        _utc(self.assessed_at)
        if any(len(set(items)) != len(items) for items in
               (self.jurisdiction_hashes, self.requirement_hashes, self.evidence_hashes,
                self.reliance_claim_hashes)):
            raise ValueError
        _hash(self, "assessment_hash")
        return self


class LegalAdmissionDecision(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    assessment_hash: str = Field(pattern=SHA256)
    assessed_at: dt.datetime
    decision_state: AdmissionState
    capability_states: tuple[tuple[LegalCapability, AdmissionState], ...]
    operator_id: str = Field(pattern=IDENTIFIER)
    reviewer_id: str = Field(pattern=IDENTIFIER)
    approver_id: str = Field(pattern=IDENTIFIER)
    legal_licensing_real: Literal[AdmissionState.NOT_PROVISIONED]
    authority_registry_real: Literal[AdmissionState.NOT_PROVISIONED]
    external_counsel_real: Literal[AdmissionState.NOT_PROVISIONED]
    provider_admission_real: Literal[AdmissionState.NOT_PROVISIONED]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _utc(self.assessed_at)
        _ids(self.operator_id, self.reviewer_id, self.approver_id)
        if len({self.operator_id, self.reviewer_id, self.approver_id}) != 3:
            raise ValueError
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError
        if tuple(capability for capability, _ in self.capability_states) != tuple(LegalCapability):
            raise ValueError
        _hash(self, "decision_hash")
        return self


def assess_contract_test_legal(
    *, jurisdictions: tuple[Any, ...], requirements: tuple[Any, ...],
    evidence: tuple[Any, ...], reliance_claims: tuple[Any, ...], assessed_at: dt.datetime,
    assessment_id: str,
    operator_id: str, reviewer_id: str, approver_id: str,
    unresolved_conflicts: tuple[str, ...] = (), missing_evidence: tuple[str, ...] = (),
) -> tuple[LegalAssessmentEvidence, LegalAdmissionDecision]:
    """Validate an exact local fixture graph; at most CONTRACT_TEST_ONLY."""
    try:
        _utc(assessed_at)
        if any(type(values) is not tuple for values in
               (jurisdictions, requirements, evidence, reliance_claims)):
            raise TypeError
        js = tuple(_rebuild(LegalJurisdictionReference, item) for item in jurisdictions)
        rs = tuple(_rebuild(LegalRequirementRecord, item) for item in requirements)
        es = tuple(_rebuild(LegalEvidenceReference, item) for item in evidence)
        cs = tuple(_rebuild(LegalRelianceClaim, item) for item in reliance_claims)
        if not js or not rs or not es:
            raise ValueError
        if len({item.jurisdiction_id for item in js}) != len(js):
            raise ValueError
        by_hash = {item.reference_hash: item for item in js}
        if len(by_hash) != len(js):
            raise ValueError
        for jurisdiction in js:
            _current(jurisdiction.effective_from, jurisdiction.effective_to, assessed_at)
        capability_states: dict[LegalCapability, AdmissionState] = {
            capability: AdmissionState.REVIEW_REQUIRED for capability in LegalCapability
        }
        requirements_by_capability: dict[LegalCapability, LegalRequirementRecord] = {}
        for requirement in rs:
            jurisdiction = by_hash.get(requirement.jurisdiction_ref_hash)
            if (jurisdiction is None or not _same_scope(jurisdiction, requirement)
                    or not _same_route(jurisdiction, requirement)
                    or requirement.capability in requirements_by_capability):
                raise ValueError
            requirements_by_capability[requirement.capability] = requirement
            _current(requirement.effective_from, requirement.effective_to, assessed_at)
            if (requirement.status is RequirementStatus.UNKNOWN
                    or requirement.status is RequirementStatus.REQUIRES_EXTERNAL_REVIEW
                    or requirement.status is RequirementStatus.NOT_PROVISIONED
                    or requirement.right_status is RightStatus.UNKNOWN):
                capability_states[requirement.capability] = AdmissionState.REVIEW_REQUIRED
            elif requirement.right_status in (RightStatus.AMBIGUOUS, RightStatus.DENIED):
                capability_states[requirement.capability] = AdmissionState.BLOCKED
        requirements_by_hash = {item.record_hash: item for item in rs}
        for claim in cs:
            requirement = requirements_by_hash.get(claim.requirement_record_hash)
            jurisdiction = by_hash.get(claim.jurisdiction_ref_hash)
            if (requirement is None or jurisdiction is None
                    or requirement.jurisdiction_ref_hash != jurisdiction.reference_hash
                    or not _same_scope(jurisdiction, claim)
                    or claim.claim_state is not RelianceClaimState.REQUIRES_EXTERNAL_REVIEW):
                raise ValueError
        for item in es:
            matching = [j for j in js if j.jurisdiction_id == item.jurisdiction_id]
            if len(matching) != 1 or not _same_scope(matching[0], item):
                raise ValueError
            if len({item.issuer_id, item.authority_id, item.verifier_id}) != 3:
                raise ValueError
            if item.verification_state is not VerificationState.CONTRACT_TEST_ONLY:
                raise ValueError
            if not item.issued_at <= item.verified_at <= assessed_at:
                raise ValueError
            _current(item.valid_from, item.expires_at, assessed_at)
            if item.revoked_at is not None and item.revoked_at <= assessed_at:
                raise ValueError
        evidence_by_requirement = {e.requirement_hash: e for e in es}
        if len(evidence_by_requirement) != len(es):
            raise ValueError
        if not set(evidence_by_requirement) <= set(requirements_by_hash):
            raise ValueError
        for requirement in rs:
            item = evidence_by_requirement.get(requirement.record_hash)
            jurisdiction = by_hash[requirement.jurisdiction_ref_hash]
            if item is None:
                missing_evidence = tuple(sorted({*missing_evidence,
                    f"missing.capability.{requirement.capability.value.lower()}"}))
                continue
            expected = (
                requirement.requirement_id, requirement.requirement_version,
                requirement.record_hash, requirement.policy_id, requirement.policy_version,
                requirement.policy_hash, jurisdiction.jurisdiction_id, requirement.subject_id,
                requirement.activity_id, requirement.scope, requirement.use_class,
                requirement.provider_ref, requirement.dataset_ref, requirement.route_ref,
                requirement.authorized_issuer_id, requirement.authorized_authority_id,
                requirement.authorized_verifier_id,
            )
            actual = (
                item.requirement_id, item.requirement_version, item.requirement_hash,
                item.policy_id, item.policy_version, item.policy_hash, item.jurisdiction_id,
                item.subject_id, item.activity_id, item.scope, item.use_class,
                item.provider_ref, item.dataset_ref, item.route_ref, item.issuer_id,
                item.authority_id, item.verifier_id,
            )
            if actual != expected:
                raise ValueError
            if (requirement.status is RequirementStatus.EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY
                    and requirement.right_status is RightStatus.GRANTED_CONTRACT_TEST_ONLY):
                capability_states[requirement.capability] = AdmissionState.CONTRACT_TEST_ONLY
        if LegalCapability.RETENTION not in requirements_by_capability:
            for dependent in (LegalCapability.DURABLE_STORAGE, LegalCapability.REPLAY_AUDIT):
                capability_states[dependent] = AdmissionState.REVIEW_REQUIRED
        assessment = seal_contract_test(
            LegalAssessmentEvidence, "assessment_hash", assessment_id=assessment_id,
            assessed_at=assessed_at, jurisdiction_hashes=tuple(j.reference_hash for j in js),
            requirement_hashes=tuple(r.record_hash for r in rs),
            evidence_hashes=tuple(e.reference_hash for e in es),
            reliance_claim_hashes=tuple(c.claim_hash for c in cs),
            unresolved_conflicts=unresolved_conflicts, missing_evidence=missing_evidence,
            reviewer_id=reviewer_id, reviewer_role=LegalRole.LEGAL_REVIEWER,
            state=VerificationState.CONTRACT_TEST_ONLY,
        )
        if unresolved_conflicts or AdmissionState.BLOCKED in capability_states.values():
            state = AdmissionState.BLOCKED
        elif missing_evidence or AdmissionState.REVIEW_REQUIRED in capability_states.values():
            state = AdmissionState.REVIEW_REQUIRED
        else:
            state = AdmissionState.CONTRACT_TEST_ONLY
        decision = seal_contract_test(
            LegalAdmissionDecision, "decision_hash", contract_version=CONTRACT_VERSION,
            assessment_hash=assessment.assessment_hash,
            assessed_at=assessed_at, decision_state=state,
            capability_states=tuple((capability, capability_states[capability])
                                    for capability in LegalCapability),
            operator_id=operator_id,
            reviewer_id=reviewer_id, approver_id=approver_id,
            legal_licensing_real=AdmissionState.NOT_PROVISIONED,
            authority_registry_real=AdmissionState.NOT_PROVISIONED,
            external_counsel_real=AdmissionState.NOT_PROVISIONED,
            provider_admission_real=AdmissionState.NOT_PROVISIONED,
            gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
            real_route="QVM_NOT_READY", global_readiness="INSUFFICIENT_REAL_DATA",
            trade_decision="NO_TRADE", signals_generated=False, live_execution_enabled=False,
            backtesting="NOT_AUTHORIZED",
        )
        return assessment, decision
    except LegalGovernanceError:
        raise
    except BaseException:  # noqa: BLE001
        raise LegalGovernanceError("legal governance assessment failed closed") from None


def assess_real_legal(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise LegalGovernanceError("REAL licensing/legal is NOT_PROVISIONED")


T = TypeVar("T", bound=_Model)
_SEAL_FIELDS = {
    LegalJurisdictionReference: "reference_hash",
    LegalRequirementRecord: "record_hash",
    LegalEvidenceReference: "reference_hash",
    LegalRelianceClaim: "claim_hash",
    LegalAssessmentEvidence: "assessment_hash",
    LegalAdmissionDecision: "decision_hash",
}


def seal_contract_test(model: type[T], hash_field: str, **values: Any) -> T:
    try:
        if _SEAL_FIELDS.get(model) != hash_field or hash_field in values:
            raise TypeError
        values[hash_field] = typed_hash(values)
        return model(**values)
    except LegalGovernanceError:
        raise
    except BaseException:  # noqa: BLE001
        raise LegalGovernanceError("invalid legal governance value") from None


def _rebuild(model: type[T], value: Any) -> T:
    try:
        if type(value) is model:
            raw = BaseModel.model_dump(value, mode="python")
        elif type(value) is dict:
            raw = value
        elif type(value) is str:
            raw = json.loads(value)
        else:
            raise TypeError
        return model.model_validate(raw)
    except BaseException:  # noqa: BLE001
        raise LegalGovernanceError("invalid legal governance value") from None


def _hash(value: BaseModel, field: str) -> None:
    raw = BaseModel.model_dump(value, mode="python", exclude={field})
    if getattr(value, field) != typed_hash(raw):
        raise ValueError


def _ids(*values: str) -> None:
    for value in values:
        if not (type(value) is str and value.isascii() and value == value.casefold()
                and value == unicodedata.normalize("NFKC", value)
                and 3 <= len(value) <= 127
                and all(c.islower() or c.isdigit() or c in "._:-" for c in value)):
            raise ValueError


def _utc(value: dt.datetime) -> None:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError


def _window(start: dt.datetime, end: dt.datetime | None) -> None:
    _utc(start)
    if end is not None:
        _utc(end)
        if start >= end:
            raise ValueError


def _current(start: dt.datetime, end: dt.datetime | None, at: dt.datetime) -> None:
    if at < start or (end is not None and at >= end):
        raise ValueError


def _same_scope(left: Any, right: Any) -> bool:
    return (left.subject_id, left.activity_id, left.scope) == (
        right.subject_id, right.activity_id, right.scope)


def _same_route(left: Any, right: Any) -> bool:
    return (left.provider_ref, left.dataset_ref, left.route_ref) == (
        right.provider_ref, right.dataset_ref, right.route_ref)


def _redact(value: Any, key: str = "") -> Any:
    sensitive = key.endswith("_id") or key in {"provider_ref", "dataset_ref", "route_ref"}
    if sensitive and isinstance(value, str):
        return f"opaque:{typed_hash(value)[:16]}"
    if isinstance(value, dict):
        return {item_key: _redact(item, item_key) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value
