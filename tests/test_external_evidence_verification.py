from __future__ import annotations

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.external_evidence_verification import (
    CONTRACT_VERSION,
    ExternalEvidenceReceipt,
    ExternalEvidenceVerificationError,
    ExternalVerificationFoundationResult,
    IndependentVerifierDecision,
    ProviderAdapterIdentity,
    RevocationReview,
    VerifierAuthoritySnapshot,
    assess_external_evidence_verification,
    canonical_gate_verification_manifest,
    seal,
    validate_external_verification_result,
)
from governance.phase7e import EvidenceGate, GateState

NOW = dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC)
FINGERPRINT = typed_hash({"synthetic": "untrusted"})


def valid_inputs(*, authority_delta=dt.timedelta(hours=3),
                 revocation_delta=dt.timedelta(minutes=5),
                 evidence_age=dt.timedelta(hours=1)):
    manifest = canonical_gate_verification_manifest()
    adapter = seal(ProviderAdapterIdentity, "identity_hash", manifest_hash=manifest.manifest_hash)
    authorities, receipts, decisions, revocations = [], [], [], []
    for index, expectation in enumerate(manifest.expectations):
        receipt_digest = typed_hash({"receipt": index})
        assessment = typed_hash({
            "contract": CONTRACT_VERSION, "gate": expectation.gate.value,
            "expectation_hash": expectation.expectation_hash,
            "provider_receipt_digest": receipt_digest, "verifier_time": NOW.isoformat(),
        })
        receipt = seal(
            ExternalEvidenceReceipt, "receipt_hash", gate=expectation.gate,
            expectation_hash=expectation.expectation_hash,
            adapter_identity_hash=adapter.identity_hash, assessment_identity=assessment,
            artifact_digest=expectation.expected_artifact_digest,
            provider_receipt_digest=receipt_digest, provider_sequence=index,
            replay_nonce_digest=typed_hash({"nonce": index}),
            provider_issued_at=NOW - evidence_age,
            observed_at=NOW - evidence_age, expires_at=NOW + dt.timedelta(hours=1),
            signature_fingerprint=FINGERPRINT, signature_check="MATCHED_UNTRUSTED",
        )
        authority = seal(
            VerifierAuthoritySnapshot, "snapshot_hash", gate=expectation.gate,
            expectation_hash=expectation.expectation_hash, receipt_hash=receipt.receipt_hash,
            assessment_identity=assessment, captured_at=NOW - authority_delta,
            valid_from=NOW - max(authority_delta, dt.timedelta(hours=4)),
            valid_until=NOW + dt.timedelta(hours=1),
            verifier_time=NOW, fingerprint=FINGERPRINT, authority_status="ACTIVE_UNTRUSTED",
        )
        decision = seal(
            IndependentVerifierDecision, "decision_hash", gate=expectation.gate,
            expectation_hash=expectation.expectation_hash, receipt_hash=receipt.receipt_hash,
            assessment_identity=assessment, authority_snapshot_hash=authority.snapshot_hash,
            verifier_time=NOW, made_at=NOW - dt.timedelta(minutes=40),
            checked_at=NOW - dt.timedelta(minutes=30),
            reviewed_at=NOW - dt.timedelta(minutes=20), outcome="CANDIDATE",
        )
        revocation = seal(
            RevocationReview, "review_hash", gate=expectation.gate,
            expectation_hash=expectation.expectation_hash, receipt_hash=receipt.receipt_hash,
            assessment_identity=assessment, authority_snapshot_hash=authority.snapshot_hash,
            decision_hash=decision.decision_hash, observed_at=receipt.observed_at,
            made_at=decision.made_at, checked_at=decision.checked_at, verifier_time=NOW,
            reviewed_at=NOW - revocation_delta, status="ACTIVE_UNTRUSTED",
        )
        receipts.append(receipt)
        authorities.append(authority)
        decisions.append(decision)
        revocations.append(revocation)
    return adapter, authorities, receipts, decisions, revocations


def assess(values=None, *, verifier_time=NOW):
    adapter, authorities, receipts, decisions, revocations = values or valid_inputs()
    return assess_external_evidence_verification(
        adapter=adapter, authorities=authorities, receipts=receipts, decisions=decisions,
        revocations=revocations, verifier_time=verifier_time,
    )


def reseal(model, hash_field, **updates):
    values = model.model_dump(mode="python")
    values.update(updates)
    values.pop(hash_field)
    return seal(type(model), hash_field, **values)


def test_observed_and_checked_candidates_never_close_gates():
    result = assess()
    assert len(result.candidates) == 10
    assert {item.state for item in result.candidates} == {"TECHNICALLY_CHECKED_NOT_TRUSTED"}
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert result.authority_state == "NOT_PROVISIONED"
    assert result.real_route == "QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert result.trade_decision == "NO_TRADE"
    assert result.live_execution_enabled is result.signals_generated is False
    assert result.backtesting == "NOT_AUTHORIZED"


