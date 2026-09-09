import datetime as dt

import pytest

from governance.legal_governance import (
    AdmissionState,
    EvidenceSourceType,
    LegalAdmissionDecision,
    LegalAssessmentEvidence,
    LegalEvidenceReference,
    LegalGovernanceError,
    LegalJurisdictionReference,
    LegalRelianceClaim,
    LegalRequirementRecord,
    LegalRole,
    LegalScope,
    RelianceClaimState,
    RequirementStatus,
    RequirementType,
    VerificationState,
    assess_contract_test_legal,
    assess_real_legal,
    seal_contract_test,
)
from governance.phase7e import EvidenceGate, GateState

UTC = dt.UTC
T0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
T1 = dt.datetime(2026, 2, 1, tzinfo=UTC)
T2 = dt.datetime(2026, 3, 1, tzinfo=UTC)
T3 = dt.datetime(2027, 1, 1, tzinfo=UTC)
D = "1" * 64


def reseal(value, model, field, **changes):
    raw = value.model_dump(mode="python", exclude={field})
    raw.update(changes)
    return seal_contract_test(model, field, **raw)


def graph():
    jurisdiction = seal_contract_test(
        LegalJurisdictionReference, "reference_hash",
        jurisdiction_id="jurisdiction.example", canonical_code="EX-1",
        scope=LegalScope.RESEARCH, subject_id="entity.alpha", activity_id="activity.research",
        effective_from=T0, effective_to=T3, source_version="source.v1", source_digest=D,
    )
    requirement = seal_contract_test(
        LegalRequirementRecord, "record_hash", requirement_id="requirement.license",
        jurisdiction_ref_hash=jurisdiction.reference_hash, subject_id="entity.alpha",
        activity_id="activity.research", scope=LegalScope.RESEARCH,
        requirement_type=RequirementType.LICENSE,
        status=RequirementStatus.EXTERNALLY_VERIFIED_CONTRACT_TEST_ONLY,
        effective_from=T0, effective_to=T3, source_version="requirement.v1", source_digest=D,
    )
    evidence = seal_contract_test(
        LegalEvidenceReference, "reference_hash", evidence_id="evidence.requirement.license",
        evidence_version="evidence.v1", source_type=EvidenceSourceType.EXTERNAL_COUNSEL,
        issuer_id="authority.example", authority_id="authority.example",
        jurisdiction_id="jurisdiction.example", subject_id="entity.alpha",
        activity_id="activity.research", scope=LegalScope.RESEARCH, evidence_digest=D,
        provenance_digest="2" * 64, issued_at=T0, valid_from=T0, verified_at=T1,
        expires_at=T3, revoked_at=None, verification_state=VerificationState.CONTRACT_TEST_ONLY,
    )
    return jurisdiction, requirement, evidence


def assess(jurisdictions=None, requirements=None, evidence=None, **changes):
    j, r, e = graph()
    values = {
        "jurisdictions": (j,) if jurisdictions is None else jurisdictions,
        "requirements": (r,) if requirements is None else requirements,
        "evidence": (e,) if evidence is None else evidence,
        "reliance_claims": (),
        "assessed_at": T2,
        "assessment_id": "assessment.001",
        "operator_id": "operator.001",
        "reviewer_id": "reviewer.001",
        "approver_id": "approver.001",
    }
    values.update(changes)
    return assess_contract_test_legal(**values)


def test_exact_graph_reaches_contract_test_only_never_real():
    assessment, decision = assess()
    assert isinstance(assessment, LegalAssessmentEvidence)
    assert isinstance(decision, LegalAdmissionDecision)
    assert decision.decision_state is AdmissionState.CONTRACT_TEST_ONLY
    assert {decision.legal_licensing_real, decision.authority_registry_real,
            decision.external_counsel_real, decision.provider_admission_real} == {
                AdmissionState.NOT_PROVISIONED}
    assert decision.gate_states == tuple((g, GateState.OPEN_EXTERNAL) for g in EvidenceGate)
    assert decision.real_route == "QVM_NOT_READY"
    assert decision.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert decision.trade_decision == "NO_TRADE"
    assert not decision.signals_generated and not decision.live_execution_enabled
    assert decision.backtesting == "NOT_AUTHORIZED"
    with pytest.raises(LegalGovernanceError, match="NOT_PROVISIONED"):
        assess_real_legal(jurisdictions=graph())


@pytest.mark.parametrize("part", ["jurisdiction", "requirement", "evidence"])
def test_missing_graph_component_fails_closed(part):
    args = {f"{part}s" if part != "evidence" else "evidence": ()}
    with pytest.raises(LegalGovernanceError):
        assess(**args)


@pytest.mark.parametrize(
    ("field", "value"),
    [("jurisdiction_id", "jurisdiction.unknown"), ("scope", LegalScope.EXECUTION),
     ("activity_id", "activity.execution"), ("subject_id", "entity.beta")],
)
def test_evidence_scope_jurisdiction_activity_or_entity_reuse_rejected(field, value):
    j, r, e = graph()
    bad = reseal(e, LegalEvidenceReference, "reference_hash", **{field: value})
    with pytest.raises(LegalGovernanceError):
        assess(jurisdictions=(j,), requirements=(r,), evidence=(bad,))


