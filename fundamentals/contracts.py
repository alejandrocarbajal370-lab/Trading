from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import pandas as pd

PeriodKind = Literal["quarterly", "fy", "ytd", "ttm", "instant"]


@dataclass(frozen=True)
class SectorBenchmark:
    """PIT sector observation; intentionally contains no rank or investment score."""

    sector_id: str
    metric: str
    value: float
    as_of: pd.Timestamp
    available_at: pd.Timestamp
    population: int
    source: str


class SectorContextSource(Protocol):
    def fetch(
        self, *, sector_id: str, metric: str, available_at: pd.Timestamp
    ) -> list[SectorBenchmark]: ...


@dataclass(frozen=True)
class CapitalAllocationRecord:
    """Reported management action; interpretation/scoring is deliberately deferred."""

    symbol: str
    action: Literal[
        "dividend", "buyback", "debt_issuance", "debt_repayment", "acquisition", "divestiture"
    ]
    amount: float | None
    currency: str | None
    effective_at: pd.Timestamp
    available_at: pd.Timestamp
    source: str
    source_reference: str
    metadata: dict[str, object] = field(default_factory=dict)
