import datetime as dt

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.external_provider_foundation import FoundationError, ProvisioningState
from governance.phase7e import EvidenceGate, GateState
from governance.trust_authority import (
    Approval,
    AuthorityCapability,
    AuthorityContract,
    AuthorityRole,
    EvidenceReference,
    build_contract_test_authority,
    build_contract_test_registry,
    observe_contract_test_provisioning,
    verify_real_authority_provisioning,
)

EFFECTIVE = dt.datetime(2026, 9, 2, 20, tzinfo=dt.UTC)
AVAILABLE = EFFECTIVE + dt.timedelta(minutes=4)
OBSERVED = AVAILABLE + dt.timedelta(minutes=1)
VERIFIED = OBSERVED + dt.timedelta(minutes=1)


def reference(name="evidence.ref"):
    return EvidenceReference(
        reference_id=name, media_type="application/json", digest="a" * 64, size=10
    )


def contract(**overrides):
    values = {
        "authority_id": "authority.primary",
        "trust_anchor": {
            "anchor_id": "anchor.primary",
            "anchor_kind": "PUBLIC_KEY",
            "credential_reference": reference("credential.ref"),
            "fingerprint": "b" * 64,
        },
        "provider_id": "provider.primary",
        "gate": EvidenceGate.RETENTION_WORM,
        "scope_id": "scope.retention",
        "policy_version": "policy.v1",
        "capabilities": tuple(AuthorityCapability),
        "effective_at": EFFECTIVE,
        "available_at": AVAILABLE,
        "approvals": tuple(
            Approval(role=role, actor_id=f"actor.{role.value.lower()}", approved_at=AVAILABLE)
            for role in AuthorityRole
        ),
    }
    values.update(overrides)
    return build_contract_test_authority(**values)


def test_contract_is_closed_content_addressed_and_test_only():
    item = contract()
    assert item.provisioning_state is ProvisioningState.CONTRACT_TEST_ONLY
    assert item.contract_hash == typed_hash(
        item.model_dump(mode="json", exclude={"contract_hash"})
    )
    assert item.trust_anchor.credential_reference.digest == "a" * 64


def test_observation_never_promotes_external_truth_and_real_route_is_sealed():
    item = contract()
    result = observe_contract_test_provisioning(
        item,
        reference(),
        expected_contract_hash=item.contract_hash,
        observed_at=OBSERVED,
        verified_at=VERIFIED,
    )
    assert result.state == "OBSERVED_UNTRUSTED"
    assert result.trust_root is ProvisioningState.NOT_PROVISIONED
    assert result.independent_verifier is ProvisioningState.NOT_PROVISIONED
    assert result.gate_state is GateState.OPEN_EXTERNAL
    with pytest.raises(FoundationError, match="NOT_PROVISIONED"):
        verify_real_authority_provisioning(
            evidence={"state": "TRUSTED"}, registry={"backend": "fixture"}
        )


def test_self_approval_missing_roles_duplicates_and_forged_capabilities_fail():
    approvals = list(contract().approvals)
    approvals[1] = approvals[1].model_copy(update={"actor_id": approvals[0].actor_id})
    with pytest.raises(ValidationError, match="self-approval"):
        contract(approvals=approvals)
    with pytest.raises(ValidationError, match="exactly one"):
        contract(approvals=approvals[:3])
    with pytest.raises(ValidationError):
        contract(capabilities=("ADMIN",))


def test_temporal_boundaries_revocation_and_utc_are_verifier_time_aware():
    revoked = contract(revoked_at=VERIFIED)
    with pytest.raises(ValidationError, match="revoked at verifier time"):
        observe_contract_test_provisioning(
            revoked,
            reference(),
            expected_contract_hash=revoked.contract_hash,
            observed_at=OBSERVED,
            verified_at=VERIFIED,
        )
    with pytest.raises(ValidationError, match="predates"):
        item = contract()
        observe_contract_test_provisioning(
            item,
            reference(),
            expected_contract_hash=item.contract_hash,
            observed_at=EFFECTIVE - dt.timedelta(seconds=1),
            verified_at=VERIFIED,
        )
    with pytest.raises(ValidationError, match="canonical UTC"):
        contract(effective_at=EFFECTIVE.astimezone(dt.timezone(dt.timedelta(hours=-6))))


def test_deep_revalidation_rejects_swaps_mutation_reseal_and_construct_bypass():
    item = contract()
    raw = item.model_dump(mode="json")
    raw["authority_id"] = "authority.swapped"
    raw["contract_hash"] = typed_hash({k: v for k, v in raw.items() if k != "contract_hash"})
    swapped = AuthorityContract.model_construct(**raw)
    with pytest.raises(FoundationError, match="binding mismatch"):
        observe_contract_test_provisioning(
            swapped,
            reference(),
            expected_contract_hash=item.contract_hash,
            observed_at=OBSERVED,
            verified_at=VERIFIED,
        )
    raw = item.model_dump(mode="python")
    raw["trust_anchor"]["fingerprint"] = "c" * 64
    bypass = AuthorityContract.model_construct(**raw)
    with pytest.raises(FoundationError, match="invalid authority contract"):
        observe_contract_test_provisioning(
            bypass,
            reference(),
            expected_contract_hash=item.contract_hash,
            observed_at=OBSERVED,
            verified_at=VERIFIED,
        )


@pytest.mark.parametrize("bad", ["Authority.Primary", "authorit\N{CYRILLIC SMALL LETTER A}.primary"])
def test_identifier_aliases_and_unicode_confusables_fail(bad):
    with pytest.raises((ValidationError, ValueError)):
        contract(authority_id=bad)


def test_unknown_or_stale_versions_and_secret_fields_fail():
    raw = contract().model_dump(mode="python")
    raw["contract_version"] = "trust-anchor-authority-contract-v0"
    with pytest.raises(ValidationError):
        AuthorityContract.model_validate(raw)
    credential = reference("credential.ref").model_dump()
    credential["private_key"] = "secret"
    with pytest.raises(ValidationError):
        EvidenceReference.model_validate(credential)


def test_registry_rejects_duplicates_and_overlapping_windows_but_allows_rotation():
    first = contract(revoked_at=EFFECTIVE + dt.timedelta(days=1))
    with pytest.raises(ValidationError, match="duplicate"):
        build_contract_test_registry(first, first)
    overlapping = contract(
        policy_version="policy.v2",
        effective_at=EFFECTIVE + dt.timedelta(hours=1),
        available_at=EFFECTIVE + dt.timedelta(hours=2),
    )
    with pytest.raises(ValidationError, match="overlapping"):
        build_contract_test_registry(first, overlapping)
    successor_effective = EFFECTIVE + dt.timedelta(days=1)
    successor = contract(
        policy_version="policy.v2",
        effective_at=successor_effective,
        available_at=successor_effective,
        approvals=tuple(
            Approval(
                role=role,
                actor_id=f"next.{role.value.lower()}",
                approved_at=successor_effective,
            )
            for role in AuthorityRole
        ),
    )
    assert len(build_contract_test_registry(first, successor).authorities) == 2
