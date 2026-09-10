import concurrent.futures
import datetime as dt
import hashlib

import pytest
from pydantic import BaseModel

from governance.ibkr_external_attestation import ProvisioningState
from governance.phase7e import EvidenceGate, GateState
from governance.sufficient_observation_policy import (
    CLASS_GATE,
    CONTRACT_VERSION,
    COUNTING_SEMANTICS_VERSION,
    DEPENDENCY_CONTRACTS,
    DependencyArtifactReference,
    DependencyAssurance,
    DependencyKind,
    DependencyState,
    EvaluationState,
    GateCriterion,
    MarketDataMode,
    ObservationClass,
    ObservationEvidence,
    ObservationPolicyError,
    PolicyStatus,
    ReasonCode,
    SufficiencyAssessment,
    SufficientObservationPolicy,
    admit_real_policy,
    evaluate_sufficiency,
    opaque_reference,
    seal_contract_test,
)

UTC = dt.UTC
NOW = dt.datetime(2026, 9, 10, 2, 0, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def opaque(value: str) -> str:
    return opaque_reference(value)


def dependency(kind, *, provider, dataset, route, entity, capability, policy, index,
               source_event, payload, available_at=None, verified_at=None, expires_at=None,
               revoked_at=None):
    source_contract, source_contract_version = DEPENDENCY_CONTRACTS[kind]
    return seal_contract_test(
        DependencyArtifactReference, "reference_hash", kind=kind,
        source_contract=source_contract, source_contract_version=source_contract_version,
        artifact_digest=digest(f"artifact-{kind}-{index}"), provider_ref=provider,
        source_event_ref_digest=source_event, payload_digest=payload,
        dataset_ref=dataset, route_ref=route, entity_ref=entity, capability_id=capability,
        policy_id=policy.policy_id, policy_version=policy.policy_version,
        available_at=available_at or NOW-dt.timedelta(minutes=55),
        effective_at=NOW-dt.timedelta(minutes=50),
        verified_at=verified_at or NOW-dt.timedelta(minutes=45),
        expires_at=expires_at or NOW+dt.timedelta(days=1), revoked_at=revoked_at,
        assurance=DependencyAssurance.CONTRACT_TEST_ONLY,
    )


def reseal(value, model, field, **changes):
    raw = BaseModel.model_dump(value, mode="python", exclude={field})
    raw.update(changes)
    return seal_contract_test(model, field, **raw)


def graph(*, status=PolicyStatus.APPROVED_FOR_EVIDENCE_COLLECTION):
    criteria = []
    for observation_class in ObservationClass:
        gate = CLASS_GATE[observation_class]
        mode = (MarketDataMode.DELAYED, MarketDataMode.REALTIME) if observation_class in {
            ObservationClass.REAL_MARKET, ObservationClass.FX
        } else (MarketDataMode.NOT_APPLICABLE,)
        criteria.append(seal_contract_test(
            GateCriterion, "criterion_hash",
            criterion_id=f"criterion.{observation_class.value.lower()}.v1",
            gate=gate, observation_class=observation_class,
            capability_id=f"capability.{observation_class.value.lower()}",
            allowed_provider_refs=(opaque(f"provider.{observation_class.value.lower()}"),),
            allowed_dataset_refs=(opaque(f"dataset.{observation_class.value.lower()}"),),
            allowed_modes=mode, minimum_observation_count=2,
            minimum_distinct_sessions=2, minimum_distinct_dates=1,
            minimum_time_span=dt.timedelta(minutes=10),
            maximum_age=dt.timedelta(hours=2), maximum_missing_fraction_ppm=0,
            required_provenance_fields=("source", "attestation", "lineage"),
            minimum_trust_state=DependencyState.CONTRACT_TEST_VALIDATED,
            require_authority_registry=True, require_legal_rights=True,
            require_custody_worm_replay=True, rationale_digest=digest("provisional governed v1"),
        ))
    criteria = tuple(sorted(criteria, key=lambda item: item.gate.value))
    approval = status is PolicyStatus.APPROVED_FOR_EVIDENCE_COLLECTION
    policy = seal_contract_test(
        SufficientObservationPolicy, "content_hash",
        policy_id="policy.sufficient-observations", policy_version="v1",
        counting_semantics_version=COUNTING_SEMANTICS_VERSION, status=status,
        created_at=NOW-dt.timedelta(days=2),
        reviewed_at=NOW-dt.timedelta(days=1) if approval else None,
        effective_from=NOW-dt.timedelta(hours=1), effective_to=NOW+dt.timedelta(days=1),
        jurisdiction_context_ref=opaque("jurisdiction.context.v1"),
        use_context_ref=opaque("use.internal-research.v1"), criteria=criteria,
        maker_actor_hash=digest("maker"), reviewer_actor_hash=digest("reviewer") if approval else None,
        approver_actor_hash=digest("approver") if approval else None,
        review_evidence_digest=digest("review") if approval else None,
        exception_policy_ref="policy.exception.requires-review.v1",
    )
    observations = []
    for class_index, observation_class in enumerate(ObservationClass):
        criterion = next(x for x in criteria if x.observation_class is observation_class)
        for index in range(2):
            start = NOW - dt.timedelta(minutes=40 - index * 20)
            provider = criterion.allowed_provider_refs[0]
            dataset = criterion.allowed_dataset_refs[0]
            entity = opaque(f"instrument.{class_index}")
            route = opaque(f"route.{class_index}")
            source_event = digest(f"event-{class_index}-{index}")
            payload = digest(f"p-{class_index}-{index}")
            artifacts = tuple(dependency(
                kind, provider=provider, dataset=dataset, route=route, entity=entity,
                capability=criterion.capability_id, policy=policy,
                index=f"{class_index}-{index}-{kind.value}",
                source_event=source_event, payload=payload,
            ) for kind in DependencyKind)
            observations.append(seal_contract_test(
                ObservationEvidence, "evidence_hash",
                observation_ref=f"observation.{class_index}.{index}",
                policy_id=policy.policy_id, policy_version=policy.policy_version,
                policy_hash=policy.content_hash,
                counting_semantics_version=policy.counting_semantics_version,
                gate=criterion.gate, observation_class=observation_class,
                capability_id=criterion.capability_id,
                provider_ref=provider, instrument_ref=entity,
                dataset_ref=dataset, route_ref=route, observation_type="point-in-time",
                session_ref=f"session.{class_index}.{index}", session_date=start.date(),
                window_start=start, window_end=start+dt.timedelta(minutes=1),
                available_at=start+dt.timedelta(minutes=2),
                market_data_mode=criterion.allowed_modes[0], payload_digest=payload,
                provenance_digest=digest(f"prov-{class_index}-{index}"),
                attestation_ref_digest=digest(f"att-{class_index}-{index}"),
                source_event_ref_digest=source_event,
                local_wrapper_digest=digest(f"wrapper-{class_index}-{index}"),
                present_provenance_fields=criterion.required_provenance_fields,
                missing_fraction_ppm=0, dependency_artifacts=artifacts,
            ))
    return policy, tuple(observations)


def assess(policy=None, observations=None):
    base_policy, base_observations = graph()
    return evaluate_sufficiency(
        policy=policy or base_policy, observations=observations or base_observations, assessed_at=NOW
    )


def market_pair():
    policy, observations = graph()
    pair = tuple(x for x in observations if x.observation_class is ObservationClass.REAL_MARKET)
    rest = tuple(x for x in observations if x.observation_class is not ObservationClass.REAL_MARKET)
    return policy, pair, rest


def market_result(result):
    return next(x for x in result.gate_results if x.gate is EvidenceGate.HISTORICAL_PIT_SECURITY_MASTER)


def test_foundation_can_only_reach_conservative_pre_verification_state():
    result = assess()
    assert result.state is EvaluationState.SUFFICIENT_FOR_EXTERNAL_VERIFICATION
    assert result.contract_validation_state == "CONTRACT_TEST_VALIDATED"
    assert result.real_policy_approval is ProvisioningState.NOT_PROVISIONED
    assert result.real_provider_admission is ProvisioningState.NOT_PROVISIONED
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert (result.real_route, result.global_readiness, result.trade_decision) == (
        "QVM_NOT_READY", "INSUFFICIENT_REAL_DATA", "NO_TRADE"
    )
    assert not result.signals_generated and not result.live_execution_enabled
    assert result.backtesting == "NOT_AUTHORIZED"
    with pytest.raises(ObservationPolicyError, match="NOT_PROVISIONED"):
        admit_real_policy(object())


def test_policy_is_versioned_content_addressed_gate_specific_and_provisional():
    policy, _ = graph()
    assert policy.contract_version == CONTRACT_VERSION
    assert {x.observation_class for x in policy.criteria} == set(ObservationClass)
    assert len({x.gate for x in policy.criteria}) == 7
    assert all(x.rationale_digest for x in policy.criteria)
    with pytest.raises(ObservationPolicyError):
        reseal(policy, SufficientObservationPolicy, "content_hash", criteria=policy.criteria[:-1])


def test_maker_checker_requires_three_distinct_actors_and_review_evidence():
    policy, _ = graph()
    for changes in (
        {"reviewer_actor_hash": policy.maker_actor_hash},
        {"approver_actor_hash": policy.reviewer_actor_hash},
        {"review_evidence_digest": None},
    ):
        with pytest.raises(ObservationPolicyError):
            reseal(policy, SufficientObservationPolicy, "content_hash", **changes)


def test_duplicate_and_new_local_wrapper_do_not_increase_count():
    policy, pair, rest = market_pair()
    alias = reseal(pair[0], ObservationEvidence, "evidence_hash",
                   observation_ref="observation.alias", local_wrapper_digest=digest("new wrapper"))
    result = assess(policy, (*rest, *pair, pair[0], alias))
    gate = market_result(result)
    assert gate.accepted_count == 2 and gate.duplicate_count == 2
    assert ReasonCode.DUPLICATE_OBSERVATION in gate.reason_codes


@pytest.mark.parametrize("field", [
    "provenance_digest", "attestation_ref_digest", "local_wrapper_digest",
])
def test_same_source_event_different_representation_counts_once(field):
    policy, pair, rest = market_pair()
    alias = reseal(pair[0], ObservationEvidence, "evidence_hash",
                   observation_ref=f"observation.alias.{field}", **{field: digest(field)})
    gate = market_result(assess(policy, (*rest, *pair, alias)))
    assert gate.accepted_count == 2 and gate.duplicate_count == 1
    assert ReasonCode.DUPLICATE_OBSERVATION in gate.reason_codes


@pytest.mark.parametrize("changes", [
    {"payload_digest": digest("changed-payload")},
    {"window_start": NOW-dt.timedelta(minutes=39),
     "window_end": NOW-dt.timedelta(minutes=38), "session_date": NOW.date(),
     "session_ref": "session.shifted"},
    {"payload_digest": digest("everything-payload"),
     "provenance_digest": digest("everything-provenance"),
     "attestation_ref_digest": digest("everything-attestation"),
     "local_wrapper_digest": digest("everything-wrapper"),
     "window_start": NOW-dt.timedelta(minutes=39),
     "window_end": NOW-dt.timedelta(minutes=38), "session_date": NOW.date(),
     "session_ref": "session.everything"},
])
def test_same_source_event_semantic_conflict_is_excluded_and_deterministic(changes):
    policy, pair, rest = market_pair()
    if "payload_digest" in changes:
        changes = {**changes, "dependency_artifacts": tuple(
            reseal(x, DependencyArtifactReference, "reference_hash",
                   payload_digest=changes["payload_digest"]) for x in pair[0].dependency_artifacts
        )}
    conflict = reseal(pair[0], ObservationEvidence, "evidence_hash",
                      observation_ref="observation.conflicting-representation", **changes)
    values = (*rest, *pair, conflict)
    first = market_result(assess(policy, values))
    second = market_result(assess(policy, tuple(reversed(values))))
    assert first == second
    assert first.state is EvaluationState.REVIEW_REQUIRED and first.accepted_count == 1
    assert first.distinct_sessions == 1 and first.distinct_dates == 1
    assert ReasonCode.SAME_WINDOW_CONFLICT in first.reason_codes


def test_source_event_identity_is_required_and_cross_provider_aggregation_is_explicit():
    policy, pair, rest = market_pair()
    with pytest.raises(ObservationPolicyError):
        reseal(pair[0], ObservationEvidence, "evidence_hash", source_event_ref_digest="")
    criterion = next(x for x in policy.criteria if x.observation_class is ObservationClass.REAL_MARKET)
    second_provider = opaque("provider.second")
    changed_criterion = reseal(
        criterion, GateCriterion, "criterion_hash",
        allowed_provider_refs=tuple(sorted((*criterion.allowed_provider_refs, second_provider))),
        allow_cross_provider_aggregation=True,
    )
    changed_policy = reseal(
        policy, SufficientObservationPolicy, "content_hash",
        criteria=tuple(changed_criterion if x is criterion else x for x in policy.criteria),
    )
    rebound = tuple(reseal(x, ObservationEvidence, "evidence_hash",
                           policy_hash=changed_policy.content_hash) for x in (*rest, *pair))
    other_artifacts = tuple(reseal(
        artifact, DependencyArtifactReference, "reference_hash", provider_ref=second_provider
    ) for artifact in rebound[-2].dependency_artifacts)
    cross_provider = reseal(
        rebound[-2], ObservationEvidence, "evidence_hash", observation_ref="observation.cross-provider",
        provider_ref=second_provider, dependency_artifacts=other_artifacts,
    )
    gate = market_result(assess(changed_policy, (*rebound, cross_provider)))
    assert gate.accepted_count == 3


def test_cross_provider_events_do_not_combine_without_policy_permission():
    policy, pair, rest = market_pair()
    criterion = next(x for x in policy.criteria if x.observation_class is ObservationClass.REAL_MARKET)
    second_provider = opaque("provider.second")
    changed_criterion = reseal(
        criterion, GateCriterion, "criterion_hash",
        allowed_provider_refs=tuple(sorted((*criterion.allowed_provider_refs, second_provider))),
    )
    changed_policy = reseal(
        policy, SufficientObservationPolicy, "content_hash",
        criteria=tuple(changed_criterion if x is criterion else x for x in policy.criteria),
    )
    rebound = tuple(reseal(x, ObservationEvidence, "evidence_hash",
                           policy_hash=changed_policy.content_hash) for x in (*rest, *pair))
    artifacts = tuple(reseal(x, DependencyArtifactReference, "reference_hash",
                             provider_ref=second_provider) for x in rebound[-2].dependency_artifacts)
    cross = reseal(rebound[-2], ObservationEvidence, "evidence_hash",
                   observation_ref="observation.cross-provider.denied", provider_ref=second_provider,
                   dependency_artifacts=artifacts)
    gate = market_result(assess(changed_policy, (*rebound, cross)))
    assert gate.accepted_count == 0 and ReasonCode.PROVIDER_MISMATCH in gate.reason_codes


def test_same_window_different_payload_is_deterministic_review_and_not_counted():
    policy, pair, rest = market_pair()
    changed_payload = digest("different")
    conflict = reseal(pair[0], ObservationEvidence, "evidence_hash",
                      observation_ref="observation.conflict", payload_digest=changed_payload,
                      dependency_artifacts=tuple(reseal(
                          x, DependencyArtifactReference, "reference_hash",
                          payload_digest=changed_payload,
                      ) for x in pair[0].dependency_artifacts))
    first = market_result(assess(policy, (*rest, *pair, conflict)))
    second = market_result(assess(policy, tuple(reversed((*rest, *pair, conflict)))))
    assert first == second
    assert first.state is EvaluationState.REVIEW_REQUIRED
    assert first.accepted_count == 1
    assert ReasonCode.SAME_WINDOW_CONFLICT in first.reason_codes


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("provider_ref", opaque("provider.other"), ReasonCode.PROVIDER_MISMATCH),
        ("dataset_ref", opaque("dataset.other"), ReasonCode.DATASET_MISMATCH),
        ("market_data_mode", MarketDataMode.NOT_APPLICABLE, ReasonCode.MODE_MISMATCH),
        ("capability_id", "capability.other", ReasonCode.SCOPE_MISMATCH),
    ],
)
def test_cross_scope_and_mode_mismatch_rejected(field, value, reason):
    policy, pair, rest = market_pair()
    changed = reseal(pair[0], ObservationEvidence, "evidence_hash", **{field: value})
    gate = market_result(assess(policy, (*rest, changed, pair[1])))
    assert gate.accepted_count == 1 and reason in gate.reason_codes


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"window_start": NOW + dt.timedelta(minutes=1), "window_end": NOW + dt.timedelta(minutes=2),
          "available_at": NOW + dt.timedelta(minutes=3), "session_date": NOW.date()},
         ReasonCode.FUTURE_OBSERVATION),
        ({"window_start": NOW-dt.timedelta(hours=4), "window_end": NOW-dt.timedelta(hours=4)+dt.timedelta(minutes=1),
          "session_date": (NOW-dt.timedelta(hours=4)).date()},
         ReasonCode.BEFORE_POLICY_EFFECTIVE),
    ],
)
def test_future_and_before_policy_observations_rejected(changes, reason):
    policy, pair, rest = market_pair()
    changed = reseal(pair[0], ObservationEvidence, "evidence_hash", **changes)
    gate = market_result(assess(policy, (*rest, changed, pair[1])))
    assert reason in gate.reason_codes and gate.accepted_count == 1


