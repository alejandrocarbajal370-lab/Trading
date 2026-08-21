import datetime

import pytest

from data.market_calendar import get_trading_calendar


def test_xnys_calendar_is_versioned_and_has_lineage() -> None:
    calendar = get_trading_calendar("XNYS")
    assert calendar.version == "xnys-historical-sessions-v1"
    assert calendar.lineage["source"].startswith("NYSE published holidays")
    assert calendar.lineage["extraordinary_closures_versioned"] is True


@pytest.mark.parametrize(
    "closed",
    [datetime.date(2001, 9, 11), datetime.date(2012, 10, 29), datetime.date(2018, 12, 5)],
)
def test_xnys_extraordinary_closures_are_not_sessions(closed: datetime.date) -> None:
    calendar = get_trading_calendar("XNYS")
    assert closed not in calendar.sessions(closed, closed)


def test_xnys_non_standard_holiday_is_historical() -> None:
    calendar = get_trading_calendar("XNYS")
    sessions = calendar.sessions(datetime.date(2021, 6, 18), datetime.date(2022, 6, 20))
    assert datetime.date(2021, 6, 18) in sessions
    assert datetime.date(2022, 6, 20) not in sessions


def test_calendar_fails_outside_versioned_range() -> None:
    with pytest.raises(ValueError, match="supports"):
        get_trading_calendar("XNYS").sessions(
            datetime.date(1999, 12, 31), datetime.date(2000, 1, 3)
        )
