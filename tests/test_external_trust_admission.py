import datetime as dt

import pytest

from governance.external_provider_foundation import FoundationError, ProvisioningState
from governance.external_trust_admission import (
    build_contract_test_verifier,
    observe_external_trust_evidence,
    verify_and_admit_contract_test_evidence,
    verify_and_admit_real_external_evidence,
)
from governance.phase7e import EvidenceGate, GateState
from governance.trust_authority import (
    Approval,
    AuthorityCapability,
    AuthorityRole,
    EvidenceReference,
    build_contract_test_anchor_registration,
    build_contract_test_authority,
    build_contract_test_registry,
    build_trust_anchor_identity,
)

T0 = dt.datetime(2026, 9, 2, 20, tzinfo=dt.UTC)
OBSERVED = T0 + dt.timedelta(minutes=3)
VERIFIED = T0 + dt.timedelta(minutes=4)
PAYLOAD = b'{"external":"evidence"}'


def graph(*, gate=EvidenceGate.RETENTION_WORM, authority_revoked=None, anchor_revoked=None):
    ref = EvidenceReference(
        reference_id="credential.ref", media_type="application/json", digest="a" * 64, size=1
    )
    identity = build_trust_anchor_identity(
        anchor_id="anchor.primary",
        anchor_kind="PUBLIC_KEY",
        credential_reference=ref,
        fingerprint="b" * 64,
    )
    anchor = build_contract_test_anchor_registration(
        anchor=identity,
        provider_id="provider.primary",
        gate=gate,
        scope_id="scope.primary",
        policy_version="policy.v1",
        effective_at=T0,
        available_at=T0 + dt.timedelta(minutes=1),
        revoked_at=anchor_revoked,
    )
    authority = build_contract_test_authority(
        authority_id="authority.primary",
        trust_anchor_identity_hash=identity.identity_hash,
        trust_anchor_registration_hash=anchor.registration_hash,
        provider_id="provider.primary",
        gate=gate,
        scope_id="scope.primary",
        policy_version="policy.v1",
        capabilities=tuple(AuthorityCapability),
        effective_at=T0,
        available_at=T0 + dt.timedelta(minutes=1),
        revoked_at=authority_revoked,
        approvals=tuple(
            Approval(
                role=r,
                actor_id=f"actor.{r.value.lower()}",
                approved_at=T0 + dt.timedelta(minutes=1),
            )
            for r in AuthorityRole
        ),
    )
    registry = build_contract_test_registry(authority, anchor_registrations=(anchor,))
    verifier = build_contract_test_verifier(
        verifier_id="verifier.contract",
        authority_contract_hash=authority.contract_hash,
        registry_hash=registry.registry_hash,
    )
    evidence = observe_external_trust_evidence(
        evidence_id="evidence.primary",
        provider_id="provider.primary",
        gate=gate,
        scope_id="scope.primary",
        policy_version="policy.v1",
        authority_contract_hash=authority.contract_hash,
        anchor_registration_hash=anchor.registration_hash,
        payload=PAYLOAD,
        observed_at=OBSERVED,
    )
    return anchor, authority, registry, verifier, evidence


def admit(*, graph_value=None, payload=PAYLOAD, **overrides):
    _, _, registry, verifier, evidence = graph_value or graph()
    values = {
        "payload": payload,
        "verifier": verifier,
        "registry": registry,
        "expected_registry_hash": registry.registry_hash,
        "expected_verifier_hash": verifier.verifier_hash,
        "verified_at": VERIFIED,
    }
    values.update(overrides)
    return verify_and_admit_contract_test_evidence(evidence, **values)


def test_contract_test_verification_never_promotes_real_or_closes_gate():
    result = admit()
    assert result.state == "CONTRACT_TEST_VERIFIED"
    assert result.gate_state is GateState.OPEN_EXTERNAL
    assert (
        result.trust_root
        is result.independent_verifier
        is result.real_provider_admission
        is ProvisioningState.NOT_PROVISIONED
    )
    assert (
        result.trade_decision,
        result.signals_generated,
        result.live_execution_enabled,
        result.backtesting,
    ) == ("NO_TRADE", False, False, "NOT_AUTHORIZED")
    with pytest.raises(FoundationError, match="NOT_PROVISIONED"):
        verify_and_admit_real_external_evidence(evidence=result)


