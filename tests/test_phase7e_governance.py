import datetime

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.phase7e import (
    EvidenceClass,
    EvidenceCustodyContext,
    EvidenceGate,
    EvidenceRecord,
    Phase7EBundle,
    ReviewedGateEvidence,
    assess_phase7e_bundle,
    require_complete_external_evidence,
)

AS_OF = datetime.datetime(2026, 8, 28, tzinfo=datetime.UTC)


def _record(gate: EvidenceGate, kind: EvidenceClass = EvidenceClass.REAL_EXTERNAL):
    return EvidenceRecord(
        gate=gate,
        evidence_class=kind,
        provider_id="provider-under-review",
        dataset_id="dataset-under-review",
        source_uri="governed://external-review/record",
        source_record_id=f"record:{gate.value}",
        content_hash=typed_hash({"gate": gate.value}),
        observed_at=AS_OF,
        scope="declared historical scope",
    )


def _review(gate: EvidenceGate):
    return ReviewedGateEvidence(
        record=_record(gate),
        maker_id="maker",
        checker_id="independent-checker",
        decision="ACCEPT",
        checked_at=AS_OF,
        review_record_id=f"review:{gate.value}",
    )


def _bundle(reviews):
    values = {
        "provider_id": "provider-under-review",
        "dataset_id": "dataset-under-review",
        "reviews": tuple(reviews),
        "assembled_at": AS_OF,
    }
    payload = {
        "version": "phase7e-real-provider-evidence-v1",
        **values,
        "reviews": [x.model_dump(mode="json") for x in values["reviews"]],
        "assembled_at": AS_OF.isoformat().replace("+00:00", "Z"),
    }
    return Phase7EBundle(**values, bundle_hash=typed_hash(payload))


def test_absence_of_evidence_is_open_external_and_not_ready():
    result = assess_phase7e_bundle(None)
    assert {state for _, state in result.gate_states} == {"OPEN_EXTERNAL"}
    assert result.state == "OPEN_EXTERNAL"
    assert result.real_route == "QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert (result.trade_decision, result.live_execution_enabled, result.signals_generated) == (
        "NO_TRADE",
        False,
        False,
    )
    assert result.backtesting == "NOT_AUTHORIZED"


def test_partial_bundle_cannot_verify_provider():
    bundle = _bundle([_review(EvidenceGate.LICENSING_LEGAL)])
    context = EvidenceCustodyContext(reviews=bundle.reviews)
    result = assess_phase7e_bundle(bundle, context)
    assert result.state == "OPEN_EXTERNAL"
    with pytest.raises(ValueError, match="OPEN_EXTERNAL"):
        require_complete_external_evidence(bundle, context)


def test_self_declared_bundle_without_governed_custody_cannot_verify_any_gate():
    bundle = _bundle([_review(gate) for gate in EvidenceGate])
    result = assess_phase7e_bundle(bundle)
    assert {state for _, state in result.gate_states} == {"OPEN_EXTERNAL"}
    assert result.state == "OPEN_EXTERNAL"


def test_fixture_cannot_be_accepted_as_real_evidence():
    with pytest.raises(ValidationError, match="contract-test-only"):
        ReviewedGateEvidence(
            record=_record(EvidenceGate.REAL_FX, EvidenceClass.CONTRACT_TEST_ONLY),
            maker_id="maker",
            checker_id="checker",
            decision="ACCEPT",
            checked_at=AS_OF,
            review_record_id="fixture-review",
        )


def test_maker_cannot_check_own_evidence():
    with pytest.raises(ValidationError, match="distinct"):
        ReviewedGateEvidence(
            record=_record(EvidenceGate.RETENTION_WORM),
            maker_id="same-person",
            checker_id="same-person",
            decision="ACCEPT",
            checked_at=AS_OF,
            review_record_id="invalid-review",
        )


def test_all_concrete_gate_reviews_complete_phase7e_only_not_real_readiness():
    bundle = _bundle([_review(gate) for gate in EvidenceGate])
    context = EvidenceCustodyContext(reviews=bundle.reviews)
    result = require_complete_external_evidence(bundle, context)
    assert result.state == "EVIDENCE_REVIEW_COMPLETE"
    assert {state for _, state in result.gate_states} == {"VERIFIED"}
    assert result.real_route == "QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
