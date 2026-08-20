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
    prices = frame[["open", "high", "low", "close"]]
    invalid_prices = prices.isna().any(axis=1) | (prices <= 0).any(axis=1)
    invalid_prices |= frame["high"] < frame["low"]
    invalid_prices |= ~frame["open"].between(frame["low"], frame["high"])
    invalid_prices |= ~frame["close"].between(frame["low"], frame["high"])
    invalid_volume = frame["volume"].isna() | (frame["volume"] < 0)
    critical_missing = frame[["symbol", "date", "close"]].isna().any(axis=1)
    stale_rows = frame["date"].notna() & (frame["date"] < data_date)
    point_in_time_violations = frame["date"].notna() & (frame["date"] > data_date)

    return evaluate_data_health(
        expected_rows=len(expected_symbols),
        received_rows=len(received_symbols),
        duplicate_rows=duplicate_rows,
        stale_critical_rows=int(stale_rows.sum()),
        invalid_price_rows=int(invalid_prices.sum()),
        invalid_volume_rows=int(invalid_volume.sum()),
        critical_missing_rows=int(critical_missing.sum()),
        point_in_time_violations=int(point_in_time_violations.sum()),
        minimum_coverage=minimum_coverage,
    )
