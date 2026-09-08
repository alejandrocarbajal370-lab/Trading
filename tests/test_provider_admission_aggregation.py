import datetime as dt
import hashlib
import traceback

import pytest
from test_external_trust_backend import provisioning_graph, validate

from governance.ibkr_external_attestation import ProvisioningState
from governance.phase7e import EvidenceGate, GateState
from governance.provider_admission_aggregation import (
    AdmissionAggregationError,
    AdmissionEvidenceBundle,
    AggregationState,
    BoundObservationEvidence,
    GateEvidenceBinding,
    SufficientObservationPolicy,
    admit_real_provider,
    aggregate_contract_test_admission_evidence,
    seal_contract_test,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def aggregation_graph(*, count: int = 3):
    backend, manifest, binding, authenticity, provisioned_at = provisioning_graph()
    provisioning = validate(
        values=(backend, manifest, binding, authenticity, provisioned_at)
    )
    assessed_at = provisioned_at + dt.timedelta(minutes=30)
    policy = seal_contract_test(
        SufficientObservationPolicy,
        "policy_hash",
        policy_id="policy.ibkr.observations.v1",
        provider="provider.ibkr",
        adapter_id="adapter.ibkr.read-only",
        dataset_id="dataset.ibkr.ohlcv",
        security_master_id=binding.security_master_id,
        route_id="route.ibkr.external-verifier",
        minimum_distinct_observations=3,
        minimum_observation_span=dt.timedelta(minutes=20),
        maximum_observation_age=dt.timedelta(hours=2),
        maximum_verifier_skew=dt.timedelta(seconds=5),
        required_gates=tuple(EvidenceGate),
        approved_at=provisioned_at - dt.timedelta(minutes=1),
        effective_at=provisioned_at,
        expires_at=assessed_at + dt.timedelta(hours=1),
        policy_authority_reference_digest=digest("policy-authority"),
        rationale_digest=digest("three observations over twenty minutes"),
    )
    observations = tuple(
        seal_contract_test(
            BoundObservationEvidence,
            "evidence_hash",
            observation_id=f"observation.ibkr.{index}",
            provider=policy.provider,
            adapter_id=policy.adapter_id,
            dataset_id=policy.dataset_id,
            security_master_id=policy.security_master_id,
            con_id=272093,
            request_hash=binding.request_hash,
            observation_binding_hash=binding.binding_hash,
            authenticity_assessment_hash=authenticity.assessment_hash,
            provisioning_assessment_hash=provisioning.assessment_hash,
            entitlement_reference_hash=authenticity.entitlement_hash,
            route_id=policy.route_id,
            observed_at=assessed_at - dt.timedelta(minutes=30 - index * 10),
            authenticated_at=assessed_at - dt.timedelta(minutes=29 - index * 10),
            verifier_time=assessed_at,
            material_digest=digest(f"material-{index}"),
            provenance_digest=digest(f"provenance-{index}"),
            lineage_digest=digest(f"lineage-{index}"),
            custody_receipt_digest=digest(f"custody-{index}"),
        )
        for index in range(count)
    )
    gates = tuple(
        seal_contract_test(
            GateEvidenceBinding,
            "gate_hash",
            gate=gate,
            provider=policy.provider,
            dataset_id=policy.dataset_id,
            security_master_id=policy.security_master_id,
            con_id=272093,
            request_hash=binding.request_hash,
            route_id=policy.route_id,
            policy_hash=policy.policy_hash,
            external_evidence_digest=digest(f"external-{gate.value}"),
            authority_registry_digest=manifest.authority_registry_reference_digest,
            trust_anchor_digest=manifest.trust_anchor_reference_digest,
            independent_verifier_digest=digest("independent-verifier"),
            verified_at=assessed_at - dt.timedelta(seconds=1),
            expires_at=assessed_at + dt.timedelta(hours=1),
            mode=ProvisioningState.CONTRACT_TEST_ONLY,
        )
        for gate in EvidenceGate
    )
    bundle = seal_contract_test(
        AdmissionEvidenceBundle,
        "bundle_hash",
        provider=policy.provider,
        adapter_id=policy.adapter_id,
        dataset_id=policy.dataset_id,
        security_master_id=policy.security_master_id,
        con_id=272093,
        request_hash=binding.request_hash,
        authenticity_assessment_hash=authenticity.assessment_hash,
        entitlement_reference_hash=authenticity.entitlement_hash,
        route_id=policy.route_id,
        policy_hash=policy.policy_hash,
        backend_hash=backend.backend_hash,
        provisioning_manifest_hash=manifest.manifest_hash,
        provisioning_assessment_hash=provisioning.assessment_hash,
        observations=observations,
        gates=gates,
        assembled_at=assessed_at,
    )
    return policy, bundle, provisioning, assessed_at, manifest


def aggregate(values=None, **changes):
    values = values or aggregation_graph()
    keys = (
        "policy",
        "bundle",
        "provisioning_assessment",
        "assessed_at",
        "provisioning_manifest",
    )
    kwargs = dict(zip(keys, values, strict=True))
    kwargs.update(changes)
    return aggregate_contract_test_admission_evidence(**kwargs)


def reseal(value, model, field, **changes):
    raw = value.model_dump(mode="python", exclude={field})
    raw.update(changes)
    return seal_contract_test(model, field, **raw)


def test_policy_sufficiency_is_contract_only_and_never_real_admission():
    result = aggregate()
    assert result.state is AggregationState.CONTRACT_TEST_VALIDATED
    assert result.observations_sufficient_under_contract_policy is True
    assert {
        result.real_observations_verified,
        result.real_gate_closure,
        result.real_provider_admission,
    } == {ProvisioningState.NOT_PROVISIONED}
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert (result.real_route, result.global_readiness) == (
        "QVM_NOT_READY",
        "INSUFFICIENT_REAL_DATA",
    )
    assert (result.trade_decision, result.signals_generated, result.live_execution_enabled) == (
        "NO_TRADE",
        False,
        False,
    )
    assert result.backtesting == "NOT_AUTHORIZED"
    with pytest.raises(AdmissionAggregationError, match="NOT_PROVISIONED"):
        admit_real_provider(object())


def test_policy_is_explicit_versioned_governed_and_requires_all_gates():
    policy = aggregation_graph()[0]
    assert policy.policy_version == "governed-sufficient-observations-v1"
    assert policy.minimum_distinct_observations == 3
    assert policy.minimum_observation_span == dt.timedelta(minutes=20)
    assert policy.required_gates == tuple(EvidenceGate)
    for changes in (
        {"required_gates": tuple(EvidenceGate)[:-1]},
        {"minimum_distinct_observations": 1},
        {"minimum_observation_span": dt.timedelta(0)},
        {"maximum_observation_age": dt.timedelta(minutes=10)},
        {"maximum_verifier_skew": dt.timedelta(minutes=6)},
    ):
        with pytest.raises(AdmissionAggregationError):
            reseal(policy, SufficientObservationPolicy, "policy_hash", **changes)


def test_insufficient_count_span_and_duplicate_replay_fail_closed():
    values = aggregation_graph()
    observations = values[1].observations
    short = reseal(values[1], AdmissionEvidenceBundle, "bundle_hash", observations=observations[:2])
    with pytest.raises(AdmissionAggregationError):
        aggregate(values=values, bundle=short)
    with pytest.raises(AdmissionAggregationError):
        reseal(
            values[1],
            AdmissionEvidenceBundle,
            "bundle_hash",
            observations=(*observations[:2], observations[1]),
        )
    alias = reseal(
        observations[1],
        BoundObservationEvidence,
        "evidence_hash",
        observation_id="observation.ibkr.alias",
    )
    with pytest.raises(AdmissionAggregationError):
        reseal(
            values[1],
            AdmissionEvidenceBundle,
            "bundle_hash",
            observations=(*observations[:2], alias),
        )
    close = tuple(
        reseal(
            item,
            BoundObservationEvidence,
            "evidence_hash",
            observed_at=values[3] - dt.timedelta(minutes=3 - index),
            authenticated_at=values[3] - dt.timedelta(minutes=2 - index),
        )
        for index, item in enumerate(observations)
    )
    with pytest.raises(AdmissionAggregationError):
        aggregate(
            values=values,
            bundle=reseal(values[1], AdmissionEvidenceBundle, "bundle_hash", observations=close),
        )


@pytest.mark.parametrize(
    "field",
    (
        "provider",
        "adapter_id",
        "dataset_id",
        "security_master_id",
        "route_id",
        "policy_hash",
        "backend_hash",
        "provisioning_manifest_hash",
        "provisioning_assessment_hash",
        "authenticity_assessment_hash",
    ),
)
def test_cross_scope_and_upstream_swaps_fail_closed(field):
    values = aggregation_graph()
    replacement = {
        "provider": "provider.other",
        "adapter_id": "adapter.other.read-only",
        "dataset_id": "dataset.other.ohlcv",
        "security_master_id": "security.other",
        "route_id": "route.other.external-verifier",
    }.get(field, "0" * 64)
    with pytest.raises(AdmissionAggregationError):
        aggregate(
            values=values,
            bundle=reseal(
                values[1], AdmissionEvidenceBundle, "bundle_hash", **{field: replacement}
            ),
        )


@pytest.mark.parametrize(
    "field",
    (
        "con_id",
        "request_hash",
        "authenticity_assessment_hash",
        "provisioning_assessment_hash",
        "entitlement_reference_hash",
        "route_id",
    ),
)
def test_observation_security_request_authenticity_entitlement_and_route_swaps_fail(field):
    values = aggregation_graph()
    observations = list(values[1].observations)
    replacement = 999 if field == "con_id" else (
        "route.other.external-verifier" if field == "route_id" else "0" * 64
    )
    observations[1] = reseal(
        observations[1], BoundObservationEvidence, "evidence_hash", **{field: replacement}
    )
    bundle = reseal(
        values[1], AdmissionEvidenceBundle, "bundle_hash", observations=tuple(observations)
    )
    with pytest.raises(AdmissionAggregationError):
        aggregate(values=values, bundle=bundle)


def test_gate_reorder_omission_duplicate_cross_gate_and_partial_closure_fail_closed():
    values = aggregation_graph()
    gates = values[1].gates
    for forged in (gates[:-1], (*gates[:-1], gates[0]), tuple(reversed(gates))):
        with pytest.raises(AdmissionAggregationError):
            reseal(values[1], AdmissionEvidenceBundle, "bundle_hash", gates=forged)
    changed = list(gates)
    changed[0] = reseal(changed[0], GateEvidenceBinding, "gate_hash", request_hash="0" * 64)
    bundle = reseal(values[1], AdmissionEvidenceBundle, "bundle_hash", gates=tuple(changed))
    with pytest.raises(AdmissionAggregationError):
        aggregate(values=values, bundle=bundle)
    raw = aggregate(values).model_dump(mode="python")
    raw["gate_states"] = ((EvidenceGate.HISTORICAL_PIT_SECURITY_MASTER, GateState.VERIFIED),)
    with pytest.raises(AdmissionAggregationError):
        type(aggregate(values)).model_validate(raw)


@pytest.mark.parametrize("condition", ("future", "expired", "revoked", "mixed_time", "stale"))
def test_future_expired_revoked_mixed_time_and_stale_evidence_fail(condition):
    values = aggregation_graph()
    if condition in {"future", "expired", "revoked"}:
        gates = list(values[1].gates)
        changes = {
            "future": {"verified_at": values[3] + dt.timedelta(seconds=1)},
            "expired": {"expires_at": values[3]},
            "revoked": {"revoked_at": values[3]},
        }[condition]
        gates[0] = reseal(gates[0], GateEvidenceBinding, "gate_hash", **changes)
        bundle = reseal(values[1], AdmissionEvidenceBundle, "bundle_hash", gates=tuple(gates))
    else:
        observations = list(values[1].observations)
        changes = {
            "mixed_time": {"verifier_time": values[3] - dt.timedelta(minutes=1)},
            "stale": {
                "observed_at": values[3] - dt.timedelta(hours=3),
                "authenticated_at": values[3] - dt.timedelta(hours=2, minutes=59),
            },
        }[condition]
        observations[0] = reseal(
            observations[0], BoundObservationEvidence, "evidence_hash", **changes
        )
        bundle = reseal(
            values[1], AdmissionEvidenceBundle, "bundle_hash", observations=tuple(observations)
        )
    with pytest.raises(AdmissionAggregationError):
        aggregate(values=values, bundle=bundle)


def test_json_copy_construct_nested_primitives_extras_and_reseal_fail_closed():
    values = aggregation_graph()
    assert aggregate(
        policy=values[0].model_dump_json(),
        bundle=values[1].model_dump_json(),
        provisioning_assessment=values[2].model_dump_json(),
        assessed_at=values[3],
        provisioning_manifest=values[4].model_dump_json(),
    ).bundle_hash == values[1].bundle_hash
    raw = values[1].model_dump(mode="json")
    raw["observations"][0]["evidence_hash"] = "0" * 64
    with pytest.raises(AdmissionAggregationError):
        aggregate(values=values, bundle=raw)
    for forged in (
        values[1].model_copy(update={"route_id": "route.forged"}),
        AdmissionEvidenceBundle.model_construct(
            **{**values[1].model_dump(), "policy_hash": "0" * 64}
        ),
    ):
        with pytest.raises(AdmissionAggregationError):
            aggregate(values=values, bundle=forged)
    object.__setattr__(values[1], "secret", "never-show-this-secret")
    with pytest.raises(AdmissionAggregationError) as exc:
        aggregate(values=values)
    rendered = "".join(traceback.format_exception(exc.value))
    assert "never-show-this-secret" not in rendered
    assert exc.value.__cause__ is exc.value.__context__ is None


@pytest.mark.parametrize("value", ("Policy.MixedCase", "policy.\N{CYRILLIC SMALL LETTER A}"))
def test_unicode_confusable_and_noncanonical_aliases_fail_closed(value):
    policy = aggregation_graph()[0]
    with pytest.raises(AdmissionAggregationError):
        reseal(policy, SufficientObservationPolicy, "policy_hash", policy_id=value)


def test_market_connectivity_and_local_hashes_are_not_admission_inputs():
    fields = set(AdmissionEvidenceBundle.model_fields)
    assert not {"market_mode", "connected", "callback", "localhost", "credential"} & fields
    result = aggregate()
    assert result.real_provider_admission is ProvisioningState.NOT_PROVISIONED
    assert all(state is GateState.OPEN_EXTERNAL for _, state in result.gate_states)
