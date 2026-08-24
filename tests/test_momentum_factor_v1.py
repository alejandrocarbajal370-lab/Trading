import datetime
import json
from pathlib import Path
from typing import Self

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from core.phase36 import run_phase36
from data.connectors.alpha_vantage import AlphaVantageMomentumHistoricalPriceSource
from data.market_calendar import get_trading_calendar
from factors.momentum import MOMENTUM_CONTRACT, MomentumFactorContract, evaluate_momentum_metrics
from research.datasets import file_sha256
from research.momentum_runner import run_momentum_experiment
from research.registry import DatasetRegistration, ResearchExperiment, ResearchRegistry
from universe.validation import UniverseRules

AS_OF = datetime.date(2025, 1, 31)


def _prices() -> pd.DataFrame:
    dates = pd.to_datetime(
        get_trading_calendar("XNYS").sessions(datetime.date(2023, 12, 20), AS_OF)
    )
    rows = []
    for symbol, daily_growth in (("AAA", 0.001), ("SPY", 0.0004)):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "date": date.date().isoformat(),
                    "adjusted_close": 100.0 * (1 + daily_growth) ** index,
                    "raw_close": 100.0 * (1 + daily_growth) ** index,
                    "currency": "USD",
                    "available_at": f"{date.date().isoformat()}T22:00:00+00:00",
                    "confidence": 0.95,
                    "input_lineage": json.dumps([{"source": "price_fixture", "series": symbol}]),
                    "price_basis": "ADJUSTED",
                    "corporate_action_status": "NONE",
                    "trading_calendar": "XNYS",
                    "session_status": "PRESENT",
                    "timing_policy": "EOD_CLOSE_T_PLUS_0",
                    "historical_provider": "fixture_provider",
                    "historical_dataset": "adjusted_daily_history",
                    "historical_dataset_version": "fixture-v1",
                    "historical_access_tier": "offline_fixture",
                }
            )
    return pd.DataFrame(rows)


def _evaluate(frame: pd.DataFrame | None = None):
    return evaluate_momentum_metrics(
        _prices() if frame is None else frame,
        experiment_id="momentum-001",
        dataset_lineage={"snapshot_id": "prices-2025-01-31"},
        as_of=AS_OF,
        benchmark_symbol="SPY",
    )


def test_individual_metrics_are_calculated_without_score_or_ranking() -> None:
    evaluation = _evaluate()
    result = evaluation.metrics.set_index("metric")
    assert set(result.index) == {definition.name for definition in MOMENTUM_CONTRACT.definitions}
    assert result.loc["momentum_12_1", "value"] > result.loc["momentum_6m", "value"] > 0
    assert result.loc["relative_strength_6m", "value"] > 0
    assert result.loc["volatility_adjusted_momentum_12_1", "status"] == "PASS"
    assert result.loc["trend_stability_12m", "value"] == pytest.approx(1.0, abs=5e-5)
    assert "score" not in result.columns
    assert evaluation.health["ranking_calculated"] is False
    assert evaluation.health["trade_decision"] == "NO_TRADE"
    assert evaluation.health["live_execution_enabled"] is False


def test_12_1_excludes_last_month() -> None:
    frame = _prices()
    aaa_tail = frame.index[frame["symbol"] == "AAA"][-21:]
    frame.loc[aaa_tail, "adjusted_close"] *= 10
    assert _evaluate(frame).metrics.set_index("metric").loc[
        "momentum_12_1", "value"
    ] == pytest.approx(_evaluate().metrics.set_index("metric").loc["momentum_12_1", "value"])


def test_relative_strength_uses_configured_benchmark() -> None:
    frame = _prices()
    frame.loc[frame["symbol"] == "SPY", "adjusted_close"] = (
        frame.loc[frame["symbol"] == "SPY", "adjusted_close"].iloc[::-1].to_numpy()
    )
    assert _evaluate(frame).metrics.set_index("metric").loc["relative_strength_6m", "value"] > 0


def test_missing_benchmark_fails_closed() -> None:
    result = _evaluate(_prices().query("symbol != 'SPY'")).metrics.set_index("metric")
    row = result.loc["relative_strength_6m"]
    assert row["status"] == "NOT_COMPUTED"
    assert "benchmark" in row["reason"]


