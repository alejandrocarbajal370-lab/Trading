"""External custody observation boundary; no REAL custody proof is provisioned."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.durable_replay import PersistenceReceipt
from governance.external_provider_foundation import (
    FoundationError,
    ProviderRegistry,
    ProvisioningState,
)
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "external-custody-retention-boundary-v1"
SHA256 = r"^[0-9a-f]{64}$"
OID = r"^[a-z0-9][a-z0-9._:/-]{2,255}$"


class CustodyObservationState(StrEnum):
    OBSERVED_UNTRUSTED = "OBSERVED_UNTRUSTED"


class RetentionMode(StrEnum):
    DECLARED_GOVERNANCE_RETENTION = "DECLARED_GOVERNANCE_RETENTION"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CustodyLocation(_ContractModel):
    provider_id: str = Field(pattern=OID)
    container_id: str = Field(pattern=OID)
    object_id: str = Field(pattern=OID)
    object_version: str = Field(pattern=OID)
    location_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_location(self):
        for label in ("provider_id", "container_id", "object_id", "object_version"):
            _unambiguous_identifier(getattr(self, label), label)
        _check_hash(self, "location_hash")
        return self


class RetentionDeclaration(_ContractModel):
    policy_id: str = Field(pattern=OID)
    mode: Literal[RetentionMode.DECLARED_GOVERNANCE_RETENTION]
    retained_from: dt.datetime
    retain_until: dt.datetime
    legal_hold_declared: bool
    declaration_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_declaration(self):
        _unambiguous_identifier(self.policy_id, "policy_id")
        _utc(self.retained_from, "retained_from")
        _utc(self.retain_until, "retain_until")
        if self.retain_until <= self.retained_from:
            raise ValueError("retention interval must be positive")
        _check_hash(self, "declaration_hash")
        return self


class RawCustodyObservation(_ContractModel):
    contract_version: Literal["external-custody-retention-boundary-v1"] = CONTRACT_VERSION
    trust_domain: Literal["CONTRACT_TEST_ONLY"]
    persistence_receipt: PersistenceReceipt
    location: CustodyLocation
    retention: RetentionDeclaration
    raw_evidence_digest: str = Field(pattern=SHA256)
    raw_evidence_size: int = Field(gt=0)
    observed_at: dt.datetime
    observation_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_observation(self):
        receipt = _revalidate(PersistenceReceipt, self.persistence_receipt, "persistence receipt")
        _utc(receipt.committed_at, "committed_at")
        _retention_receipt(receipt)
        _revalidate(CustodyLocation, self.location, "custody location")
        _revalidate(RetentionDeclaration, self.retention, "retention declaration")
        _utc(self.observed_at, "observed_at")
        if self.observed_at < receipt.committed_at:
            raise ValueError("custody observation precedes durable replay commit")
        if self.retention.retained_from < receipt.committed_at:
            raise ValueError("retention start precedes durable replay commit")
        if self.observed_at < self.retention.retained_from:
            raise ValueError("custody observation precedes retention start")
        if self.observed_at >= self.retention.retain_until:
            raise ValueError("custody observation is outside retention interval")
        _check_hash(self, "observation_hash")
        return self


class CustodyBoundaryAssessment(_ContractModel):
    observation: RawCustodyObservation
    state: Literal[CustodyObservationState.OBSERVED_UNTRUSTED]
    assessed_at: dt.datetime
    external_custody: Literal[ProvisioningState.NOT_PROVISIONED]
    worm_retention: Literal[ProvisioningState.NOT_PROVISIONED]
    legal_retention_approval: Literal[ProvisioningState.NOT_PROVISIONED]
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED]
    independent_verifier: Literal[ProvisioningState.NOT_PROVISIONED]
    gate_state: Literal[GateState.OPEN_EXTERNAL]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]
    assessment_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_assessment(self):
        _revalidate(RawCustodyObservation, self.observation, "custody observation")
        _utc(self.assessed_at, "assessed_at")
        if self.assessed_at < self.observation.observed_at:
            raise ValueError("assessment precedes custody observation")
        if self.assessed_at >= self.observation.retention.retain_until:
            raise ValueError("assessment is outside retention interval")
        _check_hash(self, "assessment_hash")
        return self


def observe_contract_test_custody(
    *,
    persistence_receipt: Any,
    provider_id: str,
    container_id: str,
    object_id: str,
    object_version: str,
    policy_id: str,
    retained_from: dt.datetime,
    retain_until: dt.datetime,
    legal_hold_declared: bool,
    raw_evidence: bytes,
    observed_at: dt.datetime,
) -> RawCustodyObservation:
    """Content-address raw evidence without treating declarations as external truth."""
    receipt = _revalidate(PersistenceReceipt, persistence_receipt, "persistence receipt")
    if receipt.adapter_mode is not ProvisioningState.CONTRACT_TEST_ONLY:
        raise FoundationError("only contract-test persistence receipts are accepted")
    _retention_receipt(receipt)
    if not isinstance(raw_evidence, bytes) or not raw_evidence:
        raise FoundationError("raw custody evidence must be non-empty bytes")
    _utc(receipt.committed_at, "committed_at")
    _utc(retained_from, "retained_from")
    _utc(retain_until, "retain_until")
    _utc(observed_at, "observed_at")
    if retained_from < receipt.committed_at:
        raise FoundationError("retention start precedes durable replay commit")
    if observed_at < receipt.committed_at:
        raise FoundationError("custody observation precedes durable replay commit")
    location = _seal(
        CustodyLocation,
        "location_hash",
        provider_id=provider_id,
        container_id=container_id,
        object_id=object_id,
        object_version=object_version,
    )
    retention = _seal(
        RetentionDeclaration,
        "declaration_hash",
        policy_id=policy_id,
        mode=RetentionMode.DECLARED_GOVERNANCE_RETENTION,
        retained_from=retained_from,
        retain_until=retain_until,
        legal_hold_declared=legal_hold_declared,
    )
    return _seal(
        RawCustodyObservation,
        "observation_hash",
        trust_domain="CONTRACT_TEST_ONLY",
        persistence_receipt=receipt,
        location=location,
        retention=retention,
        raw_evidence_digest=hashlib.sha256(raw_evidence).hexdigest(),
        raw_evidence_size=len(raw_evidence),
        observed_at=observed_at,
    )


def assess_contract_test_custody(
    observation: Any, *, raw_evidence: bytes, assessed_at: dt.datetime
) -> CustodyBoundaryAssessment:
    """Deeply revalidate an observation and keep every external gate open."""
    canonical = _revalidate(RawCustodyObservation, observation, "custody observation")
    if not isinstance(raw_evidence, bytes) or not raw_evidence:
        raise FoundationError("raw custody evidence must be non-empty bytes")
    if len(raw_evidence) != canonical.raw_evidence_size:
        raise FoundationError("raw custody evidence size mismatch")
    if hashlib.sha256(raw_evidence).hexdigest() != canonical.raw_evidence_digest:
        raise FoundationError("raw custody evidence digest mismatch")
    return _seal(
        CustodyBoundaryAssessment,
        "assessment_hash",
        observation=canonical,
        state=CustodyObservationState.OBSERVED_UNTRUSTED,
        assessed_at=assessed_at,
        external_custody=ProvisioningState.NOT_PROVISIONED,
        worm_retention=ProvisioningState.NOT_PROVISIONED,
        legal_retention_approval=ProvisioningState.NOT_PROVISIONED,
        trust_root=ProvisioningState.NOT_PROVISIONED,
        independent_verifier=ProvisioningState.NOT_PROVISIONED,
        gate_state=GateState.OPEN_EXTERNAL,
        trade_decision="NO_TRADE",
        signals_generated=False,
        live_execution_enabled=False,
        backtesting="NOT_AUTHORIZED",
    )


def verify_real_external_custody(*, gate: EvidenceGate, evidence: Any) -> None:
    """Sealed REAL route: the repository owns no authority, backend or trust root."""
    _revalidate(EvidenceGateValue, {"gate": gate}, "evidence gate")
    del evidence
    raise FoundationError("REAL external custody verification is NOT_PROVISIONED")


class EvidenceGateValue(_ContractModel):
    gate: EvidenceGate


T = TypeVar("T", bound=BaseModel)


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise FoundationError("model contains undeclared fields")
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise FoundationError("input is not canonically serializable") from exc


def _revalidate(expected: type[T], value: Any, label: str) -> T:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FoundationError(f"invalid {label}") from exc


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(raw.model_dump(mode="json", exclude={hash_field}, warnings=False))
    return expected(**values)


def _check_hash(value: BaseModel, hash_field: str) -> None:
    expected = typed_hash(value.model_dump(mode="json", exclude={hash_field}, warnings=False))
    if getattr(value, hash_field) != expected:
        raise ValueError(f"{hash_field} mismatch")


def _utc(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    if value.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{label} must use canonical UTC")


def _retention_receipt(receipt: PersistenceReceipt) -> None:
    expected = ProviderRegistry.resolve(EvidenceGate.RETENTION_WORM).route_hash
    if receipt.replay_identity.route_hash != expected:
        raise FoundationError("persistence receipt is not bound to the retention gate")


def _unambiguous_identifier(value: str, label: str) -> None:
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise ValueError(f"{label} contains ambiguous path segments")
