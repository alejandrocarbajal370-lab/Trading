from __future__ import annotations

import datetime
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from data.connectors.sec_edgar import SecFundamentalsResult
from data.sec_universe_binding import (
    SecAcquisitionPlan,
    build_sec_acquisition_plan,
    ingest_governed_universe,
)
from data.security_master_pit import (
    ARTIFACT_VERSION,
    BITEMPORAL_POLICY_VERSION,
    COVERAGE_MANIFEST_VERSION,
    LISTING_POLICY_VERSION,
    RELATIONSHIP_POLICY_VERSION,
    SEC_BRIDGE_VERSION,
    SYMBOL_IDENTITY_POLICY_VERSION,
    ConstituentRecord,
    CoverageCompleteness,
    PITUniverseArtifact,
    ProviderCoverageManifest,
    ProviderIdentity,
    SecurityIdentityRecord,
    SecurityMasterPITError,
    phase7b_sec_mapping_bridge,
    reconstruct_pit_universe,
    universe_source_records,
)
from governance.canonical import typed_hash
from universe.schedule import UniverseRebalanceSchedule
from universe.snapshots import UniverseSnapshotStore
from universe.validation import UniverseRules, universe_health, validate_universe

UTC = datetime.UTC
AS_OF = datetime.datetime(2020, 6, 1, tzinfo=UTC)
START = datetime.datetime(2010, 1, 1, tzinfo=UTC)
END = datetime.datetime(2021, 1, 1, tzinfo=UTC)
PROVIDER = ProviderIdentity(
    name="synthetic-contract", version="v1", licensing="OPEN_EXTERNAL",
    retention="raw required", state="OPEN_EXTERNAL",
)


def security(pid="sec-1", **updates):
    values = {
        "permanent_id": pid, "issuer_id": "issuer-1", "symbol": "AAA", "exchange": "NYSE",
        "listing_start": START, "listing_end": None, "delisting_status": "ACTIVE",
        "share_class": "A", "security_type": "COMMON_STOCK", "canonical_cik": "0000000001",
        "cik_lineage": "canonical provider field", "source": "master", "source_record_id": f"s-{pid}",
        "available_at": START + datetime.timedelta(days=1), "valid_from": START,
    }
    values.update(updates)
    return SecurityIdentityRecord(**values)


def member(pid="sec-1", **updates):
    values = {
        "universe_id": "IDX", "permanent_id": pid, "entry_at": START,
        "source": "constituents", "source_record_id": f"m-{pid}",
        "available_at": START + datetime.timedelta(days=1), "valid_from": START,
    }
    values.update(updates)
    return ConstituentRecord(**values)


def reconstruct(securities, memberships, as_of=AS_OF, coverage_manifest=None):
    return reconstruct_pit_universe(
        security_records=securities, constituent_records=memberships, universe_id="IDX",
        as_of=as_of, provider=PROVIDER, source_hashes=("a" * 64, "b" * 64),
        runtime_code_fingerprint="git:test", coverage_manifest=coverage_manifest,
    )


def relation(pid, related, kind, **updates):
    relationship_available_at = updates.pop(
        "relationship_available_at", START + datetime.timedelta(days=2)
    )
    return security(
        pid, relationship_type=kind, related_permanent_id=related,
        relationship_available_at=relationship_available_at, **updates,
    )


def observations(ids):
    return pd.DataFrame([{
        "permanent_id": pid, "asset_type": "COMMON_STOCK", "country": "US",
        "region": "North America", "sector": "Technology", "industry": "Software",
        "market_cap": 1_000_000_000, "market_cap_currency": "USD", "average_volume": 1_000_000,
        "average_dollar_volume": 50_000_000, "source_timestamp": "2020-05-30T00:00:00Z",
        "available_at": "2020-05-31T00:00:00Z",
    } for pid in ids])


def snapshot(tmp_path: Path, result):
    source = universe_source_records(result, observations(result.artifact.permanent_identities))
    rules = UniverseRules()
    membership = validate_universe(source, rules=rules, as_of=pd.Timestamp(result.artifact.as_of))
    return UniverseSnapshotStore(tmp_path).save(
        membership, as_of=pd.Timestamp(result.artifact.as_of),
        validation=universe_health(membership, rules=rules), rules=rules,
        schedule=UniverseRebalanceSchedule(), recorded_at=pd.Timestamp(result.artifact.as_of),
    )


