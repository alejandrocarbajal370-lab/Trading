import datetime

import pandas as pd
import pytest

from data.validation.health import HealthStatus
from data.validation.prices import validate_prices

DATA_DATE = datetime.date(2026, 8, 19)


def _prices(**overrides: object) -> pd.DataFrame:
    row = {
        "symbol": "AAPL",
        "date": DATA_DATE,
        "open": 230.1,
        "high": 233.4,
        "low": 229.8,
        "close": 232.75,
        "volume": 50_210_000,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _validate(frame: pd.DataFrame):
    return validate_prices(frame, expected_symbols={"AAPL"}, data_date=DATA_DATE)


def test_future_date_is_a_point_in_time_violation_and_fails() -> None:
    result = _validate(_prices(date=DATA_DATE + datetime.timedelta(days=1)))

    assert result.status is HealthStatus.FAIL
    assert result.point_in_time_violations == 1
    assert any("point-in-time" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("open", 229.7),
        ("open", 233.5),
        ("close", 229.7),
        ("close", 233.5),
    ],
)
def test_open_or_close_outside_low_high_range_fails(column: str, value: float) -> None:
    result = _validate(_prices(**{column: value}))

    assert result.status is HealthStatus.FAIL
    assert result.invalid_price_rows == 1


@pytest.mark.parametrize("volume", [float("nan"), -1])
def test_invalid_or_negative_volume_fails(volume: float) -> None:
    result = _validate(_prices(volume=volume))

    assert result.status is HealthStatus.FAIL
    assert result.invalid_volume_rows == 1


def test_zero_volume_is_valid() -> None:
    result = _validate(_prices(volume=0))

    assert result.status is HealthStatus.PASS
    assert result.invalid_volume_rows == 0
