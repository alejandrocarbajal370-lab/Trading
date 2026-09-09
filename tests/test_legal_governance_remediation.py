import datetime as dt
import json

import pytest
from pydantic import BaseModel

from governance.legal_governance import (
    AdmissionState,
    EvidenceSourceType,
    LegalCapability,
    LegalEvidenceReference,
    LegalGovernanceError,
    LegalJurisdictionReference,
    LegalRequirementRecord,
    LegalScope,
    RequirementStatus,
    RequirementType,
    RightStatus,
    VerificationState,
    assess_contract_test_legal,
    seal_contract_test,
)

UTC = dt.UTC
T0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
T1 = dt.datetime(2026, 2, 1, tzinfo=UTC)
T2 = dt.datetime(2026, 3, 1, tzinfo=UTC)
T3 = dt.datetime(2027, 1, 1, tzinfo=UTC)


def trusted(value, *, exclude=()):
    return BaseModel.model_dump(value, mode="python", exclude=set(exclude))


def reseal(value, model, field, **changes):
    data = trusted(value, exclude=(field,))
    data.update(changes)
    return seal_contract_test(model, field, **data)


def graph(*, omitted=(), overrides=None):
    jurisdiction = seal_contract_test(
        LegalJurisdictionReference, "reference_hash",
        jurisdiction_id="jurisdiction.example", canonical_code="EX-1",
        scope=LegalScope.DATA, subject_id="entity.alpha",
        activity_id="activity.governed-use", provider_ref="provider.alpha.v1",
        dataset_ref="dataset.prices.v1", route_ref="route.research.v1",
        effective_from=T0, effective_to=T3, source_version="source.v1",
        source_digest="1" * 64,
    )
    requirements = []
    evidence = []
    overrides = overrides or {}
    for index, capability in enumerate(LegalCapability, 1):
        if capability in omitted:
            continue
        status, right_status = overrides.get(
            capability,
            (RequirementStatus.EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY,
             RightStatus.GRANTED_CONTRACT_TEST_ONLY),
        )
        requirement = seal_contract_test(
            LegalRequirementRecord, "record_hash",
            requirement_id=f"requirement.{capability.value.lower()}",
            requirement_version="requirement.v1",
            jurisdiction_ref_hash=jurisdiction.reference_hash, subject_id="entity.alpha",
            activity_id="activity.governed-use", scope=LegalScope.DATA,
            use_class=capability, capability=capability,
            requirement_type=RequirementType.DATA_RIGHTS, status=status,
            right_status=right_status, policy_id="policy.data-rights",
            policy_version="policy.v1", policy_hash="2" * 64,
            provider_ref="provider.alpha.v1", dataset_ref="dataset.prices.v1",
            route_ref="route.research.v1", authorized_issuer_id="issuer.counsel.v1",
            authorized_authority_id="authority.registry.v1",
            authorized_verifier_id="verifier.independent.v1", effective_from=T0,
            effective_to=T3, source_version="requirement.source.v1",
            source_digest="3" * 64,
        )
        item = seal_contract_test(
            LegalEvidenceReference, "reference_hash", evidence_id=f"evidence.{index:02d}",
            evidence_version="evidence.v1", source_type=EvidenceSourceType.EXTERNAL_COUNSEL,
            issuer_id=requirement.authorized_issuer_id,
            authority_id=requirement.authorized_authority_id,
            verifier_id=requirement.authorized_verifier_id,
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.requirement_version,
            requirement_hash=requirement.record_hash, policy_id=requirement.policy_id,
            policy_version=requirement.policy_version, policy_hash=requirement.policy_hash,
            jurisdiction_id=jurisdiction.jurisdiction_id, subject_id=requirement.subject_id,
            activity_id=requirement.activity_id, scope=requirement.scope,
            use_class=requirement.use_class, provider_ref=requirement.provider_ref,
            dataset_ref=requirement.dataset_ref, route_ref=requirement.route_ref,
            evidence_digest="4" * 64, provenance_digest="5" * 64, issued_at=T0,
            valid_from=T0, verified_at=T1, expires_at=T3, revoked_at=None,
            verification_state=VerificationState.CONTRACT_TEST_ONLY,
        )
        requirements.append(requirement)
        evidence.append(item)
    return jurisdiction, tuple(requirements), tuple(evidence)


def assess(jurisdiction, requirements, evidence, **changes):
    values = {
        "jurisdictions": (jurisdiction,), "requirements": requirements,
        "evidence": evidence, "reliance_claims": (), "assessed_at": T2,
        "assessment_id": "assessment.001", "operator_id": "operator.001",
        "reviewer_id": "reviewer.001", "approver_id": "approver.001",
    }
    values.update(changes)
    return assess_contract_test_legal(**values)


def capability_state(decision, capability):
    return dict(decision.capability_states)[capability]


def test_complete_independent_capability_matrix_is_local_only():
    jurisdiction, requirements, evidence = graph()
    _, decision = assess(jurisdiction, requirements, evidence)
    assert decision.decision_state is AdmissionState.CONTRACT_TEST_ONLY
    assert all(value is AdmissionState.CONTRACT_TEST_ONLY
               for _, value in decision.capability_states)
    assert decision.legal_licensing_real is AdmissionState.NOT_PROVISIONED