def test_listing_state_machine_boundaries_relisting_and_symbology():
    with pytest.raises(ValidationError, match="DELISTED requires"):
        security(delisting_status="DELISTED")
    with pytest.raises(ValidationError, match="listing validity"):
        security(listing_end=START - datetime.timedelta(days=1), delisting_status="DELISTED")
    with pytest.raises(ValidationError, match="ACTIVE cannot"):
        security(listing_end=END)
    first = security(listing_end=END, valid_to=END, delisting_status="DELISTED")
    second = security(
        symbol="BBB", listing_start=END, valid_from=END,
        available_at=END + datetime.timedelta(days=1), source_record_id="s-relist",
    )
    assert reconstruct([second, first], [member()], AS_OF).securities == (first,)
    with pytest.raises(SecurityMasterPITError, match="overlapping conflicting"):
        reconstruct([security(), security(symbol="BBB", source_record_id="s2")], [member()])
    reused = security(
        "sec-2", issuer_id="issuer-2", listing_start=END, valid_from=END,
        available_at=END + datetime.timedelta(days=1), source_record_id="s2",
        canonical_cik="0000000002",
    )
    reconstruct([first, reused], [member()])
    ambiguous = security(
        "sec-2", issuer_id="issuer-2", source_record_id="s2", canonical_cik="0000000002"
    )
    with pytest.raises(SecurityMasterPITError, match="symbology"):
        reconstruct([security(), ambiguous], [member()])
    different_venue = ambiguous.model_copy(update={"exchange": "NASDAQ"})
    reconstruct([security(), different_venue], [member()])


def test_relationship_graph_self_cycles_unknown_future_conflicts_and_valid_dag():
    with pytest.raises(ValidationError, match="self-link"):
        relation("sec-1", "sec-1", "MERGER_PREDECESSOR")
    a = relation("a", "b", "MERGER_PREDECESSOR", symbol="A", source_record_id="a")
    b = relation("b", "a", "MERGER_SUCCESSOR", symbol="B", source_record_id="b")
    with pytest.raises(SecurityMasterPITError, match="cycle"):
        reconstruct([a, b], [member("a")])
    c = relation("c", "a", "SPINOFF_CHILD", symbol="C", source_record_id="c")
    a3 = a.model_copy(update={"related_permanent_id": "b"})
    b3 = b.model_copy(update={"related_permanent_id": "c"})
    with pytest.raises(SecurityMasterPITError, match="cycle"):
        reconstruct([a3, b3, c], [member("a")])
    with pytest.raises(SecurityMasterPITError, match="unknown"):
        reconstruct([relation("a", "missing", "MERGER_PREDECESSOR", symbol="A")], [member("a")])
    future = relation(
        "a", "b", "MERGER_PREDECESSOR", symbol="A",
        relationship_available_at=AS_OF + datetime.timedelta(days=1),
    )
    target = security("b", symbol="B", source_record_id="b")
    with pytest.raises(SecurityMasterPITError, match="future structural"):
        reconstruct([future, target], [member("a")])
    conflicting = a.model_copy(update={"relationship_type": "SPINOFF_PARENT"})
    with pytest.raises(SecurityMasterPITError, match="conflicting"):
        reconstruct([a, conflicting, target], [member("a")])
    valid = reconstruct([a, target], [member("a")])
    assert valid.artifact.relationship_hash


def _coverage(**updates):
    values = {
        "provider": "synthetic", "dataset": "members", "dataset_version": "v1",
        "universe_scope": "IDX", "temporal_coverage_from": START,
        "temporal_coverage_to": END, "sequence_numbers": (1, 2),
        "snapshot_identities": ("snap-1", "snap-2"), "raw_source_hashes": ("a" * 64,),
        "evidence_hashes": ("b" * 64,),
        "completeness_state": CoverageCompleteness.VERIFIED_WITHIN_DECLARED_SCOPE,
        "correction_policy": "append-only", "revision_policy": "supersedes explicit record",
        "licensing_state": "OPEN_EXTERNAL", "retention_state": "raw required",
        "available_at": END, "acquired_at": END, "current_only": False,
    }
    values.update(updates)
    draft = ProviderCoverageManifest.model_construct(**values, manifest_hash="0" * 64)
    return ProviderCoverageManifest(**values, manifest_hash=typed_hash(draft.identity_payload()))


def test_coverage_manifest_requires_evidence_gap_free_history_and_hash_integrity():
    assert _coverage().ready_within_declared_scope
    for updates in (
        {"evidence_hashes": ()}, {"sequence_numbers": (1, 3)}, {"current_only": True}
    ):
        with pytest.raises(ValidationError, match="verified coverage"):
            _coverage(**updates)
    manifest = _coverage(completeness_state=CoverageCompleteness.PARTIAL, evidence_hashes=())
    assert not manifest.ready_within_declared_scope
    payload = manifest.model_dump(mode="python")
    payload["raw_source_hashes"] = ("c" * 64,)
    with pytest.raises(ValidationError, match="hash mismatch"):
        ProviderCoverageManifest.model_validate(payload)


def test_bitemporal_late_correction_never_rewrites_prior_snapshot():
    original = security()
    correction = security(
        symbol="NEW", source_record_id="correction", available_at=END,
        valid_from=START, supersedes_source_record_id="s-sec-1", revision_id="R2",
    )
    before = reconstruct([original, correction], [member()], AS_OF)
    assert before.securities[0].symbol == "AAA"
    after = reconstruct([original, correction], [member()], END + datetime.timedelta(days=1))
    assert after.securities[0].symbol == "NEW"


