import datetime
import json
from pathlib import Path

import pandas as pd
import pytest

from core.phase36 import run_phase36
from data.market_calendar import get_trading_calendar
from factors.momentum import evaluate_momentum_metrics
from factors.quality import evaluate_quality_metrics
from factors.qvm import (
    FactorBatch,
    factor_dataset_hash,
    observation_from_row,
    qvm_lineage_hash,
)
from factors.value import evaluate_value_metrics
from research.datasets import file_sha256
from research.qvm_runner import run_qvm_research
from universe.validation import UniverseRules

AS_OF = datetime.date(2025, 3, 15)
AVAILABLE_AT = "2025-03-01T00:00:00+00:00"
SNAPSHOT_ID = "universe-2025-03-15"
AVAILABILITY_POLICY = "KNOWN_BY_AS_OF"
ENTITY_POLICY = "symbol"


def _lineage(metric: str) -> str:
    return json.dumps(
        [
            {
                "metric": metric,
                "source": "golden_e2e_fixture",
                "available_at": AVAILABLE_AT,
                "fiscal_period_end": "2024-12-31",
            }
        ],
        sort_keys=True,
    )


def _universe_snapshot(tmp_path: Path) -> Path:
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
                "market_cap": 1_000_000_000,
                "average_volume": 1_000_000,
                "average_dollar_volume": 20_000_000,
                "listing_date": "2020-01-01T00:00:00Z",
                "source": "golden_e2e_fixture",
                "source_timestamp": "2025-03-14T22:00:00Z",
                "available_at": "2025-03-14T22:00:00Z",
            }
        ]
    ).to_csv(source, index=False)
    return run_phase36(
        source_path=source,
        rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=datetime.datetime.combine(AS_OF, datetime.time.min, tzinfo=datetime.UTC),
        output_root=tmp_path / "universe_validation",
        snapshot_root=tmp_path / "universe_snapshots",
    ).snapshot_dir


def _quality_output() -> pd.DataFrame:
    rows = []
    histories = {
        "roic_v1": (0.10, 0.14),
        "free_cash_flow_margin": (0.12, 0.16),
        "cfo_to_net_income": (1.1, 1.2),
        "net_debt_to_ebitda": (1.8, 1.5),
        "accrual_ratio": (0.03, 0.02),
    }
    for metric, values in histories.items():
        for period_end, value in zip(("2023-12-31", "2024-12-31"), values, strict=True):
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
    return evaluate_quality_metrics(
        pd.DataFrame(rows),
        experiment_id="qvm-golden-quality",
        dataset_lineage={"snapshot_id": "financial-2024-12-31"},
    ).metrics


def _value_output() -> pd.DataFrame:
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
        rows.append(
            {
                "symbol": "AAA",
                "valuation_as_of": AS_OF.isoformat(),
                "fiscal_period_end": "2024-12-31",
                "period_basis": "INSTANT" if instant else "TTM",
                "metric": metric,
                "value": value,
                "unit": "currency",
                "currency": "USD",
                "available_at": AVAILABLE_AT,
                "status": "PASS",
                "reason": None,
                "confidence": 0.95,
                "input_lineage": _lineage(metric),
                "industry": "Machinery",
            }
        )
    return evaluate_value_metrics(
        pd.DataFrame(rows),
        experiment_id="qvm-golden-value",
        dataset_lineage={"snapshot_id": "financial-2024-12-31"},
    ).metrics


def _momentum_output() -> pd.DataFrame:
    dates = pd.to_datetime(get_trading_calendar("XNYS").sessions(datetime.date(2024, 1, 2), AS_OF))
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
                    "input_lineage": json.dumps(
                        [{"source": "golden_price_fixture", "series": symbol}]
                    ),
                    "price_basis": "ADJUSTED",
                    "corporate_action_status": "NONE",
                    "trading_calendar": "XNYS",
                    "session_status": "PRESENT",
                    "timing_policy": "EOD_CLOSE_T_PLUS_0",
                    "historical_provider": "golden_fixture",
                    "historical_dataset": "adjusted_daily_history",
                    "historical_dataset_version": "golden-v1",
                    "historical_access_tier": "offline_fixture",
                }
            )
    return evaluate_momentum_metrics(
        pd.DataFrame(rows),
        experiment_id="qvm-golden-momentum",
        dataset_lineage={"snapshot_id": "prices-2025-03-15"},
        as_of=AS_OF,
        benchmark_symbol="SPY",
    ).metrics


