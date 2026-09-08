"""Governed observation policy and provider-admission aggregation contract.

This module can validate synthetic contract graphs.  It cannot close a REAL
gate or admit a provider because no external verifier or evidence backend is
provisioned in this repository.
"""

from __future__ import annotations

import datetime as dt
import json
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.external_trust_backend import (
    PrincipalRole,
    ProvisioningContractAssessment,
    ProvisioningEvidenceManifest,
)
from governance.ibkr_external_attestation import ProvisioningState
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "provider-admission-evidence-aggregation-v2"
POLICY_VERSION = "governed-sufficient-observations-v2"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class AdmissionAggregationError(ValueError):
    """Untrusted aggregation input failed closed."""


class AggregationState(StrEnum):
    CONTRACT_TEST_VALIDATED = "CONTRACT_TEST_VALIDATED"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001 - rejected input may contain secrets
            raise AdmissionAggregationError("invalid admission aggregation value") from None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        try:
            return super().model_validate(obj, **kwargs)
        except BaseException:  # noqa: BLE001
            raise AdmissionAggregationError("invalid admission aggregation value") from None

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any):
        try:
            return super().model_validate_json(json_data, **kwargs)
        except BaseException:  # noqa: BLE001
            raise AdmissionAggregationError("invalid admission aggregation value") from None


