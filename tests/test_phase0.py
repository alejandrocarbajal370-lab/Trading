import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core.phase0 import run_phase0
from data.validation.health import HealthStatus


def _write_prices(path: Path, *, close: float = 232.75) -> None:
    pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "date": "2026-08-19",
                "open": 230.1,
                "high": 233.4,
                "low": 229.8,
                "close": close,
                "volume": 50_210_000,
            }
        ]
    ).to_csv(path, index=False)


def test_phase0_writes_a_complete_validation_bundle(tmp_path: Path) -> None:
    source = tmp_path / "prices.csv"
    _write_prices(source)
    result = run_phase0(
        source_path=source,
        symbols={"AAPL"},
        data_date=datetime.date(2026, 8, 19),
        output_root=tmp_path / "outputs",
        now=datetime.datetime(2026, 8, 20, 12, 0, tzinfo=ZoneInfo("America/Mexico_City")),
    )

    assert result.health.status is HealthStatus.PASS
    assert {path.name for path in result.output_dir.iterdir()} == {
        "data_health.json",
        "ingested_prices.csv",
        "run_summary.json",
        "validation_manifest.json",
    }
    manifest = json.loads((result.output_dir / "validation_manifest.json").read_text())
    summary = json.loads((result.output_dir / "run_summary.json").read_text())
    assert manifest["checks"]["live_execution"] == "DISABLED"
    assert summary["trade_decision"] == "NO_TRADE"


def test_phase0_fails_health_for_invalid_price(tmp_path: Path) -> None:
    source = tmp_path / "prices.csv"
    _write_prices(source, close=-1)
    result = run_phase0(
        source_path=source,
        symbols={"AAPL"},
        data_date=datetime.date(2026, 8, 19),
        output_root=tmp_path / "outputs",
    )
    assert result.health.status is HealthStatus.FAIL
