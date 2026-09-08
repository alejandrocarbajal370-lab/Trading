import datetime as dt
import traceback

import pytest

from governance.canonical import typed_hash
from governance.ibkr_real_provisioning import (
    CONTRACT_VERSION,
    AuthenticEntitlementEvidence,
    EvidenceLifecycle,
    EvidenceState,
    IBKRRealProvisioningError,
    IBKRSessionBinding,
    MarketDataMode,
    SessionObservation,
    assess_contract_test,
    check_real_provisioning,
    seal_contract_test,
)
from governance.phase7e import EvidenceGate, GateState

UTC = dt.UTC
D = lambda value: typed_hash({"fixture": value})


def graph():
    now = dt.datetime(2026, 9, 8, 12, tzinfo=UTC)
    lifecycle = seal_contract_test(
        EvidenceLifecycle,
        "lifecycle_hash",
        requested_at=now - dt.timedelta(minutes=5),
        available_at=now - dt.timedelta(minutes=4),
        effective_at=now - dt.timedelta(minutes=3),
        verified_at=now - dt.timedelta(minutes=2),
        expires_at=now + dt.timedelta(hours=1),
        revoked_at=None,
    )
    common = {
        "contract_version": CONTRACT_VERSION,
        "provider": "provider.ibkr",
        "adapter_id": "adapter.ibkr.read-only",
        "dataset_id": "dataset.prices.ohlcv",
        "route_id": "route.ibkr.local.read-only",
        "request_id": "request.msft.001",
        "request_hash": D("request"),
        "security_master_id": "security.us.msft.xnas",
        "con_id": 272093,
    }
    session = seal_contract_test(
        IBKRSessionBinding,
        "binding_hash",
        **common,
        credential_backend_reference_digest=D("credential-backend"),
        deployment_reference_digest=D("deployment"),
        session_reference_digest=D("session"),
        session_evidence_digest=D("session-evidence"),
        read_only=True,
        lifecycle=lifecycle,
    )
    entitlement_lifecycle = seal_contract_test(
        EvidenceLifecycle,
        "lifecycle_hash",
        requested_at=now - dt.timedelta(minutes=3),
        available_at=now - dt.timedelta(minutes=3),
        effective_at=now - dt.timedelta(minutes=3),
        verified_at=now - dt.timedelta(minutes=2),
        expires_at=now + dt.timedelta(hours=1),
        revoked_at=None,
    )
    entitlement = seal_contract_test(
        AuthenticEntitlementEvidence,
        "evidence_hash",
        **common,
        session_binding_hash=session.binding_hash,
        session_evidence_digest=session.session_evidence_digest,
        entitlement_authority_reference_digest=D("external-authority"),
        entitlement_evidence_digest=D("external-evidence"),
        entitlement_scope_digest=D("scope"),
        lifecycle=entitlement_lifecycle,
        state=EvidenceState.CONTRACT_TEST_ONLY,
    )
    observation = seal_contract_test(
        SessionObservation,
        "observation_digest",
        session_binding_hash=session.binding_hash,
        observed_at=now - dt.timedelta(minutes=1),
        market_mode=MarketDataMode.REALTIME,
        socket_connected=True,
        callbacks_observed=True,
        ticks_observed=True,
    )
    return session, entitlement, observation, now


def reseal(value, model, field, **changes):
    raw = value.model_dump(mode="python", exclude={field})
    raw.update(changes)
    return seal_contract_test(model, field, **raw)


def test_contract_success_never_confers_real_entitlement_or_admission():
    result = assess_contract_test(*graph()[:3], assessed_at=graph()[3])
    assert result.state is EvidenceState.CONTRACT_TEST_ONLY
    assert {result.authentic_entitlement_real, result.provider_admission_real,
            result.independent_verifier_real} == {EvidenceState.NOT_PROVISIONED}
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert (result.real_route, result.global_readiness) == ("QVM_NOT_READY", "INSUFFICIENT_REAL_DATA")
    assert (result.trade_decision, result.signals_generated, result.live_execution_enabled) == ("NO_TRADE", False, False)
    assert result.backtesting == "NOT_AUTHORIZED"
    assert check_real_provisioning() is EvidenceState.NOT_PROVISIONED


