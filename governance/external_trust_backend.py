"""External trust-backend provisioning contract; no REAL backend is provisioned."""

from __future__ import annotations

import datetime as dt
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.ibkr_external_attestation import (
    ExternalAuthenticityAssessment,
    ObservationAttestationBinding,
    ProvisioningState,
)
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "external-trust-backend-provisioning-v1"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class TrustBackendError(ValueError):
    """An untrusted value failed the provisioning boundary."""


class PrincipalRole(StrEnum):
    PROVISIONING_MAKER = "PROVISIONING_MAKER"
    PROVISIONING_CHECKER = "PROVISIONING_CHECKER"
    ATTESTER = "ATTESTER"
    VERIFIER = "VERIFIER"
    AUTHORITY = "AUTHORITY"
    REVOCATION_OWNER = "REVOCATION_OWNER"


class ContractState(StrEnum):
    CONTRACT_TEST_VALIDATED = "CONTRACT_TEST_VALIDATED"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        failed = False
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - pydantic may retain rejected secrets
            failed = True
        if failed:
            raise TrustBackendError("invalid trust backend value")

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        return cls._safe_validate("model_validate", obj, kwargs)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any):
        return cls._safe_validate("model_validate_json", json_data, kwargs)

    @classmethod
    def model_validate_strings(cls, obj: Any, **kwargs: Any):
        return cls._safe_validate("model_validate_strings", obj, kwargs)

    @classmethod
    def _safe_validate(cls, route: str, value: Any, kwargs: dict[str, Any]):
        failed = False
        try:
            result = getattr(super(), route)(value, **kwargs)
        except BaseException:  # noqa: BLE001
            failed = True
            result = None
        if failed:
            raise TrustBackendError("invalid trust backend value")
        return result


