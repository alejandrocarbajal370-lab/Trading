import datetime

import pytest
from pydantic import ValidationError

from factors.contracts import (
    EarningsRevisionMetadata,
    FinancialConfidence,
    MetricObservation,
    MomentumFactorInputs,
    PriceObservation,
    QualityFactorInputs,
    ValueFactorInputs,
)

NOW = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)
AS_OF = NOW.date()


def _metric(
    value: float = 1.0, *, unit: str = "USD", period_kind: str = "ttm"
) -> MetricObservation:
    return MetricObservation(
        value=value,
        as_of=AS_OF,
        available_at=NOW,
        source="fixture",
        unit=unit,
        period_kind=period_kind,
        confidence=0.9,
        lineage=("fixture/fact",),
    )


def test_factor_input_contracts_validate_required_schemas_without_scores() -> None:
    quality = QualityFactorInputs(
        symbol="AAA",
        as_of=AS_OF,
        roic=_metric(unit="RATIO", period_kind="ratio"),
        roic_history=(
            _metric(0.9, unit="RATIO", period_kind="ratio"),
            _metric(unit="RATIO", period_kind="ratio"),
        ),
        fcf_margin=_metric(unit="RATIO", period_kind="ratio"),
        cfo_conversion=_metric(unit="RATIO", period_kind="ratio"),
        stability=_metric(unit="RATIO", period_kind="ratio"),
        leverage=_metric(unit="RATIO", period_kind="ratio"),
        financial_confidence=FinancialConfidence(score=0.9),
    )
    value = ValueFactorInputs(
        symbol="AAA",
        as_of=AS_OF,
        market_cap=_metric(period_kind="instant"),
        enterprise_value=_metric(period_kind="instant"),
        fcf_ttm=_metric(),
        ebitda_ttm=_metric(),
        earnings_ttm=_metric(),
    )
    momentum = MomentumFactorInputs(
        symbol="AAA",
        as_of=AS_OF,
        price_history=(
            PriceObservation(
                date=AS_OF, adjusted_close=10, volume=1000, available_at=NOW, source="fixture"
            ),
        ),
        returns=(_metric(unit="RATIO", period_kind="ratio"),),
        volume=(_metric(unit="SHARES", period_kind="instant"),),
        earnings_revision_metadata=EarningsRevisionMetadata(),
    )
    for contract in (quality, value, momentum):
        fields = type(contract).model_fields
        assert "score" not in fields
        assert "rank" not in fields


def test_value_contract_automatically_rejects_currency_and_period_mismatch() -> None:
    with pytest.raises(ValidationError, match="compatible currency"):
        ValueFactorInputs(
            symbol="AAA",
            as_of=AS_OF,
            market_cap=_metric(period_kind="instant"),
            enterprise_value=_metric(unit="EUR", period_kind="instant"),
            fcf_ttm=_metric(),
            ebitda_ttm=_metric(),
            earnings_ttm=_metric(),
        )

    with pytest.raises(ValidationError, match="must be TTM"):
        ValueFactorInputs(
            symbol="AAA",
            as_of=AS_OF,
            market_cap=_metric(period_kind="instant"),
            enterprise_value=_metric(period_kind="instant"),
            fcf_ttm=_metric(period_kind="fy"),
            ebitda_ttm=_metric(),
            earnings_ttm=_metric(),
        )


def test_factor_contracts_reject_unknown_fields_invalid_confidence_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        FinancialConfidence(score=1.1)
    with pytest.raises(ValidationError):
        EarningsRevisionMetadata(unapproved_signal=1)
    with pytest.raises(ValidationError):
        MetricObservation(
            value=1,
            as_of=AS_OF,
            available_at=NOW,
            source="fixture",
            unit="USD",
            period_kind="ttm",
            confidence=1.1,
            lineage=("fixture",),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        MetricObservation(
            value=1,
            as_of=AS_OF,
            available_at=NOW.replace(tzinfo=None),
            source="fixture",
            unit="USD",
            period_kind="ttm",
            confidence=0.9,
            lineage=("fixture",),
        )