@pytest.mark.parametrize("mode", tuple(MarketDataMode))
def test_connectivity_callbacks_ticks_and_market_mode_are_not_entitlement(mode):
    session, entitlement, observation, now = graph()
    observation = reseal(observation, SessionObservation, "observation_digest", market_mode=mode)
    result = assess_contract_test(session, entitlement, observation, assessed_at=now)
    assert result.authentic_entitlement_real is EvidenceState.NOT_PROVISIONED


@pytest.mark.parametrize("field,replacement", [
    ("provider", "provider.other"), ("adapter_id", "adapter.other"),
    ("dataset_id", "dataset.other"), ("route_id", "route.other"),
    ("request_hash", "0" * 64), ("security_master_id", "security.other"),
    ("con_id", 1), ("session_binding_hash", "0" * 64),
    ("session_evidence_digest", "0" * 64),
])
def test_cross_scope_session_security_request_route_swaps_fail(field, replacement):
    session, entitlement, observation, now = graph()
    with pytest.raises(IBKRRealProvisioningError):
        entitlement = reseal(entitlement, AuthenticEntitlementEvidence, "evidence_hash", **{field: replacement})
        assess_contract_test(session, entitlement, observation, assessed_at=now)


@pytest.mark.parametrize("condition", ("stale", "future", "expired", "revoked"))
def test_lifecycle_fails_closed(condition):
    session, entitlement, observation, now = graph()
    lifecycle = entitlement.lifecycle
    changes = {
        "stale": {"requested_at": now - dt.timedelta(hours=3), "available_at": now - dt.timedelta(hours=2, minutes=59), "effective_at": now - dt.timedelta(hours=2, minutes=58), "verified_at": now - dt.timedelta(hours=2, minutes=57), "expires_at": now - dt.timedelta(seconds=1)},
        "future": {"requested_at": now + dt.timedelta(seconds=1), "available_at": now + dt.timedelta(seconds=2), "effective_at": now + dt.timedelta(seconds=3), "verified_at": now + dt.timedelta(seconds=4), "expires_at": now + dt.timedelta(hours=1)},
        "expired": {"expires_at": now},
        "revoked": {"revoked_at": now},
    }[condition]
    with pytest.raises(IBKRRealProvisioningError):
        lifecycle = reseal(lifecycle, EvidenceLifecycle, "lifecycle_hash", **changes)
        entitlement = reseal(entitlement, AuthenticEntitlementEvidence, "evidence_hash", lifecycle=lifecycle)
        assess_contract_test(session, entitlement, observation, assessed_at=now)


def test_construct_copy_json_nested_extras_unicode_and_reseal_fail_closed():
    session, entitlement, observation, now = graph()
    assert assess_contract_test(session.model_dump_json(), entitlement.model_dump_json(), observation.model_dump_json(), assessed_at=now)
    forged = entitlement.model_copy(update={"session_binding_hash": "0" * 64})
    constructed = AuthenticEntitlementEvidence.model_construct(**{**entitlement.model_dump(), "request_hash": "0" * 64})
    nested = entitlement.model_dump(mode="python")
    nested["lifecycle"]["expires_at"] = now
    extra = entitlement.model_dump(mode="python")
    extra["username"] = "secret-user"
    for value in (forged, constructed, nested, extra):
        with pytest.raises(IBKRRealProvisioningError):
            assess_contract_test(session, value, observation, assessed_at=now)
    with pytest.raises(IBKRRealProvisioningError):
        reseal(session, IBKRSessionBinding, "binding_hash", request_id="request.m\N{CYRILLIC SMALL LETTER A}ft")


def test_secret_and_account_id_never_survive_errors_or_domain_surface():
    session, entitlement, observation, now = graph()
    raw = entitlement.model_dump(mode="python")
    raw["password"] = "never-show-secret"
    with pytest.raises(IBKRRealProvisioningError) as exc:
        assess_contract_test(session, raw, observation, assessed_at=now)
    rendered = "".join(traceback.format_exception(exc.value))
    assert "never-show-secret" not in rendered
    assert exc.value.__cause__ is exc.value.__context__ is None
    fields = set(IBKRSessionBinding.model_fields) | set(AuthenticEntitlementEvidence.model_fields)
    assert not {"username", "password", "token", "account_id", "market_mode", "connected"} & fields


def test_replay_reseal_and_local_self_authentication_cannot_elevate():
    session, entitlement, observation, now = graph()
    replay = reseal(entitlement, AuthenticEntitlementEvidence, "evidence_hash",
                    entitlement_authority_reference_digest=D("local-hmac-key"))
    result = assess_contract_test(session, replay, observation, assessed_at=now)
    assert result.authentic_entitlement_real is EvidenceState.NOT_PROVISIONED
    assert result.provider_admission_real is EvidenceState.NOT_PROVISIONED


