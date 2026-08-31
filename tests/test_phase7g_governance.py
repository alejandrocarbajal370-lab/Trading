import datetime as dt
import json

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState
from governance.phase7g import (
    CredentialReference,
    ExternalAuthorityProvisioning,
    GateEvidenceCandidate,
    LegalState,
    MakerCheckerDecision,
    ObjectLockEvidenceReceipt,
    Phase7GContractError,
    ProviderDatasetSelection,
    ProvisionedArtifactEnvelope,
    ProvisioningTransition,
    SelectionState,
    assess_provisioning_foundation,
    real_external_verification_unavailable,
)

NOW = dt.datetime(2026, 8, 30, 12, tzinfo=dt.UTC)
VALID_FROM = NOW - dt.timedelta(days=2)
SELECTED = NOW - dt.timedelta(days=1)
PROVISIONING = SELECTED + dt.timedelta(hours=1)
PROVISIONED = SELECTED + dt.timedelta(hours=2)
RETRIEVED = SELECTED + dt.timedelta(hours=3)
RECORDED = SELECTED + dt.timedelta(hours=4)
OBSERVED = SELECTED + dt.timedelta(hours=5)
PENDING = SELECTED + dt.timedelta(hours=6)
FUTURE = NOW + dt.timedelta(days=1)


def seal(cls, field, **values):
    raw = cls.model_construct(**values, **{field: "0" * 64})
    values[field] = typed_hash(raw.model_dump(mode="json", exclude={field}, warnings=False))
    return cls(**values)


def reseal(model, field, **changes):
    values = model.model_dump(mode="python")
    values.update(changes)
    return seal(type(model), field, **{k: v for k, v in values.items() if k != field})


def foundation():
    decision = seal(MakerCheckerDecision, "decision_hash", maker_id="actor.maker",
        checker_id="actor.checker", made_at=SELECTED, checked_at=SELECTED, decision="SELECT")
    selection = seal(ProviderDatasetSelection, "selection_hash", provider_id="provider.candidate",
        dataset_id="dataset.candidate", dataset_version="dataset.v1", scope_id="scope.candidate",
        legal_state=LegalState.REVIEW_PENDING, license_artifact_reference="legal.pending",
        commercial_terms_declaration="DECLARED_ONLY", valid_from=VALID_FROM,
        selected_at=SELECTED, valid_until=FUTURE, legal_effective_from=VALID_FROM,
        legal_effective_until=FUTURE, decision=decision)
    authority = seal(ExternalAuthorityProvisioning, "provisioning_hash",
        authority_id="authority.pending", mechanism_version="verification.v1")
    credential = seal(CredentialReference, "reference_hash", reference_id="credential.provider",
        provider_id=selection.provider_id, dataset_id=selection.dataset_id,
        scope_id=selection.scope_id, adapter_id="adapter.contract",
        secret_store_namespace="trading/provider", opaque_reference_id="ref_0123456789abcdef")
    transitions = []
    times = (SELECTED, PROVISIONING, PROVISIONED, PENDING)
    states = tuple(SelectionState)
    for index, when in enumerate(times):
        transitions.append(seal(ProvisioningTransition, "transition_hash",
            previous_state=states[index], current_state=states[index + 1], occurred_at=when,
            selection_hash=selection.selection_hash))
    receipts, envelopes, candidates = [], [], []
    for gate in EvidenceGate:
        slug = gate.value.casefold()
        digest = typed_hash({"gate": gate.value, "source": f"source.{slug}"})
        receipt = seal(ObjectLockEvidenceReceipt, "receipt_hash", receipt_id=f"receipt.{slug}",
            gate=gate, provider_id=selection.provider_id, dataset_id=selection.dataset_id,
            dataset_version=selection.dataset_version, scope_id=selection.scope_id,
            bucket_id="bucket.candidate", object_id=f"object.{slug}", object_version="object.v1",
            artifact_digest=digest, recorded_at=RECORDED, retention_mode="DECLARED_ONLY",
            retain_until=FUTURE, legal_hold="NOT_CONFIGURED")
        envelope = seal(ProvisionedArtifactEnvelope, "envelope_hash", gate=gate,
            source_identity=f"source.{slug}", provider_id=selection.provider_id,
            dataset_id=selection.dataset_id, dataset_version=selection.dataset_version,
            scope_id=selection.scope_id, adapter_id=credential.adapter_id, retrieved_at=RETRIEVED,
            artifact_digest=digest, provenance_reference=f"provenance.{slug}",
            custody_reference=receipt.receipt_id, credential_reference_id=credential.reference_id)
        candidate = seal(GateEvidenceCandidate, "candidate_hash", gate=gate,
            provider_id=selection.provider_id, dataset_id=selection.dataset_id,
            dataset_version=selection.dataset_version, scope_id=selection.scope_id,
            source_identity=envelope.source_identity,
            provenance_reference=envelope.provenance_reference,
            credential_reference_id=credential.reference_id, selection_hash=selection.selection_hash,
            artifact_digest=digest, authority_provisioning_hash=authority.provisioning_hash,
            custody_receipt_hash=receipt.receipt_hash, policy_id=f"policy.{slug}",
            observed_at=OBSERVED, expires_at=FUTURE)
        receipts.append(receipt); envelopes.append(envelope); candidates.append(candidate)
    return (selection, authority, tuple(receipts), (credential,), tuple(envelopes),
            tuple(candidates), tuple(transitions))


