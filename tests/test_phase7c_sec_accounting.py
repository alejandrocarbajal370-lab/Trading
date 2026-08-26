from __future__ import annotations

import datetime
import hashlib
import json

import pandas as pd
import pytest

from data.connectors.sec_edgar import SecEdgarFundamentalsSource, SecEdgarResponse
from data.raw_snapshots import RawSnapshotStore
from data.sec_universe_binding import build_sec_acquisition_plan_from_unproved_records_for_testing
from fundamentals.sec_accounting import (
    DEFAULT_SEC_MAPPING_REGISTRY,
    DEFAULT_SEC_UNIT_REGISTRY,
    SecAccountingBindingError,
    SecConceptMapping,
    SecMappingRegistry,
    SecUnitRegistry,
    bind_sec_to_accounting,
)
from universe.schedule import UniverseRebalanceSchedule
from universe.snapshots import UniverseSnapshotStore
from universe.validation import UniverseRules, validate_universe

AS_OF = datetime.datetime(2026, 8, 25, 20, tzinfo=datetime.UTC)
ACCESSION = "0000000001-26-000001"


def _plan(tmp_path, *, two_classes=False):
    ids = ("perm-a", "perm-b") if two_classes else ("perm-a",)
    members = pd.DataFrame([
        {"symbol": f"S{index}", "permanent_id": permanent_id, "exchange": "NYSE",
         "asset_type": "COMMON_STOCK", "country": "US", "region": "North America",
         "sector": "Technology", "industry": "Software", "market_cap": 1_000_000_000,
         "market_cap_currency": "USD", "average_volume": 1_000_000,
         "average_dollar_volume": 50_000_000, "listing_date": "2010-01-01",
         "source": "fixture", "source_timestamp": "2026-08-25T18:00:00Z",
         "available_at": "2026-08-25T19:00:00Z"}
        for index, permanent_id in enumerate(ids)
    ])
    membership = validate_universe(members, rules=UniverseRules(), as_of=pd.Timestamp(AS_OF))
    snapshot = UniverseSnapshotStore(tmp_path / "universe").save(
        membership, as_of=pd.Timestamp(AS_OF), validation={"status": "PASS"},
        rules=UniverseRules(), schedule=UniverseRebalanceSchedule(),
        recorded_at=pd.Timestamp(AS_OF),
    )
    mappings = pd.DataFrame([
        {"permanent_id": permanent_id, "cik": "1", "valid_from": "2020-01-01T00:00:00Z",
         "valid_to": None, "available_at": "2020-01-02T00:00:00Z", "source": "fixture",
         "source_record_id": f"record-{index}"}
        for index, permanent_id in enumerate(ids)
    ])
    return build_sec_acquisition_plan_from_unproved_records_for_testing(
        universe_snapshot_dir=snapshot, security_master_records=mappings, as_of=AS_OF)


def _result(tmp_path, observations, *, accepted="2026-02-01T16:00:00Z"):
    accessions = []
    accepted_times = []
    forms = []
    for _, _, observation in observations:
        accession = observation.get("accn", ACCESSION)
        if accession not in accessions:
            accessions.append(accession)
            accepted_times.append(observation.get("accepted", accepted))
            forms.append(observation.get("form", "10-K"))
    submissions = {"filings": {"recent": {
        "accessionNumber": accessions, "acceptanceDateTime": accepted_times,
        "filingDate": ["2026-02-01"] * len(accessions), "form": forms}, "files": []}}
    facts = {"cik": 1, "facts": {"us-gaap": {}}}
    for concept, unit, observation in observations:
        facts["facts"]["us-gaap"].setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append({
            "start": observation.get("start"), "end": observation["end"],
            "val": observation.get("val", 100), "accn": observation.get("accn", ACCESSION),
            "fy": observation.get("fy", 2025), "fp": observation.get("fp", "FY"),
            "form": observation.get("form", "10-K"), "filed": "2026-02-01",
            "frame": observation.get("frame", "CY2025")})
    def transport(url, headers, timeout):
        payload = submissions if "/submissions/" in url else facts
        return SecEdgarResponse(json.dumps(payload).encode(), "application/json")
    source = SecEdgarFundamentalsSource(
        user_agent="Phase7C research@example.org", raw_store=RawSnapshotStore(tmp_path / "raw"),
        transport=transport)
    return source.fetch(cik_by_symbol={"ANY": "1"}, as_of=AS_OF)


