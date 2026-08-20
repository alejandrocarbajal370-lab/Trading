from __future__ import annotations

import datetime

import pandas as pd

from fundamentals.source import PointInTimeViolation, normalize_data_timestamp

KEY_COLUMNS = ["symbol", "fiscal_period_end", "metric"]


def select_point_in_time(
    records: pd.DataFrame, *, data_date: datetime.date | datetime.datetime
) -> pd.DataFrame:
    """Select the latest publicly available filing/amendment for each economic fact."""
    cutoff = normalize_data_timestamp(data_date)
    eligible = records[records["available_at"] <= cutoff].copy()
    eligible = eligible.sort_values(KEY_COLUMNS + ["available_at", "filed_at"])
    snapshot = eligible.drop_duplicates(KEY_COLUMNS, keep="last").reset_index(drop=True)
    if (snapshot["available_at"] > cutoff).any():
        raise PointInTimeViolation("PIT violation: snapshot includes future information")
    return snapshot


def assert_point_in_time(
    snapshot: pd.DataFrame, *, data_date: datetime.date | datetime.datetime
) -> None:
    cutoff = normalize_data_timestamp(data_date)
    if (snapshot["available_at"] > cutoff).any():
        raise PointInTimeViolation("PIT violation: available_at exceeds data_date")
