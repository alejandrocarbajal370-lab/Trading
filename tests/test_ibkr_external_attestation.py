import datetime as dt
import hashlib
import traceback
from itertools import combinations

import pytest

from governance.canonical import typed_hash
from governance.ibkr_external_attestation import (
    ActorIdentity,
    ActorLifecycle,
    ActorRole,
    AuthenticEntitlementReference,
    ExternalAttestationEnvelope,
    ExternalAttestationError,
    ExternalTrustLifecycle,
    ProvisioningState,
    bind_ibkr_observation,
    seal_contract_test,
    verify_contract_test_attestation,
    verify_real_external_attestation,
)
from governance.ibkr_probe import SourceKind, build_request, capture_probe
from governance.phase7e import EvidenceGate, GateState

T0 = dt.datetime(2026, 9, 4, 20, tzinfo=dt.UTC)
ASSERTION = b"contract-only detached external assertion"
SECRET = "raw-account-secret-never-leak"


class FixtureTransport:
    api_version = "9.81.1.post1"

    def collect(self, config, instrument):
        del config, instrument
        return {
            "server_version": 157,
            "server_current_time": T0,
            "resolved_contract": {
                "conid": 272093,
                "symbol": "MSFT",
                "security_type": "STK",
                "exchange": "SMART",
                "primary_exchange": "NASDAQ",
                "currency": "USD",
                "local_symbol": "MSFT",
            },
            "mode_code": 3,
            "market_mode": "DELAYED",
            "tick_count": 0,
            "historical_bars": [
                {
                    "event_at": dt.datetime.now(dt.UTC).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                    "open": "500.00",
                    "high": "501.00",
                    "low": "499.00",
                    "close": "500.50",
                    "volume": "100",
                }
            ],
            "errors": [],
            "retrieved_at": dt.datetime.now(dt.UTC),
        }


