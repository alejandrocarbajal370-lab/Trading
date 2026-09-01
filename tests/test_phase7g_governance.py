import datetime as dt
import json

import pytest
from pydantic import ValidationError

from governance import phase7g
from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState
from governance.phase7g import (
    CredentialReference,
    ExternalAuthorityProvisioning,
    GateEvidenceCandidate,
    GateEvidenceManifest,
    GateProvisioningExpectation,
    LegalState,
    MakerCheckerDecision,
    ObjectLockEvidenceReceipt,
    Phase7GContractError,
    ProviderDatasetSelection,
    ProvisionedArtifactEnvelope,
    ProvisioningTransition,
    SelectionState,
    assess_provisioning_foundation,
    canonical_gate_evidence_manifest,
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
    credential = seal(CredentialReference, "reference_hash",
        credential_reference_digest=typed_hash({"credential": "sanitized-outside-contract"}),
        provider_id=selection.provider_id, dataset_id=selection.dataset_id,
        scope_id=selection.scope_id, adapter_id="phase7g.adapter.contract")
    transitions = []
    times = (SELECTED, PROVISIONING, PROVISIONED, PENDING)
    states = tuple(SelectionState)
    for index, when in enumerate(times):
        transitions.append(seal(ProvisioningTransition, "transition_hash",
            previous_state=states[index], current_state=states[index + 1], occurred_at=when,
            selection_hash=selection.selection_hash))
    receipts, envelopes, candidates = [], [], []
    manifest = canonical_gate_evidence_manifest()
    for expectation in manifest.expectations:
        gate = expectation.gate
        slug = gate.value.casefold()
        digest = expectation.expected_artifact_digest
        receipt = seal(ObjectLockEvidenceReceipt, "receipt_hash", receipt_id=f"receipt.{slug}",
            gate=gate, provider_id=selection.provider_id, dataset_id=selection.dataset_id,
            dataset_version=selection.dataset_version, scope_id=selection.scope_id,
            bucket_id=expectation.custody_bucket_id, object_id=expectation.custody_object_id,
            object_version=expectation.custody_object_version,
            artifact_digest=digest, recorded_at=RECORDED, retention_mode="DECLARED_ONLY",
            retain_until=FUTURE, legal_hold="NOT_CONFIGURED")
        envelope = seal(ProvisionedArtifactEnvelope, "envelope_hash", gate=gate,
            source_identity=expectation.source_identity, provider_id=selection.provider_id,
            dataset_id=selection.dataset_id, dataset_version=selection.dataset_version,
            scope_id=selection.scope_id, adapter_id=credential.adapter_id, retrieved_at=RETRIEVED,
            artifact_digest=digest, provenance_reference=expectation.provenance_policy_id,
            custody_reference=receipt.receipt_id,
            credential_reference_digest=credential.credential_reference_digest)
        candidate = seal(GateEvidenceCandidate, "candidate_hash", gate=gate,
            provider_id=selection.provider_id, dataset_id=selection.dataset_id,
            dataset_version=selection.dataset_version, scope_id=selection.scope_id,
            source_identity=envelope.source_identity,
            provenance_reference=envelope.provenance_reference,
            credential_reference_digest=credential.credential_reference_digest,
            selection_hash=selection.selection_hash,
            artifact_digest=digest, authority_provisioning_hash=authority.provisioning_hash,
            custody_receipt_hash=receipt.receipt_hash, policy_id=expectation.evidence_policy_id,
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


@pytest.mark.parametrize("value", [
    "eyJhbGciOiJIUzI1NiJ9.payload.signature",
    "dXNlcjpwYXNzd29yZA==",
    "0123456789abcdef" * 4,
    "sk_live_0123456789abcdef",
    "user:password",
    "https://store.invalid/ref?token=secret",
    "-----BEGIN PRIVATE KEY-----payload-----END PRIVATE KEY-----",
])
def test_secret_or_locator_material_cannot_occupy_credential_identity(value):
    values = foundation()[3][0].model_dump(mode="python")
    values["credential_reference_digest"] = value
    values["reference_hash"] = "0" * 64
    with pytest.raises(ValidationError): CredentialReference.model_validate(values)


def test_credential_dto_has_no_reversible_locator_field_or_output():
    credential = foundation()[3][0]
    assert set(credential.model_dump()) == {"version", "credential_reference_digest",
        "provider_id", "dataset_id", "scope_id", "purpose", "adapter_id", "reference_hash"}
    serialized = credential.model_dump_json()
    for forbidden in ("locator", "secret", "handle", "namespace", "password", "sk_live"):
        assert forbidden not in serialized.casefold()
    values = credential.model_dump(mode="python")
    values["locator"] = "user:password"
    with pytest.raises(ValidationError): CredentialReference.model_validate(values)


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
    arbitrary = "a" * 64
    envelopes[0] = reseal(envelopes[0], "envelope_hash", credential_reference_digest=arbitrary)
    candidates[0] = reseal(candidates[0], "candidate_hash", credential_reference_digest=arbitrary)
    with pytest.raises(Phase7GContractError, match="does not resolve"):
        assess(replace(replace(items, 4, tuple(envelopes)), 5, tuple(candidates)))


def test_envelope_custody_reference_to_other_receipt_fails():
    items = foundation(); envelopes = list(items[4])
    envelopes[0] = reseal(envelopes[0], "envelope_hash", custody_reference=items[2][1].receipt_id)
    with pytest.raises(Phase7GContractError, match="manifest"):
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
    with pytest.raises(Phase7GContractError, match="manifest"):
        assess(replace(replace(items, 4, tuple(envelopes)), 5, tuple(candidates)))


@pytest.mark.parametrize("changes", [
    {"bucket_id": "bucket.unrelated"},
    {"object_id": "object.unrelated"},
    {"object_version": "object.v999"},
    {"artifact_digest": "a" * 64},
])
def test_custody_object_identity_fully_resealed_fails(changes):
    items = foundation(); receipts = list(items[2]); candidates = list(items[5])
    receipts[0] = reseal(receipts[0], "receipt_hash", **changes)
    candidates[0] = reseal(candidates[0], "candidate_hash",
        custody_receipt_hash=receipts[0].receipt_hash,
        **({"artifact_digest": changes["artifact_digest"]} if "artifact_digest" in changes else {}))
    with pytest.raises(Phase7GContractError, match="manifest"):
        assess(replace(replace(items, 2, tuple(receipts)), 5, tuple(candidates)))


def test_complete_cross_gate_packages_fully_resealed_still_fail():
    items = foundation(); receipts = list(items[2]); envelopes = list(items[4]); candidates = list(items[5])
    old_receipts, old_envelopes, old_candidates = receipts[:2], envelopes[:2], candidates[:2]
    for target, source in ((0, 1), (1, 0)):
        gate = old_receipts[target].gate
        receipt_id = old_receipts[target].receipt_id
        receipts[target] = reseal(old_receipts[source], "receipt_hash", gate=gate, receipt_id=receipt_id)
        envelopes[target] = reseal(old_envelopes[source], "envelope_hash", gate=gate,
            custody_reference=receipt_id)
        candidates[target] = reseal(old_candidates[source], "candidate_hash", gate=gate,
            custody_receipt_hash=receipts[target].receipt_hash)
    swapped = replace(replace(replace(items, 2, tuple(receipts)), 4, tuple(envelopes)),
        5, tuple(candidates))
    with pytest.raises(Phase7GContractError, match="manifest"):
        assess(swapped)


def test_manifest_is_code_owned_and_forged_versions_hashes_fail():
    manifest = canonical_gate_evidence_manifest()
    forged_expectation = manifest.expectations[0].model_copy(
        update={"source_identity": "phase7g.source.forged"})
    values = manifest.model_dump(mode="python")
    values["expectations"] = (forged_expectation, *manifest.expectations[1:])
    with pytest.raises(ValidationError): GateEvidenceManifest.model_validate(values)
    with pytest.raises(ValidationError): GateEvidenceManifest.model_validate(
        {**manifest.model_dump(mode="python"), "version": "phase7g-manifest-swapped"})
    with pytest.raises(TypeError):
        phase7g.assess_provisioning_foundation(manifest=manifest, selection=None, authority=None,
            custody=(), credentials=(), envelopes=(), candidates=(), transitions=(),
            verifier_time=NOW)


@pytest.mark.parametrize("forge", ["copy", "construct", "dict", "json"])
def test_manifest_expectation_primitive_hardening(forge):
    valid = canonical_gate_evidence_manifest().expectations[0]
    values = valid.model_dump(mode="python")
    values["custody_object_version"] = "phase7g.object.version.forged"
    if forge == "copy": forged = valid.model_copy(update=values)
    elif forge == "construct": forged = GateProvisioningExpectation.model_construct(**values)
    elif forge == "json": forged = json.loads(json.dumps(values, default=str))
    else: forged = values
    with pytest.raises((ValidationError, Phase7GContractError)):
        phase7g._revalidate(GateProvisioningExpectation, forged, "manifest expectation")


def test_collections_are_order_independent_and_result_is_canonical():
    items = foundation()
    reordered = replace(replace(replace(items, 2, tuple(reversed(items[2]))), 4,
        tuple(reversed(items[4]))), 5, tuple(reversed(items[5])))
    assert tuple(x.gate for x in assess(reordered).candidates) == tuple(EvidenceGate)


@pytest.mark.parametrize("index", [2, 4, 5])
def test_duplicate_and_missing_gate_coverage_fail(index):
    items = foundation(); collection = list(items[index])
    with pytest.raises(Phase7GContractError, match="duplicate|cover ten"):
        assess(replace(items, index, tuple(collection[:-1] + [collection[0]])))
    with pytest.raises(Phase7GContractError, match="cover ten"):
        assess(replace(items, index, tuple(collection[:-1])))


def test_extra_unknown_gate_fails_during_primitive_revalidation():
    items = foundation(); extra = items[4][0].model_dump(mode="python")
    extra["gate"] = "UNRECOGNIZED_GATE"
    with pytest.raises(Phase7GContractError, match="invalid envelope"):
        assess(replace(items, 4, (*items[4], extra)))


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
