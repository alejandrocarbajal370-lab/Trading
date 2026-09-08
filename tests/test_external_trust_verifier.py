import datetime as dt
import traceback

import pytest

from governance.canonical import typed_hash
from governance.external_trust_verifier import (
    AuthorityRegistryEvidence,
    ExternalAttestationEnvelope,
    ExternalLifecycle,
    ExternalTrustError,
    IndependentVerificationResult,
    PrincipalProvisioningEvidence,
    PrincipalRole,
    ProvisioningState,
    TrustAnchorProvisioningEvidence,
    assess_contract_test,
    check_real_external_trust,
    seal_contract_test,
    verify_real,
)
from governance.ibkr_real_provisioning import (
    CONTRACT_VERSION as UPSTREAM_VERSION,
)
from governance.ibkr_real_provisioning import (
    AuthenticEntitlementEvidence,
    EvidenceLifecycle,
    EvidenceState,
    IBKRSessionBinding,
    MarketDataMode,
    SessionObservation,
)
from governance.ibkr_real_provisioning import (
    seal_contract_test as seal_upstream,
)
from governance.phase7e import EvidenceGate, GateState

UTC = dt.UTC
D = lambda value: typed_hash({"fixture": value})


def graph():
    now = dt.datetime(2026, 9, 8, 16, tzinfo=UTC)
    upstream_lifecycle = seal_upstream(
        EvidenceLifecycle, "lifecycle_hash", requested_at=now-dt.timedelta(minutes=20),
        available_at=now-dt.timedelta(minutes=19), effective_at=now-dt.timedelta(minutes=18),
        verified_at=now-dt.timedelta(minutes=17), expires_at=now+dt.timedelta(hours=2), revoked_at=None,
    )
    common = {"provider": "provider.ibkr", "adapter_id": "adapter.ibkr.read-only",
                  "dataset_id": "dataset.prices.ohlcv", "route_id": "route.ibkr.local.read-only",
                  "request_id": "request.msft.001", "request_hash": D("request"),
                  "security_master_id": "security.us.msft.xnas", "con_id": 272093}
    session = seal_upstream(
        IBKRSessionBinding, "binding_hash", contract_version=UPSTREAM_VERSION, **common,
        credential_backend_reference_digest=D("backend"), deployment_reference_digest=D("deployment"),
        session_reference_digest=D("session"), session_evidence_digest=D("session-evidence"),
        read_only=True, lifecycle=upstream_lifecycle,
    )
    entitlement = seal_upstream(
        AuthenticEntitlementEvidence, "evidence_hash", contract_version=UPSTREAM_VERSION, **common,
        session_binding_hash=session.binding_hash, session_evidence_digest=session.session_evidence_digest,
        entitlement_authority_reference_digest=D("entitlement-authority"),
        entitlement_evidence_digest=D("entitlement"), entitlement_scope_digest=D("scope"),
        lifecycle=upstream_lifecycle, state=EvidenceState.CONTRACT_TEST_ONLY,
    )
    observation = seal_upstream(
        SessionObservation, "observation_digest", session_binding_hash=session.binding_hash,
        observed_at=now-dt.timedelta(minutes=12), market_mode=MarketDataMode.REALTIME,
        socket_connected=True, callbacks_observed=True, ticks_observed=True,
    )
    lifecycle = seal_contract_test(
        ExternalLifecycle, "lifecycle_hash", requested_at=now-dt.timedelta(minutes=16),
        available_at=now-dt.timedelta(minutes=15), effective_at=now-dt.timedelta(minutes=14),
        verified_at=now-dt.timedelta(minutes=13), expires_at=now+dt.timedelta(hours=1), revoked_at=None,
    )
    anchor = seal_contract_test(
        TrustAnchorProvisioningEvidence, "evidence_hash", trust_anchor_id="anchor.external.001",
        trust_anchor_reference_digest=D("anchor-ref"), public_material_digest=D("public-material"),
        provenance_digest=D("anchor-provenance"), lineage_digest=D("anchor-lineage"),
        lifecycle=lifecycle, state=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    registry_ref = D("registry-ref")
    principals = tuple(seal_contract_test(
        PrincipalProvisioningEvidence, "evidence_hash", principal_id=f"principal.{role.value.lower().replace('_', '-')}",
        role=role, principal_reference_digest=D(f"principal-{role.value}"),
        authority_registry_reference_digest=registry_ref, provisioning_evidence_digest=D(f"provision-{role.value}"),
        lifecycle=lifecycle, state=ProvisioningState.CONTRACT_TEST_ONLY,
    ) for role in PrincipalRole)
    by_role = {item.role: item for item in principals}
    registry = seal_contract_test(
        AuthorityRegistryEvidence, "evidence_hash", registry_id="registry.external.001",
        registry_reference_digest=registry_ref, trust_anchor_evidence_hash=anchor.evidence_hash,
        authority_principal_digest=by_role[PrincipalRole.AUTHORITY].principal_reference_digest,
        revocation_owner_principal_digest=by_role[PrincipalRole.REVOCATION_OWNER].principal_reference_digest,
        registry_material_digest=D("registry-material"), provenance_digest=D("registry-provenance"),
        lineage_digest=D("registry-lineage"), lifecycle=lifecycle,
        state=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    envelope = seal_contract_test(
        ExternalAttestationEnvelope, "envelope_hash",
        contract_version="external-trust-attestation-independent-verifier-v1",
        attestation_id="attestation.external.001",
        **common, session_binding_hash=session.binding_hash, session_evidence_digest=session.session_evidence_digest,
        entitlement_evidence_hash=entitlement.evidence_hash, observation_digest=observation.observation_digest,
        backend_reference_digest=session.credential_backend_reference_digest,
        deployment_reference_digest=session.deployment_reference_digest,
        trust_anchor_evidence_hash=anchor.evidence_hash, authority_registry_evidence_hash=registry.evidence_hash,
        attester_principal_evidence_hash=by_role[PrincipalRole.ATTESTER].evidence_hash,
        material_digest=D("attestation-material"), provenance_digest=D("attestation-provenance"),
        lineage_digest=D("attestation-lineage"), available_at=now-dt.timedelta(minutes=11),
        effective_at=now-dt.timedelta(minutes=10), attested_at=now-dt.timedelta(minutes=9),
        expires_at=now+dt.timedelta(minutes=30), state=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    verification = seal_contract_test(
        IndependentVerificationResult, "result_hash",
        contract_version="external-trust-attestation-independent-verifier-v1",
        verification_id="verification.external.001",
        attestation_id=envelope.attestation_id, attestation_envelope_hash=envelope.envelope_hash,
        trust_anchor_evidence_hash=anchor.evidence_hash, authority_registry_evidence_hash=registry.evidence_hash,
        verifier_principal_evidence_hash=by_role[PrincipalRole.VERIFIER].evidence_hash,
        verification_material_digest=D("verification-material"), provenance_digest=D("verification-provenance"),
        lineage_digest=D("verification-lineage"), verified_at=now-dt.timedelta(minutes=5),
        expires_at=now+dt.timedelta(minutes=20), state=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    return {"session": session, "entitlement": entitlement, "observation": observation, "trust_anchor": anchor,
                "authority_registry": registry, "principals": principals, "attestations": (envelope,),
                "verification": verification, "assessed_at": now}


def reseal(value, field, **changes):
    raw = value.model_dump(mode="python", exclude={field})
    raw.update(changes)
    return seal_contract_test(type(value), field, **raw)


def reseal_upstream(value, field, **changes):
    raw = value.model_dump(mode="python", exclude={field})
    raw.update(changes)
    return seal_upstream(type(value), field, **raw)


def relink(values):
    """Rebuild the whole downstream graph so lifecycle checks cannot hide behind hashes."""
    session = values["session"]
    entitlement = reseal_upstream(
        values["entitlement"], "evidence_hash",
        session_binding_hash=session.binding_hash,
        session_evidence_digest=session.session_evidence_digest,
    )
    observation = reseal_upstream(
        values["observation"], "observation_digest", session_binding_hash=session.binding_hash,
    )
    people = values["principals"]
    by_role = {item.role: item for item in people}
    registry = reseal(
        values["authority_registry"], "evidence_hash",
        trust_anchor_evidence_hash=values["trust_anchor"].evidence_hash,
        authority_principal_digest=by_role[PrincipalRole.AUTHORITY].principal_reference_digest,
        revocation_owner_principal_digest=by_role[PrincipalRole.REVOCATION_OWNER].principal_reference_digest,
    )
    envelope = reseal(
        values["attestations"][0], "envelope_hash",
        session_binding_hash=session.binding_hash,
        session_evidence_digest=session.session_evidence_digest,
        entitlement_evidence_hash=entitlement.evidence_hash,
        observation_digest=observation.observation_digest,
        trust_anchor_evidence_hash=values["trust_anchor"].evidence_hash,
        authority_registry_evidence_hash=registry.evidence_hash,
        attester_principal_evidence_hash=by_role[PrincipalRole.ATTESTER].evidence_hash,
    )
    verification = reseal(
        values["verification"], "result_hash",
        attestation_envelope_hash=envelope.envelope_hash,
        trust_anchor_evidence_hash=values["trust_anchor"].evidence_hash,
        authority_registry_evidence_hash=registry.evidence_hash,
        verifier_principal_evidence_hash=by_role[PrincipalRole.VERIFIER].evidence_hash,
    )
    values.update(entitlement=entitlement, observation=observation,
                  authority_registry=registry, attestations=(envelope,), verification=verification)
    return values


def with_lifecycle(value, **changes):
    upstream = isinstance(value, (IBKRSessionBinding, AuthenticEntitlementEvidence))
    seal = reseal_upstream if upstream else reseal
    lifecycle = seal(value.lifecycle, "lifecycle_hash", **changes)
    hash_field = "binding_hash" if isinstance(value, IBKRSessionBinding) else "evidence_hash"
    return seal(value, hash_field, lifecycle=lifecycle)


def test_contract_graph_preserves_every_real_and_safety_boundary():
    result = assess_contract_test(**graph())
    assert result.attestation_contract_validated and result.independent_verification_contract_validated
    assert {result.trust_anchor_real, result.authority_registry_real, result.attester_real,
            result.independent_verifier_real, result.provider_admission_real,
            result.custody_worm_replay_real, result.legal_licensing_real} == {ProvisioningState.NOT_PROVISIONED}
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert (result.real_route, result.global_readiness, result.trade_decision) == ("QVM_NOT_READY", "INSUFFICIENT_REAL_DATA", "NO_TRADE")
    assert not result.signals_generated and not result.live_execution_enabled
    assert result.backtesting == "NOT_AUTHORIZED"
    assert check_real_external_trust() is ProvisioningState.NOT_PROVISIONED


def test_attestation_is_not_verification_and_verification_is_not_admission():
    values = graph()
    assert values["attestations"][0].state is ProvisioningState.CONTRACT_TEST_ONLY
    assert values["verification"].state is ProvisioningState.CONTRACT_TEST_ONLY
    assert assess_contract_test(**values).provider_admission_real is ProvisioningState.NOT_PROVISIONED
    with pytest.raises(ExternalTrustError, match="NOT_PROVISIONED"):
        verify_real(lambda: True, signer="local-hmac-test-key")


@pytest.mark.parametrize("role", tuple(PrincipalRole))
def test_roles_are_exact_unique_and_non_confusable(role):
    values = graph()
    people = list(values["principals"])
    index = tuple(PrincipalRole).index(role)
    other = people[(index + 1) % len(people)]
    people[index] = reseal(people[index], "evidence_hash", principal_id=other.principal_id,
                           principal_reference_digest=other.principal_reference_digest)
    values["principals"] = tuple(people)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**values)


@pytest.mark.parametrize("target", ("anchor", "registry", "attester", "verifier", "session", "entitlement", "attestation"))
def test_swaps_rotation_and_cross_graph_copy_fail_closed(target):
    values = graph()
    if target == "anchor":
        values["trust_anchor"] = reseal(values["trust_anchor"], "evidence_hash", lineage_digest=D("rotated"))
    elif target == "registry":
        values["authority_registry"] = reseal(values["authority_registry"], "evidence_hash", lineage_digest=D("rotated"))
    elif target in {"attester", "verifier"}:
        role = PrincipalRole.ATTESTER if target == "attester" else PrincipalRole.VERIFIER
        people = list(values["principals"]); index = tuple(PrincipalRole).index(role)
        people[index] = reseal(people[index], "evidence_hash", provisioning_evidence_digest=D("rotated"))
        values["principals"] = tuple(people)
    elif target == "session":
        values["attestations"] = (reseal(values["attestations"][0], "envelope_hash", session_binding_hash="0"*64),)
    elif target == "entitlement":
        values["attestations"] = (reseal(values["attestations"][0], "envelope_hash", entitlement_evidence_hash="0"*64),)
    else:
        values["verification"] = reseal(values["verification"], "result_hash", attestation_envelope_hash="0"*64)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**values)


@pytest.mark.parametrize("condition", ("revoked", "expired", "future", "duplicate"))
def test_lifecycle_causality_and_duplicate_attestations_fail_closed(condition):
    values = graph(); now = values["assessed_at"]
    if condition == "duplicate":
        values["attestations"] *= 2
    elif condition == "future":
        values["verification"] = reseal(values["verification"], "result_hash", verified_at=now+dt.timedelta(seconds=1))
    elif condition == "expired":
        values["verification"] = reseal(values["verification"], "result_hash", expires_at=now)
    else:
        lifecycle = reseal(values["trust_anchor"].lifecycle, "lifecycle_hash", revoked_at=values["verification"].verified_at)
        values["trust_anchor"] = reseal(values["trust_anchor"], "evidence_hash", lifecycle=lifecycle)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**values)


@pytest.mark.parametrize("target", ("anchor", "registry", "session", "entitlement"))
@pytest.mark.parametrize("boundary", ("between", "equal"))
def test_material_evidence_revoked_as_of_assessment_rejects_after_full_relink(target, boundary):
    values = graph(); now = values["assessed_at"]
    revoked_at = now if boundary == "equal" else values["verification"].verified_at + dt.timedelta(minutes=1)
    key = {"anchor": "trust_anchor", "registry": "authority_registry"}.get(target, target)
    values[key] = with_lifecycle(values[key], revoked_at=revoked_at)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**relink(values))


