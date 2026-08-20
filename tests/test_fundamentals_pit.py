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
    normalize_data_timestamp,
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
        "fundamental_history.csv",
        "fundamental_snapshot.csv",
        "data_confidence.csv",
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


def test_date_cutoff_includes_filing_available_before_market_end_of_day() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    same_day = records.iloc[[0]].copy()
    same_day["available_at"] = pd.Timestamp("2025-11-01T20:00:00Z")

    snapshot = select_point_in_time(same_day, data_date=datetime.date(2025, 11, 1))

    assert snapshot["value"].tolist() == [100]


def test_date_cutoff_excludes_filing_available_after_market_end_of_day() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"})
    after_cutoff = records.iloc[[0]].copy()
    after_cutoff["available_at"] = pd.Timestamp("2025-11-02T04:00:00Z")

    snapshot = select_point_in_time(after_cutoff, data_date=datetime.date(2025, 11, 1))

    assert snapshot.empty


def test_datetime_cutoff_preserves_exact_instant_and_naive_means_utc() -> None:
    aware = datetime.datetime(2025, 11, 1, 16, 30, tzinfo=ZoneInfo("America/New_York"))
    naive = datetime.datetime(2025, 11, 1, 20, 30, tzinfo=datetime.UTC).replace(tzinfo=None)

    assert normalize_data_timestamp(aware) == pd.Timestamp("2025-11-01T20:30:00Z")
    assert normalize_data_timestamp(naive) == pd.Timestamp("2025-11-01T20:30:00Z")


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


def test_pit_identity_preserves_different_start_and_period_type() -> None:
    records = CsvFundamentalSource(FIXTURE).fetch(symbols={"AAPL"}).iloc[[0]].copy()
    ytd = records.copy()
    ytd["fiscal_period_start"] = datetime.date(2025, 1, 1)
    instant = records.copy()
    instant["fiscal_period_start"] = None
    instant["period_type"] = "instant"
    snapshot = select_point_in_time(
        pd.concat([records, ytd, instant], ignore_index=True),
        data_date=datetime.datetime(2025, 11, 1, tzinfo=datetime.UTC),
    )
    assert len(snapshot) == 3
    assert set(snapshot["period_type"]) == {"duration", "instant"}


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