class ExternalBackendIdentity(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    backend_id: str = Field(pattern=IDENTIFIER)
    provider: Literal["provider.ibkr"]
    deployment_identity_digest: str = Field(pattern=SHA256)
    endpoint_reference_digest: str = Field(pattern=SHA256)
    configuration_digest: str = Field(pattern=SHA256)
    operating_mode: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    backend_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_identity(self):
        _identifier(self.backend_id)
        _hash(self, "backend_hash")
        return self


class ExternalPrincipal(_Model):
    principal_id: str = Field(pattern=IDENTIFIER)
    role: PrincipalRole
    external_identity_digest: str = Field(pattern=SHA256)
    authority_reference_digest: str = Field(pattern=SHA256)
    effective_at: dt.datetime
    available_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    principal_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_principal(self):
        _identifier(self.principal_id)
        for name in ("effective_at", "available_at", "expires_at", "revoked_at"):
            _utc(getattr(self, name))
        if not self.effective_at <= self.available_at < self.expires_at:
            raise ValueError("invalid principal lifecycle")
        if self.revoked_at is not None and self.revoked_at <= self.available_at:
            raise ValueError("invalid revocation lifecycle")
        _hash(self, "principal_hash")
        return self


class ProvisioningEvidenceManifest(_Model):
    backend_hash: str = Field(pattern=SHA256)
    provider: Literal["provider.ibkr"]
    security_master_id: Literal["security.us.msft.xnas"]
    request_hash: str = Field(pattern=SHA256)
    observation_binding_hash: str = Field(pattern=SHA256)
    authenticity_assessment_hash: str = Field(pattern=SHA256)
    entitlement_reference_hash: str = Field(pattern=SHA256)
    trust_anchor_reference_digest: str = Field(pattern=SHA256)
    authority_registry_reference_digest: str = Field(pattern=SHA256)
    replay_service_reference_digest: str = Field(pattern=SHA256)
    custody_evidence_reference_digest: str = Field(pattern=SHA256)
    worm_evidence_reference_digest: str = Field(pattern=SHA256)
    legal_approval_reference_digest: str = Field(pattern=SHA256)
    principals: tuple[ExternalPrincipal, ...]
    effective_at: dt.datetime
    expires_at: dt.datetime
    mode: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    manifest_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_manifest(self):
        _utc(self.effective_at)
        _utc(self.expires_at)
        if self.expires_at <= self.effective_at:
            raise ValueError("invalid manifest lifecycle")
        principals = tuple(_deep(ExternalPrincipal, value) for value in self.principals)
        if tuple(item.role for item in principals) != tuple(PrincipalRole):
            raise ValueError("principals must be exact and ordered")
        identities = {item.external_identity_digest for item in principals}
        if len(identities) != len(principals):
            raise ValueError("external principals must be independent")
        _hash(self, "manifest_hash")
        return self


class ProvisioningContractAssessment(_Model):
    backend_hash: str = Field(pattern=SHA256)
    manifest_hash: str = Field(pattern=SHA256)
    observation_binding_hash: str = Field(pattern=SHA256)
    authenticity_assessment_hash: str = Field(pattern=SHA256)
    assessed_at: dt.datetime
    state: Literal[ContractState.CONTRACT_TEST_VALIDATED]
    backend_real: Literal[ProvisioningState.NOT_PROVISIONED]
    trust_anchor_real: Literal[ProvisioningState.NOT_PROVISIONED]
    authority_registry_real: Literal[ProvisioningState.NOT_PROVISIONED]
    entitlement_real: Literal[ProvisioningState.NOT_PROVISIONED]
    independent_verifier_real: Literal[ProvisioningState.NOT_PROVISIONED]
    replay_custody_worm_legal_real: Literal[ProvisioningState.NOT_PROVISIONED]
    provider_admission_real: Literal[ProvisioningState.NOT_PROVISIONED]
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
        _utc(self.assessed_at)
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError("all gates must remain open")
        _hash(self, "assessment_hash")
        return self


def validate_contract_test_provisioning(
    *, backend: Any, manifest: Any, observation_binding: Any,
    authenticity_assessment: Any, assessed_at: dt.datetime
) -> ProvisioningContractAssessment:
    """Validate only contract shape and exact lineage; never activate external trust."""
    try:
        service = _deep(ExternalBackendIdentity, backend)
        record = _deep(ProvisioningEvidenceManifest, manifest)
        binding = _deep(ObservationAttestationBinding, observation_binding)
        authenticity = _deep(ExternalAuthenticityAssessment, authenticity_assessment)
        _utc(assessed_at)
        if service.operating_mode is not ProvisioningState.CONTRACT_TEST_ONLY:
            raise ValueError("unsupported backend mode")
        if record.backend_hash != service.backend_hash:
            raise ValueError("backend binding mismatch")
        if (record.provider, record.security_master_id, record.request_hash) != (
            binding.provider, binding.security_master_id, binding.request_hash
        ):
            raise ValueError("provider, security or request swap")
        if record.observation_binding_hash != binding.binding_hash:
            raise ValueError("observation binding mismatch")
        if record.authenticity_assessment_hash != authenticity.assessment_hash:
            raise ValueError("authenticity assessment mismatch")
        if authenticity.binding_hash != binding.binding_hash:
            raise ValueError("cross-assessment binding mismatch")
        if record.entitlement_reference_hash != authenticity.entitlement_hash:
            raise ValueError("entitlement binding mismatch")
        if not record.effective_at <= assessed_at < record.expires_at:
            raise ValueError("manifest unavailable at assessment time")
        for principal in record.principals:
            if not principal.available_at <= assessed_at < principal.expires_at:
                raise ValueError("principal unavailable at assessment time")
            if principal.revoked_at is not None and assessed_at >= principal.revoked_at:
                raise ValueError("principal revoked at assessment time")
        return _seal(
            ProvisioningContractAssessment, "assessment_hash",
            backend_hash=service.backend_hash, manifest_hash=record.manifest_hash,
            observation_binding_hash=binding.binding_hash,
            authenticity_assessment_hash=authenticity.assessment_hash, assessed_at=assessed_at,
            state=ContractState.CONTRACT_TEST_VALIDATED,
            backend_real=ProvisioningState.NOT_PROVISIONED,
            trust_anchor_real=ProvisioningState.NOT_PROVISIONED,
            authority_registry_real=ProvisioningState.NOT_PROVISIONED,
            entitlement_real=ProvisioningState.NOT_PROVISIONED,
            independent_verifier_real=ProvisioningState.NOT_PROVISIONED,
            replay_custody_worm_legal_real=ProvisioningState.NOT_PROVISIONED,
            provider_admission_real=ProvisioningState.NOT_PROVISIONED,
            gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
            real_route="QVM_NOT_READY", global_readiness="INSUFFICIENT_REAL_DATA",
            trade_decision="NO_TRADE", signals_generated=False,
            live_execution_enabled=False, backtesting="NOT_AUTHORIZED",
        )
    except BaseException as exc:  # noqa: BLE001
        if type(exc) is TrustBackendError:
            message = str(exc)
        else:
            message = "invalid trust backend provisioning"
        raise TrustBackendError(message) from None


def provision_real_external_trust_backend(*args: Any, **kwargs: Any) -> None:
    """The repository has no backend, signer, keys, registry or verifier to inject."""
    del args, kwargs
    raise TrustBackendError("REAL external trust backend is NOT_PROVISIONED")


T = TypeVar("T", bound=BaseModel)


def seal_contract_test(expected: type[T], hash_field: str, **values: Any) -> T:
    failed = False
    try:
        if _SEAL_FIELDS.get(expected) != hash_field:
            raise TypeError("unsupported model")
        result = _seal(expected, hash_field, **values)
    except BaseException:  # noqa: BLE001
        failed = True
        result = None
    if failed:
        raise TrustBackendError("invalid contract-test trust backend value")
    return result


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    payload = raw.model_dump(mode="json", exclude={hash_field}, warnings=False)
    return expected(**values, **{hash_field: typed_hash(payload)})


def _deep(expected: type[T], value: Any) -> T:
    try:
        if isinstance(value, BaseModel):
            if set(value.__dict__) - set(type(value).model_fields):
                raise ValueError("undeclared fields")
            value = value.model_dump(mode="json", warnings=False)
        elif isinstance(value, str):
            value = json.loads(value)
        elif not isinstance(value, dict):
            raise TypeError("unsupported value")
        primitive = json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return expected.model_validate(primitive)
    except BaseException:  # noqa: BLE001
        raise TrustBackendError("invalid trust backend value") from None


def _identifier(value: str) -> None:
    if not value.isascii() or value != value.casefold() or value != unicodedata.normalize("NFKC", value):
        raise ValueError("identifier must be canonical lowercase ASCII")


def _utc(value: dt.datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() != dt.timedelta(0)):
        raise ValueError("timestamp must be canonical UTC")


def _hash(value: BaseModel, field: str) -> None:
    if getattr(value, field) != typed_hash(value.model_dump(mode="json", exclude={field}, warnings=False)):
        raise ValueError("hash mismatch")


_SEAL_FIELDS: dict[type[BaseModel], str] = {
    ExternalBackendIdentity: "backend_hash",
    ExternalPrincipal: "principal_hash",
    ProvisioningEvidenceManifest: "manifest_hash",
    ProvisioningContractAssessment: "assessment_hash",
}
