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
    CoverageEvidenceEntry,
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
    name="synthetic-contract",
    version="v1",
    licensing="OPEN_EXTERNAL",
    retention="raw required",
    state="OPEN_EXTERNAL",
)


def security(pid="sec-1", **updates):
    values = {
        "permanent_id": pid,
        "issuer_id": "issuer-1",
        "symbol": "AAA",
        "exchange": "NYSE",
        "listing_start": START,
        "listing_end": None,
        "delisting_status": "ACTIVE",
        "share_class": "A",
        "security_type": "COMMON_STOCK",
        "canonical_cik": "0000000001",
        "cik_lineage": "canonical provider field",
        "source": "master",
        "source_record_id": f"s-{pid}",
        "available_at": START + datetime.timedelta(days=1),
        "valid_from": START,
    }
    values.update(updates)
    return SecurityIdentityRecord(**values)


def member(pid="sec-1", **updates):
    values = {
        "universe_id": "IDX",
        "permanent_id": pid,
        "entry_at": START,
        "source": "constituents",
        "source_record_id": f"m-{pid}",
        "available_at": START + datetime.timedelta(days=1),
        "valid_from": START,
    }
    values.update(updates)
    return ConstituentRecord(**values)


def reconstruct(securities, memberships, as_of=AS_OF, coverage_manifest=None):
    return reconstruct_pit_universe(
        security_records=securities,
        constituent_records=memberships,
        universe_id="IDX",
        as_of=as_of,
        provider=PROVIDER,
        source_hashes=("a" * 64, "b" * 64),
        runtime_code_fingerprint="git:test",
        coverage_manifest=coverage_manifest,
    )


def relation(pid, related, kind, **updates):
    relationship_available_at = updates.pop(
        "relationship_available_at", START + datetime.timedelta(days=2)
    )
    relationship_effective_at = updates.pop("relationship_effective_at", AS_OF)
    return security(
        pid,
        relationship_type=kind,
        related_permanent_id=related,
        relationship_available_at=relationship_available_at,
        relationship_effective_at=relationship_effective_at,
        **updates,
    )


def observations(ids):
    return pd.DataFrame(
        [
            {
                "permanent_id": pid,
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Technology",
                "industry": "Software",
                "market_cap": 1_000_000_000,
                "market_cap_currency": "USD",
                "average_volume": 1_000_000,
                "average_dollar_volume": 50_000_000,
                "source_timestamp": "2020-05-30T00:00:00Z",
                "available_at": "2020-05-31T00:00:00Z",
            }
            for pid in ids
        ]
    )


