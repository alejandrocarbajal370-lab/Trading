from pathlib import Path

import pytest
from pydantic import ValidationError

from governance.phase7e import EvidenceGate, GateState
from governance.roadmap import (
    AFTER_NEXT_BLOCK,
    FUTURE_TAX_AWARE_CAPABILITY,
    NEXT_BLOCK,
    ImplementationAuthorization,
    MergeOrder,
    NextBlockScope,
    RoadmapBlock,
    TaxAwareDependency,
    TaxAwareScope,
    TaxLotContractField,
    validate_next_block,
)

ROOT = Path(__file__).resolve().parents[1]


def test_external_authenticity_foundation_follows_the_completed_probe():
    assert (
        NEXT_BLOCK.name
        == RoadmapBlock.IBKR_OBSERVATION_EXTERNAL_AUTHENTICITY_FOUNDATION
    )
    assert (
        NEXT_BLOCK.current_block
        == RoadmapBlock.IBKR_REPRODUCIBLE_READ_ONLY_LOCAL_OBSERVATION_PROBE
    )
    assert NEXT_BLOCK.current_block.value != NEXT_BLOCK.name.value
    assert (
        NEXT_BLOCK.foundation_implementation
        == ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT
    )
    assert NEXT_BLOCK.implementation_authorized is True
    assert NEXT_BLOCK.real_external_activation == ImplementationAuthorization.NOT_AUTHORIZED
    assert NEXT_BLOCK.activation_real is False
    assert NEXT_BLOCK.operating_mode == "CONTRACT_TEST_ONLY"
    assert NEXT_BLOCK.operating_mode_real is False
    assert NEXT_BLOCK.merge_order == MergeOrder.AFTER_CURRENT_BLOCK_MERGED
    assert NEXT_BLOCK.successor_pr == "NEW_PR_REQUIRED"
    assert NEXT_BLOCK.scope == tuple(NextBlockScope)
    assert NEXT_BLOCK.evidence_states == ("OBSERVED_UNTRUSTED",)


def test_roadmap_rejects_self_reference_or_missing_foundation_authorization():
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
        / "docs/adr/0012-ibkr-observation-external-authenticity-foundation.md"
    ).read_text()
    for document in (readme, adr):
        normalized = " ".join(document.split())
        assert NEXT_BLOCK.name.value in normalized
        assert NEXT_BLOCK.foundation_implementation.value in document
        assert NEXT_BLOCK.real_external_activation.value in document
        assert NEXT_BLOCK.operating_mode in document
        assert NEXT_BLOCK.merge_order.value in document
        assert NEXT_BLOCK.successor_pr in document
    assert "exact `NEXT_BLOCK`" in readme
    assert "machine-readable successor" in adr


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


def test_successor_after_authorized_foundation_is_undetermined_and_unauthorized():
    assert AFTER_NEXT_BLOCK.after == NEXT_BLOCK.name
    assert AFTER_NEXT_BLOCK.name == "UNDETERMINED"
    assert AFTER_NEXT_BLOCK.implementation_authorized is False
    assert AFTER_NEXT_BLOCK.activation_real is False
    assert AFTER_NEXT_BLOCK.decision_state == "ARCHITECTURAL_DECISION_REQUIRED"


def test_tax_aware_governance_is_future_only_and_does_not_replace_next_block():
    capability = FUTURE_TAX_AWARE_CAPABILITY
    assert capability.name == RoadmapBlock.TAX_LOT_TAX_AWARE_PORTFOLIO_GOVERNANCE
    assert capability.current_next_block is False
    assert capability.name != NEXT_BLOCK.name
    assert capability.implementation_authorized is False
    assert capability.activation_authorized is False
    assert capability.dependencies == tuple(TaxAwareDependency)
    assert capability.scope == tuple(TaxAwareScope)
    assert capability.contract_fields == tuple(TaxLotContractField)


def test_tax_aware_governance_cannot_precede_readiness_or_enable_trading():
    capability = FUTURE_TAX_AWARE_CAPABILITY
    assert capability.dependencies == (
        TaxAwareDependency.REAL_PROVIDER_DATA_OBSERVED_VERIFIED_ADMITTED,
        TaxAwareDependency.REAL_QVM_SCORING_GOVERNED_READY,
        TaxAwareDependency.BACKTESTING_AUTHORIZED_VALIDATED,
    )
    assert capability.required_before == ("PORTFOLIO_OPTIMIZER_REBALANCE_LIVE",)
    assert capability.enables_trading is False
    assert capability.trade_decision == "NO_TRADE"
    assert capability.signals_generated is False
    assert capability.live_execution_enabled is False

    raw = capability.model_dump(mode="python")
    raw["dependencies"] = raw["dependencies"][:-1]
    with pytest.raises(ValidationError):
        type(capability).model_validate(raw)

    raw = capability.model_dump(mode="python")
    raw["activation_authorized"] = True
    with pytest.raises(ValidationError):
        type(capability).model_validate(raw)


def test_tax_aware_documentation_matches_machine_readable_scope():
    document = (ROOT / "docs/tax_aware_portfolio_governance.md").read_text()
    normalized = " ".join(document.split())
    assert FUTURE_TAX_AWARE_CAPABILITY.name.value in normalized
    assert FUTURE_TAX_AWARE_CAPABILITY.status.value in document
    for dependency in TaxAwareDependency:
        assert f"`{dependency.value}`" in document
    for scope in TaxAwareScope:
        assert f"`{scope.value}`" in document
    for field in TaxLotContractField:
        assert f"`{field.value}`" in document
    assert "tax_estimate" in document and "tax_filing_truth" in document
