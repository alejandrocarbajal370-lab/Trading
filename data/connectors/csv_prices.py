from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class CsvPriceSource:
    """Deterministic Phase 0 price source backed by a local CSV snapshot."""

    path: Path

    def fetch(self) -> pd.DataFrame:
        frame = pd.read_csv(self.path)
        missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
        if missing:
            raise ValueError(f"price source is missing required columns: {', '.join(missing)}")

        result = frame.loc[:, REQUIRED_COLUMNS].copy()
        result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.date
        for column in ("open", "high", "low", "close", "volume"):
            result[column] = pd.to_numeric(result[column], errors="coerce")
        return result.sort_values(["date", "symbol"], ignore_index=True)
