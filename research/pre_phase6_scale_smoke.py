from __future__ import annotations

import argparse
import datetime
import json
import resource
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

from core.phase36 import run_phase36
from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from data.market_calendar import get_trading_calendar
from data.market_data import LineageEntry, govern_market_data
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.integration import integrate_governed_inputs
from governance.research_chain import (
    evaluate_governed_momentum,
    evaluate_governed_quality,
    evaluate_governed_qvm,
    evaluate_governed_value,
)
from research.pre_phase6_readiness import admit_sealed_for_phase6
from universe.validation import UniverseRules

SCALE_SMOKE_VERSION = "pre-phase6-synthetic-pipeline-smoke-v1"
AS_OF = datetime.datetime(2025, 3, 15, 23, 59, tzinfo=datetime.UTC)
ACCOUNTING_VALUES = {
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


def _symbols(security_count: int) -> tuple[str, ...]:
    if not 1 <= security_count <= 5_000:
        raise ValueError("security_count must be between 1 and 5000")
    return tuple(f"S{index:05d}" for index in range(security_count))


def _universe(symbols: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Industrials",
                "industry": "Machinery",
                "market_cap": float(1_000_000_000 + index),
                "market_cap_currency": "EUR",
                "average_volume": 1_000_000,
                "average_dollar_volume": 20_000_000,
                "listing_date": "2020-01-01T00:00:00Z",
                "source": "synthetic-scale-smoke",
                "source_timestamp": "2025-03-14T22:00:00Z",
                "available_at": "2025-03-14T22:00:00Z",
                "universe_confidence": 0.95,
            }
            for index, symbol in enumerate(symbols)
        ]
    )


