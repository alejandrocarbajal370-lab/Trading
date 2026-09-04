"""IBKR external-attestation contract; REAL verification is not provisioned."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.ibkr_probe import MarketDataMode, ProbeEvidence, SourceKind
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "ibkr-observation-external-attestation-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class ExternalAttestationError(ValueError):
    """An untrusted value failed the external-attestation boundary."""


class ProvisioningState(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class ContractVerificationState(StrEnum):
    CONTRACT_TEST_VERIFIED = "CONTRACT_TEST_VERIFIED"


class ActorRole(StrEnum):
    ATTESTER = "ATTESTER"
    VERIFIER = "VERIFIER"
    RUNTIME_OPERATOR = "RUNTIME_OPERATOR"
    PROVISIONING_MAKER = "PROVISIONING_MAKER"
    AUTHORITY = "AUTHORITY"
    REVOCATION_OWNER = "REVOCATION_OWNER"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        failed = False
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - rejected values may contain secrets
            failed = True
        if failed:
            raise ExternalAttestationError("invalid external attestation value")

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        return cls._sanitized_validate("model_validate", obj, kwargs)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any):
        return cls._sanitized_validate("model_validate_json", json_data, kwargs)

    @classmethod
    def model_validate_strings(cls, obj: Any, **kwargs: Any):
        return cls._sanitized_validate("model_validate_strings", obj, kwargs)

    @classmethod
    def _sanitized_validate(cls, route: str, value: Any, kwargs: dict[str, Any]):
        failed = False
        try:
            validator = getattr(super(), route)
            result = validator(value, **kwargs)
        except BaseException:  # noqa: BLE001 - Pydantic errors retain rejected input
            failed = True
            result = None
        if failed:
            raise ExternalAttestationError("invalid external attestation value")
        return result


class ActorIdentity(_Model):
    actor_id: str = Field(pattern=IDENTIFIER)
    role: ActorRole
    identity_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_actor(self):
        _identifier(self.actor_id, "actor_id")
        _hash(self, "identity_digest")
        return self


class ActorLifecycle(_Model):
    actor_identity_digest: str = Field(pattern=SHA256)
    role: ActorRole
    effective_at: dt.datetime
    available_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    lifecycle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_lifecycle(self):
        for name in ("effective_at", "available_at", "expires_at", "revoked_at"):
            _utc(getattr(self, name), name)
        if not self.effective_at <= self.available_at < self.expires_at:
            raise ValueError("invalid actor lifecycle chronology")
        if self.revoked_at is not None and self.revoked_at <= self.available_at:
            raise ValueError("actor revocation must follow availability")
        _hash(self, "lifecycle_hash")
        return self


class ExternalTrustLifecycle(_Model):
    anchor_id: str = Field(pattern=IDENTIFIER)
    authority_id: str = Field(pattern=IDENTIFIER)
    public_material_digest: str = Field(pattern=SHA256)
    registry_digest: str = Field(pattern=SHA256)
    authority_identity_digest: str = Field(pattern=SHA256)
    actor_lifecycles: tuple[ActorLifecycle, ...]
    effective_at: dt.datetime
    available_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    mode: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    lifecycle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_lifecycle(self):
        _identifier(self.anchor_id, "anchor_id")
        _identifier(self.authority_id, "authority_id")
        for name in ("effective_at", "available_at", "expires_at", "revoked_at"):
            _utc(getattr(self, name), name)
        if not self.effective_at <= self.available_at < self.expires_at:
            raise ValueError("invalid trust lifecycle chronology")
        if self.revoked_at is not None and self.revoked_at <= self.available_at:
            raise ValueError("revocation must follow trust availability")
        lifecycles = tuple(
            _deep(ActorLifecycle, item, "actor lifecycle") for item in self.actor_lifecycles
        )
        if tuple(item.role for item in lifecycles) != tuple(ActorRole):
            raise ValueError("actor lifecycles must be exact and ordered")
        if len({item.actor_identity_digest for item in lifecycles}) != len(lifecycles):
            raise ValueError("actor lifecycle identities must be independent")
        authority = lifecycles[tuple(ActorRole).index(ActorRole.AUTHORITY)]
        if authority.actor_identity_digest != self.authority_identity_digest:
            raise ValueError("authority lifecycle identity mismatch")
        _hash(self, "lifecycle_hash")
        return self


class ObservationAttestationBinding(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    provider: Literal["provider.ibkr"]
    adapter: Literal["adapter.ibkr.python-api.local-read-only-probe"]
    dataset: Literal["PRICES_OHLCV"]
    evidence_hash: str = Field(pattern=SHA256)
    request_hash: str = Field(pattern=SHA256)
    request_id: str = Field(pattern=IDENTIFIER)
    security_master_id: Literal["security.us.msft.xnas"]
    permanent_id: Literal["ibkr.conid.272093"]
    lineage_digest: str = Field(pattern=SHA256)
    market_mode: MarketDataMode
    requested_at: dt.datetime
    retrieved_at: dt.datetime
    observed_at: dt.datetime
    server_current_time: dt.datetime | None
    raw_digest: str = Field(pattern=SHA256)
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    credential_reference_digest: str = Field(pattern=SHA256)
    binding_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_binding(self):
        _identifier(self.request_id, "request_id")
        for name in ("requested_at", "retrieved_at", "observed_at", "server_current_time"):
            _utc(getattr(self, name), name)
        if not self.requested_at <= self.retrieved_at <= self.observed_at:
            raise ValueError("observation chronology is invalid")
        _hash(self, "binding_hash")
        return self


class AuthenticEntitlementReference(_Model):
    """Digest-only reference; market mode is deliberately not entitlement proof."""

    provider: Literal["provider.ibkr"]
    account_reference_digest: str = Field(pattern=SHA256)
    entitlement_evidence_digest: str = Field(pattern=SHA256)
    dataset: Literal["PRICES_OHLCV"]
    security_master_id: Literal["security.us.msft.xnas"]
    effective_at: dt.datetime
    expires_at: dt.datetime
    external_state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    entitlement_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_entitlement(self):
        _utc(self.effective_at, "entitlement effective_at")
        _utc(self.expires_at, "entitlement expires_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("entitlement window must be positive")
        _hash(self, "entitlement_hash")
        return self


class ExternalAttestationEnvelope(_Model):
    mode: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    binding_hash: str = Field(pattern=SHA256)
    entitlement_hash: str = Field(pattern=SHA256)
    lifecycle_hash: str = Field(pattern=SHA256)
    actors_hash: str = Field(pattern=SHA256)
    attester_identity_digest: str = Field(pattern=SHA256)
    authority_identity_digest: str = Field(pattern=SHA256)
    issued_at: dt.datetime
    expires_at: dt.datetime
    assertion_digest: str = Field(pattern=SHA256)
    envelope_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_envelope(self):
        _utc(self.issued_at, "issued_at")
        _utc(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("attestation window must be positive")
        _hash(self, "envelope_hash")
        return self


class ExternalAuthenticityAssessment(_Model):
    binding_hash: str = Field(pattern=SHA256)
    envelope_hash: str = Field(pattern=SHA256)
    entitlement_hash: str = Field(pattern=SHA256)
    lifecycle_hash: str = Field(pattern=SHA256)
    actors_hash: str = Field(pattern=SHA256)
    verifier_identity_digest: str = Field(pattern=SHA256)
    verified_at: dt.datetime
    state: Literal[ContractVerificationState.CONTRACT_TEST_VERIFIED]
    real_authenticity: Literal[ProvisioningState.NOT_PROVISIONED]
    real_entitlement: Literal[ProvisioningState.NOT_PROVISIONED]
    real_provider_admission: Literal[ProvisioningState.NOT_PROVISIONED]
    external_custody_worm_legal: Literal[ProvisioningState.NOT_PROVISIONED]
    replay_binding: Literal["CONTENT_IDENTITY_BOUND_NOT_EXTERNAL_CUSTODY"]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]
    assessment_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_assessment(self):
        _utc(self.verified_at, "verified_at")
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError("all ten gates must remain OPEN_EXTERNAL")
        _hash(self, "assessment_hash")
        return self


def bind_ibkr_observation(
    evidence: Any, *, credential_reference_digest: str
) -> ObservationAttestationBinding:
    """Bind the complete PR #35 observation identity without authenticating its origin."""
    failed = False
    try:
        item = _deep(ProbeEvidence, evidence, "IBKR observation")
        if item.source_kind not in {
            SourceKind.CONTRACT_TEST_ONLY,
            SourceKind.LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED,
        }:
            raise ValueError("unsupported observation source")
        request = item.request
        result = _seal(
            ObservationAttestationBinding,
            "binding_hash",
            provider=request.provider,
            adapter=request.adapter,
            dataset="PRICES_OHLCV",
            evidence_hash=item.evidence_hash,
            request_hash=request.request_hash,
            request_id=request.request_id,
            security_master_id=request.instrument.security_master_id,
            permanent_id=request.instrument.permanent_id,
            lineage_digest=request.instrument.lineage_digest,
            market_mode=item.confirmed_market_data_mode,
            requested_at=item.requested_at,
            retrieved_at=item.retrieved_at,
            observed_at=item.observed_at,
            server_current_time=item.server_current_time,
            raw_digest=item.raw_digest,
            material_digest=item.material_digest,
            provenance_digest=item.provenance_digest,
            credential_reference_digest=credential_reference_digest,
        )
    except BaseException:  # noqa: BLE001 - the entire public boundary is hostile
        failed = True
        result = None
    if failed:
        raise ExternalAttestationError("invalid IBKR observation binding")
    return result