def _revenue(val=100, **changes):
    observation = {"start": "2025-01-01", "end": "2025-12-31", "val": val,
                   "fp": "FY", "frame": "CY2025"}
    observation.update(changes)
    return ("Revenues", "USD", observation)


def test_sec_to_accounting_is_issuer_level_sealed_and_confidence_open(tmp_path):
    result = bind_sec_to_accounting(_result(tmp_path, [_revenue()]), plan=_plan(tmp_path, two_classes=True), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))
    assert result.mapped_metrics == ("revenue",)
    assert result.readiness_state == "ACCOUNTING_BOUND_QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert len(result.accounting.frame) == 1
    row = result.accounting.frame.iloc[0]
    assert json.loads(row["applicable_permanent_ids"]) == ["perm-a", "perm-b"]
    assert pd.isna(row["data_confidence"]) and pd.isna(row["mapping_confidence"])


def test_unregistered_custom_or_alias_is_unmapped_never_guessed(tmp_path):
    sec = _result(tmp_path, [_revenue(), ("RevenueFromContractWithCustomerCustom", "USD", _revenue()[2])])
    bound = bind_sec_to_accounting(sec, plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))
    assert "us-gaap:RevenueFromContractWithCustomerCustom" in bound.unmapped_concepts
    assert len(bound.accounting.frame) == 1


def test_preregistered_standard_revenue_alias_is_allowed(tmp_path):
    observation = _revenue()[2]
    sec = _result(
        tmp_path,
        [("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", observation)],
    )
    bound = bind_sec_to_accounting(sec, plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))
    assert bound.mapped_metrics == ("revenue",)


@pytest.mark.parametrize("column,value,match", [
    ("unit", "SHARES", "reconstruct"),
    ("period_type", "instant", "reconstruct"),
    ("fiscal_period_start", "2025-12-31", "reconstruct"),
    ("available_at", pd.Timestamp("2026-08-26T00:00:00Z"), "reconstruct"),
    ("accession", "0000000001-26-999999", "reconstruct"),
    ("form", "10-Q", "reconstruct"),
    ("raw_snapshot_sha256", "0" * 64, "reconstruct"),
])
def test_semantic_and_proof_mutations_fail_closed(tmp_path, column, value, match):
    sec = _result(tmp_path, [_revenue()])
    sec.facts.loc[:, column] = value
    with pytest.raises(SecAccountingBindingError, match=match):
        bind_sec_to_accounting(sec, plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))


