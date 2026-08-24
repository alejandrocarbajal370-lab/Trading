from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash

CONFIDENCE_POLICY_VERSION = "conservative-input-min-v1"
CLASSIFICATION_CONTRACT_VERSION = "pit-classification-v1"
PEER_ASSIGNMENT_VERSION = "peer-assignment-v1"
STATUS_TAXONOMY_VERSION = "factor-status-taxonomy-v1"
APPLICABILITY_POLICY_VERSION = "sector-applicability-v1"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GovernedStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_CONFIDENCE = "MISSING_CONFIDENCE"
    MISSING = "MISSING"
    NOT_COMPUTED = "NOT_COMPUTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID_LINEAGE = "INVALID_LINEAGE"
    INVALID_DATA = "INVALID_DATA"
    INVALID_CURRENCY = "INVALID_CURRENCY"
    INVALID_UNIT = "INVALID_UNIT"
    INVALID_DENOMINATOR = "INVALID_DENOMINATOR"
    PIT_VIOLATION = "PIT_VIOLATION"
    STALE_PRICE = "STALE_PRICE"
    PERIOD_MISMATCH = "PERIOD_MISMATCH"
    INDUSTRY_RESTRICTED = "INDUSTRY_RESTRICTED"


def governed_status(value: object) -> GovernedStatus:
    try:
        return GovernedStatus(str(value))
    except ValueError as error:
        raise ValueError(
            f"unknown governed status under {STATUS_TAXONOMY_VERSION}: {value}"
        ) from error


class ConfidenceVector(ContractModel):
    data_confidence: float = Field(ge=0, le=1)
    calculation_confidence: float = Field(ge=0, le=1)
    economic_confidence: float = Field(ge=0, le=1)
    policy_version: Literal["conservative-input-min-v1"] = CONFIDENCE_POLICY_VERSION

    @property
    def governed_confidence(self) -> float:
        return min(self.data_confidence, self.calculation_confidence, self.economic_confidence)


def conservative_confidence(values: list[ConfidenceVector]) -> ConfidenceVector:
    if not values:
        raise ValueError("governed confidence is required; synthetic defaults are forbidden")
    return ConfidenceVector(
        data_confidence=min(item.data_confidence for item in values),
        calculation_confidence=min(item.calculation_confidence for item in values),
        economic_confidence=min(item.economic_confidence for item in values),
    )


class ClassificationRecord(ContractModel):
    symbol: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    source: str = Field(min_length=1)
    taxonomy: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    available_at: datetime.datetime
    contract_version: Literal["pit-classification-v1"] = CLASSIFICATION_CONTRACT_VERSION

    @model_validator(mode="after")
    def validate_timestamp(self) -> ClassificationRecord:
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("classification available_at must be timezone-aware")
        if self.taxonomy.upper() in {"UNKNOWN", "UNSPECIFIED"}:
            raise ValueError("unknown classification taxonomy")
        return self


def peer_assignment_hash(
    records: list[ClassificationRecord],
    *,
    as_of: datetime.datetime,
    universe_snapshot_hash: str,
) -> str:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("peer assignment as_of must be timezone-aware")
    if any(item.available_at > as_of for item in records):
        raise ValueError("classification is stale/future relative to as_of")
    symbols = [item.symbol.strip().upper() for item in records]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate classification symbol")
    mappings = sorted(
        (
            {
                "symbol": item.symbol.strip().upper(),
                "sector": item.sector,
                "industry": item.industry,
                "source": item.source,
                "taxonomy": item.taxonomy,
                "taxonomy_version": item.taxonomy_version,
                "available_at": item.available_at,
            }
            for item in records
        ),
        key=lambda item: item["symbol"],
    )
    return typed_hash(
        {
            "version": PEER_ASSIGNMENT_VERSION,
            "as_of": as_of,
            "universe_snapshot_hash": universe_snapshot_hash,
            "mappings": mappings,
        }
    )


class MetricApplicability(ContractModel):
    metric: str
    sector: str = "*"
    industry: str = "*"
    state: Literal["APPLICABLE", "NOT_APPLICABLE", "REVIEW"]
    reason: str


APPLICABILITY_MATRIX = (
    MetricApplicability(
        metric="enterprise_value_to_ebitda",
        sector="Financials",
        state="NOT_APPLICABLE",
        reason="EV and operating debt are not comparable for financial institutions",
    ),
    MetricApplicability(
        metric="ev_to_ebitda",
        sector="Financials",
        state="NOT_APPLICABLE",
        reason="EV and operating debt are not comparable for financial institutions",
    ),
    MetricApplicability(
        metric="ev_to_ebit",
        sector="Financials",
        state="NOT_APPLICABLE",
        reason="EV and operating debt are not comparable for financial institutions",
    ),
    MetricApplicability(
        metric="ebit_yield",
        sector="Financials",
        state="NOT_APPLICABLE",
        reason="EV and operating debt are not comparable for financial institutions",
    ),
    MetricApplicability(
        metric="net_debt_to_ebitda",
        sector="Financials",
        state="NOT_APPLICABLE",
        reason="debt is an operating input for banks and insurers",
    ),
    MetricApplicability(
        metric="cfo_conversion",
        industry="Banks",
        state="NOT_APPLICABLE",
        reason="CFO classification is not comparable for banks",
    ),
    MetricApplicability(
        metric="cfo_to_net_income",
        industry="Banks",
        state="NOT_APPLICABLE",
        reason="CFO classification is not comparable for banks",
    ),
    MetricApplicability(
        metric="cfo_conversion",
        industry="Insurance",
        state="NOT_APPLICABLE",
        reason="CFO classification is not comparable for insurers",
    ),
    MetricApplicability(
        metric="cfo_to_net_income",
        industry="Insurance",
        state="NOT_APPLICABLE",
        reason="CFO classification is not comparable for insurers",
    ),
    MetricApplicability(
        metric="net_debt_to_ebitda",
        industry="REITs",
        state="REVIEW",
        reason="FFO and property debt conventions require a REIT-specific contract",
    ),
    MetricApplicability(
        metric="cfo_conversion",
        industry="REITs",
        state="REVIEW",
        reason="FFO/AFFO is the economically relevant sector-specific basis",
    ),
)


def metric_applicability(
    metric: str, sector: str | None, industry: str | None
) -> MetricApplicability:
    matches = [
        item
        for item in APPLICABILITY_MATRIX
        if item.metric == metric
        and (item.sector == "*" or item.sector == sector)
        and (item.industry == "*" or item.industry == industry)
    ]
    if matches:
        return max(matches, key=lambda item: (item.industry != "*", item.sector != "*"))
    return MetricApplicability(metric=metric, state="APPLICABLE", reason="no sector restriction")
