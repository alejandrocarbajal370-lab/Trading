from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data.connectors.sec_edgar import SecEdgarFundamentalsSource, SecEdgarResponse
from data.raw_snapshots import RawSnapshotStore
from data.sec_universe_binding import (
    SecAcquisitionPlan,
    SecUniverseBindingError,
    build_sec_acquisition_plan,
    build_sec_acquisition_plan_from_unproved_records_for_testing,
    ingest_governed_universe,
)
from governance.canonical import typed_hash
from universe.schedule import UniverseRebalanceSchedule
from universe.snapshots import UniverseSnapshotStore
from universe.validation import UniverseRules, validate_universe

AS_OF = datetime.datetime(2026, 8, 25, 20, 0, tzinfo=datetime.UTC)


def _universe(
    tmp_path: Path, members=("issuer-aaa", "issuer-bbb"), symbols: tuple[str, ...] | None = None
) -> Path:
    rows = []
    for index, permanent_id in enumerate(members):
        rows.append(
            {
                "symbol": (
                    symbols[index]
                    if symbols is not None
                    else ("OLD" if permanent_id == "issuer-aaa" and index == 0 else f"T{index}")
                ),
                "permanent_id": permanent_id,
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Technology",
                "industry": "Software",
                "market_cap": 1_000_000_000,
                "market_cap_currency": "USD",
                "average_volume": 1_000_000,
                "average_dollar_volume": 50_000_000,
                "listing_date": "2010-01-01",
                "source": "governed-universe-fixture",
                "source_timestamp": "2026-08-25T18:00:00Z",
                "available_at": "2026-08-25T19:00:00Z",
            }
        )
    membership = validate_universe(
        pd.DataFrame(rows), rules=UniverseRules(), as_of=pd.Timestamp(AS_OF)
    )
    return UniverseSnapshotStore(tmp_path / "universe").save(
        membership,
        as_of=pd.Timestamp(AS_OF),
        validation={"status": "PASS"},
        rules=UniverseRules(),
        schedule=UniverseRebalanceSchedule(),
        recorded_at=pd.Timestamp(AS_OF),
    )


def _mappings(ids=("issuer-aaa", "issuer-bbb")) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "permanent_id": permanent_id,
                "cik": str(index + 1),
                "valid_from": "2020-01-01T00:00:00Z",
                "valid_to": None,
                "available_at": "2020-01-02T00:00:00Z",
                "source": "security-master-contract-fixture",
                "source_record_id": f"record-{index + 1}",
            }
            for index, permanent_id in enumerate(ids)
        ]
    )


def _plan(tmp_path: Path, members=("issuer-aaa", "issuer-bbb"), mappings=None):
    return build_sec_acquisition_plan_from_unproved_records_for_testing(
        universe_snapshot_dir=_universe(tmp_path, members),
        security_master_records=_mappings(members) if mappings is None else mappings,
        as_of=AS_OF,
    )


def test_universe_change_changes_exact_sec_issuers_and_excludes_outsiders(tmp_path):
    mappings = _mappings(("issuer-aaa", "issuer-bbb", "issuer-outside"))
    first = _plan(tmp_path / "first", ("issuer-aaa", "issuer-bbb"), mappings)
    second = _plan(tmp_path / "second", ("issuer-bbb",), mappings)
    assert {item.canonical_cik for item in first.issuers} == {"0000000001", "0000000002"}
    assert {item.canonical_cik for item in second.issuers} == {"0000000002"}
    assert all("issuer-outside" not in item.permanent_ids for item in first.issuers)


def test_missing_malformed_conflicting_and_duplicate_identity_fail_closed(tmp_path):
    with pytest.raises(SecUniverseBindingError, match="no CIK"):
        _plan(tmp_path / "missing", mappings=_mappings(("issuer-aaa",)))
    malformed = _mappings()
    malformed.loc[0, "cik"] = "AAPL"
    with pytest.raises(SecUniverseBindingError, match="malformed"):
        _plan(tmp_path / "malformed", mappings=malformed)
    conflicting = pd.concat([_mappings(), _mappings().iloc[[0]].assign(cik="9")])
    with pytest.raises(SecUniverseBindingError, match="duplicate/conflicting"):
        _plan(tmp_path / "conflict", mappings=conflicting)
    with pytest.raises(SecUniverseBindingError, match="duplicate permanent"):
        _plan(tmp_path / "duplicate", members=("issuer-aaa", "issuer-aaa"))