def test_unknown_jurisdiction_requirement_rejected():
    j, r, e = graph()
    bad = reseal(r, LegalRequirementRecord, "record_hash", jurisdiction_ref_hash="3" * 64)
    with pytest.raises(LegalGovernanceError):
        assess(jurisdictions=(j,), requirements=(bad,), evidence=(e,))


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": T2},
        {"revoked_at": T2},
        {"issued_at": T3, "verified_at": T3},
        {"issuer_id": "issuer.other"},
        {"verification_state": VerificationState.UNVERIFIED},
        {"verification_state": VerificationState.NOT_PROVISIONED},
    ],
)
def test_stale_future_mismatched_or_untrusted_evidence_rejected(changes):
    j, r, e = graph()
    bad = reseal(e, LegalEvidenceReference, "reference_hash", **changes)
    with pytest.raises(LegalGovernanceError):
        assess(jurisdictions=(j,), requirements=(r,), evidence=(bad,))


def test_wrong_jurisdiction_counsel_evidence_rejected():
    j, r, e = graph()
    other = reseal(j, LegalJurisdictionReference, "reference_hash",
                   jurisdiction_id="jurisdiction.other", canonical_code="OT-1")
    bad = reseal(e, LegalEvidenceReference, "reference_hash",
                 jurisdiction_id="jurisdiction.other")
    with pytest.raises(LegalGovernanceError):
        assess(jurisdictions=(j, other), requirements=(r,), evidence=(bad,))


def test_missing_evidence_does_not_imply_exemption():
    j, r, e = graph()
    unrelated = reseal(e, LegalEvidenceReference, "reference_hash",
                       evidence_id="evidence.unrelated")
    assessment, decision = assess(jurisdictions=(j,), requirements=(r,), evidence=(unrelated,))
    assert assessment.missing_evidence == ("missing.requirement.evidence",)
    assert decision.decision_state is AdmissionState.REVIEW_REQUIRED
    assert decision.legal_licensing_real is AdmissionState.NOT_PROVISIONED


def test_reliance_claim_is_separate_review_input_not_a_conclusion():
    j, r, _ = graph()
    claim = seal_contract_test(
        LegalRelianceClaim, "claim_hash", claim_id="claim.exemption.001",
        jurisdiction_ref_hash=j.reference_hash, requirement_record_hash=r.record_hash,
        subject_id="entity.alpha", activity_id="activity.research", scope=LegalScope.RESEARCH,
        claim_state=RelianceClaimState.REQUIRES_EXTERNAL_REVIEW,
        source_version="claim.v1", source_digest="4" * 64,
    )
    assessment, decision = assess(reliance_claims=(claim,))
    assert assessment.reliance_claim_hashes == (claim.claim_hash,)
    assert decision.legal_licensing_real is AdmissionState.NOT_PROVISIONED


def test_conflicts_and_ambiguous_multi_jurisdiction_fail_closed():
    assessment, decision = assess(unresolved_conflicts=("conflict.requirement",))
    assert assessment.unresolved_conflicts
    assert decision.decision_state is AdmissionState.BLOCKED
    j, r, e = graph()
    other = reseal(j, LegalJurisdictionReference, "reference_hash",
                   jurisdiction_id="jurisdiction.other", canonical_code="OT-1")
    other_r = reseal(r, LegalRequirementRecord, "record_hash",
                     requirement_id="requirement.other", jurisdiction_ref_hash=other.reference_hash)
    other_e = reseal(e, LegalEvidenceReference, "reference_hash",
                     evidence_id="evidence.requirement.other",
                     jurisdiction_id="jurisdiction.other")
    _, multi = assess(jurisdictions=(j, other), requirements=(r, other_r),
                      evidence=(e, other_e), unresolved_conflicts=("conflict.multi-jurisdiction",))
    assert multi.decision_state is AdmissionState.BLOCKED


def test_hash_version_tamper_and_reseal_cannot_reach_real():
    j, r, e = graph()
    raw = e.model_dump(mode="python")
    raw["evidence_version"] = "evidence.v2"
    with pytest.raises(LegalGovernanceError):
        LegalEvidenceReference.model_validate(raw)
    resealed = reseal(e, LegalEvidenceReference, "reference_hash", evidence_version="evidence.v2")
    _, decision = assess(jurisdictions=(j,), requirements=(r,), evidence=(resealed,))
    assert decision.decision_state is AdmissionState.CONTRACT_TEST_ONLY
    assert decision.legal_licensing_real is AdmissionState.NOT_PROVISIONED


def test_maker_checker_reviewer_separation_and_secret_safe_repr():
    with pytest.raises(LegalGovernanceError):
        assess(reviewer_id="operator.001")
    _, _, evidence = graph()
    assert "authority.example" not in repr(evidence)
    assert "authority.example" not in str(evidence)
    assert tuple(LegalRole) == (
        LegalRole.LEGAL_EVIDENCE_OPERATOR, LegalRole.LEGAL_REVIEWER, LegalRole.LEGAL_APPROVER)
