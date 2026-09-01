"""External evidence verification acceptance foundation; never gate closure."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import secrets
import threading
import weakref
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "external-evidence-verification-acceptance-v2"
TEMPORAL_POLICY_VERSION = "external-verifier-causality-replay-v2"
MANIFEST_VERSION = "external-verification-canonical-manifest-v1"
OBSERVATION_VERSION = "material-observation-contract-test-v1"
REPLAY_IDENTITY_VERSION = "material-replay-identity-v1"
MAX_EVIDENCE_AGE = dt.timedelta(hours=24)
MAX_AUTHORITY_AGE = dt.timedelta(hours=24)
MAX_REVOCATION_AGE = dt.timedelta(hours=1)
SHA256 = r"^[0-9a-f]{64}$"

Observer = Literal["actor.external.observer"]
Maker = Literal["actor.external.maker"]
Checker = Literal["actor.external.checker"]
Reviewer = Literal["actor.external.reviewer"]


class ExternalEvidenceVerificationError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateVerificationExpectation(ContractModel):
    """Code-owned contract identity; internal consistency, not external truth."""

    version: Literal["gate-verification-expectation-v1"] = "gate-verification-expectation-v1"
    gate: EvidenceGate
    provider_ref: str
    dataset_ref: str
    dataset_version_ref: str
    adapter_ref: str
    adapter_release_ref: str
    evidence_policy_ref: str
    receipt_policy_ref: str
    expected_artifact_digest: str = Field(pattern=SHA256)
    accepted_artifact_digests: tuple[str, ...]
    expectation_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        if (
            not self.accepted_artifact_digests
            or self.expected_artifact_digest != (self.accepted_artifact_digests[0])
        ):
            raise ValueError("invalid canonical artifact digest registry")
        if len(set(self.accepted_artifact_digests)) != len(self.accepted_artifact_digests) or any(
            re.fullmatch(SHA256, value) is None for value in self.accepted_artifact_digests
        ):
            raise ValueError("invalid accepted artifact digests")
        _hash(self, "expectation_hash")
        return self


class GateVerificationManifest(ContractModel):
    version: Literal["external-verification-canonical-manifest-v1"] = MANIFEST_VERSION
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    expectations: tuple[GateVerificationExpectation, ...]
    manifest_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        if tuple(item.gate for item in self.expectations) != tuple(EvidenceGate):
            raise ValueError("manifest must cover canonical gates in canonical order")
        _hash(self, "manifest_hash")
        return self


class ProviderAdapterIdentity(ContractModel):
    """Code-owned manifest reference; no caller-authored provider metadata."""

    version: Literal["provider-adapter-identity-v2"] = "provider-adapter-identity-v2"
    manifest_version: Literal["external-verification-canonical-manifest-v1"] = MANIFEST_VERSION
    manifest_hash: str = Field(pattern=SHA256)
    identity_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _hash(self, "identity_hash")
        return self


class MaterializedObservedEvidence(ContractModel):
    """Content-bound CONTRACT_TEST_ONLY observation; not provider authentication."""

    version: Literal["material-observation-contract-test-v1"] = OBSERVATION_VERSION
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    gate: EvidenceGate
    expectation_hash: str = Field(pattern=SHA256)
    provider_ref: str
    dataset_ref: str
    dataset_version_ref: str
    adapter_ref: str
    adapter_release_ref: str
    evidence_policy_ref: str
    receipt_policy_ref: str
    adapter_identity_hash: str = Field(pattern=SHA256)
    material_base64: str
    material_digest: str = Field(pattern=SHA256)
    observed_at: dt.datetime
    observer_id: Observer = "actor.external.observer"
    observation_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.observed_at, "observed_at")
        if _material_digest(self.material_base64) != self.material_digest:
            raise ValueError("material digest mismatch")
        _hash(self, "observation_hash")
        return self


class ReplayLedger(ABC):
    """Verifier-owned atomic consumption boundary; REAL durable storage is absent."""

    @property
    @abstractmethod
    def provisioning_state(self) -> str: ...

    @abstractmethod
    def consume_many(self, identities: Iterable[str], verifier_time: dt.datetime) -> None: ...


class InMemoryContractTestReplayLedger(ReplayLedger):
    """Process-local atomic contract implementation; never durable/REAL replay protection."""

    def __init__(self) -> None:
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    @property
    def provisioning_state(self) -> str:
        return "CONTRACT_TEST_ONLY"

    def consume_many(self, identities: Iterable[str], verifier_time: dt.datetime) -> None:
        _aware(verifier_time, "verifier_time")
        batch = tuple(identities)
        if len(batch) != len(set(batch)):
            raise ExternalEvidenceVerificationError("duplicate replay identity in assessment")
        with self._lock:
            if any(identity in self._consumed for identity in batch):
                raise ExternalEvidenceVerificationError("material evidence replayed")
            self._consumed.update(batch)


_CONTEXT_FACTORY_TOKEN = object()
_CONTEXT_REGISTRY_LOCK = threading.Lock()
_CONTEXT_REGISTRY: weakref.WeakKeyDictionary[
    ExternalEvidenceVerifierContext, InMemoryContractTestReplayLedger
] = weakref.WeakKeyDictionary()


class ExternalEvidenceVerifierContext:
    """Explicit CONTRACT_TEST_ONLY verifier lifecycle; never REAL authority."""

    __slots__ = ("__weakref__", "_ledger", "_lifecycle_namespace", "_sealed")

    def __init__(self, factory_token: object) -> None:
        if factory_token is not _CONTEXT_FACTORY_TOKEN:
            raise ExternalEvidenceVerificationError(
                "contract-test verifier context must be created by its explicit factory"
            )
        ledger = InMemoryContractTestReplayLedger()
        namespace = typed_hash(
            {
                "contract": CONTRACT_VERSION,
                "manifest": MANIFEST_VERSION,
                "replay_identity": REPLAY_IDENTITY_VERSION,
                "lifecycle_entropy": secrets.token_hex(32),
            }
        )
        object.__setattr__(self, "_ledger", ledger)
        object.__setattr__(self, "_lifecycle_namespace", namespace)
        object.__setattr__(self, "_sealed", True)
        with _CONTEXT_REGISTRY_LOCK:
            _CONTEXT_REGISTRY[self] = ledger

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("verifier context is immutable")
        object.__setattr__(self, name, value)

    @property
    def lifecycle_namespace(self) -> str:
        """Opaque code-created identity for this isolated contract-test lifecycle."""
        return self._lifecycle_namespace

    def assess_external_evidence_verification(
        self, **intake: Any
    ) -> ExternalVerificationFoundationResult:
        """Assess within this context's stable process-local replay lifecycle."""
        return assess_external_evidence_verification(verifier_context=self, **intake)


