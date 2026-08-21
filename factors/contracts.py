from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    source: str


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