def test_future_mapping_and_mutated_universe_or_plan_fail_closed(tmp_path):
    future = _mappings()
    future.loc[0, "available_at"] = "2026-08-26T00:00:00Z"
    with pytest.raises(SecUniverseBindingError, match="future"):
        _plan(tmp_path / "future", mappings=future)
    universe_dir = _universe(tmp_path / "mutated")
    path = universe_dir / "universe_membership.csv"
    path.write_text(path.read_text().replace("issuer-aaa", "issuer-mutated"))
    with pytest.raises(SecUniverseBindingError, match="checksum mismatch"):
        build_sec_acquisition_plan_from_unproved_records_for_testing(
            universe_snapshot_dir=universe_dir,
            security_master_records=_mappings(),
            as_of=AS_OF,
        )
    plan = _plan(tmp_path / "stale")
    payload = plan.model_dump(mode="python")
    payload["eligible_permanent_ids"] = ("issuer-mutated", "issuer-bbb")
    with pytest.raises(ValueError, match="not canonical|exactly cover|hash mismatch"):
        SecAcquisitionPlan.model_validate(payload)


@pytest.mark.parametrize("field", ["source", "source_record_id"])
@pytest.mark.parametrize(
    "invalid", [None, np.nan, "nan", "none", "null", "n/a", "na", "unknown", "   "]
)
def test_null_and_placeholder_lineage_fail_closed(tmp_path, field, invalid):
    mappings = _mappings()
    mappings.loc[0, field] = invalid
    with pytest.raises(SecUniverseBindingError, match="lineage is incomplete"):
        _plan(tmp_path, mappings=mappings)


def test_valid_lineage_is_accepted_and_stale_mapping_is_rejected(tmp_path):
    plan = _plan(tmp_path / "valid")
    assert plan.issuers[0].security_mapping_proofs[0].source == "security-master-contract-fixture"
    stale = _mappings()
    stale.loc[0, "valid_to"] = "2026-08-24T23:59:59Z"
    with pytest.raises(SecUniverseBindingError, match="stale"):
        _plan(tmp_path / "stale", mappings=stale)
    boundary = _mappings(("issuer-aaa",))
    boundary.loc[0, "valid_to"] = AS_OF.isoformat()
    with pytest.raises(SecUniverseBindingError, match="stale"):
        _plan(tmp_path / "half-open-boundary", ("issuer-aaa",), boundary)
    boundary.loc[0, "valid_to"] = (AS_OF + datetime.timedelta(seconds=1)).isoformat()
    assert _plan(tmp_path / "inside-half-open", ("issuer-aaa",), boundary).issuers


def test_rehashed_semantically_invalid_lineage_is_rejected_by_consumer(tmp_path):
    plan = _plan(tmp_path, ("issuer-aaa",))
    bad_proof = plan.issuers[0].security_mapping_proofs[0].model_copy(update={"source": "null"})
    bad_issuer = plan.issuers[0].model_copy(update={"security_mapping_proofs": (bad_proof,)})
    mutated = plan.model_copy(update={"issuers": (bad_issuer,)})
    forged = mutated.model_copy(update={"plan_hash": typed_hash(mutated.identity_payload())})
    with pytest.raises(ValueError, match="lineage.*placeholder"):
        ingest_governed_universe(plan=forged, source=object())


def test_two_permanent_ids_one_cik_retain_distinct_security_lineage(tmp_path):
    compatible = _mappings()
    compatible["cik"] = "1"
    compatible["source_record_id"] = "shared-record"
    plan = _plan(tmp_path / "compatible", mappings=compatible)
    assert len(plan.issuers) == 1
    assert plan.issuers[0].permanent_ids == ("issuer-aaa", "issuer-bbb")

    conflicting = compatible.copy()
    conflicting.loc[1, "source_record_id"] = "conflicting-record"
    distinct = _plan(tmp_path / "distinct", mappings=conflicting)
    assert tuple(item.source_record_id for item in distinct.issuers[0].security_mapping_proofs) == (
        "shared-record",
        "conflicting-record",
    )

    chronology_conflict = compatible.copy()
    chronology_conflict.loc[1, "valid_from"] = "2021-01-01T00:00:00Z"
    chronology = _plan(tmp_path / "chronology", mappings=chronology_conflict)
    assert len(chronology.issuers[0].security_mapping_proofs) == 2


