from __future__ import annotations

import datetime

import pandas as pd

from fundamentals.source import PointInTimeViolation, normalize_data_timestamp

KEY_COLUMNS = [
    "symbol",
    "fiscal_period_start",
    "fiscal_period_end",
    "period_type",
    "metric",
]


def select_point_in_time(
    records: pd.DataFrame, *, data_date: datetime.date | datetime.datetime
) -> pd.DataFrame:
    """Select the latest publicly available filing/amendment for each economic fact."""
    cutoff = normalize_data_timestamp(data_date)
    eligible = records[records["available_at"] <= cutoff].copy()
    # pandas drops NA group keys by default; use a sentinel so instant facts retain
    # their explicit null start while amendments are selected.
    eligible["_period_start_key"] = (
        eligible["fiscal_period_start"].astype("string").fillna("<instant>")
    )
    keys = ["symbol", "_period_start_key", "fiscal_period_end", "period_type", "metric"]
    eligible = eligible.sort_values(keys + ["available_at", "filed_at"])
    snapshot = (
        eligible.drop_duplicates(keys, keep="last")
        .drop(columns="_period_start_key")
        .reset_index(drop=True)
    )
    if (snapshot["available_at"] > cutoff).any():
        raise PointInTimeViolation("PIT violation: snapshot includes future information")
    return snapshot


def assert_point_in_time(
    snapshot: pd.DataFrame, *, data_date: datetime.date | datetime.datetime
) -> None:
    cutoff = normalize_data_timestamp(data_date)
    if (snapshot["available_at"] > cutoff).any():
        raise PointInTimeViolation("PIT violation: available_at exceeds data_date")
