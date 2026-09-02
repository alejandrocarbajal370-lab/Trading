"""External provider interface foundation; no REAL provider or trust is provisioned."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import threading
import weakref
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "external-provider-interface-foundation-v1"
SHA256 = r"^[0-9a-f]{64}$"


class FoundationError(ValueError):
    """A sensitive boundary rejected non-canonical or unprovisioned input."""


class EvidenceState(StrEnum):
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    TRUSTED = "TRUSTED"
    CLOSED = "CLOSED"


class ProvisioningState(StrEnum):
    NOT_PROVISIONED = "NOT_PROVISIONED"
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


class AttestationState(StrEnum):
    NOT_PROVISIONED = "NOT_PROVISIONED"
    UNVERIFIED = "UNVERIFIED"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderId(StrEnum):
    CONTRACT_REGISTRY = "provider.contract_registry"


class DatasetId(StrEnum):
    HISTORICAL_PIT_SECURITY_MASTER = "dataset.historical_pit_security_master"
    LICENSING_LEGAL = "dataset.licensing_legal"
    HISTORICAL_COMPLETENESS = "dataset.historical_completeness"
    RETENTION_WORM = "dataset.retention_worm"
    OPERATIONS_MONITORING = "dataset.operations_monitoring"
    REAL_FX = "dataset.real_fx"
    SHARES_OUTSTANDING_PIT = "dataset.shares_outstanding_pit"
    RESTATEMENT_MATERIALITY = "dataset.restatement_materiality"
    CORPORATE_ACTION_ECONOMICS = "dataset.corporate_action_economics"
    SCALE_OPERATIONAL_VALIDATION = "dataset.scale_operational_validation"


class AdapterId(StrEnum):
    CONTRACT_FIXTURE = "adapter.contract_fixture"


_DATASET_BY_GATE = dict(zip(EvidenceGate, DatasetId, strict=True))


class CanonicalRoute(ContractModel):
    gate: EvidenceGate
    provider: ProviderId
    dataset: DatasetId
    adapter: AdapterId
    registry_version: Literal["provider-interface-registry-v1"] = "provider-interface-registry-v1"
    route_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_route(self):
        if self.provider is not ProviderId.CONTRACT_REGISTRY:
            raise ValueError("provider is not registry-governed")
        if self.adapter is not AdapterId.CONTRACT_FIXTURE or self.dataset is not _DATASET_BY_GATE[self.gate]:
            raise ValueError("route does not match canonical gate registry")
        _check_hash(self, "route_hash")
        return self


class ProviderRegistry:
    """Code-owned resolution; callers select a gate, never truth-bearing strings."""

    @staticmethod
    def resolve(gate: EvidenceGate) -> CanonicalRoute:
        if type(gate) is not EvidenceGate:
            raise FoundationError("gate must be a canonical EvidenceGate")
        return _seal(
            CanonicalRoute,
            "route_hash",
            gate=gate,
            provider=ProviderId.CONTRACT_REGISTRY,
            dataset=_DATASET_BY_GATE[gate],
            adapter=AdapterId.CONTRACT_FIXTURE,
        )


class MaterialObservation(ContractModel):
    route: CanonicalRoute
    state: Literal[EvidenceState.OBSERVED] = EvidenceState.OBSERVED
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    observed_at: dt.datetime
    observation_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_observation(self):
        _aware(self.observed_at, "observed_at")
        _revalidate(CanonicalRoute, self.route, "route")
        _check_hash(self, "observation_hash")
        return self


class AttestationResult(ContractModel):
    state: Literal[AttestationState.NOT_PROVISIONED, AttestationState.UNVERIFIED]
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    detail: Literal["SIGNATURE_VERIFICATION_UNAVAILABLE"] = "SIGNATURE_VERIFICATION_UNAVAILABLE"


class EvidenceHandoff(ContractModel):
    route: CanonicalRoute
    observation_hash: str = Field(pattern=SHA256)
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    observed_at: dt.datetime
    handed_off_at: dt.datetime
    evidence_state: Literal[EvidenceState.OBSERVED] = EvidenceState.OBSERVED
    attestation: AttestationResult
    handoff_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_handoff(self):
        route = _revalidate(CanonicalRoute, self.route, "route")
        attestation = _revalidate(AttestationResult, self.attestation, "attestation")
        _aware(self.observed_at, "observed_at")
        _aware(self.handed_off_at, "handed_off_at")
        if self.handed_off_at < self.observed_at:
            raise ValueError("handoff cannot precede observation")
        if route.gate not in EvidenceGate or attestation.state not in AttestationState:
            raise ValueError("non-canonical handoff")
        expected_observation = _seal(
            MaterialObservation,
            "observation_hash",
            route=route,
            material_digest=self.material_digest,
            provenance_digest=self.provenance_digest,
            observed_at=self.observed_at,
        )
        if self.observation_hash != expected_observation.observation_hash:
            raise ValueError("observation_hash does not bind handoff material and provenance")
        _check_hash(self, "handoff_hash")
        return self


class FoundationResult(ContractModel):
    contract_version: Literal["external-provider-interface-foundation-v1"] = CONTRACT_VERSION
    handoffs: tuple[EvidenceHandoff, ...]
    evidence_states: tuple[Literal[EvidenceState.OBSERVED], ...]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    durable_replay: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    independent_verifier: Literal[ProvisioningState.NOT_PROVISIONED] = ProvisioningState.NOT_PROVISIONED
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    result_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_result(self):
        handoffs = tuple(_revalidate(EvidenceHandoff, item, "handoff") for item in self.handoffs)
        if tuple(item.route.gate for item in handoffs) != tuple(EvidenceGate):
            raise ValueError("handoffs must cover all canonical gates in order")
        if self.evidence_states != (EvidenceState.OBSERVED,) * len(EvidenceGate):
            raise ValueError("foundation cannot promote observed evidence")
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError("all gates must remain OPEN_EXTERNAL")
        _check_hash(self, "result_hash")
        return self


@runtime_checkable
class ProviderAdapter(Protocol):
    @property
    def provisioning_state(self) -> ProvisioningState: ...

    def fetch(self, route: CanonicalRoute) -> tuple[bytes, bytes]: ...


class AttestationVerifier(ABC):
    @property
    @abstractmethod
    def provisioning_state(self) -> ProvisioningState: ...

    @abstractmethod
    def verify(self, observation: MaterialObservation) -> AttestationResult: ...


class DurableReplayPort(ABC):
    @property
    @abstractmethod
    def provisioning_state(self) -> ProvisioningState: ...

    @abstractmethod
    def consume(self, replay_identities: tuple[str, ...]) -> None: ...


class IndependentVerifierPort(ABC):
    @property
    @abstractmethod
    def provisioning_state(self) -> ProvisioningState: ...

    @abstractmethod
    def handoff(self, observation: MaterialObservation, at: dt.datetime) -> EvidenceHandoff: ...


class NotProvisionedAttestationVerifier(AttestationVerifier):
    provisioning_state = ProvisioningState.NOT_PROVISIONED

    def verify(self, observation: MaterialObservation) -> AttestationResult:
        _revalidate(MaterialObservation, observation, "observation")
        return AttestationResult(state=AttestationState.NOT_PROVISIONED)


class NotProvisionedDurableReplay(DurableReplayPort):
    provisioning_state = ProvisioningState.NOT_PROVISIONED

    def consume(self, replay_identities: tuple[str, ...]) -> None:
        raise FoundationError("REAL durable replay is NOT_PROVISIONED")


class NotProvisionedIndependentVerifier(IndependentVerifierPort):
    provisioning_state = ProvisioningState.NOT_PROVISIONED

    def handoff(self, observation: MaterialObservation, at: dt.datetime) -> EvidenceHandoff:
        raise FoundationError("independent verifier is NOT_PROVISIONED")


class ContractTestAdapter:
    provisioning_state = ProvisioningState.CONTRACT_TEST_ONLY

    def fetch(self, route: CanonicalRoute) -> tuple[bytes, bytes]:
        canonical = _revalidate(CanonicalRoute, route, "route")
        material = f"fixture:{canonical.gate.value}".encode()
        provenance = f"contract-test:{canonical.route_hash}".encode()
        return material, provenance


class _ContractTestReplay(DurableReplayPort):
    provisioning_state = ProvisioningState.CONTRACT_TEST_ONLY

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def consume(self, replay_identities: tuple[str, ...]) -> None:
        if len(replay_identities) != len(set(replay_identities)):
            raise FoundationError("duplicate evidence within batch")
        with self._lock:
            if any(identity in self._seen for identity in replay_identities):
                raise FoundationError("evidence replayed within verifier lifecycle")
            self._seen.update(replay_identities)


class _ContractTestIndependentVerifier(IndependentVerifierPort):
    provisioning_state = ProvisioningState.CONTRACT_TEST_ONLY

    def __init__(self, attestation: AttestationVerifier) -> None:
        self._attestation = attestation

    def handoff(self, observation: MaterialObservation, at: dt.datetime) -> EvidenceHandoff:
        observed = _revalidate(MaterialObservation, observation, "observation")
        result = self._attestation.verify(observed)
        return _seal(
            EvidenceHandoff,
            "handoff_hash",
            route=observed.route,
            observation_hash=observed.observation_hash,
            material_digest=observed.material_digest,
            provenance_digest=observed.provenance_digest,
            observed_at=observed.observed_at,
            handed_off_at=at,
            attestation=result,
        )


_FACTORY_TOKEN = object()
_CONTEXTS: weakref.WeakKeyDictionary[ContractTestContext, tuple[_ContractTestReplay, _ContractTestIndependentVerifier]] = weakref.WeakKeyDictionary()
_CONTEXT_LOCK = threading.Lock()


class ContractTestContext:
    """Explicit isolated fake lifecycle; cannot enter the sealed REAL route."""

    __slots__ = ("__weakref__", "_nonce")

    def __init__(self, token: object) -> None:
        if token is not _FACTORY_TOKEN:
            raise FoundationError("context must be factory-created")
        self._nonce = secrets.token_hex(32)
        pair = (_ContractTestReplay(), _ContractTestIndependentVerifier(NotProvisionedAttestationVerifier()))
        with _CONTEXT_LOCK:
            _CONTEXTS[self] = pair

    def evaluate(self, *, adapter: ProviderAdapter, observed_at: dt.datetime, handed_off_at: dt.datetime) -> FoundationResult:
        if type(adapter) is not ContractTestAdapter:
            raise FoundationError("only the isolated contract-test adapter is allowed")
        replay, verifier = _context_components(self)
        handoffs = []
        replay_ids = []
        for gate in EvidenceGate:
            route = ProviderRegistry.resolve(gate)
            material, provenance = adapter.fetch(route)
            observation = observe_material(route, material, provenance, observed_at)
            handoffs.append(verifier.handoff(observation, handed_off_at))
            replay_ids.append(typed_hash({"contract": CONTRACT_VERSION, "route": route.route_hash, "material": observation.material_digest, "provenance": observation.provenance_digest}))
        replay.consume(tuple(replay_ids))
        return _seal(
            FoundationResult,
            "result_hash",
            handoffs=tuple(handoffs),
            evidence_states=(EvidenceState.OBSERVED,) * len(EvidenceGate),
            gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
        )


def build_contract_test_context() -> ContractTestContext:
    return ContractTestContext(_FACTORY_TOKEN)


def _context_components(context: Any) -> tuple[_ContractTestReplay, _ContractTestIndependentVerifier]:
    if type(context) is not ContractTestContext:
        raise FoundationError("valid contract-test lifecycle required")
    with _CONTEXT_LOCK:
        pair = _CONTEXTS.get(context)
    if pair is None or type(pair[0]) is not _ContractTestReplay or type(pair[1]) is not _ContractTestIndependentVerifier:
        raise FoundationError("valid contract-test lifecycle required")
    return pair


def observe_material(route: Any, material: bytes, provenance: bytes, observed_at: dt.datetime) -> MaterialObservation:
    canonical = _revalidate(CanonicalRoute, route, "route")
    if not isinstance(material, bytes) or not material or not isinstance(provenance, bytes) or not provenance:
        raise FoundationError("material and provenance must be non-empty bytes")
    return _seal(
        MaterialObservation,
        "observation_hash",
        route=canonical,
        material_digest=hashlib.sha256(material).hexdigest(),
        provenance_digest=hashlib.sha256(provenance).hexdigest(),
        observed_at=observed_at,
    )


def evaluate_real_foundation(*, adapter: Any, replay: Any, verifier: Any) -> None:
    """Sealed REAL boundary: interfaces exist, but every component must remain absent."""
    if adapter is not None or type(replay) is not NotProvisionedDurableReplay or type(verifier) is not NotProvisionedIndependentVerifier:
        raise FoundationError("REAL components cannot be substituted before provisioning")
    raise FoundationError("REAL provider route is NOT_PROVISIONED")


def validate_foundation_result(value: Any) -> FoundationResult:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise FoundationError("invalid foundation result") from exc
    return _revalidate(FoundationResult, value, "foundation result")


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
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError) as exc:
        raise FoundationError(f"invalid {label}") from exc


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(raw.model_dump(mode="json", exclude={hash_field}, warnings=False))
    return expected(**values)


def _check_hash(value: BaseModel, hash_field: str) -> None:
    expected = typed_hash(value.model_dump(mode="json", exclude={hash_field}, warnings=False))
    if getattr(value, hash_field) != expected:
        raise ValueError(f"{hash_field} mismatch")


def _aware(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
