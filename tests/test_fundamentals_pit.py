import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.phase2 import run_phase2
from fundamentals.csv_source import CsvFundamentalSource
from fundamentals.pit import assert_point_in_time, select_point_in_time
from fundamentals.source import (
    FundamentalSourceResponseError,
    PointInTimeViolation,
)

FIXTURE = Path("tests/fixtures/fundamentals_pit.csv")


def test_success_path_writes_pit_outputs_and_preserves_safety(tmp_path: Path) -> None:
    result = run_phase2(
        symbols={"AAPL"},
        data_date=datetime.datetime(2025, 11, 1, tzinfo=datetime.UTC),
        source_path=FIXTURE,
        output_root=tmp_path,
        now=datetime.datetime(2026, 8, 20, tzinfo=ZoneInfo("America/Mexico_City")),
    )
    assert result.snapshot["value"].tolist() == [100]
    assert {path.name for path in result.output_dir.iterdir()} == {
        "fundamental_snapshot.csv",
        "fundamental_health.json",
        "run_summary.json",
        "validation_manifest.json",
    }
    summary = json.loads((result.output_dir / "run_summary.json").read_text())
    assert summary["trade_decision"] == "NO_TRADE"
    assert summary["live_execution_enabled"] is False


def test_future_filing_is_excluded_without_lookahead() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    snapshot = select_point_in_time(
        records, data_date=datetime.datetime(2025, 11, 1, tzinfo=datetime.UTC)
    )
    assert snapshot["available_at"].max() <= pd.Timestamp("2025-11-01T00:00:00Z")
    assert snapshot["value"].tolist() == [100]


def test_late_filing_is_unavailable_for_earlier_economic_period() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    snapshot = select_point_in_time(
        records, data_date=datetime.datetime(2025, 10, 1, tzinfo=datetime.UTC)
    )
    assert snapshot.empty


def test_latest_available_amendment_replaces_original() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    snapshot = select_point_in_time(
        records, data_date=datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC)
    )
    assert snapshot["value"].tolist() == [105]


def test_explicit_future_snapshot_is_a_pit_violation() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    with pytest.raises(PointInTimeViolation, match="PIT violation"):
        assert_point_in_time(
            records,
            data_date=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        )


def test_missing_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    path.write_text("symbol,value\nAAPL,1\n", encoding="utf-8")
    with pytest.raises(FundamentalSourceResponseError, match="missing required fields"):
        CsvFundamentalSource(path).fetch(symbols={"AAPL"})


class FailingSource:
    name = "failed_provider"

    def fetch(self, *, symbols: set[str]) -> pd.DataFrame:
        raise FundamentalSourceResponseError("provider unavailable")


def test_provider_failure_leaves_audit_trail(tmp_path: Path) -> None:
    with pytest.raises(FundamentalSourceResponseError, match="provider unavailable"):
        run_phase2(
            symbols={"AAPL"},
            data_date=datetime.date(2025, 11, 1),
            fundamental_source=FailingSource(),
            output_root=tmp_path,
        )
    run_dir = next(tmp_path.iterdir())
    assert {path.name for path in run_dir.iterdir()} == {
        "run_summary.json",
        "validation_manifest.json",
    }
    summary = json.loads((run_dir / "run_summary.json").read_text())
    assert summary["overall_status"] == "FAIL"
    assert summary["fundamental_health"] == "NOT_RUN"
    assert summary["trade_decision"] == "NO_TRADE"
    assert summary["live_execution_enabled"] is False


def test_pipeline_marks_a_future_snapshot_as_pit_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    monkeypatch.setattr("core.phase2.select_point_in_time", lambda *_args, **_kwargs: records)

    with pytest.raises(PointInTimeViolation, match="PIT violation"):
        run_phase2(
            symbols={"AAPL"},
            data_date=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
            source_path=FIXTURE,
            output_root=tmp_path,
        )

    run_dir = next(tmp_path.iterdir())
    manifest = json.loads((run_dir / "validation_manifest.json").read_text())
    assert manifest["overall_status"] == "FAIL"
    assert manifest["checks"]["point_in_time"] == "FAIL"
