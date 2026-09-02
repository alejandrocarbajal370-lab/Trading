import datetime as dt

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.durable_replay import build_contract_test_persistent_replay, derive_replay_identity
from governance.external_custody import (
    CustodyBoundaryAssessment,
    CustodyObservationState,
    RawCustodyObservation,
    assess_contract_test_custody,
    observe_contract_test_custody,
    verify_real_external_custody,
)
from governance.external_provider_foundation import (
    FoundationError,
    ProviderRegistry,
    ProvisioningState,
    observe_material,
)
from governance.phase7e import EvidenceGate, GateState

COMMITTED = dt.datetime(2026, 9, 2, 18, tzinfo=dt.UTC)
OBSERVED = COMMITTED + dt.timedelta(minutes=1)
ASSESSED = OBSERVED + dt.timedelta(minutes=1)
RAW_EVIDENCE = b"synthetic custody control export"


def receipt(tmp_path, *, committed_at=COMMITTED, gate=EvidenceGate.RETENTION_WORM):
    material = observe_material(
        ProviderRegistry.resolve(gate),
        b"raw-material",
        b"provider-lineage",
        COMMITTED,
    )
    identity = derive_replay_identity(material)
    adapter = build_contract_test_persistent_replay(tmp_path / "replay.sqlite3")
    return adapter.consume_if_new((identity,), committed_at=committed_at)[0]


def observation(tmp_path, **overrides):
    values = {
        "persistence_receipt": receipt(tmp_path),
        "provider_id": "contract.custody.provider",
        "container_id": "contract.bucket",
        "object_id": "raw/object/sha256",
        "object_version": "version.001",
        "policy_id": "retention.policy.v1",
        "retained_from": COMMITTED,
        "retain_until": COMMITTED + dt.timedelta(days=30),
        "legal_hold_declared": False,
        "raw_evidence": RAW_EVIDENCE,
        "observed_at": OBSERVED,
    }
    values.update(overrides)
    return observe_contract_test_custody(**values)


def test_observation_binds_receipt_location_retention_and_raw_evidence(tmp_path):
    first = observation(tmp_path)
    assert first.trust_domain == "CONTRACT_TEST_ONLY"
    assert first.persistence_receipt.receipt_hash == receipt_hash(first)
    assert first.raw_evidence_size == len(RAW_EVIDENCE)

    second_dir = tmp_path / "second"
    second_dir.mkdir()
    assert observation(second_dir, raw_evidence=b"different") != first
    third_dir = tmp_path / "third"
    third_dir.mkdir()
    assert observation(third_dir, object_version="version.002") != first


