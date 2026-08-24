from __future__ import annotations

import datetime

import pandas as pd
import pytest

from core.phase36 import run_phase36
from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from data.market_data import LineageEntry, govern_market_data
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.integration import (
    CrossLayerGovernanceError,
    integrate_governed_inputs,
    write_governed_inputs,
)
from governance.units import UnitOntologyError, normalize_unit, unit_kind
from universe.validation import UniverseRules, UniverseValidationError

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
        "fiscal_period_start": "2024-01-01", "period_type": "duration",
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


def _universe(tmp_path, *, market_cap_currency: str | None = "EUR"):
    existing = tmp_path / "snapshots" / AS_OF.date().isoformat()
    if existing.exists():
        return existing
    source = tmp_path / "universe.csv"
    row = {"symbol": "AAA", "exchange": "NYSE", "asset_type": "COMMON_STOCK",
        "country": "US", "region": "North America", "sector": "Industrials",
        "industry": "Machinery", "market_cap": 100.0,
        "average_volume": 1000,
        "average_dollar_volume": 100000, "listing_date": "2020-01-01T00:00:00Z",
        "source": "universe-fixture", "source_timestamp": "2025-01-31T20:00:00Z",
        "available_at": "2025-01-31T21:00:00Z"}
    if market_cap_currency is not None:
        row["market_cap_currency"] = market_cap_currency
    pd.DataFrame([row]).to_csv(source, index=False)
    return run_phase36(source_path=source, rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=AS_OF, output_root=tmp_path / "validation", snapshot_root=tmp_path / "snapshots",
        now=AS_OF).snapshot_dir


def _integrate(tmp_path, **overrides):
    inputs = {"market_data": _market(), "fx": _fx(), "accounting": _accounting(),
        "universe_snapshot_dir": _universe(tmp_path), "as_of": AS_OF, "base_currency": "USD",
        "required_fundamentals": {"revenue", "margin"}}
    inputs.update(overrides)
    return integrate_governed_inputs(**inputs)


def test_cross_layer_integration_translates_and_preserves_identity(tmp_path) -> None:
    result = _integrate(tmp_path)
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


def test_market_cap_currency_is_explicitly_converted_with_complete_fx_lineage(tmp_path) -> None:
    result = _integrate(tmp_path)
    membership = result.universe_membership.set_index("symbol").loc["AAA"]
    conversion = result.fx_conversions.query("metric == 'market_cap'").iloc[0]
    assert membership["original_market_cap"] == pytest.approx(100.0)
    assert membership["market_cap_currency"] == "EUR"
    assert membership["market_cap"] == pytest.approx(110.0)
    assert conversion["source_currency"] == "EUR"
    assert conversion["target_currency"] == "USD"
    assert conversion["rate"] == pytest.approx(1.1)
    assert conversion["conversion_method"] == "direct"
    assert conversion["rate_market_timestamp"] == pd.Timestamp("2024-12-31T16:00:00Z")
    assert conversion["rate_available_at"] == pd.Timestamp("2024-12-31T16:01:00Z")
    assert conversion["fx_canonical_id"] == result.manifest.fx_canonical_id
    assert conversion["fx_checksum"] == result.manifest.fx_checksum


def test_market_cap_in_base_currency_records_identity_without_synthetic_fixing(tmp_path) -> None:
    result = _integrate(
        tmp_path,
        universe_snapshot_dir=_universe(tmp_path, market_cap_currency="USD"),
    )
    conversion = result.fx_conversions.query("metric == 'market_cap'").iloc[0]
    assert conversion["conversion_method"] == "identity"
    assert conversion["rate"] == pytest.approx(1.0)
    assert pd.isna(conversion["rate_market_timestamp"])
    assert pd.isna(conversion["rate_available_at"])
    assert pd.isna(conversion["fx_canonical_id"])


@pytest.mark.parametrize("currency", [None, "", "XYZ", "RATIO"])
def test_missing_or_invalid_market_cap_currency_fails_closed(tmp_path, currency) -> None:
    with pytest.raises((UniverseValidationError, CrossLayerGovernanceError, UnitOntologyError)):
        _integrate(
            tmp_path,
            universe_snapshot_dir=_universe(tmp_path, market_cap_currency=currency),
        )


def test_cross_layer_fingerprint_is_reproducible(tmp_path) -> None:
    first, second = _integrate(tmp_path), _integrate(tmp_path)
    assert first.manifest.fingerprint == second.manifest.fingerprint
    assert first.manifest.model_dump(mode="json") == second.manifest.model_dump(mode="json")


def test_cross_layer_bundle_is_content_addressed_and_immutable(tmp_path) -> None:
    result = _integrate(tmp_path)
    output = write_governed_inputs(result, output_root=tmp_path)
    assert output.name == f"cross_layer_{result.manifest.fingerprint}"
    assert {path.name for path in output.iterdir()} == {
        "market_snapshot.csv",
        "accounting_snapshot.csv",
        "fx_conversions.csv",
        "cross_layer_manifest.json",
        "universe_membership.csv",
    }
    assert write_governed_inputs(result, output_root=tmp_path) == output
    (output / "market_snapshot.csv").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(CrossLayerGovernanceError, match="immutable"):
        write_governed_inputs(result, output_root=tmp_path)


def test_manual_entity_override_is_not_accepted(tmp_path) -> None:
    with pytest.raises(TypeError, match="eligible_entities"):
        _integrate(tmp_path, eligible_entities={"AAA", "BBB"})


def test_missing_required_fundamental_fails_closed(tmp_path) -> None:
    with pytest.raises(CrossLayerGovernanceError, match="missing fundamentals"):
        _integrate(tmp_path, required_fundamentals={"revenue", "ebit"})


def test_mutation_after_governance_fails_closed(tmp_path) -> None:
    market = _market()
    market.frame.loc[0, "adjusted_close"] = 99.0
    with pytest.raises(CrossLayerGovernanceError, match="mutation detected"):
        _integrate(tmp_path, market_data=market)


def test_naive_cutoff_fails_closed(tmp_path) -> None:
    with pytest.raises(CrossLayerGovernanceError, match="timezone-aware"):
        _integrate(tmp_path, as_of=datetime.datetime(2025, 1, 31))  # noqa: DTZ001


def test_unit_ontology_is_explicit_and_fail_closed() -> None:
    assert normalize_unit("usd") == "USD"
    assert unit_kind("USD") == "MONETARY"
    assert unit_kind("BPS") == "NON_MONETARY"
    with pytest.raises(UnitOntologyError, match="unknown unit"):
        normalize_unit("ABC")


def test_post_governance_snapshot_mutation_fails_before_factor_sealing(tmp_path) -> None:
    from governance.research_chain import seal_factor_output

    result = _integrate(tmp_path)
    result.accounting_snapshot.loc[0, "value"] = 999.0
    metrics = pd.DataFrame([{"symbol": "AAA", "as_of": AS_OF.date(), "metric": "roic",
        "value": 0.1, "unit": "percentage", "available_at": "2025-01-30T00:00:00Z",
        "confidence": 1.0, "status": "PASS", "reason": None,
        "lineage": "{\"source\": \"governed\"}"}])
    with pytest.raises(CrossLayerGovernanceError, match="accounting snapshot hash mismatch"):
        seal_factor_output(factor="Quality", metrics=metrics, cross_layer=result)