@pytest.mark.parametrize("hook", ("str", "repr", "model_dump", "property"))
def test_hostile_conversion_hooks_are_never_invoked_or_leaked(hook):
    marker = "LEAK_ACCOUNT_U1234567_PASSWORD_hunter2"

    class Hostile:
        def __str__(self):
            raise RuntimeError(marker)

        def __repr__(self):
            raise RuntimeError(marker)

        def model_dump(self):
            raise RuntimeError(marker)

        @property
        def payload(self):
            raise RuntimeError(marker)

    hostile = Hostile()
    assert hook in {"str", "repr", "model_dump", "property"}
    with pytest.raises(IBKRRealProvisioningError) as exc:
        seal_contract_test(EvidenceLifecycle, "lifecycle_hash", requested_at=hostile)
    rendered = "".join(traceback.format_exception(exc.value))
    assert marker not in rendered
    assert exc.value.__cause__ is exc.value.__context__ is None


def test_hostile_subclass_and_duck_rebuild_paths_are_contained():
    session, entitlement, observation, now = graph()
    marker = "LEAK_ACCOUNT_U7654321_TOKEN_secret"

    class HostileSubclass(AuthenticEntitlementEvidence):
        def model_dump(self, *args, **kwargs):
            raise RuntimeError(marker)

    class HostileDuck:
        def model_dump(self, *args, **kwargs):
            raise RuntimeError(marker)

        def __repr__(self):
            raise RuntimeError(marker)

    hostile_values = (
        HostileSubclass.model_construct(**entitlement.model_dump(mode="python")),
        HostileDuck(),
    )
    for hostile in hostile_values:
        with pytest.raises(IBKRRealProvisioningError) as exc:
            assess_contract_test(session, hostile, observation, assessed_at=now)
        rendered = "".join(traceback.format_exception(exc.value))
        assert marker not in rendered
        assert exc.value.__cause__ is exc.value.__context__ is None


def test_entitlement_and_observation_must_follow_bound_session_context():
    session, entitlement, observation, now = graph()
    before = session.lifecycle.effective_at - dt.timedelta(microseconds=1)
    early_lifecycle = reseal(
        entitlement.lifecycle,
        EvidenceLifecycle,
        "lifecycle_hash",
        requested_at=before - dt.timedelta(seconds=3),
        available_at=before - dt.timedelta(seconds=2),
        effective_at=before - dt.timedelta(seconds=1),
        verified_at=before,
    )
    early_entitlement = reseal(
        entitlement, AuthenticEntitlementEvidence, "evidence_hash", lifecycle=early_lifecycle
    )
    early_observation = reseal(
        observation, SessionObservation, "observation_digest", observed_at=before
    )
    for candidate_entitlement, candidate_observation in (
        (early_entitlement, observation),
        (entitlement, early_observation),
    ):
        with pytest.raises(IBKRRealProvisioningError):
            assess_contract_test(
                session, candidate_entitlement, candidate_observation, assessed_at=now
            )


def test_observation_after_session_expiry_or_revocation_fails_closed():
    session, entitlement, observation, now = graph()
    for cutoff in ("expiry", "revocation"):
        changes = (
            {"expires_at": observation.observed_at}
            if cutoff == "expiry"
            else {"revoked_at": observation.observed_at}
        )
        lifecycle = reseal(session.lifecycle, EvidenceLifecycle, "lifecycle_hash", **changes)
        changed = reseal(session, IBKRSessionBinding, "binding_hash", lifecycle=lifecycle)
        linked_entitlement = reseal(
            entitlement,
            AuthenticEntitlementEvidence,
            "evidence_hash",
            session_binding_hash=changed.binding_hash,
        )
        linked_observation = reseal(
            observation,
            SessionObservation,
            "observation_digest",
            session_binding_hash=changed.binding_hash,
        )
        with pytest.raises(IBKRRealProvisioningError):
            assess_contract_test(changed, linked_entitlement, linked_observation, assessed_at=now)


def test_exact_session_effective_boundary_is_valid():
    session, entitlement, observation, now = graph()
    observation = reseal(
        observation,
        SessionObservation,
        "observation_digest",
        observed_at=session.lifecycle.effective_at,
    )
    assert assess_contract_test(session, entitlement, observation, assessed_at=now)
