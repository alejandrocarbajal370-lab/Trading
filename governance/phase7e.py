"""Phase 7E provider-agnostic evidence admission contracts.

These contracts model review state only. They cannot enable QVM or global readiness.
"""

from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash

PHASE7E_CONTRACT_VERSION = "phase7e-real-provider-evidence-v1"
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


REQUIRED_GATES = frozenset(EvidenceGate)


class EvidenceClass(StrEnum):
    REAL_EXTERNAL = "REAL_EXTERNAL"
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"


class GateState(StrEnum):
    OPEN_EXTERNAL = "OPEN_EXTERNAL"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"


class EvidenceRecord(ContractModel):
    gate: EvidenceGate
    evidence_class: EvidenceClass
    provider_id: str
    dataset_id: str
    source_uri: str
    source_record_id: str
    content_hash: str = Field(pattern=SHA256)
    observed_at: datetime.datetime
    scope: str


class ReviewedGateEvidence(ContractModel):
    record: EvidenceRecord
    maker_id: str
    checker_id: str
    decision: Literal["ACCEPT", "REJECT"]
    checked_at: datetime.datetime
    review_record_id: str

    @model_validator(mode="after")
    def maker_checker_and_real_evidence(self) -> ReviewedGateEvidence:
        if self.maker_id == self.checker_id:
            raise ValueError("maker and checker must be distinct")
        if self.decision == "ACCEPT" and self.record.evidence_class != EvidenceClass.REAL_EXTERNAL:
            raise ValueError("contract-test-only evidence cannot be accepted as real evidence")
        if self.checked_at < self.record.observed_at:
            raise ValueError("review cannot predate evidence")
        return self


class Phase7EBundle(ContractModel):
    version: Literal["phase7e-real-provider-evidence-v1"] = PHASE7E_CONTRACT_VERSION
    provider_id: str
    dataset_id: str
    reviews: tuple[ReviewedGateEvidence, ...]
    assembled_at: datetime.datetime
    bundle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_bundle(self) -> Phase7EBundle:
        if any(
            (item.record.provider_id, item.record.dataset_id)
            != (self.provider_id, self.dataset_id)
            for item in self.reviews
        ):
            raise ValueError("evidence identity mismatch")
        gates = [item.record.gate for item in self.reviews]
        if len(gates) != len(set(gates)):
            raise ValueError("duplicate gate evidence")
        expected = typed_hash(self.model_dump(mode="json", exclude={"bundle_hash"}))
        if self.bundle_hash != expected:
            raise ValueError("evidence bundle hash mismatch")
        return self


class EvidenceCustodyContext(ContractModel):
    """Records independently resolved from governed custody, not bundle declarations."""

    reviews: tuple[ReviewedGateEvidence, ...] = ()


class Phase7EAssessment(ContractModel):
    version: Literal["phase7e-assessment-v1"] = "phase7e-assessment-v1"
    provider_id: str
    dataset_id: str
    gate_states: tuple[tuple[EvidenceGate, GateState], ...]
    state: Literal["OPEN_EXTERNAL", "EVIDENCE_REVIEW_COMPLETE"]
    real_route: Literal["QVM_NOT_READY"] = "QVM_NOT_READY"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    backtesting: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"


def assess_phase7e_bundle(
    bundle: Phase7EBundle | None, context: EvidenceCustodyContext | None = None
) -> Phase7EAssessment:
    """Recompute gate state; Phase 7E never promotes real/global readiness."""
    accepted: set[EvidenceGate] = set()
    provider_id = "UNSELECTED"
    dataset_id = "UNSELECTED"
    if bundle is not None:
        parsed = Phase7EBundle.model_validate(bundle.model_dump(mode="python"))
        provider_id, dataset_id = parsed.provider_id, parsed.dataset_id
        resolved = set((context or EvidenceCustodyContext()).reviews)
        accepted = {
            item.record.gate
            for item in parsed.reviews
            if item.decision == "ACCEPT"
            and item.record.evidence_class == EvidenceClass.REAL_EXTERNAL
            and item in resolved
        }
    states = tuple(
        (gate, GateState.VERIFIED if gate in accepted else GateState.OPEN_EXTERNAL)
        for gate in EvidenceGate
    )
    complete = accepted == REQUIRED_GATES
    return Phase7EAssessment(
        provider_id=provider_id,
        dataset_id=dataset_id,
        gate_states=states,
        state="EVIDENCE_REVIEW_COMPLETE" if complete else "OPEN_EXTERNAL",
    )


def require_complete_external_evidence(
    bundle: Phase7EBundle, context: EvidenceCustodyContext
) -> Phase7EAssessment:
    assessment = assess_phase7e_bundle(bundle, context)
    if assessment.state != "EVIDENCE_REVIEW_COMPLETE":
        raise Phase7EContractError("Phase 7E gates remain OPEN_EXTERNAL")
    return assessment