def build_contract_test_verifier_context() -> ExternalEvidenceVerifierContext:
    """Start a new, explicitly isolated CONTRACT_TEST_ONLY verifier lifecycle."""
    return ExternalEvidenceVerifierContext(_CONTEXT_FACTORY_TOKEN)


def _context_ledger(value: Any) -> InMemoryContractTestReplayLedger:
    if type(value) is not ExternalEvidenceVerifierContext:
        raise ExternalEvidenceVerificationError("valid verifier-owned context required")
    with _CONTEXT_REGISTRY_LOCK:
        ledger = _CONTEXT_REGISTRY.get(value)
    try:
        valid = (
            type(ledger) is InMemoryContractTestReplayLedger
            and value._ledger is ledger
            and re.fullmatch(SHA256, value._lifecycle_namespace) is not None
            and value._sealed is True
        )
    except (AttributeError, TypeError):
        valid = False
    if not valid:
        raise ExternalEvidenceVerificationError("valid verifier-owned context required")
    return ledger


class ExternalEvidenceReceipt(ContractModel):
    """Observed contract-test evidence; never authentication or acceptance."""

    version: Literal["external-evidence-receipt-v2"] = "external-evidence-receipt-v2"
    gate: EvidenceGate
    expectation_hash: str = Field(pattern=SHA256)
    adapter_identity_hash: str = Field(pattern=SHA256)
    observation_hash: str = Field(pattern=SHA256)
    assessment_identity: str = Field(pattern=SHA256)
    artifact_digest: str = Field(pattern=SHA256)
    provider_receipt_digest: str = Field(pattern=SHA256)
    provider_sequence: int = Field(ge=0)
    replay_nonce_digest: str = Field(pattern=SHA256)
    provider_issued_at: dt.datetime
    observed_at: dt.datetime
    expires_at: dt.datetime
    signature_fingerprint: str = Field(pattern=SHA256)
    signature_check: Literal["MATCHED_UNTRUSTED", "INVALID", "UNSUPPORTED"]
    observation_state: Literal["OBSERVED_UNVERIFIED"] = "OBSERVED_UNVERIFIED"
    receipt_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        for label in ("provider_issued_at", "observed_at", "expires_at"):
            _aware(getattr(self, label), label)
        if not self.provider_issued_at <= self.observed_at < self.expires_at:
            raise ValueError("invalid receipt chronology")
        _hash(self, "receipt_hash")
        return self