def test_stale_observation_rejected_under_governed_maximum_age():
    policy, pair, rest = market_pair()
    criterion = next(x for x in policy.criteria if x.observation_class is ObservationClass.REAL_MARKET)
    changed_criterion = reseal(criterion, GateCriterion, "criterion_hash",
                               maximum_age=dt.timedelta(minutes=20))
    criteria = tuple(changed_criterion if x is criterion else x for x in policy.criteria)
    changed_policy = reseal(policy, SufficientObservationPolicy, "content_hash", criteria=criteria)
    rebound = tuple(reseal(x, ObservationEvidence, "evidence_hash",
                           policy_hash=changed_policy.content_hash) for x in (*rest, *pair))
    gate = market_result(assess(changed_policy, rebound))
    assert ReasonCode.STALE_OBSERVATION in gate.reason_codes


def test_materially_changed_v2_does_not_silently_reuse_v1_evidence():
    policy, observations = graph()
    v2 = reseal(policy, SufficientObservationPolicy, "content_hash", policy_version="v2")
    result = evaluate_sufficiency(policy=v2, observations=observations, assessed_at=NOW)
    assert result.state is EvaluationState.REVIEW_REQUIRED
    assert all(ReasonCode.POLICY_VERSION_MISMATCH in x.reason_codes for x in result.gate_results)


