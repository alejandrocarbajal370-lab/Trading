import datetime
import json
from pathlib import Path

import pandas as pd
import pytest

from core.phase36 import run_phase36
from universe.validation import UniverseRules, UniverseValidationError, validate_universe

FIXTURE = Path("tests/fixtures/universe.csv")
AS_OF = pd.Timestamp("2026-08-20T00:00:00Z")


def _records() -> pd.DataFrame:
    return pd.read_csv(FIXTURE)


def _rules(**overrides: object) -> UniverseRules:
    defaults = {
        "minimum_market_cap": 100_000_000,
        "minimum_average_volume": 500_000,
        "minimum_average_dollar_volume": 10_000_000,
        "allowed_asset_types": ("COMMON_STOCK",),
        "minimum_listing_age_days": 365,
        "allowed_exchanges": ("NASDAQ", "NYSE"),
    }
    return UniverseRules(**(defaults | overrides))


def test_inclusion_and_every_exclusion_is_retained_with_reasons() -> None:
    result = validate_universe(_records(), rules=_rules(), as_of=AS_OF).set_index("symbol")
    assert result.loc["AAA", "eligibility_status"] == "ELIGIBLE"
    assert "market_cap_below_minimum" in result.loc["SMALL", "exclusion_reason"]
    assert "average_volume_below_minimum" in result.loc["SMALL", "exclusion_reason"]
    assert result.loc["ETF1", "exclusion_reason"] == "asset_type_not_allowed"
    assert result.loc["NEW", "exclusion_reason"] == "listing_age_below_minimum"
    assert len(result) == 4
    assert json.loads(result.loc["AAA", "lineage"])["source"] == "fixture"


def test_missing_threshold_data_is_an_explicit_exclusion() -> None:
    records = _records().iloc[[0]].copy()
    records["market_cap"] = float("nan")
    result = validate_universe(records, rules=_rules(), as_of=AS_OF).iloc[0]
    assert result["eligibility_status"] == "EXCLUDED"
    assert result["exclusion_reason"] == "missing_market_cap"
    assert result["confidence"] < 1


def test_thresholds_and_etf_policy_are_configurable() -> None:
    permissive = _rules(
        minimum_market_cap=0,
        minimum_average_volume=0,
        minimum_average_dollar_volume=0,
        minimum_listing_age_days=0,
        allowed_asset_types=("COMMON_STOCK", "ETF"),
    )
    result = validate_universe(_records(), rules=permissive, as_of=AS_OF)
    assert set(result["eligibility_status"]) == {"ELIGIBLE"}


def test_exchange_filter_is_configurable() -> None:
    result = validate_universe(
        _records().iloc[[1]], rules=_rules(allowed_exchanges=("NASDAQ",)), as_of=AS_OF
    ).iloc[0]
    assert "exchange_not_allowed" in result["exclusion_reason"]


def test_duplicate_symbols_and_invalid_asset_types_violate_contract() -> None:
    duplicate = pd.concat([_records().iloc[[0]], _records().iloc[[0]]], ignore_index=True)
    with pytest.raises(UniverseValidationError, match="duplicate symbols: AAA"):
        validate_universe(duplicate, rules=_rules(), as_of=AS_OF)
    invalid = _records().iloc[[0]].copy()
    invalid.loc[:, "asset_type"] = "CRYPTO"
    with pytest.raises(UniverseValidationError, match="invalid asset types: CRYPTO"):
        validate_universe(invalid, rules=_rules(), as_of=AS_OF)


def test_phase36_writes_validation_and_preserves_safety(tmp_path: Path) -> None:
    result = run_phase36(
        source_path=FIXTURE,
        rules=_rules(),
        as_of=datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC),
        output_root=tmp_path,
    )
    validation = json.loads((result.output_dir / "universe_validation.json").read_text())
    summary = json.loads((result.output_dir / "run_summary.json").read_text())
    assert validation["eligible"] == 1
    assert validation["excluded"] == 3
    assert validation["rules"]["minimum_market_cap"] == 100_000_000
    assert summary["trade_decision"] == "NO_TRADE"
    assert summary["live_execution_enabled"] is False


def test_failure_audit_trail_is_written_and_error_is_reraised(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.csv"
    _records().drop(columns="exchange").to_csv(invalid, index=False)
    with pytest.raises(UniverseValidationError, match="missing required fields: exchange"):
        run_phase36(
            source_path=invalid,
            rules=_rules(),
            as_of=datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC),
            output_root=tmp_path / "outputs",
        )
    run_dir = next((tmp_path / "outputs").iterdir())
    validation = json.loads((run_dir / "universe_validation.json").read_text())
    manifest = json.loads((run_dir / "validation_manifest.json").read_text())
    assert validation["status"] == "FAIL"
    assert validation["trade_decision"] == "NO_TRADE"
    assert manifest["critical_errors"] == 1
    assert not (run_dir / "universe_membership.csv").exists()
