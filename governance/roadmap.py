"""Machine-readable authorization boundary for the next non-REAL foundation."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from governance.phase7e import EvidenceGate, GateState


class ImplementationAuthorization(StrEnum):
    AUTHORIZED_TO_IMPLEMENT = "AUTHORIZED_TO_IMPLEMENT"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class RoadmapBlock(StrEnum):
    EXTERNAL_PROVIDER_ADAPTER_DURABLE_VERIFICATION_INTERFACE_FOUNDATION = (
        "External Provider Adapter & Durable Verification Interface Foundation"
    )
    DURABLE_REPLAY_PERSISTENCE_CUSTODY_BOUNDARY_FOUNDATION = (
        "Durable Replay Persistence & Custody Boundary Foundation"
    )


class NextBlockScope(StrEnum):
    REPLAY_IDENTITY_CONTRACT = "REPLAY_IDENTITY_CONTRACT"
    ATOMIC_CONSUME_IF_NEW_SEMANTICS = "ATOMIC_CONSUME_IF_NEW_SEMANTICS"
    RESTART_AND_CROSS_PROCESS_CONTINUITY_CONTRACT = (
        "RESTART_AND_CROSS_PROCESS_CONTINUITY_CONTRACT"
    )
    CUSTODY_RETENTION_BOUNDARY = "CUSTODY_RETENTION_BOUNDARY"
    FAILURE_RECOVERY_AND_CONCURRENCY_SEMANTICS = (
        "FAILURE_RECOVERY_AND_CONCURRENCY_SEMANTICS"
    )
    CONTRACT_TEST_PERSISTENCE_ADAPTER = "CONTRACT_TEST_PERSISTENCE_ADAPTER"


class MergeOrder(StrEnum):
    AFTER_CURRENT_BLOCK_MERGED = "AFTER_CURRENT_BLOCK_MERGED"


class NextBlockAuthorization(BaseModel):
    """Code-owned roadmap state; authorization to build is not REAL activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_block: Literal[
        RoadmapBlock.EXTERNAL_PROVIDER_ADAPTER_DURABLE_VERIFICATION_INTERFACE_FOUNDATION
    ]
    name: Literal[RoadmapBlock.DURABLE_REPLAY_PERSISTENCE_CUSTODY_BOUNDARY_FOUNDATION]
    foundation_implementation: Literal[
        ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT
    ]
    real_external_activation: Literal[ImplementationAuthorization.NOT_AUTHORIZED]
    operating_mode: Literal["CONTRACT_TEST_ONLY"]
    merge_order: Literal[MergeOrder.AFTER_CURRENT_BLOCK_MERGED]
    successor_pr: Literal["NEW_PR_REQUIRED"]
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
    independent_verifier: Literal["NOT_PROVISIONED"]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]

    @model_validator(mode="after")
    def validate_authorization_boundary(self):
        if self.current_block.value == self.name.value:
            raise ValueError("roadmap successor cannot reference the current block")
        if not self.scope:
            raise ValueError("roadmap successor must have implementable scope")
        if self.foundation_implementation is not ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT:
            raise ValueError("roadmap successor must be explicitly authorized to implement")
        if self.real_external_activation is not ImplementationAuthorization.NOT_AUTHORIZED:
            raise ValueError("REAL activation must remain forbidden")
        if self.gate_states != tuple(
            (gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate
        ):
            raise ValueError("all gates must remain OPEN_EXTERNAL")
        return self


NEXT_BLOCK = NextBlockAuthorization(
    current_block=(
        RoadmapBlock.EXTERNAL_PROVIDER_ADAPTER_DURABLE_VERIFICATION_INTERFACE_FOUNDATION
    ),
    name=RoadmapBlock.DURABLE_REPLAY_PERSISTENCE_CUSTODY_BOUNDARY_FOUNDATION,
    foundation_implementation=ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT,
    real_external_activation=ImplementationAuthorization.NOT_AUTHORIZED,
    operating_mode="CONTRACT_TEST_ONLY",
    merge_order=MergeOrder.AFTER_CURRENT_BLOCK_MERGED,
    successor_pr="NEW_PR_REQUIRED",
    scope=tuple(NextBlockScope),
    evidence_states=("OBSERVED", "VERIFIED", "TRUSTED", "CLOSED"),
    gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    trust_root="NOT_PROVISIONED",
    durable_replay="NOT_PROVISIONED",
    independent_verifier="NOT_PROVISIONED",
    real_route="QVM_NOT_READY",
    global_readiness="INSUFFICIENT_REAL_DATA",
    trade_decision="NO_TRADE",
    signals_generated=False,
    live_execution_enabled=False,
    backtesting="NOT_AUTHORIZED",
)


def validate_next_block(value: Any) -> NextBlockAuthorization:
    """Reconstruct untrusted roadmap values at the public truth boundary."""
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise ValueError("roadmap model contains undeclared fields")
        value = value.model_dump(mode="json", warnings=False)
    if isinstance(value, str):
        return NextBlockAuthorization.model_validate_json(value)
    return NextBlockAuthorization.model_validate(value)
