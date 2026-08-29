"""Fail-closed Phase 7E evidence admission contracts.

Local hashes prove integrity, never authenticity. This repository can validate
contract fixtures but has no real custody or reviewer trust anchor; consequently
the REAL route cannot derive ``VERIFIED``.
"""

from __future__ import annotations

import datetime
import json
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash

PHASE7E_CONTRACT_VERSION = "phase7e-evidence-contract-v2"
PHASE7E_POLICY_VERSION = "phase7e-contract-policy-v2"
SHA256 = r"^[0-9a-f]{64}$"


class Phase7EContractError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceGate(StrEnum):
    HISTORICAL_PIT_SECURITY_MASTER = "HISTORICAL_PIT_SECURITY_MASTER"
    LICENSING_LEGAL = "LICENSING_LEGAL"
    HISTORICAL_COMPLETENESS = "HISTORICAL_COMPLETENESS"
    RETENTION_WORM = "RETENTION_WORM"
    OPERATIONS_MONITORING = "OPERATIONS_MONITORING"
    REAL_FX = "REAL_FX"
    SHARES_OUTSTANDING_PIT = "SHARES_OUTSTANDING_PIT"
    RESTATEMENT_MATERIALITY = "RESTATEMENT_MATERIALITY"
    CORPORATE_ACTION_ECONOMICS = "CORPORATE_ACTION_ECONOMICS"
    SCALE_OPERATIONAL_VALIDATION = "SCALE_OPERATIONAL_VALIDATION"


class GateState(StrEnum):
    OPEN_EXTERNAL = "OPEN_EXTERNAL"
    VERIFIED = "VERIFIED"


REQUIRED_GATES = frozenset(EvidenceGate)
CANONICAL_GATES = tuple(EvidenceGate)


class WindowPayload(ContractModel):
    window_start: datetime.datetime
    window_end: datetime.datetime


class HistoricalPitPayload(WindowPayload):
    kind: Literal["historical_pit"]
    universe_id: str
    security_master_id: str
    pit_semantics: str
    completeness_artifact_ids: tuple[str, ...]


class LicensingPayload(ContractModel):
    kind: Literal["licensing"]
    legal_artifact_id: str
    permitted_use: str
    effective_at: datetime.datetime
    expires_at: datetime.datetime
    retention_permitted: bool
    derived_use_permitted: bool


class CompletenessPayload(WindowPayload):
    kind: Literal["completeness"]
    universe_id: str
    expected_count: int = Field(gt=0)
    observed_count: int = Field(ge=0)
    methodology_id: str

    @model_validator(mode="after")
    def complete_coverage(self) -> CompletenessPayload:
        if self.observed_count < self.expected_count:
            raise ValueError("partial coverage cannot be represented as complete")
        return self


class RetentionPayload(ContractModel):
    kind: Literal["retention_worm"]
    storage_control_artifact_id: str
    retention_days: int = Field(gt=0)
    immutability_mechanism_artifact_id: str
    derived_artifact_policy_id: str


class OperationsPayload(WindowPayload):
    kind: Literal["operations"]
    monitoring_artifact_id: str
    incident_artifact_id: str
    availability_artifact_id: str


class FxPayload(WindowPayload):
    kind: Literal["fx"]
    pairs: tuple[str, ...]
    pit_semantics: str
    fx_artifact_id: str


class SharesPayload(WindowPayload):
    kind: Literal["shares_pit"]
    issuer_ids: tuple[str, ...]
    security_ids: tuple[str, ...]
    shares_semantics: str
    lineage_id: str


class RestatementPayload(ContractModel):
    kind: Literal["restatement"]
    accounting_policy_id: str
    restatement_policy_id: str
    detection_artifact_id: str
    materiality_artifact_id: str


class CorporateActionPayload(WindowPayload):
    kind: Literal["corporate_actions"]
    security_ids: tuple[str, ...]
    action_types: tuple[str, ...]
    economic_treatment_policy_id: str


class ScalePayload(WindowPayload):
    kind: Literal["scale"]
    workload_id: str
    coverage_id: str
    volume: int = Field(gt=0)
    operational_test_artifact_id: str


EvidencePayload = Annotated[
    HistoricalPitPayload
    | LicensingPayload
    | CompletenessPayload
    | RetentionPayload
    | OperationsPayload
    | FxPayload
    | SharesPayload
    | RestatementPayload
    | CorporateActionPayload
    | ScalePayload,
    Field(discriminator="kind"),
]
PAYLOAD_GATE = dict(
    zip(
        (
            "historical_pit",
            "licensing",
            "completeness",
            "retention_worm",
            "operations",
            "fx",
            "shares_pit",
            "restatement",
            "corporate_actions",
            "scale",
        ),
        EvidenceGate,
        strict=True,
    )
)
GATE_PAYLOAD_TYPE = {
    gate: payload_type
    for gate, payload_type in zip(
        EvidenceGate,
        (
            HistoricalPitPayload,
            LicensingPayload,
            CompletenessPayload,
            RetentionPayload,
            OperationsPayload,
            FxPayload,
            SharesPayload,
            RestatementPayload,
            CorporateActionPayload,
            ScalePayload,
        ),
        strict=True,
    )
}