def verify_contract_test_attestation(
    *,
    observation: Any,
    binding: Any,
    entitlement: Any,
    lifecycle: Any,
    envelope: Any,
    actors: tuple[Any, ...],
    assertion: bytes,
    verified_at: dt.datetime,
) -> ExternalAuthenticityAssessment:
    """Exercise exact bindings; the result can never represent REAL authenticity."""
    failed = False
    message = "invalid external attestation verification"
    try:
        result = _verify_contract_test_attestation(
            observation=observation,
            binding=binding,
            entitlement=entitlement,
            lifecycle=lifecycle,
            envelope=envelope,
            actors=actors,
            assertion=assertion,
            verified_at=verified_at,
        )
    except BaseException as exc:  # noqa: BLE001 - sanitize the complete public route
        failed = True
        result = None
        if type(exc) is ExternalAttestationError:
            message = str(exc)
    if failed:
        raise ExternalAttestationError(message)
    return result


def _verify_contract_test_attestation(
    *,
    observation: Any,
    binding: Any,
    entitlement: Any,
    lifecycle: Any,
    envelope: Any,
    actors: tuple[Any, ...],
    assertion: bytes,
    verified_at: dt.datetime,
) -> ExternalAuthenticityAssessment:
    source = _deep(ProbeEvidence, observation, "IBKR observation")
    subject = _deep(ObservationAttestationBinding, binding, "observation binding")
    grant = _deep(AuthenticEntitlementReference, entitlement, "entitlement reference")
    trust = _deep(ExternalTrustLifecycle, lifecycle, "trust lifecycle")
    attestation = _deep(ExternalAttestationEnvelope, envelope, "attestation envelope")
    people = tuple(_deep(ActorIdentity, item, "actor identity") for item in actors)
    expected_roles = tuple(ActorRole)
    if tuple(item.role for item in people) != expected_roles or len(
        {x.actor_id for x in people}
    ) != len(people):
        raise ExternalAttestationError("actors must be exact, ordered and independent")
    by_role = {item.role: item for item in people}
    actors_hash = typed_hash([item.model_dump(mode="json", warnings=False) for item in people])
    _utc(verified_at, "verified_at")
    if not isinstance(assertion, bytes) or not assertion:
        raise ExternalAttestationError("external assertion must be non-empty bytes")
    rebuilt = bind_ibkr_observation(
        source, credential_reference_digest=subject.credential_reference_digest
    )
    if rebuilt != subject:
        raise ExternalAttestationError("observation binding mismatch")
    if (grant.provider, grant.dataset, grant.security_master_id) != (
        subject.provider,
        subject.dataset,
        subject.security_master_id,
    ):
        raise ExternalAttestationError("cross-provider, dataset or security entitlement swap")
    if (
        attestation.binding_hash != subject.binding_hash
        or attestation.entitlement_hash != grant.entitlement_hash
    ):
        raise ExternalAttestationError("attestation evidence or entitlement binding mismatch")
    if attestation.lifecycle_hash != trust.lifecycle_hash:
        raise ExternalAttestationError("attestation trust lifecycle binding mismatch")
    if attestation.attester_identity_digest != by_role[ActorRole.ATTESTER].identity_digest:
        raise ExternalAttestationError("attester identity binding mismatch")
    if attestation.authority_identity_digest != by_role[ActorRole.AUTHORITY].identity_digest:
        raise ExternalAttestationError("authority identity binding mismatch")
    if attestation.actors_hash != actors_hash:
        raise ExternalAttestationError("actor set binding mismatch")
    actor_lifecycles = {item.role: item for item in trust.actor_lifecycles}
    for role, actor in by_role.items():
        lifecycle_record = actor_lifecycles[role]
        if lifecycle_record.actor_identity_digest != actor.identity_digest:
            raise ExternalAttestationError(f"{role.value} lifecycle identity mismatch")
        if not lifecycle_record.available_at <= attestation.issued_at < lifecycle_record.expires_at:
            raise ExternalAttestationError(f"{role.value} lifecycle unavailable at issuance")
        if not lifecycle_record.available_at <= verified_at < lifecycle_record.expires_at:
            raise ExternalAttestationError(
                f"{role.value} lifecycle unavailable, expired or future-dated"
            )
        if lifecycle_record.revoked_at is not None and verified_at >= lifecycle_record.revoked_at:
            raise ExternalAttestationError(f"{role.value} lifecycle revoked")
    if hashlib.sha256(assertion).hexdigest() != attestation.assertion_digest:
        raise ExternalAttestationError("external assertion digest mismatch")
    if source.source_kind is not SourceKind.CONTRACT_TEST_ONLY:
        raise ExternalAttestationError("REAL observation verification is NOT_PROVISIONED")
    if not trust.available_at <= attestation.issued_at < trust.expires_at:
        raise ExternalAttestationError("attestation issued outside trust lifecycle")
    if trust.revoked_at is not None and verified_at >= trust.revoked_at:
        raise ExternalAttestationError("trust was revoked at verifier time")
    if not attestation.issued_at <= verified_at < min(attestation.expires_at, trust.expires_at):
        raise ExternalAttestationError("attestation is stale, expired or future-dated")
    if not grant.effective_at <= source.observed_at < grant.expires_at:
        raise ExternalAttestationError("entitlement absent at observation time")
    if attestation.issued_at < source.observed_at:
        raise ExternalAttestationError("attestation predates observation")
    return _seal(
        ExternalAuthenticityAssessment,
        "assessment_hash",
        binding_hash=subject.binding_hash,
        envelope_hash=attestation.envelope_hash,
        entitlement_hash=grant.entitlement_hash,
        lifecycle_hash=trust.lifecycle_hash,
        actors_hash=actors_hash,
        verifier_identity_digest=by_role[ActorRole.VERIFIER].identity_digest,
        verified_at=verified_at,
        state=ContractVerificationState.CONTRACT_TEST_VERIFIED,
        real_authenticity=ProvisioningState.NOT_PROVISIONED,
        real_entitlement=ProvisioningState.NOT_PROVISIONED,
        real_provider_admission=ProvisioningState.NOT_PROVISIONED,
        external_custody_worm_legal=ProvisioningState.NOT_PROVISIONED,
        replay_binding="CONTENT_IDENTITY_BOUND_NOT_EXTERNAL_CUSTODY",
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
        real_route="QVM_NOT_READY",
        global_readiness="INSUFFICIENT_REAL_DATA",
        trade_decision="NO_TRADE",
        signals_generated=False,
        live_execution_enabled=False,
        backtesting="NOT_AUTHORIZED",
    )


