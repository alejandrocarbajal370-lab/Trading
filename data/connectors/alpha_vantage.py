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
    """Alpha Vantage adjusted daily adapter with corporate-action lineage."""

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

    def fetch_history(self, *, symbols: set[str], as_of: datetime.date) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for symbol in sorted(symbols):
            payload = self._daily_adjusted_payload(symbol)
            series = payload.get("Time Series (Daily)")
            if not isinstance(series, dict):
                raise PriceSourceResponseError(
                    f"Alpha Vantage response for {symbol} has no adjusted daily time series"
                )
            for raw_date, values in series.items():
                if not isinstance(values, dict):
                    continue
                date = datetime.date.fromisoformat(str(raw_date))
                if date <= as_of:
                    rows.append(self._momentum_row(symbol, date, values))
        return pd.DataFrame(rows).sort_values(["symbol", "date"], ignore_index=True)

    def _fetch_symbol(self, symbol: str, data_date: datetime.date) -> dict[str, object]:
        payload = self._daily_adjusted_payload(symbol)
        provider_error = (
            payload.get("Error Message") or payload.get("Note") or payload.get("Information")
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
                "volume": float(values["6. volume"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceSourceResponseError(
                f"Alpha Vantage returned an invalid EOD row for {symbol}"
            ) from exc

    def _daily_adjusted_payload(self, symbol: str) -> dict[str, object]:
        query = urllib.parse.urlencode(
            {
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": symbol,
                "outputsize": "full",
                "apikey": self.api_key,
            }
        )
        payload = self._request_json(f"{self.base_url}?{query}")
        provider_error = (
            payload.get("Error Message") or payload.get("Note") or payload.get("Information")
        )
        if provider_error:
            raise PriceSourceResponseError(f"Alpha Vantage rejected {symbol}: {provider_error}")
        return payload

    @staticmethod
    def _momentum_row(
        symbol: str, date: datetime.date, values: dict[str, object]
    ) -> dict[str, object]:
        try:
            raw_close = float(values["4. close"])
            adjusted_close = float(values["5. adjusted close"])
            dividend = float(values["7. dividend amount"])
            split = float(values["8. split coefficient"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceSourceResponseError(
                f"Alpha Vantage returned an invalid adjusted EOD row for {symbol}"
            ) from exc
        action_type = None
        if split != 1 and dividend != 0:
            action_type = "SPLIT_AND_DIVIDEND"
        elif split != 1:
            action_type = "SPLIT"
        elif dividend != 0:
            action_type = "DIVIDEND"
        lineage = [
            {
                "source": "alpha_vantage",
                "provider_function": "TIME_SERIES_DAILY_ADJUSTED",
                "outputsize": "full",
                "symbol": symbol.strip().upper(),
            }
        ]
        return {
            "symbol": symbol.strip().upper(),
            "date": date,
            "adjusted_close": adjusted_close,
            "raw_close": raw_close,
            "currency": "USD",
            "available_at": f"{date.isoformat()}T22:00:00+00:00",
            "confidence": 1.0,
            "input_lineage": json.dumps(lineage, sort_keys=True),
            "price_basis": "ADJUSTED",
            "corporate_action_status": "APPLIED" if action_type else "NONE",
            "corporate_action_type": action_type,
            "adjustment_factor": adjusted_close / raw_close,
            "dividend_amount": dividend,
            "split_coefficient": split,
            "trading_calendar": "XNYS",
            "session_status": "PRESENT",
            "timing_policy": "EOD_CLOSE_T_PLUS_0",
        }

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
