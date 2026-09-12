import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from governance.phase7e import EvidenceGate, GateState
from governance.roadmap import NEXT_BLOCK
from research.data_grade import (
    ResearchBacktestingAuthorization,
    ResearchDataGrade,
    ResearchGradeAdmission,
    assess_research_grade,
    require_production_grade,
)
from research.registry import DatasetRegistration


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registration(path: Path, sha256: str | None = None) -> DatasetRegistration:
    return DatasetRegistration(
        dataset_id="qvm-research-dataset",
        snapshot_id="qvm-research-dataset-2026-09-11",
        path=path.name,
        sha256=sha256 or _sha256(path),
        lineage=("caller text is not proof",),
    )


def _universe_snapshot(root: Path) -> Path:
    directory = root / "universe"
    directory.mkdir()
    membership = directory / "universe_membership.csv"
    validation = directory / "universe_validation.json"
    membership.write_text("symbol,as_of\nAAA,2025-01-01\n", encoding="utf-8")
    validation.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    metadata = {
        "as_of": "2025-01-01",
        "membership_sha256": _sha256(membership),
        "validation_sha256": _sha256(validation),
        "ruleset": {"version": "test-v1"},
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
    (directory / "snapshot_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return directory


def test_random_registered_hash_cannot_authorize(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    result = assess_research_grade(_registration(dataset, "a" * 64), registry_root=tmp_path)
    assert result.research_data_grade is ResearchDataGrade.FAILED_RESEARCH_DATA
    assert "dataset_identity_checksums:failed:" in result.reasons[0]
    assert result.research_backtesting_authorization is (
        ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_NOT_AUTHORIZED
    )


def test_content_mutation_after_registration_fails(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    registration = _registration(dataset)
    dataset.write_text("value\n2\n", encoding="utf-8")
    result = assess_research_grade(registration, registry_root=tmp_path)
    assert result.research_data_grade is ResearchDataGrade.FAILED_RESEARCH_DATA


def test_valid_canonical_artifacts_remain_insufficient_until_every_control_is_verified(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    result = assess_research_grade(
        _registration(dataset),
        registry_root=tmp_path,
        universe_snapshot_dir=_universe_snapshot(tmp_path),
    )
    assert result.research_data_grade is ResearchDataGrade.INSUFFICIENT_RESEARCH_DATA
    assert result.research_backtesting_authorization is (
        ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_NOT_AUTHORIZED
    )
    assert "provenance_lineage:not_content_bound" in result.reasons
    assert "reproducibility:not_canonically_verifiable" in result.reasons
    assert "restatement_handling:applicability_not_canonically_verifiable" in result.reasons
    assert "corporate_action_handling:applicability_not_canonically_verifiable" in result.reasons


def test_missing_universe_proof_fails_closed(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    result = assess_research_grade(_registration(dataset), registry_root=tmp_path)
    assert result.research_data_grade is ResearchDataGrade.INSUFFICIENT_RESEARCH_DATA
    assert "universe_survivorship:verified_snapshot_required" in result.reasons


def test_caller_cannot_construct_research_grade_authorization() -> None:
    with pytest.raises(ValidationError, match="unavailable until every control"):
        ResearchGradeAdmission(
            dataset_id="forged",
            snapshot_id="forged",
            research_data_grade="RESEARCH_GRADE",
            research_backtesting_authorization="RESEARCH_BACKTESTING_AUTHORIZED",
            reasons=(),
            permitted_consumers=("RESEARCH", "RESEARCH_BACKTESTING"),
        )


def test_admission_cannot_be_forged_into_production_or_execution_authority(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    admission = assess_research_grade(_registration(dataset), registry_root=tmp_path)
    for field, value in (
        ("production_grade", True),
        ("implicit_production_promotion", True),
        ("portfolio_authorized", True),
        ("execution_authorized", True),
        ("signals_generated", True),
        ("live_execution_enabled", True),
    ):
        with pytest.raises(ValidationError):
            ResearchGradeAdmission.model_validate(admission.model_dump() | {field: value})
    with pytest.raises(TypeError, match="never valid production"):
        require_production_grade(admission)


def test_research_contract_does_not_change_step6_or_production_backtesting(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")
    assess_research_grade(_registration(dataset), registry_root=tmp_path)
    assert NEXT_BLOCK.backtesting == "NOT_AUTHORIZED"
    assert NEXT_BLOCK.real_route == "QVM_NOT_READY"
    assert NEXT_BLOCK.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert NEXT_BLOCK.trade_decision == "NO_TRADE"
    assert not NEXT_BLOCK.signals_generated and not NEXT_BLOCK.live_execution_enabled
    assert NEXT_BLOCK.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