@pytest.mark.parametrize("gate", tuple(EvidenceGate))
def test_all_ten_gates_remain_open_external(gate):
    result = admit(graph_value=graph(gate=gate))
    assert result.evidence.gate is gate
    assert result.gate_state is GateState.OPEN_EXTERNAL


def test_payload_tamper_fake_verifier_and_registry_fail_closed():
    bundle = graph()
    with pytest.raises(FoundationError, match="digest mismatch"):
        admit(graph_value=bundle, payload=b"{" + b"x" * (len(PAYLOAD) - 2) + b"}")
    with pytest.raises(FoundationError, match="verifier binding mismatch"):
        admit(graph_value=bundle, expected_verifier_hash="0" * 64)
    with pytest.raises(FoundationError, match="registry binding mismatch"):
        admit(graph_value=bundle, expected_registry_hash="0" * 64)


@pytest.mark.parametrize(
    "verifier_id",
    [
        "authority.primary",
        "actor.maker",
        "actor.checker",
        "actor.reviewer",
        "actor.authority",
    ],
)
def test_verifier_identity_must_be_independent_from_authority_actors(verifier_id):
    _, authority, registry, _, evidence = graph()
    verifier = build_contract_test_verifier(
        verifier_id=verifier_id,
        authority_contract_hash=authority.contract_hash,
        registry_hash=registry.registry_hash,
    )
    with pytest.raises(FoundationError, match="verifier identity is not independent"):
        verify_and_admit_contract_test_evidence(
            evidence,
            payload=PAYLOAD,
            verifier=verifier,
            registry=registry,
            expected_registry_hash=registry.registry_hash,
            expected_verifier_hash=verifier.verifier_hash,
            verified_at=VERIFIED,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "provider.other"),
        ("gate", EvidenceGate.LICENSING_LEGAL),
        ("scope_id", "scope.other"),
    ],
)
def test_fully_resealed_cross_gate_scope_swaps_fail(field, value):
    _, _, registry, verifier, evidence = graph()
    raw = evidence.model_dump(mode="python")
    raw[field] = value
    forged = observe_external_trust_evidence(
        payload=PAYLOAD,
        **{
            k: v
            for k, v in raw.items()
            if k
            not in {"contract_version", "mode", "payload_digest", "payload_size", "evidence_hash"}
        },
    )
    with pytest.raises(FoundationError, match="cross-gate or scope"):
        verify_and_admit_contract_test_evidence(
            forged,
            payload=PAYLOAD,
            verifier=verifier,
            registry=registry,
            expected_registry_hash=registry.registry_hash,
            expected_verifier_hash=verifier.verifier_hash,
            verified_at=VERIFIED,
        )


@pytest.mark.parametrize("which", ["authority", "anchor"])
def test_revocation_at_verifier_time_fails_independently(which):
    kwargs = {f"{which}_revoked": VERIFIED}
    with pytest.raises(FoundationError, match=f"{which} revoked"):
        admit(graph_value=graph(**kwargs))


def test_nested_construct_copy_and_lifecycle_swap_bypasses_fail():
    anchor, authority, registry, verifier, evidence = graph()
    forged = evidence.model_copy(update={"gate": EvidenceGate.LICENSING_LEGAL})
    with pytest.raises(FoundationError, match="invalid external trust evidence"):
        verify_and_admit_contract_test_evidence(
            forged,
            payload=PAYLOAD,
            verifier=verifier,
            registry=registry,
            expected_registry_hash=registry.registry_hash,
            expected_verifier_hash=verifier.verifier_hash,
            verified_at=VERIFIED,
        )
    other = graph(gate=EvidenceGate.LICENSING_LEGAL)
    with pytest.raises(FoundationError, match="registry binding mismatch"):
        admit(graph_value=(anchor, authority, other[2], verifier, evidence))


def test_observation_and_verification_require_canonical_time_order():
    bundle = graph()
    with pytest.raises(FoundationError, match="verification precedes"):
        admit(graph_value=bundle, verified_at=OBSERVED - dt.timedelta(seconds=1))
    with pytest.raises(ValueError, match="canonical UTC"):
        observe_external_trust_evidence(
            evidence_id="evidence.primary",
            provider_id="provider.primary",
            gate=EvidenceGate.RETENTION_WORM,
            scope_id="scope.primary",
            policy_version="policy.v1",
            authority_contract_hash=bundle[1].contract_hash,
            anchor_registration_hash=bundle[0].registration_hash,
            payload=PAYLOAD,
            observed_at=OBSERVED.replace(tzinfo=None),
        )
