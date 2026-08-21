import json
from pathlib import Path

import pandas as pd
import pytest

from factors.quality import QUALITY_CONTRACT, evaluate_quality_metrics
from fundamentals.formulas import free_cash_flow, positive_denominator_ratio, ratio, roic_v1
from research.datasets import DatasetVersionError, file_sha256
from research.quality_runner import run_quality_experiment
from research.registry import DatasetRegistration, ResearchExperiment, ResearchRegistry


def _lineage(metric: str) -> str:
    return json.dumps(
        [
            {
                "metric": metric,
                "source": "sec_fixture",
                "available_at": "2025-03-01T00:00:00+00:00",
                "fiscal_period_end": "2024-12-31",
            }
        ]
    )


def _metrics() -> pd.DataFrame:
    rows = []
    values = {
        "roic_v1": (0.10, 0.14),
        "free_cash_flow_margin": (0.12, 0.16),
        "cfo_to_net_income": (1.1, 1.2),
        "net_debt_to_ebitda": (1.8, 1.5),
        "accrual_ratio": (0.03, 0.02),
    }
    for metric, history in values.items():
        for period_end, value in zip(("2023-12-31", "2024-12-31"), history, strict=True):
            rows.append(
                {
                    "symbol": "AAA",
                    "fiscal_period_end": period_end,
                    "period_type": "duration",
                    "period_basis": "period (not annualized)",
                    "metric": metric,
                    "value": value,
                    "status": "PASS",
                    "reason": None,
                    "confidence": 0.95,
                    "input_lineage": _lineage(metric),
                }
            )
    return pd.DataFrame(rows)


def _registered(tmp_path: Path) -> tuple[Path, ResearchExperiment, Path]:
    dataset_path = tmp_path / "financial_metrics.csv"
    _metrics().to_csv(dataset_path, index=False)
    dataset = DatasetRegistration(
        dataset_id="financial-intelligence-metrics",
        snapshot_id="financial-2024-12-31",
        path=dataset_path.name,
        sha256=file_sha256(dataset_path),
        lineage=("Financial Intelligence/financial_metrics.csv",),
    )
    experiment = ResearchExperiment(
        experiment_id="quality-001",
        experiment_version="1.0",
        hypothesis=QUALITY_CONTRACT.hypothesis,
        outcome_metric="quality_metric_coverage",
        universe="Governed test universe",
        universe_snapshot_id="universe-2024-12-31",
        ruleset_version="universe-v1",
        sample_start="2023-01-01",
        sample_end="2024-12-31",
        preregistered_at="2025-01-01T00:00:00Z",
        created_at="2025-01-01T00:00:00Z",
        metrics_evaluated=tuple(item.name for item in QUALITY_CONTRACT.definitions),
        expected_result="Individual Quality metrics are reproducible.",
        observed_result="PENDING",
        decision="REVIEW",
        status="READY",
        datasets=(dataset,),
        data_lineage=("Financial Intelligence", "Research Environment"),
    )
    registry_path = tmp_path / "registry.jsonl"
    ResearchRegistry(registry_path).register(experiment)
    return registry_path, experiment, dataset_path


def test_financial_formulas_used_by_quality_are_correct() -> None:
    assert roic_v1(20, 0.25, 30, 100, 10).value == pytest.approx(0.125)
    assert ratio(24, 20, denominator_name="net_income").value == pytest.approx(1.2)
    fcf = free_cash_flow(30, 10)
    assert ratio(fcf.value, 100, denominator_name="revenue").value == pytest.approx(0.2)
    assert positive_denominator_ratio(15, 10, denominator_name="ebitda").value == pytest.approx(1.5)


def test_quality_returns_individual_metrics_and_stability_without_score() -> None:
    result = evaluate_quality_metrics(
        _metrics(),
        experiment_id="quality-001",
        dataset_lineage={"snapshot_id": "financial-2024-12-31"},
    )
    values = result.metrics.set_index("metric")["value"].to_dict()
    assert values["roic"] == pytest.approx(0.14)
    assert values["cfo_conversion"] == pytest.approx(1.2)
    assert values["fcf_margin"] == pytest.approx(0.16)
    assert values["net_debt_to_ebitda"] == pytest.approx(1.5)
    assert values["accrual_quality"] == pytest.approx(0.02)
    assert values["roic_stability"] == pytest.approx(0.02)
    assert values["margin_stability"] == pytest.approx(0.02)
    assert "score" not in result.metrics.columns
    assert result.health["composite_score_calculated"] is False


