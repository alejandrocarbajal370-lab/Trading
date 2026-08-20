from __future__ import annotations

import calendar
import datetime
from dataclasses import asdict, dataclass
from typing import Any, Literal

import pandas as pd

RebalanceFrequency = Literal["daily", "weekly", "monthly", "quarterly", "annual"]


@dataclass(frozen=True)
class UniverseRebalanceSchedule:
    """Configuration contract for universe refreshes; it does not schedule jobs."""

    frequency: RebalanceFrequency = "monthly"
    interval: int = 1

    def __post_init__(self) -> None:
        if self.interval < 1:
            raise ValueError("rebalance interval must be positive")

    def next_expected_date(self, snapshot_date: datetime.date | pd.Timestamp) -> datetime.date:
        current = pd.Timestamp(snapshot_date).date()
        if self.frequency == "daily":
            return current + datetime.timedelta(days=self.interval)
        if self.frequency == "weekly":
            return current + datetime.timedelta(weeks=self.interval)
        months = {"monthly": 1, "quarterly": 3, "annual": 12}[self.frequency] * self.interval
        absolute_month = current.year * 12 + current.month - 1 + months
        year, zero_based_month = divmod(absolute_month, 12)
        month = zero_based_month + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return datetime.date(year, month, day)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
