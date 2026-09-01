from __future__ import annotations

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.external_evidence_verification import (
    ExternalEvidenceReceipt,
    ExternalEvidenceVerificationError,
    IndependentVerifierDecision,
    ProviderAdapterIdentity,
    VerifierAuthoritySnapshot,
    assess_external_evidence_verification,
    seal,
)
from governance.phase7e import EvidenceGate, GateState

NOW = dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC)
FINGERPRINT = typed_hash({"synthetic": "untrusted"})


def valid_inputs():
    adapter = seal(ProviderAdapterIdentity, "identity_hash", provider_id="provider.candidate",
                   dataset_id="dataset.candidate", dataset_version="dataset.v1",
                   adapter_id="adapter.candidate", adapter_release="release.v1")
    authority = seal(VerifierAuthoritySnapshot, "snapshot_hash", authority_id="authority.external",
                     observer_id="observer.independent", captured_at=NOW - dt.timedelta(hours=3),
                     fingerprint=FINGERPRINT,
                     revocation_checked_at=NOW - dt.timedelta(minutes=20))
    receipts = []
    decisions = []
    for index, gate in enumerate(EvidenceGate):
        receipt = seal(
            ExternalEvidenceReceipt, "receipt_hash", gate=gate,
            adapter_identity_hash=adapter.identity_hash,
            artifact_digest=typed_hash({"gate": gate.value, "fixture": True}),
            provider_receipt_id=f"receipt.{index}", provider_sequence=index,
            replay_nonce_digest=typed_hash({"nonce": index}),
            provider_issued_at=NOW - dt.timedelta(hours=2),
            observed_at=NOW - dt.timedelta(hours=1), expires_at=NOW + dt.timedelta(hours=1),
            signature_fingerprint=FINGERPRINT, signature_check="MATCHED_UNTRUSTED",
        )
        decision = seal(
            IndependentVerifierDecision, "decision_hash", gate=gate,
            receipt_hash=receipt.receipt_hash, maker_id="reviewer.maker",
            checker_id="reviewer.checker", authority_snapshot_hash=authority.snapshot_hash,
            made_at=NOW - dt.timedelta(minutes=40), checked_at=NOW - dt.timedelta(minutes=30),
            outcome="CANDIDATE",
        )
        receipts.append(receipt)
        decisions.append(decision)
    return adapter, authority, receipts, decisions


def assess(values=None, **kwargs):
    adapter, authority, receipts, decisions = values or valid_inputs()
    return assess_external_evidence_verification(
        adapter=adapter, authority=authority, receipts=receipts, decisions=decisions,
        verifier_time=kwargs.pop("verifier_time", NOW), **kwargs,
    )


def test_observed_and_technically_checked_never_close_gates():
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


@pytest.mark.parametrize("transport", ["copy", "construct", "dict", "json"])
def test_forged_truth_and_recomputed_hash_still_rejected(transport):
    adapter, authority, receipts, decisions = valid_inputs()
    values = receipts[0].model_dump(mode="python")
    values["observation_state"] = "VERIFIED"
    values["receipt_hash"] = typed_hash({k: v for k, v in values.items() if k != "receipt_hash"})
    if transport == "copy":
        forged = receipts[0].model_copy(update=values)
    elif transport == "construct":
        forged = ExternalEvidenceReceipt.model_construct(**values)
    elif transport == "json":
        forged = json.loads(json.dumps(ExternalEvidenceReceipt.model_construct(**values).model_dump(
            mode="json", warnings=False)))
    else:
        forged = values
    receipts[0] = forged
    with pytest.raises(ExternalEvidenceVerificationError, match="invalid receipt"):
        assess((adapter, authority, receipts, decisions))


@pytest.mark.parametrize("attack", ["nonce", "receipt", "stale", "future", "fingerprint",
                                           "adapter", "decision", "authority", "rejected"])