def test_assessment_is_observed_untrusted_and_preserves_safety(tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    result = assess_contract_test_custody(
        observation(second), raw_evidence=RAW_EVIDENCE, assessed_at=ASSESSED
    )
    assert result.state is CustodyObservationState.OBSERVED_UNTRUSTED
    assert result.external_custody is ProvisioningState.NOT_PROVISIONED
    assert result.worm_retention is ProvisioningState.NOT_PROVISIONED
    assert result.legal_retention_approval is ProvisioningState.NOT_PROVISIONED
    assert result.trust_root is ProvisioningState.NOT_PROVISIONED
    assert result.independent_verifier is ProvisioningState.NOT_PROVISIONED
    assert result.gate_state is GateState.OPEN_EXTERNAL
    assert result.trade_decision == "NO_TRADE"
    assert result.signals_generated is False
    assert result.live_execution_enabled is False
    assert result.backtesting == "NOT_AUTHORIZED"


def test_deep_revalidation_rejects_nested_mutation_and_resealing(tmp_path):
    raw = observation(tmp_path).model_dump(mode="python")
    raw["location"]["object_version"] = "version.forged"
    with pytest.raises(FoundationError, match="invalid custody observation"):
        assess_contract_test_custody(raw, raw_evidence=RAW_EVIDENCE, assessed_at=ASSESSED)

    second = tmp_path / "second"
    second.mkdir()
    result = assess_contract_test_custody(
        observation(second), raw_evidence=RAW_EVIDENCE, assessed_at=ASSESSED
    )
    forged = result.model_dump(mode="python")
    forged["worm_retention"] = ProvisioningState.CONTRACT_TEST_ONLY
    forged.pop("assessment_hash")
    with pytest.raises(ValidationError):
        CustodyBoundaryAssessment(**forged, assessment_hash="0" * 64)


def test_temporal_causality_and_retention_fail_closed(tmp_path):
    with pytest.raises(FoundationError, match="precedes durable replay"):
        observation(tmp_path, observed_at=COMMITTED - dt.timedelta(seconds=1))
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises((FoundationError, ValidationError), match="retention|outside"):
        observation(second, retain_until=OBSERVED)
    third = tmp_path / "third"
    third.mkdir()
    with pytest.raises((FoundationError, ValidationError, ValueError), match="timezone-aware|invalid"):
        observation(third, observed_at=OBSERVED.replace(tzinfo=None))
    fourth = tmp_path / "fourth"
    fourth.mkdir()
    with pytest.raises((FoundationError, ValidationError), match="precedes"):
        assess_contract_test_custody(
            observation(fourth),
            raw_evidence=RAW_EVIDENCE,
            assessed_at=OBSERVED - dt.timedelta(seconds=1),
        )
    fifth = tmp_path / "fifth"
    fifth.mkdir()
    with pytest.raises((FoundationError, ValidationError), match="outside retention"):
        assess_contract_test_custody(
            observation(fifth),
            raw_evidence=RAW_EVIDENCE,
            assessed_at=COMMITTED + dt.timedelta(days=30),
        )


def test_fully_resealed_retention_start_before_commit_fails(tmp_path):
    item = observation(tmp_path)
    forged = item.model_dump(mode="json")
    forged["retention"]["retained_from"] = (
        COMMITTED - dt.timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    forged["retention"]["declaration_hash"] = typed_hash(
        {key: value for key, value in forged["retention"].items() if key != "declaration_hash"}
    )
    forged["observation_hash"] = typed_hash(
        {key: value for key, value in forged.items() if key != "observation_hash"}
    )
    with pytest.raises(ValidationError, match="retention start precedes"):
        RawCustodyObservation.model_validate(forged)


def test_unknown_fields_empty_evidence_and_model_construct_bypass_fail(tmp_path):
    with pytest.raises(FoundationError, match="non-empty bytes"):
        observation(tmp_path, raw_evidence=b"")
    second = tmp_path / "second"
    second.mkdir()
    raw = observation(second).model_dump(mode="python")
    raw["unknown"] = "forged"
    with pytest.raises(FoundationError, match="invalid custody observation"):
        assess_contract_test_custody(raw, raw_evidence=RAW_EVIDENCE, assessed_at=ASSESSED)
    raw.pop("unknown")
    raw["observation_hash"] = "0" * 64
    bypass = RawCustodyObservation.model_construct(**raw)
    with pytest.raises(FoundationError, match="invalid custody observation|undeclared"):
        assess_contract_test_custody(
            bypass, raw_evidence=RAW_EVIDENCE, assessed_at=ASSESSED
        )


def receipt_hash(value):
    return value.persistence_receipt.receipt_hash


def test_raw_bytes_are_recomputed_at_assessment_boundary(tmp_path):
    item = observation(tmp_path)
    with pytest.raises(FoundationError, match="digest mismatch"):
        assess_contract_test_custody(
            item, raw_evidence=b"x" * len(RAW_EVIDENCE), assessed_at=ASSESSED
        )


def test_equivalent_non_utc_offsets_are_rejected_to_prevent_hash_aliases(tmp_path):
    mexico = dt.timezone(dt.timedelta(hours=-6))
    with pytest.raises(ValueError, match="canonical UTC"):
        observation(tmp_path, retained_from=COMMITTED.astimezone(mexico))
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises(ValueError, match="canonical UTC"):
        observation(second, observed_at=OBSERVED.astimezone(mexico))


@pytest.mark.parametrize("object_id", ["aaa/../bbb", "aaa/./bbb", "aaa//bbb", "aaa/"])
def test_ambiguous_object_identity_segments_fail_closed(tmp_path, object_id):
    with pytest.raises((FoundationError, ValidationError), match="ambiguous"):
        observation(tmp_path, object_id=object_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "aaa/../bbb"),
        ("container_id", "aaa//bbb"),
        ("object_version", "aaa/./bbb"),
        ("policy_id", "aaa/../bbb"),
    ],
)
def test_all_location_and_policy_identifiers_reject_path_aliases(tmp_path, field, value):
    with pytest.raises((FoundationError, ValidationError), match="ambiguous"):
        observation(tmp_path, **{field: value})


def test_non_utc_nested_receipt_swap_fails_deep_revalidation(tmp_path):
    item = observation(tmp_path)
    mexico = dt.timezone(dt.timedelta(hours=-6))
    second = tmp_path / "second"
    second.mkdir()
    swapped = item.model_dump(mode="python")
    swapped["persistence_receipt"] = receipt(
        second, committed_at=COMMITTED.astimezone(mexico)
    ).model_dump(mode="python")
    bypass = RawCustodyObservation.model_construct(**swapped)
    with pytest.raises(FoundationError, match="invalid custody observation"):
        assess_contract_test_custody(
            bypass, raw_evidence=RAW_EVIDENCE, assessed_at=ASSESSED
        )


@pytest.mark.parametrize(
    "gate", [gate for gate in EvidenceGate if gate is not EvidenceGate.RETENTION_WORM]
)
def test_cross_gate_receipt_swap_matrix_fails_closed(tmp_path, gate):
    with pytest.raises(FoundationError, match="retention gate"):
        observation(tmp_path, persistence_receipt=receipt(tmp_path, gate=gate))


def test_real_route_is_sealed_and_cannot_accept_fake_backend_or_authority():
    with pytest.raises(FoundationError, match="NOT_PROVISIONED"):
        verify_real_external_custody(
            gate=EvidenceGate.RETENTION_WORM,
            evidence={"backend": "caller.fake", "trust_root": "caller.fake"},
        )
    with pytest.raises(FoundationError, match="invalid evidence gate"):
        verify_real_external_custody(gate="UNKNOWN", evidence={})
