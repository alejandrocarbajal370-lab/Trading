"""Fail-closed trust-anchor and authority provisioning contract foundation."""

from __future__ import annotations

import datetime as dt
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.external_provider_foundation import FoundationError, ProvisioningState
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "trust-anchor-authority-contract-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class AuthorityRole(StrEnum):
    MAKER = "MAKER"
    CHECKER = "CHECKER"
    REVIEWER = "REVIEWER"
    AUTHORITY = "AUTHORITY"


class AuthorityCapability(StrEnum):
    ATTEST_PROVISIONING = "ATTEST_PROVISIONING"
    VERIFY_EVIDENCE = "VERIFY_EVIDENCE"
    REVOKE_ANCHOR = "REVOKE_ANCHOR"


class ContractMode(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _id(value: str, label: str) -> None:
    if value != unicodedata.normalize("NFKC", value) or value != value.casefold():
        raise ValueError(f"{label} must be canonical lowercase ASCII")
    if not value.isascii():
        raise ValueError(f"{label} must be canonical lowercase ASCII")


def _utc(value: dt.datetime | None, label: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() != dt.timedelta(0)):
        raise ValueError(f"{label} must use canonical UTC")


class EvidenceReference(_Model):
    reference_id: str = Field(pattern=IDENTIFIER)
    media_type: Literal["application/json", "application/pkix-cert", "application/cbor"]
    digest: str = Field(pattern=SHA256)
    size: int = Field(gt=0)

    @model_validator(mode="after")
    def canonical(self):
        _id(self.reference_id, "reference_id")
        return self


class TrustAnchorIdentity(_Model):
    anchor_id: str = Field(pattern=IDENTIFIER)
    anchor_kind: Literal["X509_CERTIFICATE", "PUBLIC_KEY", "TRANSPARENCY_LOG_ROOT"]
    credential_reference: EvidenceReference
    fingerprint: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self):
        _id(self.anchor_id, "anchor_id")
        _deep(EvidenceReference, self.credential_reference, "credential reference")
        return self


class Approval(_Model):
    role: AuthorityRole
    actor_id: str = Field(pattern=IDENTIFIER)
    approved_at: dt.datetime

    @model_validator(mode="after")
    def canonical(self):
        _id(self.actor_id, "actor_id")
        _utc(self.approved_at, "approved_at")
        return self


class AuthorityContract(_Model):
    contract_version: Literal["trust-anchor-authority-contract-v1"] = CONTRACT_VERSION
    mode: Literal[ContractMode.CONTRACT_TEST_ONLY]
    authority_id: str = Field(pattern=IDENTIFIER)
    trust_anchor: TrustAnchorIdentity
    provider_id: str = Field(pattern=IDENTIFIER)
    gate: EvidenceGate
    scope_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    capabilities: tuple[AuthorityCapability, ...]
    effective_at: dt.datetime
    available_at: dt.datetime
    revoked_at: dt.datetime | None = None
    approvals: tuple[Approval, ...]
    provisioning_state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    contract_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_contract(self):
        for name in ("authority_id", "provider_id", "scope_id", "policy_version"):
            _id(getattr(self, name), name)
        _deep(TrustAnchorIdentity, self.trust_anchor, "trust anchor")
        _utc(self.effective_at, "effective_at")
        _utc(self.available_at, "available_at")
        _utc(self.revoked_at, "revoked_at")
        if self.available_at < self.effective_at:
            raise ValueError("availability precedes effective time")
        if self.revoked_at is not None and self.revoked_at <= self.effective_at:
            raise ValueError("revocation must follow effective time")
        if not self.capabilities or len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be non-empty and unique")
        approvals = tuple(_deep(Approval, item, "approval") for item in self.approvals)
        roles = {item.role for item in approvals}
        if roles != set(AuthorityRole) or len(approvals) != len(AuthorityRole):
            raise ValueError("exactly one approval per required role is required")
        if len({item.actor_id for item in approvals}) != len(approvals):
            raise ValueError("self-approval or maker-checker collapse is forbidden")
        if any(item.approved_at > self.available_at for item in approvals):
            raise ValueError("approval occurs after contract availability")
        _hash(self, "contract_hash")
        return self