def _observations() -> dict[str, tuple]:
    outputs = {
        "Quality": _quality_output().query("metric in ['roic', 'fcf_margin']"),
        "Value": _value_output().query("metric in ['ev_to_ebit', 'fcf_yield']"),
        "Momentum": _momentum_output().query(
            "metric in ['momentum_12_1', 'volatility_adjusted_momentum_12_1']"
        ),
    }
    return {
        factor: tuple(
            observation_from_row(
                row,
                factor=factor,
                universe_snapshot_id=SNAPSHOT_ID,
                as_of=AS_OF,
            )
            for _, row in frame.iterrows()
        )
        for factor, frame in outputs.items()
    }


def _batches(universe_hash: str) -> tuple[FactorBatch, ...]:
    observations = _observations()
    dataset_hashes = {factor: factor_dataset_hash(items) for factor, items in observations.items()}
    lineage_hash = qvm_lineage_hash(
        universe_snapshot_id=SNAPSHOT_ID,
        universe_snapshot_hash=universe_hash,
        factor_dataset_hashes=dataset_hashes,
        as_of=AS_OF,
        availability_policy=AVAILABILITY_POLICY,
        entity_policy=ENTITY_POLICY,
    )
    return tuple(
        FactorBatch(
            factor=factor,
            universe_snapshot_id=SNAPSHOT_ID,
            as_of=AS_OF,
            availability_policy=AVAILABILITY_POLICY,
            entity_policy=ENTITY_POLICY,
            universe_snapshot_hash=universe_hash,
            factor_dataset_hash=dataset_hashes[factor],
            lineage_hash=lineage_hash,
            observations=observations[factor],
        )
        for factor in ("Quality", "Value", "Momentum")
    )


def _assert_no_prohibited_output(value: object) -> None:
    prohibited = {
        "score",
        "composite_score",
        "weights",
        "ranking",
        "selection",
        "portfolio",
        "backtest",
        "broker",
        "execution",
    }

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in prohibited:
                    assert nested is False
                else:
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)