def test_missing_low_confidence_and_incompatible_periods_are_explicit() -> None:
    metrics = _metrics()
    metrics.loc[metrics["metric"] == "cfo_to_net_income", ["value", "status", "reason"]] = [
        None,
        "MISSING",
        "missing inputs: net_income",
    ]
    metrics.loc[metrics["metric"] == "roic_v1", "confidence"] = 0.4
    metrics.loc[
        (metrics["metric"] == "free_cash_flow_margin")
        & (metrics["fiscal_period_end"] == "2023-12-31"),
        "period_basis",
    ] = "ttm"
    result = evaluate_quality_metrics(
        metrics, experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    ).metrics.set_index("metric")
    assert result.loc["cfo_conversion", "status"] == "MISSING"
    assert result.loc["roic", "status"] == "LOW_CONFIDENCE"
    assert result.loc["roic_stability", "status"] == "LOW_CONFIDENCE"
    assert result.loc["margin_stability", "status"] == "NOT_COMPUTED"
    assert "incompatible periods" in result.loc["margin_stability", "reason"]


def test_duplicate_conflict_and_pit_violation_propagate() -> None:
    metrics = _metrics()
    duplicate = metrics[
        (metrics["metric"] == "roic_v1") & (metrics["fiscal_period_end"] == "2024-12-31")
    ].copy()
    duplicate["value"] = 0.99
    metrics = pd.concat([metrics, duplicate], ignore_index=True)
    metrics.loc[
        (metrics["metric"] == "cfo_to_net_income") & (metrics["fiscal_period_end"] == "2024-12-31"),
        ["value", "status", "reason"],
    ] = [None, "NOT_COMPUTED", "PIT violation: available_at exceeds data_date"]
    result = evaluate_quality_metrics(
        metrics, experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    ).metrics.set_index("metric")
    assert result.loc["roic", "status"] == "NOT_COMPUTED"
    assert "conflicting metrics" in result.loc["roic", "reason"]
    assert result.loc["cfo_conversion", "status"] == "NOT_COMPUTED"
    assert "PIT violation" in result.loc["cfo_conversion", "reason"]


def test_quality_research_run_is_reproducible_and_auditable(tmp_path: Path) -> None:
    registry_path, experiment, _ = _registered(tmp_path)
    kwargs = {
        "registry_path": registry_path,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "output_root": tmp_path / "outputs",
        "assumptions": ("Reported periods are compared only when their bases match.",),
    }
    first = run_quality_experiment(**kwargs)
    second = run_quality_experiment(**kwargs)
    assert first.output_dir == second.output_dir
    assert first.research_run == second.research_run
    run = json.loads((first.output_dir / "quality_research_run.json").read_text())
    assert run["universe_snapshot_id"] == "universe-2024-12-31"
    assert run["quality_ruleset_version"] == "quality-v1.1"
    assert run["trade_decision"] == "NO_TRADE"
    assert run["live_execution_enabled"] is False
    assert run["composite_score_calculated"] is False
    output = pd.read_csv(first.output_dir / "quality_metrics.csv")
    assert output[["value", "status", "reason", "confidence", "lineage"]].shape[1] == 5