def assess(items=None):
    v = items or foundation()
    return assess_provisioning_foundation(selection=v[0], authority=v[1], custody=v[2],
        credentials=v[3], envelopes=v[4], candidates=v[5], transitions=v[6], verifier_time=NOW)


def replace(items, index, value):
    changed = list(items); changed[index] = value; return tuple(changed)


def test_foundation_preserves_exact_fail_closed_state():
    result = assess()
    assert len(result.candidates) == 10
    assert result.gate_states == tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)
    assert (result.real_route, result.global_readiness, result.trade_decision) == (
        "QVM_NOT_READY", "INSUFFICIENT_REAL_DATA", "NO_TRADE")
    assert not result.live_execution_enabled and not result.signals_generated
    assert result.backtesting == "NOT_AUTHORIZED"


@pytest.mark.parametrize("field,value", [("approval_state", "APPROVED"),
    ("admission_state", "ADMITTED"), ("selection_state", "REAL_APPROVED"),
    ("legal_state", "EXTERNALLY_VERIFIED")])
def test_selection_cannot_claim_real_authority(field, value):
    values = foundation()[0].model_dump(mode="python"); values[field] = value
    with pytest.raises(ValidationError): ProviderDatasetSelection.model_validate(values)


@pytest.mark.parametrize("value", ["sk-live-ThisLooksLikeAKey123", "ghp_abcdefghijk1234567890",
    "eyJhbGciOiJIUzI1NiJ9.payload.signature", "hunter2-correct-horse-battery-staple"])
def test_secret_looking_material_is_structurally_rejected(value):
    values = foundation()[3][0].model_dump(mode="python")
    values["opaque_reference_id"] = value; values["reference_hash"] = "0" * 64
    with pytest.raises(ValidationError): CredentialReference.model_validate(values)


def test_credential_repr_hides_opaque_handle_but_dump_is_only_a_handle():
    credential = foundation()[3][0]
    assert credential.opaque_reference_id not in repr(credential)
    assert set(credential.model_dump()) == {"version", "reference_id", "provider_id", "dataset_id",
        "scope_id", "purpose", "adapter_id", "secret_store_namespace", "opaque_reference_id",
        "reference_hash"}


def test_expired_selection_fully_resealed_fails():
    items = foundation(); selection = reseal(items[0], "selection_hash", valid_until=NOW)
    with pytest.raises(Phase7GContractError, match="expired"): assess(replace(items, 0, selection))


def test_retrieval_before_valid_from_fully_resealed_fails():
    items = foundation(); envelopes = list(items[4])
    envelopes[0] = reseal(envelopes[0], "envelope_hash", retrieved_at=VALID_FROM-dt.timedelta(seconds=1))
    with pytest.raises(Phase7GContractError, match="temporal"): assess(replace(items, 4, tuple(envelopes)))


def test_custody_provider_mismatch_fully_resealed_fails():
    items = foundation(); receipts = list(items[2])
    receipts[0] = reseal(receipts[0], "receipt_hash", provider_id="provider.swap")
    candidates = list(items[5]); candidates[0] = reseal(candidates[0], "candidate_hash",
        custody_receipt_hash=receipts[0].receipt_hash)
    items = replace(replace(items, 2, tuple(receipts)), 5, tuple(candidates))
    with pytest.raises(Phase7GContractError, match="custody identity"): assess(items)


def test_arbitrary_credential_id_without_record_fails():
    items = foundation(); envelopes = list(items[4]); candidates = list(items[5])
    envelopes[0] = reseal(envelopes[0], "envelope_hash", credential_reference_id="credential.arbitrary")
    candidates[0] = reseal(candidates[0], "candidate_hash", credential_reference_id="credential.arbitrary")
    with pytest.raises(Phase7GContractError, match="does not resolve"):
        assess(replace(replace(items, 4, tuple(envelopes)), 5, tuple(candidates)))


def test_envelope_custody_reference_to_other_receipt_fails():
    items = foundation(); envelopes = list(items[4])
    envelopes[0] = reseal(envelopes[0], "envelope_hash", custody_reference=items[2][1].receipt_id)
    with pytest.raises(Phase7GContractError, match="custody/provenance"):
        assess(replace(items, 4, tuple(envelopes)))