def test_qvm_golden_e2e_consumes_real_factor_outputs(tmp_path: Path) -> None:
    universe_dir = _universe_snapshot(tmp_path)
    universe_metadata = json.loads(
        (universe_dir / "snapshot_metadata.json").read_text(encoding="utf-8")
    )
    universe_hash = universe_metadata["membership_sha256"]
    assert universe_hash == file_sha256(universe_dir / "universe_membership.csv")

    batches = _batches(universe_hash)
    assert {batch.universe_snapshot_id for batch in batches} == {SNAPSHOT_ID}
    assert {batch.universe_snapshot_hash for batch in batches} == {universe_hash}
    assert {batch.as_of for batch in batches} == {AS_OF}
    assert {batch.availability_policy for batch in batches} == {AVAILABILITY_POLICY}
    assert {batch.entity_policy for batch in batches} == {ENTITY_POLICY}
    assert len({batch.lineage_hash for batch in batches}) == 1
    assert batches[0].lineage_hash == _batches(universe_hash)[0].lineage_hash

    semantics = {
        (item.factor, item.metric, item.unit) for batch in batches for item in batch.observations
    }
    assert semantics == {
        ("Quality", "roic", "percentage"),
        ("Quality", "fcf_margin", "percentage"),
        ("Value", "ev_to_ebit", "multiple"),
        ("Value", "fcf_yield", "ratio"),
        ("Momentum", "momentum_12_1", "return"),
        (
            "Momentum",
            "volatility_adjusted_momentum_12_1",
            "return_per_volatility",
        ),
    }

    result = run_qvm_research(
        batches=batches,
        output_root=tmp_path / "qvm_outputs",
        universe_snapshot_dir=universe_dir,
    )
    required = {
        "qvm_factor_matrix.csv",
        "qvm_health.json",
        "qvm_lineage.json",
        "qvm_validation_report.json",
    }
    assert required <= {path.name for path in result.output_dir.iterdir()}
    assert result.research_run["trade_decision"] == "NO_TRADE"
    assert result.research_run["live_execution_enabled"] is False
    assert result.research_run["composite_score_calculated"] is False
    assert result.research_run["ranking_calculated"] is False
    assert result.research_run["portfolio_constructed"] is False
    assert result.research_run["backtest_executed"] is False

    for name in required - {"qvm_factor_matrix.csv"}:
        _assert_no_prohibited_output(
            json.loads((result.output_dir / name).read_text(encoding="utf-8"))
        )
    matrix = pd.read_csv(result.output_dir / "qvm_factor_matrix.csv")
    assert len(matrix) == 1
    for batch in batches:
        for observation in batch.observations:
            column = f"{batch.factor.lower()}__{observation.metric}"
            assert matrix.loc[0, column] == pytest.approx(observation.value)
    lineage = json.loads((result.output_dir / "qvm_lineage.json").read_text())
    assert lineage["lineage_hash"] == batches[0].lineage_hash
    assert lineage["factors"] == {
        batch.factor: [item.lineage for item in batch.observations] for batch in batches
    }
    assert not any(
        prohibited in column.lower()
        for column in matrix.columns
        for prohibited in (
            "score",
            "weight",
            "rank",
            "selection",
            "portfolio",
            "backtest",
            "broker",
            "execution",
        )
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("factor_dataset_hash", "b" * 64, "dataset hash"),
        ("universe_snapshot_hash", "b" * 64, "universe"),
        ("lineage_hash", "b" * 64, "lineage"),
        ("as_of", datetime.date(2025, 3, 14), "PIT"),
    ],
)
def test_qvm_golden_e2e_fails_closed_when_governance_changes(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    universe_dir = _universe_snapshot(tmp_path)
    metadata = json.loads((universe_dir / "snapshot_metadata.json").read_text())
    batches = list(_batches(metadata["membership_sha256"]))
    batches[0] = batches[0].model_copy(update={field: value})
    with pytest.raises(ValueError, match=reason):
        run_qvm_research(
            batches=tuple(batches),
            output_root=tmp_path / "qvm_outputs",
            universe_snapshot_dir=universe_dir,
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("factor", "Value", "observation factor does not match"),
        ("metric", "unknown_metric", "unknown_metric"),
        ("unit", "ratio", "expected percentage, got ratio"),
    ],
)
def test_qvm_golden_e2e_fails_closed_for_invalid_metric_semantics(
    tmp_path: Path, field: str, value: str, reason: str
) -> None:
    universe_dir = _universe_snapshot(tmp_path)
    metadata = json.loads((universe_dir / "snapshot_metadata.json").read_text())
    batches = list(_batches(metadata["membership_sha256"]))
    observations = list(batches[0].observations)
    observations[0] = observations[0].model_copy(update={field: value})
    changed = tuple(observations)
    batches[0] = batches[0].model_copy(
        update={"observations": changed, "factor_dataset_hash": factor_dataset_hash(changed)}
    )
    hashes = {batch.factor: batch.factor_dataset_hash for batch in batches}
    lineage_hash = qvm_lineage_hash(
        universe_snapshot_id=SNAPSHOT_ID,
        universe_snapshot_hash=metadata["membership_sha256"],
        factor_dataset_hashes=hashes,
        as_of=AS_OF,
        availability_policy=AVAILABILITY_POLICY,
        entity_policy=ENTITY_POLICY,
    )
    batches = [batch.model_copy(update={"lineage_hash": lineage_hash}) for batch in batches]
    with pytest.raises(ValueError, match=reason):
        run_qvm_research(
            batches=tuple(batches),
            output_root=tmp_path / "qvm_outputs",
            universe_snapshot_dir=universe_dir,
        )