class SufficientObservationPolicy(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    policy_version: Literal[POLICY_VERSION] = POLICY_VERSION
    policy_id: str = Field(pattern=IDENTIFIER)
    provider: Literal["provider.ibkr"]
    adapter_id: str = Field(pattern=IDENTIFIER)
    dataset_id: str = Field(pattern=IDENTIFIER)
    security_master_id: Literal["security.us.msft.xnas"]
    route_id: str = Field(pattern=IDENTIFIER)
    minimum_distinct_observations: int = Field(ge=2, le=1000)
    minimum_observation_span: dt.timedelta
    maximum_observation_age: dt.timedelta
    maximum_verifier_skew: dt.timedelta
    required_gates: tuple[EvidenceGate, ...]
    approved_at: dt.datetime
    effective_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    authority_registry_reference_digest: str = Field(pattern=SHA256)
    authority_principal_hash: str = Field(pattern=SHA256)
    revocation_owner_principal_hash: str = Field(pattern=SHA256)
    revocation_context_digest: str = Field(pattern=SHA256)
    policy_authority_reference_digest: str = Field(pattern=SHA256)
    rationale_digest: str = Field(pattern=SHA256)
    policy_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_policy(self):
        _identifier(self.policy_id)
        _identifier(self.adapter_id)
        _identifier(self.dataset_id)
        _identifier(self.route_id)
        for value in (self.approved_at, self.effective_at, self.expires_at, self.revoked_at):
            if value is not None:
                _utc(value)
        if not self.approved_at <= self.effective_at < self.expires_at:
            raise ValueError("invalid policy lifecycle")
        if self.revoked_at is not None and self.revoked_at <= self.approved_at:
            raise ValueError("invalid policy revocation lifecycle")
        expected_context = typed_hash({
            "contract": CONTRACT_VERSION,
            "authority_registry": self.authority_registry_reference_digest,
            "authority_principal": self.authority_principal_hash,
            "revocation_owner_principal": self.revocation_owner_principal_hash,
        })
        if self.revocation_context_digest != expected_context:
            raise ValueError("invalid policy revocation context")
        if self.required_gates != tuple(EvidenceGate):
            raise ValueError("policy must require all canonical gates exactly once")
        if self.minimum_observation_span <= dt.timedelta(0):
            raise ValueError("observation span must be positive")
        if self.maximum_observation_age < self.minimum_observation_span:
            raise ValueError("observation age must cover the required span")
        if not dt.timedelta(0) <= self.maximum_verifier_skew <= dt.timedelta(minutes=5):
            raise ValueError("invalid verifier skew")
        _hash(self, "policy_hash")
        return self


class BoundObservationEvidence(_Model):
    observation_id: str = Field(pattern=IDENTIFIER)
    provider: Literal["provider.ibkr"]
    adapter_id: str = Field(pattern=IDENTIFIER)
    dataset_id: str = Field(pattern=IDENTIFIER)
    security_master_id: Literal["security.us.msft.xnas"]
    con_id: int = Field(gt=0)
    request_hash: str = Field(pattern=SHA256)
    observation_binding_hash: str = Field(pattern=SHA256)
    authenticity_assessment_hash: str = Field(pattern=SHA256)
    provisioning_assessment_hash: str = Field(pattern=SHA256)
    entitlement_reference_hash: str = Field(pattern=SHA256)
    route_id: str = Field(pattern=IDENTIFIER)
    observed_at: dt.datetime
    authenticated_at: dt.datetime
    verifier_time: dt.datetime
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    lineage_digest: str = Field(pattern=SHA256)
    custody_receipt_digest: str = Field(pattern=SHA256)
    replay_service_reference_digest: str = Field(pattern=SHA256)
    custody_evidence_reference_digest: str = Field(pattern=SHA256)
    worm_evidence_reference_digest: str = Field(pattern=SHA256)
    legal_approval_reference_digest: str = Field(pattern=SHA256)
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_observation(self):
        for value in (self.observation_id, self.adapter_id, self.dataset_id, self.route_id):
            _identifier(value)
        for value in (self.observed_at, self.authenticated_at, self.verifier_time):
            _utc(value)
        if not self.observed_at <= self.authenticated_at <= self.verifier_time:
            raise ValueError("invalid observation chronology")
        _hash(self, "evidence_hash")
        return self


class GateEvidenceBinding(_Model):
    gate: EvidenceGate
    provider: Literal["provider.ibkr"]
    dataset_id: str = Field(pattern=IDENTIFIER)
    security_master_id: Literal["security.us.msft.xnas"]
    con_id: int = Field(gt=0)
    request_hash: str = Field(pattern=SHA256)
    route_id: str = Field(pattern=IDENTIFIER)
    policy_hash: str = Field(pattern=SHA256)
    external_evidence_digest: str = Field(pattern=SHA256)
    applicable_gates: tuple[EvidenceGate, ...]
    applicability_binding_digest: str = Field(pattern=SHA256)
    authority_registry_digest: str = Field(pattern=SHA256)
    trust_anchor_digest: str = Field(pattern=SHA256)
    independent_verifier_digest: str = Field(pattern=SHA256)
    verified_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    mode: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    gate_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_gate(self):
        for value in (self.dataset_id, self.route_id):
            _identifier(value)
        for value in (self.verified_at, self.expires_at, self.revoked_at):
            if value is not None:
                _utc(value)
        if self.expires_at <= self.verified_at:
            raise ValueError("invalid gate evidence lifecycle")
        if self.revoked_at is not None and self.revoked_at <= self.verified_at:
            raise ValueError("invalid gate revocation lifecycle")
        if not self.applicable_gates or tuple(
            gate for gate in EvidenceGate if gate in self.applicable_gates
        ) != self.applicable_gates or self.gate not in self.applicable_gates:
            raise ValueError("invalid gate applicability")
        expected_applicability = typed_hash({
            "contract": CONTRACT_VERSION,
            "policy": self.policy_hash,
            "external_evidence": self.external_evidence_digest,
            "applicable_gates": [gate.value for gate in self.applicable_gates],
        })
        if self.applicability_binding_digest != expected_applicability:
            raise ValueError("invalid gate applicability binding")
        _hash(self, "gate_hash")
        return self


class AdmissionEvidenceBundle(_Model):
    provider: Literal["provider.ibkr"]
    adapter_id: str = Field(pattern=IDENTIFIER)
    dataset_id: str = Field(pattern=IDENTIFIER)
    security_master_id: Literal["security.us.msft.xnas"]
    con_id: int = Field(gt=0)
    request_hash: str = Field(pattern=SHA256)
    authenticity_assessment_hash: str = Field(pattern=SHA256)
    entitlement_reference_hash: str = Field(pattern=SHA256)
    route_id: str = Field(pattern=IDENTIFIER)
    policy_hash: str = Field(pattern=SHA256)
    backend_hash: str = Field(pattern=SHA256)
    provisioning_manifest_hash: str = Field(pattern=SHA256)
    provisioning_assessment_hash: str = Field(pattern=SHA256)
    observations: tuple[BoundObservationEvidence, ...]
    gates: tuple[GateEvidenceBinding, ...]
    assembled_at: dt.datetime
    bundle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_bundle(self):
        for value in (self.adapter_id, self.dataset_id, self.route_id):
            _identifier(value)
        _utc(self.assembled_at)
        observations = tuple(_deep(BoundObservationEvidence, value) for value in self.observations)
        gates = tuple(_deep(GateEvidenceBinding, value) for value in self.gates)
        if not observations:
            raise ValueError("observations required")
        if tuple(item.gate for item in gates) != tuple(EvidenceGate):
            raise ValueError("all canonical gate bindings required exactly once")
        if len({item.observation_id for item in observations}) != len(observations):
            raise ValueError("duplicate observation identity")
        if len({item.evidence_hash for item in observations}) != len(observations):
            raise ValueError("duplicate observation evidence")
        semantic_identities = {_semantic_observation_identity(item) for item in observations}
        if len(semantic_identities) != len(observations):
            raise ValueError("same observation counted under aliases")
        if observations != tuple(sorted(observations, key=lambda item: item.observed_at)):
            raise ValueError("observations must be chronologically ordered")
        by_external_evidence: dict[str, list[GateEvidenceBinding]] = {}
        for gate in gates:
            by_external_evidence.setdefault(gate.external_evidence_digest, []).append(gate)
        for shared in by_external_evidence.values():
            actual = tuple(item.gate for item in shared)
            if any(item.applicable_gates != actual for item in shared):
                raise ValueError("external evidence reused without bound multi-applicability")
        _hash(self, "bundle_hash")
        return self


class AdmissionAggregationAssessment(_Model):
    policy_hash: str = Field(pattern=SHA256)
    bundle_hash: str = Field(pattern=SHA256)
    provisioning_assessment_hash: str = Field(pattern=SHA256)
    observation_evidence_hashes: tuple[str, ...]
    gate_evidence_hashes: tuple[str, ...]
    assessed_at: dt.datetime
    state: Literal[AggregationState.CONTRACT_TEST_VALIDATED]
    observations_sufficient_under_contract_policy: Literal[True]
    real_observations_verified: Literal[ProvisioningState.NOT_PROVISIONED]
    real_gate_closure: Literal[ProvisioningState.NOT_PROVISIONED]
    real_provider_admission: Literal[ProvisioningState.NOT_PROVISIONED]
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
            raise ValueError("contract evidence cannot close REAL gates")
        _hash(self, "assessment_hash")
        return self


def aggregate_contract_test_admission_evidence(
    *,
    policy: Any,
    bundle: Any,
    provisioning_manifest: Any,
    provisioning_assessment: Any,
    assessed_at: dt.datetime,
) -> AdmissionAggregationAssessment:
    """Validate exact contract lineage while keeping every REAL state fail-closed."""
    failed = False
    message = "invalid admission evidence"
    result = None
    try:
        rule = _deep(SufficientObservationPolicy, policy)
        package = _deep(AdmissionEvidenceBundle, bundle)
        manifest = _deep(ProvisioningEvidenceManifest, provisioning_manifest)
        provisioning = _deep(ProvisioningContractAssessment, provisioning_assessment)
        _utc(assessed_at)
        _same_scope(rule, package)
        if package.policy_hash != rule.policy_hash:
            raise ValueError("policy binding mismatch")
        if package.backend_hash != provisioning.backend_hash:
            raise ValueError("backend binding mismatch")
        if package.provisioning_manifest_hash != provisioning.manifest_hash:
            raise ValueError("provisioning manifest binding mismatch")
        if package.provisioning_manifest_hash != manifest.manifest_hash:
            raise ValueError("provisioning manifest content mismatch")
        if package.provisioning_assessment_hash != provisioning.assessment_hash:
            raise ValueError("provisioning assessment binding mismatch")
        if package.authenticity_assessment_hash != provisioning.authenticity_assessment_hash:
            raise ValueError("authenticity assessment binding mismatch")
        if provisioning.observation_binding_hash != manifest.observation_binding_hash:
            raise ValueError("canonical observation binding mismatch")
        expected_manifest = (
            package.provider,
            package.security_master_id,
            package.request_hash,
            package.authenticity_assessment_hash,
            package.entitlement_reference_hash,
        )
        actual_manifest = (
            manifest.provider,
            manifest.security_master_id,
            manifest.request_hash,
            manifest.authenticity_assessment_hash,
            manifest.entitlement_reference_hash,
        )
        if expected_manifest != actual_manifest:
            raise ValueError("upstream manifest lineage swap")
        principals = {principal.role: principal for principal in manifest.principals}
        authority = principals[PrincipalRole.AUTHORITY]
        revocation_owner = principals[PrincipalRole.REVOCATION_OWNER]
        verifier = principals[PrincipalRole.VERIFIER]
        for principal in manifest.principals:
            if not principal.available_at <= assessed_at < principal.expires_at:
                raise ValueError("policy authority context unavailable")
            if principal.revoked_at is not None and assessed_at >= principal.revoked_at:
                raise ValueError("policy authority context revoked")
        expected_policy_authority = typed_hash({
            "contract": CONTRACT_VERSION,
            "authority_registry": manifest.authority_registry_reference_digest,
            "authority_principal": authority.principal_hash,
        })
        if (
            rule.authority_registry_reference_digest
            != manifest.authority_registry_reference_digest
            or rule.authority_principal_hash != authority.principal_hash
            or rule.revocation_owner_principal_hash != revocation_owner.principal_hash
            or rule.policy_authority_reference_digest != expected_policy_authority
        ):
            raise ValueError("policy authority mismatch")
        if not rule.approved_at <= assessed_at:
            raise ValueError("policy approval is future or unavailable")
        if not rule.effective_at <= assessed_at < rule.expires_at:
            raise ValueError("policy unavailable at assessment time")
        if rule.revoked_at is not None and assessed_at >= rule.revoked_at:
            raise ValueError("policy revoked at assessment time")
        if package.assembled_at > assessed_at:
            raise ValueError("bundle assembled in the future")
        if package.assembled_at < max(manifest.effective_at, provisioning.assessed_at):
            raise ValueError("bundle predates required upstream evidence")
        if len(package.observations) < rule.minimum_distinct_observations:
            raise ValueError("insufficient distinct observations")
        if package.observations[-1].observed_at - package.observations[0].observed_at < rule.minimum_observation_span:
            raise ValueError("insufficient observation span")
        for observation in package.observations:
            _same_scope(rule, observation)
            if (observation.con_id, observation.request_hash) != (
                package.con_id,
                package.request_hash,
            ):
                raise ValueError("security identity or request swap")
            if observation.authenticity_assessment_hash != package.authenticity_assessment_hash:
                raise ValueError("observation authenticity swap")
            if observation.entitlement_reference_hash != package.entitlement_reference_hash:
                raise ValueError("observation entitlement swap")
            if observation.provisioning_assessment_hash != provisioning.assessment_hash:
                raise ValueError("observation provisioning swap")
            if observation.observation_binding_hash != manifest.observation_binding_hash:
                raise ValueError("observation binding swap")
            references = (
                observation.replay_service_reference_digest,
                observation.custody_evidence_reference_digest,
                observation.worm_evidence_reference_digest,
                observation.legal_approval_reference_digest,
            )
            canonical_references = (
                manifest.replay_service_reference_digest,
                manifest.custody_evidence_reference_digest,
                manifest.worm_evidence_reference_digest,
                manifest.legal_approval_reference_digest,
            )
            if references != canonical_references:
                raise ValueError("observation replay, custody, WORM or legal swap")
            if not (
                observation.observed_at <= observation.authenticated_at
                <= observation.verifier_time <= package.assembled_at <= assessed_at
            ):
                raise ValueError("invalid observation aggregation causality")
            if assessed_at - observation.observed_at > rule.maximum_observation_age:
                raise ValueError("stale observation")
            if assessed_at - observation.verifier_time > rule.maximum_verifier_skew:
                raise ValueError("mixed verifier time")
        for gate in package.gates:
            _same_scope(rule, gate)
            if (gate.con_id, gate.request_hash) != (package.con_id, package.request_hash):
                raise ValueError("gate security or request swap")
            if gate.policy_hash != rule.policy_hash:
                raise ValueError("cross-policy gate binding")
            if (
                gate.authority_registry_digest
                != manifest.authority_registry_reference_digest
                or gate.trust_anchor_digest != manifest.trust_anchor_reference_digest
            ):
                raise ValueError("gate authority or trust-anchor swap")
            if gate.independent_verifier_digest != verifier.external_identity_digest:
                raise ValueError("gate verifier swap")
            if gate.verified_at > package.assembled_at:
                raise ValueError("bundle predates gate evidence")
            if not gate.verified_at <= assessed_at < gate.expires_at:
                raise ValueError("stale or future gate evidence")
            if gate.revoked_at is not None and assessed_at >= gate.revoked_at:
                raise ValueError("revoked gate evidence")
        result = _seal(
            AdmissionAggregationAssessment,
            "assessment_hash",
            policy_hash=rule.policy_hash,
            bundle_hash=package.bundle_hash,
            provisioning_assessment_hash=provisioning.assessment_hash,
            observation_evidence_hashes=tuple(x.evidence_hash for x in package.observations),
            gate_evidence_hashes=tuple(x.gate_hash for x in package.gates),
            assessed_at=assessed_at,
            state=AggregationState.CONTRACT_TEST_VALIDATED,
            observations_sufficient_under_contract_policy=True,
            real_observations_verified=ProvisioningState.NOT_PROVISIONED,
            real_gate_closure=ProvisioningState.NOT_PROVISIONED,
            real_provider_admission=ProvisioningState.NOT_PROVISIONED,
            gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
            real_route="QVM_NOT_READY",
            global_readiness="INSUFFICIENT_REAL_DATA",
            trade_decision="NO_TRADE",
            signals_generated=False,
            live_execution_enabled=False,
            backtesting="NOT_AUTHORIZED",
        )
    except BaseException as exc:  # noqa: BLE001
        failed = True
        message = str(exc) if type(exc) is AdmissionAggregationError else "invalid admission evidence"
    if failed:
        raise AdmissionAggregationError(message) from None
    return result


def admit_real_provider(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise AdmissionAggregationError("REAL provider admission is NOT_PROVISIONED")


T = TypeVar("T", bound=BaseModel)


def seal_contract_test(expected: type[T], hash_field: str, **values: Any) -> T:
    failed = False
    result = None
    try:
        if _SEAL_FIELDS.get(expected) != hash_field:
            raise TypeError("unsupported model")
        result = _seal(expected, hash_field, **values)
    except BaseException:  # noqa: BLE001
        failed = True
    if failed:
        raise AdmissionAggregationError("invalid admission aggregation value") from None
    return result


def _same_scope(policy: SufficientObservationPolicy, value: Any) -> None:
    expected = (
        policy.provider,
        policy.dataset_id,
        policy.security_master_id,
        policy.route_id,
    )
    actual = (value.provider, value.dataset_id, value.security_master_id, value.route_id)
    if expected != actual:
        raise ValueError("provider, dataset, security or route swap")
    if hasattr(value, "adapter_id") and value.adapter_id != policy.adapter_id:
        raise ValueError("adapter swap")


def _semantic_observation_identity(value: BoundObservationEvidence) -> str:
    """Derive identity from governed immutable content, never caller aliases or seals."""
    return typed_hash({
        "contract": CONTRACT_VERSION,
        "provider": value.provider,
        "adapter": value.adapter_id,
        "dataset": value.dataset_id,
        "security_master": value.security_master_id,
        "con_id": value.con_id,
        "request": value.request_hash,
        "canonical_binding": value.observation_binding_hash,
        "observed_at": value.observed_at,
        "material": value.material_digest,
        "provenance": value.provenance_digest,
        "lineage": value.lineage_digest,
        "custody_receipt": value.custody_receipt_digest,
    })


def _deep(expected: type[T], value: Any) -> T:
    try:
        if isinstance(value, BaseModel):
            if set(value.__dict__) - set(type(value).model_fields):
                raise ValueError("undeclared model fields")
            value = value.model_dump(mode="json", warnings=False)
        elif isinstance(value, str):
            value = json.loads(value)
        elif not isinstance(value, dict):
            raise TypeError("unsupported value")
        return expected.model_validate(json.loads(json.dumps(value, sort_keys=True)))
    except BaseException:  # noqa: BLE001
        raise AdmissionAggregationError("invalid admission aggregation value") from None


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    digest = typed_hash(raw.model_dump(mode="json", exclude={hash_field}, warnings=False))
    return expected(**values, **{hash_field: digest})


def _hash(value: BaseModel, field: str) -> None:
    actual = getattr(value, field)
    expected = typed_hash(value.model_dump(mode="json", exclude={field}, warnings=False))
    if actual != expected:
        raise ValueError("hash mismatch")


def _identifier(value: str) -> None:
    if not value.isascii() or value != value.casefold() or value != unicodedata.normalize("NFKC", value):
        raise ValueError("identifier must be canonical lowercase ASCII")


def _utc(value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError("timestamp must use canonical UTC")


_SEAL_FIELDS: dict[type[BaseModel], str] = {
    SufficientObservationPolicy: "policy_hash",
    BoundObservationEvidence: "evidence_hash",
    GateEvidenceBinding: "gate_hash",
    AdmissionEvidenceBundle: "bundle_hash",
    AdmissionAggregationAssessment: "assessment_hash",
}
