from __future__ import annotations

import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FinancialConfidence(ContractModel):
    score: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()
    lineage: tuple[str, ...] = ()


class MetricObservation(ContractModel):
    value: float
    as_of: datetime.date
    available_at: datetime.datetime
    source: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    period_kind: Literal["quarterly", "fy", "ytd", "ttm", "instant", "ratio"]
    status: Literal["PASS", "WARNING", "LOW_CONFIDENCE"] = "PASS"
    reason: str | None = None
    confidence: float = Field(ge=0, le=1)
    lineage: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_timezone(self) -> Self:
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        return self


class QualityFactorInputs(ContractModel):
    symbol: str
    as_of: datetime.date
    roic: MetricObservation
    roic_history: tuple[MetricObservation, ...]
    fcf_margin: MetricObservation
    cfo_conversion: MetricObservation
    stability: MetricObservation
    leverage: MetricObservation
    financial_confidence: FinancialConfidence


class ValueFactorInputs(ContractModel):
    symbol: str
    as_of: datetime.date
    market_cap: MetricObservation
    enterprise_value: MetricObservation
    fcf_ttm: MetricObservation
    ebitda_ttm: MetricObservation
    earnings_ttm: MetricObservation

    @model_validator(mode="after")
    def validate_valuation_compatibility(self) -> Self:
        monetary = (
            self.market_cap,
            self.enterprise_value,
            self.fcf_ttm,
            self.ebitda_ttm,
            self.earnings_ttm,
        )
        units = {item.unit for item in monetary}
        if len(units) != 1:
            raise ValueError("Value inputs must use one compatible currency/unit")
        for item in (self.fcf_ttm, self.ebitda_ttm, self.earnings_ttm):
            if item.period_kind != "ttm":
                raise ValueError("Value flow inputs must be TTM")
        if (
            self.market_cap.period_kind != "instant"
            or self.enterprise_value.period_kind != "instant"
        ):
            raise ValueError("Value market-cap and enterprise-value inputs must be instant")
        cutoff = datetime.datetime.combine(self.as_of, datetime.time.max, tzinfo=datetime.UTC)
        if any(item.available_at.astimezone(datetime.UTC) > cutoff for item in monetary):
            raise ValueError("Value inputs cannot be available after as_of")
        return self


class PriceObservation(ContractModel):
    date: datetime.date
    adjusted_close: float = Field(gt=0)
    volume: float = Field(ge=0)
    available_at: datetime.datetime
    source: str


class EarningsRevisionMetadata(ContractModel):
    """Reserved provider metadata only; no revision signal is calculated."""

    provider: str | None = None
    available_at: datetime.datetime | None = None
    raw_reference: str | None = None


class MomentumFactorInputs(ContractModel):
    symbol: str
    as_of: datetime.date
    price_history: tuple[PriceObservation, ...]
    returns: tuple[MetricObservation, ...]
    volume: tuple[MetricObservation, ...]
    earnings_revision_metadata: EarningsRevisionMetadata
