"""IBKR provisioning contracts; every REAL dependency remains fail-closed."""

from __future__ import annotations

import datetime as dt
import hashlib
from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.ibkr_observation import (
    DatasetClass,
    EvidenceState,
    MarketDataMode,
    ObservationBatch,
    ObservationError,
    ProviderId,
    ProvisioningState,
    assert_payload,
    validate_observation_batch,
)
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "ibkr-provisioned-observation-evidence-v1"
SHA256 = r"^[0-9a-f]{64}$"
OID = r"^[a-z0-9][a-z0-9._:-]{2,127}$"
PROFILE_DIGEST = hashlib.sha256(b"ibkr-private-gateway-profile-contract-v1").hexdigest()
ACCOUNT_DIGEST = hashlib.sha256(b"ibkr-account-reference-contract-v1").hexdigest()
ENTITLEMENT_SOURCE_DIGEST = hashlib.sha256(b"contract-only-entitlement-evidence").hexdigest()
ACTOR_IDS = (
    "actor.ibkr.provisioning-maker",
    "actor.ibkr.independent-checker",
    "actor.ibkr.runtime-operator",
    "actor.ibkr.revocation-owner",
)


class IBKRProvisioningError(ValueError):
    """The provisioning/evidence boundary rejected an untrusted value."""


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArchitectureDecision(StrEnum):
    SECURE_EXTERNAL_CREDENTIAL_HANDLING_DEFINED = (
        "SECURE_EXTERNAL_CREDENTIAL_HANDLING_DEFINED"
    )
    APPROVED_CONNECTIVITY_DEFINED = "APPROVED_CONNECTIVITY_DEFINED"
    LICENSING_DEFINED = "LICENSING_DEFINED"
    OPERATIONAL_OWNERSHIP_DEFINED = "OPERATIONAL_OWNERSHIP_DEFINED"
    REAL_CAPTURE_EVIDENCE_DEFINED = "REAL_CAPTURE_EVIDENCE_DEFINED"


class ConnectionState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIGURED_REFERENCE_ONLY = "CONFIGURED_REFERENCE_ONLY"
    CONNECTING = "CONNECTING"
    OBSERVING_READ_ONLY = "OBSERVING_READ_ONLY"


class ActorRole(StrEnum):
    PROVISIONING_MAKER = "PROVISIONING_MAKER"
    INDEPENDENT_CHECKER = "INDEPENDENT_CHECKER"
    RUNTIME_OPERATOR = "RUNTIME_OPERATOR"
    REVOCATION_OWNER = "REVOCATION_OWNER"


class UseClass(StrEnum):
    CONTRACT_VALIDATION = "CONTRACT_VALIDATION"


class DisplayClassification(StrEnum):
    NON_DISPLAY_DECLARATION_ONLY = "NON_DISPLAY_DECLARATION_ONLY"


class SecretResolver(Protocol):
    """Runtime injection seam. Implementations and returned secrets stay outside domain models."""

    def resolve(self, reference_digest: str) -> bytes: ...


T = TypeVar("T", bound=BaseModel)


def _dump(value: BaseModel, hash_field: str) -> dict[str, Any]:
    return value.model_dump(mode="json", exclude={hash_field}, warnings=False)


def _check_hash(value: BaseModel, hash_field: str) -> None:
    if typed_hash(_dump(value, hash_field)) != getattr(value, hash_field):
        raise ValueError(f"{hash_field} does not match canonical payload")


def _seal(model: type[T], hash_field: str, **values: Any) -> T:
    raw = model.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(_dump(raw, hash_field))
    return model(**values)


def _revalidate(model: type[T], value: Any, label: str) -> T:
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise IBKRProvisioningError(f"{label} contains undeclared fields")
        value = value.model_dump(mode="python", warnings=False)
    try:
        if isinstance(value, str):
            return model.model_validate_json(value)
        return model.model_validate(value)
    except Exception as exc:
        raise IBKRProvisioningError(f"invalid {label}") from exc


