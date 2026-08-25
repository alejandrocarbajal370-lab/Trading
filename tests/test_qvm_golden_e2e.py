import datetime
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from core.phase36 import run_phase36
from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from data.market_calendar import get_trading_calendar
from data.market_data import LineageEntry, govern_market_data
from factors.momentum import evaluate_momentum_metrics
from factors.quality import evaluate_quality_metrics
from factors.qvm import (
    FactorBatch,
    factor_dataset_hash,
    observation_from_row,
    qvm_lineage_hash,
)
from factors.value import evaluate_value_metrics
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.integration import CrossLayerGovernanceError, integrate_governed_inputs
from governance.research_chain import (
    _value_inputs,
    evaluate_governed_momentum,
    evaluate_governed_quality,
    evaluate_governed_qvm,
    evaluate_governed_value,
    financial_metrics_from_governed_accounting,
    governed_factor_batch_identity,
    seal_factor_output,
)
from research.datasets import file_sha256
from research.pre_phase6_readiness import admit_sealed_for_phase6
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


def _universe_snapshot(
    tmp_path: Path,
    *,
    as_of: datetime.date = AS_OF,
    sector: str = "Industrials",
    industry: str = "Machinery",
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "universe.csv"
    pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": sector,
                "industry": industry,
                "market_cap": 1_000_000_000,
                "market_cap_currency": "EUR",
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
        as_of=datetime.datetime.combine(as_of, datetime.time.min, tzinfo=datetime.UTC),
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


def _phase56_chain(
    tmp_path: Path,
    *,
    valuation_date: datetime.date = AS_OF,
    periods: tuple[tuple[str, str, str], ...] = (("FY2024", "2024-01-01", "2024-12-31"),),
    row_overrides: dict[tuple[str, str], dict[str, object]] | None = None,
    sector: str = "Industrials",
    industry: str = "Machinery",
):
    cutoff = datetime.datetime.combine(valuation_date, datetime.time(23, 59), tzinfo=datetime.UTC)
    universe_dir = _universe_snapshot(
        tmp_path, as_of=valuation_date, sector=sector, industry=industry
    )
    metadata_path = universe_dir / "snapshot_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["as_of"] = cutoff.isoformat()
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    sessions = get_trading_calendar("XNYS").sessions(datetime.date(2024, 1, 2), valuation_date)
    price_rows = []
    for symbol, growth in (("AAA", 0.001), ("SPY", 0.0004)):
        for index, day in enumerate(sessions):
            price = 100.0 * (1 + growth) ** index
            price_rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "raw_close": price,
                    "adjusted_close": price,
                    "currency": "USD",
                    "available_at": f"{day.isoformat()}T22:00:00Z",
                    "corporate_action_status": "NONE",
                    "corporate_action_type": None,
                    "adjustment_factor": 1.0,
                    "data_confidence": 0.95,
                    "calculation_confidence": 0.94,
                    "economic_confidence": 0.93,
                }
            )
    market = govern_market_data(
        pd.DataFrame(price_rows),
        source="phase56-market",
        dataset_version="market-v1",
        available_at=cutoff,
        lineage=(LineageEntry(source="phase56-market", dataset="prices", dataset_version="v1"),),
        trading_calendar="XNYS",
        as_of=cutoff,
        maximum_staleness_sessions=0,
    )
    fx_dates = {period_end for _, _, period_end in periods} | {"2024-11-30", "2024-12-31"}
    fx_rows = [
        {
            "currency_pair": "EUR/USD",
            "base_currency": "EUR",
            "quote_currency": "USD",
            "market_timestamp": f"{day}T16:00:00Z",
            "available_at": f"{day}T16:01:00Z",
            "rate": 1.1,
        }
        for day in sorted(fx_dates)
    ]
    fx = govern_fx(
        pd.DataFrame(fx_rows),
        source="phase56-fx",
        dataset_version="fx-v1",
        available_at=cutoff,
        lineage=(FXLineageEntry(source="phase56-fx", dataset="rates", dataset_version="v1"),),
        as_of=cutoff,
        staleness_policy=FXStalenessPolicy(maximum_sessions=120),
    )
    accounting_values = {
        "cash_from_operations": 25.0,
        "capital_expenditures": 5.0,
        "revenue": 100.0,
        "net_income": 12.0,
        "operating_income": 18.0,
        "ebitda": 22.0,
        "total_debt": 30.0,
        "cash": 10.0,
        "total_equity": 70.0,
        "total_assets": 120.0,
        "tax_rate": 0.25,
    }
    accounting_rows = []
    instant_metrics = {"total_debt", "cash", "total_equity", "total_assets"}
    row_overrides = row_overrides or {}
    for fiscal_period, period_start, period_end in periods:
        filing_date = pd.Timestamp(period_end, tz="UTC") + pd.Timedelta(days=1)
        for metric, value in accounting_values.items():
            row = {
                "fact_id": f"aaa-{metric}-{fiscal_period}",
                "entity": "AAA",
                "metric": metric,
                "fiscal_period": fiscal_period,
                "period_end": period_end,
                "fiscal_period_start": None if metric in instant_metrics else period_start,
                "period_type": "instant" if metric in instant_metrics else "duration",
                "filing_date": filing_date.isoformat(),
                "available_at": (filing_date + pd.Timedelta(minutes=1)).isoformat(),
                "value": value,
                "unit": "RATIO" if metric == "tax_rate" else "EUR",
                "source": "phase56-accounting",
                "dataset_version": "accounting-v1",
                "revision": 0,
                "revision_type": "ORIGINAL",
                "supersedes_revision": None,
                "data_confidence": 0.95,
                "calculation_confidence": 0.94,
                "economic_confidence": 0.90,
            }
            row.update(row_overrides.get((fiscal_period, metric), {}))
            accounting_rows.append(row)
    accounting = govern_accounting(
        pd.DataFrame(accounting_rows),
        source="phase56-accounting",
        dataset_version="accounting-v1",
        available_at=cutoff,
        lineage=(
            AccountingLineageEntry(
                source="phase56-accounting", dataset="filings", dataset_version="v1"
            ),
        ),
        as_of=cutoff,
    )
    return integrate_governed_inputs(
        universe_snapshot_dir=universe_dir,
        market_data=market,
        fx=fx,
        accounting=accounting,
        as_of=cutoff,
        base_currency="USD",
        required_fundamentals=set(accounting_values),
        reference_symbols={"SPY"},
    )