@pytest.mark.parametrize("role", tuple(PrincipalRole))
def test_each_required_principal_revoked_after_verification_rejects_after_full_relink(role):
    values = graph()
    people = list(values["principals"]); index = tuple(PrincipalRole).index(role)
    people[index] = with_lifecycle(
        people[index], revoked_at=values["verification"].verified_at + dt.timedelta(minutes=1),
    )
    values["principals"] = tuple(people)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**relink(values))


@pytest.mark.parametrize("target", ("anchor", "registry", "principal", "session", "entitlement"))
@pytest.mark.parametrize("boundary", ("between", "equal"))
def test_material_evidence_expired_as_of_assessment_rejects_after_full_relink(target, boundary):
    values = graph(); now = values["assessed_at"]
    expires_at = now if boundary == "equal" else values["verification"].verified_at + dt.timedelta(minutes=1)
    if target == "principal":
        people = list(values["principals"])
        people[0] = with_lifecycle(people[0], expires_at=expires_at)
        values["principals"] = tuple(people)
    else:
        key = {"anchor": "trust_anchor", "registry": "authority_registry"}.get(target, target)
        values[key] = with_lifecycle(values[key], expires_at=expires_at)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**relink(values))


@pytest.mark.parametrize("target", ("attestation", "verification"))
def test_attestation_and_verification_expiry_at_assessment_boundary_rejects(target):
    values = graph(); now = values["assessed_at"]
    if target == "attestation":
        values["attestations"] = (reseal(values["attestations"][0], "envelope_hash", expires_at=now),)
        values["verification"] = reseal(
            values["verification"], "result_hash",
            attestation_envelope_hash=values["attestations"][0].envelope_hash,
        )
    else:
        values["verification"] = reseal(values["verification"], "result_hash", expires_at=now)
    with pytest.raises(ExternalTrustError):
        assess_contract_test(**values)


