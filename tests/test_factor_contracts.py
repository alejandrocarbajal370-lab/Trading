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


def _metric(value: float = 1.0) -> MetricObservation:
    return MetricObservation(value=value, as_of=AS_OF, available_at=NOW, source="fixture")


def test_factor_input_contracts_validate_required_schemas_without_scores() -> None:
    quality = QualityFactorInputs(
        symbol="AAA",
        as_of=AS_OF,
        roic=_metric(),
        roic_history=(_metric(0.9), _metric()),
        fcf_margin=_metric(),
        cfo_conversion=_metric(),
        stability=_metric(),
        leverage=_metric(),
        financial_confidence=FinancialConfidence(score=0.9),
    )
    value = ValueFactorInputs(
        symbol="AAA",
        as_of=AS_OF,
        market_cap=_metric(),
        enterprise_value=_metric(),
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
        returns=(_metric(),),
        volume=(_metric(),),
        earnings_revision_metadata=EarningsRevisionMetadata(),
    )
    for contract in (quality, value, momentum):
        fields = type(contract).model_fields
        assert "score" not in fields
        assert "rank" not in fields


def test_factor_contracts_reject_unknown_fields_and_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        FinancialConfidence(score=1.1)
    with pytest.raises(ValidationError):
        EarningsRevisionMetadata(unapproved_signal=1)