@pytest.mark.parametrize(
    ("mutation", "expected_status", "reason"),
    [
        (lambda f: f.assign(available_at="2025-02-01T00:00:00+00:00"), "PIT_VIOLATION", "PIT"),
        (lambda f: f.assign(date="2025-02-01"), "INVALID_DATA", "future"),
        (lambda f: f.assign(adjusted_close=np.nan), "INVALID_DATA", "missing adjusted"),
        (lambda f: f.assign(adjusted_close=0.0), "INVALID_DATA", "log transformation"),
        (lambda f: f.assign(session_status="MISSING"), "INVALID_DATA", "gaps"),
    ],
)
def test_market_data_violations_fail_closed(mutation, expected_status: str, reason: str) -> None:
    frame = _prices()
    aaa = mutation(frame[frame["symbol"] == "AAA"].copy())
    combined = pd.concat([aaa, frame[frame["symbol"] == "SPY"]], ignore_index=True)
    row = _evaluate(combined).metrics.iloc[0]
    assert row["status"] == expected_status
    assert reason in row["reason"]


def test_zero_volatility_is_not_computed() -> None:
    frame = _prices()
    frame.loc[frame["symbol"] == "AAA", "adjusted_close"] = 100.0
    row = _evaluate(frame).metrics.set_index("metric").loc["volatility_adjusted_momentum_12_1"]
    assert row["status"] == "NOT_COMPUTED"
    assert "volatility" in row["reason"]


@pytest.mark.parametrize(
    ("column", "status"),
    [("input_lineage", "INVALID_LINEAGE"), ("confidence", "MISSING_CONFIDENCE")],
)
def test_governance_fields_are_required(column: str, status: str) -> None:
    frame = _prices()
    frame.loc[frame["symbol"] == "AAA", column] = None
    assert _evaluate(frame).metrics.iloc[0]["status"] == status


def test_unadjusted_prices_are_rejected() -> None:
    frame = _prices()
    mask = frame["symbol"] == "AAA"
    frame.loc[mask, "price_basis"] = "UNADJUSTED"
    frame.loc[mask, "corporate_action_status"] = "NONE"
    result = _evaluate(frame).metrics
    assert set(result["status"]) == {"INVALID_DATA"}
    assert "unadjusted" in result.iloc[0]["reason"]


def test_stale_prices_fail_closed() -> None:
    frame = _prices()
    frame = frame[pd.to_datetime(frame["date"]).dt.date <= AS_OF - datetime.timedelta(days=10)]
    assert set(_evaluate(frame).metrics["status"]) == {"STALE_PRICE"}


def test_missing_expected_session_is_detected_without_self_reported_gap() -> None:
    frame = _prices()
    missing_date = datetime.date(2025, 1, 15)
    frame = frame[~((frame["symbol"] == "AAA") & (frame["date"] == missing_date.isoformat()))]
    result = _evaluate(frame).metrics
    assert set(result["status"]) == {"INVALID_DATA"}
    assert "missing expected market sessions" in result.iloc[0]["reason"]


@pytest.mark.parametrize("column", ["trading_calendar", "timing_policy", "price_basis"])
def test_benchmark_compatibility_mismatch_fails_closed(column: str) -> None:
    frame = _prices()
    values = {"trading_calendar": "XLON", "timing_policy": "NEXT_OPEN", "price_basis": "UNADJUSTED"}
    frame.loc[frame["symbol"] == "SPY", column] = values[column]
    row = _evaluate(frame).metrics.set_index("metric").loc["relative_strength_6m"]
    assert row["status"] == "INVALID_DATA"
    assert "benchmark" in row["reason"]


def test_log_transformation_and_session_window_are_explicit_and_correct() -> None:
    frame = _prices()
    aaa = frame[frame["symbol"] == "AAA"].reset_index(drop=True)
    expected = aaa.iloc[-1]["adjusted_close"] / aaa.iloc[-127]["adjusted_close"] - 1
    evaluation = _evaluate(frame)
    row = evaluation.metrics.set_index("metric").loc["momentum_6m"]
    assert row["value"] == pytest.approx(expected)
    lineage = json.loads(row["lineage"])
    assert lineage["transformation"] == {
        "input_price": "adjusted_close",
        "transform": "natural_log",
        "formula": "log_price_t = ln(adjusted_close_t)",
        "version": "log-price-v1",
    }


