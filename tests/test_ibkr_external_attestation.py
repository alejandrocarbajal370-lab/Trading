import datetime as dt
import hashlib

import pytest
from pydantic import ValidationError

from governance.ibkr_external_attestation import (
    ActorIdentity,
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
    binding = bind_ibkr_observation(
        observation, credential_reference_digest=credential_digest
    )
    actors = tuple(
        seal_contract_test(
            ActorIdentity,
            "identity_digest",
            actor_id=f"actor.{role.value.casefold().replace('_', '-')}",
            role=role,
        )
        for role in ActorRole
    )
    lifecycle = seal_contract_test(
        ExternalTrustLifecycle,
        "lifecycle_hash",
        anchor_id="anchor.ibkr.contract",
        authority_id="authority.ibkr.contract",
        public_material_digest=hashlib.sha256(b"public-material").hexdigest(),
        registry_digest=hashlib.sha256(b"external-registry-snapshot").hexdigest(),
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
    keys = ("observation", "binding", "entitlement", "lifecycle", "envelope", "actors", "verified_at")
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
    assert (result.real_route, result.global_readiness) == ("QVM_NOT_READY", "INSUFFICIENT_REAL_DATA")
    assert (result.trade_decision, result.signals_generated, result.live_execution_enabled) == (
        "NO_TRADE", False, False
    )
    assert result.backtesting == "NOT_AUTHORIZED"
    with pytest.raises(ExternalAttestationError, match="NOT_PROVISIONED"):
        verify_real_external_attestation(result)


def test_market_mode_is_bound_but_cannot_substitute_for_entitlement():
    values = graph()
    assert values[1].market_mode == "DELAYED"
    bad = reseal(values[2], AuthenticEntitlementReference, "entitlement_hash", dataset="PRICES_OHLCV")
    # Even a self-consistent declaration remains contract-only and REAL entitlement remains absent.
    assert verify(values=(*values[:2], bad, *values[3:])).real_entitlement == "NOT_PROVISIONED"


@pytest.mark.parametrize("field", ["evidence_hash", "request_hash", "lineage_digest", "raw_digest", "material_digest", "provenance_digest"])
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
    with pytest.raises(ValidationError):
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
        values[4], ExternalAttestationEnvelope, "envelope_hash", attester_identity_digest=actors[1].identity_digest
    )
    with pytest.raises(ExternalAttestationError, match="attester identity"):
        verify(values=values, envelope=envelope)


@pytest.mark.parametrize("condition", ["revoked", "expired", "stale", "future"])
def test_revoked_expired_stale_and_future_attestations_fail_at_verifier_time(condition):
    values = graph()
    verified = values[6]
    if condition == "revoked":
        lifecycle = reseal(values[3], ExternalTrustLifecycle, "lifecycle_hash", revoked_at=verified)
        envelope = reseal(values[4], ExternalAttestationEnvelope, "envelope_hash", lifecycle_hash=lifecycle.lifecycle_hash)
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
    with pytest.raises(ValidationError, match="canonical UTC"):
        seal_contract_test(ExternalTrustLifecycle, "lifecycle_hash", **raw)
    with pytest.raises(ValidationError):
        ActorIdentity(actor_id="actor.verifіer", role="VERIFIER", identity_digest="0" * 64)
    forged = values[1].model_copy(update={"request_hash": "0" * 64})
    with pytest.raises(ExternalAttestationError, match="invalid observation binding"):
        verify(values=values, binding=forged)
    constructed = type(values[4]).model_construct(**{**values[4].model_dump(), "binding_hash": "0" * 64})
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
    binding = bind_ibkr_observation(local, credential_reference_digest=values[1].credential_reference_digest)
    envelope = reseal(
        values[4], ExternalAttestationEnvelope, "envelope_hash", binding_hash=binding.binding_hash
    )
    with pytest.raises(ExternalAttestationError, match="NOT_PROVISIONED"):
        verify(values=(local, binding, values[2], values[3], envelope, *values[5:]))
