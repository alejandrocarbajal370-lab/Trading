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
    version: str
    source: str
    valid_from: datetime.date
    valid_to: datetime.date
    extraordinary_closures: frozenset[datetime.date]

    def sessions(self, start: datetime.date, end: datetime.date) -> tuple[datetime.date, ...]:
        if end < start:
            return ()
        if start < self.valid_from or end > self.valid_to:
            raise ValueError(
                f"{self.name} calendar {self.version} supports "
                f"{self.valid_from.isoformat()} through {self.valid_to.isoformat()}"
            )
        dates = pd.date_range(start, end, freq=self.business_day).date
        return tuple(day for day in dates if day not in self.extraordinary_closures)

    @property
    def lineage(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "extraordinary_closures_versioned": True,
        }


_XNYS_EXTRAORDINARY_CLOSURES = frozenset(
    {
        # September 11 attacks and infrastructure recovery.
        datetime.date(2001, 9, 11),
        datetime.date(2001, 9, 12),
        datetime.date(2001, 9, 13),
        datetime.date(2001, 9, 14),
        # Presidential funerals and Hurricane Sandy.
        datetime.date(2004, 6, 11),
        datetime.date(2007, 1, 2),
        datetime.date(2012, 10, 29),
        datetime.date(2012, 10, 30),
        datetime.date(2018, 12, 5),
    }
)

_CALENDARS = {
    "XNYS": TradingCalendar(
        name="XNYS",
        sessions_per_year=252,
        business_day=CustomBusinessDay(calendar=_XNYSHolidays()),
        version="xnys-historical-sessions-v1",
        source="NYSE published holidays + versioned extraordinary closures",
        valid_from=datetime.date(2000, 1, 1),
        valid_to=datetime.date(2030, 12, 31),
        extraordinary_closures=_XNYS_EXTRAORDINARY_CLOSURES,
    ),
}


def get_trading_calendar(name: str) -> TradingCalendar:
    try:
        return _CALENDARS[name]
    except KeyError as error:
        raise ValueError(f"unsupported trading_calendar: {name}") from error