def test_expired_replaced_or_revoked_policy_invalidates_future_counting():
    policy, observations = graph()
    variants = (
        reseal(policy, SufficientObservationPolicy, "content_hash", effective_to=NOW),
        reseal(policy, SufficientObservationPolicy, "content_hash",
               replacement_policy_hash=digest("replacement")),
        reseal(policy, SufficientObservationPolicy, "content_hash",
               revoked_at=NOW, revocation_evidence_digest=digest("revocation")),
    )
    for unavailable in variants:
        rebound = tuple(reseal(x, ObservationEvidence, "evidence_hash",
                               policy_hash=unavailable.content_hash) for x in observations)
        result = evaluate_sufficiency(policy=unavailable, observations=rebound, assessed_at=NOW)
        assert result.state is EvaluationState.REVIEW_REQUIRED
        assert all(ReasonCode.OUTSIDE_POLICY_WINDOW in x.reason_codes for x in result.gate_results)


@pytest.mark.parametrize("kind,reason", [
    (DependencyKind.TRUST_VERIFIER, ReasonCode.TRUST_NOT_PROVISIONED),
    (DependencyKind.AUTHORITY_REGISTRY, ReasonCode.TRUST_NOT_PROVISIONED),
    (DependencyKind.LEGAL_RIGHT, ReasonCode.LEGAL_NOT_PROVISIONED),
    (DependencyKind.CUSTODY_WORM_REPLAY, ReasonCode.CUSTODY_NOT_PROVISIONED),
])
def test_missing_dependency_artifacts_fail_closed(kind, reason):
    policy, pair, rest = market_pair()
    changed = reseal(pair[0], ObservationEvidence, "evidence_hash",
                     dependency_artifacts=tuple(x for x in pair[0].dependency_artifacts
                                                if x.kind is not kind))
    gate = market_result(assess(policy, (*rest, changed, pair[1])))
    assert reason in gate.reason_codes and gate.state is EvaluationState.NOT_PROVISIONED


