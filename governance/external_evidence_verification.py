"""External evidence verification acceptance foundation; never gate closure."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "external-evidence-verification-acceptance-v1"
TEMPORAL_POLICY_VERSION = "external-verifier-causality-replay-v1"
MAX_EVIDENCE_AGE = dt.timedelta(hours=24)
SHA256 = r"^[0-9a-f]{64}$"
OID = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class ExternalEvidenceVerificationError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderAdapterIdentity(ContractModel):
    """Public adapter identity only. Credentials and secret locators are not representable."""

    version: Literal["provider-adapter-identity-v1"] = "provider-adapter-identity-v1"
    provider_id: str = Field(pattern=OID)
    dataset_id: str = Field(pattern=OID)
    dataset_version: str = Field(pattern=OID)
    adapter_id: str = Field(pattern=OID)
    adapter_release: str = Field(pattern=OID)
    identity_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _hash(self, "identity_hash")
        return self


class VerifierAuthoritySnapshot(ContractModel):
    version: Literal["verifier-authority-snapshot-v1"] = "verifier-authority-snapshot-v1"
    authority_id: str = Field(pattern=OID)
    observer_id: str = Field(pattern=OID)
    captured_at: dt.datetime
    fingerprint: str = Field(pattern=SHA256)
    revocation_checked_at: dt.datetime
    trust_state: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"
    independently_observed: Literal[True] = True
    snapshot_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.captured_at, "captured_at")
        _aware(self.revocation_checked_at, "revocation_checked_at")
        if self.revocation_checked_at < self.captured_at:
            raise ValueError("revocation check predates authority observation")
        _hash(self, "snapshot_hash")
        return self


class ExternalEvidenceReceipt(ContractModel):
    """What the verifier observed; observation is not authentication or acceptance."""

    version: Literal["external-evidence-receipt-v1"] = "external-evidence-receipt-v1"
    gate: EvidenceGate
    adapter_identity_hash: str = Field(pattern=SHA256)
    artifact_digest: str = Field(pattern=SHA256)
    provider_receipt_id: str = Field(pattern=OID)
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


class IndependentVerifierDecision(ContractModel):
    version: Literal["independent-verifier-decision-v1"] = "independent-verifier-decision-v1"
    gate: EvidenceGate
    receipt_hash: str = Field(pattern=SHA256)
    maker_id: str = Field(pattern=OID)
    checker_id: str = Field(pattern=OID)
    authority_snapshot_hash: str = Field(pattern=SHA256)
    made_at: dt.datetime
    checked_at: dt.datetime
    outcome: Literal["CANDIDATE", "REJECT"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def check(self):
        _aware(self.made_at, "made_at")
        _aware(self.checked_at, "checked_at")
        if self.maker_id == self.checker_id or self.checked_at < self.made_at:
            raise ValueError("invalid maker-checker decision")
        _hash(self, "decision_hash")
        return self


class GateVerificationCandidate(ContractModel):
    gate: EvidenceGate
    receipt_hash: str = Field(pattern=SHA256)
    decision_hash: str = Field(pattern=SHA256)
    state: Literal["TECHNICALLY_CHECKED_NOT_TRUSTED"] = "TECHNICALLY_CHECKED_NOT_TRUSTED"
    gate_state: Literal[GateState.OPEN_EXTERNAL] = GateState.OPEN_EXTERNAL
    reason: Literal["EXTERNAL_TRUST_ROOT_NOT_PROVISIONED"] = "EXTERNAL_TRUST_ROOT_NOT_PROVISIONED"


class ExternalVerificationFoundationResult(ContractModel):
    contract_version: Literal["external-evidence-verification-acceptance-v1"] = CONTRACT_VERSION
    temporal_policy_version: Literal["external-verifier-causality-replay-v1"] = TEMPORAL_POLICY_VERSION
    candidates: tuple[GateVerificationCandidate, ...]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    authority_state: Literal["NOT_PROVISIONED"] = "NOT_PROVISIONED"
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"

    @model_validator(mode="after")
    def check(self):
        if tuple(item.gate for item in self.candidates) != tuple(EvidenceGate):
            raise ValueError("candidates must cover canonical gates")
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
    """Construct a validated contract object for adapters and contract tests."""
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(raw.model_dump(mode="json", exclude={hash_field}, warnings=False))
    return expected(**values)


def assess_external_evidence_verification(
    *, adapter: Any, authority: Any, receipts: Any, decisions: Any, verifier_time: dt.datetime,
) -> ExternalVerificationFoundationResult:
    """Validate intake and produce non-closing candidates while external trust is absent."""
    _aware(verifier_time, "verifier_time")
    adapter_record = _revalidate(ProviderAdapterIdentity, adapter, "adapter identity")
    authority_record = _revalidate(VerifierAuthoritySnapshot, authority, "authority snapshot")
    receipt_items = tuple(_revalidate(ExternalEvidenceReceipt, item, "receipt") for item in receipts)
    decision_items = tuple(_revalidate(IndependentVerifierDecision, item, "decision") for item in decisions)
    receipt_by_gate = _canonical(receipt_items, "receipts")
    decision_by_gate = _canonical(decision_items, "decisions")
    nonces: set[str] = set()
    provider_receipts: set[str] = set()
    candidates = []
    for gate in EvidenceGate:
        receipt = receipt_by_gate[gate]
        decision = decision_by_gate[gate]
        if receipt.adapter_identity_hash != adapter_record.identity_hash:
            raise ExternalEvidenceVerificationError("adapter identity binding mismatch")
        if receipt.replay_nonce_digest in nonces or receipt.provider_receipt_id in provider_receipts:
            raise ExternalEvidenceVerificationError("replayed evidence receipt")
        nonces.add(receipt.replay_nonce_digest)
        provider_receipts.add(receipt.provider_receipt_id)
        if receipt.signature_fingerprint != authority_record.fingerprint:
            raise ExternalEvidenceVerificationError("signature fingerprint mismatch")
        if receipt.signature_check != "MATCHED_UNTRUSTED":
            raise ExternalEvidenceVerificationError("signature check did not produce a candidate")
        if not (receipt.observed_at <= decision.made_at <= decision.checked_at <= verifier_time):
            raise ExternalEvidenceVerificationError("verification causality violation")
        if (verifier_time >= receipt.expires_at
                or verifier_time - receipt.observed_at > MAX_EVIDENCE_AGE):
            raise ExternalEvidenceVerificationError("stale external evidence")
        if authority_record.revocation_checked_at > verifier_time:
            raise ExternalEvidenceVerificationError("future revocation observation")
        if decision.receipt_hash != receipt.receipt_hash:
            raise ExternalEvidenceVerificationError("decision receipt binding mismatch")
        if decision.authority_snapshot_hash != authority_record.snapshot_hash:
            raise ExternalEvidenceVerificationError("decision authority binding mismatch")
        if decision.outcome != "CANDIDATE":
            raise ExternalEvidenceVerificationError("rejected evidence cannot become a candidate")
        candidates.append(GateVerificationCandidate(gate=gate, receipt_hash=receipt.receipt_hash,
                                                     decision_hash=decision.decision_hash))
    return ExternalVerificationFoundationResult(
        candidates=tuple(candidates),
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    )


def _canonical(items: tuple[T, ...], label: str) -> dict[EvidenceGate, T]:
    mapped: dict[EvidenceGate, T] = {}
    for item in items:
        if item.gate in mapped:
            raise ExternalEvidenceVerificationError(f"duplicate {label} gate")
        mapped[item.gate] = item
    if set(mapped) != set(EvidenceGate):
        raise ExternalEvidenceVerificationError(f"{label} must cover ten canonical gates")
    return mapped
