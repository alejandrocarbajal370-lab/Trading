import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.phase0 import run_phase0
from data.connectors.base import (
    PriceSourceConfigurationError,
    PriceSourceRequestError,
    PriceSourceResponseError,
)
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
    assert summary["data_source"] == "csv"


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


class _FailingPriceSource:
    name = "test-provider"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch(self, **_kwargs: object) -> pd.DataFrame:
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        PriceSourceRequestError("provider timed out"),
        PriceSourceResponseError("provider returned malformed data"),
    ],
)
def test_phase0_writes_failure_bundle_before_source_error(tmp_path: Path, error: Exception) -> None:
    output_root = tmp_path / "outputs"

    with pytest.raises(type(error), match=str(error)):
        run_phase0(
            price_source=_FailingPriceSource(error),
            symbols={"AAPL"},
            data_date=datetime.date(2026, 8, 19),
            output_root=output_root,
            now=datetime.datetime(2026, 8, 20, 12, 0, tzinfo=ZoneInfo("America/Mexico_City")),
        )

    run_dirs = list(output_root.iterdir())
    assert len(run_dirs) == 1
    assert {path.name for path in run_dirs[0].iterdir()} == {
        "run_summary.json",
        "validation_manifest.json",
    }
    manifest = json.loads((run_dirs[0] / "validation_manifest.json").read_text())
    summary = json.loads((run_dirs[0] / "run_summary.json").read_text())
    assert manifest["run_id"] == run_dirs[0].name
    assert manifest["overall_status"] == "FAIL"
    assert manifest["checks"] == {
        "data_health": "NOT_RUN",
        "live_execution": "DISABLED",
        "market_data_source": "FAIL",
        "trade_decision": "NO_TRADE",
    }
    assert summary == {
        "data_health": "NOT_RUN",
        "data_source": "test-provider",
        "error_message": str(error),
        "error_type": type(error).__name__,
        "live_execution_enabled": False,
        "overall_status": "FAIL",
        "run_id": run_dirs[0].name,
        "source_path": None,
        "trade_decision": "NO_TRADE",
    }
    assert not (run_dirs[0] / "ingested_prices.csv").exists()
    assert not (run_dirs[0] / "data_health.json").exists()


def test_phase0_audits_missing_provider_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    output_root = tmp_path / "outputs"

    with pytest.raises(PriceSourceConfigurationError, match="ALPHA_VANTAGE_API_KEY"):
        run_phase0(
            provider="alpha-vantage",
            symbols={"AAPL"},
            data_date=datetime.date(2026, 8, 19),
            output_root=output_root,
        )

    run_dir = next(output_root.iterdir())
    manifest = json.loads((run_dir / "validation_manifest.json").read_text())
    summary = json.loads((run_dir / "run_summary.json").read_text())
    assert manifest["overall_status"] == "FAIL"
    assert manifest["checks"]["data_health"] == "NOT_RUN"
    assert summary["data_source"] == "alpha-vantage"
    assert summary["error_type"] == "PriceSourceConfigurationError"
    assert summary["trade_decision"] == "NO_TRADE"
