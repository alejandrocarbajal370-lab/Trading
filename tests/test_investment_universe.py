import datetime
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from core.phase36 import run_phase36
from universe.diagnostics import UniverseHealthRules, diagnose_universe, stress_test_universe
from universe.schedule import UniverseRebalanceSchedule
from universe.snapshots import UniverseSnapshotStore
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
    assert result["universe_confidence"] < 1


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
        snapshot_root=tmp_path / "snapshots",
    )
    validation = json.loads((result.output_dir / "universe_validation.json").read_text())
    summary = json.loads((result.output_dir / "run_summary.json").read_text())
    assert validation["counts"]["eligible"] == 1
    assert validation["counts"]["excluded"] == 3
    assert validation["rules"]["minimum_market_cap"] == 100_000_000
    assert validation["distributions"]["sector"] == {"Technology": 1}
    assert validation["stress_tests"]
    assert result.snapshot_dir.name == "2026-08-20"
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
            snapshot_root=tmp_path / "snapshots",
        )
    run_dir = next((tmp_path / "outputs").iterdir())
    validation = json.loads((run_dir / "universe_validation.json").read_text())
    manifest = json.loads((run_dir / "validation_manifest.json").read_text())
    assert validation["status"] == "FAIL"
    assert validation["trade_decision"] == "NO_TRADE"
    assert manifest["critical_errors"] == 1
    assert not (run_dir / "universe_membership.csv").exists()


def test_historical_snapshots_are_reconstructible_and_immutable(tmp_path: Path) -> None:
    store = UniverseSnapshotStore(tmp_path)
    first = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    validation = {"status": "PASS"}
    store.save(
        first,
        as_of=AS_OF,
        validation=validation,
        rules=_rules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=AS_OF,
    )
    reconstructed = store.load("2026-08-20").set_index("symbol")
    assert reconstructed.loc["AAA", "eligibility_status"] == "ELIGIBLE"
    changed = first.copy()
    changed.loc[changed["symbol"] == "AAA", "eligibility_status"] = "EXCLUDED"
    with pytest.raises(UniverseValidationError, match="immutable universe snapshot"):
        store.save(
            changed,
            as_of=AS_OF,
            validation=validation,
            rules=_rules(),
            schedule=UniverseRebalanceSchedule(),
            recorded_at=AS_OF,
        )


def test_snapshot_history_prevents_survivorship_bias_when_asset_later_disappears(
    tmp_path: Path,
) -> None:
    store = UniverseSnapshotStore(tmp_path)
    first = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    store.save(
        first,
        as_of=AS_OF,
        validation={"status": "PASS"},
        rules=_rules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=AS_OF,
    )
    later_records = _records().loc[_records()["symbol"] != "AAA"]
    later_date = pd.Timestamp("2026-09-20T00:00:00Z")
    later = validate_universe(later_records, rules=_rules(), as_of=later_date)
    store.save(
        later,
        as_of=later_date,
        validation={"status": "PASS"},
        rules=_rules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=later_date,
    )
    assert "AAA" in set(store.load("2026-08-20")["symbol"])
    assert "AAA" not in set(store.load("2026-09-20")["symbol"])


def test_entries_exits_and_exclusion_reasons_are_audited() -> None:
    previous = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    current_records = _records().copy()
    current_records.loc[current_records["symbol"] == "AAA", "market_cap"] = 1
    current_records.loc[current_records["symbol"] == "SMALL", "market_cap"] = 1_000_000_000
    current_records.loc[current_records["symbol"] == "SMALL", "average_volume"] = 1_000_000
    current_records.loc[current_records["symbol"] == "SMALL", "average_dollar_volume"] = 20_000_000
    current = validate_universe(current_records, rules=_rules(), as_of=AS_OF)
    diagnostic = diagnose_universe(
        current,
        rules=_rules(),
        health_rules=UniverseHealthRules(),
        stress_tests=[],
        previous=previous,
    )
    assert diagnostic["changes"]["entries"] == ["SMALL"]
    assert diagnostic["changes"]["exits"] == ["AAA"]
    aaa = next(change for change in diagnostic["changes"]["changes"] if change["symbol"] == "AAA")
    assert aaa["reason"] == "market_cap_below_minimum"


def test_threshold_sensitivity_reports_coverage_impact() -> None:
    records = _records().iloc[[0]].copy()
    records.loc[:, "market_cap"] = 110_000_000
    tests = stress_test_universe(records, rules=_rules(), as_of=AS_OF)
    stricter = next(test for test in tests if test["scenario"] == "minimum_market_cap_plus_20pct")
    assert stricter["eligible"] == 0
    assert stricter["coverage_loss"] == 1.0


