import json
from pathlib import Path

import pytest

from research.contracts import FactorResearchInput, FactorResearchOutput, ResearchEvaluation
from research.datasets import DatasetVersionError, file_sha256
from research.registry import (
    DatasetRegistration,
    RegistryValidationError,
    ResearchExperiment,
    ResearchRegistry,
)
from research.runner import run_registered_experiment


def _experiment(dataset: DatasetRegistration, **changes: object) -> ResearchExperiment:
    values = {
        "experiment_id": "foundation-001",
        "experiment_version": "1.0",
        "hypothesis": "A future factor may have a measurable relationship with a forward outcome.",
        "outcome_metric": "future_return_placeholder",
        "universe": "Governed US common-stock universe",
        "universe_snapshot_id": "universe-2026-08-01",
        "ruleset_version": "universe-v1",
        "sample_start": "2020-01-01",
        "sample_end": "2025-12-31",
        "preregistered_at": "2026-08-20T00:00:00Z",
        "created_at": "2026-08-20T00:00:00Z",
        "metrics_evaluated": ("row_count", "missing_cells"),
        "expected_result": "Dataset contracts remain stable and reproducible.",
        "observed_result": "PENDING",
        "decision": "REVIEW",
        "status": "READY",
        "datasets": (dataset,),
        "data_lineage": ("universe snapshot", "fixture source"),
    }
    values.update(changes)
    return ResearchExperiment(**values)


def _registered(tmp_path: Path) -> tuple[Path, ResearchExperiment, Path]:
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("symbol,value\nAAPL,1\nMSFT,\n", encoding="utf-8")
    dataset = DatasetRegistration(
        dataset_id="foundation-input",
        snapshot_id="dataset-snapshot-001",
        path=dataset_path.name,
        sha256=file_sha256(dataset_path),
        lineage=("tests/fixture-generator",),
    )
    experiment = _experiment(dataset)
    registry_path = tmp_path / "registry.jsonl"
    ResearchRegistry(registry_path).register(experiment)
    return registry_path, experiment, dataset_path


def test_same_registered_input_produces_same_result_and_output(tmp_path: Path) -> None:
    registry_path, experiment, _ = _registered(tmp_path)
    first = run_registered_experiment(
        registry_path=registry_path,
        experiment_id=experiment.experiment_id,
        experiment_version=experiment.experiment_version,
        output_root=tmp_path / "outputs",
    )
    second = run_registered_experiment(
        registry_path=registry_path,
        experiment_id=experiment.experiment_id,
        experiment_version=experiment.experiment_version,
        output_root=tmp_path / "outputs",
    )
    assert first.output_dir == second.output_dir
    assert first.research_run == second.research_run
    assert first.research_run["health"] == "PASS"
    assert first.research_run["metrics"]["datasets"][0]["rows"] == 2
    assert first.research_run["metrics"]["datasets"][0]["missing_cells"] == 1
    assert first.research_run["trade_decision"] == "NO_TRADE"
    assert first.research_run["live_execution_enabled"] is False
    assert first.research_run["factor_calculations_performed"] is False
    assert json.loads((first.output_dir / "research_config.json").read_text())["experiment"]


def test_dataset_version_mismatch_can_fail_or_warn(tmp_path: Path) -> None:
    registry_path, experiment, dataset_path = _registered(tmp_path)
    dataset_path.write_text("symbol,value\nAAPL,2\n", encoding="utf-8")
    with pytest.raises(DatasetVersionError, match="dataset version mismatch"):
        run_registered_experiment(
            registry_path=registry_path,
            experiment_id=experiment.experiment_id,
            experiment_version=experiment.experiment_version,
            output_root=tmp_path / "fail-output",
        )
    warned = run_registered_experiment(
        registry_path=registry_path,
        experiment_id=experiment.experiment_id,
        experiment_version=experiment.experiment_version,
        output_root=tmp_path / "warn-output",
        mismatch_policy="warn",
    )
    assert warned.research_run["health"] == "WARNING"
    assert "dataset version mismatch" in warned.research_run["warnings"][0]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"hypothesis": ""}, "missing registry fields"),
        ({"status": "RUNNING"}, "invalid experiment state"),
        ({"status": "COMPLETED"}, "cannot be executed"),
        ({"data_lineage": ()}, "missing registry fields"),
    ],
)
def test_registry_rejects_missing_fields_invalid_states_and_lineage(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    _, experiment, _ = _registered(tmp_path)
    invalid = _experiment(experiment.datasets[0], **changes)
    with pytest.raises(RegistryValidationError, match=message):
        invalid.validate(phase4=True)


def test_dataset_registration_rejects_incomplete_lineage(tmp_path: Path) -> None:
    _, experiment, _ = _registered(tmp_path)
    incomplete = DatasetRegistration(
        dataset_id="input",
        snapshot_id="snapshot",
        path="dataset.csv",
        sha256=experiment.datasets[0].sha256,
        lineage=(),
    )
    with pytest.raises(RegistryValidationError, match="incomplete lineage"):
        _experiment(incomplete).validate(phase4=True)


def test_factor_research_contracts_define_boundaries_without_factor_logic() -> None:
    inputs = FactorResearchInput(
        experiment_id="foundation-001",
        experiment_version="1.0",
        universe_snapshot_id="universe-2026-08-01",
        ruleset_version="universe-v1",
        dataset_snapshot_ids=("dataset-snapshot-001",),
        analysis_start="2020-01-01",
        analysis_end="2025-12-31",
        lineage=("registry/foundation-001/1.0",),
    )
    outputs = FactorResearchOutput(
        experiment_id=inputs.experiment_id,
        observations=0,
        metrics={"coverage": None},
    )
    evaluation = ResearchEvaluation(
        health="PASS",
        expected_result="Contract is reproducible.",
        observed_result="Contract validated; no factor calculated.",
        decision="REVIEW",
        metrics=outputs.metrics,
    )
    fields = set(FactorResearchOutput.model_fields)
    assert not {"quality", "value", "momentum", "score", "rank", "signal"} & fields
    assert evaluation.decision == "REVIEW"
