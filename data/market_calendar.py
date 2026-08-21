from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, ClassVar

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)
from pandas.tseries.offsets import CustomBusinessDay


class _XNYSHolidays(AbstractHolidayCalendar):
    rules: ClassVar[list[Any]] = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


@dataclass(frozen=True)
class TradingCalendar:
    name: str
    sessions_per_year: int
    business_day: CustomBusinessDay

    def sessions(self, start: datetime.date, end: datetime.date) -> tuple[datetime.date, ...]:
        if end < start:
            return ()
        return tuple(pd.date_range(start, end, freq=self.business_day).date)


_CALENDARS = {
    "XNYS": TradingCalendar("XNYS", 252, CustomBusinessDay(calendar=_XNYSHolidays())),
}


def get_trading_calendar(name: str) -> TradingCalendar:
    try:
        return _CALENDARS[name]
    except KeyError as error:
        raise ValueError(f"unsupported trading_calendar: {name}") from error