def test_empty_universe_is_fail_with_auditable_reason() -> None:
    membership = validate_universe(_records(), rules=_rules(minimum_market_cap=99e12), as_of=AS_OF)
    diagnostic = diagnose_universe(
        membership,
        rules=_rules(minimum_market_cap=99e12),
        health_rules=UniverseHealthRules(),
        stress_tests=[],
    )
    assert diagnostic["status"] == "FAIL"
    assert {reason["code"] for reason in diagnostic["reasons"]} >= {"empty_eligible_universe"}


def test_excessive_concentration_is_warning() -> None:
    membership = validate_universe(_records().iloc[[0]], rules=_rules(), as_of=AS_OF)
    diagnostic = diagnose_universe(
        membership,
        rules=_rules(),
        health_rules=UniverseHealthRules(maximum_group_concentration=0.5),
        stress_tests=[],
    )
    assert diagnostic["status"] == "WARNING"
    assert "excessive_sector_concentration" in {
        reason["code"] for reason in diagnostic["reasons"]
    }


def test_snapshot_checksum_failure_leaves_detectable_audit_violation(tmp_path: Path) -> None:
    store = UniverseSnapshotStore(tmp_path)
    membership = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    directory = store.save(
        membership,
        as_of=AS_OF,
        validation={"status": "PASS"},
        rules=_rules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=AS_OF,
    )
    membership_path = directory / "universe_membership.csv"
    membership_path.write_text(membership_path.read_text() + "corrupt", encoding="utf-8")
    with pytest.raises(UniverseValidationError, match="checksum mismatch"):
        store.load(AS_OF)


def test_ruleset_version_and_schedule_are_persisted_in_snapshot(tmp_path: Path) -> None:
    rules = _rules(ruleset_version="universe-v2")
    result = run_phase36(
        source_path=FIXTURE,
        rules=rules,
        schedule=UniverseRebalanceSchedule(frequency="monthly"),
        as_of=AS_OF,
        output_root=tmp_path / "outputs",
        snapshot_root=tmp_path / "snapshots",
        now=datetime.datetime(2026, 8, 20, 12, tzinfo=datetime.UTC),
    )
    metadata = json.loads((result.snapshot_dir / "snapshot_metadata.json").read_text())
    assert metadata["ruleset"]["version"] == "universe-v2"
    assert metadata["ruleset"]["parameters"]["minimum_market_cap"] == 100_000_000
    assert metadata["next_expected_date"] == "2026-09-20"
    assert metadata["rebalance_schedule"] == {"frequency": "monthly", "interval": 1}

    with pytest.raises(UniverseValidationError, match="snapshot ruleset already exists"):
        UniverseSnapshotStore(tmp_path / "snapshots").save(
            result.membership,
            as_of=AS_OF,
            validation={"status": "PASS"},
            rules=_rules(ruleset_version="universe-v3"),
            schedule=UniverseRebalanceSchedule(),
            recorded_at=AS_OF,
        )


def test_same_inputs_reproduce_identical_membership(tmp_path: Path) -> None:
    first = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    second = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    pd.testing.assert_frame_equal(first, second)
    store = UniverseSnapshotStore(tmp_path)
    directory = store.save(
        first,
        as_of=AS_OF,
        validation={"status": "PASS"},
        rules=_rules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=AS_OF,
    )
    original = (directory / "universe_membership.csv").read_bytes()
    store.save(
        second,
        as_of=AS_OF,
        validation={"status": "PASS"},
        rules=_rules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=AS_OF,
    )
    assert (directory / "universe_membership.csv").read_bytes() == original


def test_ruleset_change_is_explicit_in_membership_comparison() -> None:
    previous = validate_universe(_records(), rules=_rules(ruleset_version="v1"), as_of=AS_OF)
    current = validate_universe(_records(), rules=_rules(ruleset_version="v2"), as_of=AS_OF)
    report = diagnose_universe(
        current,
        rules=_rules(ruleset_version="v2"),
        health_rules=UniverseHealthRules(),
        stress_tests=[],
        previous=previous,
        previous_ruleset_version="v1",
    )
    assert report["changes"]["ruleset_changed"] is True


def test_universe_confidence_is_not_financial_confidence() -> None:
    membership = validate_universe(_records(), rules=_rules(), as_of=AS_OF)
    assert "universe_confidence" in membership
    assert "financial_confidence" not in membership
    assert "confidence" not in membership


def test_universe_validation_entry_point_generates_outputs(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.phase36",
            "--source",
            str(FIXTURE),
            "--as-of",
            "2026-08-20",
            "--output-root",
            str(tmp_path / "outputs"),
            "--snapshot-root",
            str(tmp_path / "snapshots"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output_dir, snapshot_dir = (Path(line) for line in result.stdout.strip().splitlines())
    assert (output_dir / "universe_validation.json").exists()
    assert (snapshot_dir / "snapshot_metadata.json").exists()
