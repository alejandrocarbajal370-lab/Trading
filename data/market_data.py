from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data.market_calendar import get_trading_calendar

MARKET_DATA_CONTRACT_VERSION = "market-data-governance-v1"
REQUIRED_COLUMNS = (
    "symbol",
    "date",
    "raw_close",
    "adjusted_close",
    "currency",
    "available_at",
    "corporate_action_status",
    "corporate_action_type",
    "adjustment_factor",
)


class MarketDataGovernanceError(ValueError):
    """Raised when market data cannot be admitted without unsafe assumptions."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LineageEntry(_ContractModel):
    source: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    transformation: str | None = None


class CorporateActionMetadata(_ContractModel):
    policy: Literal["PROVIDER_ADJUSTED_RECONCILED"] = "PROVIDER_ADJUSTED_RECONCILED"
    supported_types: tuple[str, ...] = ("SPLIT", "DIVIDEND", "SPLIT_AND_DIVIDEND")
    raw_close_preserved: Literal[True] = True


class MarketDataMetadata(_ContractModel):
    source: str = Field(min_length=1)
    available_at: datetime.datetime
    dataset_version: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_id: str = Field(pattern=r"^market-data:[0-9a-f]{64}$")
    lineage: tuple[LineageEntry, ...] = Field(min_length=1)
    trading_calendar: str
    price_basis: Literal["RAW_AND_ADJUSTED"] = "RAW_AND_ADJUSTED"
    corporate_actions: CorporateActionMetadata = CorporateActionMetadata()
    contract_version: Literal["market-data-governance-v1"] = MARKET_DATA_CONTRACT_VERSION

    @field_validator("available_at")
    @classmethod
    def timezone_required(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        return value


@runtime_checkable
class MarketDataProvider(Protocol):
    """Provider boundary: adapters return data plus auditable source metadata."""

    @property
    def name(self) -> str: ...

    @property
    def dataset_version(self) -> str: ...

    def fetch_market_data(
        self, *, symbols: set[str], as_of: datetime.datetime
    ) -> MarketDataDataset: ...


@dataclass(frozen=True)
class MarketDataDataset:
    """Validated PIT market-data snapshot with content-addressed identity."""

    frame: pd.DataFrame
    metadata: MarketDataMetadata

    def __post_init__(self) -> None:
        observed = canonical_market_data_checksum(self.frame)
        if observed != self.metadata.checksum:
            raise MarketDataGovernanceError(
                f"market-data checksum mismatch: expected {self.metadata.checksum}, observed {observed}"
            )
        if self.metadata.canonical_id != f"market-data:{observed}":
            raise MarketDataGovernanceError(
                "market-data canonical identity does not match checksum"
            )

    def momentum_frame(self) -> pd.DataFrame:
        """Return a defensive copy carrying the governed identity into Momentum."""
        result = self.frame.copy(deep=True)
        lineage = {
            "source": self.metadata.source,
            "dataset": "governed_market_data",
            "dataset_version": self.metadata.dataset_version,
            "canonical_id": self.metadata.canonical_id,
            "checksum": self.metadata.checksum,
            "contract_version": self.metadata.contract_version,
            "upstream": [item.model_dump(mode="json") for item in self.metadata.lineage],
        }
        result["input_lineage"] = json.dumps([lineage], sort_keys=True)
        result["price_basis"] = "ADJUSTED"
        result["trading_calendar"] = self.metadata.trading_calendar
        result["session_status"] = "PRESENT"
        result["timing_policy"] = "EOD_CLOSE_T_PLUS_0"
        result["historical_provider"] = self.metadata.source
        result["historical_dataset"] = "governed_market_data"
        result["historical_dataset_version"] = self.metadata.dataset_version
        result["historical_access_tier"] = "governed"
        if "confidence" not in result:
            result["confidence"] = 1.0
        return result


def canonical_market_data_checksum(frame: pd.DataFrame) -> str:
    """Hash semantic content, independent of input row order or dataframe index."""
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise MarketDataGovernanceError(
            f"market data missing required columns: {', '.join(missing)}"
        )
    ordered_columns = [*REQUIRED_COLUMNS, *sorted(set(frame.columns) - set(REQUIRED_COLUMNS))]
    canonical = frame.loc[:, ordered_columns].copy()
    canonical["symbol"] = canonical["symbol"].astype(str).str.strip().str.upper()
    canonical["date"] = pd.to_datetime(canonical["date"], errors="raise").dt.date.astype(str)
    available = pd.to_datetime(canonical["available_at"], errors="raise", utc=True)
    canonical["available_at"] = available.map(lambda value: value.isoformat())
    for column in ("raw_close", "adjusted_close", "adjustment_factor"):
        canonical[column] = pd.to_numeric(canonical[column], errors="raise").map(
            lambda value: format(float(value), ".17g")
        )
    for column in set(canonical.columns) - set(REQUIRED_COLUMNS):
        canonical[column] = canonical[column].map(
            lambda value: "" if pd.isna(value) else str(value)
        )
    canonical = canonical.fillna("").sort_values(["symbol", "date"], kind="stable")
    payload = canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def govern_market_data(
    frame: pd.DataFrame,
    *,
    source: str,
    dataset_version: str,
    available_at: datetime.datetime,
    lineage: tuple[LineageEntry, ...],
    trading_calendar: str,
    as_of: datetime.datetime,
    maximum_staleness_sessions: int = 1,
) -> MarketDataDataset:
    """Validate and content-address a snapshot; every ambiguity fails closed."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise MarketDataGovernanceError("as_of must be timezone-aware")
    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise MarketDataGovernanceError("available_at must be timezone-aware")
    if available_at > as_of:
        raise MarketDataGovernanceError("PIT violation: dataset available_at exceeds as_of")
    if maximum_staleness_sessions < 0:
        raise MarketDataGovernanceError("maximum_staleness_sessions must be non-negative")

    data = frame.copy(deep=True)
    missing = sorted(set(REQUIRED_COLUMNS) - set(data.columns))
    if missing:
        raise MarketDataGovernanceError(
            f"market data missing required columns: {', '.join(missing)}"
        )
    data["symbol"] = data["symbol"].astype(str).str.strip().str.upper()
    if data.empty or (data["symbol"] == "").any():
        raise MarketDataGovernanceError("market data requires non-empty symbols and rows")
    try:
        data["date"] = pd.to_datetime(data["date"], errors="raise").dt.date
        timestamps = pd.to_datetime(data["available_at"], errors="raise", utc=True)
        data["raw_close"] = pd.to_numeric(data["raw_close"], errors="raise")
        data["adjusted_close"] = pd.to_numeric(data["adjusted_close"], errors="raise")
        data["adjustment_factor"] = pd.to_numeric(data["adjustment_factor"], errors="raise")
    except (TypeError, ValueError) as error:
        raise MarketDataGovernanceError(f"invalid market-data value: {error}") from error
    if data.duplicated(["symbol", "date"]).any():
        raise MarketDataGovernanceError("duplicate symbol/session observations")
    if any(timestamp.to_pydatetime() > as_of.astimezone(datetime.UTC) for timestamp in timestamps):
        raise MarketDataGovernanceError("PIT violation: row available_at exceeds as_of")
    if any(
        timestamp.to_pydatetime() > available_at.astimezone(datetime.UTC)
        for timestamp in timestamps
    ):
        raise MarketDataGovernanceError(
            "PIT violation: row available_at exceeds dataset availability"
        )
    if (data["date"] > as_of.date()).any():
        raise MarketDataGovernanceError("PIT violation: price date exceeds as_of")
    for column in ("raw_close", "adjusted_close", "adjustment_factor"):
        if (~np.isfinite(data[column])).any() or (data[column] <= 0).any():
            raise MarketDataGovernanceError(f"{column} must contain finite positive values")
    observed_factor = data["adjusted_close"] / data["raw_close"]
    if not np.allclose(observed_factor, data["adjustment_factor"], rtol=1e-10, atol=1e-12):
        raise MarketDataGovernanceError("raw and adjusted close do not reconcile")

    statuses = set(data["corporate_action_status"].astype(str))
    if statuses - {"NONE", "APPLIED"}:
        raise MarketDataGovernanceError("invalid corporate_action_status")
    applied = data["corporate_action_status"].astype(str) == "APPLIED"
    allowed_types = {"SPLIT", "DIVIDEND", "SPLIT_AND_DIVIDEND"}
    types = set(data.loc[applied, "corporate_action_type"].dropna().astype(str))
    if applied.any() and (not types or types - allowed_types):
        raise MarketDataGovernanceError("applied corporate actions require a supported type")
    if data.loc[~applied, "corporate_action_type"].notna().any():
        raise MarketDataGovernanceError("corporate action type present when status is NONE")

    calendar = get_trading_calendar(trading_calendar)
    for symbol, group in data.groupby("symbol", sort=True):
        observed = set(group["date"])
        expected = set(calendar.sessions(min(observed), max(observed)))
        if missing_sessions := sorted(expected - observed):
            preview = ", ".join(day.isoformat() for day in missing_sessions[:3])
            raise MarketDataGovernanceError(f"{symbol} has missing market sessions: {preview}")
        if unexpected := sorted(observed - expected):
            preview = ", ".join(day.isoformat() for day in unexpected[:3])
            raise MarketDataGovernanceError(f"{symbol} has non-session observations: {preview}")
        sessions_to_as_of = calendar.sessions(max(observed), as_of.date())
        stale_sessions = max(0, len(sessions_to_as_of) - 1)
        if stale_sessions > maximum_staleness_sessions:
            raise MarketDataGovernanceError(
                f"{symbol} is stale by {stale_sessions} market sessions"
            )

    data["available_at"] = timestamps.map(lambda value: value.isoformat())
    data = data.sort_values(["symbol", "date"], kind="stable").reset_index(drop=True)
    checksum = canonical_market_data_checksum(data)
    metadata = MarketDataMetadata(
        source=source,
        available_at=available_at,
        dataset_version=dataset_version,
        checksum=checksum,
        canonical_id=f"market-data:{checksum}",
        lineage=lineage,
        trading_calendar=trading_calendar,
    )
    return MarketDataDataset(frame=data, metadata=metadata)
