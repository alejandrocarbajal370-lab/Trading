import datetime

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.phase7e import (
    CompletenessPayload,
    ContractApproval,
    ContractEvidenceBundle,
    ContractGateVerification,
    ContractReviewerRegistry,
    ContractTestCustodyContext,
    ContractTestEvidence,
    CorporateActionPayload,
    EvidenceGate,
    FxPayload,
    GatePolicy,
    GateState,
    HistoricalPitPayload,
    LicensingPayload,
    OperationsPayload,
    Phase7EAssessment,
    Phase7EContractError,
    RealGateVerification,
    RestatementPayload,
    RetentionPayload,
    ScalePayload,
    SharesPayload,
    assess_phase7e_bundle,
    verify_contract_evidence_bundle,
    verify_real_external_evidence_bundle,
)

NOW = datetime.datetime(2026, 8, 28, tzinfo=datetime.UTC)
START = NOW - datetime.timedelta(days=365)
PROVIDER, DATASET, SCOPE = "synthetic-provider", "synthetic-dataset", "full-scope"


def _sealed(cls, **values):
    field = "policy_hash" if cls is GatePolicy else "content_hash"
    base = cls.model_construct(**values, **{field: "0" * 64})
    values[field] = typed_hash(base.model_dump(mode="json", exclude={field}))
    return cls(**values)


def _policy(gate, **changes):
    values = {
        "gate": gate,
        "provider_id": PROVIDER,
        "dataset_id": DATASET,
        "as_of": NOW,
        "scope_id": SCOPE,
        "window_start": START,
        "window_end": NOW,
        "max_age": datetime.timedelta(days=30),
    }
    values.update(changes)
    return _sealed(GatePolicy, **values)


def _payloads():
    return {
        EvidenceGate.HISTORICAL_PIT_SECURITY_MASTER: HistoricalPitPayload(
            kind="historical_pit",
            universe_id="u",
            security_master_id="sm",
            window_start=START,
            window_end=NOW,
            pit_semantics="available-at",
            completeness_artifact_ids=("c",),
        ),
        EvidenceGate.LICENSING_LEGAL: LicensingPayload(
            kind="licensing",
            legal_artifact_id="legal",
            permitted_use="research",
            effective_at=START,
            expires_at=NOW + datetime.timedelta(days=1),
            retention_permitted=True,
            derived_use_permitted=True,
        ),
        EvidenceGate.HISTORICAL_COMPLETENESS: CompletenessPayload(
            kind="completeness",
            universe_id="u",
            window_start=START,
            window_end=NOW,
            expected_count=10,
            observed_count=10,
            methodology_id="m",
        ),
        EvidenceGate.RETENTION_WORM: RetentionPayload(
            kind="retention_worm",
            storage_control_artifact_id="s",
            retention_days=365,
            immutability_mechanism_artifact_id="immutable-control",
            derived_artifact_policy_id="d",
        ),
        EvidenceGate.OPERATIONS_MONITORING: OperationsPayload(
            kind="operations",
            window_start=START,
            window_end=NOW,
            monitoring_artifact_id="m",
            incident_artifact_id="i",
            availability_artifact_id="a",
        ),
        EvidenceGate.REAL_FX: FxPayload(
            kind="fx",
            pairs=("USD/MXN",),
            window_start=START,
            window_end=NOW,
            pit_semantics="available-at",
            fx_artifact_id="fx",
        ),
        EvidenceGate.SHARES_OUTSTANDING_PIT: SharesPayload(
            kind="shares_pit",
            issuer_ids=("i",),
            security_ids=("s",),
            window_start=START,
            window_end=NOW,
            shares_semantics="as-reported",
            lineage_id="l",
        ),
        EvidenceGate.RESTATEMENT_MATERIALITY: RestatementPayload(
            kind="restatement",
            accounting_policy_id="a",
            restatement_policy_id="r",
            detection_artifact_id="d",
            materiality_artifact_id="m",
        ),
        EvidenceGate.CORPORATE_ACTION_ECONOMICS: CorporateActionPayload(
            kind="corporate_actions",
            security_ids=("s",),
            action_types=("split",),
            window_start=START,
            window_end=NOW,
            economic_treatment_policy_id="e",
        ),
        EvidenceGate.SCALE_OPERATIONAL_VALIDATION: ScalePayload(
            kind="scale",
            workload_id="w",
            coverage_id="c",
            volume=100,
            window_start=START,
            window_end=NOW,
            operational_test_artifact_id="o",
        ),
    }


def _evidence(gate, policy=None, **changes):
    policy = policy or _policy(gate)
    values = {
        "gate": gate,
        "provider_id": PROVIDER,
        "dataset_id": DATASET,
        "evidence_id": f"e:{gate}",
        "effective_at": START,
        "available_at": NOW - datetime.timedelta(days=1),
        "expires_at": None,
        "as_of": NOW,
        "scope_id": SCOPE,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
        "payload": _payloads()[gate],
    }
    values.update(changes)
    return _sealed(ContractTestEvidence, **values)