@pytest.mark.parametrize(
    ("omitted", "affected"),
    [
        (LegalCapability.RETENTION,
         (LegalCapability.DURABLE_STORAGE, LegalCapability.REPLAY_AUDIT)),
        (LegalCapability.REDISTRIBUTION, (LegalCapability.REDISTRIBUTION,)),
        (LegalCapability.LIVE_EXECUTION_USE, (LegalCapability.LIVE_EXECUTION_USE,)),
        (LegalCapability.DERIVED_DATA_ARTIFACTS,
         (LegalCapability.DERIVED_DATA_ARTIFACTS,)),
    ],
)
def test_missing_right_does_not_inherit_from_another_capability(omitted, affected):
    jurisdiction, requirements, evidence = graph(omitted=(omitted,))
    _, decision = assess(jurisdiction, requirements, evidence)
    assert decision.decision_state is AdmissionState.REVIEW_REQUIRED
    assert all(capability_state(decision, item) is AdmissionState.REVIEW_REQUIRED
               for item in affected)


@pytest.mark.parametrize(
    ("status", "right", "expected"),
    [
        (RequirementStatus.UNKNOWN, RightStatus.GRANTED_CONTRACT_TEST_ONLY,
         AdmissionState.REVIEW_REQUIRED),
        (RequirementStatus.EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY, RightStatus.UNKNOWN,
         AdmissionState.REVIEW_REQUIRED),
        (RequirementStatus.EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY, RightStatus.AMBIGUOUS,
         AdmissionState.BLOCKED),
        (RequirementStatus.EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY, RightStatus.DENIED,
         AdmissionState.BLOCKED),
    ],
)
def test_unknown_ambiguous_and_denied_are_fail_closed(status, right, expected):
    capability = LegalCapability.INTERNAL_RESEARCH
    jurisdiction, requirements, evidence = graph(overrides={capability: (status, right)})
    _, decision = assess(jurisdiction, requirements, evidence)
    assert capability_state(decision, capability) is expected
    assert decision.decision_state is expected


@pytest.mark.parametrize(
    ("target", "changes"),
    [
        ("requirement", {"requirement_version": "requirement.v2"}),
        ("requirement", {"policy_version": "policy.v2", "policy_hash": "6" * 64}),
        ("evidence", {"issuer_id": "issuer.swapped"}),
        ("evidence", {"authority_id": "authority.swapped"}),
        ("evidence", {"verifier_id": "verifier.swapped"}),
        ("evidence", {"issuer_id": "issuer.swapped",
                      "authority_id": "authority.swapped"}),
        ("evidence", {"provider_ref": "provider.beta.v1"}),
        ("evidence", {"dataset_ref": "dataset.other.v1"}),
        ("evidence", {"route_ref": "route.other.v1"}),
        ("evidence", {"subject_id": "entity.beta"}),
    ],
)
def test_stale_policy_requirement_and_cross_binding_reuse_rejected(target, changes):
    jurisdiction, requirements, evidence = graph()
    if target == "requirement":
        changed = reseal(requirements[0], LegalRequirementRecord, "record_hash", **changes)
        requirements = (changed, *requirements[1:])
    else:
        changed = reseal(evidence[0], LegalEvidenceReference, "reference_hash", **changes)
        evidence = (changed, *evidence[1:])
    with pytest.raises(LegalGovernanceError):
        assess(jurisdiction, requirements, evidence)


def test_copy_construct_json_hash_mismatch_and_reseal_never_widen_rights():
    jurisdiction, requirements, evidence = graph()
    requirement = requirements[0]
    forged = (
        requirement.model_copy(update={"right_status": RightStatus.DENIED}),
        LegalRequirementRecord.model_construct(
            **{**trusted(requirement), "right_status": RightStatus.DENIED}),
        json.dumps({**BaseModel.model_dump(requirement, mode="json"),
                    "right_status": RightStatus.DENIED}),
    )
    for item in forged:
        with pytest.raises(LegalGovernanceError):
            assess(jurisdiction, (item, *requirements[1:]), evidence)
    resealed = reseal(requirement, LegalRequirementRecord, "record_hash",
                      right_status=RightStatus.DENIED)
    with pytest.raises(LegalGovernanceError):
        assess(jurisdiction, (resealed, *requirements[1:]), evidence)


def test_repr_str_dump_json_and_errors_never_leak_sensitive_identifiers():
    jurisdiction, requirements, evidence = graph()
    sensitive = "sensitive.fixture-only-value"
    item = reseal(evidence[0], LegalEvidenceReference, "reference_hash", subject_id=sensitive)
    rendered = (repr(item), str(item), repr(item.model_dump()), item.model_dump_json())
    assert all(sensitive not in value for value in rendered)
    hostile = BaseModel.model_dump(item, mode="json")
    hostile["evidence_digest"] = "invalid"
    for loader in (lambda: LegalEvidenceReference.model_validate(hostile),
                   lambda: LegalEvidenceReference.model_validate_json(json.dumps(hostile))):
        with pytest.raises(LegalGovernanceError) as error:
            loader()
        assert sensitive not in str(error.value) and sensitive not in repr(error.value)
    with pytest.raises(LegalGovernanceError) as error:
        assess(jurisdiction, requirements, (item, *evidence[1:]))
    assert sensitive not in str(error.value)


def test_public_serialization_uses_only_opaque_identifier_digests():
    _, _, evidence = graph()
    dumped = evidence[0].model_dump()
    assert dumped["subject_id"].startswith("opaque:")
    assert dumped["issuer_id"].startswith("opaque:")
    assert dumped["provider_ref"].startswith("opaque:")
