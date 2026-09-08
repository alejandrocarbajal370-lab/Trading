"""IBKR REAL session provisioning and authentic entitlement evidence contracts.

The repository can validate contract-test fixtures, but cannot authenticate REAL
evidence. Connectivity and market-data mode are deliberately excluded from the
entitlement decision.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "ibkr-real-provisioning-entitlement-evidence-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class IBKRRealProvisioningError(ValueError):
    """Untrusted provisioning input failed closed without retaining its value."""


class EvidenceState(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class MarketDataMode(StrEnum):
    REALTIME = "REALTIME"
    FROZEN = "FROZEN"
    DELAYED = "DELAYED"
    DELAYED_FROZEN = "DELAYED_FROZEN"
    UNKNOWN = "UNKNOWN"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - rejected values can contain secrets
            raise IBKRRealProvisioningError("invalid IBKR evidence value") from None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        try:
            return super().model_validate(obj, **kwargs)
        except BaseException:  # noqa: BLE001
            raise IBKRRealProvisioningError("invalid IBKR evidence value") from None

    @classmethod
    def model_validate_json(cls, value: str | bytes | bytearray, **kwargs: Any):
        try:
            return super().model_validate_json(value, **kwargs)
        except BaseException:  # noqa: BLE001
            raise IBKRRealProvisioningError("invalid IBKR evidence value") from None


class EvidenceLifecycle(_Model):
    requested_at: dt.datetime
    available_at: dt.datetime
    effective_at: dt.datetime
    verified_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    lifecycle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_lifecycle(self):
        values = (
            self.requested_at,
            self.available_at,
            self.effective_at,
            self.verified_at,
            self.expires_at,
        )
        for value in (*values, self.revoked_at):
            if value is not None:
                _utc(value)
        if values != tuple(sorted(values)) or self.verified_at >= self.expires_at:
            raise ValueError("invalid lifecycle")
        if self.revoked_at is not None and self.revoked_at < self.available_at:
            raise ValueError("invalid revocation")
        _hash(self, "lifecycle_hash")
        return self


class IBKRSessionBinding(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    provider: Literal["provider.ibkr"]
    adapter_id: str = Field(pattern=IDENTIFIER)
    dataset_id: str = Field(pattern=IDENTIFIER)
    route_id: str = Field(pattern=IDENTIFIER)
    request_id: str = Field(pattern=IDENTIFIER)
    request_hash: str = Field(pattern=SHA256)
    security_master_id: Literal["security.us.msft.xnas"]
    con_id: Literal[272093]
    credential_backend_reference_digest: str = Field(pattern=SHA256)
    deployment_reference_digest: str = Field(pattern=SHA256)
    session_reference_digest: str = Field(pattern=SHA256)
    session_evidence_digest: str = Field(pattern=SHA256)
    read_only: Literal[True]
    lifecycle: EvidenceLifecycle
    binding_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_binding(self):
        for value in (self.adapter_id, self.dataset_id, self.route_id, self.request_id):
            _identifier(value)
        object.__setattr__(self, "lifecycle", _deep(EvidenceLifecycle, self.lifecycle))
        _hash(self, "binding_hash")
        return self


class AuthenticEntitlementEvidence(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    provider: Literal["provider.ibkr"]
    adapter_id: str = Field(pattern=IDENTIFIER)
    dataset_id: str = Field(pattern=IDENTIFIER)
    route_id: str = Field(pattern=IDENTIFIER)
    request_id: str = Field(pattern=IDENTIFIER)
    request_hash: str = Field(pattern=SHA256)
    security_master_id: Literal["security.us.msft.xnas"]
    con_id: Literal[272093]
    session_binding_hash: str = Field(pattern=SHA256)
    session_evidence_digest: str = Field(pattern=SHA256)
    entitlement_authority_reference_digest: str = Field(pattern=SHA256)
    entitlement_evidence_digest: str = Field(pattern=SHA256)
    entitlement_scope_digest: str = Field(pattern=SHA256)
    lifecycle: EvidenceLifecycle
    state: Literal[EvidenceState.CONTRACT_TEST_ONLY]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_entitlement(self):
        for value in (self.adapter_id, self.dataset_id, self.route_id, self.request_id):
            _identifier(value)
        object.__setattr__(self, "lifecycle", _deep(EvidenceLifecycle, self.lifecycle))
        _hash(self, "evidence_hash")
        return self


class SessionObservation(_Model):
    """Operational observation only; it is never entitlement evidence."""

    session_binding_hash: str = Field(pattern=SHA256)
    observed_at: dt.datetime
    market_mode: MarketDataMode
    socket_connected: bool
    callbacks_observed: bool
    ticks_observed: bool
    observation_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_observation(self):
        _utc(self.observed_at)
        _hash(self, "observation_digest")
        return self


class ContractAssessment(_Model):
    state: Literal[EvidenceState.CONTRACT_TEST_ONLY]
    session_operational_contract_validated: Literal[True]
    authentic_entitlement_real: Literal[EvidenceState.NOT_PROVISIONED]
    provider_admission_real: Literal[EvidenceState.NOT_PROVISIONED]
    independent_verifier_real: Literal[EvidenceState.NOT_PROVISIONED]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]

    @model_validator(mode="after")
    def validate_assessment(self):
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError("REAL gates remain open")
        return self


def assess_contract_test(
    session: IBKRSessionBinding | dict[str, Any] | str,
    entitlement: AuthenticEntitlementEvidence | dict[str, Any] | str,
    observation: SessionObservation | dict[str, Any] | str,
    *,
    assessed_at: dt.datetime,
) -> ContractAssessment:
    """Reconstruct and validate contract fixtures without conferring REAL trust."""

    failed = False
    try:
        _utc(assessed_at)
        session = _rebuild(IBKRSessionBinding, session)
        entitlement = _rebuild(AuthenticEntitlementEvidence, entitlement)
        observation = _rebuild(SessionObservation, observation)
        if not _same_scope(session, entitlement):
            raise ValueError("scope mismatch")
        if entitlement.session_binding_hash != session.binding_hash:
            raise ValueError("session swap")
        if entitlement.session_evidence_digest != session.session_evidence_digest:
            raise ValueError("session evidence swap")
        if observation.session_binding_hash != session.binding_hash:
            raise ValueError("observation swap")
        if not entitlement.lifecycle.verified_at <= assessed_at < entitlement.lifecycle.expires_at:
            raise ValueError("entitlement unavailable")
        if not session.lifecycle.verified_at <= assessed_at < session.lifecycle.expires_at:
            raise ValueError("session unavailable")
        if entitlement.lifecycle.revoked_at is not None and entitlement.lifecycle.revoked_at <= assessed_at:
            raise ValueError("entitlement revoked")
        if session.lifecycle.revoked_at is not None and session.lifecycle.revoked_at <= assessed_at:
            raise ValueError("session revoked")
        if observation.observed_at > assessed_at:
            raise ValueError("future observation")
    except BaseException:  # noqa: BLE001 - never retain attacker-controlled values
        failed = True
    if failed:
        raise IBKRRealProvisioningError("IBKR evidence assessment failed closed")
    return ContractAssessment(
        state=EvidenceState.CONTRACT_TEST_ONLY,
        session_operational_contract_validated=True,
        authentic_entitlement_real=EvidenceState.NOT_PROVISIONED,
        provider_admission_real=EvidenceState.NOT_PROVISIONED,
        independent_verifier_real=EvidenceState.NOT_PROVISIONED,
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
        real_route="QVM_NOT_READY",
        global_readiness="INSUFFICIENT_REAL_DATA",
        trade_decision="NO_TRADE",
        signals_generated=False,
        live_execution_enabled=False,
        backtesting="NOT_AUTHORIZED",
    )


def check_real_provisioning() -> EvidenceState:
    """Honest REAL checker until an independent verifier is externally provisioned."""

    return EvidenceState.NOT_PROVISIONED


T = TypeVar("T", bound=_Model)


def seal_contract_test(model: type[T], hash_field: str, **values: Any) -> T:
    if hash_field in values:
        raise IBKRRealProvisioningError("hash must be derived")
    values[hash_field] = typed_hash(values)
    return model(**values)


def _rebuild(model: type[T], value: T | dict[str, Any] | str) -> T:
    if isinstance(value, str):
        return model.model_validate_json(value)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    return model.model_validate(value)


def _deep(model: type[T], value: T | dict[str, Any]) -> T:
    return model.model_validate(value.model_dump(mode="python") if isinstance(value, BaseModel) else value)


def _same_scope(left: IBKRSessionBinding, right: AuthenticEntitlementEvidence) -> bool:
    fields = ("provider", "adapter_id", "dataset_id", "route_id", "request_id", "request_hash", "security_master_id", "con_id")
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _utc(value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC required")


def _identifier(value: str) -> None:
    if value != unicodedata.normalize("NFKC", value) or not value.isascii() or value != value.lower():
        raise ValueError("noncanonical identifier")


def _hash(value: BaseModel, field: str) -> None:
    expected = typed_hash(value.model_dump(mode="python", exclude={field}))
    if getattr(value, field) != expected:
        raise ValueError("hash mismatch")