def test_phase56_golden_universe_to_qvm_is_one_governed_chain(tmp_path: Path) -> None:
    chain = _phase56_chain(tmp_path)
    batches = (
        seal_factor_output(
            factor="Quality",
            metrics=_quality_output().query("metric in ['roic', 'fcf_margin']"),
            cross_layer=chain,
        ),
        seal_factor_output(
            factor="Value",
            metrics=_value_output().query("metric in ['ev_to_ebit', 'fcf_yield']"),
            cross_layer=chain,
        ),
        seal_factor_output(
            factor="Momentum",
            metrics=_momentum_output().query(
                "metric in ['momentum_12_1', 'volatility_adjusted_momentum_12_1']"
            ),
            cross_layer=chain,
        ),
    )
    evaluation = evaluate_governed_qvm(batches=batches, expected=chain)
    assert evaluation.health["status"] == "PASS"
    assert {batch.cross_layer_fingerprint for batch in batches} == {
        chain.manifest.cross_layer_fingerprint
    }
    assert {batch.eligible_symbols_hash for batch in batches} == {
        chain.manifest.eligible_symbols_hash
    }
    assert evaluation.health["composite_score_calculated"] is False
    assert evaluation.health["ranking_calculated"] is False
    assert evaluation.health["trade_decision"] == "NO_TRADE"
    assert evaluation.health["live_execution_enabled"] is False