def test_rehashed_stale_issuer_is_rejected_by_consumer(tmp_path):
    plan = _plan(tmp_path, ("issuer-aaa",))
    stale_proof = plan.issuers[0].security_mapping_proofs[0].model_copy(update={"valid_to": AS_OF})
    stale_issuer = plan.issuers[0].model_copy(update={"security_mapping_proofs": (stale_proof,)})
    mutated = plan.model_copy(update={"issuers": (stale_issuer,)})
    forged = mutated.model_copy(update={"plan_hash": typed_hash(mutated.identity_payload())})
    with pytest.raises(ValueError, match="chronology"):
        ingest_governed_universe(plan=forged, source=object())


def test_reorder_is_deterministic_and_ticker_change_does_not_duplicate_issuer(tmp_path):
    mappings = _mappings().iloc[::-1].reset_index(drop=True)
    first = _plan(tmp_path / "first", mappings=mappings)
    second = _plan(tmp_path / "second", mappings=mappings.iloc[::-1])
    assert first.plan_hash == second.plan_hash
    assert first.issuers == second.issuers
    changed = _universe(tmp_path / "ticker-change", ("issuer-aaa",))
    membership = changed / "universe_membership.csv"
    original = membership.read_text()
    assert "OLD" in original
    mapping = _mappings(("issuer-aaa",))
    plan = build_sec_acquisition_plan_from_unproved_records_for_testing(
        universe_snapshot_dir=changed, security_master_records=mapping, as_of=AS_OF
    )
    assert len(plan.issuers) == 1
    assert plan.issuers[0].permanent_ids == ("issuer-aaa",)

    old_snapshot = _universe(tmp_path / "old-snapshot", ("issuer-aaa",), ("OLD",))
    new_snapshot = _universe(tmp_path / "new-snapshot", ("issuer-aaa",), ("NEW",))
    old_plan = build_sec_acquisition_plan_from_unproved_records_for_testing(
        universe_snapshot_dir=old_snapshot, security_master_records=mapping, as_of=AS_OF
    )
    new_plan = build_sec_acquisition_plan_from_unproved_records_for_testing(
        universe_snapshot_dir=new_snapshot, security_master_records=mapping, as_of=AS_OF
    )
    assert old_plan.issuers == new_plan.issuers
    assert old_plan.eligible_permanent_ids == new_plan.eligible_permanent_ids
    assert len(old_plan.issuers) == len(new_plan.issuers) == 1


def test_governed_builder_rejects_manual_mapping_bypass(tmp_path):
    with pytest.raises(SecUniverseBindingError, match="verified Phase 7B bridge"):
        build_sec_acquisition_plan(
            universe_snapshot_dir=_universe(tmp_path),
            security_master_records=_mappings(),
            as_of=AS_OF,
        )


def test_execution_requests_only_planned_ciks_and_preserves_raw_lineage(tmp_path):
    requested: list[str] = []

    def transport(url, headers, timeout):
        requested.append(url)
        cik = url.split("CIK", 1)[1][:10]
        accession = f"{cik}-26-000001"
        if "/submissions/" in url:
            payload = {
                "filings": {
                    "recent": {
                        "accessionNumber": [accession],
                        "acceptanceDateTime": ["2026-02-01T16:00:00Z"],
                        "filingDate": ["2026-02-01"],
                        "form": ["10-K"],
                    },
                    "files": [],
                }
            }
        else:
            payload = {
                "cik": int(cik),
                "facts": {
                    "us-gaap": {
                        "Assets": {
                            "units": {
                                "USD": [
                                    {
                                        "end": "2025-12-31",
                                        "val": 1,
                                        "accn": accession,
                                        "fy": 2025,
                                        "fp": "FY",
                                        "form": "10-K",
                                        "filed": "2026-02-01",
                                    }
                                ]
                            }
                        }
                    }
                },
            }
        return SecEdgarResponse(json.dumps(payload).encode(), "application/json", final_url=url)

    plan = _plan(tmp_path / "plan", ("issuer-aaa",))
    source = SecEdgarFundamentalsSource(
        "Trading research@example.org",
        RawSnapshotStore(tmp_path / "raw"),
        transport=transport,
        sleeper=lambda _: None,
    )
    with pytest.raises(SecUniverseBindingError, match="embedded Phase 7B proof"):
        ingest_governed_universe(plan=plan, source=source)
    assert requested == []


def test_connector_probes_are_not_production_universe_inputs(tmp_path):
    plan = _plan(tmp_path, ("issuer-aaa",))
    serialized = plan.model_dump_json()
    assert all(probe not in serialized for probe in ("AAPL", "TSLA", "BABA"))