def test_split_and_dividend_adjustment_lineage_is_preserved() -> None:
    frame = _prices()
    affected = (frame["symbol"] == "AAA") & (frame["date"] == "2024-08-01")
    frame["corporate_action_type"] = None
    frame["adjustment_factor"] = 1.0
    frame.loc[affected, "corporate_action_status"] = "APPLIED"
    frame.loc[affected, "corporate_action_type"] = "SPLIT_AND_DIVIDEND"
    frame.loc[affected, "adjustment_factor"] = 0.5
    frame.loc[affected, "raw_close"] = frame.loc[affected, "adjusted_close"] / 0.5
    result = _evaluate(frame)
    assert result.health["status"] == "PASS"
    lineage = json.loads(result.metrics.iloc[0]["lineage"])
    assert lineage["corporate_actions"] == ["SPLIT_AND_DIVIDEND"]


def test_corporate_action_adjustment_must_reconcile_to_raw_close() -> None:
    frame = _prices()
    affected = (frame["symbol"] == "AAA") & (frame["date"] == "2024-08-01")
    frame["corporate_action_type"] = None
    frame["adjustment_factor"] = 1.0
    frame.loc[affected, "corporate_action_status"] = "APPLIED"
    frame.loc[affected, "corporate_action_type"] = "SPLIT"
    frame.loc[affected, "adjustment_factor"] = 0.5
    result = _evaluate(frame).metrics
    assert set(result["status"]) == {"INVALID_DATA"}
    assert "does not validate" in result.iloc[0]["reason"]


def test_golden_adjusted_market_data_to_momentum_is_fail_closed_and_interpretable() -> None:
    evaluation = _evaluate()
    assert evaluation.health["status"] == "PASS"
    assert evaluation.validation_report["checks"]["market_data_audit"] == "completed"
    assert set(evaluation.metrics["price_basis"]) == {"ADJUSTED"}
    assert set(evaluation.metrics["unit"]) == {"return", "return_per_volatility", "r_squared"}
    assert evaluation.health["trade_decision"] == "NO_TRADE"
    assert evaluation.health["live_execution_enabled"] is False


def test_golden_provider_history_to_momentum_end_to_end() -> None:
    sessions = get_trading_calendar("XNYS").sessions(datetime.date(2023, 12, 20), AS_OF)
    payloads: dict[str, dict[str, object]] = {}
    for symbol, growth in (("AAA", 0.001), ("SPY", 0.0004)):
        series = {}
        for index, date in enumerate(sessions):
            price = 100 * (1 + growth) ** index
            series[date.isoformat()] = {
                "4. close": str(price),
                "5. adjusted close": str(price),
                "7. dividend amount": "0",
                "8. split coefficient": "1",
            }
        payloads[symbol] = {"Time Series (Daily)": series}

    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode()

    def opener(request: object, *, timeout: float) -> Response:
        del timeout
        symbol = "AAA" if "symbol=AAA" in request.full_url else "SPY"  # type: ignore[attr-defined]
        return Response(payloads[symbol])

    source = AlphaVantageMomentumHistoricalPriceSource(api_key="fixture", opener=opener)
    prices = source.fetch_history(symbols={"AAA", "SPY"}, as_of=AS_OF)
    evaluation = evaluate_momentum_metrics(
        prices,
        experiment_id="golden-market-data-momentum",
        dataset_lineage={"source_metadata": source.metadata},
        as_of=AS_OF,
        benchmark_symbol="SPY",
    )
    assert evaluation.health["status"] == "PASS"
    assert set(evaluation.metrics["status"]) == {"PASS"}
    assert evaluation.lineage["independent_corporate_action_source"] is False
    assert evaluation.health["trade_decision"] == "NO_TRADE"