def _utc(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{label} must be canonical UTC")


class ArchitectureDecisionRecord(ContractModel):
    version: Literal["ibkr-architecture-decisions-v1"] = "ibkr-architecture-decisions-v1"
    decisions: tuple[ArchitectureDecision, ...]
    contract_level: Literal["DEFINED"] = "DEFINED"
    real_provisioning: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    activation_real: Literal[False] = False
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_record(self):
        if self.decisions != tuple(ArchitectureDecision):
            raise ValueError("all five architecture decisions must be defined in canonical order")
        _check_hash(self, "decision_hash")
        return self


class GovernedCredentialReference(ContractModel):
    version: Literal["ibkr-external-credential-reference-v1"] = (
        "ibkr-external-credential-reference-v1"
    )
    provider: Literal[ProviderId.IBKR] = ProviderId.IBKR
    reference_digest: str = Field(pattern=SHA256)
    backend_evidence_digest: None = None
    state: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    effective_at: dt.datetime
    revoked_at: dt.datetime | None = None
    rotation: Literal[1] = 1
    reference_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_reference(self):
        _utc(self.effective_at, "credential effective_at")
        if self.revoked_at is not None:
            _utc(self.revoked_at, "credential revoked_at")
            if self.revoked_at <= self.effective_at:
                raise ValueError("credential revocation must follow effectiveness")
        _check_hash(self, "reference_hash")
        return self


class ConnectionProfileReference(ContractModel):
    version: Literal["ibkr-private-gateway-profile-v1"] = "ibkr-private-gateway-profile-v1"
    provider: Literal[ProviderId.IBKR] = ProviderId.IBKR
    boundary: Literal["IBKR_GATEWAY_TWS_API_PRIVATE_CONTROLLED"] = (
        "IBKR_GATEWAY_TWS_API_PRIVATE_CONTROLLED"
    )
    profile_digest: Literal[PROFILE_DIGEST] = PROFILE_DIGEST
    account_reference_digest: Literal[ACCOUNT_DIGEST] = ACCOUNT_DIGEST
    network_exposure: Literal["NO_INBOUND_PUBLIC_EXPOSURE"] = "NO_INBOUND_PUBLIC_EXPOSURE"
    capability: Literal["MARKET_OBSERVATION_READ_ONLY"] = "MARKET_OBSERVATION_READ_ONLY"
    preferred_session: Literal["DEDICATED_GATEWAY_FUTURE"] = "DEDICATED_GATEWAY_FUTURE"
    state: Literal[ConnectionState.CONFIGURED_REFERENCE_ONLY] = (
        ConnectionState.CONFIGURED_REFERENCE_ONLY
    )
    profile_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_profile(self):
        _check_hash(self, "profile_hash")
        return self


class ConnectionTransition(ContractModel):
    from_state: ConnectionState
    to_state: ConnectionState
    transition_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_transition(self):
        allowed = {
            (ConnectionState.NOT_CONFIGURED, ConnectionState.CONFIGURED_REFERENCE_ONLY),
            (ConnectionState.CONFIGURED_REFERENCE_ONLY, ConnectionState.CONNECTING),
            (ConnectionState.CONNECTING, ConnectionState.OBSERVING_READ_ONLY),
            (ConnectionState.CONNECTING, ConnectionState.CONFIGURED_REFERENCE_ONLY),
            (ConnectionState.OBSERVING_READ_ONLY, ConnectionState.CONFIGURED_REFERENCE_ONLY),
        }
        if (self.from_state, self.to_state) not in allowed:
            raise ValueError("connection transition is not in the read-only state machine")
        _check_hash(self, "transition_hash")
        return self


class MarketDataEntitlementEvidence(ContractModel):
    version: Literal["ibkr-market-data-entitlement-v1"] = "ibkr-market-data-entitlement-v1"
    provider: Literal[ProviderId.IBKR] = ProviderId.IBKR
    account_reference_digest: Literal[ACCOUNT_DIGEST] = ACCOUNT_DIGEST
    dataset: Literal[DatasetClass.PRICES_OHLCV] = DatasetClass.PRICES_OHLCV
    feed_id: Literal["ibkr.historical-bars.contract"] = "ibkr.historical-bars.contract"
    market_data_mode: Literal[MarketDataMode.DELAYED] = MarketDataMode.DELAYED
    use_class: Literal[UseClass.CONTRACT_VALIDATION] = UseClass.CONTRACT_VALIDATION
    display_classification: Literal[DisplayClassification.NON_DISPLAY_DECLARATION_ONLY] = (
        DisplayClassification.NON_DISPLAY_DECLARATION_ONLY
    )
    storage_permission: Literal["DECLARED_ONLY_NOT_EXTERNALLY_VERIFIED"] = (
        "DECLARED_ONLY_NOT_EXTERNALLY_VERIFIED"
    )
    derived_artifact_permission: Literal["DECLARED_ONLY_NOT_EXTERNALLY_VERIFIED"] = (
        "DECLARED_ONLY_NOT_EXTERNALLY_VERIFIED"
    )
    retention_terms_id: Literal["retention.not-externally-verified"] = (
        "retention.not-externally-verified"
    )
    effective_at: dt.datetime
    expires_at: dt.datetime
    source_evidence_digest: Literal[ENTITLEMENT_SOURCE_DIGEST] = ENTITLEMENT_SOURCE_DIGEST
    external_evidence_state: Literal[ProvisioningState.NOT_PROVISIONED] = (
        ProvisioningState.NOT_PROVISIONED
    )
    policy_version: Literal["ibkr-entitlement-policy-v1"] = "ibkr-entitlement-policy-v1"
    entitlement_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_entitlement(self):
        _utc(self.effective_at, "entitlement effective_at")
        _utc(self.expires_at, "entitlement expires_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("entitlement window must be positive")
        _check_hash(self, "entitlement_hash")
        return self


class ActorRecord(ContractModel):
    actor_id: str = Field(pattern=OID)
    role: ActorRole
    effective_at: dt.datetime
    revoked_at: dt.datetime | None = None
    record_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_actor(self):
        _utc(self.effective_at, "actor effective_at")
        if self.revoked_at is not None:
            _utc(self.revoked_at, "actor revoked_at")
            if self.revoked_at <= self.effective_at:
                raise ValueError("actor revocation must follow effectiveness")
        _check_hash(self, "record_hash")
        return self


class ActorRegistry(ContractModel):
    actors: tuple[ActorRecord, ...]
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY] = ProvisioningState.CONTRACT_TEST_ONLY
    real_registry: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_registry(self):
        actors = tuple(_revalidate(ActorRecord, item, "actor") for item in self.actors)
        expected = tuple(zip(ACTOR_IDS, tuple(ActorRole), strict=True))
        if tuple((item.actor_id, item.role) for item in actors) != expected:
            raise ValueError("actor registry does not match the code-owned role binding")
        _check_hash(self, "registry_hash")
        return self


class ProvisioningApproval(ContractModel):
    maker_id: str = Field(pattern=OID)
    checker_id: str = Field(pattern=OID)
    operator_id: str = Field(pattern=OID)
    revocation_owner_id: str = Field(pattern=OID)
    credential_reference_hash: str = Field(pattern=SHA256)
    connection_profile_hash: str = Field(pattern=SHA256)
    entitlement_hash: str = Field(pattern=SHA256)
    approved_at: dt.datetime
    approval_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_approval(self):
        _utc(self.approved_at, "approved_at")
        if self.maker_id == self.checker_id:
            raise ValueError("maker and checker must be independent")
        if (
            self.maker_id,
            self.checker_id,
            self.operator_id,
            self.revocation_owner_id,
        ) != ACTOR_IDS:
            raise ValueError("approval actors do not match the governed registry")
        _check_hash(self, "approval_hash")
        return self


class SanitizedTransportMetadata(ContractModel):
    protocol: Literal["IBKR_GATEWAY_TWS_API"] = "IBKR_GATEWAY_TWS_API"
    status: Literal["CONTRACT_FIXTURE_SUCCESS"] = "CONTRACT_FIXTURE_SUCCESS"
    error_code: None = None
    public_inbound_exposure: Literal[False] = False
    metadata_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_metadata(self):
        _check_hash(self, "metadata_hash")
        return self


class RawPayloadBinding(ContractModel):
    page_index: int = Field(ge=0)
    payload_digest: str = Field(pattern=SHA256)
    payload_size: int = Field(gt=0)
    binding_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_binding(self):
        _check_hash(self, "binding_hash")
        return self


class IBKRRealCaptureEvidence(ContractModel):
    """Shape required for REAL capture; instances remain contract-only and untrusted."""

    contract_version: Literal["ibkr-provisioned-observation-evidence-v1"] = CONTRACT_VERSION
    observation: ObservationBatch
    raw_payloads: tuple[RawPayloadBinding, ...]
    availability_at: dt.datetime
    connection_profile: ConnectionProfileReference
    credential_reference: GovernedCredentialReference
    entitlement: MarketDataEntitlementEvidence
    actor_registry: ActorRegistry
    approval: ProvisioningApproval
    transport: SanitizedTransportMetadata
    durable_local_persistence_receipt: None = None
    persistence_guarantee: Literal["NOT_INTEGRATED_WITH_PHASE29_IDENTITY"] = (
        "NOT_INTEGRATED_WITH_PHASE29_IDENTITY"
    )
    evidence_state: Literal[EvidenceState.OBSERVED_UNTRUSTED] = EvidenceState.OBSERVED_UNTRUSTED
    provider_admission: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    authority: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    independent_verifier: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    external_custody_worm_legal: Literal[ProvisioningState.NOT_PROVISIONED] = (
        ProvisioningState.NOT_PROVISIONED
    )
    capture_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_capture(self):
        observation = validate_observation_batch(self.observation)
        profile = _revalidate(ConnectionProfileReference, self.connection_profile, "connection profile")
        credential = _revalidate(
            GovernedCredentialReference, self.credential_reference, "credential reference"
        )
        entitlement = _revalidate(MarketDataEntitlementEvidence, self.entitlement, "entitlement")
        registry = _revalidate(ActorRegistry, self.actor_registry, "actor registry")
        approval = _revalidate(ProvisioningApproval, self.approval, "approval")
        _revalidate(SanitizedTransportMetadata, self.transport, "transport metadata")
        payloads = tuple(_revalidate(RawPayloadBinding, item, "raw payload") for item in self.raw_payloads)
        _utc(self.availability_at, "availability_at")
        envelope = observation.envelopes[0]
        expected_payloads = tuple(
            (item.response.page.page_index, item.payload_digest, item.payload_size)
            for item in observation.envelopes
        )
        if tuple((item.page_index, item.payload_digest, item.payload_size) for item in payloads) != expected_payloads:
            raise ValueError("capture payload bindings differ from adapter envelopes")
        if self.availability_at < envelope.market_event_at or self.availability_at > envelope.retrieved_at:
            raise ValueError("availability timestamp violates observation chronology")
        if entitlement.market_data_mode is not envelope.response.market_data_mode:
            raise ValueError("entitlement mode differs from observed mode")
        if entitlement.dataset is not envelope.request.dataset:
            raise ValueError("entitlement dataset differs from observed dataset")
        if profile.provider is not envelope.request.provider or entitlement.provider is not profile.provider:
            raise ValueError("provider binding mismatch")
        if entitlement.account_reference_digest != profile.account_reference_digest:
            raise ValueError("cross-account entitlement/profile binding mismatch")
        if credential.reference_digest != envelope.request.credential.reference_digest:
            raise ValueError("credential reference differs from adapter request")
        if credential.revoked_at is not None and self.availability_at >= credential.revoked_at:
            raise ValueError("credential reference was revoked before capture")
        if not (credential.effective_at <= self.availability_at):
            raise ValueError("credential reference was not effective for capture")
        if not (entitlement.effective_at <= self.availability_at < entitlement.expires_at):
            raise ValueError("entitlement is absent or expired for capture")
        actors = {item.actor_id: item for item in registry.actors}
        for actor_id in (
            approval.maker_id,
            approval.checker_id,
            approval.operator_id,
            approval.revocation_owner_id,
        ):
            actor = actors.get(actor_id)
            if actor is None or actor.effective_at > approval.approved_at:
                raise ValueError("approval actor is not active")
            if actor.revoked_at is not None and actor.revoked_at <= self.availability_at:
                raise ValueError("approval actor was revoked before capture")
        if approval.approved_at > self.availability_at:
            raise ValueError("capture predates provisioning approval")
        if approval.credential_reference_hash != credential.reference_hash:
            raise ValueError("approval credential binding mismatch")
        if approval.connection_profile_hash != profile.profile_hash:
            raise ValueError("approval profile binding mismatch")
        if approval.entitlement_hash != entitlement.entitlement_hash:
            raise ValueError("approval entitlement binding mismatch")
        _check_hash(self, "capture_hash")
        return self


class ReadinessAssessment(ContractModel):
    decisions: tuple[tuple[ArchitectureDecision, Literal["DEFINED"]], ...]
    missing_real_prerequisites: tuple[str, ...]
    ibkr_real: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    activation_real: Literal[False] = False
    operating_mode_real: Literal[False] = False
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    signals_generated: Literal[False] = False
    live_execution_enabled: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    assessment_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_assessment(self):
        if self.decisions != tuple((item, "DEFINED") for item in ArchitectureDecision):
            raise ValueError("readiness must record all five defined decisions")
        if self.missing_real_prerequisites != MISSING_REAL_PREREQUISITES:
            raise ValueError("readiness prerequisites must remain complete and canonical")
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError("all ten evidence gates must remain OPEN_EXTERNAL")
        _check_hash(self, "assessment_hash")
        return self


MISSING_REAL_PREREQUISITES = (
    "EXTERNAL_SECRET_BACKEND_AND_ACTUAL_CREDENTIAL",
    "ACTUAL_IBKR_GATEWAY_TWS_SESSION",
    "AUTHENTIC_MARKET_DATA_ENTITLEMENT_EVIDENCE",
    "EXTERNALLY_PROVISIONED_ACTOR_REGISTRY",
    "REAL_TRUST_ROOT",
    "REAL_AUTHORITY",
    "REAL_INDEPENDENT_VERIFIER",
    "EXTERNAL_CUSTODY_WORM_LEGAL_APPROVAL",
    "REAL_PROVIDER_ADMISSION",
)


ARCHITECTURE_DECISIONS = _seal(
    ArchitectureDecisionRecord,
    "decision_hash",
    decisions=tuple(ArchitectureDecision),
)


def build_contract_test_capture(
    observation: Any, *, raw_payload: bytes, captured_at: dt.datetime
) -> IBKRRealCaptureEvidence:
    """Exercise the REAL evidence shape without claiming any REAL provisioning."""
    batch = validate_observation_batch(observation)
    if len(batch.envelopes) != 1:
        raise IBKRProvisioningError("contract capture requires the single-page fixture")
    envelope = batch.envelopes[0]
    assert_payload(envelope, raw_payload)
    _utc(captured_at, "captured_at")
    profile = _seal(ConnectionProfileReference, "profile_hash")
    credential = _seal(
        GovernedCredentialReference,
        "reference_hash",
        reference_digest=envelope.request.credential.reference_digest,
        effective_at=envelope.market_event_at,
        rotation=1,
    )
    entitlement = _seal(
        MarketDataEntitlementEvidence,
        "entitlement_hash",
        effective_at=envelope.market_event_at,
        expires_at=captured_at + dt.timedelta(days=1),
    )
    actors = tuple(
        _seal(
            ActorRecord,
            "record_hash",
            actor_id=actor_id,
            role=role,
            effective_at=envelope.market_event_at,
        )
        for actor_id, role in zip(ACTOR_IDS, tuple(ActorRole), strict=True)
    )
    registry = _seal(ActorRegistry, "registry_hash", actors=actors)
    approval = _seal(
        ProvisioningApproval,
        "approval_hash",
        maker_id=ACTOR_IDS[0],
        checker_id=ACTOR_IDS[1],
        operator_id=ACTOR_IDS[2],
        revocation_owner_id=ACTOR_IDS[3],
        credential_reference_hash=credential.reference_hash,
        connection_profile_hash=profile.profile_hash,
        entitlement_hash=entitlement.entitlement_hash,
        approved_at=envelope.market_event_at,
    )
    transport = _seal(SanitizedTransportMetadata, "metadata_hash")
    return _seal(
        IBKRRealCaptureEvidence,
        "capture_hash",
        observation=batch,
        raw_payloads=(
            _seal(
                RawPayloadBinding,
                "binding_hash",
                page_index=envelope.response.page.page_index,
                payload_digest=hashlib.sha256(raw_payload).hexdigest(),
                payload_size=len(raw_payload),
            ),
        ),
        availability_at=captured_at,
        connection_profile=profile,
        credential_reference=credential,
        entitlement=entitlement,
        actor_registry=registry,
        approval=approval,
        transport=transport,
    )


def validate_capture(
    value: Any, *, raw_payload: bytes | tuple[bytes, ...]
) -> IBKRRealCaptureEvidence:
    canonical = _revalidate(IBKRRealCaptureEvidence, value, "IBKR capture evidence")
    payloads = (raw_payload,) if isinstance(raw_payload, bytes) else raw_payload
    if len(payloads) != len(canonical.observation.envelopes):
        raise IBKRProvisioningError("capture payload count does not match observation")
    try:
        for envelope, payload in zip(canonical.observation.envelopes, payloads, strict=True):
            assert_payload(envelope, payload)
    except ObservationError as exc:
        raise IBKRProvisioningError("capture payload does not match observation") from exc
    return canonical


def readiness_assessment() -> ReadinessAssessment:
    return _seal(
        ReadinessAssessment,
        "assessment_hash",
        decisions=tuple((item, "DEFINED") for item in ArchitectureDecision),
        missing_real_prerequisites=MISSING_REAL_PREREQUISITES,
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    )


def evaluate_real_route(*, secret_resolver: SecretResolver | None = None) -> None:
    """No resolver, fixture, or caller input can provision REAL in this foundation."""
    del secret_resolver
    raise IBKRProvisioningError("IBKR REAL observation is NOT_PROVISIONED")
