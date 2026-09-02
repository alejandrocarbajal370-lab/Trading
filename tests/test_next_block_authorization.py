from governance.phase7e import EvidenceGate, GateState
from governance.roadmap import (
    NEXT_BLOCK,
    ImplementationAuthorization,
    NextBlockScope,
)


def test_next_foundation_is_authorized_but_real_activation_is_not():
    assert (
        NEXT_BLOCK.name
        == "External Provider Adapter & Durable Verification Interface Foundation"
    )
    assert (
        NEXT_BLOCK.foundation_implementation
        == ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT
    )
    assert NEXT_BLOCK.real_external_activation == ImplementationAuthorization.NOT_AUTHORIZED
    assert NEXT_BLOCK.operating_mode == "CONTRACT_TEST_ONLY"
    assert NEXT_BLOCK.scope == tuple(NextBlockScope)
    assert NEXT_BLOCK.evidence_states == ("OBSERVED", "VERIFIED", "TRUSTED", "CLOSED")


def test_next_foundation_preserves_all_frozen_safety_states():
    assert NEXT_BLOCK.gate_states == tuple(
        (gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate
    )
    assert len(NEXT_BLOCK.gate_states) == 10
    assert NEXT_BLOCK.trust_root == "NOT_PROVISIONED"
    assert NEXT_BLOCK.durable_replay == "NOT_PROVISIONED"
    assert NEXT_BLOCK.real_route == "QVM_NOT_READY"
    assert NEXT_BLOCK.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert NEXT_BLOCK.trade_decision == "NO_TRADE"
    assert NEXT_BLOCK.signals_enabled is False
    assert NEXT_BLOCK.live_execution_enabled is False
    assert NEXT_BLOCK.backtesting == "NOT_AUTHORIZED"