def test_replay_staleness_temporal_and_binding_attacks_fail_closed(attack):
    adapter, authority, receipts, decisions = valid_inputs()
    if attack == "nonce":
        values = {**receipts[1].model_dump(mode="python"),
                  "replay_nonce_digest": receipts[0].replay_nonce_digest}
        receipts[1] = seal(ExternalEvidenceReceipt, "receipt_hash",
                           **{k: v for k, v in values.items() if k != "receipt_hash"})
    elif attack == "receipt":
        values = {**receipts[1].model_dump(mode="python"),
                  "provider_receipt_id": receipts[0].provider_receipt_id}
        receipts[1] = seal(ExternalEvidenceReceipt, "receipt_hash",
                           **{k: v for k, v in values.items() if k != "receipt_hash"})
    elif attack == "stale":
        return _assert_stale((adapter, authority, receipts, decisions))
    elif attack == "future":
        authority = authority.model_copy(update={"revocation_checked_at": NOW + dt.timedelta(hours=1)})
    elif attack == "fingerprint":
        receipts[0] = receipts[0].model_copy(update={"signature_fingerprint": "f" * 64})
    elif attack == "adapter":
        receipts[0] = receipts[0].model_copy(update={"adapter_identity_hash": "e" * 64})
    elif attack == "decision":
        decisions[0] = decisions[0].model_copy(update={"receipt_hash": "d" * 64})
    elif attack == "authority":
        decisions[0] = decisions[0].model_copy(update={"authority_snapshot_hash": "c" * 64})
    else:
        values = decisions[0].model_dump(mode="python")
        values["outcome"] = "REJECT"
        decisions[0] = seal(IndependentVerifierDecision, "decision_hash",
                            **{k: v for k, v in values.items() if k != "decision_hash"})
    with pytest.raises(ExternalEvidenceVerificationError):
        assess((adapter, authority, receipts, decisions))


def _assert_stale(values):
    with pytest.raises(ExternalEvidenceVerificationError, match="stale"):
        assess(values, verifier_time=NOW + dt.timedelta(hours=24))


def test_missing_duplicate_reordered_and_secret_fields_rejected():
    adapter, authority, receipts, decisions = valid_inputs()
    with pytest.raises(ExternalEvidenceVerificationError, match="ten canonical"):
        assess((adapter, authority, receipts[:-1], decisions))
    with pytest.raises(ExternalEvidenceVerificationError, match="duplicate"):
        assess((adapter, authority, receipts[:-1] + [receipts[0]], decisions))
    secret = {**adapter.model_dump(mode="python"), "credential": "do-not-admit"}
    with pytest.raises(ExternalEvidenceVerificationError, match="invalid adapter"):
        assess((secret, authority, receipts, decisions))
    result = assess((adapter, authority, list(reversed(receipts)), list(reversed(decisions))))
    assert tuple(item.gate for item in result.candidates) == tuple(EvidenceGate)


def test_invalid_signature_naive_times_and_caller_gate_closure_rejected():
    adapter, authority, receipts, decisions = valid_inputs()
    values = receipts[0].model_dump(mode="python")
    values["signature_check"] = "INVALID"
    receipts[0] = seal(ExternalEvidenceReceipt, "receipt_hash",
                       **{k: v for k, v in values.items() if k != "receipt_hash"})
    with pytest.raises(ExternalEvidenceVerificationError, match="signature"):
        assess((adapter, authority, receipts, decisions))
    with pytest.raises(ValidationError):
        seal(VerifierAuthoritySnapshot, "snapshot_hash", authority_id="authority.external",
             observer_id="observer.independent", captured_at=NOW.replace(tzinfo=None),
             fingerprint=FINGERPRINT, revocation_checked_at=NOW)
    result = assess()
    with pytest.raises(ValidationError):
        result.model_copy(update={"gate_states": tuple(
            (gate, GateState.VERIFIED) for gate in EvidenceGate)}).__class__.model_validate(
                result.model_copy(update={"gate_states": tuple(
                    (gate, GateState.VERIFIED) for gate in EvidenceGate)}).model_dump(mode="json"))