def snapshot(tmp_path: Path, result):
    source = universe_source_records(result, observations(result.artifact.permanent_identities))
    rules = UniverseRules()
    membership = validate_universe(source, rules=rules, as_of=pd.Timestamp(result.artifact.as_of))
    return UniverseSnapshotStore(tmp_path).save(
        membership,
        as_of=pd.Timestamp(result.artifact.as_of),
        validation=universe_health(membership, rules=rules),
        rules=rules,
        schedule=UniverseRebalanceSchedule(),
        recorded_at=pd.Timestamp(result.artifact.as_of),
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
        symbol="BBB",
        listing_start=END,
        valid_from=END,
        available_at=END + datetime.timedelta(days=1),
        source_record_id="s-relist",
    )
    assert reconstruct([second, first], [member()], AS_OF).securities == (first,)
    with pytest.raises(SecurityMasterPITError, match="revision identity|overlapping conflicting"):
        reconstruct([security(), security(symbol="BBB", source_record_id="s2")], [member()])
    reused = security(
        "sec-2",
        issuer_id="issuer-2",
        listing_start=END,
        valid_from=END,
        available_at=END + datetime.timedelta(days=1),
        source_record_id="s2",
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
    assert security(symbol="  aaa ", exchange="nyse").symbology_key[:2] == ("AAA", "NYSE")
    assert security(symbol="ＡＡＡ").symbol == "AAA"
    with pytest.raises(ValidationError, match="ASCII"):
        security(symbol="ΑΑΑ")


def test_relationship_graph_self_cycles_unknown_future_conflicts_and_valid_dag():
    with pytest.raises(ValidationError, match="self-link"):
        relation("sec-1", "sec-1", "MERGER_PREDECESSOR")
    a = relation("a", "b", "MERGER_PREDECESSOR", symbol="A", source_record_id="a")
    b = relation("b", "a", "MERGER_SUCCESSOR", symbol="B", source_record_id="b")
    with pytest.raises(SecurityMasterPITError, match="unknown"):
        reconstruct([relation("a", "missing", "MERGER_PREDECESSOR", symbol="A")], [member("a")])
    future = relation(
        "a",
        "b",
        "MERGER_PREDECESSOR",
        symbol="A",
        relationship_available_at=AS_OF + datetime.timedelta(days=1),
    )
    target = security("b", symbol="B", source_record_id="b")
    with pytest.raises(SecurityMasterPITError, match="future structural"):
        reconstruct([future, target], [member("a")])
    with pytest.raises(SecurityMasterPITError, match="paired"):
        reconstruct([a, target], [member("a")])
    valid = reconstruct([a, b], [member("a")])
    assert valid.artifact.relationship_hash


def _coverage(**updates):
    entries = (
        CoverageEvidenceEntry(
            sequence_number=1,
            snapshot_identity="snap-1",
            raw_source_hash="a" * 64,
            evidence_hash="b" * 64,
            effective_from=START,
            effective_to=datetime.datetime(2015, 1, 1, tzinfo=UTC),
            available_at=END,
            acquired_at=END,
            source="licensed",
            provider_identity="synthetic:v1",
        ),
        CoverageEvidenceEntry(
            sequence_number=2,
            snapshot_identity="snap-2",
            raw_source_hash="c" * 64,
            evidence_hash="d" * 64,
            effective_from=datetime.datetime(2015, 1, 1, tzinfo=UTC),
            effective_to=END,
            available_at=END,
            acquired_at=END,
            source="licensed",
            provider_identity="synthetic:v1",
        ),
    )
    values = {
        "provider": "synthetic",
        "dataset": "members",
        "dataset_version": "v1",
        "universe_scope": "IDX",
        "temporal_coverage_from": START,
        "temporal_coverage_to": END,
        "entries": entries,
        "completeness_state": CoverageCompleteness.VERIFIED_WITHIN_DECLARED_SCOPE,
        "correction_policy": "append-only",
        "revision_policy": "supersedes explicit record",
        "licensing_state": "OPEN_EXTERNAL",
        "retention_state": "raw required",
        "available_at": END,
        "acquired_at": END,
        "current_only": False,
    }
    values.update(updates)
    draft = ProviderCoverageManifest.model_construct(**values, manifest_hash="0" * 64)
    return ProviderCoverageManifest(**values, manifest_hash=typed_hash(draft.identity_payload()))


def test_coverage_manifest_requires_evidence_gap_free_history_and_hash_integrity():
    assert _coverage().ready_within_declared_scope
    for updates in (
        {"entries": ()},
        {
            "entries": tuple(
                item.model_copy(update={"sequence_number": number})
                for item, number in zip(_coverage().entries, (1, 3))
            )
        },
        {"current_only": True},
    ):
        with pytest.raises(ValidationError, match="verified coverage"):
            _coverage(**updates)
    manifest = _coverage(completeness_state=CoverageCompleteness.PARTIAL, entries=())
    assert not manifest.ready_within_declared_scope
    payload = _coverage().model_dump(mode="python")
    payload["entries"][0]["raw_source_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        ProviderCoverageManifest.model_validate(payload)


def test_bitemporal_late_correction_never_rewrites_prior_snapshot():
    original = security()
    correction = security(
        symbol="NEW",
        source_record_id="correction",
        available_at=END,
        valid_from=START,
        supersedes_source_record_id="s-sec-1",
        revision_id="R2",
    )
    before = reconstruct([original, correction], [member()], AS_OF)
    assert before.securities[0].symbol == "AAA"
    after = reconstruct([original, correction], [member()], END + datetime.timedelta(days=1))
    assert after.securities[0].symbol == "NEW"
    third = security(
        symbol="LATEST",
        source_record_id="correction-3",
        available_at=END + datetime.timedelta(days=2),
        valid_from=START,
        supersedes_source_record_id="correction",
        revision_id="R3",
    )
    latest = reconstruct(
        [third, original, correction], [member()], END + datetime.timedelta(days=3)
    )
    assert latest.securities[0].symbol == "LATEST"


def test_constituent_revision_chain_is_pit_and_hashes_full_known_chain():
    r1 = member()
    r2 = member(
        source_record_id="m-r2",
        revision_id="R2",
        supersedes_source_record_id="m-sec-1",
        available_at=END,
        exit_at=END + datetime.timedelta(days=30),
    )
    r3 = member(
        source_record_id="m-r3",
        revision_id="R3",
        supersedes_source_record_id="m-r2",
        available_at=END + datetime.timedelta(days=10),
        exit_at=END + datetime.timedelta(days=60),
    )
    before = reconstruct([security()], [r3, r1, r2], AS_OF)
    at_r2 = reconstruct([security()], [r2, r1, r3], END)
    after_r3 = reconstruct([security()], [r1, r2, r3], END + datetime.timedelta(days=10))
    assert before.memberships == (r1,)
    assert at_r2.memberships == (r2,)
    assert after_r3.memberships == (r3,)
    assert len(after_r3.membership_proof_records) == 3
    assert (
        len(
            {
                before.artifact.membership_hash,
                at_r2.artifact.membership_hash,
                after_r3.artifact.membership_hash,
            }
        )
        == 3
    )


def test_constituent_revision_missing_predecessor_and_fork_reject():
    missing = member(
        source_record_id="m-r2",
        revision_id="R2",
        supersedes_source_record_id="missing",
        available_at=END,
    )
    with pytest.raises(SecurityMasterPITError, match="missing predecessor"):
        reconstruct([security()], [member(), missing])
    r2 = missing.model_copy(update={"supersedes_source_record_id": "m-sec-1"})
    fork = member(
        source_record_id="m-fork",
        revision_id="R3",
        supersedes_source_record_id="m-sec-1",
        available_at=END + datetime.timedelta(days=1),
    )
    with pytest.raises(SecurityMasterPITError, match="fork"):
        reconstruct([security()], [member(), r2, fork])


def test_exact_duplicate_rows_reject_before_reorder_canonicalization():
    with pytest.raises(SecurityMasterPITError, match="exact duplicate"):
        reconstruct([security(), security()], [member()])
    with pytest.raises(SecurityMasterPITError, match="exact duplicate"):
        reconstruct([security()], [member(), member()])


@pytest.mark.parametrize(
    "field",
    [
        "membership_hash",
        "security_master_hash",
        "cik_mapping_hash",
        "relationship_hash",
        "as_of",
        "source_hashes",
        "listing_policy_version",
    ],
)
def test_outer_artifact_mutations_without_reseal_reject(field):
    result = reconstruct([security()], [member()])
    payload = result.artifact.model_dump(mode="python")
    payload[field] = (
        AS_OF + datetime.timedelta(days=1)
        if field == "as_of"
        else ("c" * 64,)
        if field == "source_hashes"
        else "listing-state-half-open-v0"
        if field == "listing_policy_version"
        else "f" * 64
    )
    with pytest.raises(ValidationError):
        PITUniverseArtifact.model_validate(payload)


def test_real_phase7b_bridge_e2e_multi_class_one_fetch_and_mutations(tmp_path):
    first = security()
    second = security(
        "sec-2",
        symbol="AAB",
        share_class="B",
        source_record_id="s-sec-2",
    )
    result = reconstruct([second, first], [member("sec-2"), member("sec-1")])
    bridge = phase7b_sec_mapping_bridge(result)
    plan = build_sec_acquisition_plan(
        universe_snapshot_dir=snapshot(tmp_path / "universe", result),
        security_master_records=bridge,
        as_of=AS_OF,
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
    forged_artifact = bridge.proof.artifact.model_copy(
        update={"as_of": AS_OF + datetime.timedelta(days=1)}
    )
    stale = bridge.model_copy(
        update={"proof": bridge.proof.model_copy(update={"artifact": forged_artifact})}
    )
    with pytest.raises(Exception, match="hash|stale|as_of"):
        build_sec_acquisition_plan(
            universe_snapshot_dir=snapshot(tmp_path / "stale", result),
            security_master_records=stale,
            as_of=AS_OF,
        )
    payload = plan.model_dump(mode="python")
    payload["phase7b_bridge_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        SecAcquisitionPlan.model_validate(payload)


def test_fully_resealed_forged_cik_with_stale_artifact_commitment_rejects(tmp_path):
    result = reconstruct([security()], [member()])
    bridge = phase7b_sec_mapping_bridge(result)
    payload = bridge.model_dump(mode="python")
    payload["records"][0]["canonical_cik"] = "0000000999"
    payload["proof"]["security_records"][0]["canonical_cik"] = "0000000999"
    payload["proof"]["security_revision_records"][0]["canonical_cik"] = "0000000999"
    payload["bridge_hash"] = typed_hash(
        {key: value for key, value in payload.items() if key != "bridge_hash"}
    )
    with pytest.raises(ValidationError, match="commitment mismatch"):
        type(bridge).model_validate(payload)

    coherent = reconstruct(
        [security(canonical_cik="0000000999", cik_lineage="corrected-provider-proof")],
        [member()],
    )
    coherent_bridge = phase7b_sec_mapping_bridge(coherent)
    plan = build_sec_acquisition_plan(
        universe_snapshot_dir=snapshot(tmp_path / "coherent", coherent),
        security_master_records=coherent_bridge,
        as_of=AS_OF,
    )
    assert plan.issuers[0].canonical_cik == "0000000999"
    assert coherent_bridge.bridge_hash != bridge.bridge_hash


def test_policy_inventory_is_frozen_and_reorder_of_both_inputs_is_stable():
    assert (
        ARTIFACT_VERSION,
        SEC_BRIDGE_VERSION,
        LISTING_POLICY_VERSION,
        SYMBOL_IDENTITY_POLICY_VERSION,
        RELATIONSHIP_POLICY_VERSION,
        BITEMPORAL_POLICY_VERSION,
        COVERAGE_MANIFEST_VERSION,
    ) == (
        "security-master-constituents-artifact-v3",
        "phase7b-sec-mapping-bridge-v2",
        "listing-state-half-open-v1",
        "us-symbology-nfkc-uppercase-ascii-v2",
        "structural-lineage-paired-semantics-v2",
        "effective-knowledge-supersession-v2",
        "historical-provider-coverage-v2",
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
    payload["security_master_hash"] = typed_hash([mutated_security.model_dump(mode="python")])
    payload["cik_mapping_hash"] = typed_hash(
        [
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
        ]
    )
    with pytest.raises(ValidationError, match="artifact hash mismatch"):
        PITUniverseArtifact.model_validate(payload)