def _approval(e, policy=None, **changes):
    policy = policy or _policy(e.gate)
    values = {
        "gate": e.gate,
        "maker": "Maker One",
        "checker": "Checker Two",
        "provider_id": e.provider_id,
        "dataset_id": e.dataset_id,
        "evidence_hash": e.content_hash,
        "as_of": e.as_of,
        "scope_id": e.scope_id,
        "policy_version": e.policy_version,
        "policy_hash": e.policy_hash,
        "decision": "ACCEPT",
    }
    values.update(changes)
    return ContractApproval(**values)


def _bundle(evidences, approvals=None):
    approvals = tuple(approvals if approvals is not None else [_approval(e) for e in evidences])
    values = {
        "provider_id": PROVIDER,
        "dataset_id": DATASET,
        "evidences": tuple(evidences),
        "approvals": approvals,
    }
    raw = ContractEvidenceBundle.model_construct(**values, bundle_hash="0" * 64)
    return ContractEvidenceBundle(
        **values, bundle_hash=typed_hash(raw.model_dump(mode="json", exclude={"bundle_hash"}))
    )


def _resealed_bundle_copy(bundle, **changes):
    values = bundle.model_dump(mode="python", exclude={"bundle_hash"}, warnings=False)
    values.update(changes)
    raw = ContractEvidenceBundle.model_construct(**values, bundle_hash="0" * 64)
    return raw.model_copy(
        update={
            "bundle_hash": typed_hash(
                raw.model_dump(mode="json", exclude={"bundle_hash"}, warnings=False)
            )
        }
    )


REGISTRY = ContractReviewerRegistry(
    actors=(
        ("maker-one", ("Maker One", " maker  one ")),
        ("checker-two", ("Checker Two",)),
    )
)
CUSTODY = ContractTestCustodyContext()


def _verify(bundle, policies):
    return verify_contract_evidence_bundle(bundle, tuple(policies), CUSTODY, REGISTRY)


def test_full_forgery_and_resealed_context_produces_zero_real_verified_gates():
    policies = [_policy(g) for g in EvidenceGate]
    forged = _bundle([_evidence(g, p) for g, p in zip(EvidenceGate, policies, strict=True)])

    class ForgedResolver:
        canonical_trust_anchor_id = "caller-made"

    result = verify_real_external_evidence_bundle(forged, ForgedResolver())
    assert {s for _, s in result.gate_states} == {GateState.OPEN_EXTERNAL}
    assert result.state == "OPEN_EXTERNAL"


def test_contract_marker_cannot_be_changed_to_real_external_and_resealed():
    data = _evidence(EvidenceGate.REAL_FX).model_dump(mode="python")
    data["trust_domain"] = "REAL_EXTERNAL"
    with pytest.raises(ValidationError):
        ContractTestEvidence(**data)


def test_contract_payload_copied_to_nominal_real_context_is_rejected():
    assert (
        verify_real_external_evidence_bundle(_evidence(EvidenceGate.REAL_FX), object()).state
        == "OPEN_EXTERNAL"
    )


def test_gate_specific_payload_cannot_be_relabelled():
    with pytest.raises(ValidationError, match="gate-specific"):
        _evidence(EvidenceGate.LICENSING_LEGAL, payload=_payloads()[EvidenceGate.REAL_FX])


def test_incompatible_payload_or_identity_reuse_rejected():
    e = _evidence(EvidenceGate.REAL_FX)
    with pytest.raises(ValidationError, match="duplicate or reused"):
        _bundle([e, e])


@pytest.mark.parametrize(
    "field,value", [("provider_id", "other-provider"), ("dataset_id", "other-dataset")]
)
def test_cross_provider_or_dataset_reuse_rejected(field, value):
    e = _evidence(EvidenceGate.REAL_FX, **{field: value})
    with pytest.raises(ValidationError, match="binding mismatch"):
        _bundle([e])


@pytest.mark.parametrize(
    "maker,checker", [("Maker One", " maker  one "), ("MAKER ONE", "maker-one")]
)
def test_same_reviewer_alias_case_whitespace_rejected(maker, checker):
    p = _policy(EvidenceGate.REAL_FX)
    e = _evidence(EvidenceGate.REAL_FX, p)
    result = _verify(_bundle([e], [_approval(e, p, maker=maker, checker=checker)]), [p])
    assert result.gate_states[5][1] == GateState.OPEN_EXTERNAL


def test_invented_or_missing_checker_rejected():
    p = _policy(EvidenceGate.REAL_FX)
    e = _evidence(EvidenceGate.REAL_FX, p)
    a = _approval(e, p, maker="invented-a", checker="invented-b")
    assert not _verify(_bundle([e], [a]), [p]).contract_semantics_complete


