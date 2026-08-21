import datetime
import json
from pathlib import Path

import pandas as pd
import pytest

from core.phase36 import run_phase36
from factors.value import VALUE_CONTRACT, evaluate_value_metrics
from research.datasets import DatasetVersionError, file_sha256
from research.registry import DatasetRegistration, ResearchExperiment, ResearchRegistry
from research.value_runner import run_value_experiment
from universe.validation import UniverseRules


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


@pytest.mark.parametrize(
    ("input_metric", "output_metric", "reason"),
    [
        ("earnings", "earnings_yield", "negative earnings"),
        ("ebit", "ebit_yield", "negative EBIT"),
        ("ebit", "ev_to_ebit", "economically uninterpretable"),
    ],
)
def test_negative_economics_are_explicit_warnings(
    input_metric: str, output_metric: str, reason: str
) -> None:
    frame = _metrics()
    frame.loc[frame["metric"] == input_metric, "value"] = -10.0
    row = _evaluate(frame).loc[output_metric]
    assert row["status"] == "WARNING"
    assert reason in row["reason"]


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


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan")])
def test_low_confidence_threshold_must_be_a_probability(threshold: float) -> None:
    with pytest.raises(ValueError, match="low_confidence_threshold"):
        evaluate_value_metrics(
            _metrics(),
            experiment_id="value-001",
            dataset_lineage={"snapshot_id": "financial-2024-12-31"},
            low_confidence_threshold=threshold,
        )


def test_invalid_valuation_date_names_the_correct_field() -> None:
    frame = _metrics()
    frame["valuation_as_of"] = "not-a-date"
    with pytest.raises(ValueError, match="invalid valuation_as_of"):
        _evaluate(frame)


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


def _governed_universe(tmp_path: Path) -> Path:
    source = tmp_path / "universe.csv"
    pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Industrials",
                "industry": "Machinery",
                "market_cap": 100.0,
                "average_volume": 1_000_000,
                "average_dollar_volume": 20_000_000,
                "listing_date": "2020-01-01T00:00:00Z",
                "source": "fixture",
                "source_timestamp": "2024-12-30T00:00:00Z",
                "available_at": "2024-12-30T00:00:00Z",
            }
        ]
    ).to_csv(source, index=False)
    return run_phase36(
        source_path=source,
        rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=datetime.datetime(2024, 12, 31, tzinfo=datetime.UTC),
        output_root=tmp_path / "universe_validation",
        snapshot_root=tmp_path / "universe_snapshots",
    ).snapshot_dir


def test_value_run_is_reproducible_and_writes_governed_outputs(tmp_path: Path) -> None:
    registry_path, experiment = _registered(tmp_path)
    universe_snapshot_dir = _governed_universe(tmp_path)
    kwargs = {
        "registry_path": registry_path,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "output_root": tmp_path / "outputs",
        "universe_snapshot_dir": universe_snapshot_dir,
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
    assert first.research_run["universe_governance"]["verified"] is True
    assert first.research_run["universe_governance"]["snapshot_id"] == "universe-2024-12-31"
    assert first.research_run["runtime_environment"]["python"]


def test_value_run_fails_closed_with_audit_when_universe_does_not_match(
    tmp_path: Path,
) -> None:
    registry_path, experiment = _registered(tmp_path)
    universe_snapshot_dir = _governed_universe(tmp_path)
    metadata_path = universe_snapshot_dir / "snapshot_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["as_of"] = "2024-12-30T00:00:00+00:00"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(DatasetVersionError, match="snapshot_id does not match"):
        run_value_experiment(
            registry_path=registry_path,
            experiment_id=experiment.experiment_id,
            experiment_version=experiment.experiment_version,
            output_root=tmp_path / "outputs",
            universe_snapshot_dir=universe_snapshot_dir,
        )
    audits = list((tmp_path / "outputs").glob("*_value_failed_*/value_governance_audit.json"))
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    assert audit["status"] == "FAIL"
    assert audit["trade_decision"] == "NO_TRADE"
    assert audit["live_execution_enabled"] is False
