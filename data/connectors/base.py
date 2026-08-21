from __future__ import annotations

import datetime
from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class PriceSource(Protocol):
    """Contract implemented by all end-of-day price sources."""

    @property
    def name(self) -> str: ...

    def fetch(self, *, symbols: set[str], data_date: datetime.date) -> pd.DataFrame: ...


@runtime_checkable
class MomentumHistoricalPriceSource(Protocol):
    """Independent contract for adjusted history used by Momentum research."""

    @property
    def name(self) -> str: ...

    @property
    def metadata(self) -> dict[str, str]: ...

    def fetch_history(self, *, symbols: set[str], as_of: datetime.date) -> pd.DataFrame: ...


class PriceSourceError(RuntimeError):
    """Base error for failures obtaining or decoding provider data."""


class PriceSourceConfigurationError(PriceSourceError):
    """Raised when required source configuration is unavailable."""


class PriceSourceRequestError(PriceSourceError):
    """Raised after a provider request cannot be completed safely."""


class PriceSourceResponseError(PriceSourceError):
    """Raised when a provider returns an error or an invalid payload."""
