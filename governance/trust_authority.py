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
    identity_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def canonical(self):
        _id(self.anchor_id, "anchor_id")
        _deep(EvidenceReference, self.credential_reference, "credential reference")
        _hash(self, "identity_hash")
        return self


class TrustAnchorRegistration(_Model):
    """Independent temporal registration of immutable trust-anchor material."""

    contract_version: Literal["trust-anchor-authority-contract-v1"] = CONTRACT_VERSION
    mode: Literal[ContractMode.CONTRACT_TEST_ONLY]
    anchor: TrustAnchorIdentity
    provider_id: str = Field(pattern=IDENTIFIER)
    gate: EvidenceGate
    scope_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    effective_at: dt.datetime
    available_at: dt.datetime
    revoked_at: dt.datetime | None = None
    registration_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_registration(self):
        for name in ("provider_id", "scope_id", "policy_version"):
            _id(getattr(self, name), name)
        _deep(TrustAnchorIdentity, self.anchor, "trust anchor identity")
        _validate_lifecycle(self.effective_at, self.available_at, self.revoked_at, "anchor")
        _hash(self, "registration_hash")
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
    trust_anchor_identity_hash: str = Field(pattern=SHA256)
    trust_anchor_registration_hash: str = Field(pattern=SHA256)
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
        _validate_lifecycle(self.effective_at, self.available_at, self.revoked_at, "authority")
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
    anchor_registrations: tuple[TrustAnchorRegistration, ...]
    authorities: tuple[AuthorityContract, ...]
    registry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_registry(self):
        registrations = tuple(
            _deep(TrustAnchorRegistration, item, "trust anchor registration")
            for item in self.anchor_registrations
        )
        authorities = tuple(
            _deep(AuthorityContract, item, "authority contract") for item in self.authorities
        )
        if not authorities or not registrations:
            raise ValueError("authority and anchor registries cannot be empty")
        if len({item.registration_hash for item in registrations}) != len(registrations):
            raise ValueError("duplicate anchor registration")
        for index, left in enumerate(registrations):
            for right in registrations[index + 1 :]:
                subject = (left.provider_id, left.gate, left.scope_id)
                other = (right.provider_id, right.gate, right.scope_id)
                if subject == other and _overlap(left, right):
                    raise ValueError("overlapping anchor registration validity windows")
        if len({item.contract_hash for item in authorities}) != len(authorities):
            raise ValueError("duplicate authority contract")
        registrations_by_hash = {item.registration_hash: item for item in registrations}
        for authority in authorities:
            registration = registrations_by_hash.get(authority.trust_anchor_registration_hash)
            if registration is None:
                raise ValueError("authority references an unregistered trust anchor lifecycle")
            if authority.trust_anchor_identity_hash != registration.anchor.identity_hash:
                raise ValueError("authority trust anchor identity binding mismatch")
            if (
                authority.provider_id,
                authority.gate,
                authority.scope_id,
                authority.policy_version,
            ) != (
                registration.provider_id,
                registration.gate,
                registration.scope_id,
                registration.policy_version,
            ):
                raise ValueError("authority trust anchor scope or policy binding mismatch")
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
    anchor_registration: TrustAnchorRegistration
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
        registration = _deep(
            TrustAnchorRegistration, self.anchor_registration, "trust anchor registration"
        )
        _match_authority_anchor(contract, registration)
        _deep(EvidenceReference, self.evidence, "provisioning evidence")
        _utc(self.observed_at, "observed_at")
        _utc(self.verified_at, "verified_at")
        if self.observed_at < contract.available_at:
            raise ValueError("evidence predates authority availability")
        if self.observed_at < registration.available_at:
            raise ValueError("evidence predates anchor availability")
        if self.verified_at < self.observed_at:
            raise ValueError("verification precedes observation")
        if contract.revoked_at is not None and self.verified_at >= contract.revoked_at:
            raise ValueError("authority was revoked at verifier time")
        if registration.revoked_at is not None and self.verified_at >= registration.revoked_at:
            raise ValueError("trust anchor was revoked at verifier time")
        _hash(self, "observation_hash")
        return self


