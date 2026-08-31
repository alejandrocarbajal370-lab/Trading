"""Phase 7G governed external-provisioning foundation; never REAL admission."""
from __future__ import annotations

import datetime as dt
import json
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

PHASE7G_CONTRACT_VERSION = "phase7g-provisioning-foundation-v2"
TEMPORAL_POLICY_VERSION = "phase7g-temporal-causality-v1"
SHA256 = r"^[0-9a-f]{64}$"
OID = r"^[a-z0-9][a-z0-9._:-]{2,127}$"
NAMESPACE = r"^[a-z][a-z0-9-]{2,31}(?:/[a-z][a-z0-9-]{2,31})*$"
OPAQUE_HANDLE = r"^ref_[A-Za-z0-9_-]{16,96}$"


class Phase7GContractError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SelectionState(StrEnum):
    UNSELECTED = "UNSELECTED"
    SELECTED = "SELECTED"
    PROVISIONING_PENDING = "PROVISIONING_PENDING"
    PROVISIONED_CONTRACT_ONLY = "PROVISIONED_CONTRACT_ONLY"
    EXTERNAL_EVIDENCE_PENDING = "EXTERNAL_EVIDENCE_PENDING"


class ExternalVerificationState(StrEnum):
    NOT_PROVISIONED = "NOT_PROVISIONED"
    OPEN_EXTERNAL = "OPEN_EXTERNAL"


