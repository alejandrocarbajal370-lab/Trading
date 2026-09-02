"""Machine-readable authorization boundary for the next external-provider foundation."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from governance.phase7e import EvidenceGate, GateState


class ImplementationAuthorization(StrEnum):
    AUTHORIZED_TO_IMPLEMENT = "AUTHORIZED_TO_IMPLEMENT"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class NextBlockScope(StrEnum):
    PROVIDER_ADAPTER_INTERFACE = "PROVIDER_ADAPTER_INTERFACE"
    CANONICAL_IDENTITY_RESOLUTION = "CANONICAL_IDENTITY_RESOLUTION"
    MATERIAL_FETCH_OBSERVATION_CONTRACT = "MATERIAL_FETCH_OBSERVATION_CONTRACT"
    FAIL_CLOSED_SIGNATURE_ATTESTATION_HOOK = "FAIL_CLOSED_SIGNATURE_ATTESTATION_HOOK"
    DURABLE_REPLAY_STORAGE_INTERFACE = "DURABLE_REPLAY_STORAGE_INTERFACE"
    INDEPENDENT_VERIFIER_INTERFACE = "INDEPENDENT_VERIFIER_INTERFACE"
    GATE_ACCEPTANCE_EVIDENCE_HANDOFF = "GATE_ACCEPTANCE_EVIDENCE_HANDOFF"
    EXPLICIT_EVIDENCE_STATE_SEPARATION = "EXPLICIT_EVIDENCE_STATE_SEPARATION"


class NextBlockAuthorization(BaseModel):
    """Code-owned roadmap state; authorization to build is not REAL activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[
        "External Provider Adapter & Durable Verification Interface Foundation"
    ]
    foundation_implementation: Literal[
        ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT
    ]
    real_external_activation: Literal[ImplementationAuthorization.NOT_AUTHORIZED]
    operating_mode: Literal["CONTRACT_TEST_ONLY"]
    scope: tuple[NextBlockScope, ...]
    evidence_states: tuple[
        Literal["OBSERVED"],
        Literal["VERIFIED"],
        Literal["TRUSTED"],
        Literal["CLOSED"],
    ]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    trust_root: Literal["NOT_PROVISIONED"]
    durable_replay: Literal["NOT_PROVISIONED"]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_enabled: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]


NEXT_BLOCK = NextBlockAuthorization(
    name="External Provider Adapter & Durable Verification Interface Foundation",
    foundation_implementation=ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT,
    real_external_activation=ImplementationAuthorization.NOT_AUTHORIZED,
    operating_mode="CONTRACT_TEST_ONLY",
    scope=tuple(NextBlockScope),
    evidence_states=("OBSERVED", "VERIFIED", "TRUSTED", "CLOSED"),
    gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    trust_root="NOT_PROVISIONED",
    durable_replay="NOT_PROVISIONED",
    real_route="QVM_NOT_READY",
    global_readiness="INSUFFICIENT_REAL_DATA",
    trade_decision="NO_TRADE",
    signals_enabled=False,
    live_execution_enabled=False,
    backtesting="NOT_AUTHORIZED",
)