def verify_real_external_attestation(*args: Any, **kwargs: Any) -> None:
    """No injectable local object can activate REAL verification."""
    del args, kwargs
    raise ExternalAttestationError("REAL external attester/trust backend is NOT_PROVISIONED")


T = TypeVar("T", bound=BaseModel)


def seal_contract_test(expected: type[T], hash_field: str, **values: Any) -> T:
    """Build only CONTRACT_TEST_ONLY values; this is not an external signer."""
    failed = False
    try:
        if _SEAL_FIELDS.get(expected) != hash_field:
            raise TypeError("unsupported contract-test model or hash field")
        result = _seal(expected, hash_field, **values)
    except BaseException:  # noqa: BLE001 - caller-controlled hooks and values are hostile
        failed = True
        result = None
    if failed:
        raise ExternalAttestationError("invalid contract-test external attestation value")
    return result


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    failed = False
    try:
        raw = expected.model_construct(**values, **{hash_field: "0" * 64})
        payload = raw.model_dump(mode="json", exclude={hash_field}, warnings=False)
        sealed = dict(values)
        sealed[hash_field] = typed_hash(payload)
        result = expected(**sealed)
    except BaseException:  # noqa: BLE001 - serializers/properties may be hostile
        failed = True
        result = None
    if failed:
        raise ExternalAttestationError("invalid external attestation value")
    return result


