import datetime as dt

import pytest
from pydantic import ValidationError

from governance.ibkr_observation import MarketDataMode, build_request, observe_contract_fixture
from governance.ibkr_provisioning import (
    ACCOUNT_DIGEST,
    ACTOR_IDS,
    ARCHITECTURE_DECISIONS,
    ActorRecord,
    ActorRegistry,
    ArchitectureDecision,
    ConnectionProfileReference,
    ConnectionState,
    ConnectionTransition,
    GovernedCredentialReference,
    IBKRProvisioningError,
    IBKRRealCaptureEvidence,
    MarketDataEntitlementEvidence,
    ProvisioningApproval,
    _seal,
    build_contract_test_capture,
    evaluate_real_route,
    readiness_assessment,
    validate_capture,
)
from governance.phase7e import EvidenceGate, GateState

EVENT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 9, 3, 12, tzinfo=dt.UTC)
PAYLOAD = b'{"bars":[{"close":"100.00"}]}'


def capture():
    observation = observe_contract_fixture(
        build_request(mode=MarketDataMode.DELAYED), observed_at=NOW
    )
    return build_contract_test_capture(observation, raw_payload=PAYLOAD, captured_at=NOW)


def reseal(value, model, hash_field, **changes):
    raw = value.model_dump(mode="python")
    raw.update(changes)
    raw.pop(hash_field)
    return _seal(model, hash_field, **raw)


def test_five_decisions_are_defined_but_real_is_not_provisioned():
    assert ARCHITECTURE_DECISIONS.decisions == tuple(ArchitectureDecision)
    assert ARCHITECTURE_DECISIONS.contract_level == "DEFINED"
    assert ARCHITECTURE_DECISIONS.real_provisioning == "NOT_PROVISIONED"
    result = readiness_assessment()
    assert len(result.missing_real_prerequisites) == 9
    assert result.ibkr_real == "NOT_PROVISIONED"
    assert result.activation_real is result.operating_mode_real is False
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert result.real_route == "QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert result.trade_decision == "NO_TRADE"
    assert result.signals_generated is result.live_execution_enabled is False
    assert result.backtesting == "NOT_AUTHORIZED"


def test_capture_binds_adapter_output_and_remains_observed_untrusted():
    result = capture()
    assert validate_capture(result.model_dump_json(), raw_payload=PAYLOAD) == result
    assert result.evidence_state == "OBSERVED_UNTRUSTED"
    assert result.provider_admission == result.authority == result.trust_root == "NOT_PROVISIONED"
    assert result.independent_verifier == result.external_custody_worm_legal == "NOT_PROVISIONED"
    assert result.durable_local_persistence_receipt is None
    assert result.persistence_guarantee == "NOT_INTEGRATED_WITH_PHASE29_IDENTITY"


@pytest.mark.parametrize("bad", [b"changed", PAYLOAD + b" "])
def test_payload_digest_and_size_tampering_rejected(bad):
    with pytest.raises(IBKRProvisioningError):
        validate_capture(capture(), raw_payload=bad)


def test_secret_material_cannot_enter_models_or_real_route():
    reference = capture().credential_reference
    raw = reference.model_dump(mode="python")
    raw["secret"] = "Bearer actual-secret"
    with pytest.raises(IBKRProvisioningError):
        validate_capture(
            capture().model_copy(update={"credential_reference": raw}), raw_payload=PAYLOAD
        )

    class FakeResolver:
        def resolve(self, reference_digest):
            return b"actual-secret"

    with pytest.raises(IBKRProvisioningError, match="NOT_PROVISIONED"):
        evaluate_real_route(secret_resolver=FakeResolver())
    with pytest.raises(TypeError):
        evaluate_real_route(raw_secret="actual-secret")  # type: ignore[call-arg]


def test_rejected_secret_is_absent_from_error_and_exception_chain():
    raw = capture().model_dump(mode="python")
    raw["credential_reference"]["secret"] = "SENSITIVE_SENTINEL"
    with pytest.raises(IBKRProvisioningError) as caught:
        validate_capture(raw, raw_payload=PAYLOAD)
    assert "SENSITIVE_SENTINEL" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_connection_profile_is_code_owned_and_state_machine_has_no_mutation_state():
    result = capture()
    for changes in (
        {"profile_digest": "0" * 64},
        {"account_reference_digest": "1" * 64},
        {"provider": "provider.fake"},
        {"capability": "ORDER_EXECUTION"},
        {"network_exposure": "PUBLIC"},
    ):
        with pytest.raises(ValidationError):
            reseal(result.connection_profile, ConnectionProfileReference, "profile_hash", **changes)
    assert not any("ORDER" in item.value or "ACCOUNT" in item.value for item in ConnectionState)
    _seal(
        ConnectionTransition,
        "transition_hash",
        from_state=ConnectionState.NOT_CONFIGURED,
        to_state=ConnectionState.CONFIGURED_REFERENCE_ONLY,
    )
    with pytest.raises(ValidationError):
        _seal(
            ConnectionTransition,
            "transition_hash",
            from_state=ConnectionState.NOT_CONFIGURED,
            to_state=ConnectionState.OBSERVING_READ_ONLY,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset": "fx"},
        {"market_data_mode": "REALTIME"},
        {"account_reference_digest": "0" * 64},
        {"provider": "provider.fake"},
        {"external_evidence_state": "PROVISIONED_REAL"},
    ],
)
def test_wrong_or_fake_entitlement_rejected_even_with_reseal(changes):
    with pytest.raises(ValidationError):
        reseal(capture().entitlement, MarketDataEntitlementEvidence, "entitlement_hash", **changes)


