import datetime
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from data.market_calendar import get_trading_calendar
from research.datasets import DatasetVersionError
from research.pit_dataset import build_and_run_pit_qvm, build_pit_equity_dataset

AS_OF = datetime.datetime(2025, 3, 15, 23, 59, tzinfo=datetime.UTC)
FUNDAMENTALS = {
    "cash_from_operations",
    "capital_expenditures",
    "revenue",
    "net_income",
    "operating_income",
    "ebit",
    "ebitda",
    "total_debt",
    "cash",
    "total_equity",
    "total_assets",
    "tax_rate",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_pilot(tmp_path: Path, *, symbols: int = 100) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    names = [f"S{index:03d}" for index in range(symbols)]
    pd.DataFrame(
        [
            {
                "symbol": symbol,
                "permanent_id": f"US-PERM-{index:03d}",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Industrials",
                "industry": "Machinery",
                "market_cap": 1_000_000_000 + index * 20_000_000,
                "market_cap_currency": "EUR",
                "average_volume": 1_000_000 + index * 1_000,
                "average_dollar_volume": 20_000_000 + index * 100_000,
                "listing_date": "2010-01-04T00:00:00Z",
                "source": "licensed-file-export",
                "source_timestamp": "2025-03-14T16:00:00Z",
                "available_at": "2025-03-14T16:05:00Z",
                "membership_as_of": AS_OF.isoformat(),
                "membership_source": "licensed-file-export",
                "membership_snapshot_id": "pit-membership-2025-03-15",
            }
            for index, symbol in enumerate(names)
        ]
    ).to_csv(tmp_path / "universe.csv", index=False)

    sessions = get_trading_calendar("XNYS").sessions(
        datetime.date(2024, 1, 2), datetime.date(2025, 3, 15)
    )
    price_rows = []
    for symbol_index, symbol in enumerate([*names, "SPY"]):
        growth = 0.00015 + symbol_index * 0.000002
        for day_index, day in enumerate(sessions):
            adjusted = 50.0 * (1.0 + growth) ** day_index * math.exp(
                0.006 * math.sin(day_index * 0.37 + symbol_index * 0.11)
            )
            price_rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "raw_close": adjusted,
                    "adjusted_close": adjusted,
                    "currency": "USD",
                    "available_at": f"{day.isoformat()}T22:00:00Z",
                    "corporate_action_status": "NONE",
                    "corporate_action_type": None,
                    "adjustment_factor": 1.0,
                    "data_confidence": 0.95,
                    "calculation_confidence": 0.95,
                    "economic_confidence": 0.95,
                }
            )
    pd.DataFrame(price_rows).to_csv(tmp_path / "market_data.csv", index=False)

    instant = {"total_debt", "cash", "total_equity", "total_assets"}
    base_values = {
        "cash_from_operations": 25_000_000.0,
        "capital_expenditures": 5_000_000.0,
        "revenue": 100_000_000.0,
        "net_income": 12_000_000.0,
        "operating_income": 18_000_000.0,
        "ebit": 18_000_000.0,
        "ebitda": 22_000_000.0,
        "total_debt": 30_000_000.0,
        "cash": 10_000_000.0,
        "total_equity": 70_000_000.0,
        "total_assets": 120_000_000.0,
        "tax_rate": 0.25,
    }
    accounting_rows = []
    metric_slopes = {
        "cash_from_operations": 0.0018,
        "capital_expenditures": 0.0005,
        "revenue": 0.0008,
        "net_income": 0.0014,
        "operating_income": 0.0012,
        "ebit": 0.0012,
        "ebitda": 0.0010,
        "total_debt": 0.0004,
        "cash": 0.0011,
        "total_equity": 0.0009,
        "total_assets": 0.0007,
    }
    for symbol_index, symbol in enumerate(names):
        scale = 1.0 + symbol_index * 0.015
        for metric, value in base_values.items():
            accounting_rows.append(
                {
                    "fact_id": f"{symbol}-{metric}-2024-original",
                    "entity": symbol,
                    "metric": metric,
                    "fiscal_period": "FY2024",
                    "period_end": "2024-12-31",
                    "fiscal_period_start": None if metric in instant else "2024-01-01",
                    "period_type": "instant" if metric in instant else "duration",
                    "filing_date": "2025-01-31T20:00:00Z",
                    "available_at": "2025-01-31T20:05:00Z",
                    "value": (
                        0.20 + symbol_index * 0.0005
                        if metric == "tax_rate"
                        else value * scale * (1.0 + symbol_index * metric_slopes[metric])
                    ),
                    "unit": "RATIO" if metric == "tax_rate" else "EUR",
                    "source": "licensed-file-export",
                    "dataset_version": "export-2025-03-15",
                    "revision": 0,
                    "revision_type": "ORIGINAL",
                    "supersedes_revision": None,
                    "data_confidence": 0.95,
                    "calculation_confidence": 0.95,
                    "economic_confidence": 0.95,
                }
            )
    pd.DataFrame(accounting_rows).to_csv(tmp_path / "accounting.csv", index=False)
    pd.DataFrame(
        [
            {
                "currency_pair": "EUR/USD",
                "base_currency": "EUR",
                "quote_currency": "USD",
                "market_timestamp": timestamp,
                "available_at": available,
                "rate": rate,
            }
            for timestamp, available, rate in (
                ("2024-12-31T16:00:00Z", "2024-12-31T16:01:00Z", 1.10),
                ("2025-03-14T16:00:00Z", "2025-03-14T16:01:00Z", 1.12),
            )
        ]
    ).to_csv(tmp_path / "fx.csv", index=False)

    files = {}
    for key, filename in {
        "universe": "universe.csv",
        "market_data": "market_data.csv",
        "accounting": "accounting.csv",
        "fx": "fx.csv",
    }.items():
        files[key] = {"path": filename, "sha256": _sha(tmp_path / filename)}
    manifest = {
        "schema_version": "pit-equity-research-files-v1",
        "source": "licensed-file-export",
        "dataset_version": "export-2025-03-15",
        "experiment_id": "100-security-pit-pilot",
        "as_of": AS_OF.isoformat(),
        "dataset_available_at": AS_OF.isoformat(),
        "base_currency": "USD",
        "benchmark_symbol": "SPY",
        "trading_calendar": "XNYS",
        "maximum_price_staleness_sessions": 0,
        "maximum_fx_staleness_sessions": 1,
        "universe_snapshot": {
            "claim": "PROVIDER_SUPPLIED_PIT_SNAPSHOT",
            "snapshot_id": "pit-membership-2025-03-15",
            "source": "licensed-file-export",
            "as_of": AS_OF.isoformat(),
        },
        "price_adjustment": {
            "series_usage": "FACTOR_RESEARCH_ONLY",
            "adjustment_scope": "SPLIT_AND_CASH_DIVIDEND",
            "portfolio_return_eligible": False,
        },
        "universe_rules": {"allowed_exchanges": ["NYSE"]},
        "required_fundamentals": sorted(FUNDAMENTALS),
        "files": files,
    }
    path = tmp_path / "pit_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def test_real_file_importer_builds_order_independent_100_security_qvm_cut(
    tmp_path: Path,
) -> None:
    manifest = _raw_pilot(tmp_path)
    result = build_and_run_pit_qvm(manifest_path=manifest, output_root=tmp_path / "outputs")
    report = json.loads(result.coverage_path.read_text())

    assert result.dataset.cross_layer.manifest.eligible_symbols_count == 100
    assert report["model_eligible_symbols"] == 100
    assert report["cohort_publication"] == "PASS"
    assert all(item["passing_symbols"] == 100 for item in report["coverage"].values())
    assert report["trade_decision"] == "NO_TRADE"
    assert report["live_execution_enabled"] is False
    assert report["real_data_readiness"] == "NOT_READY"
    assert report["survivorship_free_history_verified"] is False
    assert report["portfolio_return_ready"] is False
    assert report["remaining_backtest_blockers"] == [
        "SURVIVORSHIP_SAFE_PIT_HISTORICAL_INPUTS",
    ]

    volatility_adjusted = result.research.momentum.metrics.query(
        "metric == 'volatility_adjusted_momentum_12_1'"
    )["value"].abs()
    assert volatility_adjusted.max() < 1_000

    market_path = tmp_path / "market_data.csv"
    shuffled = pd.read_csv(market_path).sample(frac=1, random_state=7)
    shuffled.to_csv(market_path, index=False)
    document = json.loads(manifest.read_text())
    document["files"]["market_data"]["sha256"] = _sha(market_path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    rebuilt = build_pit_equity_dataset(
        manifest_path=manifest, output_root=tmp_path / "reordered"
    )
    assert (
        rebuilt.cross_layer.manifest.market_data_checksum
        == result.dataset.cross_layer.manifest.market_data_checksum
    )
    assert (
        rebuilt.cross_layer.manifest.cross_layer_fingerprint
        == result.dataset.cross_layer.manifest.cross_layer_fingerprint
    )


def test_importer_requires_cutoff_bound_universe_provenance(tmp_path: Path) -> None:
    manifest = _raw_pilot(tmp_path, symbols=1)
    path = tmp_path / "universe.csv"
    universe = pd.read_csv(path)
    universe.loc[0, "membership_as_of"] = "2025-03-14T23:59:00Z"
    universe.to_csv(path, index=False)
    document = json.loads(manifest.read_text())
    document["files"]["universe"]["sha256"] = _sha(path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DatasetVersionError, match="bound to manifest as_of"):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "outputs")