def test_naked_dependency_enums_and_fabricated_digest_cannot_create_truth():
    _, pair, _ = market_pair()
    raw = BaseModel.model_dump(pair[0], mode="python", exclude={"evidence_hash"})
    raw["trust_state"] = DependencyState.EXTERNALLY_VERIFIED
    with pytest.raises(ObservationPolicyError):
        seal_contract_test(ObservationEvidence, "evidence_hash", **raw)
    artifact = pair[0].dependency_artifacts[0]
    with pytest.raises(ObservationPolicyError):
        artifact.model_copy(update={"artifact_digest": digest("fabricated")})


@pytest.mark.parametrize("field,value", [
    ("provider_ref", opaque("wrong-provider")), ("dataset_ref", opaque("wrong-dataset")),
    ("route_ref", opaque("wrong-route")), ("entity_ref", opaque("wrong-entity")),
    ("capability_id", "capability.wrong"),
    ("source_event_ref_digest", digest("wrong-event")),
    ("payload_digest", digest("wrong-payload")),
])
def test_dependency_scope_bindings_are_enforced(field, value):
    policy, pair, rest = market_pair()
    artifacts = list(pair[0].dependency_artifacts)
    artifacts[0] = reseal(artifacts[0], DependencyArtifactReference, "reference_hash",
                          **{field: value})
    changed = reseal(pair[0], ObservationEvidence, "evidence_hash",
                     dependency_artifacts=tuple(artifacts))
    gate = market_result(assess(policy, (*rest, changed, pair[1])))
    assert gate.accepted_count == 1
    assert ReasonCode.DEPENDENCY_BINDING_MISMATCH in gate.reason_codes


