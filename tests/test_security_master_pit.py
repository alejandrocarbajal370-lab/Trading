from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import pytest

from data.sec_universe_binding import build_sec_acquisition_plan
from data.security_master_pit import (
    ConstituentRecord,
    PITUniverseArtifact,
    ProviderIdentity,
    SecurityIdentityRecord,
    SecurityMasterPITError,
    reconstruct_pit_universe,
    universe_source_records,
)
from universe.schedule import UniverseRebalanceSchedule
from universe.snapshots import UniverseSnapshotStore
from universe.validation import UniverseRules, universe_health, validate_universe

UTC = datetime.UTC
OLD_DATE = datetime.datetime(2020, 6, 1, tzinfo=UTC)
NEW_DATE = datetime.datetime(2022, 6, 1, tzinfo=UTC)
PROVIDER = ProviderIdentity(
    name="contract-only-provider", version="v1", licensing="OPEN_EXTERNAL",
    retention="raw snapshots required before connection", state="OPEN_EXTERNAL",
)
HASHES = ("a" * 64,)


def security(pid="sec-1", symbol="OLD", start=datetime.datetime(2010, 1, 1, tzinfo=UTC),
             end=None, valid_from=datetime.datetime(2010, 1, 1, tzinfo=UTC), valid_to=None,
             available=datetime.datetime(2010, 1, 2, tzinfo=UTC), record="s1", cik="0000000001"):
    return SecurityIdentityRecord(
        permanent_id=pid, issuer_id=f"issuer-{pid}", symbol=symbol, exchange="NYSE",
        listing_start=start, listing_end=end,
        delisting_status="DELISTED" if end else "ACTIVE", share_class="A",
        security_type="COMMON_STOCK", canonical_cik=cik,
        cik_lineage="provider-cik-field" if cik is not None else None,
        source="licensed-master", source_record_id=record, available_at=available,
        valid_from=valid_from, valid_to=valid_to, confidence=None,
    )


def member(pid="sec-1", entry=datetime.datetime(2010, 1, 1, tzinfo=UTC), exit=None,
           available=datetime.datetime(2010, 1, 2, tzinfo=UTC), record="m1"):
    return ConstituentRecord(
        universe_id="IDX", permanent_id=pid, entry_at=entry, exit_at=exit,
        source="licensed-constituents", source_record_id=record, available_at=available,
        valid_from=entry, confidence=None,
    )


def reconstruct(securities, memberships, as_of=OLD_DATE):
    return reconstruct_pit_universe(
        security_records=securities, constituent_records=memberships, universe_id="IDX",
        as_of=as_of, provider=PROVIDER, source_hashes=HASHES,
        runtime_code_fingerprint="git:test-runtime", require_cik=True,
    )


def observations(ids):
    return pd.DataFrame([{
        "permanent_id": pid, "asset_type": "COMMON_STOCK", "country": "US",
        "region": "North America", "sector": "Industrials", "industry": "Tools",
        "market_cap": 1_000_000_000, "market_cap_currency": "USD",
        "average_volume": 1_000_000, "average_dollar_volume": 25_000_000,
        "source_timestamp": "2020-05-30T00:00:00Z", "available_at": "2020-05-31T00:00:00Z",
    } for pid in ids])


def test_ticker_change_preserves_identity_and_reorder_preserves_hash():
    old = security(end=datetime.datetime(2021, 1, 1, tzinfo=UTC), valid_to=datetime.datetime(2021, 1, 1, tzinfo=UTC))
    new = security(symbol="NEW", start=datetime.datetime(2021, 1, 1, tzinfo=UTC),
                   valid_from=datetime.datetime(2021, 1, 1, tzinfo=UTC), record="s2")
    membership = member()
    before = reconstruct([new, old], [membership], OLD_DATE)
    after = reconstruct([old, new], [membership], NEW_DATE)
    assert before.artifact.permanent_identities == after.artifact.permanent_identities == ("sec-1",)
    assert before.securities[0].symbol == "OLD"
    assert after.securities[0].symbol == "NEW"
    assert reconstruct([old], [membership], OLD_DATE).artifact.artifact_hash == reconstruct([old], [membership], OLD_DATE).artifact.artifact_hash


