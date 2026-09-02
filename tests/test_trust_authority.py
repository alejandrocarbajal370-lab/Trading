import datetime as dt

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.external_provider_foundation import FoundationError, ProvisioningState
from governance.phase7e import EvidenceGate, GateState
from governance.trust_authority import (
    Approval,
    AuthorityCapability,
    AuthorityRole,
    EvidenceReference,
    TrustAnchorIdentity,
    TrustAnchorRegistration,
    build_contract_test_anchor_registration,
    build_contract_test_authority,
    build_contract_test_registry,
    build_trust_anchor_identity,
    observe_contract_test_provisioning,
    verify_real_authority_provisioning,
)

EFFECTIVE = dt.datetime(2026, 9, 2, 20, tzinfo=dt.UTC)
AVAILABLE = EFFECTIVE + dt.timedelta(minutes=4)
ANCHOR_AVAILABLE = AVAILABLE + dt.timedelta(minutes=1)
OBSERVED = ANCHOR_AVAILABLE + dt.timedelta(minutes=1)
VERIFIED = OBSERVED + dt.timedelta(minutes=1)


def reference(name="evidence.ref", digest="a" * 64):
    return EvidenceReference(
        reference_id=name, media_type="application/json", digest=digest, size=10
    )


def identity(anchor_id="anchor.primary", fingerprint="b" * 64, digest="a" * 64):
    return build_trust_anchor_identity(
        anchor_id=anchor_id,
        anchor_kind="PUBLIC_KEY",
        credential_reference=reference("credential.ref", digest),
        fingerprint=fingerprint,
    )


def registration(anchor=None, **overrides):
    values = {
        "anchor": anchor or identity(),
        "provider_id": "provider.primary",
        "gate": EvidenceGate.RETENTION_WORM,
        "scope_id": "scope.retention",
        "policy_version": "policy.v1",
        "effective_at": EFFECTIVE,
        "available_at": ANCHOR_AVAILABLE,
    }
    values.update(overrides)
    return build_contract_test_anchor_registration(**values)


def contract(anchor=None, **overrides):
    anchor = anchor or registration()
    values = {
        "authority_id": "authority.primary",
        "trust_anchor_identity_hash": anchor.anchor.identity_hash,
        "trust_anchor_registration_hash": anchor.registration_hash,
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


def observe(authority, anchor, **overrides):
    values = {
        "expected_contract_hash": authority.contract_hash,
        "expected_anchor_registration_hash": anchor.registration_hash,
        "observed_at": OBSERVED,
        "verified_at": VERIFIED,
    }
    values.update(overrides)
    return observe_contract_test_provisioning(authority, anchor, reference(), **values)


def test_independently_content_addressed_and_test_only_observation():
    anchor = registration()
    authority = contract(anchor)
    result = observe(authority, anchor)
    assert authority.provisioning_state is ProvisioningState.CONTRACT_TEST_ONLY
    assert anchor.registration_hash == typed_hash(
        anchor.model_dump(mode="json", exclude={"registration_hash"})
    )
    assert anchor.anchor.identity_hash == typed_hash(
        anchor.anchor.model_dump(mode="json", exclude={"identity_hash"})
    )
    assert result.state == "OBSERVED_UNTRUSTED"
    assert result.trust_root is result.independent_verifier is ProvisioningState.NOT_PROVISIONED
    assert result.gate_state is GateState.OPEN_EXTERNAL
    with pytest.raises(FoundationError, match="NOT_PROVISIONED"):
        verify_real_authority_provisioning(evidence={"state": "TRUSTED"})


def test_independent_revocations_and_exact_boundaries_fail_closed():
    revoked_anchor = registration(revoked_at=VERIFIED)
    with pytest.raises(ValidationError, match="anchor was revoked"):
        observe(contract(revoked_anchor), revoked_anchor)
    valid_anchor = registration()
    with pytest.raises(ValidationError, match="authority was revoked"):
        observe(contract(valid_anchor, revoked_at=VERIFIED), valid_anchor)
    between = registration(revoked_at=OBSERVED + dt.timedelta(seconds=1))
    with pytest.raises(ValidationError, match="anchor was revoked"):
        observe(contract(between), between)


@pytest.mark.parametrize(
    ("authority_available", "anchor_available", "message"),
    [
        (OBSERVED + dt.timedelta(seconds=1), ANCHOR_AVAILABLE, "authority availability"),
        (AVAILABLE, OBSERVED + dt.timedelta(seconds=1), "anchor availability"),
    ],
)
def test_observation_must_follow_both_availability_times(
    authority_available, anchor_available, message
):
    anchor = registration(available_at=anchor_available)
    authority = contract(anchor, available_at=authority_available)
    with pytest.raises(ValidationError, match=message):
        observe(authority, anchor)


def test_observation_after_both_availability_times_is_only_untrusted():
    anchor = registration()
    assert observe(contract(anchor), anchor).state == "OBSERVED_UNTRUSTED"


def test_lifecycle_causality_offsets_and_naive_utc_fail():
    with pytest.raises(ValidationError, match="availability precedes"):
        registration(available_at=EFFECTIVE - dt.timedelta(seconds=1))
    with pytest.raises(ValidationError, match="revocation must follow"):
        registration(revoked_at=ANCHOR_AVAILABLE)
    with pytest.raises(ValidationError, match="canonical UTC"):
        registration(effective_at=EFFECTIVE.astimezone(dt.timezone(dt.timedelta(hours=-6))))
    with pytest.raises(ValidationError, match="canonical UTC"):
        registration(effective_at=EFFECTIVE.replace(tzinfo=None))


def test_rotation_nonoverlap_and_same_identity_windows_allowed_duplicates_overlap_rejected():
    boundary = EFFECTIVE + dt.timedelta(days=1)
    old = registration(revoked_at=boundary)
    old_authority = contract(old, revoked_at=boundary)
    with pytest.raises(ValidationError, match="duplicate anchor"):
        build_contract_test_registry(old_authority, anchor_registrations=(old, old))
    overlap = registration(
        anchor=identity("anchor.next", "c" * 64, "c" * 64),
        effective_at=EFFECTIVE + dt.timedelta(hours=1),
        available_at=EFFECTIVE + dt.timedelta(hours=2),
    )
    with pytest.raises(ValidationError, match="overlapping anchor"):
        build_contract_test_registry(old_authority, anchor_registrations=(old, overlap))
    successor = registration(
        anchor=identity("anchor.next", "c" * 64, "c" * 64),
        policy_version="policy.v2",
        effective_at=boundary,
        available_at=boundary,
    )
    successor_authority = contract(
        successor,
        authority_id="authority.next",
        policy_version="policy.v2",
        effective_at=boundary,
        available_at=boundary,
        approvals=tuple(
            Approval(role=r, actor_id=f"next.{r.value.lower()}", approved_at=boundary)
            for r in AuthorityRole
        ),
    )
    assert (
        len(
            build_contract_test_registry(
                old_authority, successor_authority, anchor_registrations=(old, successor)
            ).anchor_registrations
        )
        == 2
    )
    same = registration(
        anchor=old.anchor, policy_version="policy.v2", effective_at=boundary, available_at=boundary
    )
    same_authority = contract(
        same,
        authority_id="authority.same",
        policy_version="policy.v2",
        effective_at=boundary,
        available_at=boundary,
        approvals=tuple(
            Approval(role=r, actor_id=f"same.{r.value.lower()}", approved_at=boundary)
            for r in AuthorityRole
        ),
    )
    assert build_contract_test_registry(
        old_authority, same_authority, anchor_registrations=(old, same)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "provider.other"),
        ("gate", EvidenceGate.LICENSING_LEGAL),
        ("scope_id", "scope.other"),
    ],
)
def test_cross_provider_gate_scope_anchor_swap_matrix(field, value):
    original = registration()
    swapped = registration(**{field: value})
    with pytest.raises(FoundationError, match="binding mismatch"):
        observe(
            contract(original), swapped, expected_anchor_registration_hash=swapped.registration_hash
        )