def test_registry_mutation_even_resealed_requires_explicit_equivalence(tmp_path):
    payload = DEFAULT_SEC_MAPPING_REGISTRY.model_dump(mode="python")
    payload["mappings"] = tuple(payload["mappings"]) + ({
        "taxonomy": "us-gaap", "concept": "ZCustomRevenue", "canonical_metric": "revenue",
        "period_type": "duration", "unit_family": "currency", "sign": "as_reported"},)
    stale_mappings = tuple(SecConceptMapping.model_validate(item) for item in payload["mappings"])
    stale = SecMappingRegistry.model_construct(
        mappings=stale_mappings,
        registry_hash=DEFAULT_SEC_MAPPING_REGISTRY.registry_hash,
        version=DEFAULT_SEC_MAPPING_REGISTRY.version,
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        bind_sec_to_accounting(_result(tmp_path, [_revenue()]), plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"), registry=stale)
    canonical = tuple(SecConceptMapping.model_validate(item) for item in sorted(payload["mappings"], key=lambda x: (x["taxonomy"], x["concept"])))
    body = {"version": payload["version"], "mappings": [item.model_dump(mode="json") for item in canonical]}
    registry_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    explicit = SecMappingRegistry(mappings=canonical, registry_hash=registry_hash)
    assert explicit.registry_hash != DEFAULT_SEC_MAPPING_REGISTRY.registry_hash


def test_multiple_frames_for_same_accession_are_ambiguous(tmp_path):
    with pytest.raises(SecAccountingBindingError, match="ambiguous SEC"):
        bind_sec_to_accounting(
            _result(tmp_path, [_revenue(frame="CY2025"), _revenue(frame="CY2025_ALT")]),
            plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))


def test_non_calendar_fy_preserved_and_late_amendment_is_pit(tmp_path):
    first = _revenue(start="2024-10-01", end="2025-09-30", frame="CY2025")
    sec = _result(tmp_path, [first])
    bound = bind_sec_to_accounting(sec, plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))
    assert bound.accounting.frame.iloc[0]["fiscal_period_start"] == datetime.date(2024, 10, 1)
    before = bound.accounting.snapshot(cutoff=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC))
    assert before.iloc[0]["value"] == 100


def test_sec_accounting_snapshot_before_and_after_amendment(tmp_path):
    amendment = _revenue(105, accn="0000000001-26-000002", form="10-K/A", accepted="2026-07-01T16:00:00Z")
    sec = _result(tmp_path, [_revenue(100), amendment])
    bound = bind_sec_to_accounting(sec, plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))
    before = bound.accounting.snapshot(
        cutoff=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC))
    after = bound.accounting.snapshot(cutoff=AS_OF)
    assert before.iloc[0]["value"] == 100
    assert before.iloc[0]["revision"] == 0
    assert after.iloc[0]["value"] == 105
    assert after.iloc[0]["revision"] == 1


