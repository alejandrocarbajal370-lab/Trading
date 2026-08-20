from __future__ import annotations

import datetime
from typing import Protocol

import pandas as pd


class PriceSource(Protocol):
    """Contract implemented by all end-of-day price sources."""

    @property
    def name(self) -> str: ...

    def fetch(self, *, symbols: set[str], data_date: datetime.date) -> pd.DataFrame: ...


class PriceSourceError(RuntimeError):
    """Base error for failures obtaining or decoding provider data."""


class PriceSourceConfigurationError(PriceSourceError):
    """Raised when required source configuration is unavailable."""


class PriceSourceRequestError(PriceSourceError):
    """Raised after a provider request cannot be completed safely."""


class PriceSourceResponseError(PriceSourceError):
    """Raised when a provider returns an error or an invalid payload."""