def test_phase56_governed_adapters_execute_real_factor_engines(tmp_path: Path) -> None:
    chain = _phase56_chain(tmp_path)
    quality, quality_batch = evaluate_governed_quality(
        cross_layer=chain, experiment_id="phase56-quality"
    )
    value, value_batch = evaluate_governed_value(cross_layer=chain, experiment_id="phase56-value")
    momentum, momentum_batch = evaluate_governed_momentum(
        cross_layer=chain, experiment_id="phase56-momentum", benchmark_symbol="SPY"
    )
    assert quality_batch.cross_layer_fingerprint == chain.manifest.cross_layer_fingerprint
    assert value_batch.accounting_snapshot_sha256 == chain.manifest.accounting_snapshot_sha256
    assert value_batch.fx_checksum == chain.manifest.fx_checksum
    assert momentum_batch.market_data_checksum == chain.manifest.market_data_checksum
    assert quality.health["phase6_eligible"] is False
    assert value.health["phase6_eligible"] is False
    assert momentum.health["phase6_eligible"] is False
    evaluation = evaluate_governed_qvm(
        batches=(quality_batch, value_batch, momentum_batch), expected=chain
    )
    assert evaluation.health["phase6_eligible"] is True
    assert evaluation.health["governance_mode"] == "phase5.6_cross_layer_verified"


def _admission_batches(tmp_path: Path):
    chain = _phase56_chain(tmp_path)
    return (
        seal_factor_output(
            factor="Quality",
            metrics=_quality_output().query("metric in ['roic', 'fcf_margin']"),
            cross_layer=chain,
        ),
        seal_factor_output(
            factor="Value",
            metrics=_value_output().query("metric in ['ev_to_ebit', 'fcf_yield']"),
            cross_layer=chain,
        ),
        seal_factor_output(
            factor="Momentum",
            metrics=_momentum_output().query(
                "metric in ['momentum_12_1', 'volatility_adjusted_momentum_12_1']"
            ),
            cross_layer=chain,
        ),
    )


def _reseal(batch, **updates):
    values = {**batch.model_dump(mode="python"), **updates}
    values["batch_identity_hash"] = governed_factor_batch_identity(values)
    return batch.model_copy(update={**updates, "batch_identity_hash": values["batch_identity_hash"]})


def test_pre_phase6_admission_emits_research_only_identity_artifact(tmp_path: Path) -> None:
    batches = _admission_batches(tmp_path)
    artifact = admit_sealed_for_phase6(batches=batches)
    assert artifact.admitted is True
    assert artifact.expected_symbols == ("AAA",)
    assert set(artifact.factor_batch_hashes) == {"Quality", "Value", "Momentum"}
    assert len(artifact.admission_artifact_hash) == 64
    assert artifact.scores_calculated is False
    assert artifact.ranking_calculated is False
    assert artifact.portfolio_constructed is False
    assert artifact.backtesting_performed is False
    assert artifact.signals_generated is False
    assert artifact.execution_enabled is False
    assert artifact.trade_decision == "NO_TRADE"
    assert artifact.live_execution_enabled is False


@pytest.mark.parametrize("batch_index,new_factor", [(0, "Value"), (1, "Momentum"), (2, "Quality")])
def test_admission_rejects_observation_factor_mismatch(
    tmp_path: Path, batch_index: int, new_factor: str
) -> None:
    batches = list(_admission_batches(tmp_path))
    observations = list(batches[batch_index].observations)
    observations[0] = observations[0].model_copy(update={"factor": new_factor})
    changed = tuple(observations)
    # Deliberately recompute the inner dataset hash and outer identity: the semantic
    # batch/observation mismatch must still fail closed at the consumer boundary.
    batches[batch_index] = _reseal(
        batches[batch_index], observations=changed, factor_dataset_hash=factor_dataset_hash(changed)
    )
    with pytest.raises((ValueError, ValidationError), match="batch factor|mismatched observation"):
        admit_sealed_for_phase6(batches=tuple(batches))