def graph():
    observation = capture_probe(build_request(adapter_version="9.81.1.post1"), FixtureTransport())
    credential_digest = hashlib.sha256(b"external-credential-reference").hexdigest()
    binding = bind_ibkr_observation(observation, credential_reference_digest=credential_digest)
    actors = tuple(
        seal_contract_test(
            ActorIdentity,
            "identity_digest",
            actor_id=f"actor.{role.value.casefold().replace('_', '-')}",
            role=role,
        )
        for role in ActorRole
    )
    actor_lifecycles = tuple(
        seal_contract_test(
            ActorLifecycle,
            "lifecycle_hash",
            actor_identity_digest=actor.identity_digest,
            role=actor.role,
            effective_at=observation.requested_at - dt.timedelta(minutes=2),
            available_at=observation.requested_at - dt.timedelta(minutes=1),
            expires_at=observation.observed_at + dt.timedelta(hours=2),
        )
        for actor in actors
    )
    lifecycle = seal_contract_test(
        ExternalTrustLifecycle,
        "lifecycle_hash",
        anchor_id="anchor.ibkr.contract",
        authority_id="authority.ibkr.contract",
        public_material_digest=hashlib.sha256(b"public-material").hexdigest(),
        registry_digest=hashlib.sha256(b"external-registry-snapshot").hexdigest(),
        authority_identity_digest=actors[4].identity_digest,
        actor_lifecycles=actor_lifecycles,
        effective_at=observation.requested_at - dt.timedelta(minutes=2),
        available_at=observation.requested_at - dt.timedelta(minutes=1),
        expires_at=observation.observed_at + dt.timedelta(hours=2),
        mode=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    entitlement = seal_contract_test(
        AuthenticEntitlementReference,
        "entitlement_hash",
        provider="provider.ibkr",
        account_reference_digest=hashlib.sha256(b"opaque-account-reference").hexdigest(),
        entitlement_evidence_digest=hashlib.sha256(b"external-entitlement-evidence").hexdigest(),
        dataset="PRICES_OHLCV",
        security_master_id="security.us.msft.xnas",
        effective_at=observation.requested_at - dt.timedelta(minutes=1),
        expires_at=observation.observed_at + dt.timedelta(hours=1),
        external_state=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    envelope = seal_contract_test(
        ExternalAttestationEnvelope,
        "envelope_hash",
        mode=ProvisioningState.CONTRACT_TEST_ONLY,
        binding_hash=binding.binding_hash,
        entitlement_hash=entitlement.entitlement_hash,
        lifecycle_hash=lifecycle.lifecycle_hash,
        actors_hash=typed_hash([actor.model_dump(mode="json", warnings=False) for actor in actors]),
        attester_identity_digest=actors[0].identity_digest,
        authority_identity_digest=actors[4].identity_digest,
        issued_at=observation.observed_at + dt.timedelta(seconds=1),
        expires_at=observation.observed_at + dt.timedelta(hours=1),
        assertion_digest=hashlib.sha256(ASSERTION).hexdigest(),
    )
    verified_at = observation.observed_at + dt.timedelta(seconds=2)
    return observation, binding, entitlement, lifecycle, envelope, actors, verified_at


def verify(values=None, **changes):
    values = values or graph()
    keys = (
        "observation",
        "binding",
        "entitlement",
        "lifecycle",
        "envelope",
        "actors",
        "verified_at",
    )
    kwargs = dict(zip(keys, values, strict=True))
    kwargs["assertion"] = ASSERTION
    kwargs.update(changes)
    return verify_contract_test_attestation(**kwargs)


def reseal(value, model, field, **changes):
    raw = value.model_dump(mode="python")
    raw.update(changes)
    raw.pop(field)
    return seal_contract_test(model, field, **raw)


def test_contract_verification_binds_pr35_evidence_and_never_promotes_real():
    result = verify()
    assert result.state == "CONTRACT_TEST_VERIFIED"
    assert result.real_authenticity == result.real_entitlement == "NOT_PROVISIONED"
    assert result.real_provider_admission == result.external_custody_worm_legal == "NOT_PROVISIONED"
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
    with pytest.raises(ExternalAttestationError, match="NOT_PROVISIONED"):
        verify_real_external_attestation(result)


def test_market_mode_is_bound_but_cannot_substitute_for_entitlement():
    values = graph()
    assert values[1].market_mode == "DELAYED"
    bad = reseal(
        values[2], AuthenticEntitlementReference, "entitlement_hash", dataset="PRICES_OHLCV"
    )
    # Even a self-consistent declaration remains contract-only and REAL entitlement remains absent.
    assert verify(values=(*values[:2], bad, *values[3:])).real_entitlement == "NOT_PROVISIONED"


@pytest.mark.parametrize(
    "field",
    [
        "evidence_hash",
        "request_hash",
        "lineage_digest",
        "raw_digest",
        "material_digest",
        "provenance_digest",
    ],
)
def test_resealed_observation_binding_swaps_are_rejected(field):
    values = graph()
    forged = reseal(values[1], type(values[1]), "binding_hash", **{field: "0" * 64})
    with pytest.raises(ExternalAttestationError, match="observation binding mismatch"):
        verify(values=values, binding=forged)


def test_cross_security_entitlement_and_cross_request_attestation_are_rejected():
    values = graph()
    raw = values[2].model_dump(mode="python")
    raw["security_master_id"] = "security.us.goog.xnas"
    raw.pop("entitlement_hash")
    with pytest.raises(ExternalAttestationError):
        seal_contract_test(AuthenticEntitlementReference, "entitlement_hash", **raw)
    forged = reseal(values[4], ExternalAttestationEnvelope, "envelope_hash", binding_hash="0" * 64)
    with pytest.raises(ExternalAttestationError, match="attestation evidence"):
        verify(values=values, envelope=forged)


def test_actor_collapse_reordering_and_identity_swaps_are_rejected():
    values = graph()
    actors = values[5]
    for forged in (actors[:-1] + (actors[0],), tuple(reversed(actors))):
        with pytest.raises(ExternalAttestationError, match="actors must be exact"):
            verify(values=values, actors=forged)
    envelope = reseal(
        values[4],
        ExternalAttestationEnvelope,
        "envelope_hash",
        attester_identity_digest=actors[1].identity_digest,
    )
    with pytest.raises(ExternalAttestationError, match="attester identity"):
        verify(values=values, envelope=envelope)


@pytest.mark.parametrize("condition", ["revoked", "expired", "stale", "future"])
def test_revoked_expired_stale_and_future_attestations_fail_at_verifier_time(condition):
    values = graph()
    verified = values[6]
    if condition == "revoked":
        lifecycle = reseal(values[3], ExternalTrustLifecycle, "lifecycle_hash", revoked_at=verified)
        envelope = reseal(
            values[4],
            ExternalAttestationEnvelope,
            "envelope_hash",
            lifecycle_hash=lifecycle.lifecycle_hash,
        )
        values = (*values[:3], lifecycle, envelope, *values[5:])
    elif condition == "expired":
        values = (*values[:6], values[4].expires_at)
    elif condition == "stale":
        values = (*values[:6], values[3].expires_at)
    else:
        values = (*values[:6], values[4].issued_at - dt.timedelta(seconds=1))
    with pytest.raises(ExternalAttestationError, match="revoked|stale|expired|future"):
        verify(values=values)


def test_malformed_time_unicode_and_construct_copy_deep_revalidation_fail():
    values = graph()
    raw = values[3].model_dump(mode="python")
    raw["available_at"] = raw["available_at"].replace(tzinfo=None)
    raw.pop("lifecycle_hash")
    with pytest.raises(ExternalAttestationError, match="invalid contract-test"):
        seal_contract_test(ExternalTrustLifecycle, "lifecycle_hash", **raw)
    with pytest.raises(ExternalAttestationError):
        ActorIdentity(actor_id="actor.verifіer", role="VERIFIER", identity_digest="0" * 64)
    forged = values[1].model_copy(update={"request_hash": "0" * 64})
    with pytest.raises(ExternalAttestationError, match="invalid observation binding"):
        verify(values=values, binding=forged)
    constructed = type(values[4]).model_construct(
        **{**values[4].model_dump(), "binding_hash": "0" * 64}
    )
    with pytest.raises(ExternalAttestationError, match="invalid attestation envelope"):
        verify(values=values, envelope=constructed)


def test_duck_objects_and_secret_bearing_failures_are_sanitized():
    class Duck:
        def model_dump(self):
            return {"trusted": True}

    with pytest.raises(ExternalAttestationError, match="invalid IBKR observation") as caught:
        bind_ibkr_observation(Duck(), credential_reference_digest="0" * 64)
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    values = graph()
    for value in (*values[1:5], *values[5]):
        dumped = value.model_dump_json()
        assert SECRET not in dumped and "account-secret" not in dumped


def test_local_observation_and_fixture_can_never_enter_real_verification():
    values = graph()
    raw = values[0].model_dump(mode="python")
    raw["source_kind"] = SourceKind.LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED
    raw.pop("evidence_hash")
    from governance.ibkr_probe import ProbeEvidence, _seal

    local = _seal(ProbeEvidence, "evidence_hash", **raw)
    binding = bind_ibkr_observation(
        local, credential_reference_digest=values[1].credential_reference_digest
    )
    envelope = reseal(
        values[4], ExternalAttestationEnvelope, "envelope_hash", binding_hash=binding.binding_hash
    )
    with pytest.raises(ExternalAttestationError, match="NOT_PROVISIONED"):
        verify(values=(local, binding, values[2], values[3], envelope, *values[5:]))


@pytest.mark.parametrize(
    ("model_index", "field"),
    [
        (1, "credential_reference_digest"),
        (1, "material_digest"),
        (1, "provenance_digest"),
        (2, "account_reference_digest"),
        (2, "entitlement_evidence_digest"),
        (3, "public_material_digest"),
        (3, "registry_digest"),
        (4, "assertion_digest"),
    ],
)
def test_all_digest_only_public_sealing_failures_are_secret_free(model_index, field):
    values = graph()
    model = type(values[model_index])
    hash_field = {
        1: "binding_hash",
        2: "entitlement_hash",
        3: "lifecycle_hash",
        4: "envelope_hash",
    }[model_index]
    raw = values[model_index].model_dump(mode="python", exclude={hash_field})
    secret = f"RAW_{field.upper()}_ABC123_SECRET"
    raw[field] = secret
    with pytest.raises(ExternalAttestationError) as caught:
        seal_contract_test(model, hash_field, **raw)
    rendered = "\n".join((str(caught.value), repr(caught.value), traceback.format_exc()))
    assert secret not in rendered
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_original_binding_secret_reproducer_is_closed_without_exception_chaining():
    observation = graph()[0]
    secret = "RAW_ACCOUNT_ID_ABC123_SECRET"
    with pytest.raises(ExternalAttestationError) as caught:
        bind_ibkr_observation(observation, credential_reference_digest=secret)
    rendered = "\n".join((str(caught.value), repr(caught.value), traceback.format_exc()))
    assert secret not in rendered
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("route", ("constructor", "model_validate", "model_validate_json"))
def test_public_pydantic_validation_routes_never_expose_rejected_values(route):
    secret = "RAW_IDENTITY_PII_ABC123_SECRET"
    raw = {"actor_id": secret, "role": "ATTESTER", "identity_digest": "0" * 64}
    with pytest.raises(ExternalAttestationError) as caught:
        if route == "constructor":
            ActorIdentity(**raw)
        elif route == "model_validate":
            ActorIdentity.model_validate(raw)
        else:
            ActorIdentity.model_validate_json(
                '{"actor_id":"'
                + secret
                + '","role":"ATTESTER","identity_digest":"'
                + "0" * 64
                + '"}'
            )
    rendered = "\n".join((str(caught.value), repr(caught.value), traceback.format_exc()))
    assert secret not in rendered
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_hostile_dump_serializer_repr_str_and_property_are_never_invoked_or_leaked():
    secret = "RAW_HOSTILE_OBJECT_ABC123_SECRET"

    class Hostile:
        @property
        def __dict__(self):
            raise RuntimeError(secret)

        def model_dump(self, *args, **kwargs):
            raise RuntimeError(secret)

        def __repr__(self):
            raise RuntimeError(secret)

        def __str__(self):
            raise RuntimeError(secret)

    with pytest.raises(ExternalAttestationError) as caught:
        bind_ibkr_observation(Hostile(), credential_reference_digest="0" * 64)
    rendered = "\n".join((str(caught.value), repr(caught.value), traceback.format_exc()))
    assert secret not in rendered
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(ExternalAttestationError):
        seal_contract_test(Hostile, "hostile_hash", payload=secret)


@pytest.mark.parametrize("role", tuple(ActorRole))
def test_each_actor_identity_is_materially_bound_and_full_rebinding_changes_assessment(role):
    values = graph()
    baseline = verify(values=values)
    actors = list(values[5])
    index = tuple(ActorRole).index(role)
    actors[index] = seal_contract_test(
        ActorIdentity,
        "identity_digest",
        actor_id=f"replacement.{role.value.casefold().replace('_', '-')}",
        role=role,
    )
    replaced = tuple(actors)
    with pytest.raises(ExternalAttestationError, match="identity binding|actor set binding"):
        verify(values=values, actors=replaced)

    records = list(values[3].actor_lifecycles)
    records[index] = reseal(
        records[index],
        ActorLifecycle,
        "lifecycle_hash",
        actor_identity_digest=replaced[index].identity_digest,
    )
    lifecycle = reseal(
        values[3],
        ExternalTrustLifecycle,
        "lifecycle_hash",
        actor_lifecycles=tuple(records),
        **(
            {"authority_identity_digest": replaced[index].identity_digest}
            if role is ActorRole.AUTHORITY
            else {}
        ),
    )
    envelope = reseal(
        values[4],
        ExternalAttestationEnvelope,
        "envelope_hash",
        lifecycle_hash=lifecycle.lifecycle_hash,
        actors_hash=typed_hash(
            [actor.model_dump(mode="json", warnings=False) for actor in replaced]
        ),
        **(
            {"attester_identity_digest": replaced[index].identity_digest}
            if role is ActorRole.ATTESTER
            else {}
        ),
        **(
            {"authority_identity_digest": replaced[index].identity_digest}
            if role is ActorRole.AUTHORITY
            else {}
        ),
    )
    rebound = verify(values=(*values[:3], lifecycle, envelope, replaced, values[6]))
    assert rebound.assessment_hash != baseline.assessment_hash
    assert rebound.actors_hash != baseline.actors_hash


@pytest.mark.parametrize("roles", tuple(combinations(tuple(ActorRole), 2)))
def test_combined_actor_swaps_are_detected_by_canonical_actor_binding(roles):
    values = graph()
    actors = list(values[5])
    for role in roles:
        index = tuple(ActorRole).index(role)
        actors[index] = seal_contract_test(
            ActorIdentity,
            "identity_digest",
            actor_id=f"combined.{role.value.casefold().replace('_', '-')}",
            role=role,
        )
    with pytest.raises(ExternalAttestationError, match="identity binding|actor set binding"):
        verify(values=values, actors=tuple(actors))


@pytest.mark.parametrize("role", tuple(ActorRole))
@pytest.mark.parametrize("condition", ("future", "expired", "revoked", "unavailable"))
def test_every_actor_lifecycle_fails_closed_at_verifier_time(role, condition):
    values = graph()
    verified = values[6]
    index = tuple(ActorRole).index(role)
    record = values[3].actor_lifecycles[index]
    changes = {
        "future": {
            "effective_at": verified + dt.timedelta(seconds=1),
            "available_at": verified + dt.timedelta(seconds=2),
            "expires_at": verified + dt.timedelta(hours=1),
        },
        "unavailable": {
            "available_at": verified + dt.timedelta(seconds=1),
            "expires_at": verified + dt.timedelta(hours=1),
        },
        "expired": {"expires_at": verified},
        "revoked": {"revoked_at": verified},
    }[condition]
    records = list(values[3].actor_lifecycles)
    records[index] = reseal(record, ActorLifecycle, "lifecycle_hash", **changes)
    lifecycle = reseal(
        values[3], ExternalTrustLifecycle, "lifecycle_hash", actor_lifecycles=tuple(records)
    )
    envelope = reseal(
        values[4],
        ExternalAttestationEnvelope,
        "envelope_hash",
        lifecycle_hash=lifecycle.lifecycle_hash,
    )
    with pytest.raises(ExternalAttestationError, match="lifecycle"):
        verify(values=(*values[:3], lifecycle, envelope, *values[5:]))


def test_authority_actor_and_lifecycle_identity_mismatch_is_rejected():
    values = graph()
    raw = values[3].model_dump(mode="python", exclude={"lifecycle_hash"})
    raw["authority_identity_digest"] = "f" * 64
    with pytest.raises(ExternalAttestationError, match="invalid contract-test"):
        seal_contract_test(ExternalTrustLifecycle, "lifecycle_hash", **raw)