def test_evidence_mutation_after_approval_invalidates_approval():
    p = _policy(EvidenceGate.REAL_FX)
    old = _evidence(EvidenceGate.REAL_FX, p)
    a = _approval(old, p)
    changed = _evidence(EvidenceGate.REAL_FX, p, evidence_id="changed")
    assert _verify(_bundle([changed], [a]), [p]).gate_states[5][1] == GateState.OPEN_EXTERNAL


@pytest.mark.parametrize(
    "changes",
    [
        {"available_at": NOW + datetime.timedelta(seconds=1)},
        {"expires_at": NOW - datetime.timedelta(seconds=1)},
        {"available_at": NOW - datetime.timedelta(days=31)},
    ],
)
def test_future_expired_or_stale_evidence_rejected(changes):
    p = _policy(EvidenceGate.REAL_FX)
    e = _evidence(EvidenceGate.REAL_FX, p, **changes)
    assert _verify(_bundle([e]), [p]).gate_states[5][1] == GateState.OPEN_EXTERNAL


@pytest.mark.parametrize(
    "approval_changes",
    [
        {"as_of": NOW - datetime.timedelta(seconds=1)},
        {"scope_id": "partial"},
        {"policy_hash": "f" * 64},
    ],
)
def test_asof_scope_or_policy_mismatch_rejected(approval_changes):
    p = _policy(EvidenceGate.REAL_FX)
    e = _evidence(EvidenceGate.REAL_FX, p)
    assert (
        _verify(_bundle([e], [_approval(e, p, **approval_changes)]), [p]).gate_states[5][1]
        == GateState.OPEN_EXTERNAL
    )


def test_partial_coverage_cannot_satisfy_full_gate():
    p = _policy(EvidenceGate.REAL_FX)
    payload = _payloads()[EvidenceGate.REAL_FX].model_copy(
        update={"window_start": START + datetime.timedelta(days=1)}
    )
    e = _evidence(EvidenceGate.REAL_FX, p, payload=payload)
    assert _verify(_bundle([e]), [p]).gate_states[5][1] == GateState.OPEN_EXTERNAL


def test_predeclared_verified_states_never_complete_real_aggregate():
    forged = {g.value: "VERIFIED" for g in EvidenceGate}
    result = assess_phase7e_bundle(forged, forged)
    assert result.state == "OPEN_EXTERNAL"
    assert {s for _, s in result.gate_states} == {GateState.OPEN_EXTERNAL}


def test_complete_fixture_passes_contract_semantics_only():
    policies = [_policy(g) for g in EvidenceGate]
    bundle = _bundle([_evidence(g, p) for g, p in zip(EvidenceGate, policies, strict=True)])
    contract = _verify(bundle, policies)
    assert contract.contract_semantics_complete
    assert {s for _, s in contract.gate_states} == {GateState.VERIFIED}
    assert verify_real_external_evidence_bundle(contract).state == "OPEN_EXTERNAL"


def test_real_route_remains_open_and_safety_invariants_hold():
    result = assess_phase7e_bundle(None)
    assert result.state == "OPEN_EXTERNAL"
    assert result.real_route == "QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert result.trade_decision == "NO_TRADE"
    assert not result.live_execution_enabled and not result.signals_generated
    assert result.backtesting == "NOT_AUTHORIZED"


@pytest.mark.parametrize("model", [RealGateVerification, Phase7EAssessment])
@pytest.mark.parametrize(
    "states",
    [
        tuple((g, GateState.VERIFIED) for g in EvidenceGate),
        tuple((g, GateState.OPEN_EXTERNAL) for g in tuple(EvidenceGate)[:-1]),
        tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)
        + ((EvidenceGate.REAL_FX, GateState.OPEN_EXTERNAL),),
        tuple(reversed(tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate))),
    ],
)
def test_public_real_outputs_reject_fabricated_missing_duplicate_or_reordered_states(model, states):
    with pytest.raises(ValidationError):
        model.model_validate({"gate_states": states})


@pytest.mark.parametrize("model", [RealGateVerification, Phase7EAssessment])
def test_direct_real_constructor_rejects_verified(model):
    with pytest.raises(ValidationError):
        model(gate_states=tuple((g, GateState.VERIFIED) for g in EvidenceGate))


def test_real_outputs_reject_unknown_gate_and_inconsistent_safety_fields():
    states = [(g.value, GateState.OPEN_EXTERNAL.value) for g in EvidenceGate]
    states[0] = ("UNKNOWN", GateState.OPEN_EXTERNAL.value)
    with pytest.raises(ValidationError):
        RealGateVerification.model_validate_json(
            __import__("json").dumps({"gate_states": states})
        )
    with pytest.raises(ValidationError):
        Phase7EAssessment.model_validate(
            {"gate_states": _open_states_for_test(), "trade_decision": "TRADE"}
        )


