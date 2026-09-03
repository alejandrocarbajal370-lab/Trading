"""Contract-test verification and admission of externally supplied trust evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.external_provider_foundation import FoundationError, ProvisioningState
from governance.phase7e import EvidenceGate, GateState
from governance.trust_authority import (
    AuthorityCapability,
    AuthorityContract,
    AuthorityRegistryContract,
    TrustAnchorRegistration,
)

CONTRACT_VERSION = "external-trust-anchor-admission-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class AdmissionState(StrEnum):
    CONTRACT_TEST_VERIFIED = "CONTRACT_TEST_VERIFIED"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExternalTrustEvidence(_Model):
    contract_version: Literal["external-trust-anchor-admission-v1"] = CONTRACT_VERSION
    mode: Literal["CONTRACT_TEST_ONLY"]
    evidence_id: str = Field(pattern=IDENTIFIER)
    provider_id: str = Field(pattern=IDENTIFIER)
    gate: EvidenceGate
    scope_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    authority_contract_hash: str = Field(pattern=SHA256)
    anchor_registration_hash: str = Field(pattern=SHA256)
    payload_digest: str = Field(pattern=SHA256)
    payload_size: int = Field(gt=0)
    observed_at: dt.datetime
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_evidence(self):
        for value in (self.evidence_id, self.provider_id, self.scope_id, self.policy_version):
            if not value.isascii() or value != value.casefold():
                raise ValueError("identifiers must be canonical lowercase ASCII")
        _utc(self.observed_at, "observed_at")
        _hash(self, "evidence_hash")
        return self


class ContractTestVerifier(_Model):
    verifier_id: str = Field(pattern=IDENTIFIER)
    authority_contract_hash: str = Field(pattern=SHA256)
    registry_hash: str = Field(pattern=SHA256)
    mode: Literal["CONTRACT_TEST_ONLY"]
    verifier_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_verifier(self):
        if not self.verifier_id.isascii() or self.verifier_id != self.verifier_id.casefold():
            raise ValueError("verifier_id must be canonical lowercase ASCII")
        _hash(self, "verifier_hash")
        return self


class AdmissionDecision(_Model):
    evidence: ExternalTrustEvidence
    verifier: ContractTestVerifier
    registry_hash: str = Field(pattern=SHA256)
    authority_contract_hash: str = Field(pattern=SHA256)
    anchor_registration_hash: str = Field(pattern=SHA256)
    verified_at: dt.datetime
    state: Literal[AdmissionState.CONTRACT_TEST_VERIFIED]
    gate_state: Literal[GateState.OPEN_EXTERNAL]
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED]
    independent_verifier: Literal[ProvisioningState.NOT_PROVISIONED]
    real_provider_admission: Literal[ProvisioningState.NOT_PROVISIONED]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]
    decision_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_decision(self):
        _deep(ExternalTrustEvidence, self.evidence, "external trust evidence")
        _deep(ContractTestVerifier, self.verifier, "contract-test verifier")
        _utc(self.verified_at, "verified_at")
        if self.verified_at < self.evidence.observed_at:
            raise ValueError("verification precedes observation")
        _hash(self, "decision_hash")
        return self


def observe_external_trust_evidence(
    *,
    evidence_id: str,
    provider_id: str,
    gate: EvidenceGate,
    scope_id: str,
    policy_version: str,
    authority_contract_hash: str,
    anchor_registration_hash: str,
    payload: bytes,
    observed_at: dt.datetime,
) -> ExternalTrustEvidence:
    """Content-address caller-supplied bytes without claiming external trust."""
    if not isinstance(payload, bytes) or not payload:
        raise FoundationError("external trust payload must be non-empty bytes")
    return _seal(
        ExternalTrustEvidence,
        "evidence_hash",
        mode="CONTRACT_TEST_ONLY",
        evidence_id=evidence_id,
        provider_id=provider_id,
        gate=gate,
        scope_id=scope_id,
        policy_version=policy_version,
        authority_contract_hash=authority_contract_hash,
        anchor_registration_hash=anchor_registration_hash,
        payload_digest=hashlib.sha256(payload).hexdigest(),
        payload_size=len(payload),
        observed_at=observed_at,
    )


def build_contract_test_verifier(
    *, verifier_id: str, authority_contract_hash: str, registry_hash: str
) -> ContractTestVerifier:
    return _seal(
        ContractTestVerifier,
        "verifier_hash",
        verifier_id=verifier_id,
        authority_contract_hash=authority_contract_hash,
        registry_hash=registry_hash,
        mode="CONTRACT_TEST_ONLY",
    )


def verify_and_admit_contract_test_evidence(
    evidence: Any,
    *,
    payload: bytes,
    verifier: Any,
    registry: Any,
    expected_registry_hash: str,
    expected_verifier_hash: str,
    verified_at: dt.datetime,
) -> AdmissionDecision:
    """Verify exact bindings and historical lifecycles; never admit a REAL provider."""
    item = _deep(ExternalTrustEvidence, evidence, "external trust evidence")
    actor = _deep(ContractTestVerifier, verifier, "contract-test verifier")
    book = _deep(AuthorityRegistryContract, registry, "authority registry")
    if book.registry_hash != expected_registry_hash or actor.registry_hash != book.registry_hash:
        raise FoundationError("authority registry binding mismatch")
    if actor.verifier_hash != expected_verifier_hash:
        raise FoundationError("verifier binding mismatch")
    if not isinstance(payload, bytes) or len(payload) != item.payload_size:
        raise FoundationError("external trust payload size mismatch")
    if hashlib.sha256(payload).hexdigest() != item.payload_digest:
        raise FoundationError("external trust payload digest mismatch")
    authority = next(
        (x for x in book.authorities if x.contract_hash == item.authority_contract_hash), None
    )
    anchor = next(
        (
            x
            for x in book.anchor_registrations
            if x.registration_hash == item.anchor_registration_hash
        ),
        None,
    )
    if authority is None or anchor is None:
        raise FoundationError("evidence references authority or anchor outside registry")
    if actor.authority_contract_hash != authority.contract_hash:
        raise FoundationError("verifier authority binding mismatch")
    _validate_bindings(item, authority, anchor)
    _utc(verified_at, "verified_at")
    if item.observed_at < max(authority.available_at, anchor.available_at):
        raise FoundationError("evidence predates authority or anchor availability")
    if verified_at < item.observed_at:
        raise FoundationError("verification precedes observation")
    for label, lifecycle in (("authority", authority), ("anchor", anchor)):
        if lifecycle.revoked_at is not None and verified_at >= lifecycle.revoked_at:
            raise FoundationError(f"{label} revoked at verifier time")
    return _seal(
        AdmissionDecision,
        "decision_hash",
        evidence=item,
        verifier=actor,
        registry_hash=book.registry_hash,
        authority_contract_hash=authority.contract_hash,
        anchor_registration_hash=anchor.registration_hash,
        verified_at=verified_at,
        state=AdmissionState.CONTRACT_TEST_VERIFIED,
        gate_state=GateState.OPEN_EXTERNAL,
        trust_root=ProvisioningState.NOT_PROVISIONED,
        independent_verifier=ProvisioningState.NOT_PROVISIONED,
        real_provider_admission=ProvisioningState.NOT_PROVISIONED,
        trade_decision="NO_TRADE",
        signals_generated=False,
        live_execution_enabled=False,
        backtesting="NOT_AUTHORIZED",
    )


def verify_and_admit_real_external_evidence(**values: Any) -> None:
    del values
    raise FoundationError("REAL external trust verification and admission is NOT_PROVISIONED")


def _validate_bindings(
    item: ExternalTrustEvidence, authority: AuthorityContract, anchor: TrustAnchorRegistration
) -> None:
    if AuthorityCapability.VERIFY_EVIDENCE not in authority.capabilities:
        raise FoundationError("authority lacks evidence verification capability")
    expected = (authority.provider_id, authority.gate, authority.scope_id, authority.policy_version)
    if expected != (item.provider_id, item.gate, item.scope_id, item.policy_version):
        raise FoundationError("cross-gate or scope evidence binding mismatch")
    if authority.trust_anchor_registration_hash != anchor.registration_hash:
        raise FoundationError("authority anchor lifecycle binding mismatch")
    if item.anchor_registration_hash != anchor.registration_hash:
        raise FoundationError("evidence anchor lifecycle binding mismatch")


T = TypeVar("T", bound=BaseModel)


def _deep(expected: type[T], value: Any, label: str) -> T:
    try:
        if isinstance(value, BaseModel):
            if set(value.__dict__) - set(type(value).model_fields):
                raise ValueError("undeclared model fields")
            value = value.model_dump(mode="json", warnings=False)
        if isinstance(value, str):
            value = json.loads(value)
        return expected.model_validate(json.loads(json.dumps(value, sort_keys=True)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FoundationError(f"invalid {label}") from exc


def _seal(expected: type[T], field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{field: "0" * 64})
    values[field] = typed_hash(raw.model_dump(mode="json", exclude={field}, warnings=False))
    return expected(**values)


def _hash(value: BaseModel, field: str) -> None:
    if getattr(value, field) != typed_hash(
        value.model_dump(mode="json", exclude={field}, warnings=False)
    ):
        raise ValueError(f"{field} mismatch")


def _utc(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{label} must use canonical UTC")