def test_wrong_dependency_contract_is_rejected_at_construction():
    _, pair, _ = market_pair()
    artifact = pair[0].dependency_artifacts[0]
    with pytest.raises(ObservationPolicyError):
        reseal(artifact, DependencyArtifactReference, "reference_hash",
               source_contract="licensing-legal-governance", source_contract_version="v2")


@pytest.mark.parametrize("changes", [
    {"expires_at": NOW}, {"revoked_at": NOW-dt.timedelta(minutes=1)},
    {"available_at": NOW+dt.timedelta(seconds=1),
     "effective_at": NOW+dt.timedelta(seconds=2),
     "verified_at": NOW+dt.timedelta(seconds=3),
     "expires_at": NOW+dt.timedelta(days=1)},
])
def test_stale_revoked_or_future_dependency_is_rejected_as_of_assessment(changes):
    policy, pair, rest = market_pair()
    artifacts = list(pair[0].dependency_artifacts)
    artifacts[0] = reseal(artifacts[0], DependencyArtifactReference, "reference_hash", **changes)
    changed = reseal(pair[0], ObservationEvidence, "evidence_hash",
                     dependency_artifacts=tuple(artifacts))
    gate = market_result(assess(policy, (*rest, changed, pair[1])))
    assert gate.accepted_count == 1 and gate.state is EvaluationState.REVIEW_REQUIRED