def _deep(expected: type[T], value: Any, label: str) -> T:
    failed = False
    try:
        if isinstance(value, BaseModel):
            if set(value.__dict__) - set(type(value).model_fields):
                raise ValueError("undeclared fields")
            value = value.model_dump(mode="json", warnings=False)
        elif isinstance(value, str):
            value = json.loads(value)
        elif not isinstance(value, dict):
            raise TypeError("unsupported input")
        primitive = json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
        result = expected.model_validate(primitive)
    except BaseException:  # noqa: BLE001 - hostile hooks may retain secret-bearing values
        failed = True
        result = None
    if failed:
        raise ExternalAttestationError(f"invalid {label}")
    return result


def _identifier(value: str, label: str) -> None:
    if (
        not value.isascii()
        or value != value.casefold()
        or value != unicodedata.normalize("NFKC", value)
    ):
        raise ValueError(f"{label} must be canonical lowercase ASCII")


def _utc(value: dt.datetime | None, label: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() != dt.timedelta(0)):
        raise ValueError(f"{label} must be canonical UTC")


def _hash(value: BaseModel, field: str) -> None:
    if getattr(value, field) != typed_hash(
        value.model_dump(mode="json", exclude={field}, warnings=False)
    ):
        raise ValueError(f"{field} mismatch")


_SEAL_FIELDS: dict[type[BaseModel], str] = {
    ActorIdentity: "identity_digest",
    ActorLifecycle: "lifecycle_hash",
    ExternalTrustLifecycle: "lifecycle_hash",
    ObservationAttestationBinding: "binding_hash",
    AuthenticEntitlementReference: "entitlement_hash",
    ExternalAttestationEnvelope: "envelope_hash",
    ExternalAuthenticityAssessment: "assessment_hash",
}