def test_all_material_evidence_active_through_assessment_remains_contract_test_only():
    assert assess_contract_test(**relink(graph())).state is ProvisioningState.CONTRACT_TEST_ONLY


def test_json_copy_construct_extras_unicode_subclass_duck_and_secrets_fail_closed():
    values = graph(); envelope = values["attestations"][0]
    assert assess_contract_test(**{**values, "verification": values["verification"].model_dump_json()})
    attacks = [
        envelope.model_copy(update={"request_hash": "0"*64}),
        ExternalAttestationEnvelope.model_construct(**{**envelope.model_dump(), "con_id": 1}),
        {**envelope.model_dump(), "private_key": "ACCOUNT_U123456_SECRET"},
    ]
    for attack in attacks:
        with pytest.raises(ExternalTrustError):
            assess_contract_test(**{**values, "attestations": (attack,)})
    with pytest.raises(ExternalTrustError):
        reseal(values["principals"][0], "evidence_hash", principal_id="principal.authоrity")

    marker = "ACCOUNT_U7654321_PRIVATE_KEY_SECRET"
    class Hostile:
        def __str__(self): raise RuntimeError(marker)
        def __repr__(self): raise RuntimeError(marker)
        def model_dump(self): raise RuntimeError(marker)
        @property
        def __dict__(self): raise RuntimeError(marker)
    for hostile in (Hostile(), type("Sub", (ExternalAttestationEnvelope,), {}).model_construct(**envelope.model_dump())):
        with pytest.raises(ExternalTrustError) as caught:
            assess_contract_test(**{**values, "attestations": (hostile,)})
        rendered = "".join(traceback.format_exception(caught.value))
        assert marker not in rendered and caught.value.__cause__ is caught.value.__context__ is None


def test_public_models_have_no_secret_key_or_account_identifier_surface():
    models = (TrustAnchorProvisioningEvidence, AuthorityRegistryEvidence,
              PrincipalProvisioningEvidence, ExternalAttestationEnvelope, IndependentVerificationResult)
    forbidden = {"secret", "private_key", "hmac", "signature", "account_id", "username", "password", "token"}
    assert all(not forbidden.intersection(model.model_fields) for model in models)