def build_contract_test_authority(**values: Any) -> AuthorityContract:
    """Build metadata for tests only; it is never evidence of REAL provisioning."""
    values["mode"] = ContractMode.CONTRACT_TEST_ONLY
    values["provisioning_state"] = ProvisioningState.CONTRACT_TEST_ONLY
    return _seal(AuthorityContract, "contract_hash", **values)


def build_trust_anchor_identity(**values: Any) -> TrustAnchorIdentity:
    """Seal immutable, content-addressed anchor identity and public material references."""
    return _seal(TrustAnchorIdentity, "identity_hash", **values)


def build_contract_test_anchor_registration(**values: Any) -> TrustAnchorRegistration:
    """Build an independently sealed anchor lifecycle for contract tests only."""
    values["mode"] = ContractMode.CONTRACT_TEST_ONLY
    return _seal(TrustAnchorRegistration, "registration_hash", **values)


def build_contract_test_registry(
    *authorities: Any, anchor_registrations: tuple[Any, ...]
) -> AuthorityRegistryContract:
    canonical = tuple(_deep(AuthorityContract, item, "authority contract") for item in authorities)
    anchors = tuple(
        _deep(TrustAnchorRegistration, item, "trust anchor registration")
        for item in anchor_registrations
    )
    return _seal(
        AuthorityRegistryContract,
        "registry_hash",
        contract_version=CONTRACT_VERSION,
        mode=ContractMode.CONTRACT_TEST_ONLY,
        anchor_registrations=anchors,
        authorities=canonical,
    )


def observe_contract_test_provisioning(
    contract: Any,
    anchor_registration: Any,
    evidence: Any,
    *,
    expected_contract_hash: str,
    expected_anchor_registration_hash: str,
    observed_at: dt.datetime,
    verified_at: dt.datetime,
) -> ProvisioningObservation:
    canonical = _deep(AuthorityContract, contract, "authority contract")
    if canonical.contract_hash != expected_contract_hash:
        raise FoundationError("authority contract binding mismatch")
    registration = _deep(TrustAnchorRegistration, anchor_registration, "trust anchor registration")
    if registration.registration_hash != expected_anchor_registration_hash:
        raise FoundationError("trust anchor registration binding mismatch")
    try:
        _match_authority_anchor(canonical, registration)
    except ValueError as exc:
        raise FoundationError("authority and trust anchor binding mismatch") from exc
    reference = _deep(EvidenceReference, evidence, "provisioning evidence")
    return _seal(
        ProvisioningObservation,
        "observation_hash",
        contract=canonical,
        anchor_registration=registration,
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
    values[hash_field] = typed_hash(
        raw.model_dump(mode="json", exclude={hash_field}, warnings=False)
    )
    return expected(**values)


def _hash(value: BaseModel, field: str) -> None:
    expected = typed_hash(value.model_dump(mode="json", exclude={field}, warnings=False))
    if getattr(value, field) != expected:
        raise ValueError(f"{field} mismatch")


def _validate_lifecycle(
    effective_at: dt.datetime,
    available_at: dt.datetime,
    revoked_at: dt.datetime | None,
    label: str,
) -> None:
    _utc(effective_at, f"{label} effective_at")
    _utc(available_at, f"{label} available_at")
    _utc(revoked_at, f"{label} revoked_at")
    if available_at < effective_at:
        raise ValueError(f"{label} availability precedes effective time")
    if revoked_at is not None and revoked_at <= available_at:
        raise ValueError(f"{label} revocation must follow effectiveness and availability")


def _match_authority_anchor(
    authority: AuthorityContract, registration: TrustAnchorRegistration
) -> None:
    if (
        authority.trust_anchor_registration_hash != registration.registration_hash
        or authority.trust_anchor_identity_hash != registration.anchor.identity_hash
    ):
        raise ValueError("authority trust anchor hash binding mismatch")
    if (
        authority.provider_id,
        authority.gate,
        authority.scope_id,
        authority.policy_version,
    ) != (
        registration.provider_id,
        registration.gate,
        registration.scope_id,
        registration.policy_version,
    ):
        raise ValueError("authority trust anchor scope or policy binding mismatch")


def _overlap(left: Any, right: Any) -> bool:
    left_end = left.revoked_at or dt.datetime.max.replace(tzinfo=dt.UTC)
    right_end = right.revoked_at or dt.datetime.max.replace(tzinfo=dt.UTC)
    return left.effective_at < right_end and right.effective_at < left_end
