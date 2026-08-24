from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

ACCOUNTING_CONTRACT_VERSION = "accounting-pit-governance-v1"
ACCOUNTING_PERIOD_ADAPTER_VERSION = "accounting-period-semantics-v1"
ACCOUNTING_REQUIRED_COLUMNS = (
    "fact_id",
    "entity",
    "metric",
    "fiscal_period",
    "period_end",
    "filing_date",
    "available_at",
    "value",
    "unit",
    "source",
    "dataset_version",
    "revision",
    "revision_type",
    "supersedes_revision",
)
ECONOMIC_FACT_KEY = ("entity", "metric", "fiscal_period", "period_end")
RESTATEMENT_INVARIANTS = (*ECONOMIC_FACT_KEY, "unit")


class AccountingGovernanceError(ValueError):
    """Raised when a fundamental fact cannot be admitted without an unsafe assumption."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountingLineageEntry(_ContractModel):
    source: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    transformation: str | None = None


class FinancialFact(_ContractModel):
    """Typed accounting observation, including its publication and revision identity."""

    fact_id: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    fiscal_period: str = Field(min_length=1)
    period_end: datetime.date
    filing_date: datetime.datetime
    available_at: datetime.datetime
    value: float
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    revision: int = Field(ge=0)
    revision_type: Literal["ORIGINAL", "RESTATEMENT"]
    supersedes_revision: int | None = Field(default=None, ge=0)

    @field_validator("filing_date", "available_at")
    @classmethod
    def timezone_required(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("accounting timestamps must be timezone-aware")
        return value


class MissingFundamentalsPolicy(_ContractModel):
    version: Literal["missing-fundamentals-v1"] = "missing-fundamentals-v1"
    action: Literal["FAIL", "ALLOW"] = "FAIL"


class AccountingMetadata(_ContractModel):
    source: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    available_at: datetime.datetime
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_id: str = Field(pattern=r"^accounting:[0-9a-f]{64}$")
    lineage: tuple[AccountingLineageEntry, ...] = Field(min_length=1)
    missing_policy: MissingFundamentalsPolicy
    contract_version: Literal["accounting-pit-governance-v1"] = ACCOUNTING_CONTRACT_VERSION

    @field_validator("available_at")
    @classmethod
    def timezone_required(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        return value


@runtime_checkable
class AccountingProvider(Protocol):
    """Provider boundary for governed, revision-aware fundamental history."""

    @property
    def name(self) -> str: ...

    @property
    def dataset_version(self) -> str: ...

    def fetch_accounting(
        self, *, entities: set[str], as_of: datetime.datetime
    ) -> AccountingDataset: ...


@dataclass(frozen=True)
class AccountingDataset:
    """Immutable-by-contract accounting history with content-addressed identity."""

    frame: pd.DataFrame
    metadata: AccountingMetadata

    def __post_init__(self) -> None:
        observed = canonical_accounting_checksum(self.frame)
        if observed != self.metadata.checksum:
            raise AccountingGovernanceError(
                f"accounting checksum mismatch: expected {self.metadata.checksum}, "
                f"observed {observed}"
            )
        if self.metadata.canonical_id != f"accounting:{observed}":
            raise AccountingGovernanceError(
                "accounting canonical identity does not match checksum"
            )

    def snapshot(
        self,
        *,
        cutoff: datetime.datetime,
        required: set[tuple[str, str]] | None = None,
    ) -> pd.DataFrame:
        """Return only the last revision known at cutoff for each economic fact."""
        _require_aware("cutoff", cutoff)
        cutoff_utc = pd.Timestamp(cutoff).tz_convert("UTC")
        # PIT selection is driven by when information became known, not by the
        # provider's revision counter or the incoming row order.
        eligible = self.frame.loc[self.frame["available_at"] <= cutoff_utc].copy()
        eligible = eligible.sort_values(
            [*ECONOMIC_FACT_KEY, "available_at", "revision"], kind="stable"
        )
        snapshot = eligible.drop_duplicates(list(ECONOMIC_FACT_KEY), keep="last").reset_index(
            drop=True
        )
        if (snapshot["available_at"] > cutoff_utc).any():
            raise AccountingGovernanceError(
                "PIT violation: accounting snapshot includes future information"
            )
        if required:
            observed = set(zip(snapshot["entity"], snapshot["metric"], strict=False))
            missing = sorted(required - observed)
            if missing and self.metadata.missing_policy.action == "FAIL":
                labels = ", ".join(f"{entity}/{metric}" for entity, metric in missing)
                raise AccountingGovernanceError(f"missing fundamentals under policy: {labels}")
        return snapshot


def _require_aware(name: str, value: datetime.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AccountingGovernanceError(f"{name} must be timezone-aware")


def _canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(ACCOUNTING_REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise AccountingGovernanceError(
            f"accounting data missing required columns: {', '.join(missing)}"
        )
    extra = sorted(set(frame.columns) - set(ACCOUNTING_REQUIRED_COLUMNS))
    canonical = frame.loc[:, [*ACCOUNTING_REQUIRED_COLUMNS, *extra]].copy()
    for column in (
        "fact_id",
        "entity",
        "metric",
        "fiscal_period",
        "unit",
        "source",
        "dataset_version",
        "revision_type",
    ):
        canonical[column] = canonical[column].astype(str).str.strip()
    canonical["entity"] = canonical["entity"].str.upper()
    canonical["unit"] = canonical["unit"].str.upper()
    canonical["revision_type"] = canonical["revision_type"].str.upper()
    canonical["period_end"] = pd.to_datetime(
        canonical["period_end"], errors="raise"
    ).dt.date.astype(str)
    for column in ("filing_date", "available_at"):
        values = pd.to_datetime(canonical[column], errors="raise", utc=True)
        canonical[column] = values.map(lambda value: value.isoformat())
    canonical["value"] = pd.to_numeric(canonical["value"], errors="raise").map(
        lambda value: format(float(value), ".17g")
    )
    canonical["revision"] = pd.to_numeric(
        canonical["revision"], errors="raise", downcast="integer"
    ).astype(str)
    canonical["supersedes_revision"] = canonical["supersedes_revision"].map(
        lambda value: "" if pd.isna(value) else str(int(value))
    )
    for column in extra:
        canonical[column] = canonical[column].map(
            lambda value: "" if pd.isna(value) else str(value)
        )
    return canonical.fillna("").sort_values(
        [*ECONOMIC_FACT_KEY, "revision", "available_at"], kind="stable"
    )


def canonical_accounting_checksum(frame: pd.DataFrame) -> str:
    """Hash semantic accounting history independently of row order and index."""
    payload = _canonical_frame(frame).to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_revisions(data: pd.DataFrame) -> None:
    invariants = RESTATEMENT_INVARIANTS
    if {"fiscal_period_start", "period_type"} <= set(data.columns):
        invariants = (*invariants, "fiscal_period_start", "period_type")
    for key, revisions in data.groupby(list(ECONOMIC_FACT_KEY), dropna=False, sort=False):
        ordered = revisions.sort_values("revision", kind="stable")
        fact_ids = set(ordered["fact_id"])
        if len(fact_ids) != 1:
            raise AccountingGovernanceError(f"revision mismatch: fact_id changed for {key}")
        expected = list(range(len(ordered)))
        if ordered["revision"].tolist() != expected:
            raise AccountingGovernanceError(f"revision mismatch: non-contiguous history for {key}")
        first = ordered.iloc[0]
        if first["revision_type"] != "ORIGINAL" or pd.notna(first["supersedes_revision"]):
            raise AccountingGovernanceError(f"revision mismatch: invalid original for {key}")
        for previous, current in zip(
            ordered.itertuples(index=False), ordered.iloc[1:].itertuples(index=False), strict=False
        ):
            invariants_changed = any(
                getattr(current, field) != getattr(previous, field)
                for field in invariants
            )
            if (
                current.revision_type != "RESTATEMENT"
                or current.supersedes_revision != previous.revision
                or current.available_at <= previous.available_at
                or current.filing_date < previous.filing_date
                or invariants_changed
            ):
                raise AccountingGovernanceError(
                    f"revision mismatch: invalid restatement chain for {key}"
                )


def govern_accounting(
    frame: pd.DataFrame,
    *,
    source: str,
    dataset_version: str,
    available_at: datetime.datetime,
    lineage: tuple[AccountingLineageEntry, ...],
    as_of: datetime.datetime,
    missing_policy: MissingFundamentalsPolicy | None = None,
) -> AccountingDataset:
    """Validate complete revision history and fail closed on any PIT ambiguity."""
    _require_aware("as_of", as_of)
    _require_aware("available_at", available_at)
    if available_at > as_of:
        raise AccountingGovernanceError("PIT violation: dataset available_at exceeds as_of")
    data = frame.copy(deep=True)
    missing = sorted(set(ACCOUNTING_REQUIRED_COLUMNS) - set(data.columns))
    if missing:
        raise AccountingGovernanceError(
            f"accounting data missing required columns: {', '.join(missing)}"
        )
    if data.empty:
        raise AccountingGovernanceError("missing fundamentals: accounting dataset is empty")
    period_columns = {"fiscal_period_start", "period_type"}
    supplied_period_columns = period_columns & set(data.columns)
    if supplied_period_columns and supplied_period_columns != period_columns:
        raise AccountingGovernanceError(
            "accounting period contract requires fiscal_period_start and period_type together"
        )
    try:
        for column in (
            "fact_id",
            "entity",
            "metric",
            "fiscal_period",
            "unit",
            "source",
            "dataset_version",
            "revision_type",
        ):
            data[column] = data[column].astype("string").str.strip()
        data["entity"] = data["entity"].str.upper()
        data["unit"] = data["unit"].str.upper()
        data["revision_type"] = data["revision_type"].str.upper()
        data["period_end"] = pd.to_datetime(data["period_end"], errors="raise").dt.date
        data["filing_date"] = pd.to_datetime(data["filing_date"], errors="raise", utc=True)
        data["available_at"] = pd.to_datetime(data["available_at"], errors="raise", utc=True)
        data["value"] = pd.to_numeric(data["value"], errors="raise")
        data["revision"] = pd.to_numeric(data["revision"], errors="raise").astype(int)
        data["supersedes_revision"] = pd.to_numeric(
            data["supersedes_revision"], errors="coerce"
        ).astype("Int64")
        if supplied_period_columns:
            data["period_type"] = data["period_type"].astype("string").str.strip().str.lower()
            starts = pd.to_datetime(data["fiscal_period_start"], errors="coerce").dt.date
            duration = data["period_type"] == "duration"
            instant = data["period_type"] == "instant"
            if (~(duration | instant)).any():
                raise AccountingGovernanceError("invalid accounting period_type")
            if starts.loc[duration].isna().any() or starts.loc[instant].notna().any():
                raise AccountingGovernanceError(
                    "duration facts require fiscal_period_start and instant facts forbid it"
                )
            if (starts.loc[duration] > data.loc[duration, "period_end"]).any():
                raise AccountingGovernanceError("fiscal_period_start must not exceed period_end")
            data["fiscal_period_start"] = starts
    except (TypeError, ValueError, OverflowError) as error:
        raise AccountingGovernanceError(f"invalid accounting value: {error}") from error
    text_columns = [
        "fact_id",
        "entity",
        "metric",
        "fiscal_period",
        "unit",
        "source",
        "dataset_version",
        "revision_type",
    ]
    if data[text_columns].isna().any().any() or data[text_columns].eq("").any().any():
        raise AccountingGovernanceError("missing fundamentals: required text field is blank")
    if (~np.isfinite(data["value"])).any():
        raise AccountingGovernanceError("fundamental values must be finite")
    if (data["revision"] < 0).any():
        raise AccountingGovernanceError("revision mismatch: revision must be non-negative")
    if set(data["revision_type"]) - {"ORIGINAL", "RESTATEMENT"}:
        raise AccountingGovernanceError("revision mismatch: invalid revision_type")
    if data.duplicated([*ECONOMIC_FACT_KEY, "revision"]).any():
        raise AccountingGovernanceError("duplicate facts: repeated economic fact revision")
    if data.duplicated(["fact_id", "revision"]).any():
        raise AccountingGovernanceError("duplicate facts: repeated fact_id revision")

    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    dataset_available = pd.Timestamp(available_at).tz_convert("UTC")
    period_end = pd.to_datetime(data["period_end"], utc=True)
    if (period_end > data["filing_date"]).any():
        raise AccountingGovernanceError("invalid accounting chronology: filing precedes period_end")
    if (data["filing_date"] > cutoff).any():
        raise AccountingGovernanceError("PIT violation: filing_date exceeds cutoff")
    if (data["available_at"] > cutoff).any():
        raise AccountingGovernanceError("PIT violation: available_at exceeds cutoff")
    if (data["available_at"] > dataset_available).any():
        raise AccountingGovernanceError(
            "PIT violation: row available_at exceeds dataset availability"
        )
    if (data["available_at"] < data["filing_date"]).any():
        raise AccountingGovernanceError(
            "invalid accounting chronology: available_at precedes filing_date"
        )
    if (data["source"] != source).any() or (data["dataset_version"] != dataset_version).any():
        raise AccountingGovernanceError("provider/source contract mismatch")
    _validate_revisions(data)

    data = data.sort_values(
        [*ECONOMIC_FACT_KEY, "revision", "available_at"], kind="stable"
    ).reset_index(drop=True)
    checksum = canonical_accounting_checksum(data)
    metadata = AccountingMetadata(
        source=source,
        dataset_version=dataset_version,
        available_at=available_at,
        checksum=checksum,
        canonical_id=f"accounting:{checksum}",
        lineage=lineage,
        missing_policy=missing_policy or MissingFundamentalsPolicy(),
    )
    return AccountingDataset(frame=data, metadata=metadata)