def test_missingness_and_provenance_never_silently_fallback():
    policy, pair, rest = market_pair()
    for changes, reason in (
        ({"missing_fraction_ppm": 1}, ReasonCode.MISSINGNESS_EXCEEDED),
        ({"present_provenance_fields": ("source",)}, ReasonCode.MISSING_PROVENANCE),
    ):
        changed = reseal(pair[0], ObservationEvidence, "evidence_hash", **changes)
        assert reason in market_result(assess(policy, (*rest, changed, pair[1]))).reason_codes


def test_draft_policy_requires_review_and_cannot_self_promote():
    draft, observations = graph(status=PolicyStatus.DRAFT)
    rebound = tuple(reseal(x, ObservationEvidence, "evidence_hash", policy_hash=draft.content_hash)
                    for x in observations)
    assert assess(draft, rebound).state is EvaluationState.REVIEW_REQUIRED
    with pytest.raises(ObservationPolicyError):
        draft.model_copy(update={"status": PolicyStatus.APPROVED_FOR_EVIDENCE_COLLECTION})


def test_copy_construct_json_and_reseal_cannot_fabricate_real_or_gate_closure():
    result = assess()
    forbidden = {"real_policy_approval": "PROVISIONED", "real_provider_admission": "PROVISIONED"}
    for operation in (
        lambda: result.model_copy(update=forbidden),
        lambda: SufficiencyAssessment.model_construct(**{
            **BaseModel.model_dump(result, mode="python"), **forbidden
        }),
        lambda: SufficiencyAssessment.model_validate_json(result.model_dump_json().replace(
            "NOT_PROVISIONED", "PROVISIONED", 1
        )),
        lambda: reseal(result, SufficiencyAssessment, "assessment_hash",
                       gate_states=((EvidenceGate.REAL_FX, GateState.VERIFIED),)),
    ):
        with pytest.raises(ObservationPolicyError):
            operation()