def _market(symbols: tuple[str, ...]) -> pd.DataFrame:
    sessions = get_trading_calendar("XNYS").sessions(datetime.date(2024, 1, 2), AS_OF.date())
    rows: list[dict[str, Any]] = []
    for symbol_index, symbol in enumerate((*symbols, "SPY")):
        growth = 0.0004 if symbol == "SPY" else 0.0007 + (symbol_index % 7) * 0.00001
        for session_index, day in enumerate(sessions):
            price = 100.0 * (1 + growth) ** session_index
            rows.append(
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
    return pd.DataFrame(rows)


def _accounting(symbols: tuple[str, ...]) -> pd.DataFrame:
    instant = {"total_debt", "cash", "total_equity", "total_assets"}
    rows: list[dict[str, Any]] = []
    for symbol_index, symbol in enumerate(symbols):
        scale = 1 + symbol_index / 100_000
        for metric, base_value in ACCOUNTING_VALUES.items():
            rows.append(
                {
                    "fact_id": f"{symbol}-{metric}-FY2024",
                    "entity": symbol,
                    "metric": metric,
                    "fiscal_period": "FY2024",
                    "period_end": "2024-12-31",
                    "fiscal_period_start": None if metric in instant else "2024-01-01",
                    "period_type": "instant" if metric in instant else "duration",
                    "filing_date": "2025-01-20T12:00:00Z",
                    "available_at": "2025-01-20T12:01:00Z",
                    "value": base_value if metric == "tax_rate" else base_value * scale,
                    "unit": "RATIO" if metric == "tax_rate" else "EUR",
                    "source": "synthetic-scale-smoke",
                    "dataset_version": "scale-v1",
                    "revision": 0,
                    "revision_type": "ORIGINAL",
                    "supersedes_revision": None,
                    "data_confidence": 0.95,
                    "calculation_confidence": 0.94,
                    "economic_confidence": 0.90,
                }
            )
    return pd.DataFrame(rows)


def run_synthetic_scale_smoke(
    *, security_count: int, workdir: Path, reorder_inputs: bool = False
) -> dict[str, Any]:
    """Exercise the complete research-only path without scores, outcomes, or execution."""
    started = time.perf_counter()
    stages: dict[str, float] = {}

    def mark(stage: str, since: float) -> float:
        now = time.perf_counter()
        stages[stage] = now - since
        return now

    stage_started = started
    workdir.mkdir(parents=True, exist_ok=True)
    symbols = _symbols(security_count)
    universe = _universe(symbols)
    market_frame = _market(symbols)
    accounting_frame = _accounting(symbols)
    stage_started = mark("fixture_generation", stage_started)
    if reorder_inputs:
        universe = universe.iloc[::-1].reset_index(drop=True)
        market_frame = market_frame.iloc[::-1].reset_index(drop=True)
        accounting_frame = accounting_frame.iloc[::-1].reset_index(drop=True)

    source = workdir / "universe.csv"
    universe.to_csv(source, index=False)
    snapshot = run_phase36(
        source_path=source,
        rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=AS_OF,
        output_root=workdir / "universe_validation",
        snapshot_root=workdir / "universe_snapshots",
    ).snapshot_dir
    stage_started = mark("universe", stage_started)
    market = govern_market_data(
        market_frame,
        source="synthetic-scale-smoke",
        dataset_version="scale-v1",
        available_at=AS_OF,
        lineage=(
            LineageEntry(
                source="synthetic-scale-smoke", dataset="prices", dataset_version="scale-v1"
            ),
        ),
        trading_calendar="XNYS",
        as_of=AS_OF,
        maximum_staleness_sessions=0,
    )
    stage_started = mark("market_data", stage_started)
    fx = govern_fx(
        pd.DataFrame(
            [
                {
                    "currency_pair": "EUR/USD",
                    "base_currency": "EUR",
                    "quote_currency": "USD",
                    "market_timestamp": "2024-12-31T16:00:00Z",
                    "available_at": "2024-12-31T16:01:00Z",
                    "rate": 1.1,
                }
            ]
        ),
        source="synthetic-scale-smoke",
        dataset_version="scale-v1",
        available_at=AS_OF,
        lineage=(
            FXLineageEntry(
                source="synthetic-scale-smoke", dataset="fx", dataset_version="scale-v1"
            ),
        ),
        as_of=AS_OF,
        staleness_policy=FXStalenessPolicy(maximum_sessions=120),
    )
    stage_started = mark("fx", stage_started)
    accounting = govern_accounting(
        accounting_frame,
        source="synthetic-scale-smoke",
        dataset_version="scale-v1",
        available_at=AS_OF,
        lineage=(
            AccountingLineageEntry(
                source="synthetic-scale-smoke",
                dataset="fundamentals",
                dataset_version="scale-v1",
            ),
        ),
        as_of=AS_OF,
    )
    stage_started = mark("accounting", stage_started)
    cross_layer = integrate_governed_inputs(
        universe_snapshot_dir=snapshot,
        market_data=market,
        fx=fx,
        accounting=accounting,
        as_of=AS_OF,
        base_currency="USD",
        required_fundamentals=set(ACCOUNTING_VALUES),
        reference_symbols={"SPY"},
    )
    stage_started = mark("cross_layer", stage_started)
    _, quality = evaluate_governed_quality(
        cross_layer=cross_layer, experiment_id="synthetic-scale-quality"
    )
    _, value = evaluate_governed_value(
        cross_layer=cross_layer, experiment_id="synthetic-scale-value"
    )
    _, momentum = evaluate_governed_momentum(
        cross_layer=cross_layer,
        experiment_id="synthetic-scale-momentum",
        benchmark_symbol="SPY",
    )
    stage_started = mark("factors", stage_started)
    batches = (quality, value, momentum)
    qvm = evaluate_governed_qvm(batches=batches, expected=cross_layer)
    admission = admit_sealed_for_phase6(batches=batches)
    mark("qvm_and_admission", stage_started)
    # Process peak RSS has negligible observer overhead, unlike tracemalloc which
    # multiplied the benchmark runtime and made the scale result misleading.
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak = int(peak_rss if sys.platform == "darwin" else peak_rss * 1024)
    return {
        "schema_version": SCALE_SMOKE_VERSION,
        "security_count": security_count,
        "market_rows": len(market_frame),
        "accounting_rows": len(accounting_frame),
        "cross_layer_fingerprint": cross_layer.manifest.cross_layer_fingerprint,
        "factor_batch_hashes": admission.factor_batch_hashes,
        "qvm_sealed_lineage_hash": admission.qvm_sealed_lineage_hash,
        "admission_artifact_hash": admission.admission_artifact_hash,
        "qvm_governance_mode": qvm.health["governance_mode"],
        "runtime_seconds_observed": time.perf_counter() - started,
        "peak_memory_bytes_observed": peak,
        "stage_runtime_seconds": stages,
        "scores_calculated": False,
        "ranking_calculated": False,
        "portfolio_constructed": False,
        "backtesting_performed": False,
        "signals_generated": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "execution_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic PRE-Phase 6 pipeline benchmark")
    parser.add_argument("--securities", type=int, default=5_000)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="pre-phase6-scale-") as directory:
        report = run_synthetic_scale_smoke(
            security_count=args.securities, workdir=Path(directory)
        )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
