import datetime as dt
import hashlib
import traceback

import pytest
from test_ibkr_external_attestation import graph, verify

from governance.external_trust_backend import (
    ContractState,
    ExternalBackendIdentity,
    ExternalPrincipal,
    PrincipalRole,
    ProvisioningEvidenceManifest,
    TrustBackendError,
    provision_real_external_trust_backend,
    seal_contract_test,
    validate_contract_test_provisioning,
)
from governance.ibkr_external_attestation import ProvisioningState
from governance.phase7e import EvidenceGate, GateState


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def provisioning_graph():
    authenticity_values = graph()
    binding = authenticity_values[1]
    authenticity = verify(values=authenticity_values)
    assessed_at = authenticity_values[6] + dt.timedelta(seconds=1)
    backend = seal_contract_test(
        ExternalBackendIdentity,
        "backend_hash",
        backend_id="backend.external.contract",
        provider="provider.ibkr",
        deployment_identity_digest=digest("external-deployment"),
        endpoint_reference_digest=digest("external-endpoint-reference"),
        configuration_digest=digest("external-config"),
        operating_mode=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    principals = tuple(
        seal_contract_test(
            ExternalPrincipal,
            "principal_hash",
            principal_id=f"principal.{role.value.casefold().replace('_', '-')}",
            role=role,
            external_identity_digest=digest(f"external-identity-{role.value}"),
            authority_reference_digest=digest(f"authority-reference-{role.value}"),
            effective_at=assessed_at - dt.timedelta(minutes=2),
            available_at=assessed_at - dt.timedelta(minutes=1),
            expires_at=assessed_at + dt.timedelta(hours=1),
        )
        for role in PrincipalRole
    )
    manifest = seal_contract_test(
        ProvisioningEvidenceManifest,
        "manifest_hash",
        backend_hash=backend.backend_hash,
        provider=binding.provider,
        security_master_id=binding.security_master_id,
        request_hash=binding.request_hash,
        observation_binding_hash=binding.binding_hash,
        authenticity_assessment_hash=authenticity.assessment_hash,
        entitlement_reference_hash=authenticity.entitlement_hash,
        trust_anchor_reference_digest=digest("trust-anchor-reference"),
        authority_registry_reference_digest=digest("authority-registry-reference"),
        replay_service_reference_digest=digest("replay-service-reference"),
        custody_evidence_reference_digest=digest("custody-evidence-reference"),
        worm_evidence_reference_digest=digest("worm-evidence-reference"),
        legal_approval_reference_digest=digest("legal-approval-reference"),
        principals=principals,
        effective_at=assessed_at - dt.timedelta(minutes=1),
        expires_at=assessed_at + dt.timedelta(hours=1),
        mode=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    return backend, manifest, binding, authenticity, assessed_at


def validate(values=None, **changes):
    values = values or provisioning_graph()
    keys = ("backend", "manifest", "observation_binding", "authenticity_assessment", "assessed_at")
    kwargs = dict(zip(keys, values, strict=True))
    kwargs.update(changes)
    return validate_contract_test_provisioning(**kwargs)


def reseal(value, model, field, **changes):
    raw = value.model_dump(mode="python", exclude={field})
    raw.update(changes)
    return seal_contract_test(model, field, **raw)


def test_contract_is_exactly_bound_and_never_claims_real_provisioning():
    result = validate()
    assert result.state is ContractState.CONTRACT_TEST_VALIDATED
    assert {
        result.backend_real,
        result.trust_anchor_real,
        result.authority_registry_real,
        result.entitlement_real,
        result.independent_verifier_real,
        result.replay_custody_worm_legal_real,
        result.provider_admission_real,
    } == {ProvisioningState.NOT_PROVISIONED}
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert (result.real_route, result.global_readiness) == ("QVM_NOT_READY", "INSUFFICIENT_REAL_DATA")
    assert (result.trade_decision, result.signals_generated, result.live_execution_enabled) == (
        "NO_TRADE", False, False
    )
    assert result.backtesting == "NOT_AUTHORIZED"
    with pytest.raises(TrustBackendError, match="NOT_PROVISIONED"):
        provision_real_external_trust_backend(object())


@pytest.mark.parametrize(
    "field",
    ("request_hash", "observation_binding_hash", "authenticity_assessment_hash", "entitlement_reference_hash"),
)
def test_cross_request_observation_assessment_and_entitlement_swaps_fail(field):
    values = provisioning_graph()
    forged = reseal(values[1], ProvisioningEvidenceManifest, "manifest_hash", **{field: "0" * 64})
    with pytest.raises(TrustBackendError):
        validate(values=values, manifest=forged)


@pytest.mark.parametrize("role", tuple(PrincipalRole))
@pytest.mark.parametrize("condition", ("future", "expired", "revoked"))
def test_every_external_principal_lifecycle_is_checked_at_verifier_time(role, condition):
    values = provisioning_graph()
    index = tuple(PrincipalRole).index(role)
    principals = list(values[1].principals)
    now = values[4]
    changes = {
        "future": {"effective_at": now + dt.timedelta(seconds=1), "available_at": now + dt.timedelta(seconds=2), "expires_at": now + dt.timedelta(hours=1)},
        "expired": {"expires_at": now},
        "revoked": {"revoked_at": now},
    }[condition]
    principals[index] = reseal(principals[index], ExternalPrincipal, "principal_hash", **changes)
    manifest = reseal(values[1], ProvisioningEvidenceManifest, "manifest_hash", principals=tuple(principals))
    with pytest.raises(TrustBackendError):
        validate(values=values, manifest=manifest)


def test_attester_verifier_collapse_reordering_and_cross_backend_swap_fail():
    values = provisioning_graph()
    principals = list(values[1].principals)
    verifier = tuple(PrincipalRole).index(PrincipalRole.VERIFIER)
    attester = tuple(PrincipalRole).index(PrincipalRole.ATTESTER)
    principals[verifier] = reseal(
        principals[verifier], ExternalPrincipal, "principal_hash",
        external_identity_digest=principals[attester].external_identity_digest,
    )
    with pytest.raises(TrustBackendError):
        reseal(values[1], ProvisioningEvidenceManifest, "manifest_hash", principals=tuple(principals))
    with pytest.raises(TrustBackendError):
        reseal(values[1], ProvisioningEvidenceManifest, "manifest_hash", principals=tuple(reversed(values[1].principals)))
    other = reseal(values[0], ExternalBackendIdentity, "backend_hash", configuration_digest="f" * 64)
    with pytest.raises(TrustBackendError):
        validate(values=values, backend=other)


def test_copy_construct_json_nested_extra_duck_and_unicode_fail_closed():
    values = provisioning_graph()
    for forged in (
        values[0].model_copy(update={"provider": "provider.fake"}),
        ExternalBackendIdentity.model_construct(**{**values[0].model_dump(), "backend_hash": "0" * 64}),
        values[0].model_dump_json().replace("provider.ibkr", "provider.fake"),
    ):
        with pytest.raises(TrustBackendError):
            validate(values=values, backend=forged)
    raw = values[1].model_dump(mode="python", exclude={"manifest_hash"})
    raw["principals"][0]["extra"] = True
    with pytest.raises(TrustBackendError):
        seal_contract_test(ProvisioningEvidenceManifest, "manifest_hash", **raw)
    with pytest.raises(TrustBackendError):
        seal_contract_test(
            ExternalBackendIdentity, "backend_hash", backend_id="backend.externaл.contract",
            provider="provider.ibkr", deployment_identity_digest="0" * 64,
            endpoint_reference_digest="1" * 64, configuration_digest="2" * 64,
            operating_mode=ProvisioningState.CONTRACT_TEST_ONLY,
        )
    with pytest.raises(TrustBackendError):
        validate(values=values, backend=object())


@pytest.mark.parametrize(
    "field",
    ("deployment_identity_digest", "endpoint_reference_digest", "configuration_digest"),
)
def test_secret_bearing_backend_validation_is_sanitized(field):
    secret = f"RAW_{field.upper()}_ACCOUNT_SECRET"
    raw = provisioning_graph()[0].model_dump(mode="python", exclude={"backend_hash"})
    raw[field] = secret
    with pytest.raises(TrustBackendError) as caught:
        seal_contract_test(ExternalBackendIdentity, "backend_hash", **raw)
    rendered = "\n".join((str(caught.value), repr(caught.value), traceback.format_exc()))
    assert secret not in rendered
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_market_mode_connection_local_callback_and_fixtures_cannot_admit_provider():
    values = provisioning_graph()
    result = validate(values=values)
    assert result.provider_admission_real is ProvisioningState.NOT_PROVISIONED
    assert result.authenticity_assessment_hash == values[3].assessment_hash


def test_downgrade_upgrade_tampering_and_unapproved_sealer_models_fail():
    values = provisioning_graph()
    forged = values[1].model_copy(update={"mode": "REAL"})
    with pytest.raises(TrustBackendError):
        validate(values=values, manifest=forged)
    with pytest.raises(TrustBackendError):
        seal_contract_test(type(values[2]), "binding_hash", **values[2].model_dump())