class GatePolicy(ContractModel):
    version: Literal["phase7e-contract-policy-v2"] = PHASE7E_POLICY_VERSION
    gate: EvidenceGate
    provider_id: str
    dataset_id: str
    as_of: datetime.datetime
    scope_id: str
    window_start: datetime.datetime
    window_end: datetime.datetime
    max_age: datetime.timedelta | None = None
    policy_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def valid(self) -> GatePolicy:
        if self.window_start > self.window_end:
            raise ValueError("invalid policy coverage window")
        if self.policy_hash != typed_hash(self.model_dump(mode="json", exclude={"policy_hash"})):
            raise ValueError("policy hash mismatch")
        return self


class ContractTestEvidence(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    gate: EvidenceGate
    provider_id: str
    dataset_id: str
    evidence_id: str
    content_hash: str = Field(pattern=SHA256)
    effective_at: datetime.datetime
    available_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    as_of: datetime.datetime
    scope_id: str
    policy_version: Literal["phase7e-contract-policy-v2"]
    policy_hash: str = Field(pattern=SHA256)
    payload: EvidencePayload

    @model_validator(mode="after")
    def bound(self) -> ContractTestEvidence:
        if PAYLOAD_GATE[self.payload.kind] != self.gate:
            raise ValueError("gate-specific payload mismatch")
        if self.content_hash != typed_hash(self.model_dump(mode="json", exclude={"content_hash"})):
            raise ValueError("evidence integrity hash mismatch")
        return self


class ContractTestCustodyContext(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    context_id: Literal["phase7e-contract-fixture-root-v2"] = "phase7e-contract-fixture-root-v2"
    context_version: Literal["v2"] = "v2"


class ContractReviewerRegistry(ContractModel):
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    actors: tuple[tuple[str, tuple[str, ...]], ...]

    def resolve(self, claimed: str) -> str | None:
        value = " ".join(claimed.split()).casefold()
        for actor, aliases in self.actors:
            if value in {" ".join(x.split()).casefold() for x in (actor, *aliases)}:
                return actor.casefold()
        return None


class ContractApproval(ContractModel):
    gate: EvidenceGate
    maker: str
    checker: str
    provider_id: str
    dataset_id: str
    evidence_hash: str = Field(pattern=SHA256)
    as_of: datetime.datetime
    scope_id: str
    policy_version: Literal["phase7e-contract-policy-v2"]
    policy_hash: str = Field(pattern=SHA256)
    decision: Literal["ACCEPT", "REJECT"]


class ContractEvidenceBundle(ContractModel):
    version: Literal["phase7e-evidence-contract-v2"] = PHASE7E_CONTRACT_VERSION
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"
    provider_id: str
    dataset_id: str
    evidences: tuple[ContractTestEvidence, ...]
    approvals: tuple[ContractApproval, ...]
    bundle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def valid(self) -> ContractEvidenceBundle:
        if any(
            (e.provider_id, e.dataset_id) != (self.provider_id, self.dataset_id)
            for e in self.evidences
        ):
            raise ValueError("provider/dataset evidence binding mismatch")
        for values in (
            [e.gate for e in self.evidences],
            [e.evidence_id for e in self.evidences],
            [e.content_hash for e in self.evidences],
            [a.gate for a in self.approvals],
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate or reused evidence")
        if self.bundle_hash != typed_hash(self.model_dump(mode="json", exclude={"bundle_hash"})):
            raise ValueError("bundle integrity hash mismatch")
        return self


class ContractGateVerification(ContractModel):
    gate_states: tuple[tuple[EvidenceGate, GateState], ...]
    contract_semantics_complete: bool
    trust_domain: Literal["CONTRACT_TEST_ONLY"] = "CONTRACT_TEST_ONLY"

    @model_validator(mode="after")
    def coherent(self) -> ContractGateVerification:
        if tuple(g for g, _ in self.gate_states) != CANONICAL_GATES:
            raise ValueError("contract gate states must be complete, unique, and canonical")
        complete = all(state == GateState.VERIFIED for _, state in self.gate_states)
        if self.contract_semantics_complete != complete:
            raise ValueError("contract completion is derived from gate states")
        return self


class RealExternalTrustResolver(Protocol):
    """Future independently provisioned resolver; intentionally unimplemented."""

    @property
    def canonical_trust_anchor_id(self) -> str: ...


class RealGateVerification(ContractModel):
    gate_states: tuple[tuple[EvidenceGate, GateState], ...]
    state: Literal["OPEN_EXTERNAL"] = "OPEN_EXTERNAL"
    reason: Literal["REAL_TRUST_ANCHORS_UNAVAILABLE"] = "REAL_TRUST_ANCHORS_UNAVAILABLE"

    @model_validator(mode="after")
    def only_current_real_state(self) -> RealGateVerification:
        if self.gate_states != _open_states():
            raise ValueError("real results require exactly ten canonical OPEN_EXTERNAL gates")
        return self


class Phase7EAssessment(ContractModel):
    gate_states: tuple[tuple[EvidenceGate, GateState], ...]
    state: Literal["OPEN_EXTERNAL"] = "OPEN_EXTERNAL"
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"

    @model_validator(mode="after")
    def only_current_assessment(self) -> Phase7EAssessment:
        if self.gate_states != _open_states():
            raise ValueError("assessment requires exactly ten canonical OPEN_EXTERNAL gates")
        return self


def _open_states():
    return tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)


ModelT = TypeVar("ModelT", bound=BaseModel)


def _primitive_snapshot(value: Any) -> Any:
    """Detach an untrusted value from Pydantic construction history.

    ``model_copy`` and ``model_construct`` may skip validation.  A JSON primitive
    round-trip deliberately discards model identity before the expected type is
    selected and validated at this verifier boundary.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise Phase7EContractError("input is not canonically serializable") from exc


def _revalidate(expected: type[ModelT], value: Any, label: str) -> ModelT:
    try:
        return expected.model_validate(_primitive_snapshot(value))
    except (TypeError, ValueError) as exc:
        raise Phase7EContractError(f"invalid {label}") from exc


def verify_contract_evidence_bundle(bundle, policies, custody, reviewers):
    """Revalidate untrusted primitives, then validate synthetic mechanics."""
    custody = _revalidate(ContractTestCustodyContext, custody, "contract custody")
    reviewers = _revalidate(ContractReviewerRegistry, reviewers, "reviewer registry")
    bundle = _revalidate(ContractEvidenceBundle, bundle, "contract bundle")
    policies = tuple(_revalidate(GatePolicy, p, "gate policy") for p in policies)

    policy_by_gate = {p.gate: p for p in policies}
    if len(policy_by_gate) != len(policies):
        raise Phase7EContractError("duplicate policies")
    if set(policy_by_gate) - REQUIRED_GATES:
        raise Phase7EContractError("unknown policy gate")

    evidence_by_gate = {}
    for raw_evidence in bundle.evidences:
        evidence = _revalidate(ContractTestEvidence, raw_evidence, "contract evidence")
        expected_payload = GATE_PAYLOAD_TYPE[evidence.gate]
        expected_payload.model_validate(_primitive_snapshot(evidence.payload))
        evidence_by_gate[evidence.gate] = evidence

    accepted = set()
    for raw_approval in bundle.approvals:
        a = _revalidate(ContractApproval, raw_approval, "contract approval")
        e, policy = evidence_by_gate.get(a.gate), policy_by_gate.get(a.gate)
        maker, checker = reviewers.resolve(a.maker), reviewers.resolve(a.checker)
        if e is None or policy is None or maker is None or checker is None or maker == checker:
            continue
        start = getattr(e.payload, "window_start", policy.window_start)
        end = getattr(e.payload, "window_end", policy.window_end)
        valid = (
            a.decision == "ACCEPT"
            and a.provider_id == e.provider_id == policy.provider_id
            and a.dataset_id == e.dataset_id == policy.dataset_id
            and a.evidence_hash == e.content_hash
            and a.as_of == e.as_of == policy.as_of
            and a.scope_id == e.scope_id == policy.scope_id
            and a.policy_version == e.policy_version == policy.version
            and a.policy_hash == e.policy_hash == policy.policy_hash
            and e.available_at <= e.as_of
            and e.effective_at <= e.as_of
            and (e.expires_at is None or e.as_of <= e.expires_at)
            and start <= policy.window_start
            and end >= policy.window_end
            and (policy.max_age is None or e.as_of - e.available_at <= policy.max_age)
        )
        if valid:
            accepted.add(a.gate)
    states = tuple(
        (g, GateState.VERIFIED if g in accepted else GateState.OPEN_EXTERNAL) for g in EvidenceGate
    )
    return ContractGateVerification(
        gate_states=states, contract_semantics_complete=accepted == REQUIRED_GATES
    )


def verify_real_external_evidence_bundle(bundle=None, resolver=None):
    """Always fail closed: the audited repository has no external trust anchors."""
    del bundle, resolver
    return RealGateVerification.model_validate({"gate_states": _open_states()})


def assess_phase7e_bundle(bundle=None, context=None):
    del bundle, context
    return Phase7EAssessment.model_validate(
        {"gate_states": verify_real_external_evidence_bundle().gate_states}
    )


def require_complete_external_evidence(bundle, context):
    del bundle, context
    raise Phase7EContractError(
        "Phase 7E gates remain OPEN_EXTERNAL: real trust anchors unavailable"
    )