def _open_states_for_test():
    return tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)


def test_model_copy_cannot_turn_real_output_verified_or_fool_aggregate():
    forged = verify_real_external_evidence_bundle().model_copy(
        update={"gate_states": tuple((g, GateState.VERIFIED) for g in EvidenceGate)}
    )
    with pytest.raises(ValidationError):
        RealGateVerification.model_validate(forged.model_dump(mode="json"))
    result = assess_phase7e_bundle(forged, forged)
    assert result.gate_states == _open_states_for_test()


@pytest.mark.parametrize("source_gate", list(EvidenceGate))
@pytest.mark.parametrize("target_gate", list(EvidenceGate))
def test_cross_gate_model_copy_matrix_is_rejected(source_gate, target_gate):
    if source_gate == target_gate:
        return
    policy = _policy(source_gate)
    evidence = _evidence(source_gate, policy)
    forged = evidence.model_copy(update={"gate": target_gate})
    bundle = _resealed_bundle_copy(
        _bundle([evidence]), evidences=(forged,), approvals=(_approval(evidence, policy),)
    )
    with pytest.raises(Phase7EContractError):
        _verify(bundle, [policy])


@pytest.mark.parametrize(
    "change",
    [
        {"provider_id": "copied-provider"},
        {"dataset_id": "copied-dataset"},
        {"as_of": NOW - datetime.timedelta(seconds=1)},
        {"scope_id": "partial-scope"},
    ],
)
def test_copied_evidence_semantics_with_stale_hash_rejected_at_boundary(change):
    policy = _policy(EvidenceGate.REAL_FX)
    evidence = _evidence(EvidenceGate.REAL_FX, policy)
    forged = evidence.model_copy(update=change)
    bundle = _resealed_bundle_copy(_bundle([evidence]), evidences=(forged,))
    with pytest.raises(Phase7EContractError):
        _verify(bundle, [policy])


def test_copied_payload_and_stale_evidence_hash_rejected_at_boundary():
    policy = _policy(EvidenceGate.REAL_FX)
    evidence = _evidence(EvidenceGate.REAL_FX, policy)
    payload = evidence.payload.model_copy(update={"kind": "licensing"})
    forged = evidence.model_copy(update={"payload": payload})
    bundle = _resealed_bundle_copy(_bundle([evidence]), evidences=(forged,))
    with pytest.raises(Phase7EContractError):
        _verify(bundle, [policy])


def test_copied_policy_with_stale_hash_rejected_at_boundary():
    policy = _policy(EvidenceGate.REAL_FX)
    evidence = _evidence(EvidenceGate.REAL_FX, policy)
    forged_policy = policy.model_copy(update={"provider_id": "copied-provider"})
    with pytest.raises(Phase7EContractError):
        _verify(_bundle([evidence]), [forged_policy])


def test_copied_approval_binding_is_rederived_not_trusted():
    policy = _policy(EvidenceGate.REAL_FX)
    evidence = _evidence(EvidenceGate.REAL_FX, policy)
    approval = _approval(evidence, policy).model_copy(update={"evidence_hash": "f" * 64})
    result = _verify(_bundle([evidence], [approval]), [policy])
    assert result.gate_states[5][1] == GateState.OPEN_EXTERNAL


def test_model_construct_nested_invalid_evidence_rejected_at_boundary():
    policy = _policy(EvidenceGate.REAL_FX)
    evidence = _evidence(EvidenceGate.REAL_FX, policy)
    forged = ContractTestEvidence.model_construct(
        **evidence.model_dump(mode="python", exclude={"content_hash"}), content_hash="0" * 64
    )
    bundle = _resealed_bundle_copy(_bundle([evidence]), evidences=(forged,))
    with pytest.raises(Phase7EContractError):
        _verify(bundle, [policy])


def test_forged_primitive_json_bundle_rejected_at_boundary():
    policy = _policy(EvidenceGate.REAL_FX)
    evidence = _evidence(EvidenceGate.REAL_FX, policy)
    primitive = _bundle([evidence]).model_dump(mode="json")
    primitive["evidences"][0]["gate"] = EvidenceGate.LICENSING_LEGAL.value
    with pytest.raises(Phase7EContractError):
        _verify(primitive, [policy])


def test_fabricated_contract_child_results_are_not_an_aggregate_authority():
    forged = ContractGateVerification.model_construct(
        gate_states=tuple((g, GateState.VERIFIED) for g in EvidenceGate),
        contract_semantics_complete=True,
        trust_domain="CONTRACT_TEST_ONLY",
    )
    assert verify_real_external_evidence_bundle(forged).gate_states == _open_states_for_test()
    assert assess_phase7e_bundle(forged).gate_states == _open_states_for_test()
