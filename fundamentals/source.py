from __future__ import annotations

import datetime
from typing import Protocol

import pandas as pd


class FundamentalSource(Protocol):
    """Raw fundamental records with explicit public-availability timestamps."""

    @property
    def name(self) -> str: ...

    def fetch(self, *, symbols: set[str]) -> pd.DataFrame: ...


class FundamentalSourceError(RuntimeError):
    """Base error for obtaining or decoding fundamental data."""


class FundamentalSourceResponseError(FundamentalSourceError):
    """Raised when a source returns data that cannot satisfy the contract."""


class PointInTimeViolation(RuntimeError):
    """Raised if a selected snapshot contains information from the future."""


def normalize_data_timestamp(value: datetime.date | datetime.datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