def test_listing_delisting_and_survivorship_reconstruction():
    delisted = security(end=datetime.datetime(2021, 1, 1, tzinfo=UTC))
    membership = member(exit=datetime.datetime(2021, 1, 1, tzinfo=UTC))
    assert reconstruct([delisted], [membership], OLD_DATE).artifact.permanent_identities == ("sec-1",)
    with pytest.raises(SecurityMasterPITError, match="membership cannot"):
        reconstruct([delisted], [membership], NEW_DATE)
    late = security(start=datetime.datetime(2023, 1, 1, tzinfo=UTC),
                    valid_from=datetime.datetime(2023, 1, 1, tzinfo=UTC))
    with pytest.raises(SecurityMasterPITError, match="uniquely demonstrated"):
        reconstruct([late], [member()], OLD_DATE)


def test_future_conflicts_duplicates_missing_cik_and_placeholders_reject():
    with pytest.raises(SecurityMasterPITError, match="future security"):
        reconstruct([security(available=OLD_DATE + datetime.timedelta(days=1))], [member()])
    conflicting = security(symbol="BAD", record="s2")
    with pytest.raises(SecurityMasterPITError, match="overlapping conflicting"):
        reconstruct([security(), conflicting], [member()])
    with pytest.raises(SecurityMasterPITError, match="duplicate source"):
        reconstruct([security(), security(pid="sec-2", cik="0000000002")], [member()])
    with pytest.raises(SecurityMasterPITError, match="CIK.*missing"):
        reconstruct([security(cik=None)], [member()])
    with pytest.raises(ValueError, match="placeholder"):
        security(pid="unknown")
    with pytest.raises(SecurityMasterPITError, match="future membership"):
        reconstruct(
            [security()],
            [member(available=OLD_DATE + datetime.timedelta(days=1))],
        )


def test_ticker_reuse_and_same_ticker_different_security_do_not_merge():
    first = security(end=datetime.datetime(2021, 1, 1, tzinfo=UTC))
    second = security(pid="sec-2", symbol="OLD", start=datetime.datetime(2022, 1, 1, tzinfo=UTC),
                      valid_from=datetime.datetime(2022, 1, 1, tzinfo=UTC), record="s2", cik="0000000002")
    first_member = member(exit=datetime.datetime(2021, 1, 1, tzinfo=UTC))
    second_member = member(pid="sec-2", entry=datetime.datetime(2022, 1, 1, tzinfo=UTC), record="m2")
    assert reconstruct([first, second], [first_member, second_member], OLD_DATE).artifact.permanent_identities == ("sec-1",)
    assert reconstruct([first, second], [first_member, second_member], NEW_DATE).artifact.permanent_identities == ("sec-2",)


def test_outsider_exact_coverage_current_list_and_mutation_fail_closed():
    result = reconstruct([security(), security(pid="outsider", record="s2", cik="0000000002")], [member()])
    assert result.artifact.permanent_identities == ("sec-1",)
    assert result.artifact.historical_completeness is False
    with pytest.raises(SecurityMasterPITError, match="exactly cover"):
        universe_source_records(result, observations(["sec-1", "outsider"]))
    payload = result.artifact.model_dump(mode="python")
    payload["membership_hash"] = "f" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        PITUniverseArtifact.model_validate(payload)


def test_e2e_pit_to_governed_universe_to_existing_sec_binding(tmp_path: Path):
    result = reconstruct([security(symbol="DERIVED")], [member()])
    source = universe_source_records(result, observations(["sec-1"]))
    assert source["symbol"].tolist() == ["DERIVED"]
    rules = UniverseRules()
    membership = validate_universe(source, rules=rules, as_of=pd.Timestamp(OLD_DATE))
    snapshot = UniverseSnapshotStore(tmp_path / "universe").save(
        membership, as_of=pd.Timestamp(OLD_DATE), validation=universe_health(membership, rules=rules),
        rules=rules, schedule=UniverseRebalanceSchedule(), recorded_at=pd.Timestamp(OLD_DATE),
    )
    mapping = pd.DataFrame([{
        "permanent_id": "sec-1", "cik": "0000000001", "valid_from": "2010-01-01T00:00:00Z",
        "valid_to": None, "available_at": "2010-01-02T00:00:00Z", "source": "licensed-master",
        "source_record_id": "s1",
    }])
    plan = build_sec_acquisition_plan(
        universe_snapshot_dir=snapshot, security_master_records=mapping, as_of=OLD_DATE,
    )
    assert plan.eligible_permanent_ids == ("sec-1",)
    assert plan.issuers[0].canonical_cik == "0000000001"