@pytest.mark.parametrize(
    "field", ["membership_hash", "security_master_hash", "cik_mapping_hash", "relationship_hash",
              "as_of", "source_hashes", "listing_policy_version"]
)
def test_outer_artifact_mutations_without_reseal_reject(field):
    result = reconstruct([security()], [member()])
    payload = result.artifact.model_dump(mode="python")
    payload[field] = (
        AS_OF + datetime.timedelta(days=1) if field == "as_of" else
        ("c" * 64,) if field == "source_hashes" else
        "listing-state-half-open-v0" if field == "listing_policy_version" else "f" * 64
    )
    with pytest.raises(ValidationError):
        PITUniverseArtifact.model_validate(payload)


def test_real_phase7b_bridge_e2e_multi_class_one_fetch_and_mutations(tmp_path):
    first = security()
    second = security(
        "sec-2", symbol="AAB", share_class="B", source_record_id="s-sec-2",
    )
    result = reconstruct([second, first], [member("sec-2"), member("sec-1")])
    bridge = phase7b_sec_mapping_bridge(result)
    plan = build_sec_acquisition_plan(
        universe_snapshot_dir=snapshot(tmp_path / "universe", result),
        security_master_records=bridge, as_of=AS_OF,
    )
    assert plan.phase7b_artifact_hash == result.artifact.artifact_hash
    assert plan.phase7b_bridge_hash == bridge.bridge_hash
    assert plan.issuers[0].permanent_ids == ("sec-1", "sec-2")

    class MockSource:
        def __init__(self):
            self.calls = []

        def fetch(self, *, cik_by_symbol, as_of):
            self.calls.append((cik_by_symbol, as_of))
            return SecFundamentalsResult(pd.DataFrame(), (), {})

    source = MockSource()
    ingested = ingest_governed_universe(plan=plan, source=source)
    assert len(source.calls) == 1
    assert source.calls[0][0] == {"sec-1": "0000000001"}
    assert ingested.plan.issuers[0].permanent_ids == ("sec-1", "sec-2")
    stale = bridge.model_copy(update={"artifact_as_of": AS_OF + datetime.timedelta(days=1)})
    with pytest.raises(Exception, match="hash|stale|as_of"):
        build_sec_acquisition_plan(
            universe_snapshot_dir=snapshot(tmp_path / "stale", result),
            security_master_records=stale, as_of=AS_OF,
        )
    payload = plan.model_dump(mode="python")
    payload["phase7b_bridge_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        SecAcquisitionPlan.model_validate(payload)


def test_policy_inventory_is_frozen_and_reorder_of_both_inputs_is_stable():
    assert (
        ARTIFACT_VERSION, SEC_BRIDGE_VERSION, LISTING_POLICY_VERSION,
        SYMBOL_IDENTITY_POLICY_VERSION, RELATIONSHIP_POLICY_VERSION,
        BITEMPORAL_POLICY_VERSION, COVERAGE_MANIFEST_VERSION,
    ) == (
        "security-master-constituents-artifact-v2", "phase7b-sec-mapping-bridge-v1",
        "listing-state-half-open-v1", "symbology-ticker-venue-class-type-v1",
        "structural-lineage-dag-v1", "effective-knowledge-correction-v1",
        "historical-provider-coverage-v1",
    )
    securities = [security(), security("sec-2", symbol="BBB", canonical_cik="0000000002")]
    members = [member(), member("sec-2")]
    one = reconstruct(securities, members)
    two = reconstruct(list(reversed(securities)), list(reversed(members)))
    assert one.artifact.artifact_hash == two.artifact.artifact_hash
    mutated = replace(one, securities=(security(symbol="MUTATED"), one.securities[1]))
    with pytest.raises(SecurityMasterPITError, match="stale"):
        phase7b_sec_mapping_bridge(mutated)


def test_recomputed_inner_hash_with_stale_outer_seal_rejects():
    result = reconstruct([security()], [member()])
    mutated_security = security(issuer_id="mutated-issuer")
    payload = result.artifact.model_dump(mode="python")
    payload["security_master_hash"] = typed_hash(
        [mutated_security.model_dump(mode="python")]
    )
    payload["cik_mapping_hash"] = typed_hash([
        {
            "permanent_id": mutated_security.permanent_id,
            "issuer_id": mutated_security.issuer_id,
            "canonical_cik": mutated_security.canonical_cik,
            "cik_lineage": mutated_security.cik_lineage,
            "source": mutated_security.source,
            "source_record_id": mutated_security.source_record_id,
            "available_at": mutated_security.available_at,
            "valid_from": mutated_security.valid_from,
            "valid_to": mutated_security.valid_to,
        }
    ])
    with pytest.raises(ValidationError, match="artifact hash mismatch"):
        PITUniverseArtifact.model_validate(payload)