def test_governance_order_is_versioned_hashed_and_revalidated(tmp_path: Path) -> None:
    batches = list(_admission_batches(tmp_path))
    original_hash = batches[0].batch_identity_hash
    mutated = tuple(reversed(batches[0].governance_order))
    stale = batches[0].model_copy(update={"governance_order": mutated})
    batches[0] = stale
    with pytest.raises((ValueError, ValidationError), match="governance order|identity"):
        admit_sealed_for_phase6(batches=tuple(batches))
    values = {**stale.model_dump(mode="python"), "governance_order": mutated}
    assert governed_factor_batch_identity(values) != original_hash


@pytest.mark.parametrize(
    "field",
    [
        "as_of",
        "universe_snapshot_hash",
        "eligible_symbols_hash",
        "validation_hash",
        "cross_layer_fingerprint",
        "peer_assignment_hash",
        "classification_taxonomy_version",
        "accounting_canonical_id",
        "market_data_canonical_id",
        "market_data_snapshot_sha256",
        "fx_canonical_id",
        "fx_conversions_sha256",
    ],
)
def test_admission_rejects_each_outer_identity_mutation(
    tmp_path: Path, field: str
) -> None:
    batches = list(_admission_batches(tmp_path))
    original = getattr(batches[0], field)
    if field == "as_of":
        changed = original - datetime.timedelta(days=1)
    elif field.endswith(("hash", "fingerprint")):
        changed = "b" * 64
    else:
        changed = f"{original}-mutated"
    batches[0] = _reseal(batches[0], **{field: changed})
    with pytest.raises((ValueError, ValidationError), match="mismatch"):
        admit_sealed_for_phase6(batches=tuple(batches))


def test_admission_requires_exactly_one_qvm_batch(tmp_path: Path) -> None:
    batches = _admission_batches(tmp_path)
    with pytest.raises(ValueError, match="exactly one Quality, Value, and Momentum"):
        admit_sealed_for_phase6(batches=batches[:2])
    with pytest.raises(ValueError, match="exactly one Quality, Value, and Momentum"):
        admit_sealed_for_phase6(batches=(batches[0], batches[0], batches[2]))


def test_admission_rejects_low_confidence_nonfinite_and_unavailable_runtime(
    tmp_path: Path,
) -> None:
    batches = list(_admission_batches(tmp_path))
    observations = list(batches[0].observations)
    observations[0] = observations[0].model_copy(update={"confidence": 0.79})
    changed = tuple(observations)
    batches[0] = _reseal(
        batches[0], observations=changed, factor_dataset_hash=factor_dataset_hash(changed)
    )
    with pytest.raises(ValueError, match="confidence must be at least 0.80"):
        admit_sealed_for_phase6(batches=tuple(batches))

    batches = list(_admission_batches(tmp_path / "nonfinite"))
    observations = list(batches[0].observations)
    observations[0] = observations[0].model_copy(update={"value": float("inf")})
    batches[0] = batches[0].model_copy(update={"observations": tuple(observations)})
    with pytest.raises(ValueError, match="finite"):
        admit_sealed_for_phase6(batches=tuple(batches))

    batches = list(_admission_batches(tmp_path / "runtime"))
    unavailable = batches[0].runtime.model_copy(update={"git_commit_sha": "UNAVAILABLE"})
    batches[0] = _reseal(batches[0], runtime=unavailable)
    with pytest.raises(ValueError, match="UNAVAILABLE|runtime fingerprint"):
        admit_sealed_for_phase6(batches=tuple(batches))


@pytest.mark.parametrize(
    "field,changed",
    [
        ("git_commit_sha", "b" * 40),
        ("requirements_lock_sha256", "b" * 64),
        ("python_version", "0.0-mutated"),
        ("pandas_version", "0.0-mutated"),
        ("numpy_version", "0.0-mutated"),
        ("platform", "mutated-platform"),
        ("implementation", "mutated-implementation"),
    ],
)
def test_admission_rejects_stale_runtime_fingerprint_payload(
    tmp_path: Path, field: str, changed: str
) -> None:
    batches = list(_admission_batches(tmp_path))
    runtime = batches[0].runtime.model_copy(update={field: changed})
    batches[0] = _reseal(batches[0], runtime=runtime)
    with pytest.raises((ValueError, ValidationError), match="runtime fingerprint"):
        admit_sealed_for_phase6(batches=tuple(batches))


