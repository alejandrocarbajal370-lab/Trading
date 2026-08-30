import datetime as dt

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
    assess_provisioning_foundation,
    real_external_verification_unavailable,
)

NOW = dt.datetime(2026, 8, 30, 12, tzinfo=dt.UTC)
PAST, FUTURE = NOW - dt.timedelta(days=1), NOW + dt.timedelta(days=1)


def seal(cls, field, **values):
    raw = cls.model_construct(**values, **{field: "0" * 64})
    values[field] = typed_hash(raw.model_dump(mode="json", exclude={field}, warnings=False))
    return cls(**values)


def foundation():
    decision = seal(
        MakerCheckerDecision,
        "decision_hash",
        maker_id="actor.maker",
        checker_id="actor.checker",
        made_at=PAST,
        checked_at=PAST,
        decision="SELECT",
    )
    selection = seal(
        ProviderDatasetSelection,
        "selection_hash",
        provider_id="provider.candidate",
        dataset_id="dataset.candidate",
        dataset_version="dataset.v1",
        scope_id="scope.candidate",
        legal_state=LegalState.REVIEW_PENDING,
        license_artifact_reference="legal.pending",
        commercial_terms_declaration="DECLARED_ONLY",
        valid_from=PAST,
        decision=decision,
    )
    authority = seal(
        ExternalAuthorityProvisioning,
        "provisioning_hash",
        authority_id="authority.pending",
        mechanism_version="verification.v1",
    )
    custody = seal(
        ObjectLockEvidenceReceipt,
        "receipt_hash",
        provider_id=selection.provider_id,
        bucket_id="bucket.candidate",
        object_id="object.candidate",
        object_version="object.v1",
        retention_mode="DECLARED_ONLY",
        retain_until=FUTURE,
        legal_hold="NOT_CONFIGURED",
    )
    envelopes, candidates = [], []
    for gate in EvidenceGate:
        envelope = seal(
            ProvisionedArtifactEnvelope,
            "envelope_hash",
            source_identity=f"source.{gate.value.casefold()}",
            provider_id=selection.provider_id,
            dataset_id=selection.dataset_id,
            dataset_version=selection.dataset_version,
            scope_id=selection.scope_id,
            retrieved_at=PAST,
            artifact_digest=typed_hash({"gate": gate.value}),
            provenance_reference=f"provenance.{gate.value.casefold()}",
            custody_reference="custody.pending",
            credential_reference_id="credential.provider",
        )
        candidate = seal(
            GateEvidenceCandidate,
            "candidate_hash",
            gate=gate,
            provider_id=selection.provider_id,
            dataset_id=selection.dataset_id,
            dataset_version=selection.dataset_version,
            scope_id=selection.scope_id,
            selection_hash=selection.selection_hash,
            artifact_digest=envelope.artifact_digest,
            authority_provisioning_hash=authority.provisioning_hash,
            custody_receipt_hash=custody.receipt_hash,
            policy_id=f"policy.{gate.value.casefold()}",
            observed_at=PAST,
            expires_at=FUTURE,
        )
        envelopes.append(envelope)
        candidates.append(candidate)
    return selection, authority, custody, tuple(envelopes), tuple(candidates)


def assess(items=None):
    v = items or foundation()
    return assess_provisioning_foundation(
        selection=v[0],
        authority=v[1],
        custody=v[2],
        envelopes=v[3],
        candidates=v[4],
        verifier_time=NOW,
    )


def reseal(model, field, **changes):
    values = model.model_dump(mode="python")
    values.update(changes)
    values[field] = "0" * 64
    raw = type(model).model_construct(**values)
    values[field] = typed_hash(raw.model_dump(mode="json", exclude={field}, warnings=False))
    return type(model)(**values)


def test_foundation_covers_all_gates_without_closing_any():
    result = assess()
    assert len(result.candidates) == 10
    assert result.gate_states == tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)
    assert (result.real_route, result.global_readiness) == (
        "QVM_NOT_READY",
        "INSUFFICIENT_REAL_DATA",
    )
    assert (result.trade_decision, result.live_execution_enabled, result.signals_generated) == (
        "NO_TRADE",
        False,
        False,
    )
    assert result.backtesting == "NOT_AUTHORIZED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("approval_state", "APPROVED"),
        ("admission_state", "ADMITTED"),
        ("selection_state", "REAL_APPROVED"),
        ("legal_state", "EXTERNALLY_VERIFIED"),
    ],
)
def test_selection_cannot_claim_approval_admission_or_external_legal_state(field, value):
    selection = foundation()[0].model_dump(mode="python")
    selection[field] = value
    with pytest.raises(ValidationError):
        ProviderDatasetSelection.model_validate(selection)


