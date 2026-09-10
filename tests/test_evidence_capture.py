from __future__ import annotations

import datetime as dt
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from governance.evidence_capture import (
    CONTRACT_VERSION,
    CaptureAssurance,
    CaptureState,
    EvidenceCaptureError,
    EvidenceCaptureRecord,
    LocalEvidenceCaptureStore,
    SourceEventState,
    canonicalize_captures,
    capture_contract_test_observation,
    project_to_step5,
)
from governance.external_evidence_verification import (
    ProviderAdapterIdentity,
    canonical_gate_verification_manifest,
    contract_test_material_for_gate,
    observe_contract_test_material,
    seal,
)
from governance.phase7e import EvidenceGate, GateState

NOW = dt.datetime(2026, 9, 10, 12, tzinfo=dt.UTC)


def upstream(gate=EvidenceGate.REAL_FX, variant="v1", observed_at=NOW):
    manifest = canonical_gate_verification_manifest()
    adapter = seal(ProviderAdapterIdentity, "identity_hash", manifest_hash=manifest.manifest_hash)
    return observe_contract_test_material(
        gate=gate, material=contract_test_material_for_gate(gate, variant),
        observed_at=observed_at, adapter=adapter,
    )


def capture(gate=EvidenceGate.REAL_FX, variant="v1", observed_at=NOW):
    return capture_contract_test_observation(
        upstream(gate, variant, observed_at), available_at=observed_at + dt.timedelta(minutes=1),
        captured_at=observed_at + dt.timedelta(minutes=2),
    )


def test_canonical_fixture_capture_is_content_addressed_but_incomplete():
    item = capture()
    assert item.contract_version == CONTRACT_VERSION
    assert item.assurance is CaptureAssurance.CONTRACT_TEST_ONLY
    assert item.capture_state is CaptureState.INCOMPLETE
    assert item.source_event_state is SourceEventState.SYNTHETIC_TEST_ONLY
    assert item.production_countable is False
    assert item.observation_identity_ref is None
    assert item.payload_digest == upstream().material_digest


@pytest.mark.parametrize("gate", tuple({
    EvidenceGate.HISTORICAL_PIT_SECURITY_MASTER, EvidenceGate.REAL_FX,
    EvidenceGate.SHARES_OUTSTANDING_PIT, EvidenceGate.HISTORICAL_COMPLETENESS,
    EvidenceGate.OPERATIONS_MONITORING, EvidenceGate.RETENTION_WORM,
    EvidenceGate.LICENSING_LEGAL,
}))
def test_all_seven_step5_classes_capture_only_partial_contract_fixtures(gate):
    item = capture(gate)
    projection = project_to_step5(item)
    assert item.gate is gate
    assert projection.eligible is False
    assert projection.state is CaptureState.NOT_PROVISIONED
    assert all(state is GateState.OPEN_EXTERNAL for _, state in projection.gate_states)


def test_arbitrary_caller_digest_ref_schema_or_version_cannot_become_truth():
    raw = upstream().model_dump(mode="python")
    for field, value in (
        ("observation_hash", "0" * 64), ("material_digest", "1" * 64),
        ("provider_ref", "caller.provider"), ("version", "caller-v99"),
    ):
        forged = dict(raw)
        forged[field] = value
        with pytest.raises(EvidenceCaptureError):
            capture_contract_test_observation(forged, available_at=NOW, captured_at=NOW)


def test_duplicate_replay_alias_counts_once_and_order_is_deterministic():
    first = capture()
    accepted, conflicts = canonicalize_captures((first, first.model_copy()))
    assert accepted == (first,)
    assert conflicts == ()
    assert canonicalize_captures(tuple(reversed((first, first)))) == (accepted, conflicts)


def test_same_semantic_slot_different_payload_requires_review():
    one, two = capture(variant="v1"), capture(variant="v2")
    accepted, conflicts = canonicalize_captures((two, one))
    assert accepted == ()
    assert len(conflicts) == 1
    assert project_to_step5(conflicts[0]).state is CaptureState.REVIEW_REQUIRED


@pytest.mark.parametrize("available,captured", [
    (NOW - dt.timedelta(microseconds=1), NOW),
    (NOW + dt.timedelta(minutes=2), NOW + dt.timedelta(minutes=1)),
    (NOW.replace(tzinfo=None), NOW),
    (NOW + dt.timedelta(minutes=1), NOW.replace(tzinfo=None)),
])
def test_utc_pit_boundaries_and_no_lookahead(available, captured):
    with pytest.raises(EvidenceCaptureError):
        capture_contract_test_observation(upstream(), available_at=available, captured_at=captured)


def test_exact_pit_boundary_is_accepted():
    item = capture_contract_test_observation(upstream(), available_at=NOW, captured_at=NOW)
    assert item.available_at == item.captured_at == NOW


def test_copy_construct_json_and_reseal_cannot_promote_assurance_or_lifecycle():
    item = capture()
    for mutate in (
        lambda: item.model_copy(update={"capture_state": "COMPLETE"}),
        lambda: EvidenceCaptureRecord.model_construct(**{
            **item.model_dump(mode="python"), "assurance": "EXTERNALLY_VERIFIED"}),
        lambda: EvidenceCaptureRecord.model_validate_json(json.dumps({
            **item.model_dump(mode="json"), "observation_identity_ref": "0" * 64})),
    ):
        with pytest.raises(EvidenceCaptureError):
            mutate()


@pytest.mark.parametrize("state", ("FUTURE", "EXPIRED", "REVOKED", "REPLACED"))
def test_unowned_lifecycle_claims_fail_closed_instead_of_becoming_current(state):
    item = capture()
    with pytest.raises(EvidenceCaptureError):
        item.model_copy(update={"lifecycle_status": state})


def test_local_store_restart_replay_and_corruption_fail_closed(tmp_path):
    path = tmp_path / "capture.sqlite"
    item = capture()
    store = LocalEvidenceCaptureStore(path)
    store.put(item)
    store.put(item)
    reopened = LocalEvidenceCaptureStore(path)
    assert reopened.assurance is CaptureAssurance.LOCAL_CAPTURE_ONLY
    assert reopened.load() == (item,)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE captures SET body='{}'")
    with pytest.raises(EvidenceCaptureError):
        LocalEvidenceCaptureStore(path)


def test_parallel_input_is_deterministic_and_privacy_errors_do_not_echo(tmp_path):
    item = capture()
    store = LocalEvidenceCaptureStore(tmp_path / "parallel.sqlite")
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(x == item for x in pool.map(store.put, (item,) * 20))
    assert store.load() == (item,)
    secret = "account-123-password-super-secret"
    raw = item.model_dump(mode="python")
    raw["provider_ref"] = secret
    with pytest.raises(EvidenceCaptureError) as caught:
        EvidenceCaptureRecord.model_validate(raw)
    assert secret not in str(caught.value)
    assert secret not in repr(item)
