from __future__ import annotations

import datetime

import pandas as pd

from data.validation.health import DataHealthResult, evaluate_data_health


def validate_prices(
    frame: pd.DataFrame,
    *,
    expected_symbols: set[str],
    data_date: datetime.date,
    minimum_coverage: float = 0.98,
) -> DataHealthResult:
    dated = frame.loc[frame["date"] == data_date]
    received_symbols = set(dated["symbol"].dropna()) & expected_symbols
    duplicate_rows = int(frame.duplicated(subset=["symbol", "date"]).sum())
    invalid_prices = (
        frame[["open", "high", "low", "close"]].isna().any(axis=1)
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame["high"] < frame["low"])
    )
    critical_missing = frame[["symbol", "date", "close"]].isna().any(axis=1)
    stale_rows = frame["date"].notna() & (frame["date"] < data_date)

    return evaluate_data_health(
        expected_rows=len(expected_symbols),
        received_rows=len(received_symbols),
        duplicate_rows=duplicate_rows,
        stale_critical_rows=int(stale_rows.sum()),
        invalid_price_rows=int(invalid_prices.sum()),
        critical_missing_rows=int(critical_missing.sum()),
        minimum_coverage=minimum_coverage,
    )
