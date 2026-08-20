from __future__ import annotations

import pandas as pd

from fundamentals.pit import select_point_in_time

VERSION_KEY = [
    "symbol",
    "fiscal_period_start",
    "fiscal_period_end",
    "period_type",
    "metric",
    "available_at",
    "filed_at",
]


def preserve_version_history(records: pd.DataFrame) -> pd.DataFrame:
    """Return immutable-version rows; conflicting duplicate version identities fail."""
    duplicated = records.duplicated(VERSION_KEY, keep=False)
    if duplicated.any():
        groups = records.loc[duplicated].groupby(VERSION_KEY, dropna=False)["value"].nunique()
        if (groups > 1).any():
            raise ValueError("conflicting values for the same fundamental version")
    return (
        records.drop_duplicates(VERSION_KEY, keep="last")
        .sort_values(VERSION_KEY)
        .reset_index(drop=True)
    )


def historical_snapshot(records: pd.DataFrame, *, available_at: pd.Timestamp) -> pd.DataFrame:
    return select_point_in_time(preserve_version_history(records), data_date=available_at)
