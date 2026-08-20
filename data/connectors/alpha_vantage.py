from __future__ import annotations

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from data.connectors.base import (
    PriceSourceConfigurationError,
    PriceSourceRequestError,
    PriceSourceResponseError,
)
from data.connectors.csv_prices import REQUIRED_COLUMNS

DEFAULT_BASE_URL = "https://www.alphavantage.co/query"


@dataclass(frozen=True)
class AlphaVantagePriceSource:
    """Alpha Vantage TIME_SERIES_DAILY adapter for unadjusted EOD OHLCV."""

    api_key: str
    timeout_seconds: float = 10.0
    max_retries: int = 2
    base_url: str = DEFAULT_BASE_URL
    opener: Callable[..., object] = urllib.request.urlopen
    sleeper: Callable[[float], None] = time.sleep

    @classmethod
    def from_env(cls) -> AlphaVantagePriceSource:
        api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
        if not api_key:
            raise PriceSourceConfigurationError(
                "ALPHA_VANTAGE_API_KEY must be set for the alpha-vantage source"
            )
        return cls(api_key=api_key)

    @property
    def name(self) -> str:
        return "alpha_vantage"

    def fetch(self, *, symbols: set[str], data_date: datetime.date) -> pd.DataFrame:
        rows = [self._fetch_symbol(symbol, data_date) for symbol in sorted(symbols)]
        return pd.DataFrame(rows, columns=REQUIRED_COLUMNS).sort_values(
            ["date", "symbol"], ignore_index=True
        )

    def _fetch_symbol(self, symbol: str, data_date: datetime.date) -> dict[str, object]:
        query = urllib.parse.urlencode(
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": self.api_key,
            }
        )
        payload = self._request_json(f"{self.base_url}?{query}")
        provider_error = payload.get("Error Message") or payload.get("Note") or payload.get(
            "Information"
        )
        if provider_error:
            raise PriceSourceResponseError(f"Alpha Vantage rejected {symbol}: {provider_error}")

        series = payload.get("Time Series (Daily)")
        if not isinstance(series, dict):
            raise PriceSourceResponseError(
                f"Alpha Vantage response for {symbol} has no daily time series"
            )
        values = series.get(data_date.isoformat())
        if not isinstance(values, dict):
            raise PriceSourceResponseError(
                f"Alpha Vantage returned no EOD row for {symbol} on {data_date.isoformat()}"
            )
        try:
            return {
                "symbol": symbol.strip().upper(),
                "date": data_date,
                "open": float(values["1. open"]),
                "high": float(values["2. high"]),
                "low": float(values["3. low"]),
                "close": float(values["4. close"]),
                "volume": float(values["5. volume"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceSourceResponseError(
                f"Alpha Vantage returned an invalid EOD row for {symbol}"
            ) from exc

    def _request_json(self, url: str) -> dict[str, object]:
        for attempt in range(self.max_retries + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Trading/0.1"})
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise PriceSourceResponseError("Alpha Vantage returned a non-object response")
                return payload
            except PriceSourceResponseError:
                raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == self.max_retries:
                    raise PriceSourceRequestError(
                        f"Alpha Vantage request failed after {attempt + 1} attempts"
                    ) from exc
                self.sleeper(0.25 * (2**attempt))
        raise AssertionError("retry loop exited unexpectedly")
