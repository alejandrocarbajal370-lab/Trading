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
    seal_contract_test,
)

UTC = dt.UTC
NOW = dt.datetime(2026, 9, 10, 2, 0, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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
            allowed_provider_refs=(f"opaque:provider.{observation_class.value.lower()}",),
            allowed_dataset_refs=(f"opaque:dataset.{observation_class.value.lower()}",),
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
        counting_semantics_version="semantic-identity-v1", status=status,
        created_at=NOW-dt.timedelta(days=2),
        reviewed_at=NOW-dt.timedelta(days=1) if approval else None,
        effective_from=NOW-dt.timedelta(hours=1), effective_to=NOW+dt.timedelta(days=1),
        jurisdiction_context_ref="opaque:jurisdiction.context.v1",
        use_context_ref="opaque:use.internal-research.v1", criteria=criteria,
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
            observations.append(seal_contract_test(
                ObservationEvidence, "evidence_hash",
                observation_ref=f"observation.{class_index}.{index}",
                policy_id=policy.policy_id, policy_version=policy.policy_version,
                policy_hash=policy.content_hash,
                counting_semantics_version=policy.counting_semantics_version,
                gate=criterion.gate, observation_class=observation_class,
                capability_id=criterion.capability_id,
                provider_ref=criterion.allowed_provider_refs[0],
                instrument_ref=f"opaque:instrument.{class_index}",
                dataset_ref=criterion.allowed_dataset_refs[0], observation_type="point-in-time",
                session_ref=f"session.{class_index}.{index}", session_date=start.date(),
                window_start=start, window_end=start+dt.timedelta(minutes=1),
                market_data_mode=criterion.allowed_modes[0], payload_digest=digest(f"p-{class_index}-{index}"),
                provenance_digest=digest(f"prov-{class_index}-{index}"),
                attestation_ref_digest=digest(f"att-{class_index}-{index}"),
                source_event_ref_digest=digest(f"event-{class_index}-{index}"),
                local_wrapper_digest=digest(f"wrapper-{class_index}-{index}"),
                present_provenance_fields=criterion.required_provenance_fields,
                missing_fraction_ppm=0, trust_state=DependencyState.CONTRACT_TEST_VALIDATED,
                authority_registry_state=DependencyState.CONTRACT_TEST_VALIDATED,
                legal_state=DependencyState.CONTRACT_TEST_VALIDATED,
                custody_state=DependencyState.CONTRACT_TEST_VALIDATED,
                dependency_valid_from=policy.effective_from,
                dependency_valid_to=policy.effective_to,
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


def test_same_window_different_payload_is_deterministic_review_and_not_counted():
    policy, pair, rest = market_pair()
    conflict = reseal(pair[0], ObservationEvidence, "evidence_hash",
                      observation_ref="observation.conflict", payload_digest=digest("different"))
    first = market_result(assess(policy, (*rest, *pair, conflict)))
    second = market_result(assess(policy, tuple(reversed((*rest, *pair, conflict)))))
    assert first == second
    assert first.state is EvaluationState.REVIEW_REQUIRED
    assert first.accepted_count == 1
    assert ReasonCode.SAME_WINDOW_CONFLICT in first.reason_codes


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("provider_ref", "opaque:provider.other", ReasonCode.PROVIDER_MISMATCH),
        ("dataset_ref", "opaque:dataset.other", ReasonCode.DATASET_MISMATCH),
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
          "session_date": NOW.date()}, ReasonCode.FUTURE_OBSERVATION),
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
    v2 = reseal(policy, SufficientObservationPolicy, "content_hash",
                policy_version="v2", counting_semantics_version="semantic-identity-v2")
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


@pytest.mark.parametrize(
    ("field", "state", "reason", "expected"),
    [
        ("trust_state", DependencyState.NOT_PROVISIONED, ReasonCode.TRUST_NOT_PROVISIONED,
         EvaluationState.NOT_PROVISIONED),
        ("trust_state", DependencyState.REVOKED, ReasonCode.TRUST_REVIEW_REQUIRED,
         EvaluationState.REVIEW_REQUIRED),
        ("authority_registry_state", DependencyState.EXPIRED, ReasonCode.TRUST_REVIEW_REQUIRED,
         EvaluationState.REVIEW_REQUIRED),
        ("legal_state", DependencyState.NOT_PROVISIONED, ReasonCode.LEGAL_NOT_PROVISIONED,
         EvaluationState.NOT_PROVISIONED),
        ("custody_state", DependencyState.NOT_PROVISIONED, ReasonCode.CUSTODY_NOT_PROVISIONED,
         EvaluationState.NOT_PROVISIONED),
    ],
)
def test_missing_expired_or_revoked_dependencies_fail_closed(field, state, reason, expected):
    policy, pair, rest = market_pair()
    changed = reseal(pair[0], ObservationEvidence, "evidence_hash", **{field: state})
    gate = market_result(assess(policy, (*rest, changed, pair[1])))
    assert reason in gate.reason_codes and gate.state is expected


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