class LegalState(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEW_PENDING = "REVIEW_PENDING"
    EXTERNALLY_VERIFIED = "EXTERNALLY_VERIFIED"


class CredentialReference(ContractModel):
    """A capability locator whose grammar cannot represent credential material."""

    version: Literal["phase7g-credential-reference-v2"] = "phase7g-credential-reference-v2"
    reference_id: str = Field(pattern=OID)
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    purpose: Literal["CONTRACT_ARTIFACT_RETRIEVAL"] = "CONTRACT_ARTIFACT_RETRIEVAL"
    adapter_id: str = Field(pattern=OID)
    secret_store_namespace: str = Field(pattern=NAMESPACE)
    opaque_reference_id: str = Field(pattern=OPAQUE_HANDLE, repr=False)
    reference_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _hash(self, "reference_hash")
        return self


class MakerCheckerDecision(ContractModel):
    version: Literal["phase7g-maker-checker-v1"] = "phase7g-maker-checker-v1"
    maker_id: str = Field(pattern=OID)
    checker_id: str = Field(pattern=OID)
    made_at: dt.datetime
    checked_at: dt.datetime
    decision: Literal["SELECT", "REJECT"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.made_at, "made_at")
        _aware(self.checked_at, "checked_at")
        if self.maker_id == self.checker_id or self.checked_at < self.made_at:
            raise ValueError("invalid maker-checker decision")
        _hash(self, "decision_hash")
        return self


class ProviderDatasetSelection(ContractModel):
    version: Literal["phase7g-selection-v2"] = "phase7g-selection-v2"
    temporal_policy_version: Literal["phase7g-temporal-causality-v1"] = TEMPORAL_POLICY_VERSION
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    selection_state: Literal[SelectionState.SELECTED] = SelectionState.SELECTED
    approval_state: Literal["NOT_APPROVED"] = "NOT_APPROVED"
    admission_state: Literal["NOT_ADMITTED"] = "NOT_ADMITTED"
    legal_state: LegalState
    license_artifact_reference: str | None = Field(default=None, pattern=OID)
    commercial_terms_declaration: str | None = None
    valid_from: dt.datetime
    selected_at: dt.datetime
    valid_until: dt.datetime | None = None
    legal_effective_from: dt.datetime
    legal_effective_until: dt.datetime | None = None
    decision: MakerCheckerDecision
    selection_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        for label in ("valid_from", "selected_at", "legal_effective_from"):
            _aware(getattr(self, label), label)
        for label in ("valid_until", "legal_effective_until"):
            if value := getattr(self, label):
                _aware(value, label)
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("invalid selection window")
        if self.legal_effective_until and self.legal_effective_until <= self.legal_effective_from:
            raise ValueError("invalid legal window")
        if self.valid_from > self.selected_at:
            raise ValueError("selection predates its valid_from")
        if self.valid_until and self.selected_at >= self.valid_until:
            raise ValueError("selection occurred outside its validity window")
        if self.decision.decision != "SELECT" or self.decision.checked_at > self.selected_at:
            raise ValueError("selection lacks prior maker-checker authorization")
        if self.legal_state is LegalState.EXTERNALLY_VERIFIED:
            raise ValueError("external legal verification is unavailable")
        _hash(self, "selection_hash")
        return self


class ExternalAuthorityProvisioning(ContractModel):
    version: Literal["phase7g-authority-provisioning-v1"] = "phase7g-authority-provisioning-v1"
    authority_id: str = Field(pattern=OID)
    mechanism_version: str = Field(pattern=OID)
    key_or_cert_fingerprint: str | None = Field(default=None, pattern=SHA256)
    valid_from: dt.datetime | None = None
    valid_until: dt.datetime | None = None
    revocation_evidence_id: str | None = Field(default=None, pattern=OID)
    state: Literal[ExternalVerificationState.NOT_PROVISIONED] = ExternalVerificationState.NOT_PROVISIONED
    self_declared: Literal[False] = False
    provisioning_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        if self.valid_from or self.valid_until:
            raise ValueError("unprovisioned authority cannot claim an effective window")
        if self.key_or_cert_fingerprint or self.revocation_evidence_id:
            raise ValueError("unprovisioned authority cannot claim verification metadata")
        _hash(self, "provisioning_hash")
        return self


class ObjectLockEvidenceReceipt(ContractModel):
    version: Literal["phase7g-object-lock-receipt-v2"] = "phase7g-object-lock-receipt-v2"
    receipt_id: str = Field(pattern=OID)
    gate: EvidenceGate
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    bucket_id: str = Field(pattern=OID)
    object_id: str = Field(pattern=OID)
    object_version: str = Field(pattern=OID)
    artifact_digest: str = Field(pattern=SHA256)
    recorded_at: dt.datetime
    retention_mode: Literal["DECLARED_ONLY", "NOT_CONFIGURED"]
    retain_until: dt.datetime | None = None
    legal_hold: Literal["DECLARED_ONLY", "NOT_CONFIGURED"]
    provider_evidence_id: str | None = Field(default=None, pattern=OID)
    verification_state: Literal[ExternalVerificationState.OPEN_EXTERNAL] = ExternalVerificationState.OPEN_EXTERNAL
    receipt_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.recorded_at, "recorded_at")
        if self.retain_until:
            _aware(self.retain_until, "retain_until")
        if self.provider_evidence_id:
            raise ValueError("external object-lock evidence is not provisioned")
        _hash(self, "receipt_hash")
        return self


class ProvisionedArtifactEnvelope(ContractModel):
    version: Literal["phase7g-artifact-envelope-v2"] = "phase7g-artifact-envelope-v2"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    gate: EvidenceGate
    source_identity: str = Field(pattern=OID)
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    adapter_id: str = Field(pattern=OID)
    retrieved_at: dt.datetime
    artifact_digest: str = Field(pattern=SHA256)
    provenance_reference: str = Field(pattern=OID)
    custody_reference: str = Field(pattern=OID)
    credential_reference_id: str = Field(pattern=OID)
    envelope_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.retrieved_at, "retrieved_at")
        _hash(self, "envelope_hash")
        return self