def test_expired_or_future_entitlement_rejected_by_deep_capture_validation():
    result = capture()
    for effective, expiry in (
        (EVENT, NOW),
        (NOW + dt.timedelta(seconds=1), NOW + dt.timedelta(days=1)),
    ):
        entitlement = reseal(
            result.entitlement,
            MarketDataEntitlementEvidence,
            "entitlement_hash",
            effective_at=effective,
            expires_at=expiry,
        )
        approval = reseal(
            result.approval,
            ProvisioningApproval,
            "approval_hash",
            entitlement_hash=entitlement.entitlement_hash,
        )
        raw = result.model_dump(mode="python")
        raw.update(entitlement=entitlement, approval=approval)
        raw.pop("capture_hash")
        with pytest.raises(ValidationError, match="entitlement"):
            _seal(IBKRRealCaptureEvidence, "capture_hash", **raw)


def test_maker_checker_spoof_and_revoked_actor_rejected():
    result = capture()
    with pytest.raises(ValidationError, match="maker and checker"):
        reseal(
            result.approval,
            ProvisioningApproval,
            "approval_hash",
            checker_id=ACTOR_IDS[0],
        )
    with pytest.raises(ValidationError, match="governed registry"):
        reseal(
            result.approval,
            ProvisioningApproval,
            "approval_hash",
            operator_id="actor.ibkr.spoof",
        )
    actors = list(result.actor_registry.actors)
    actors[2] = reseal(
        actors[2], ActorRecord, "record_hash", revoked_at=NOW - dt.timedelta(seconds=1)
    )
    registry = reseal(result.actor_registry, ActorRegistry, "registry_hash", actors=tuple(actors))
    raw = result.model_dump(mode="python")
    raw["actor_registry"] = registry
    raw.pop("capture_hash")
    with pytest.raises(ValidationError, match="revoked"):
        _seal(IBKRRealCaptureEvidence, "capture_hash", **raw)


def test_stale_credential_rotation_or_revocation_rejected():
    result = capture()
    with pytest.raises(ValidationError):
        reseal(
            result.credential_reference,
            GovernedCredentialReference,
            "reference_hash",
            rotation=2,
        )
    revoked = reseal(
        result.credential_reference,
        GovernedCredentialReference,
        "reference_hash",
        revoked_at=NOW - dt.timedelta(seconds=1),
        rotation=1,
    )
    approval = reseal(
        result.approval,
        ProvisioningApproval,
        "approval_hash",
        credential_reference_hash=revoked.reference_hash,
    )
    raw = result.model_dump(mode="python")
    raw.update(credential_reference=revoked, approval=approval)
    raw.pop("capture_hash")
    with pytest.raises(ValidationError, match="revoked"):
        _seal(IBKRRealCaptureEvidence, "capture_hash", **raw)


@pytest.mark.parametrize(
    "path,value",
    [
        (("observation", "envelopes", 0, "request", "request_hash"), "0" * 64),
        (("observation", "envelopes", 0, "response", "market_data_mode"), "REALTIME"),
        (("observation", "envelopes", 0, "response", "page", "page_index"), 2),
        (("observation", "envelopes", 0, "request", "instrument", "permanent_id"), "ibkr.bad"),
        (("observation", "envelopes", 0, "observed_at"), EVENT),
    ],
)
def test_nested_request_pagination_identity_timestamp_mode_swaps_rejected(path, value):
    raw = capture().model_dump(mode="python")
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(IBKRProvisioningError):
        validate_capture(raw, raw_payload=PAYLOAD)


def test_model_construct_model_copy_json_and_nested_mutation_bypasses_fail():
    result = capture()
    forged = IBKRRealCaptureEvidence.model_construct(
        **{**result.model_dump(mode="python"), "provider_admission": "PROVISIONED_REAL"}
    )
    with pytest.raises(IBKRProvisioningError):
        validate_capture(forged, raw_payload=PAYLOAD)
    copied = result.model_copy(update={"capture_hash": "0" * 64})
    with pytest.raises(IBKRProvisioningError):
        validate_capture(copied, raw_payload=PAYLOAD)
    raw = result.model_dump_json().replace("OBSERVED_UNTRUSTED", "TRUSTED")
    with pytest.raises(IBKRProvisioningError):
        validate_capture(raw, raw_payload=PAYLOAD)


def test_fake_persistence_and_cross_gate_trust_claims_cannot_be_added():
    raw = capture().model_dump(mode="python")
    raw["durable_local_persistence_receipt"] = {
        "worm": True,
        "custody": "verified",
        "receipt_hash": "0" * 64,
    }
    raw["authority"] = "PROVISIONED_REAL"
    with pytest.raises(IBKRProvisioningError):
        validate_capture(raw, raw_payload=PAYLOAD)
    assert ACCOUNT_DIGEST == capture().connection_profile.account_reference_digest