def test_currency_is_preserved_and_qvm_remains_blocked_without_fx(tmp_path):
    cny = list(_revenue())
    cny[1] = "CNY"
    bound = bind_sec_to_accounting(_result(tmp_path, [tuple(cny)]), plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"))
    assert bound.accounting.frame.iloc[0]["unit"] == "CNY"
    assert bound.readiness_state.endswith("QVM_NOT_READY")


@pytest.mark.parametrize("unit", ["ABC", "SHARES", "PURE", "USD/SHARES", " USD "])
def test_currency_registry_rejects_shape_only_and_other_unit_families(tmp_path, unit):
    revenue = list(_revenue())
    revenue[1] = unit
    with pytest.raises(SecAccountingBindingError, match="unit family"):
        bind_sec_to_accounting(
            _result(tmp_path, [tuple(revenue)]), plan=_plan(tmp_path), as_of=AS_OF,
            raw_store=RawSnapshotStore(tmp_path / "raw"),
        )


@pytest.mark.parametrize("form,fp,start,end,accepted", [
    ("10-Q", "FY", "2025-01-01", "2025-12-31", "2026-02-01T16:00:00Z"),
    ("6-K", "FY", "2025-01-01", "2025-12-31", "2026-02-01T16:00:00Z"),
])
def test_form_period_policy_rejects_unsupported_combinations(tmp_path, form, fp, start, end, accepted):
    with pytest.raises(SecAccountingBindingError, match="form|annual|semantics"):
        bind_sec_to_accounting(
            _result(tmp_path, [_revenue(form=form, fp=fp, start=start, end=end, accepted=accepted)]),
            plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"),
        )


@pytest.mark.parametrize("form,fp,start,end", [
    ("10-K", "FY", "2025-01-01", "2025-12-31"),
    ("20-F", "FY", "2025-01-01", "2025-12-31"),
    ("10-Q", "Q1", "2025-01-01", "2025-03-31"),
    ("10-Q", "Q2", "2025-04-01", "2025-06-30"),
    ("10-Q", "Q3", "2025-07-01", "2025-09-30"),
])
def test_form_period_policy_accepts_explicit_supported_combinations(tmp_path, form, fp, start, end):
    bound = bind_sec_to_accounting(
        _result(tmp_path, [_revenue(form=form, fp=fp, start=start, end=end)]),
        plan=_plan(tmp_path), as_of=AS_OF, raw_store=RawSnapshotStore(tmp_path / "raw"),
    )
    assert bound.mapped_metrics == ("revenue",)


def test_nonexistent_resealed_manifest_is_rejected(tmp_path):
    sec = _result(tmp_path, [_revenue()])
    declared = sec.raw_manifests[0]
    forged = declared.model_copy(update={"acquisition_id": "f" * 32, "sha256": "a" * 64})
    object.__setattr__(sec, "raw_manifests", (forged, *sec.raw_manifests[1:]))
    with pytest.raises(SecAccountingBindingError, match="physically verifiable"):
        bind_sec_to_accounting(
            sec, plan=_plan(tmp_path), as_of=AS_OF,
            raw_store=RawSnapshotStore(tmp_path / "raw"),
        )


def test_tampered_raw_payload_is_rejected(tmp_path):
    sec = _result(tmp_path, [_revenue()])
    manifest = next(item for item in sec.raw_manifests if item.resource.startswith("companyfacts:"))
    event = tmp_path / "raw" / manifest.provider / "acquisitions" / f"{manifest.acquisition_id}.json"
    payload = (event.parent / manifest.payload_file).resolve()
    payload.write_bytes(payload.read_bytes() + b" ")
    with pytest.raises(SecAccountingBindingError, match="physically verifiable"):
        bind_sec_to_accounting(
            sec, plan=_plan(tmp_path), as_of=AS_OF,
            raw_store=RawSnapshotStore(tmp_path / "raw"),
        )


def test_coherent_verified_raw_change_creates_new_proof_identity(tmp_path):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first = bind_sec_to_accounting(
        _result(first_dir, [_revenue(100)]), plan=_plan(first_dir), as_of=AS_OF,
        raw_store=RawSnapshotStore(first_dir / "raw"),
    )
    second = bind_sec_to_accounting(
        _result(second_dir, [_revenue(101)]), plan=_plan(second_dir), as_of=AS_OF,
        raw_store=RawSnapshotStore(second_dir / "raw"),
    )
    assert first.raw_proof.proof_hash != second.raw_proof.proof_hash
    assert first.accounting.metadata.canonical_id != second.accounting.metadata.canonical_id


def test_currency_registry_mutation_with_stale_hash_is_rejected(tmp_path):
    stale = SecUnitRegistry.model_construct(
        version=DEFAULT_SEC_UNIT_REGISTRY.version,
        currencies=tuple(sorted((*DEFAULT_SEC_UNIT_REGISTRY.currencies, "AUD"))),
        registry_hash=DEFAULT_SEC_UNIT_REGISTRY.registry_hash,
    )
    with pytest.raises(ValueError, match="currency registry hash mismatch"):
        bind_sec_to_accounting(
            _result(tmp_path, [_revenue()]), plan=_plan(tmp_path), as_of=AS_OF,
            raw_store=RawSnapshotStore(tmp_path / "raw"), unit_registry=stale,
        )


def test_manifest_resource_or_cik_relabel_is_rejected(tmp_path):
    sec = _result(tmp_path, [_revenue()])
    declared = sec.raw_manifests[0]
    forged = declared.model_copy(update={"resource": "submissions:0000000002"})
    object.__setattr__(sec, "raw_manifests", (forged, *sec.raw_manifests[1:]))
    with pytest.raises(SecAccountingBindingError, match="differs from verified storage"):
        bind_sec_to_accounting(
            sec, plan=_plan(tmp_path), as_of=AS_OF,
            raw_store=RawSnapshotStore(tmp_path / "raw"),
        )