class AuthorityRegistryContract(_Model):
    contract_version: Literal["trust-anchor-authority-contract-v1"] = CONTRACT_VERSION
    mode: Literal[ContractMode.CONTRACT_TEST_ONLY]
    authorities: tuple[AuthorityContract, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_registry(self):
        authorities = tuple(
            _deep(AuthorityContract, item, "authority contract") for item in self.authorities
        )
        if not authorities:
            raise ValueError("authority registry cannot be empty")
        if len({item.contract_hash for item in authorities}) != len(authorities):
            raise ValueError("duplicate authority contract")
        for index, left in enumerate(authorities):
            for right in authorities[index + 1 :]:
                subject = (left.authority_id, left.provider_id, left.gate, left.scope_id)
                other = (right.authority_id, right.provider_id, right.gate, right.scope_id)
                if subject == other and _overlap(left, right):
                    raise ValueError("overlapping authority validity windows")
        _hash(self, "registry_hash")
        return self


class ProvisioningObservation(_Model):
    contract: AuthorityContract
    evidence: EvidenceReference
    observed_at: dt.datetime
    verified_at: dt.datetime
    state: Literal["OBSERVED_UNTRUSTED"]
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED]
    independent_verifier: Literal[ProvisioningState.NOT_PROVISIONED]
    gate_state: Literal[GateState.OPEN_EXTERNAL]
    observation_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_observation(self):
        contract = _deep(AuthorityContract, self.contract, "authority contract")
        _deep(EvidenceReference, self.evidence, "provisioning evidence")
        _utc(self.observed_at, "observed_at")
        _utc(self.verified_at, "verified_at")
        if self.observed_at < contract.effective_at:
            raise ValueError("evidence predates authority effectiveness")
        if self.verified_at < self.observed_at:
            raise ValueError("verification precedes observation")
        if contract.revoked_at is not None and self.verified_at >= contract.revoked_at:
            raise ValueError("authority was revoked at verifier time")
        _hash(self, "observation_hash")
        return self


def build_contract_test_authority(**values: Any) -> AuthorityContract:
    """Build metadata for tests only; it is never evidence of REAL provisioning."""
    values["mode"] = ContractMode.CONTRACT_TEST_ONLY
    values["provisioning_state"] = ProvisioningState.CONTRACT_TEST_ONLY
    return _seal(AuthorityContract, "contract_hash", **values)


def build_contract_test_registry(*authorities: Any) -> AuthorityRegistryContract:
    canonical = tuple(_deep(AuthorityContract, item, "authority contract") for item in authorities)
    return _seal(
        AuthorityRegistryContract,
        "registry_hash",
        contract_version=CONTRACT_VERSION,
        mode=ContractMode.CONTRACT_TEST_ONLY,
        authorities=canonical,
    )


def observe_contract_test_provisioning(
    contract: Any,
    evidence: Any,
    *,
    expected_contract_hash: str,
    observed_at: dt.datetime,
    verified_at: dt.datetime,
) -> ProvisioningObservation:
    canonical = _deep(AuthorityContract, contract, "authority contract")
    if canonical.contract_hash != expected_contract_hash:
        raise FoundationError("authority contract binding mismatch")
    reference = _deep(EvidenceReference, evidence, "provisioning evidence")
    return _seal(
        ProvisioningObservation,
        "observation_hash",
        contract=canonical,
        evidence=reference,
        observed_at=observed_at,
        verified_at=verified_at,
        state="OBSERVED_UNTRUSTED",
        trust_root=ProvisioningState.NOT_PROVISIONED,
        independent_verifier=ProvisioningState.NOT_PROVISIONED,
        gate_state=GateState.OPEN_EXTERNAL,
    )


def verify_real_authority_provisioning(*, evidence: Any, registry: Any = None) -> None:
    del evidence, registry
    raise FoundationError("REAL trust-anchor and authority provisioning is NOT_PROVISIONED")


T = TypeVar("T", bound=BaseModel)


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise FoundationError("model contains undeclared fields")
        value = value.model_dump(mode="json", warnings=False)
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _deep(expected: type[T], value: Any, label: str) -> T:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FoundationError(f"invalid {label}") from exc


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(raw.model_dump(mode="json", exclude={hash_field}, warnings=False))
    return expected(**values)


def _hash(value: BaseModel, field: str) -> None:
    expected = typed_hash(value.model_dump(mode="json", exclude={field}, warnings=False))
    if getattr(value, field) != expected:
        raise ValueError(f"{field} mismatch")


def _overlap(left: AuthorityContract, right: AuthorityContract) -> bool:
    left_end = left.revoked_at or dt.datetime.max.replace(tzinfo=dt.UTC)
    right_end = right.revoked_at or dt.datetime.max.replace(tzinfo=dt.UTC)
    return left.effective_at < right_end and right.effective_at < left_end
