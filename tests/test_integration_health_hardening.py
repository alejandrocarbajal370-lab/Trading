import datetime
import json
from pathlib import Path

import pandas as pd

from core.phase2 import run_phase2
from core.phase36 import run_phase36
from universe.validation import UniverseRules

PIT_FIXTURE = Path("tests/fixtures/fundamentals_pit.csv")


def test_phase2_empty_pit_snapshot_is_fail_not_false_pass(tmp_path: Path) -> None:
    result = run_phase2(
        symbols={"AAPL"},
        data_date=datetime.datetime(2025, 10, 1, tzinfo=datetime.UTC),
        source_path=PIT_FIXTURE,
        output_root=tmp_path,
    )
    assert result.snapshot.empty
    health = json.loads((result.output_dir / "fundamental_health.json").read_text())
    summary = json.loads((result.output_dir / "run_summary.json").read_text())
    manifest = json.loads((result.output_dir / "validation_manifest.json").read_text())
    assert health["status"] == "FAIL"
    assert health["point_in_time"] == "PASS"
    assert summary["overall_status"] == "FAIL"
    assert manifest["critical_errors"] == 1
    assert summary["trade_decision"] == "NO_TRADE"
    assert summary["live_execution_enabled"] is False


def test_universe_fail_sets_critical_error_in_manifest(tmp_path: Path) -> None:
    source = tmp_path / "universe.csv"
    pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Industrials",
                "industry": "Machinery",
                "market_cap": 100,
                "average_volume": 100,
                "average_dollar_volume": 100,
                "listing_date": "2020-01-01T00:00:00Z",
                "source": "fixture",
                "source_timestamp": "2026-02-28T00:00:00Z",
                "available_at": "2026-02-28T00:00:00Z",
            }
        ]
    ).to_csv(source, index=False)
    result = run_phase36(
        source_path=source,
        rules=UniverseRules(minimum_market_cap=1_000_000, allowed_exchanges=("NYSE",)),
        as_of=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
        output_root=tmp_path / "validation",
        snapshot_root=tmp_path / "snapshots",
    )
    manifest = json.loads((result.output_dir / "validation_manifest.json").read_text())
    summary = json.loads((result.output_dir / "run_summary.json").read_text())
    assert summary["overall_status"] == "FAIL"
    assert manifest["critical_errors"] == 1
    assert manifest["checks"]["universe_validation"] == "FAIL"