def test_complete_cross_gate_package_swap_fully_resealed_fails():
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    originals = [
        (receipts[index], authorities[index], decisions[index], revocations[index])
        for index in (0, 1)
    ]

    def relabel_and_reseal(package, target_gate):
        old_receipt, old_authority, old_decision, old_revocation = package
        assessment = typed_hash({
            "contract": CONTRACT_VERSION, "gate": target_gate.value,
            "expectation_hash": old_receipt.expectation_hash,
            "provider_receipt_digest": old_receipt.provider_receipt_digest,
            "verifier_time": NOW.isoformat(),
        })
        receipt = reseal(old_receipt, "receipt_hash", gate=target_gate,
                         assessment_identity=assessment)
        authority = reseal(old_authority, "snapshot_hash", gate=target_gate,
                           receipt_hash=receipt.receipt_hash, assessment_identity=assessment)
        decision = reseal(old_decision, "decision_hash", gate=target_gate,
                          receipt_hash=receipt.receipt_hash, assessment_identity=assessment,
                          authority_snapshot_hash=authority.snapshot_hash)
        revocation = reseal(old_revocation, "review_hash", gate=target_gate,
                            receipt_hash=receipt.receipt_hash, assessment_identity=assessment,
                            authority_snapshot_hash=authority.snapshot_hash,
                            decision_hash=decision.decision_hash)
        return receipt, authority, decision, revocation

    gate_iter = iter(EvidenceGate)
    left_package = relabel_and_reseal(originals[1], next(gate_iter))
    right_package = relabel_and_reseal(originals[0], next(gate_iter))
    for index, package in zip((0, 1), (left_package, right_package), strict=True):
        receipts[index], authorities[index], decisions[index], revocations[index] = package
    with pytest.raises(ExternalEvidenceVerificationError):
        assess((adapter, authorities, receipts, decisions, revocations))


@pytest.mark.parametrize("field", [
    "provider_ref", "dataset_ref", "dataset_version_ref", "adapter_ref",
    "adapter_release_ref", "evidence_policy_ref", "receipt_policy_ref",
    "expected_artifact_digest",
])
def test_forged_manifest_or_registry_metadata_cannot_be_supplied(field):
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    forged = canonical_gate_verification_manifest().model_dump(mode="python")
    forged["expectations"][0][field] = "f" * 64 if field.endswith("digest") else "forged"
    extra = {**adapter.model_dump(mode="python"), "manifest": forged}
    with pytest.raises(ExternalEvidenceVerificationError, match="invalid adapter"):
        assess((extra, authorities, receipts, decisions, revocations))


@pytest.mark.parametrize("collection_index", [1, 2, 3, 4])
@pytest.mark.parametrize("shape", ["missing", "duplicate", "extra"])
def test_gate_coverage_fail_closed(collection_index, shape):
    values = list(valid_inputs())
    items = list(values[collection_index])
    if shape == "missing":
        items.pop()
    elif shape == "duplicate":
        items[-1] = items[0]
    else:
        items.append(items[0])
    values[collection_index] = items
    with pytest.raises(ExternalEvidenceVerificationError):
        assess(tuple(values))


def test_reorder_is_canonicalized_without_positional_authority():
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    result = assess((adapter, list(reversed(authorities)), list(reversed(receipts)),
                     list(reversed(decisions)), list(reversed(revocations))))
    assert tuple(item.gate for item in result.candidates) == tuple(EvidenceGate)


@pytest.mark.parametrize("kind", [
    "authority_365d", "revocation_365d", "authority_after_observation",
    "retroactive_activation", "revoked_before_observation", "revoked_after_decision",
    "authority_unknown", "revocation_unknown", "stale_hash",
])
def test_authority_revocation_causality_and_status_fail_closed(kind):
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    if kind == "authority_365d":
        authorities[0] = reseal(authorities[0], "snapshot_hash",
                                 captured_at=NOW - dt.timedelta(days=365),
                                 valid_from=NOW - dt.timedelta(days=366))
    elif kind == "revocation_365d":
        revocations[0] = reseal(revocations[0], "review_hash",
                                reviewed_at=NOW - dt.timedelta(days=365))
    elif kind == "authority_after_observation":
        authorities[0] = reseal(authorities[0], "snapshot_hash",
                                 captured_at=NOW - dt.timedelta(minutes=30))
    elif kind == "retroactive_activation":
        authorities[0] = reseal(authorities[0], "snapshot_hash",
                                 valid_from=NOW - dt.timedelta(minutes=30),
                                 captured_at=NOW - dt.timedelta(minutes=20))
    elif kind.startswith("revoked_"):
        when = receipts[0].observed_at - dt.timedelta(minutes=1)
        if kind == "revoked_after_decision":
            when = decisions[0].checked_at + dt.timedelta(minutes=1)
        revocations[0] = reseal(revocations[0], "review_hash", status="REVOKED",
                                revoked_at=when)
    elif kind == "authority_unknown":
        authorities[0] = reseal(authorities[0], "snapshot_hash", authority_status="UNKNOWN")
    elif kind == "revocation_unknown":
        revocations[0] = reseal(revocations[0], "review_hash", status="UNKNOWN")
    else:
        authorities[0] = authorities[0].model_copy(update={"captured_at": NOW})
    with pytest.raises(ExternalEvidenceVerificationError):
        assess((adapter, authorities, receipts, decisions, revocations))


