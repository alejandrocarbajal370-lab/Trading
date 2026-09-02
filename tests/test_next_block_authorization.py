from pathlib import Path

import pytest
from pydantic import ValidationError

from governance.phase7e import EvidenceGate, GateState
from governance.roadmap import (
    NEXT_BLOCK,
    ImplementationAuthorization,
    MergeOrder,
    NextBlockScope,
    RoadmapBlock,
    validate_next_block,
)

ROOT = Path(__file__).resolve().parents[1]


def test_next_foundation_is_authorized_but_real_activation_is_not():
    assert (
        NEXT_BLOCK.name
        == RoadmapBlock.DURABLE_REPLAY_PERSISTENCE_CUSTODY_BOUNDARY_FOUNDATION
    )
    assert (
        NEXT_BLOCK.current_block
        == RoadmapBlock.EXTERNAL_PROVIDER_ADAPTER_DURABLE_VERIFICATION_INTERFACE_FOUNDATION
    )
    assert NEXT_BLOCK.current_block.value != NEXT_BLOCK.name.value
    assert (
        NEXT_BLOCK.foundation_implementation
        == ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT
    )
    assert NEXT_BLOCK.real_external_activation == ImplementationAuthorization.NOT_AUTHORIZED
    assert NEXT_BLOCK.operating_mode == "CONTRACT_TEST_ONLY"
    assert NEXT_BLOCK.merge_order == MergeOrder.AFTER_CURRENT_BLOCK_MERGED
    assert NEXT_BLOCK.successor_pr == "NEW_PR_REQUIRED"
    assert NEXT_BLOCK.scope == tuple(NextBlockScope)
    assert NEXT_BLOCK.evidence_states == ("OBSERVED", "VERIFIED", "TRUSTED", "CLOSED")


def test_roadmap_rejects_self_reference_or_unauthorized_successor():
    raw = NEXT_BLOCK.model_dump(mode="python")
    raw["name"] = raw["current_block"]
    with pytest.raises(ValidationError):
        type(NEXT_BLOCK).model_validate(raw)

    raw = NEXT_BLOCK.model_dump(mode="python")
    raw["foundation_implementation"] = ImplementationAuthorization.NOT_AUTHORIZED
    with pytest.raises(ValidationError):
        type(NEXT_BLOCK).model_validate(raw)


def test_roadmap_json_copy_construct_and_direct_validation_fail_closed():
    assert validate_next_block(NEXT_BLOCK.model_dump_json()) == NEXT_BLOCK
    for forged in (
        NEXT_BLOCK.model_copy(update={"real_external_activation": "AUTHORIZED_TO_IMPLEMENT"}),
        type(NEXT_BLOCK).model_construct(
            **{**NEXT_BLOCK.model_dump(), "signals_generated": True}
        ),
    ):
        with pytest.raises((ValidationError, ValueError)):
            validate_next_block(forged)


def test_readme_adr_and_machine_readable_successor_agree_exactly():
    readme = (ROOT / "README.md").read_text()
    adr = (
        ROOT
        / "docs/adr/0005-durable-replay-persistence-custody-boundary-foundation.md"
    ).read_text()
    for document in (readme, adr):
        normalized = " ".join(document.split())
        assert NEXT_BLOCK.name.value in normalized
        assert NEXT_BLOCK.foundation_implementation.value in document
        assert NEXT_BLOCK.real_external_activation.value in document
        assert NEXT_BLOCK.operating_mode in document
        assert NEXT_BLOCK.merge_order.value in document
        assert NEXT_BLOCK.successor_pr in document
    assert "new PR" in readme and "new PR" in adr


def test_next_foundation_preserves_all_frozen_safety_states():
    assert NEXT_BLOCK.gate_states == tuple(
        (gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate
    )
    assert len(NEXT_BLOCK.gate_states) == 10
    assert NEXT_BLOCK.trust_root == "NOT_PROVISIONED"
    assert NEXT_BLOCK.durable_replay == "NOT_PROVISIONED"
    assert NEXT_BLOCK.independent_verifier == "NOT_PROVISIONED"
    assert NEXT_BLOCK.real_route == "QVM_NOT_READY"
    assert NEXT_BLOCK.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert NEXT_BLOCK.trade_decision == "NO_TRADE"
    assert NEXT_BLOCK.signals_generated is False
    assert NEXT_BLOCK.live_execution_enabled is False
    assert NEXT_BLOCK.backtesting == "NOT_AUTHORIZED"
