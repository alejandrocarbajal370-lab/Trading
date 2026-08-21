import json
from pathlib import Path

import pandas as pd
import pytest

from factors.value import VALUE_CONTRACT, evaluate_value_metrics
from research.datasets import file_sha256
from research.registry import DatasetRegistration, ResearchExperiment, ResearchRegistry
from research.value_runner import run_value_experiment


def _lineage(metric: str) -> str:
    return json.dumps([{
        "metric": metric,
        "source": "sec_fixture",
        "available_at": "2025-03-01T00:00:00+00:00",
        "fiscal_period_end": "2024-12-31",
    }])


def _metrics() -> pd.DataFrame:
    values = {
        "free_cash_flow": 10.0,
        "earnings": 8.0,
        "ebit": 12.0,
        "ebitda": 15.0,
        "market_cap": 100.0,
        "enterprise_value": 120.0,
    }
    rows = []
    for metric, value in values.items():
        instant = metric in {"market_cap", "enterprise_value"}
        rows.append({
            "symbol": "AAA",
            "valuation_as_of": "2025-03-15",
            "fiscal_period_end": "2024-12-31",
            "period_basis": "INSTANT" if instant else "TTM",
            "metric": metric,
            "value": value,
            "unit": "currency",
            "currency": "USD",
            "available_at": "2025-03-01T00:00:00+00:00",
            "status": "PASS",
            "reason": None,
            "confidence": 0.95,
            "input_lineage": _lineage(metric),
            "industry": "Machinery",
        })
    return pd.DataFrame(rows)


def _evaluate(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    return evaluate_value_metrics(
        _metrics() if frame is None else frame,
        experiment_id="value-001",
        dataset_lineage={"snapshot_id": "financial-2024-12-31"},
    ).metrics.set_index("metric")


def test_core_metrics_are_individual_and_absolute_only() -> None:
    result = _evaluate()
    assert result.loc["fcf_yield", "value"] == pytest.approx(0.10)
    assert result.loc["earnings_yield", "value"] == pytest.approx(0.08)
    assert result.loc["ebit_yield", "value"] == pytest.approx(0.10)
    assert result.loc["ev_to_ebit", "value"] == pytest.approx(10.0)
    assert result.loc["ev_to_ebitda", "value"] == pytest.approx(8.0)
    assert set(result["value_category"]) == {"ABSOLUTE"}
    assert "score" not in result.columns
    assert VALUE_CONTRACT.relative_value_mode == "metadata_only"


def test_wrong_currency_fails_closed() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "market_cap", "currency"] = "EUR"
    assert _evaluate(frame).loc["fcf_yield", "status"] == "INVALID_CURRENCY"


def test_negative_fcf_is_warning_not_normal_signal() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "free_cash_flow", "value"] = -10.0
    row = _evaluate(frame).loc["fcf_yield"]
    assert row["value"] == pytest.approx(-0.1)
    assert row["status"] == "WARNING"
    assert "not a normal value signal" in row["reason"]


def test_zero_market_cap_fails_closed() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "market_cap", "value"] = 0.0
    assert _evaluate(frame).loc["earnings_yield", "status"] == "INVALID_DENOMINATOR"


def test_invalid_enterprise_value_fails_all_ev_metrics() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "enterprise_value", "value"] = -1.0
    result = _evaluate(frame)
    assert (result.loc[["ebit_yield", "ev_to_ebit", "ev_to_ebitda"], "status"] == "INVALID_DENOMINATOR").all()


def test_period_mismatch_fails_closed() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "earnings", "period_basis"] = "QUARTER"
    assert _evaluate(frame).loc["earnings_yield", "status"] == "PERIOD_MISMATCH"


@pytest.mark.parametrize(
    ("column", "expected"),
    [("input_lineage", "INVALID_LINEAGE"), ("confidence", "MISSING_CONFIDENCE")],
)
def test_missing_governance_fields_fail_closed(column: str, expected: str) -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "earnings", column] = None
    assert _evaluate(frame).loc["earnings_yield", "status"] == expected


def test_pit_violation_fails_closed() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "free_cash_flow", "available_at"] = "2025-04-01T00:00:00+00:00"
    assert _evaluate(frame).loc["fcf_yield", "status"] == "PIT_VIOLATION"


def test_restricted_industry_blocks_ev_but_not_market_cap_metrics() -> None:
    frame = _metrics()
    frame["industry"] = "Banking"
    result = _evaluate(frame)
    assert result.loc["fcf_yield", "status"] == "PASS"
    assert result.loc["ebit_yield", "status"] == "INDUSTRY_RESTRICTED"
    assert result.loc["ev_to_ebit", "status"] == "INDUSTRY_RESTRICTED"


def test_outlier_valuation_is_warning() -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == "ebit", "value"] = 0.5
    row = _evaluate(frame).loc["ev_to_ebit"]
    assert row["value"] == pytest.approx(240.0)
    assert row["status"] == "WARNING"
    assert "extreme" in row["reason"]


def _registered(tmp_path: Path) -> tuple[Path, ResearchExperiment]:
    dataset_path = tmp_path / "value_inputs.csv"
    _metrics().to_csv(dataset_path, index=False)
    registration = DatasetRegistration(
        dataset_id="value-financial-inputs",
        snapshot_id="value-2024-12-31",
        path=dataset_path.name,
        sha256=file_sha256(dataset_path),
        lineage=("Financial Intelligence",),
    )
    experiment = ResearchExperiment(
        experiment_id="value-001",
        experiment_version="1.0",
        hypothesis=VALUE_CONTRACT.hypothesis,
        outcome_metric="individual_value_metric_coverage",
        universe="Governed test universe",
        universe_snapshot_id="universe-2024-12-31",
        ruleset_version="universe-v1",
        sample_start="2024-01-01",
        sample_end="2024-12-31",
        preregistered_at="2025-01-01T00:00:00Z",
        created_at="2025-01-01T00:00:00Z",
        metrics_evaluated=tuple(item.name for item in VALUE_CONTRACT.definitions),
        expected_result="Individual Value metrics are reproducible.",
        observed_result="PENDING",
        decision="REVIEW",
        status="READY",
        datasets=(registration,),
        data_lineage=("Financial Intelligence", "Research Environment"),
    )
    registry_path = tmp_path / "registry.jsonl"
    ResearchRegistry(registry_path).register(experiment)
    return registry_path, experiment


def test_value_run_is_reproducible_and_writes_governed_outputs(tmp_path: Path) -> None:
    registry_path, experiment = _registered(tmp_path)
    kwargs = {
        "registry_path": registry_path,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "output_root": tmp_path / "outputs",
    }
    first = run_value_experiment(**kwargs)
    second = run_value_experiment(**kwargs)
    assert first.output_dir == second.output_dir
    assert first.research_run == second.research_run
    for name in ("value_metrics.csv", "value_health.json", "value_lineage.json", "value_validation_report.json"):
        assert (first.output_dir / name).is_file()
    assert first.research_run["trade_decision"] == "NO_TRADE"
    assert first.research_run["live_execution_enabled"] is False
    assert first.research_run["composite_score_calculated"] is False