def test_contract_is_fail_closed_and_benchmark_configurable() -> None:
    assert MOMENTUM_CONTRACT.benchmark_configurable is True
    assert MOMENTUM_CONTRACT.composite_score is False
    assert MOMENTUM_CONTRACT.ranking_calculated is False
    with pytest.raises(ValidationError):
        MomentumFactorContract(definitions=MOMENTUM_CONTRACT.definitions, unknown=True)


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan")])
def test_confidence_threshold_must_be_probability(threshold: float) -> None:
    with pytest.raises(ValueError, match="low_confidence_threshold"):
        evaluate_momentum_metrics(
            _prices(),
            experiment_id="m",
            dataset_lineage={},
            as_of=AS_OF,
            benchmark_symbol="SPY",
            low_confidence_threshold=threshold,
        )


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
                "market_cap_currency": "USD",
                "average_volume": 1_000_000,
                "average_dollar_volume": 20_000_000,
                "listing_date": "2020-01-01T00:00:00Z",
                "source": "fixture",
                "source_timestamp": "2025-01-30T00:00:00Z",
                "available_at": "2025-01-30T00:00:00Z",
            }
        ]
    ).to_csv(source, index=False)
    return run_phase36(
        source_path=source,
        rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=datetime.datetime(2025, 1, 31, tzinfo=datetime.UTC),
        output_root=tmp_path / "universe_validation",
        snapshot_root=tmp_path / "universe_snapshots",
    ).snapshot_dir


def _registered(tmp_path: Path) -> tuple[Path, ResearchExperiment]:
    dataset = tmp_path / "prices.csv"
    _prices().to_csv(dataset, index=False)
    registration = DatasetRegistration(
        dataset_id="momentum-prices",
        snapshot_id="prices-2025-01-31",
        path=dataset.name,
        sha256=file_sha256(dataset),
        lineage=("Market Data",),
    )
    experiment = ResearchExperiment(
        experiment_id="momentum-001",
        experiment_version="1.0",
        hypothesis=MOMENTUM_CONTRACT.hypothesis,
        outcome_metric="individual_momentum_metric_coverage",
        universe="Governed test universe",
        universe_snapshot_id="universe-2025-01-31",
        ruleset_version="universe-v1",
        sample_start="2024-01-01",
        sample_end="2025-01-31",
        preregistered_at="2025-01-01T00:00:00+00:00",
        created_at="2025-01-01T00:00:00+00:00",
        metrics_evaluated=tuple(x.name for x in MOMENTUM_CONTRACT.definitions),
        expected_result="Individual Momentum metrics are reproducible.",
        status="READY",
        datasets=(registration,),
        data_lineage=("Market Data", "Research Environment"),
    )
    registry = tmp_path / "registry.jsonl"
    ResearchRegistry(registry).register(experiment)
    return registry, experiment


def test_runner_is_reproducible_and_writes_required_outputs(tmp_path: Path) -> None:
    registry, experiment = _registered(tmp_path)
    kwargs = {
        "registry_path": registry,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "benchmark_symbol": "SPY",
        "as_of": AS_OF,
        "output_root": tmp_path / "outputs",
        "universe_snapshot_dir": _governed_universe(tmp_path),
    }
    first, second = run_momentum_experiment(**kwargs), run_momentum_experiment(**kwargs)
    assert first.output_dir == second.output_dir
    assert first.research_run == second.research_run
    for name in (
        "momentum_metrics.csv",
        "momentum_health.json",
        "momentum_lineage.json",
        "momentum_validation_report.json",
    ):
        assert (first.output_dir / name).is_file()
    run = first.research_run
    assert run["trade_decision"] == "NO_TRADE"
    assert run["live_execution_enabled"] is False
    assert run["composite_score_calculated"] is False
    assert run["ranking_calculated"] is False
    assert run["portfolio_constructed"] is False
    assert run["backtest_executed"] is False
    assert run["signals_generated"] is False
    assert run["market_data_audit_completed"] is True
    assert run["historical_price_source"] == {
        "provider": "fixture_provider",
        "dataset": "adjusted_daily_history",
        "dataset_version": "fixture-v1",
        "access_tier": "offline_fixture",
    }