def test_input_order_and_parallel_evaluations_are_stable_and_never_double_count():
    policy, observations = graph()
    expected = assess(policy, observations)
    orders = (observations, tuple(reversed(observations)), observations[::2] + observations[1::2])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda value: assess(policy, value), orders))
    assert all(result == expected for result in results)


def test_serialization_and_errors_do_not_reflect_hostile_sensitive_input():
    policy, _ = graph()
    secret = "RFC-SENSITIVE-SECRET-123"
    with pytest.raises(ObservationPolicyError) as captured:
        SufficientObservationPolicy.model_validate({
            **BaseModel.model_dump(policy, mode="python"), "jurisdiction_context_ref": secret
        })
    assert secret not in str(captured.value) and secret not in repr(captured.value)
    assert secret not in repr(policy) and secret not in str(policy)
    assert secret not in policy.model_dump_json()


@pytest.mark.parametrize("secret", [
    "RFC-CAGJ900101ABC", "account-U1234567", "passport-G12345678",
    "1600 Pennsylvania Avenue", "token-sk-sensitive-value",
])
def test_raw_sensitive_refs_fail_without_retention_or_echo(secret):
    policy, pair, _ = market_pair()
    raw = BaseModel.model_dump(pair[0], mode="python", exclude={"evidence_hash"})
    raw["provider_ref"] = secret
    with pytest.raises(ObservationPolicyError) as captured:
        seal_contract_test(ObservationEvidence, "evidence_hash", **raw)
    assert secret not in str(captured.value) and secret not in repr(captured.value)
    sanctioned = opaque_reference(secret)
    assert sanctioned == opaque_reference(secret) and secret not in sanctioned
    assert sanctioned.startswith("opaque:v1:") and len(sanctioned) == 74
    assert secret not in repr(policy) and secret not in policy.model_dump_json()


def test_evidence_availability_is_point_in_time_and_boundary_is_inclusive():
    policy, pair, rest = market_pair()
    after = reseal(pair[0], ObservationEvidence, "evidence_hash",
                   available_at=NOW+dt.timedelta(microseconds=1))
    gate = market_result(assess(policy, (*rest, after, pair[1])))
    assert gate.accepted_count == 1
    assert ReasonCode.EVIDENCE_NOT_AVAILABLE_AS_OF in gate.reason_codes
    boundary = reseal(pair[0], ObservationEvidence, "evidence_hash", available_at=NOW)
    assert market_result(assess(policy, (*rest, boundary, pair[1]))).accepted_count == 2


def test_impossible_or_non_utc_availability_fails_closed():
    _, pair, _ = market_pair()
    for value in (pair[0].window_end-dt.timedelta(microseconds=1), NOW.replace(tzinfo=None),
                  NOW.astimezone(dt.timezone(dt.timedelta(hours=-6)))):
        with pytest.raises(ObservationPolicyError):
            reseal(pair[0], ObservationEvidence, "evidence_hash", available_at=value)