def test_admission_rejects_legacy_factor_batch_and_dataframe(tmp_path: Path) -> None:
    batches = _admission_batches(tmp_path)
    legacy = FactorBatch(
        factor="Quality",
        universe_snapshot_id=batches[0].universe_snapshot_id,
        as_of=batches[0].as_of.date(),
        availability_policy=batches[0].availability_policy_version,
        universe_snapshot_hash=batches[0].universe_snapshot_hash,
        factor_dataset_hash=batches[0].factor_dataset_hash,
        lineage_hash="a" * 64,
        observations=batches[0].observations,
    )
    with pytest.raises(TypeError, match="exact GovernedFactorBatch"):
        admit_sealed_for_phase6(batches=(legacy,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact GovernedFactorBatch"):
        admit_sealed_for_phase6(batches=(pd.DataFrame(),))  # type: ignore[arg-type]


def test_unknown_status_fails_at_producer_sealing_and_admission(tmp_path: Path) -> None:
    chain = _phase56_chain(tmp_path)
    invalid = _quality_output().query("metric == 'roic'").copy()
    invalid["status"] = "UNEXPECTED_PROVIDER_STATUS"
    with pytest.raises(ValueError, match="unknown governed status"):
        seal_factor_output(factor="Quality", metrics=invalid, cross_layer=chain)

    batches = list(_admission_batches(tmp_path / "admission"))
    observations = list(batches[0].observations)
    observations[0] = observations[0].model_copy(update={"status": "MUTATED_UNKNOWN"})
    changed = tuple(observations)
    batches[0] = _reseal(
        batches[0], observations=changed, factor_dataset_hash=factor_dataset_hash(changed)
    )
    with pytest.raises(ValidationError, match="observations.0.status"):
        admit_sealed_for_phase6(batches=tuple(batches))


@pytest.mark.parametrize(
    ("sector", "industry", "metric"),
    [
        ("Financials", "Banks", "net_debt_to_ebitda"),
        ("Financials", "Insurance", "cfo_conversion"),
        ("Real Estate", "REITs", "cfo_conversion"),
    ],
)
def test_sector_applicability_is_enforced_before_admission(
    tmp_path: Path, sector: str, industry: str, metric: str
) -> None:
    chain = _phase56_chain(tmp_path, sector=sector, industry=industry)
    batch = seal_factor_output(
        factor="Quality", metrics=_quality_output().query("metric == @metric"), cross_layer=chain
    )
    observation = batch.observations[0]
    assert observation.status == "NOT_APPLICABLE"
    assert observation.applicability in {"NOT_APPLICABLE", "REVIEW"}
    assert observation.value is None


def test_value_financials_applicability_never_reaches_pass(tmp_path: Path) -> None:
    chain = _phase56_chain(tmp_path, sector="Financials", industry="Banks")
    batch = seal_factor_output(
        factor="Value", metrics=_value_output().query("metric == 'ev_to_ebit'"), cross_layer=chain
    )
    observation = batch.observations[0]
    assert observation.status == "NOT_APPLICABLE"
    assert observation.applicability == "NOT_APPLICABLE"
    assert observation.value is None


def test_non_calendar_fiscal_year_is_preserved_end_to_end(tmp_path: Path) -> None:
    chain = _phase56_chain(
        tmp_path,
        valuation_date=datetime.date(2025, 4, 15),
        periods=(("FY2025", "2024-04-01", "2025-03-31"),),
    )
    financial = financial_metrics_from_governed_accounting(chain)
    fcf = financial.query("metric == 'free_cash_flow' and status == 'PASS'").iloc[0]
    assert fcf["fiscal_period_start"] == datetime.date(2024, 4, 1)
    assert fcf["fiscal_period_end"] == datetime.date(2025, 3, 31)
    value_inputs = _value_inputs(chain, financial)
    assert set(value_inputs["fiscal_period_end"]) == {datetime.date(2025, 3, 31)}
    lineage = json.loads(value_inputs.iloc[0]["input_lineage"])[0]
    assert lineage["selected_fiscal_period_start"] == "2024-04-01"
    assert lineage["selected_fiscal_period_end"] == "2025-03-31"
    assert lineage["accounting_canonical_id"] == chain.manifest.accounting_canonical_id


def test_value_policy_selects_latest_complete_fy_and_ignores_quarter(tmp_path: Path) -> None:
    periods = (
        ("FY2023", "2023-01-01", "2023-12-31"),
        ("Q1-2024", "2024-01-01", "2024-03-31"),
        ("FY2024", "2024-01-01", "2024-12-31"),
    )
    chain = _phase56_chain(
        tmp_path,
        periods=periods,
        row_overrides={("FY2024", "net_income"): {"value": 99.0}},
    )
    financial = financial_metrics_from_governed_accounting(chain)
    inputs = _value_inputs(chain, financial).set_index("metric")
    assert inputs.loc["earnings", "value"] == pytest.approx(108.9)
    assert set(inputs["fiscal_period_end"]) == {datetime.date(2024, 12, 31)}


def test_value_rejects_flows_from_different_periods(tmp_path: Path) -> None:
    chain = _phase56_chain(
        tmp_path,
        row_overrides={("FY2024", "operating_income"): {"fiscal_period_start": "2024-04-01"}},
    )
    financial = financial_metrics_from_governed_accounting(chain)
    with pytest.raises(CrossLayerGovernanceError, match="compatible Value flow period"):
        _value_inputs(chain, financial)


def test_value_rejects_stock_and_flow_temporal_incompatibility(tmp_path: Path) -> None:
    chain = _phase56_chain(
        tmp_path,
        row_overrides={
            ("FY2024", "cash"): {"period_end": "2024-11-30"},
            ("FY2024", "total_debt"): {"period_end": "2024-11-30"},
        },
    )
    financial = financial_metrics_from_governed_accounting(chain)
    with pytest.raises(CrossLayerGovernanceError, match="stock and flow periods"):
        _value_inputs(chain, financial)


def test_value_rejects_duplicate_temporal_facts_across_fiscal_labels(tmp_path: Path) -> None:
    chain = _phase56_chain(
        tmp_path,
        periods=(("FY2024", "2024-01-01", "2024-12-31"), ("FY-ALT", "2024-01-01", "2024-12-31")),
    )
    financial = financial_metrics_from_governed_accounting(chain)
    with pytest.raises(CrossLayerGovernanceError, match="ambiguous Value flow facts"):
        _value_inputs(chain, financial)


@pytest.mark.parametrize(
    "field",
    [
        "cross_layer_fingerprint",
        "universe_snapshot_hash",
        "membership_hash",
        "eligible_symbols_hash",
        "accounting_checksum",
        "accounting_snapshot_sha256",
        "fx_checksum",
        "market_data_checksum",
    ],
)
def test_phase56_qvm_rejects_any_upstream_identity_mismatch(tmp_path: Path, field: str) -> None:
    chain = _phase56_chain(tmp_path)
    batches = [
        seal_factor_output(
            factor="Quality", metrics=_quality_output().query("metric == 'roic'"), cross_layer=chain
        ),
        seal_factor_output(
            factor="Value",
            metrics=_value_output().query("metric == 'fcf_yield'"),
            cross_layer=chain,
        ),
        seal_factor_output(
            factor="Momentum",
            metrics=_momentum_output().query("metric == 'momentum_12_1'"),
            cross_layer=chain,
        ),
    ]
    batches[0] = batches[0].model_copy(update={field: "b" * 64})
    with pytest.raises(CrossLayerGovernanceError, match="mismatch"):
        evaluate_governed_qvm(batches=tuple(batches), expected=chain)