class GateEvidenceCandidate(ContractModel):
    version: Literal["phase7g-gate-candidate-v2"] = "phase7g-gate-candidate-v2"
    gate: EvidenceGate
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
    source_identity: str = Field(pattern=OID)
    provenance_reference: str = Field(pattern=OID)
    credential_reference_id: str = Field(pattern=OID)
    selection_hash: str = Field(pattern=SHA256)
    artifact_digest: str = Field(pattern=SHA256)
    authority_provisioning_hash: str = Field(pattern=SHA256)
    custody_receipt_hash: str = Field(pattern=SHA256)
    policy_id: str = Field(pattern=OID)
    observed_at: dt.datetime
    expires_at: dt.datetime
    state: Literal["EXTERNAL_EVIDENCE_PENDING"] = "EXTERNAL_EVIDENCE_PENDING"
    gate_state: Literal[GateState.OPEN_EXTERNAL] = GateState.OPEN_EXTERNAL
    candidate_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.observed_at, "observed_at")
        _aware(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise ValueError("invalid evidence-candidate window")
        _hash(self, "candidate_hash")
        return self


class ProvisioningTransition(ContractModel):
    version: Literal["phase7g-transition-v1"] = "phase7g-transition-v1"
    previous_state: SelectionState
    current_state: SelectionState
    occurred_at: dt.datetime
    selection_hash: str = Field(pattern=SHA256)
    transition_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.occurred_at, "occurred_at")
        allowed = dict(zip(tuple(SelectionState)[:-1], tuple(SelectionState)[1:], strict=True))
        if allowed.get(self.previous_state) is not self.current_state:
            raise ValueError("invalid provisioning transition")
        _hash(self, "transition_hash")
        return self


class Phase7GFoundationResult(ContractModel):
    contract_version: Literal["phase7g-provisioning-foundation-v2"] = PHASE7G_CONTRACT_VERSION
    state: Literal[SelectionState.EXTERNAL_EVIDENCE_PENDING] = SelectionState.EXTERNAL_EVIDENCE_PENDING
    candidates: tuple[GateEvidenceCandidate, ...]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"

    @model_validator(mode="after")
    def check(self):
        if tuple(x.gate for x in self.candidates) != tuple(EvidenceGate):
            raise ValueError("candidates must cover ten canonical gates")
        expected = tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
        if self.gate_states != expected:
            raise ValueError("official gates must remain OPEN_EXTERNAL")
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
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise Phase7GContractError("input is not canonically serializable") from exc


def _revalidate(expected: type[T], value: Any, label: str) -> T:
    try:
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError) as exc:
        raise Phase7GContractError(f"invalid {label}") from exc


def _by_gate(items: tuple[T, ...], label: str) -> dict[EvidenceGate, T]:
    mapped: dict[EvidenceGate, T] = {}
    for item in items:
        gate = item.gate
        if gate in mapped:
            raise Phase7GContractError(f"duplicate {label} gate")
        mapped[gate] = item
    if set(mapped) != set(EvidenceGate):
        raise Phase7GContractError(f"{label} must cover ten canonical gates")
    return mapped