@pytest.mark.parametrize(("target", "field", "value"), [
    ("authority", "observer_id", "actor.external.maker"),
    ("authority", "observer_id", "actor.external.checker"),
    ("decision", "maker_id", "actor.external.checker"),
    ("decision", "maker_id", "actor.external.reviewer"),
])
def test_actor_independence_is_code_owned_and_fail_closed(target, field, value):
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    collection = authorities if target == "authority" else decisions
    hash_field = "snapshot_hash" if target == "authority" else "decision_hash"
    raw = collection[0].model_dump(mode="python")
    raw[field] = value
    raw.pop(hash_field)
    raw[hash_field] = typed_hash(raw)
    collection[0] = type(collection[0]).model_construct(**raw)
    with pytest.raises(ExternalEvidenceVerificationError):
        assess((adapter, authorities, receipts, decisions, revocations))


SECRET_PAYLOADS = [
    "token.secretvalue1234567890", "sk_live_0123456789abcdef", "user:password",
    "a" * 64, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
    "c2VjcmV0LWxvY2F0b3ItdmFsdWU=", "https://user:pass@example.test/path",
    "key=value&token=secret", "-----BEGIN PRIVATE KEY-----secret-----END PRIVATE KEY-----",
    "x" * 4096,
]


@pytest.mark.parametrize("payload", SECRET_PAYLOADS)
@pytest.mark.parametrize("field", [
    "provider_id", "dataset_id", "dataset_version", "adapter_id", "adapter_release",
])
def test_secret_metadata_fields_are_not_representable_or_serialized(field, payload):
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    injected = {**adapter.model_dump(mode="python"), field: payload}
    with pytest.raises(ExternalEvidenceVerificationError, match="invalid adapter"):
        assess((injected, authorities, receipts, decisions, revocations))
    result_text = repr(assess()) + assess().model_dump_json() + str(assess().model_dump())
    assert payload not in result_text


@pytest.mark.parametrize("transport", ["copy", "construct", "dict", "json", "nested"])
@pytest.mark.parametrize(("field", "promoted"), [
    ("authority_state", "PROVISIONED"), ("real_route", "QVM_READY"),
    ("live_execution_enabled", True), ("gate_states", tuple(
        (gate, GateState.VERIFIED) for gate in EvidenceGate)),
])
def test_promoted_result_cannot_cross_public_truth_boundary(transport, field, promoted):
    result = assess()
    values = result.model_dump(mode="python")
    values[field] = promoted
    values["result_hash"] = typed_hash({k: v for k, v in values.items() if k != "result_hash"})
    if transport == "copy":
        forged = result.model_copy(update=values)
    elif transport == "construct":
        forged = ExternalVerificationFoundationResult.model_construct(**values)
    elif transport == "json":
        forged = json.loads(ExternalVerificationFoundationResult.model_construct(
            **values).model_dump_json(warnings=False))
    elif transport == "nested":
        forged = {"result": ExternalVerificationFoundationResult.model_construct(**values)}
    else:
        forged = values
    with pytest.raises(ExternalEvidenceVerificationError, match="foundation result"):
        validate_external_verification_result(forged)


def test_rejected_decision_cannot_be_resold_as_candidate():
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    decisions[0] = reseal(decisions[0], "decision_hash", outcome="REJECT")
    with pytest.raises(ExternalEvidenceVerificationError):
        assess((adapter, authorities, receipts, decisions, revocations))


@pytest.mark.parametrize("attack", ["nonce", "receipt", "stale", "expiry", "future"])
def test_replay_and_receipt_freshness_boundaries(attack):
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    verifier_time = NOW
    if attack == "nonce":
        receipts[1] = reseal(receipts[1], "receipt_hash",
                             replay_nonce_digest=receipts[0].replay_nonce_digest)
    elif attack == "receipt":
        receipts[1] = reseal(receipts[1], "receipt_hash",
                             provider_receipt_digest=receipts[0].provider_receipt_digest)
    elif attack == "stale":
        verifier_time = receipts[0].observed_at + dt.timedelta(hours=24, microseconds=1)
    elif attack == "expiry":
        verifier_time = receipts[0].expires_at
    else:
        verifier_time = NOW - dt.timedelta(hours=2)
    with pytest.raises(ExternalEvidenceVerificationError):
        assess((adapter, authorities, receipts, decisions, revocations), verifier_time=verifier_time)


def test_exact_24h_receipt_age_is_allowed_when_not_expired():
    result = assess(valid_inputs(authority_delta=dt.timedelta(hours=24),
                                 evidence_age=dt.timedelta(hours=24)))
    assert len(result.candidates) == 10


def test_naive_time_and_extra_secret_field_rejected():
    adapter, authorities, receipts, decisions, revocations = valid_inputs()
    with pytest.raises(ValueError):
        assess((adapter, authorities, receipts, decisions, revocations),
               verifier_time=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        VerifierAuthoritySnapshot.model_validate({
            **authorities[0].model_dump(mode="python"), "credential": "secret",
        })
