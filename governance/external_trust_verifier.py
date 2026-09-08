"""External trust, attestation and independent-verifier REAL foundation.

Only contract-test graph validation is implemented.  No repository-local value can
become REAL trusted or verified evidence.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.ibkr_real_provisioning import (
    AuthenticEntitlementEvidence,
    IBKRSessionBinding,
    SessionObservation,
)
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "external-trust-attestation-independent-verifier-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class ExternalTrustError(ValueError):
    """Untrusted external-trust input failed closed."""


class ProvisioningState(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class PrincipalRole(StrEnum):
    AUTHORITY = "AUTHORITY"
    REVOCATION_OWNER = "REVOCATION_OWNER"
    ATTESTER = "ATTESTER"
    VERIFIER = "VERIFIER"
    PROVISIONING_MAKER = "PROVISIONING_MAKER"
    PROVISIONING_CHECKER = "PROVISIONING_CHECKER"
    RUNTIME_OPERATOR = "RUNTIME_OPERATOR"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        failed = False
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - rejected input may contain secrets
            failed = True
        if failed:
            raise ExternalTrustError("invalid external trust value") from None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        result = None
        try:
            result = super().model_validate(obj, **kwargs)
        except BaseException:  # noqa: BLE001
            result = None
        if result is None:
            raise ExternalTrustError("invalid external trust value") from None
        return result

    @classmethod
    def model_validate_json(cls, value: str | bytes | bytearray, **kwargs: Any):
        result = None
        try:
            result = super().model_validate_json(value, **kwargs)
        except BaseException:  # noqa: BLE001
            result = None
        if result is None:
            raise ExternalTrustError("invalid external trust value") from None
        return result


class ExternalLifecycle(_Model):
    requested_at: dt.datetime
    available_at: dt.datetime
    effective_at: dt.datetime
    verified_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    lifecycle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_lifecycle(self):
        ordered = (self.requested_at, self.available_at, self.effective_at, self.verified_at)
        for value in (*ordered, self.expires_at, self.revoked_at):
            if value is not None:
                _utc(value)
        if ordered != tuple(sorted(ordered)) or self.verified_at >= self.expires_at:
            raise ValueError("invalid lifecycle chronology")
        if self.revoked_at is not None and self.revoked_at < self.available_at:
            raise ValueError("invalid lifecycle revocation")
        _hash(self, "lifecycle_hash")
        return self


class PrincipalProvisioningEvidence(_Model):
    principal_id: str = Field(pattern=IDENTIFIER)
    role: PrincipalRole
    principal_reference_digest: str = Field(pattern=SHA256)
    authority_registry_reference_digest: str = Field(pattern=SHA256)
    provisioning_evidence_digest: str = Field(pattern=SHA256)
    lifecycle: ExternalLifecycle
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_evidence(self):
        _identifier(self.principal_id)
        object.__setattr__(self, "lifecycle", _deep(ExternalLifecycle, self.lifecycle))
        _hash(self, "evidence_hash")
        return self


class TrustAnchorProvisioningEvidence(_Model):
    trust_anchor_id: str = Field(pattern=IDENTIFIER)
    trust_anchor_reference_digest: str = Field(pattern=SHA256)
    public_material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    lineage_digest: str = Field(pattern=SHA256)
    lifecycle: ExternalLifecycle
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_evidence(self):
        _identifier(self.trust_anchor_id)
        object.__setattr__(self, "lifecycle", _deep(ExternalLifecycle, self.lifecycle))
        _hash(self, "evidence_hash")
        return self


class AuthorityRegistryEvidence(_Model):
    registry_id: str = Field(pattern=IDENTIFIER)
    registry_reference_digest: str = Field(pattern=SHA256)
    trust_anchor_evidence_hash: str = Field(pattern=SHA256)
    authority_principal_digest: str = Field(pattern=SHA256)
    revocation_owner_principal_digest: str = Field(pattern=SHA256)
    registry_material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    lineage_digest: str = Field(pattern=SHA256)
    lifecycle: ExternalLifecycle
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_evidence(self):
        _identifier(self.registry_id)
        object.__setattr__(self, "lifecycle", _deep(ExternalLifecycle, self.lifecycle))
        _hash(self, "evidence_hash")
        return self


class ExternalAttestationEnvelope(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    attestation_id: str = Field(pattern=IDENTIFIER)
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
    entitlement_evidence_hash: str = Field(pattern=SHA256)
    observation_digest: str = Field(pattern=SHA256)
    backend_reference_digest: str = Field(pattern=SHA256)
    deployment_reference_digest: str = Field(pattern=SHA256)
    trust_anchor_evidence_hash: str = Field(pattern=SHA256)
    authority_registry_evidence_hash: str = Field(pattern=SHA256)
    attester_principal_evidence_hash: str = Field(pattern=SHA256)
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    lineage_digest: str = Field(pattern=SHA256)
    available_at: dt.datetime
    effective_at: dt.datetime
    attested_at: dt.datetime
    expires_at: dt.datetime
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    envelope_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_envelope(self):
        for value in (self.adapter_id, self.dataset_id, self.route_id, self.request_id, self.attestation_id):
            _identifier(value)
        times = (self.available_at, self.effective_at, self.attested_at)
        for value in (*times, self.expires_at):
            _utc(value)
        if times != tuple(sorted(times)) or self.attested_at >= self.expires_at:
            raise ValueError("invalid attestation chronology")
        _hash(self, "envelope_hash")
        return self


class IndependentVerificationResult(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    verification_id: str = Field(pattern=IDENTIFIER)
    attestation_id: str = Field(pattern=IDENTIFIER)
    attestation_envelope_hash: str = Field(pattern=SHA256)
    trust_anchor_evidence_hash: str = Field(pattern=SHA256)
    authority_registry_evidence_hash: str = Field(pattern=SHA256)
    verifier_principal_evidence_hash: str = Field(pattern=SHA256)
    verification_material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    lineage_digest: str = Field(pattern=SHA256)
    verified_at: dt.datetime
    expires_at: dt.datetime
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    result_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_result(self):
        _identifier(self.verification_id)
        _identifier(self.attestation_id)
        _utc(self.verified_at)
        _utc(self.expires_at)
        if self.verification_id == self.attestation_id or self.verified_at >= self.expires_at:
            raise ValueError("invalid independent verification")
        _hash(self, "result_hash")
        return self


class ExternalTrustAssessment(_Model):
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    attestation_contract_validated: Literal[True]
    independent_verification_contract_validated: Literal[True]
    trust_anchor_real: Literal[ProvisioningState.NOT_PROVISIONED]
    authority_registry_real: Literal[ProvisioningState.NOT_PROVISIONED]
    attester_real: Literal[ProvisioningState.NOT_PROVISIONED]
    independent_verifier_real: Literal[ProvisioningState.NOT_PROVISIONED]
    provider_admission_real: Literal[ProvisioningState.NOT_PROVISIONED]
    custody_worm_replay_real: Literal[ProvisioningState.NOT_PROVISIONED]
    legal_licensing_real: Literal[ProvisioningState.NOT_PROVISIONED]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]


def assess_contract_test(
    *, session: Any, entitlement: Any, observation: Any, trust_anchor: Any,
    authority_registry: Any, principals: tuple[Any, ...], attestations: tuple[Any, ...],
    verification: Any, assessed_at: dt.datetime,
) -> ExternalTrustAssessment:
    """Validate two independent contract steps without granting REAL trust."""
    failed = False
    try:
        session = _rebuild(IBKRSessionBinding, session)
        entitlement = _rebuild(AuthenticEntitlementEvidence, entitlement)
        observation = _rebuild(SessionObservation, observation)
        anchor = _rebuild(TrustAnchorProvisioningEvidence, trust_anchor)
        registry = _rebuild(AuthorityRegistryEvidence, authority_registry)
        if type(principals) is not tuple:
            raise TypeError("exact principal tuple required")
        people = tuple(_rebuild(PrincipalProvisioningEvidence, item) for item in principals)
        if type(attestations) is not tuple or len(attestations) != 1:
            raise ValueError("duplicate or missing attestation")
        envelope = _rebuild(ExternalAttestationEnvelope, attestations[0])
        result = _rebuild(IndependentVerificationResult, verification)
        _utc(assessed_at)
        if tuple(item.role for item in people) != tuple(PrincipalRole):
            raise ValueError("principal roles incomplete or reordered")
        if len({item.principal_id for item in people}) != len(people) or len(
            {item.principal_reference_digest for item in people}
        ) != len(people):
            raise ValueError("principal identities not independent")
        by_role = {item.role: item for item in people}
        if registry.trust_anchor_evidence_hash != anchor.evidence_hash:
            raise ValueError("trust anchor rotation or swap")
        if registry.authority_principal_digest != by_role[PrincipalRole.AUTHORITY].principal_reference_digest:
            raise ValueError("authority swap")
        if registry.revocation_owner_principal_digest != by_role[PrincipalRole.REVOCATION_OWNER].principal_reference_digest:
            raise ValueError("revocation owner swap")
        if any(item.authority_registry_reference_digest != registry.registry_reference_digest for item in people):
            raise ValueError("authority registry swap")
        _scope(session, entitlement, envelope)
        if observation.session_binding_hash != session.binding_hash:
            raise ValueError("observation session swap")
        if envelope.session_binding_hash != session.binding_hash or envelope.session_evidence_digest != session.session_evidence_digest:
            raise ValueError("attestation session swap")
        if envelope.entitlement_evidence_hash != entitlement.evidence_hash or envelope.observation_digest != observation.observation_digest:
            raise ValueError("attestation evidence swap")
        if envelope.backend_reference_digest != session.credential_backend_reference_digest or envelope.deployment_reference_digest != session.deployment_reference_digest:
            raise ValueError("backend or deployment swap")
        if envelope.trust_anchor_evidence_hash != anchor.evidence_hash or envelope.authority_registry_evidence_hash != registry.evidence_hash:
            raise ValueError("trust graph swap")
        if envelope.attester_principal_evidence_hash != by_role[PrincipalRole.ATTESTER].evidence_hash:
            raise ValueError("attester swap")
        if result.attestation_id != envelope.attestation_id or result.attestation_envelope_hash != envelope.envelope_hash:
            raise ValueError("verification copied to another attestation")
        if result.trust_anchor_evidence_hash != anchor.evidence_hash or result.authority_registry_evidence_hash != registry.evidence_hash:
            raise ValueError("verification trust graph swap")
        if result.verifier_principal_evidence_hash != by_role[PrincipalRole.VERIFIER].evidence_hash:
            raise ValueError("verifier swap")
        if observation.observed_at > envelope.available_at or entitlement.lifecycle.verified_at > envelope.available_at or session.lifecycle.verified_at > envelope.available_at:
            raise ValueError("attestation predates upstream evidence")
        if envelope.attested_at > result.verified_at or result.verified_at > assessed_at:
            raise ValueError("impossible verification chronology")
        if assessed_at >= result.expires_at or assessed_at >= envelope.expires_at:
            raise ValueError("attestation or verification expired")
        for lifecycle, label in (
            (session.lifecycle, "session"),
            (entitlement.lifecycle, "entitlement"),
        ):
            if not lifecycle.verified_at <= assessed_at < lifecycle.expires_at:
                raise ValueError(f"{label} evidence unavailable at assessment")
            if lifecycle.revoked_at is not None and lifecycle.revoked_at <= assessed_at:
                raise ValueError(f"{label} evidence revoked at assessment")
        for item in (anchor, registry, *people):
            lifecycle = item.lifecycle
            if not lifecycle.verified_at <= envelope.attested_at < lifecycle.expires_at:
                raise ValueError("trust evidence unavailable at attestation")
            if not lifecycle.verified_at <= result.verified_at < lifecycle.expires_at:
                raise ValueError("trust evidence unavailable at verification")
            if lifecycle.revoked_at is not None and lifecycle.revoked_at <= result.verified_at:
                raise ValueError("trust evidence revoked")
            if not lifecycle.verified_at <= assessed_at < lifecycle.expires_at:
                raise ValueError("trust evidence unavailable at assessment")
            if lifecycle.revoked_at is not None and lifecycle.revoked_at <= assessed_at:
                raise ValueError("trust evidence revoked at assessment")
    except BaseException:  # noqa: BLE001 - discard hostile values and exceptions
        failed = True
    if failed:
        raise ExternalTrustError("external trust assessment failed closed") from None
    return ExternalTrustAssessment(
        state=ProvisioningState.CONTRACT_TEST_ONLY,
        attestation_contract_validated=True,
        independent_verification_contract_validated=True,
        trust_anchor_real=ProvisioningState.NOT_PROVISIONED,
        authority_registry_real=ProvisioningState.NOT_PROVISIONED,
        attester_real=ProvisioningState.NOT_PROVISIONED,
        independent_verifier_real=ProvisioningState.NOT_PROVISIONED,
        provider_admission_real=ProvisioningState.NOT_PROVISIONED,
        custody_worm_replay_real=ProvisioningState.NOT_PROVISIONED,
        legal_licensing_real=ProvisioningState.NOT_PROVISIONED,
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
        real_route="QVM_NOT_READY", global_readiness="INSUFFICIENT_REAL_DATA",
        trade_decision="NO_TRADE", signals_generated=False, live_execution_enabled=False,
        backtesting="NOT_AUTHORIZED",
    )


def check_real_external_trust() -> ProvisioningState:
    """No external resolver is installed in this repository."""
    return ProvisioningState.NOT_PROVISIONED


def verify_real(*args: Any, **kwargs: Any) -> None:
    """Reject local adapters, callbacks, signers and monkeypatched collaborators."""
    del args, kwargs
    raise ExternalTrustError("REAL external trust and independent verifier are NOT_PROVISIONED")


T = TypeVar("T", bound=_Model)


def seal_contract_test(model: type[T], hash_field: str, **values: Any) -> T:
    result = None
    try:
        if _SEAL_FIELDS.get(model) != hash_field or hash_field in values:
            raise TypeError("unsupported contract")
        values[hash_field] = typed_hash(_safe(values))
        result = model(**values)
    except BaseException:  # noqa: BLE001
        result = None
    if result is None:
        raise ExternalTrustError("invalid external trust value") from None
    return result


def _rebuild(model: type[T], value: Any) -> T:
    if type(value) is str:
        return model.model_validate_json(value)
    if type(value) is model:
        value = BaseModel.model_dump(value, mode="python")
    elif type(value) is not dict:
        raise ExternalTrustError("invalid external trust value")
    return model.model_validate(value)


def _deep(model: type[T], value: Any) -> T:
    return _rebuild(model, value)


def _safe(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int, float, dt.datetime}:
        if type(value) is dt.datetime:
            _utc(value)
        return value
    if type(value) in {ProvisioningState, PrincipalRole}:
        return value
    if type(value) is dict:
        clean = {}
        for key, item in dict.items(value):
            if type(key) is not str:
                raise TypeError("unsupported mapping key")
            clean[key] = _safe(item)
        return clean
    if type(value) in {tuple, list}:
        return type(value)(_safe(item) for item in value)
    if type(value) in _SEAL_FIELDS:
        raw = object.__getattribute__(value, "__dict__")
        return {name: _safe(dict.__getitem__(raw, name)) for name in type(value).model_fields}
    raise TypeError("unsupported contract value")


def _scope(session: IBKRSessionBinding, entitlement: AuthenticEntitlementEvidence, envelope: ExternalAttestationEnvelope) -> None:
    fields = ("provider", "adapter_id", "dataset_id", "route_id", "request_id", "request_hash", "security_master_id", "con_id")
    if any(getattr(session, field) != getattr(entitlement, field) or getattr(session, field) != getattr(envelope, field) for field in fields):
        raise ValueError("provider/session/security/request/route scope swap")


def _identifier(value: str) -> None:
    if not value.isascii() or value != value.casefold() or value != unicodedata.normalize("NFKC", value):
        raise ValueError("noncanonical identifier")


def _utc(value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC required")


def _hash(value: BaseModel, field: str) -> None:
    raw = object.__getattribute__(value, "__dict__")
    payload = {name: _safe(dict.__getitem__(raw, name)) for name in type(value).model_fields if name != field}
    if dict.__getitem__(raw, field) != typed_hash(payload):
        raise ValueError("hash mismatch")


_SEAL_FIELDS: dict[type[_Model], str] = {
    ExternalLifecycle: "lifecycle_hash",
    PrincipalProvisioningEvidence: "evidence_hash",
    TrustAnchorProvisioningEvidence: "evidence_hash",
    AuthorityRegistryEvidence: "evidence_hash",
    ExternalAttestationEnvelope: "envelope_hash",
    IndependentVerificationResult: "result_hash",
}