def test_two_gate_fully_resealed_artifact_swap_fails():
    items = foundation(); envelopes = list(items[4]); candidates = list(items[5])
    a, b = envelopes[:2]
    for index, other in ((0, b), (1, a)):
        envelopes[index] = reseal(envelopes[index], "envelope_hash",
            source_identity=other.source_identity, provenance_reference=other.provenance_reference,
            artifact_digest=other.artifact_digest)
        candidates[index] = reseal(candidates[index], "candidate_hash",
            source_identity=other.source_identity, provenance_reference=other.provenance_reference,
            artifact_digest=other.artifact_digest)
    with pytest.raises(Phase7GContractError, match="custody/provenance"):
        assess(replace(replace(items, 4, tuple(envelopes)), 5, tuple(candidates)))


def test_collections_are_order_independent_and_result_is_canonical():
    items = foundation()
    reordered = replace(replace(replace(items, 2, tuple(reversed(items[2]))), 4,
        tuple(reversed(items[4]))), 5, tuple(reversed(items[5])))
    assert tuple(x.gate for x in assess(reordered).candidates) == tuple(EvidenceGate)


def test_state_skip_and_reverse_are_rejected_at_boundary():
    base = foundation()[6][1].model_dump(mode="python")
    for previous, current in ((SelectionState.SELECTED, SelectionState.EXTERNAL_EVIDENCE_PENDING),
                              (SelectionState.PROVISIONING_PENDING, SelectionState.SELECTED)):
        base.update(previous_state=previous, current_state=current, transition_hash="0" * 64)
        with pytest.raises(ValidationError): ProvisioningTransition.model_validate(base)


@pytest.mark.parametrize("forge", ["construct", "copy", "dict", "json"])
def test_forged_terminal_transition_is_revalidated(forge):
    items = foundation(); transitions = list(items[6]); valid = transitions[1]
    values = valid.model_dump(mode="python"); values["current_state"] = "EXTERNAL_EVIDENCE_PENDING"
    if forge == "construct": forged = ProvisioningTransition.model_construct(**values)
    elif forge == "copy": forged = valid.model_copy(update={"current_state": "EXTERNAL_EVIDENCE_PENDING"})
    elif forge == "json": forged = json.loads(json.dumps(valid.model_dump(mode="json"))); forged["current_state"] = "EXTERNAL_EVIDENCE_PENDING"
    else: forged = values
    transitions[1] = forged
    with pytest.raises(Phase7GContractError, match="invalid transition"):
        assess(replace(items, 6, tuple(transitions)))


def test_retroactive_legal_effectiveness_fully_resealed_fails():
    items = foundation(); selection = reseal(items[0], "selection_hash", legal_effective_from=RETRIEVED+dt.timedelta(seconds=1))
    transitions = tuple(reseal(x, "transition_hash", selection_hash=selection.selection_hash) for x in items[6])
    candidates = tuple(reseal(x, "candidate_hash", selection_hash=selection.selection_hash) for x in items[5])
    items = replace(replace(replace(items, 0, selection), 5, candidates), 6, transitions)
    with pytest.raises(Phase7GContractError, match="retroactive|predates"):
        assess(items)


def test_model_copy_nested_dict_stale_hash_and_alternate_dto_fail():
    items = foundation(); forged = items[0].model_copy(update={"provider_id": "provider.forged"})
    with pytest.raises(Phase7GContractError, match="invalid selection"): assess(replace(items, 0, forged))
    nested = items[0].model_dump(mode="python"); nested["decision"]["checker_id"] = nested["decision"]["maker_id"]
    with pytest.raises(Phase7GContractError, match="invalid selection"): assess(replace(items, 0, nested))
    envelope = items[4][0].model_dump(mode="python"); envelope["artifact_digest"] = "a" * 64
    with pytest.raises(Phase7GContractError, match="invalid envelope"):
        assess(replace(items, 4, (envelope, *items[4][1:])))


def test_authority_and_worm_cannot_be_fabricated():
    authority = foundation()[1].model_dump(mode="python"); authority["key_or_cert_fingerprint"] = "a" * 64
    with pytest.raises(ValidationError): ExternalAuthorityProvisioning.model_validate(authority)
    receipt = foundation()[2][0].model_dump(mode="python"); receipt["provider_evidence_id"] = "fake.receipt"
    with pytest.raises(ValidationError): ObjectLockEvidenceReceipt.model_validate(receipt)


def test_fixture_to_real_and_result_copy_have_no_authority_path():
    forged = assess().model_copy(update={"state": "REAL_APPROVED"}); assert forged.state == "REAL_APPROVED"
    with pytest.raises(Phase7GContractError, match="unavailable"): real_external_verification_unavailable(forged)
    envelope = foundation()[4][0].model_dump(mode="python"); envelope["trust_domain"] = "REAL"
    with pytest.raises(ValidationError): ProvisionedArtifactEnvelope.model_validate(envelope)
