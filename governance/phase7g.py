"""Phase 7G governed external-provisioning foundation; never REAL admission."""

from __future__ import annotations

import datetime as dt
import json
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

PHASE7G_CONTRACT_VERSION = "phase7g-provisioning-foundation-v1"
SHA256 = r"^[0-9a-f]{64}$"
OID = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


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
    version: Literal["phase7g-credential-reference-v1"] = "phase7g-credential-reference-v1"
    reference_id: str = Field(pattern=OID)
    backend: Literal["ENV_REFERENCE", "SECRET_MANAGER_HANDLE"]
    handle: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$|^[a-z0-9][a-z0-9/_:.-]{2,255}$")

    @model_validator(mode="after")
    def reject_values(self):
        lowered = self.handle.casefold()
        if any(x in lowered for x in ("bearer ", "api_key=", "password=", "secret=")):
            raise ValueError("credential values are forbidden")
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
    version: Literal["phase7g-selection-v1"] = "phase7g-selection-v1"
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
    valid_until: dt.datetime | None = None
    decision: MakerCheckerDecision
    selection_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.valid_from, "valid_from")
        if self.valid_until:
            _aware(self.valid_until, "valid_until")
            if self.valid_until <= self.valid_from:
                raise ValueError("invalid selection window")
        if self.decision.decision != "SELECT" or self.decision.checked_at > self.valid_from:
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
    state: Literal[ExternalVerificationState.NOT_PROVISIONED] = (
        ExternalVerificationState.NOT_PROVISIONED
    )
    self_declared: Literal[False] = False
    provisioning_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        if self.valid_from:
            _aware(self.valid_from, "authority valid_from")
        if self.valid_until:
            _aware(self.valid_until, "authority valid_until")
        if self.key_or_cert_fingerprint or self.revocation_evidence_id:
            raise ValueError("unprovisioned authority cannot claim verification metadata")
        _hash(self, "provisioning_hash")
        return self


class ObjectLockEvidenceReceipt(ContractModel):
    version: Literal["phase7g-object-lock-receipt-v1"] = "phase7g-object-lock-receipt-v1"
    provider_id: str = Field(pattern=OID)
    bucket_id: str = Field(pattern=OID)
    object_id: str = Field(pattern=OID)
    object_version: str = Field(pattern=OID)
    retention_mode: Literal["DECLARED_ONLY", "NOT_CONFIGURED"]
    retain_until: dt.datetime | None = None
    legal_hold: Literal["DECLARED_ONLY", "NOT_CONFIGURED"]
    provider_evidence_id: str | None = Field(default=None, pattern=OID)
    verification_state: Literal[ExternalVerificationState.OPEN_EXTERNAL] = (
        ExternalVerificationState.OPEN_EXTERNAL
    )
    receipt_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        if self.retain_until:
            _aware(self.retain_until, "retain_until")
        if self.provider_evidence_id:
            raise ValueError("external object-lock evidence is not provisioned")
        _hash(self, "receipt_hash")
        return self


class ProvisionedArtifactEnvelope(ContractModel):
    version: Literal["phase7g-artifact-envelope-v1"] = "phase7g-artifact-envelope-v1"
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    source_identity: str = Field(pattern=OID)
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
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
    version: Literal["phase7g-gate-candidate-v1"] = "phase7g-gate-candidate-v1"
    gate: EvidenceGate
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    scope_id: str = Field(pattern=OID)
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


class Phase7GFoundationResult(ContractModel):
    contract_version: Literal["phase7g-provisioning-foundation-v1"] = PHASE7G_CONTRACT_VERSION
    state: Literal["EXTERNAL_EVIDENCE_PENDING"] = "EXTERNAL_EVIDENCE_PENDING"
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


def assess_provisioning_foundation(
    *,
    selection: Any,
    authority: Any,
    custody: Any,
    envelopes: Any,
    candidates: Any,
    verifier_time: dt.datetime,
) -> Phase7GFoundationResult:
    """Revalidate contract-only candidates without providing any REAL promotion path."""
    _aware(verifier_time, "verifier_time")
    selected = _revalidate(ProviderDatasetSelection, selection, "selection")
    authority_record = _revalidate(ExternalAuthorityProvisioning, authority, "authority")
    custody_record = _revalidate(ObjectLockEvidenceReceipt, custody, "custody")
    envelope_items = tuple(
        _revalidate(ProvisionedArtifactEnvelope, x, "envelope") for x in envelopes
    )
    candidate_items = tuple(_revalidate(GateEvidenceCandidate, x, "candidate") for x in candidates)
    if tuple(x.gate for x in candidate_items) != tuple(EvidenceGate):
        raise Phase7GContractError("candidates must cover ten canonical gates")
    if len(envelope_items) != len(EvidenceGate):
        raise Phase7GContractError("one envelope per canonical gate is required")
    for envelope, candidate in zip(envelope_items, candidate_items, strict=True):
        selected_identity = (
            selected.provider_id,
            selected.dataset_id,
            selected.dataset_version,
            selected.scope_id,
        )
        if (
            envelope.provider_id,
            envelope.dataset_id,
            envelope.dataset_version,
            envelope.scope_id,
        ) != selected_identity or (
            candidate.provider_id,
            candidate.dataset_id,
            candidate.dataset_version,
            candidate.scope_id,
        ) != selected_identity:
            raise Phase7GContractError("provider/dataset/version/scope binding mismatch")
        if (
            candidate.selection_hash != selected.selection_hash
            or candidate.artifact_digest != envelope.artifact_digest
            or candidate.authority_provisioning_hash != authority_record.provisioning_hash
            or candidate.custody_receipt_hash != custody_record.receipt_hash
            or envelope.retrieved_at > verifier_time
            or candidate.observed_at > verifier_time
            or candidate.expires_at <= verifier_time
        ):
            raise Phase7GContractError("stale, future, or swapped evidence candidate")
    return Phase7GFoundationResult(
        candidates=candidate_items,
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    )


def real_external_verification_unavailable(*_args: Any, **_kwargs: Any) -> None:
    raise Phase7GContractError(
        "REAL verification is unavailable: external trust is not provisioned"
    )
