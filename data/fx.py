from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

FX_CONTRACT_VERSION = "fx-governance-v1"
FX_REQUIRED_COLUMNS = (
    "currency_pair",
    "base_currency",
    "quote_currency",
    "market_timestamp",
    "available_at",
    "rate",
)


class FXGovernanceError(ValueError):
    """Raised when FX data cannot be used without an unsafe assumption."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FXLineageEntry(_ContractModel):
    source: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    transformation: str | None = None


class FXMetadata(_ContractModel):
    source: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    available_at: datetime.datetime
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_id: str = Field(pattern=r"^fx:[0-9a-f]{64}$")
    lineage: tuple[FXLineageEntry, ...] = Field(min_length=1)
    contract_version: str = Field(default=FX_CONTRACT_VERSION, pattern=r"^fx-governance-v1$")

    @field_validator("available_at")
    @classmethod
    def timezone_required(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        return value


@runtime_checkable
class FXProvider(Protocol):
    """Provider boundary implemented by Bloomberg, AlphaVantage, or other adapters."""

    @property
    def name(self) -> str: ...

    @property
    def dataset_version(self) -> str: ...

    def fetch_fx(
        self, *, currency_pairs: set[str], as_of: datetime.datetime
    ) -> FXDataset: ...


@dataclass(frozen=True)
class FXConversion:
    amount: float
    source_currency: str
    target_currency: str
    converted_amount: float
    rate: float
    rate_market_timestamp: datetime.datetime
    rate_available_at: datetime.datetime
    fx_canonical_id: str
    fx_checksum: str
    fx_source: str
    fx_dataset_version: str


@dataclass(frozen=True)
class FXDataset:
    """Validated PIT FX observations with content-addressed identity."""

    frame: pd.DataFrame
    metadata: FXMetadata

    def __post_init__(self) -> None:
        observed = canonical_fx_checksum(self.frame)
        if observed != self.metadata.checksum:
            raise FXGovernanceError(
                f"FX checksum mismatch: expected {self.metadata.checksum}, observed {observed}"
            )
        if self.metadata.canonical_id != f"fx:{observed}":
            raise FXGovernanceError("FX canonical identity does not match checksum")

    def convert(
        self,
        amount: float,
        *,
        source_currency: str,
        target_currency: str,
        market_at: datetime.datetime,
        cutoff: datetime.datetime,
    ) -> FXConversion:
        """Convert historically using only observations known by the PIT cutoff."""
        _require_aware("market_at", market_at)
        _require_aware("cutoff", cutoff)
        if not np.isfinite(amount):
            raise FXGovernanceError("amount must be finite")
        source = _currency(source_currency)
        target = _currency(target_currency)
        if source == target:
            return FXConversion(
                amount=float(amount),
                source_currency=source,
                target_currency=target,
                converted_amount=float(amount),
                rate=1.0,
                rate_market_timestamp=market_at,
                rate_available_at=cutoff,
                fx_canonical_id=self.metadata.canonical_id,
                fx_checksum=self.metadata.checksum,
                fx_source=self.metadata.source,
                fx_dataset_version=self.metadata.dataset_version,
            )

        market_utc = pd.Timestamp(market_at).tz_convert("UTC")
        cutoff_utc = pd.Timestamp(cutoff).tz_convert("UTC")
        rows = self.frame.loc[
            (self.frame["market_timestamp"] <= market_utc)
            & (self.frame["available_at"] <= cutoff_utc)
        ]
        direct = rows.loc[
            (rows["base_currency"] == source) & (rows["quote_currency"] == target)
        ]
        inverse = rows.loc[
            (rows["base_currency"] == target) & (rows["quote_currency"] == source)
        ]
        if not direct.empty:
            observation = direct.sort_values(
                ["market_timestamp", "available_at"], kind="stable"
            ).iloc[-1]
            rate = float(observation["rate"])
        elif not inverse.empty:
            observation = inverse.sort_values(
                ["market_timestamp", "available_at"], kind="stable"
            ).iloc[-1]
            rate = 1.0 / float(observation["rate"])
        else:
            raise FXGovernanceError(
                f"no PIT-safe FX rate for {source}/{target} at market_at and cutoff"
            )
        return FXConversion(
            amount=float(amount),
            source_currency=source,
            target_currency=target,
            converted_amount=float(amount) * rate,
            rate=rate,
            rate_market_timestamp=observation["market_timestamp"].to_pydatetime(),
            rate_available_at=observation["available_at"].to_pydatetime(),
            fx_canonical_id=self.metadata.canonical_id,
            fx_checksum=self.metadata.checksum,
            fx_source=self.metadata.source,
            fx_dataset_version=self.metadata.dataset_version,
        )


def _require_aware(name: str, value: datetime.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FXGovernanceError(f"{name} must be timezone-aware")


def _currency(value: object) -> str:
    if value is None or pd.isna(value):
        raise FXGovernanceError("currency is missing")
    currency = str(value).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise FXGovernanceError(f"invalid currency: {value!r}")
    return currency


def canonical_fx_checksum(frame: pd.DataFrame) -> str:
    """Hash semantic FX content independently of row order and dataframe index."""
    missing = sorted(set(FX_REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise FXGovernanceError(f"FX data missing required columns: {', '.join(missing)}")
    extra = sorted(set(frame.columns) - set(FX_REQUIRED_COLUMNS))
    canonical = frame.loc[:, [*FX_REQUIRED_COLUMNS, *extra]].copy()
    for column in ("base_currency", "quote_currency"):
        canonical[column] = canonical[column].map(_currency)
    canonical["currency_pair"] = canonical["currency_pair"].astype(str).str.strip().str.upper()
    for column in ("market_timestamp", "available_at"):
        timestamps = pd.to_datetime(canonical[column], errors="raise", utc=True)
        canonical[column] = timestamps.map(lambda value: value.isoformat())
    canonical["rate"] = pd.to_numeric(canonical["rate"], errors="raise").map(
        lambda value: format(float(value), ".17g")
    )
    for column in extra:
        canonical[column] = canonical[column].map(
            lambda value: "" if pd.isna(value) else str(value)
        )
    canonical = canonical.fillna("").sort_values(
        ["currency_pair", "market_timestamp", "available_at"], kind="stable"
    )
    return hashlib.sha256(
        canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()


def govern_fx(
    frame: pd.DataFrame,
    *,
    source: str,
    dataset_version: str,
    available_at: datetime.datetime,
    lineage: tuple[FXLineageEntry, ...],
    as_of: datetime.datetime,
    maximum_staleness: datetime.timedelta,
) -> FXDataset:
    """Validate and content-address an FX snapshot; ambiguity always fails closed."""
    _require_aware("as_of", as_of)
    _require_aware("available_at", available_at)
    if available_at > as_of:
        raise FXGovernanceError("PIT violation: dataset available_at exceeds as_of")
    if maximum_staleness < datetime.timedelta(0):
        raise FXGovernanceError("maximum_staleness must be non-negative")

    data = frame.copy(deep=True)
    missing = sorted(set(FX_REQUIRED_COLUMNS) - set(data.columns))
    if missing:
        raise FXGovernanceError(f"FX data missing required columns: {', '.join(missing)}")
    if data.empty:
        raise FXGovernanceError("FX data requires at least one observation")
    try:
        data["base_currency"] = data["base_currency"].map(_currency)
        data["quote_currency"] = data["quote_currency"].map(_currency)
        data["currency_pair"] = data["currency_pair"].astype(str).str.strip().str.upper()
        data["market_timestamp"] = pd.to_datetime(
            data["market_timestamp"], errors="raise", utc=True
        )
        data["available_at"] = pd.to_datetime(data["available_at"], errors="raise", utc=True)
        data["rate"] = pd.to_numeric(data["rate"], errors="raise")
    except (TypeError, ValueError, OverflowError) as error:
        raise FXGovernanceError(f"invalid FX value: {error}") from error

    expected_pairs = data["base_currency"] + "/" + data["quote_currency"]
    if (data["base_currency"] == data["quote_currency"]).any() or not data[
        "currency_pair"
    ].equals(expected_pairs):
        raise FXGovernanceError("invalid currency pair")
    if (~np.isfinite(data["rate"])).any() or (data["rate"] <= 0).any():
        raise FXGovernanceError("FX rates must be finite and positive")
    if data.duplicated(["currency_pair", "market_timestamp", "available_at"]).any():
        raise FXGovernanceError("duplicate FX observations")

    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    dataset_available = pd.Timestamp(available_at).tz_convert("UTC")
    if (data["market_timestamp"] > cutoff).any():
        raise FXGovernanceError("PIT violation: FX market timestamp exceeds as_of")
    if (data["available_at"] > cutoff).any():
        raise FXGovernanceError("PIT violation: FX available_at exceeds as_of")
    if (data["available_at"] > dataset_available).any():
        raise FXGovernanceError("PIT violation: row available_at exceeds dataset availability")
    if (data["available_at"] < data["market_timestamp"]).any():
        raise FXGovernanceError("invalid FX chronology: available_at precedes market timestamp")
    latest_by_pair = data.groupby("currency_pair")["market_timestamp"].max()
    stale = latest_by_pair.loc[cutoff - latest_by_pair > maximum_staleness]
    if not stale.empty:
        raise FXGovernanceError(f"stale FX data for: {', '.join(stale.index)}")

    data = data.sort_values(
        ["currency_pair", "market_timestamp", "available_at"], kind="stable"
    ).reset_index(drop=True)
    checksum = canonical_fx_checksum(data)
    metadata = FXMetadata(
        source=source,
        dataset_version=dataset_version,
        available_at=available_at,
        checksum=checksum,
        canonical_id=f"fx:{checksum}",
        lineage=lineage,
    )
    return FXDataset(frame=data, metadata=metadata)