def test_split_and_dividend_series_is_research_only_and_rejects_double_adjustment(
    tmp_path: Path,
) -> None:
    manifest = _raw_pilot(tmp_path, symbols=1)
    path = tmp_path / "market_data.csv"
    market = pd.read_csv(path)
    market["corporate_action_type"] = market["corporate_action_type"].astype("object")
    symbol_rows = market.index[market["symbol"] == "S000"]
    split_row, dividend_row = symbol_rows[-40], symbol_rows[-20]
    market.loc[split_row, ["corporate_action_status", "corporate_action_type"]] = [
        "APPLIED",
        "SPLIT",
    ]
    market.loc[split_row, "raw_close"] = market.loc[split_row, "adjusted_close"] / 0.5
    market.loc[split_row, "adjustment_factor"] = 0.5
    market.loc[dividend_row, ["corporate_action_status", "corporate_action_type"]] = [
        "APPLIED",
        "DIVIDEND",
    ]
    market.loc[dividend_row, "raw_close"] = market.loc[dividend_row, "adjusted_close"] / 0.99
    market.loc[dividend_row, "adjustment_factor"] = 0.99
    market.to_csv(path, index=False)
    document = json.loads(manifest.read_text())
    document["files"]["market_data"]["sha256"] = _sha(path)
    manifest.write_text(json.dumps(document), encoding="utf-8")

    result = build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "valid")
    source_manifest = json.loads((result.output_dir / "source_manifest.json").read_text())
    assert source_manifest["price_adjustment"]["series_usage"] == "FACTOR_RESEARCH_ONLY"
    assert source_manifest["research_limitations"]["portfolio_return_ready"] is False

    market.loc[split_row, "adjusted_close"] *= 0.5
    market.to_csv(path, index=False)
    document["files"]["market_data"]["sha256"] = _sha(path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="raw and adjusted close do not reconcile"):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "invalid")