class VerifierAuthoritySnapshot(ContractModel):
    version: Literal["verifier-authority-snapshot-v2"] = "verifier-authority-snapshot-v2"
    gate: EvidenceGate
    expectation_hash: str = Field(pattern=SHA256)
    receipt_hash: str = Field(pattern=SHA256)
    assessment_identity: str = Field(pattern=SHA256)
    observer_id: Observer = "actor.external.observer"
    maker_id: Maker = "actor.external.maker"
    checker_id: Checker = "actor.external.checker"
    reviewer_id: Reviewer = "actor.external.reviewer"
    captured_at: dt.datetime
    valid_from: dt.datetime
    valid_until: dt.datetime
    verifier_time: dt.datetime
    fingerprint: str = Field(pattern=SHA256)
    authority_status: Literal["ACTIVE_UNTRUSTED", "REVOKED", "UNKNOWN", "NOT_PROVISIONED"]
    independently_observed: Literal[True] = True
    snapshot_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        for label in ("captured_at", "valid_from", "valid_until", "verifier_time"):
            _aware(getattr(self, label), label)
        if not self.valid_from <= self.captured_at < self.valid_until:
            raise ValueError("invalid authority validity window")
        _hash(self, "snapshot_hash")
        return self


class IndependentVerifierDecision(ContractModel):
    version: Literal["independent-verifier-decision-v2"] = "independent-verifier-decision-v2"
    gate: EvidenceGate
    expectation_hash: str = Field(pattern=SHA256)
    receipt_hash: str = Field(pattern=SHA256)
    assessment_identity: str = Field(pattern=SHA256)
    observer_id: Observer = "actor.external.observer"
    maker_id: Maker = "actor.external.maker"
    checker_id: Checker = "actor.external.checker"
    reviewer_id: Reviewer = "actor.external.reviewer"
    authority_snapshot_hash: str = Field(pattern=SHA256)
    verifier_time: dt.datetime
    made_at: dt.datetime
    checked_at: dt.datetime
    reviewed_at: dt.datetime
    outcome: Literal["CANDIDATE", "REJECT"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        for label in ("verifier_time", "made_at", "checked_at", "reviewed_at"):
            _aware(getattr(self, label), label)
        if not self.made_at <= self.checked_at <= self.reviewed_at <= self.verifier_time:
            raise ValueError("invalid maker-checker-reviewer chronology")
        _hash(self, "decision_hash")
        return self


class RevocationReview(ContractModel):
    version: Literal["revocation-review-v1"] = "revocation-review-v1"
    gate: EvidenceGate
    expectation_hash: str = Field(pattern=SHA256)
    receipt_hash: str = Field(pattern=SHA256)
    assessment_identity: str = Field(pattern=SHA256)
    authority_snapshot_hash: str = Field(pattern=SHA256)
    decision_hash: str = Field(pattern=SHA256)
    observer_id: Observer = "actor.external.observer"
    maker_id: Maker = "actor.external.maker"
    checker_id: Checker = "actor.external.checker"
    reviewer_id: Reviewer = "actor.external.reviewer"
    observed_at: dt.datetime
    made_at: dt.datetime
    checked_at: dt.datetime
    verifier_time: dt.datetime
    reviewed_at: dt.datetime
    status: Literal["ACTIVE_UNTRUSTED", "REVOKED", "UNKNOWN", "NOT_PROVISIONED"]
    revoked_at: dt.datetime | None = None
    review_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        for label in ("observed_at", "made_at", "checked_at", "verifier_time", "reviewed_at"):
            _aware(getattr(self, label), label)
        if self.revoked_at is not None:
            _aware(self.revoked_at, "revoked_at")
        if self.reviewed_at > self.verifier_time:
            raise ValueError("revocation review is in the future")
        _hash(self, "review_hash")
        return self


class GateVerificationCandidate(ContractModel):
    gate: EvidenceGate
    expectation_hash: str = Field(pattern=SHA256)
    receipt_hash: str = Field(pattern=SHA256)
    decision_hash: str = Field(pattern=SHA256)
    authority_snapshot_hash: str = Field(pattern=SHA256)
    revocation_review_hash: str = Field(pattern=SHA256)
    state: Literal["TECHNICALLY_CHECKED_NOT_TRUSTED"] = "TECHNICALLY_CHECKED_NOT_TRUSTED"
    gate_state: Literal[GateState.OPEN_EXTERNAL] = GateState.OPEN_EXTERNAL
    reason: Literal["EXTERNAL_TRUST_ROOT_NOT_PROVISIONED"] = "EXTERNAL_TRUST_ROOT_NOT_PROVISIONED"


class ExternalVerificationFoundationResult(ContractModel):
    contract_version: Literal["external-evidence-verification-acceptance-v2"] = CONTRACT_VERSION
    temporal_policy_version: Literal["external-verifier-causality-replay-v2"] = (
        TEMPORAL_POLICY_VERSION
    )
    candidates: tuple[GateVerificationCandidate, ...]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    authority_state: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    result_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        if tuple(item.gate for item in self.candidates) != tuple(EvidenceGate):
            raise ValueError("candidates must cover canonical gates")
        expected = tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
        if self.gate_states != expected:
            raise ValueError("official gates must remain OPEN_EXTERNAL")
        _hash(self, "result_hash")
        return self


T = TypeVar("T", bound=BaseModel)


def _aware(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _hash(value: BaseModel, field: str) -> None:
    if getattr(value, field) != typed_hash(value.model_dump(mode="json", exclude={field})):
        raise ValueError(f"{field} mismatch")


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise ExternalEvidenceVerificationError("model contains undeclared fields")
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ExternalEvidenceVerificationError("input is not canonically serializable") from exc


def _revalidate(expected: type[T], value: Any, label: str) -> T:
    try:
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError) as exc:
        raise ExternalEvidenceVerificationError(f"invalid {label}") from exc


def seal(expected: type[T], hash_field: str, **values: Any) -> T:
    """Construct a hash-sealed contract object for contract tests."""
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(
        raw.model_dump(mode="json", exclude={hash_field}, warnings=False)
    )
    return expected(**values)


def _material_digest(material_base64: str) -> str:
    try:
        material = base64.b64decode(material_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("material must be canonical base64") from exc
    if base64.b64encode(material).decode("ascii") != material_base64:
        raise ValueError("material must use canonical base64 encoding")
    return hashlib.sha256(material).hexdigest()


def _contract_test_material(gate: EvidenceGate, variant: str = "v1") -> bytes:
    if variant not in {"v1", "v2"}:
        raise ExternalEvidenceVerificationError("unknown contract-test material variant")
    return f"external-evidence-contract-fixture-{variant}:{gate.value}".encode()


def canonical_gate_verification_manifest() -> GateVerificationManifest:
    """Reconstruct the immutable code-owned contract-test expectation registry."""
    expectations = []
    for gate in EvidenceGate:
        slug = gate.value.casefold()
        expectations.append(
            seal(
                GateVerificationExpectation,
                "expectation_hash",
                gate=gate,
                provider_ref=f"registry.provider.{slug}",
                dataset_ref=f"registry.dataset.{slug}",
                dataset_version_ref="registry.dataset.version.v1",
                adapter_ref=f"registry.adapter.{slug}",
                adapter_release_ref="registry.adapter.release.v1",
                evidence_policy_ref=f"registry.evidence.{slug}.v1",
                receipt_policy_ref=f"registry.receipt.{slug}.v1",
                expected_artifact_digest=hashlib.sha256(_contract_test_material(gate)).hexdigest(),
                accepted_artifact_digests=tuple(
                    hashlib.sha256(_contract_test_material(gate, variant)).hexdigest()
                    for variant in ("v1", "v2")
                ),
            )
        )
    return seal(GateVerificationManifest, "manifest_hash", expectations=tuple(expectations))


def observe_contract_test_material(
    *,
    gate: EvidenceGate,
    material: bytes,
    observed_at: dt.datetime,
    adapter: Any,
) -> MaterializedObservedEvidence:
    """Adapter-facing test boundary that computes content digest; it never authenticates it."""
    if not isinstance(material, bytes) or not material:
        raise ExternalEvidenceVerificationError("observed material bytes are required")
    _aware(observed_at, "observed_at")
    manifest = canonical_gate_verification_manifest()
    adapter_record = _revalidate(ProviderAdapterIdentity, adapter, "adapter identity")
    if (adapter_record.manifest_version, adapter_record.manifest_hash) != (
        manifest.version,
        manifest.manifest_hash,
    ):
        raise ExternalEvidenceVerificationError("adapter manifest binding mismatch")
    expectation = {item.gate: item for item in manifest.expectations}[gate]
    encoded = base64.b64encode(material).decode("ascii")
    return seal(
        MaterializedObservedEvidence,
        "observation_hash",
        gate=gate,
        expectation_hash=expectation.expectation_hash,
        provider_ref=expectation.provider_ref,
        dataset_ref=expectation.dataset_ref,
        dataset_version_ref=expectation.dataset_version_ref,
        adapter_ref=expectation.adapter_ref,
        adapter_release_ref=expectation.adapter_release_ref,
        evidence_policy_ref=expectation.evidence_policy_ref,
        receipt_policy_ref=expectation.receipt_policy_ref,
        adapter_identity_hash=adapter_record.identity_hash,
        material_base64=encoded,
        material_digest=hashlib.sha256(material).hexdigest(),
        observed_at=observed_at,
    )


def contract_test_material_for_gate(gate: EvidenceGate, variant: str = "v1") -> bytes:
    """Return synthetic fixture bytes; unavailable to any REAL admission path."""
    return _contract_test_material(gate, variant)


def validate_external_verification_result(value: Any) -> ExternalVerificationFoundationResult:
    """Mandatory public truth boundary: rebuild primitives and revalidate derived safe state."""
    return _revalidate(ExternalVerificationFoundationResult, value, "foundation result")


def assess_external_evidence_verification(
    *,
    verifier_context: Any = None,
    adapter: Any,
    observed_materials: Any,
    authorities: Any,
    receipts: Any,
    decisions: Any,
    revocations: Any,
    verifier_time: dt.datetime,
) -> ExternalVerificationFoundationResult:
    """Validate intake and derive non-closing candidates while external trust is absent."""
    _aware(verifier_time, "verifier_time")
    replay_ledger = _context_ledger(verifier_context)
    manifest = canonical_gate_verification_manifest()
    adapter_record = _revalidate(ProviderAdapterIdentity, adapter, "adapter identity")
    if (adapter_record.manifest_version, adapter_record.manifest_hash) != (
        manifest.version,
        manifest.manifest_hash,
    ):
        raise ExternalEvidenceVerificationError("adapter manifest binding mismatch")
    observed_by_gate = _canonical(
        tuple(
            _revalidate(MaterializedObservedEvidence, x, "observed material")
            for x in observed_materials
        ),
        "observed materials",
    )
    receipt_by_gate = _canonical(
        tuple(_revalidate(ExternalEvidenceReceipt, x, "receipt") for x in receipts), "receipts"
    )
    authority_by_gate = _canonical(
        tuple(_revalidate(VerifierAuthoritySnapshot, x, "authority") for x in authorities),
        "authorities",
    )
    decision_by_gate = _canonical(
        tuple(_revalidate(IndependentVerifierDecision, x, "decision") for x in decisions),
        "decisions",
    )
    revocation_by_gate = _canonical(
        tuple(_revalidate(RevocationReview, x, "revocation review") for x in revocations),
        "revocations",
    )
    expectation_by_gate = {item.gate: item for item in manifest.expectations}
    candidates = []
    replay_identities = []
    for gate in EvidenceGate:
        expectation = expectation_by_gate[gate]
        observed = observed_by_gate[gate]
        receipt, authority = receipt_by_gate[gate], authority_by_gate[gate]
        decision, revocation = decision_by_gate[gate], revocation_by_gate[gate]
        expected_assessment = typed_hash(
            {
                "contract": CONTRACT_VERSION,
                "gate": gate.value,
                "expectation_hash": expectation.expectation_hash,
                "provider_receipt_digest": receipt.provider_receipt_digest,
                "verifier_time": verifier_time.isoformat(),
            }
        )
        common = (gate, expectation.expectation_hash, receipt.receipt_hash, expected_assessment)
        if (
            receipt.gate,
            receipt.expectation_hash,
            receipt.receipt_hash,
            receipt.assessment_identity,
        ) != common:
            raise ExternalEvidenceVerificationError("canonical gate expectation mismatch")
        if receipt.artifact_digest not in expectation.accepted_artifact_digests:
            raise ExternalEvidenceVerificationError("canonical artifact identity mismatch")
        observed_binding = (
            observed.gate,
            observed.expectation_hash,
            observed.provider_ref,
            observed.dataset_ref,
            observed.dataset_version_ref,
            observed.adapter_ref,
            observed.adapter_release_ref,
            observed.evidence_policy_ref,
            observed.receipt_policy_ref,
            observed.adapter_identity_hash,
            observed.material_digest,
            observed.observed_at,
        )
        expected_observed_binding = (
            gate,
            expectation.expectation_hash,
            expectation.provider_ref,
            expectation.dataset_ref,
            expectation.dataset_version_ref,
            expectation.adapter_ref,
            expectation.adapter_release_ref,
            expectation.evidence_policy_ref,
            expectation.receipt_policy_ref,
            adapter_record.identity_hash,
            receipt.artifact_digest,
            receipt.observed_at,
        )
        if observed_binding != expected_observed_binding:
            raise ExternalEvidenceVerificationError(
                "material observation canonical binding mismatch"
            )
        if receipt.observation_hash != observed.observation_hash or (
            receipt.artifact_digest != observed.material_digest
        ):
            raise ExternalEvidenceVerificationError("receipt material observation mismatch")
        if receipt.adapter_identity_hash != adapter_record.identity_hash:
            raise ExternalEvidenceVerificationError("adapter identity binding mismatch")
        replay_identities.append(
            typed_hash(
                {
                    "version": REPLAY_IDENTITY_VERSION,
                    "temporal_policy": TEMPORAL_POLICY_VERSION,
                    "gate": gate.value,
                    "expectation_hash": expectation.expectation_hash,
                    "provider_ref": expectation.provider_ref,
                    "dataset_ref": expectation.dataset_ref,
                    "dataset_version_ref": expectation.dataset_version_ref,
                    "adapter_ref": expectation.adapter_ref,
                    "adapter_release_ref": expectation.adapter_release_ref,
                    "material_digest": observed.material_digest,
                }
            )
        )
        if receipt.signature_check != "MATCHED_UNTRUSTED":
            raise ExternalEvidenceVerificationError("signature check did not produce a candidate")
        authority_common = (
            authority.gate,
            authority.expectation_hash,
            authority.receipt_hash,
            authority.assessment_identity,
        )
        decision_common = (
            decision.gate,
            decision.expectation_hash,
            decision.receipt_hash,
            decision.assessment_identity,
        )
        revocation_common = (
            revocation.gate,
            revocation.expectation_hash,
            revocation.receipt_hash,
            revocation.assessment_identity,
        )
        if authority_common != common or decision_common != common or revocation_common != common:
            raise ExternalEvidenceVerificationError("gate assessment binding mismatch")
        actors = (
            authority.observer_id,
            authority.maker_id,
            authority.checker_id,
            authority.reviewer_id,
        )
        if (
            len(set(actors)) != 4
            or actors
            != (decision.observer_id, decision.maker_id, decision.checker_id, decision.reviewer_id)
            or actors
            != (
                revocation.observer_id,
                revocation.maker_id,
                revocation.checker_id,
                revocation.reviewer_id,
            )
        ):
            raise ExternalEvidenceVerificationError("actor independence or binding mismatch")
        if authority.fingerprint != receipt.signature_fingerprint:
            raise ExternalEvidenceVerificationError("signature fingerprint mismatch")
        if authority.verifier_time != verifier_time or decision.verifier_time != verifier_time:
            raise ExternalEvidenceVerificationError("verifier-time binding mismatch")
        if (
            authority.authority_status != "ACTIVE_UNTRUSTED"
            or revocation.status != "ACTIVE_UNTRUSTED"
        ):
            raise ExternalEvidenceVerificationError("authority or revocation status is fail-closed")
        if revocation.revoked_at is not None and revocation.revoked_at <= verifier_time:
            raise ExternalEvidenceVerificationError("authority revoked at a relevant time")
        if not (
            authority.valid_from
            <= authority.captured_at
            <= receipt.provider_issued_at
            <= receipt.observed_at
            <= decision.made_at
            <= decision.checked_at
            <= decision.reviewed_at
            <= revocation.reviewed_at
            <= verifier_time
            < authority.valid_until
        ):
            raise ExternalEvidenceVerificationError("verification causality violation")
        if authority.captured_at < verifier_time - MAX_AUTHORITY_AGE:
            raise ExternalEvidenceVerificationError("stale authority snapshot")
        if revocation.reviewed_at < verifier_time - MAX_REVOCATION_AGE:
            raise ExternalEvidenceVerificationError("stale revocation review")
        if (
            revocation.observed_at,
            revocation.made_at,
            revocation.checked_at,
            revocation.verifier_time,
        ) != (receipt.observed_at, decision.made_at, decision.checked_at, verifier_time):
            raise ExternalEvidenceVerificationError("revocation relevant-time binding mismatch")
        if revocation.authority_snapshot_hash != authority.snapshot_hash:
            raise ExternalEvidenceVerificationError("revocation authority binding mismatch")
        if decision.authority_snapshot_hash != authority.snapshot_hash:
            raise ExternalEvidenceVerificationError("decision authority binding mismatch")
        if revocation.decision_hash != decision.decision_hash:
            raise ExternalEvidenceVerificationError("revocation decision binding mismatch")
        if decision.outcome != "CANDIDATE":
            raise ExternalEvidenceVerificationError("rejected evidence cannot become a candidate")
        if (
            verifier_time >= receipt.expires_at
            or verifier_time - receipt.observed_at > MAX_EVIDENCE_AGE
        ):
            raise ExternalEvidenceVerificationError("stale external evidence")
        candidates.append(
            GateVerificationCandidate(
                gate=gate,
                expectation_hash=expectation.expectation_hash,
                receipt_hash=receipt.receipt_hash,
                decision_hash=decision.decision_hash,
                authority_snapshot_hash=authority.snapshot_hash,
                revocation_review_hash=revocation.review_hash,
            )
        )
    replay_ledger.consume_many(replay_identities, verifier_time)
    result = seal(
        ExternalVerificationFoundationResult,
        "result_hash",
        candidates=tuple(candidates),
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    )
    return validate_external_verification_result(result)


def _canonical(items: tuple[T, ...], label: str) -> dict[EvidenceGate, T]:
    mapped: dict[EvidenceGate, T] = {}
    for item in items:
        if item.gate in mapped:
            raise ExternalEvidenceVerificationError(f"duplicate {label} gate")
        mapped[item.gate] = item
    if set(mapped) != set(EvidenceGate):
        raise ExternalEvidenceVerificationError(f"{label} must cover ten canonical gates")
    return mapped
