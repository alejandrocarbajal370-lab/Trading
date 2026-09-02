import datetime as dt

import pytest
from pydantic import ValidationError

from governance.external_provider_foundation import (
    AdapterId,
    AttestationState,
    CanonicalRoute,
    ContractTestAdapter,
    DatasetId,
    EvidenceState,
    FoundationError,
    FoundationResult,
    NotProvisionedAttestationVerifier,
    NotProvisionedDurableReplay,
    NotProvisionedIndependentVerifier,
    ProviderId,
    ProviderRegistry,
    _seal,
    build_contract_test_context,
    evaluate_real_foundation,
    observe_material,
    validate_foundation_result,
)
from governance.phase7e import EvidenceGate, GateState

NOW = dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC)


def result():
    return build_contract_test_context().evaluate(
        adapter=ContractTestAdapter(), observed_at=NOW, handed_off_at=NOW + dt.timedelta(seconds=1)
    )


def test_all_gates_are_canonically_bound_and_safety_state_is_frozen():
    value = result()
    assert tuple(item.route.gate for item in value.handoffs) == tuple(EvidenceGate)
    assert value.evidence_states == (EvidenceState.OBSERVED,) * 10
    assert value.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert value.trust_root == value.durable_replay == value.independent_verifier == "NOT_PROVISIONED"
    assert value.real_route == "QVM_NOT_READY"
    assert value.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert value.trade_decision == "NO_TRADE"
    assert value.live_execution_enabled is value.signals_generated is False
    assert value.backtesting == "NOT_AUTHORIZED"


@pytest.mark.parametrize("promoted", [EvidenceState.VERIFIED, EvidenceState.TRUSTED, EvidenceState.CLOSED])
def test_adapter_or_caller_cannot_promote_observation(promoted):
    raw = result().model_dump(mode="json")
    raw["evidence_states"][0] = promoted.value
    raw["result_hash"] = "0" * 64
    with pytest.raises(FoundationError):
        validate_foundation_result(raw)


@pytest.mark.parametrize("gate", tuple(EvidenceGate))
def test_cross_gate_route_swaps_fail_even_when_hashes_are_recomputed(gate):
    canonical = ProviderRegistry.resolve(gate)
    other_gate = next(item for item in EvidenceGate if item is not gate)
    raw = canonical.model_dump(mode="python")
    raw["gate"] = other_gate
    raw.pop("route_hash")
    with pytest.raises(ValidationError):
        _seal(CanonicalRoute, "route_hash", **raw)


@pytest.mark.parametrize("field,value", [
    ("provider", "provider.password=hunter2"),
    ("dataset", "dataset.secret=token"),
    ("adapter", "adapter.api_key=plausible"),
])
def test_arbitrary_identity_strings_are_rejected_and_not_serialized(field, value):
    raw = ProviderRegistry.resolve(EvidenceGate.REAL_FX).model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        type(ProviderRegistry.resolve(EvidenceGate.REAL_FX)).model_validate(raw)
    assert value not in result().model_dump_json()


def test_material_and_provenance_digests_are_computed_at_boundary():
    route = ProviderRegistry.resolve(EvidenceGate.REAL_FX)
    observed = observe_material(route, b"material", b"provenance", NOW)
    assert observed.state is EvidenceState.OBSERVED
    assert observed.material_digest != observed.provenance_digest
    with pytest.raises(FoundationError):
        observe_material(route, b"", b"provenance", NOW)


def test_stale_or_recomputed_hash_never_creates_authenticity():
    value = result()
    handoff = value.handoffs[0]
    assert handoff.evidence_state is EvidenceState.OBSERVED
    assert handoff.attestation.state is AttestationState.NOT_PROVISIONED
    forged = handoff.model_copy(update={"evidence_state": EvidenceState.TRUSTED})
    with pytest.raises(FoundationError):
        validate_foundation_result(value.model_copy(update={"handoffs": (forged, *value.handoffs[1:])}))


@pytest.mark.parametrize("field", ["observation_hash", "material_digest", "provenance_digest"])
def test_resealed_handoff_cannot_break_observation_binding(field):
    value = result()
    handoff = value.handoffs[0]
    raw = handoff.model_dump(mode="python")
    raw[field] = "f" * 64
    raw.pop("handoff_hash")
    with pytest.raises(ValidationError, match="observation_hash does not bind"):
        _seal(type(handoff), "handoff_hash", **raw)


def test_attestation_hook_cannot_be_caller_promoted():
    observed = observe_material(ProviderRegistry.resolve(EvidenceGate.REAL_FX), b"m", b"p", NOW)
    attestation = NotProvisionedAttestationVerifier().verify(observed)
    assert attestation.state is AttestationState.NOT_PROVISIONED
    with pytest.raises(ValidationError):
        type(attestation).model_validate({**attestation.model_dump(), "state": "VERIFIED"})


def test_real_route_rejects_contract_fake_and_all_substitution():
    with pytest.raises(FoundationError, match="cannot be substituted"):
        evaluate_real_foundation(
            adapter=ContractTestAdapter(), replay=NotProvisionedDurableReplay(), verifier=NotProvisionedIndependentVerifier()
        )
    with pytest.raises(FoundationError, match="NOT_PROVISIONED"):
        evaluate_real_foundation(
            adapter=None, replay=NotProvisionedDurableReplay(), verifier=NotProvisionedIndependentVerifier()
        )


def test_one_lifecycle_rejects_duplicate_even_with_fresh_adapter():
    context = build_contract_test_context()
    context.evaluate(adapter=ContractTestAdapter(), observed_at=NOW, handed_off_at=NOW)
    with pytest.raises(FoundationError, match="replayed"):
        context.evaluate(adapter=ContractTestAdapter(), observed_at=NOW, handed_off_at=NOW)


def test_alternate_public_consumer_revalidates_nested_constructed_models():
    value = result()
    forged_route = value.handoffs[0].route.model_construct(
        **{**value.handoffs[0].route.model_dump(), "dataset": DatasetId.LICENSING_LEGAL}
    )
    forged_handoff = value.handoffs[0].model_construct(
        **{**value.handoffs[0].model_dump(), "route": forged_route}
    )
    forged = FoundationResult.model_construct(
        **{**value.model_dump(), "handoffs": (forged_handoff, *value.handoffs[1:])}
    )
    with pytest.raises(FoundationError):
        validate_foundation_result(forged)


def test_json_model_validate_copy_and_construct_cannot_promote_truth():
    value = result()
    assert validate_foundation_result(value.model_dump_json()) == value
    for forged in (
        value.model_copy(update={"trade_decision": "TRADE"}),
        FoundationResult.model_construct(**{**value.model_dump(), "signals_generated": True}),
    ):
        with pytest.raises(FoundationError):
            validate_foundation_result(forged)


def test_registry_types_are_closed_enums_not_free_strings():
    route = ProviderRegistry.resolve(EvidenceGate.REAL_FX)
    assert type(route.provider) is ProviderId
    assert type(route.dataset) is DatasetId
    assert type(route.adapter) is AdapterId


def test_temporal_causality_fails_closed():
    with pytest.raises(ValidationError, match="precede"):
        build_contract_test_context().evaluate(
            adapter=ContractTestAdapter(), observed_at=NOW, handed_off_at=NOW - dt.timedelta(seconds=1)
        )
