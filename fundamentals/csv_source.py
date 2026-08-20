from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from fundamentals.source import FundamentalSourceResponseError

REQUIRED_COLUMNS = (
    "symbol",
    "fiscal_period_end",
    "filed_at",
    "available_at",
    "metric",
    "value",
    "source",
)


@dataclass(frozen=True)
class CsvFundamentalSource:
    path: Path

    @property
    def name(self) -> str:
        return "csv_fundamentals"

    def fetch(self, *, symbols: set[str]) -> pd.DataFrame:
        try:
            frame = pd.read_csv(self.path)
        except (OSError, pd.errors.ParserError) as exc:
            raise FundamentalSourceResponseError(f"could not read fundamental source: {exc}") from exc

        missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
        if missing:
            raise FundamentalSourceResponseError(f"missing required fields: {', '.join(missing)}")
        result = frame.loc[:, REQUIRED_COLUMNS].copy()
        result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
        result["metric"] = result["metric"].astype(str).str.strip()
        result["source"] = result["source"].astype(str).str.strip()
        result = result[result["symbol"].isin({symbol.upper() for symbol in symbols})]
        try:
            result["fiscal_period_end"] = pd.to_datetime(
                result["fiscal_period_end"], format="%Y-%m-%d", errors="raise"
            ).dt.date
            for column in ("filed_at", "available_at"):
                result[column] = pd.to_datetime(result[column], utc=True, errors="raise")
            result["value"] = pd.to_numeric(result["value"], errors="raise")
        except (ValueError, TypeError) as exc:
            raise FundamentalSourceResponseError(f"invalid fundamental field: {exc}") from exc

        blank = (
            result["symbol"].eq("") | result["metric"].eq("") | result["source"].eq("")
        )
        if result.empty or blank.any() or result.isna().any().any():
            raise FundamentalSourceResponseError("fundamental records contain missing fields")
        if (result["available_at"] < result["filed_at"]).any():
            raise FundamentalSourceResponseError("available_at cannot precede filed_at")
        return result.reset_index(drop=True)