def test_quality_runner_rejects_dataset_mismatch(tmp_path: Path) -> None:
    registry_path, experiment, dataset_path = _registered(tmp_path)
    dataset_path.write_text(dataset_path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(DatasetVersionError, match="dataset version mismatch"):
        run_quality_experiment(
            registry_path=registry_path,
            experiment_id=experiment.experiment_id,
            experiment_version=experiment.experiment_version,
            output_root=tmp_path / "outputs",
        )


@pytest.mark.parametrize("column", ["value", "status", "reason", "input_lineage"])
def test_quality_rejects_missing_required_input_columns(column: str) -> None:
    with pytest.raises(ValueError, match="missing quality input columns"):
        evaluate_quality_metrics(
            _metrics().drop(columns=column),
            experiment_id="quality-001",
            dataset_lineage={"snapshot_id": "snapshot"},
        )


def test_absent_metric_is_emitted_as_missing() -> None:
    metrics = _metrics()[lambda frame: frame["metric"] != "net_debt_to_ebitda"]
    result = evaluate_quality_metrics(
        metrics,
        experiment_id="quality-001",
        dataset_lineage={"snapshot_id": "snapshot"},
    ).metrics.set_index("metric")
    assert result.loc["net_debt_to_ebitda", "status"] == "MISSING"
    assert "absent" in result.loc["net_debt_to_ebitda", "reason"]


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [(None, "MISSING_CONFIDENCE"), (float("nan"), "MISSING_CONFIDENCE"), ("bad", "LOW_CONFIDENCE"), (1.2, "LOW_CONFIDENCE")],
)
def test_missing_null_and_invalid_confidence_never_assume_full_confidence(
    confidence: object, expected: str
) -> None:
    metrics = _metrics()
    metrics["confidence"] = metrics["confidence"].astype(object)
    metrics.loc[metrics["metric"] == "roic_v1", "confidence"] = confidence
    result = evaluate_quality_metrics(
        metrics, experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    ).metrics.set_index("metric")
    assert result.loc["roic", "status"] == expected
    assert result.loc["roic", "confidence"] == 0


def test_absent_confidence_column_is_missing_confidence() -> None:
    result = evaluate_quality_metrics(
        _metrics().drop(columns="confidence"),
        experiment_id="quality-001",
        dataset_lineage={"snapshot_id": "snapshot"},
    ).metrics.set_index("metric")
    assert result.loc["roic", "status"] == "MISSING_CONFIDENCE"


@pytest.mark.parametrize("lineage", ["{broken", "", "[]", "null"])
def test_corrupt_or_empty_lineage_degrades_status(lineage: str) -> None:
    metrics = _metrics()
    metrics.loc[
        (metrics["metric"] == "roic_v1") & (metrics["fiscal_period_end"] == "2024-12-31"),
        "input_lineage",
    ] = lineage
    result = evaluate_quality_metrics(
        metrics, experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    ).metrics.set_index("metric")
    assert result.loc["roic", "status"] == "INVALID_LINEAGE"


def test_sector_foundation_and_primary_source_are_propagated() -> None:
    metrics = _metrics()
    metrics["sector"] = "Industrials"
    metrics["industry"] = "Machinery"
    metrics["sector_percentile"] = 82.0
    metrics["industry_percentile"] = 74.0
    metrics["pit_metadata"] = json.dumps({"knowledge_date": "2025-03-01"})
    row = evaluate_quality_metrics(
        metrics, experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    ).metrics.set_index("metric").loc["roic"]
    assert row["sector"] == "Industrials"
    assert row["industry_percentile"] == 74.0
    assert row["primary_source"] == "sec_fixture"
    assert row["source_available_at"] == "2025-03-01T00:00:00+00:00"
    assert row["source_fiscal_period_end"] == "2024-12-31"
    assert json.loads(row["pit_metadata"])["knowledge_date"] == "2025-03-01"


def test_persistence_metrics_are_individual_and_reproducible() -> None:
    result = evaluate_quality_metrics(
        _metrics(), experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    ).metrics.set_index("metric")
    assert result.loc["roic_consistency", "value"] == 1
    assert result.loc["roic_positive_years", "value"] == 2
    assert result.loc["fcf_consistency", "value"] == 1
    assert result.loc["fcf_positive_years", "value"] == 2
    assert result.loc["margin_persistence", "value"] == 1


def test_extreme_roic_and_metric_disagreement_emit_explanatory_warnings() -> None:
    metrics = _metrics()
    metrics.loc[
        (metrics["metric"] == "roic_v1") & (metrics["fiscal_period_end"] == "2024-12-31"),
        "value",
    ] = 1.5
    metrics.loc[
        (metrics["metric"] == "net_debt_to_ebitda")
        & (metrics["fiscal_period_end"] == "2024-12-31"),
        "value",
    ] = 5.0
    result = evaluate_quality_metrics(
        metrics, experiment_id="quality-001", dataset_lineage={"snapshot_id": "snapshot"}
    )
    row = result.metrics.set_index("metric").loc["roic"]
    warnings = json.loads(row["warnings"])
    assert row["status"] == "PASS"
    assert any("extreme ROIC" in warning for warning in warnings)
    assert "high ROIC conflicts with elevated leverage" in warnings
    assert result.health["status"] == "WARNING"