def assess_provisioning_foundation(*, selection: Any, authority: Any, custody: Any,
                                   credentials: Any, envelopes: Any, candidates: Any,
                                   transitions: Any, verifier_time: dt.datetime) -> Phase7GFoundationResult:
    """Derive contract-only state after reconstructing every caller-controlled input."""
    _aware(verifier_time, "verifier_time")
    selected = _revalidate(ProviderDatasetSelection, selection, "selection")
    authority_record = _revalidate(ExternalAuthorityProvisioning, authority, "authority")
    custody_items = tuple(_revalidate(ObjectLockEvidenceReceipt, x, "custody receipt") for x in custody)
    credential_items = tuple(_revalidate(CredentialReference, x, "credential reference") for x in credentials)
    envelope_items = tuple(_revalidate(ProvisionedArtifactEnvelope, x, "envelope") for x in envelopes)
    candidate_items = tuple(_revalidate(GateEvidenceCandidate, x, "candidate") for x in candidates)
    transition_items = tuple(_revalidate(ProvisioningTransition, x, "transition") for x in transitions)

    if not (selected.valid_from <= selected.selected_at <= verifier_time):
        raise Phase7GContractError("selection temporal causality violation")
    if selected.valid_until and verifier_time >= selected.valid_until:
        raise Phase7GContractError("selection expired at verifier_time")
    if selected.legal_effective_from > selected.selected_at:
        raise Phase7GContractError("retroactive legal/licensing legitimation")
    if selected.legal_effective_until and verifier_time >= selected.legal_effective_until:
        raise Phase7GContractError("legal/licensing window expired at verifier_time")

    expected_states = tuple(SelectionState)
    if len(transition_items) != len(expected_states) - 1:
        raise Phase7GContractError("incomplete provisioning transition chain")
    for index, transition in enumerate(transition_items):
        if (transition.previous_state is not expected_states[index]
                or transition.current_state is not expected_states[index + 1]
                or transition.selection_hash != selected.selection_hash
                or transition.occurred_at > verifier_time
                or (index and transition.occurred_at < transition_items[index - 1].occurred_at)):
            raise Phase7GContractError("invalid provisioning transition chain")
    if transition_items[0].occurred_at != selected.selected_at:
        raise Phase7GContractError("SELECTED transition does not match selection")

    custody_by_gate = _by_gate(custody_items, "custody receipts")
    envelopes_by_gate = _by_gate(envelope_items, "envelopes")
    candidates_by_gate = _by_gate(candidate_items, "candidates")
    credentials_by_id = {item.reference_id: item for item in credential_items}
    if len(credentials_by_id) != len(credential_items):
        raise Phase7GContractError("duplicate credential reference")
    selected_identity = (selected.provider_id, selected.dataset_id, selected.dataset_version, selected.scope_id)
    provisioned_at = transition_items[2].occurred_at
    evidence_pending_at = transition_items[3].occurred_at
    for gate in EvidenceGate:
        envelope, candidate, receipt = envelopes_by_gate[gate], candidates_by_gate[gate], custody_by_gate[gate]
        credential = credentials_by_id.get(envelope.credential_reference_id)
        envelope_identity = (envelope.provider_id, envelope.dataset_id, envelope.dataset_version, envelope.scope_id)
        candidate_identity = (candidate.provider_id, candidate.dataset_id, candidate.dataset_version, candidate.scope_id)
        receipt_identity = (receipt.provider_id, receipt.dataset_id, receipt.dataset_version, receipt.scope_id)
        if envelope_identity != selected_identity or candidate_identity != selected_identity:
            raise Phase7GContractError("provider/dataset/version/scope binding mismatch")
        if receipt_identity != selected_identity:
            raise Phase7GContractError("custody identity binding mismatch")
        if credential is None:
            raise Phase7GContractError("credential reference does not resolve")
        if (credential.provider_id, credential.dataset_id, credential.scope_id, credential.adapter_id) != (
                selected.provider_id, selected.dataset_id, selected.scope_id, envelope.adapter_id):
            raise Phase7GContractError("credential capability binding mismatch")
        if (envelope.custody_reference != receipt.receipt_id
                or receipt.artifact_digest != envelope.artifact_digest
                or candidate.custody_receipt_hash != receipt.receipt_hash
                or candidate.selection_hash != selected.selection_hash
                or candidate.artifact_digest != envelope.artifact_digest
                or candidate.authority_provisioning_hash != authority_record.provisioning_hash
                or candidate.source_identity != envelope.source_identity
                or candidate.provenance_reference != envelope.provenance_reference
                or candidate.credential_reference_id != envelope.credential_reference_id):
            raise Phase7GContractError("gate artifact/custody/provenance binding mismatch")
        if not (selected.valid_from <= selected.selected_at <= provisioned_at
                <= envelope.retrieved_at <= receipt.recorded_at <= candidate.observed_at
                <= evidence_pending_at <= verifier_time < candidate.expires_at):
            raise Phase7GContractError("temporal causality violation")
        if envelope.retrieved_at < selected.legal_effective_from:
            raise Phase7GContractError("artifact predates legal/licensing effectiveness")

    canonical_candidates = tuple(candidates_by_gate[gate] for gate in EvidenceGate)
    return Phase7GFoundationResult(candidates=canonical_candidates,
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate))


def real_external_verification_unavailable(*_args: Any, **_kwargs: Any) -> None:
    raise Phase7GContractError("REAL verification is unavailable: external trust is not provisioned")