def test_importer_rejects_source_file_tamper(tmp_path: Path) -> None:
    manifest = _raw_pilot(tmp_path, symbols=1)
    path = tmp_path / "universe.csv"
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(DatasetVersionError, match="checksum mismatch: universe"):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "outputs")


def test_importer_rejects_future_price_and_universe_mismatch(tmp_path: Path) -> None:
    manifest = _raw_pilot(tmp_path, symbols=1)
    market_path = tmp_path / "market_data.csv"
    market = pd.read_csv(market_path)
    market.loc[0, "available_at"] = "2025-03-16T00:00:00Z"
    market.to_csv(market_path, index=False)
    document = json.loads(manifest.read_text())
    document["files"]["market_data"]["sha256"] = _sha(market_path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="row available_at exceeds as_of"):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "future")

    manifest = _raw_pilot(tmp_path / "mismatch", symbols=1)
    accounting_path = manifest.parent / "accounting.csv"
    accounting = pd.read_csv(accounting_path)
    accounting["entity"] = "ZZZ"
    accounting.to_csv(accounting_path, index=False)
    document = json.loads(manifest.read_text())
    document["files"]["accounting"]["sha256"] = _sha(accounting_path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="missing fundamentals under policy"):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "mismatch-out")


@pytest.mark.parametrize(
    ("filename", "mutate", "message"),
    [
        (
            "market_data.csv",
            lambda frame: frame.assign(
                adjustment_factor=frame["adjustment_factor"].mask(frame.index == 0, 0.5)
            ),
            "raw and adjusted close do not reconcile",
        ),
        (
            "fx.csv",
            lambda frame: frame.assign(
                market_timestamp="2024-12-31T16:00:00Z",
                available_at="2024-12-31T16:01:00Z",
            ).iloc[:1],
            "stale",
        ),
    ],
)
def test_importer_rejects_bad_adjustments_and_stale_fx(
    tmp_path: Path, filename: str, mutate, message: str
) -> None:
    manifest = _raw_pilot(tmp_path, symbols=1)
    path = tmp_path / filename
    mutate(pd.read_csv(path)).to_csv(path, index=False)
    document = json.loads(manifest.read_text())
    key = "market_data" if filename == "market_data.csv" else "fx"
    document["files"][key]["sha256"] = _sha(path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "outputs")


def test_importer_rejects_conflicting_accounting_identity(tmp_path: Path) -> None:
    manifest = _raw_pilot(tmp_path, symbols=1)
    path = tmp_path / "accounting.csv"
    accounting = pd.read_csv(path)
    duplicate = accounting.iloc[[0]].copy()
    duplicate["fact_id"] = "conflicting-duplicate"
    duplicate["value"] = duplicate["value"] * 2
    pd.concat([accounting, duplicate], ignore_index=True).to_csv(path, index=False)
    document = json.loads(manifest.read_text())
    document["files"]["accounting"]["sha256"] = _sha(path)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="repeated economic fact revision"):
        build_pit_equity_dataset(manifest_path=manifest, output_root=tmp_path / "outputs")