def test_resealed_swap_nested_mutation_construct_copy_and_json_revalidation():
    anchor = registration()
    authority = contract(anchor)
    swapped = registration(policy_version="policy.v2")
    with pytest.raises(FoundationError, match="registration binding mismatch"):
        observe(authority, swapped, expected_anchor_registration_hash=anchor.registration_hash)
    raw = anchor.model_dump(mode="python")
    raw["anchor"]["fingerprint"] = "c" * 64
    raw["registration_hash"] = typed_hash(
        {k: v for k, v in raw.items() if k != "registration_hash"}
    )
    bypass = TrustAnchorRegistration.model_construct(**raw)
    with pytest.raises(FoundationError, match="invalid trust anchor registration"):
        observe(authority, bypass, expected_anchor_registration_hash=raw["registration_hash"])
    copied = anchor.model_copy(update={"provider_id": "provider.other"})
    with pytest.raises(FoundationError, match="invalid trust anchor registration"):
        observe(authority, copied)
    assert TrustAnchorRegistration.model_validate_json(anchor.model_dump_json()) == anchor


def test_same_id_fingerprint_cannot_hide_new_material_and_models_are_closed():
    original = identity()
    changed = identity(digest="d" * 64)
    assert original.anchor_id == changed.anchor_id and original.fingerprint == changed.fingerprint
    assert original.identity_hash != changed.identity_hash
    anchor = registration(anchor=original)
    with pytest.raises(FoundationError, match="binding mismatch"):
        observe(contract(anchor), registration(anchor=changed))
    with pytest.raises(ValidationError):
        TrustAnchorIdentity.model_validate(original.model_dump() | {"private_key": "secret"})
    with pytest.raises(ValidationError):
        TrustAnchorRegistration.model_validate(anchor.model_dump() | {"extra": "forbidden"})


def test_maker_checker_versions_aliases_and_authority_overlap_fail():
    anchor = registration()
    approvals = list(contract(anchor).approvals)
    approvals[1] = approvals[1].model_copy(update={"actor_id": approvals[0].actor_id})
    with pytest.raises(ValidationError, match="self-approval"):
        contract(anchor, approvals=approvals)
    with pytest.raises(ValidationError):
        TrustAnchorRegistration.model_validate(anchor.model_dump() | {"contract_version": "v0"})
    with pytest.raises((ValidationError, ValueError)):
        identity(anchor_id="Anchor.Primary")
    first = contract(anchor, revoked_at=EFFECTIVE + dt.timedelta(days=1))
    second = contract(
        anchor,
        effective_at=EFFECTIVE + dt.timedelta(hours=1),
        available_at=EFFECTIVE + dt.timedelta(hours=2),
    )
    with pytest.raises(ValidationError, match="overlapping authority"):
        build_contract_test_registry(first, second, anchor_registrations=(anchor,))
