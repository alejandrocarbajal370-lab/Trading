import pytest
from pydantic import ValidationError

from governance.phase7e import EvidenceGate, GateState
from governance.roadmap import NEXT_BLOCK
from research.data_grade import (
    ResearchBacktestingAuthorization,
    ResearchDataGrade,
    ResearchGradeAdmission,
    ResearchGradeEvidence,
    assess_research_grade,
    require_production_grade,
)


def _evidence(**changes: object) -> ResearchGradeEvidence:
    values = {
        "dataset_id": "qvm-research-dataset",
        "snapshot_id": "qvm-research-dataset-2026-09-11",
        "dataset_checksums": ("a" * 64, "b" * 64),
        "lineage": ("governed universe", "PIT accounting", "PIT prices and FX"),
        "reproducibility_fingerprint": "c" * 64,
        "pit_no_lookahead": "SATISFIED",
        "provenance_lineage": "SATISFIED",
        "dataset_identity_checksums": "SATISFIED",
        "reproducibility": "SATISFIED",
        "restatement_handling": "SATISFIED",
        "universe_survivorship": "SATISFIED",
        "corporate_action_handling": "SATISFIED",
        "no_silent_imputation": "SATISFIED",
    }
    values.update(changes)
    return ResearchGradeEvidence.model_validate(values)


def test_complete_evidence_authorizes_only_research_backtesting() -> None:
    result = assess_research_grade(_evidence())
    assert result.research_data_grade is ResearchDataGrade.RESEARCH_GRADE
    assert result.research_backtesting_authorization is (
        ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_AUTHORIZED
    )
    assert result.permitted_consumers == ("RESEARCH", "RESEARCH_BACKTESTING")
    assert not result.production_grade
    assert not result.portfolio_authorized and not result.execution_authorized
    assert result.trade_decision == "NO_TRADE" and not result.signals_generated
    assert result.execution_authority == "HUMAN_ONLY"
    assert result.human_execution_required and not result.live_execution_enabled


@pytest.mark.parametrize("state", ["INSUFFICIENT", "FAILED"])
def test_missing_or_failed_control_denies_research_backtesting(state: str) -> None:
    result = assess_research_grade(_evidence(pit_no_lookahead=state))
    expected = (
        ResearchDataGrade.FAILED_RESEARCH_DATA
        if state == "FAILED"
        else ResearchDataGrade.INSUFFICIENT_RESEARCH_DATA
    )
    assert result.research_data_grade is expected
    assert result.research_backtesting_authorization is (
        ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_NOT_AUTHORIZED
    )
    assert result.permitted_consumers == ("RESEARCH",)
    assert result.reasons == (f"pit_no_lookahead:{state}",)


def test_conditional_controls_may_be_explicitly_not_required() -> None:
    result = assess_research_grade(
        _evidence(restatement_handling="NOT_REQUIRED", corporate_action_handling="NOT_REQUIRED")
    )
    assert result.research_data_grade is ResearchDataGrade.RESEARCH_GRADE


def test_mandatory_control_cannot_be_declared_not_required() -> None:
    with pytest.raises(ValidationError, match="mandatory research controls"):
        _evidence(no_silent_imputation="NOT_REQUIRED")


def test_admission_cannot_be_forged_into_production_or_execution_authority() -> None:
    admitted = assess_research_grade(_evidence())
    for field, value in (
        ("production_grade", True),
        ("implicit_production_promotion", True),
        ("portfolio_authorized", True),
        ("execution_authorized", True),
        ("signals_generated", True),
        ("live_execution_enabled", True),
    ):
        with pytest.raises(ValidationError):
            ResearchGradeAdmission.model_validate(admitted.model_dump() | {field: value})
    with pytest.raises(TypeError, match="never valid production"):
        require_production_grade(admitted)


def test_research_contract_does_not_change_step6_or_production_backtesting() -> None:
    assess_research_grade(_evidence())
    assert NEXT_BLOCK.backtesting == "NOT_AUTHORIZED"
    assert NEXT_BLOCK.real_route == "QVM_NOT_READY"
    assert NEXT_BLOCK.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert NEXT_BLOCK.trade_decision == "NO_TRADE"
    assert not NEXT_BLOCK.signals_generated and not NEXT_BLOCK.live_execution_enabled
    assert NEXT_BLOCK.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
