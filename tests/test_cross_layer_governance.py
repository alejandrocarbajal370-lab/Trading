from __future__ import annotations

import datetime

import pandas as pd
import pytest

from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from data.market_data import LineageEntry, govern_market_data
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.integration import (
    CrossLayerGovernanceError,
    integrate_governed_inputs,
    write_governed_inputs,
)

AS_OF = datetime.datetime(2025, 1, 31, 23, 59, tzinfo=datetime.UTC)


def _market():
    return govern_market_data(
        pd.DataFrame([{"symbol": "AAA", "date": "2025-01-31", "raw_close": 100.0,
            "adjusted_close": 100.0, "currency": "USD", "available_at": "2025-01-31T22:00:00Z",
            "corporate_action_status": "NONE", "corporate_action_type": None,
            "adjustment_factor": 1.0}]),
        source="market-fixture", dataset_version="market-v1",
        available_at=datetime.datetime(2025, 1, 31, 22, tzinfo=datetime.UTC),
        lineage=(LineageEntry(source="market-fixture", dataset="prices", dataset_version="v1"),),
        trading_calendar="XNYS", as_of=AS_OF, maximum_staleness_sessions=0,
    )


def _fx():
    return govern_fx(
        pd.DataFrame([{"currency_pair": "EUR/USD", "base_currency": "EUR",
            "quote_currency": "USD", "market_timestamp": "2024-12-31T16:00:00Z",
            "available_at": "2024-12-31T16:01:00Z", "rate": 1.1}]),
        source="fx-fixture", dataset_version="fx-v1",
        available_at=datetime.datetime(2025, 1, 31, 22, tzinfo=datetime.UTC),
        lineage=(FXLineageEntry(source="fx-fixture", dataset="rates", dataset_version="v1"),),
        as_of=AS_OF, staleness_policy=FXStalenessPolicy(maximum_sessions=30),
    )


def _accounting():
    common = {"entity": "AAA", "fiscal_period": "FY2024", "period_end": "2024-12-31",
        "filing_date": "2025-01-20T12:00:00Z", "available_at": "2025-01-20T12:01:00Z",
        "source": "accounting-fixture", "dataset_version": "accounting-v1", "revision": 0,
        "revision_type": "ORIGINAL", "supersedes_revision": None}
    return govern_accounting(
        pd.DataFrame([
            {**common, "fact_id": "aaa-revenue-2024", "metric": "revenue", "value": 100.0,
             "unit": "EUR"},
            {**common, "fact_id": "aaa-margin-2024", "metric": "margin", "value": 0.2,
             "unit": "RATIO"},
        ]),
        source="accounting-fixture", dataset_version="accounting-v1",
        available_at=datetime.datetime(2025, 1, 31, 22, tzinfo=datetime.UTC),
        lineage=(AccountingLineageEntry(source="accounting-fixture", dataset="facts",
            dataset_version="v1"),), as_of=AS_OF,
    )


def _integrate(**overrides):
    inputs = {"market_data": _market(), "fx": _fx(), "accounting": _accounting(),
        "eligible_entities": {"AAA"}, "as_of": AS_OF, "base_currency": "USD",
        "required_fundamentals": {"revenue", "margin"}}
    inputs.update(overrides)
    return integrate_governed_inputs(**inputs)


def test_cross_layer_integration_translates_and_preserves_identity() -> None:
    result = _integrate()
    facts = result.accounting_snapshot.set_index("metric")
    assert facts.loc["revenue", "value"] == pytest.approx(110.0)
    assert facts.loc["revenue", "unit"] == "USD"
    assert facts.loc["margin", "value"] == pytest.approx(0.2)
    conversion = result.fx_conversions.set_index("metric").loc["revenue"]
    assert conversion["conversion_method"] == "direct"
    assert conversion["fx_canonical_id"] == result.manifest.fx_canonical_id
    assert result.manifest.health == "PASS"
    assert result.manifest.trade_decision == "NO_TRADE"
    assert result.manifest.live_execution_enabled is False
    assert result.manifest.scores_calculated is False
    assert result.manifest.ranking_calculated is False
    assert result.manifest.portfolio_constructed is False


def test_cross_layer_fingerprint_is_reproducible() -> None:
    first, second = _integrate(), _integrate()
    assert first.manifest.fingerprint == second.manifest.fingerprint
    assert first.manifest.model_dump(mode="json") == second.manifest.model_dump(mode="json")


def test_cross_layer_bundle_is_content_addressed_and_immutable(tmp_path) -> None:
    result = _integrate()
    output = write_governed_inputs(result, output_root=tmp_path)
    assert output.name == f"cross_layer_{result.manifest.fingerprint}"
    assert {path.name for path in output.iterdir()} == {
        "market_snapshot.csv",
        "accounting_snapshot.csv",
        "fx_conversions.csv",
        "cross_layer_manifest.json",
    }
    assert write_governed_inputs(result, output_root=tmp_path) == output
    (output / "market_snapshot.csv").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(CrossLayerGovernanceError, match="immutable"):
        write_governed_inputs(result, output_root=tmp_path)


def test_entity_mismatch_fails_closed() -> None:
    with pytest.raises(CrossLayerGovernanceError, match="entity alignment"):
        _integrate(eligible_entities={"AAA", "BBB"})


def test_missing_required_fundamental_fails_closed() -> None:
    with pytest.raises(CrossLayerGovernanceError, match="missing fundamentals"):
        _integrate(required_fundamentals={"revenue", "ebit"})


def test_mutation_after_governance_fails_closed() -> None:
    market = _market()
    market.frame.loc[0, "adjusted_close"] = 99.0
    with pytest.raises(CrossLayerGovernanceError, match="mutation detected"):
        _integrate(market_data=market)


def test_naive_cutoff_fails_closed() -> None:
    with pytest.raises(CrossLayerGovernanceError, match="timezone-aware"):
        _integrate(as_of=datetime.datetime(2025, 1, 31))  # noqa: DTZ001