def test_credentials_are_references_never_values():
    CredentialReference(
        reference_id="credential.provider", backend="ENV_REFERENCE", handle="API_HANDLE"
    )
    with pytest.raises(ValidationError):
        CredentialReference(
            reference_id="credential.provider",
            backend="SECRET_MANAGER_HANDLE",
            handle="secret=password=hunter2",
        )


def test_authority_cannot_self_declare_or_attach_fake_fingerprint():
    values = foundation()[1].model_dump(mode="python")
    values["self_declared"] = True
    with pytest.raises(ValidationError):
        ExternalAuthorityProvisioning.model_validate(values)
    values["self_declared"] = False
    values["key_or_cert_fingerprint"] = "a" * 64
    with pytest.raises(ValidationError, match="cannot claim"):
        ExternalAuthorityProvisioning.model_validate(values)


def test_hash_only_or_provider_id_cannot_prove_worm():
    values = foundation()[2].model_dump(mode="python")
    values["verification_state"] = "VERIFIED"
    with pytest.raises(ValidationError):
        ObjectLockEvidenceReceipt.model_validate(values)
    values["verification_state"] = "OPEN_EXTERNAL"
    values["provider_evidence_id"] = "claimed.receipt"
    with pytest.raises(ValidationError, match="not provisioned"):
        ObjectLockEvidenceReceipt.model_validate(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "provider.swap"),
        ("dataset_id", "dataset.swap"),
        ("dataset_version", "dataset.v2"),
        ("scope_id", "scope.swap"),
    ],
)
def test_identity_swap_fails_even_when_candidate_is_resealed(field, value):
    items = list(foundation())
    candidates = list(items[4])
    candidates[0] = reseal(candidates[0], "candidate_hash", **{field: value})
    items[4] = tuple(candidates)
    with pytest.raises(Phase7GContractError, match="binding mismatch"):
        assess(tuple(items))


def test_gate_swap_and_reordered_candidates_fail():
    items = list(foundation())
    candidates = list(items[4])
    candidates[0], candidates[1] = candidates[1], candidates[0]
    items[4] = tuple(candidates)
    with pytest.raises(Phase7GContractError, match="canonical gates"):
        assess(tuple(items))


@pytest.mark.parametrize("when", [NOW, NOW - dt.timedelta(seconds=1)])
def test_stale_or_replayed_candidate_fails(when):
    items = list(foundation())
    candidates = list(items[4])
    candidates[0] = reseal(candidates[0], "candidate_hash", expires_at=when)
    items[4] = tuple(candidates)
    with pytest.raises(Phase7GContractError, match="stale, future, or swapped"):
        assess(tuple(items))


def test_future_retrieval_and_retroactive_selection_fail():
    items = list(foundation())
    envelopes = list(items[3])
    envelopes[0] = reseal(envelopes[0], "envelope_hash", retrieved_at=FUTURE)
    items[3] = tuple(envelopes)
    with pytest.raises(Phase7GContractError, match="stale, future, or swapped"):
        assess(tuple(items))
    selection = foundation()[0].model_dump(mode="python")
    selection["valid_from"] = PAST - dt.timedelta(seconds=1)
    selection["selection_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="prior maker-checker"):
        ProviderDatasetSelection.model_validate(selection)


def test_model_copy_construct_nested_dict_and_stale_hash_shortcuts_fail():
    items = list(foundation())
    items[0] = items[0].model_copy(update={"provider_id": "provider.forged"})
    with pytest.raises(Phase7GContractError, match="invalid selection"):
        assess(tuple(items))
    values = foundation()[0].model_dump(mode="python")
    values["decision"]["checker_id"] = values["decision"]["maker_id"]
    with pytest.raises(Phase7GContractError, match="invalid selection"):
        assess((values, *foundation()[1:]))


def test_alternate_result_dto_and_fixture_to_real_have_no_authority_path():
    forged = assess().model_copy(update={"state": "REAL_APPROVED"})
    assert forged.state == "REAL_APPROVED"
    with pytest.raises(Phase7GContractError, match="REAL verification is unavailable"):
        real_external_verification_unavailable(forged)
    envelope = foundation()[3][0].model_dump(mode="python")
    envelope["trust_domain"] = "REAL"
    with pytest.raises(ValidationError):
        ProvisionedArtifactEnvelope.model_validate(envelope)


def test_state_transition_skipping_is_unrepresentable():
    values = foundation()[0].model_dump(mode="python")
    values["decision"]["decision"] = "REJECT"
    values["decision"]["decision_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        ProviderDatasetSelection.model_validate(values)
