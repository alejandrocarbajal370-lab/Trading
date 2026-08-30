import datetime as dt
import hashlib

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState
from governance.phase7f import (
    PHASE7F_CONTRACT_VERSION,
    PHASE7F_TEMPORAL_POLICY_VERSION,
    AdmissionStage,
    AnchorBinding,
    ArtifactClass,
    ArtifactRequest,
    AuthorityBinding,
    AuthorityCapability,
    AuthorityClass,
    AuthorityProvenance,
    ContractAuthority,
    ContractAuthorityRegistry,
    ContractPolicy,
    ContractReviewerIdentityRegistry,
    ContractTrustAnchorRegistry,
    CustodyRecord,
    IndependentAuditRecord,
    Phase7FContractError,
    ProviderDatasetCandidate,
    ResolvedArtifact,
    ReviewDecision,
    ReviewerIdentity,
    ReviewerRole,
    ScopeCoverage,
    TrustAnchor,
    admission_snapshot_hash,
    real_external_authority_verifier_unavailable,
    verify_contract_admission,
)

NOW = dt.datetime(2026, 8, 29, tzinfo=dt.UTC)
PAST = NOW - dt.timedelta(days=30)


def seal(cls, field, **values):
    raw = cls.model_construct(**values, **{field: "0" * 64})
    values[field] = typed_hash(raw.model_dump(mode="json", exclude={field}, warnings=False))
    return cls(**values)


def universe():
    provenance = seal(
        AuthorityProvenance,
        "provenance_hash",
        provenance_id="prov.synthetic",
        issuer="synthetic fixture",
        issued_at=PAST,
        declaration="contract consistency only",
    )
    authorities = []
    specs = (
        ("authority.anchor", AuthorityClass.GOVERNANCE, AuthorityCapability.ANCHOR),
        ("authority.custody", AuthorityClass.CUSTODY, AuthorityCapability.CUSTODY),
        ("authority.identity", AuthorityClass.IDENTITY, AuthorityCapability.REVIEWERS),
        ("authority.policy", AuthorityClass.GOVERNANCE, AuthorityCapability.POLICY),
        ("authority.audit", AuthorityClass.AUDIT, AuthorityCapability.AUDIT),
    )
    for authority_id, authority_class, capability in specs:
        authorities.append(
            seal(
                ContractAuthority,
                "authority_hash",
                authority_id=authority_id,
                authority_class=authority_class,
                capabilities=(capability,),
                valid_from=PAST,
                provenance=provenance,
            )
        )
    authority_registry = seal(
        ContractAuthorityRegistry,
        "registry_hash",
        registry_id="registry.authority",
        valid_from=PAST,
        authorities=tuple(sorted(authorities, key=lambda item: item.authority_id)),
    )

    def authority_binding(authority_id):
        authority = next(x for x in authorities if x.authority_id == authority_id)
        return AuthorityBinding(
            authority_id=authority_id,
            authority_registry_version=authority_registry.version,
            authority_registry_hash=authority_registry.registry_hash,
            authority_hash=authority.authority_hash,
            provenance_hash=authority.provenance.provenance_hash,
        )

    anchor = seal(
        TrustAnchor,
        "anchor_hash",
        anchor_id="anchor.evidence",
        source_system_id="source.custody",
        authority=authority_binding("authority.anchor"),
        artifact_classes=(
            ArtifactClass.EVIDENCE,
            ArtifactClass.IDENTITY_REGISTRY,
            ArtifactClass.CUSTODY_AUDIT,
        ),
        activated_at=PAST,
    )
    anchor_registry = seal(
        ContractTrustAnchorRegistry,
        "registry_hash",
        authority_registry_hash=authority_registry.registry_hash,
        anchors=(anchor,),
    )
    anchor_binding = AnchorBinding(
        anchor_id=anchor.anchor_id,
        source_system_id=anchor.source_system_id,
        anchor_version=anchor.version,
        anchor_hash=anchor.anchor_hash,
        anchor_registry_version=anchor_registry.version,
        anchor_registry_hash=anchor_registry.registry_hash,
    )
    identities = (
        ReviewerIdentity(
            actor_id="actor_00000001",
            aliases=("Maker Alice",),
            roles=(ReviewerRole.MAKER,),
            valid_from=PAST,
        ),
        ReviewerIdentity(
            actor_id="actor_00000002",
            aliases=("Checker Bob",),
            roles=(ReviewerRole.CHECKER,),
            valid_from=PAST,
        ),
        ReviewerIdentity(
            actor_id="actor_00000003",
            aliases=("Auditor Céline",),
            roles=(ReviewerRole.INDEPENDENT_AUDITOR,),
            valid_from=PAST,
        ),
    )
    reviewers = seal(
        ContractReviewerIdentityRegistry,
        "registry_hash",
        registry_id="registry.reviewers",
        authority=authority_binding("authority.identity"),
        anchor=anchor_binding,
        valid_from=PAST,
        identities=identities,
    )
    scope = seal(
        ScopeCoverage,
        "scope_hash",
        scope_id="scope.declared",
        dimensions=("market:synthetic", "universe:synthetic"),
        coverage_start=PAST,
        coverage_end=NOW,
    )
    policy = seal(
        ContractPolicy,
        "policy_hash",
        policy_id="policy.admission",
        policy_version="policy.v1",
        authority=authority_binding("authority.policy"),
        effective_from=PAST,
        required_gates=tuple(EvidenceGate),
    )
    candidate = seal(
        ProviderDatasetCandidate,
        "candidate_hash",
        candidate_id="candidate.synthetic",
        provider_id="provider.synthetic",
        dataset_id="dataset.synthetic",
        dataset_version="dataset.v1",
        scope=scope,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        required_anchors=(anchor_binding,),
        required_gates=tuple(EvidenceGate),
        declared_at=PAST,
    )
    request = ArtifactRequest(
        request_id="request.synthetic",
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate.candidate_hash,
        anchor=anchor_binding,
        canonical_source_id="contract://synthetic/evidence",
        artifact_id="artifact.synthetic",
        artifact_class=ArtifactClass.EVIDENCE,
        artifact_version="artifact.v1",
        gate=EvidenceGate.LICENSING_LEGAL,
        provider_id=candidate.provider_id,
        dataset_id=candidate.dataset_id,
        dataset_version=candidate.dataset_version,
        scope_id=scope.scope_id,
        scope_hash=scope.scope_hash,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        as_of=NOW - dt.timedelta(days=1),
        requested_at=NOW - dt.timedelta(hours=3),
    )
    source = b"synthetic contract evidence"
    custody = seal(
        CustodyRecord,
        "custody_hash",
        custody_record_id="custody.synthetic",
        authority=authority_binding("authority.custody"),
        anchor=anchor_binding,
        provider_id=request.provider_id,
        dataset_id=request.dataset_id,
        artifact_id=request.artifact_id,
        artifact_version=request.artifact_version,
        gate=request.gate,
        scope_id=request.scope_id,
        as_of=request.as_of,
        effective_at=request.as_of,
        available_at=NOW - dt.timedelta(hours=2),
        source_sha256=hashlib.sha256(source).hexdigest(),
    )
    artifact = ResolvedArtifact(
        request_hash=typed_hash(request.model_dump(mode="json")),
        canonical_source_id=request.canonical_source_id,
        artifact_id=request.artifact_id,
        artifact_version=request.artifact_version,
        retrieved_at=NOW - dt.timedelta(hours=1),
        custody=custody,
        source_bytes_hex=source.hex(),
        source_sha256=hashlib.sha256(source).hexdigest(),
    )
    decision = seal(
        ReviewDecision,
        "decision_hash",
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate.candidate_hash,
        request_hash=typed_hash(request.model_dump(mode="json")),
        artifact_hash=typed_hash(artifact.model_dump(mode="json")),
        gate=request.gate,
        provider_id=candidate.provider_id,
        dataset_id=candidate.dataset_id,
        dataset_version=candidate.dataset_version,
        scope_id=scope.scope_id,
        scope_hash=scope.scope_hash,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        reviewer_registry_hash=reviewers.registry_hash,
        maker_claim="Maker Alice",
        checker_claim="Checker Bob",
        decided_at=NOW - dt.timedelta(minutes=30),
        decision="ACCEPT",
    )
    items = [
        candidate,
        authority_registry,
        anchor_registry,
        reviewers,
        policy,
        request,
        artifact,
        decision,
    ]
    snapshot = admission_snapshot_hash(
        authority_registry,
        anchor_registry,
        candidate,
        policy,
        request,
        artifact,
        decision,
        reviewers,
        NOW,
    )
    audit = seal(
        IndependentAuditRecord,
        "audit_hash",
        audit_id="audit.synthetic",
        authority=authority_binding("authority.audit"),
        anchor=anchor_binding,
        auditor_claim="Auditor Céline",
        audited_at=NOW - dt.timedelta(minutes=5),
        verifier_time=NOW,
        policy_version=PHASE7F_CONTRACT_VERSION,
        temporal_policy_version=PHASE7F_TEMPORAL_POLICY_VERSION,
        snapshot_hash=snapshot,
        verdict="APPROVE",
    )
    return items + [audit]


def verify(items):
    return verify_contract_admission(*items, verifier_time=NOW)


def reseal(obj, cls, field, **updates):
    values = obj.model_dump(mode="python", exclude={"version", field})
    values.update(updates)
    return seal(cls, field, **values)


def refresh_audit(items):
    values = items[8].model_dump(mode="python", exclude={"version", "audit_hash"})
    values["snapshot_hash"] = admission_snapshot_hash(
        items[1], items[2], items[0], items[4], items[5], items[6], items[7], items[3], NOW
    )
    items[8] = seal(IndependentAuditRecord, "audit_hash", **values)


def set_chronology(
    items,
    *,
    requested_at=None,
    custody_available_at=None,
    retrieved_at=None,
    decided_at=None,
    audited_at=None,
):
    """Reseal every downstream binding after a deliberate chronology change."""
    if requested_at is not None:
        items[5] = items[5].model_copy(update={"requested_at": requested_at})
    custody = items[6].custody
    if custody_available_at is not None:
        custody = reseal(
            custody, CustodyRecord, "custody_hash", available_at=custody_available_at
        )
    artifact_updates = {"custody": custody, "request_hash": typed_hash(items[5].model_dump(mode="json"))}
    if retrieved_at is not None:
        artifact_updates["retrieved_at"] = retrieved_at
    items[6] = items[6].model_copy(update=artifact_updates)
    decision_updates = {
        "request_hash": typed_hash(items[5].model_dump(mode="json")),
        "artifact_hash": typed_hash(items[6].model_dump(mode="json")),
    }
    if decided_at is not None:
        decision_updates["decided_at"] = decided_at
    items[7] = reseal(items[7], ReviewDecision, "decision_hash", **decision_updates)
    if audited_at is not None:
        items[8] = reseal(
            items[8], IndependentAuditRecord, "audit_hash", audited_at=audited_at
        )
    refresh_audit(items)


def replace_anchor(items, **updates):
    """Rebind the complete snapshot to a resealed anchor, preserving all local hashes."""
    anchor = reseal(items[2].anchors[0], TrustAnchor, "anchor_hash", **updates)
    items[2] = reseal(items[2], ContractTrustAnchorRegistry, "registry_hash", anchors=(anchor,))
    binding = AnchorBinding(
        anchor_id=anchor.anchor_id,
        source_system_id=anchor.source_system_id,
        anchor_version=anchor.version,
        anchor_hash=anchor.anchor_hash,
        anchor_registry_version=items[2].version,
        anchor_registry_hash=items[2].registry_hash,
    )
    items[0] = reseal(
        items[0], ProviderDatasetCandidate, "candidate_hash", required_anchors=(binding,)
    )
    items[5] = items[5].model_copy(
        update={"candidate_hash": items[0].candidate_hash, "anchor": binding}
    )
    items[3] = reseal(items[3], ContractReviewerIdentityRegistry, "registry_hash", anchor=binding)
    custody = reseal(items[6].custody, CustodyRecord, "custody_hash", anchor=binding)
    items[6] = items[6].model_copy(
        update={
            "request_hash": typed_hash(items[5].model_dump(mode="json")),
            "custody": custody,
        }
    )
    items[7] = reseal(
        items[7],
        ReviewDecision,
        "decision_hash",
        candidate_hash=items[0].candidate_hash,
        request_hash=typed_hash(items[5].model_dump(mode="json")),
        artifact_hash=typed_hash(items[6].model_dump(mode="json")),
        reviewer_registry_hash=items[3].registry_hash,
    )
    items[8] = reseal(items[8], IndependentAuditRecord, "audit_hash", anchor=binding)
    refresh_audit(items)


def test_valid_independent_admission_is_contract_only():
    result = verify(universe())
    assert result.admission_complete and result.mechanics_valid
    assert result.real_gate_state == GateState.OPEN_EXTERNAL
    assert (result.real_route, result.global_readiness, result.trade_decision) == (
        "QVM_NOT_READY",
        "INSUFFICIENT_REAL_DATA",
        "NO_TRADE",
    )
    assert not result.live_execution_enabled and not result.signals_generated
    assert (
        result.backtesting == "NOT_AUTHORIZED"
        and not real_external_authority_verifier_unavailable()
    )


@pytest.mark.parametrize("actor", ["actor_00000001", "actor_00000002"])
def test_reviewer_revoked_after_decision_before_verifier_rejects(actor):
    items = universe()
    registry = items[3]
    identities = []
    for identity in registry.identities:
        identities.append(
            identity.model_copy(update={"revoked_at": NOW - dt.timedelta(minutes=15)})
            if identity.actor_id == actor
            else identity
        )
    items[3] = reseal(
        registry, ContractReviewerIdentityRegistry, "registry_hash", identities=tuple(identities)
    )
    assert not verify(items).admission_complete


@pytest.mark.parametrize(
    "field,value",
    [
        ("valid_until", NOW - dt.timedelta(minutes=1)),
        ("revoked_at", NOW - dt.timedelta(minutes=1)),
        ("valid_from", NOW + dt.timedelta(minutes=1)),
    ],
)
def test_reviewer_registry_time_state_rejects(field, value):
    items = universe()
    items[3] = reseal(items[3], ContractReviewerIdentityRegistry, "registry_hash", **{field: value})
    assert not verify(items).admission_complete


@pytest.mark.parametrize(
    "field,value",
    [
        ("valid_until", NOW - dt.timedelta(minutes=1)),
        ("revoked_at", NOW - dt.timedelta(minutes=1)),
        ("valid_from", NOW + dt.timedelta(minutes=1)),
    ],
)
def test_authority_registry_time_state_rejects(field, value):
    items = universe()
    items[1] = reseal(items[1], ContractAuthorityRegistry, "registry_hash", **{field: value})
    assert not verify(items).admission_complete


def test_revoked_authority_rejects_even_with_resealed_registry():
    items = universe()
    auth = list(items[1].authorities)
    auth[0] = reseal(
        auth[0], ContractAuthority, "authority_hash", revoked_at=NOW - dt.timedelta(minutes=1)
    )
    items[1] = reseal(items[1], ContractAuthorityRegistry, "registry_hash", authorities=tuple(auth))
    assert not verify(items).admission_complete


def test_expired_anchor_rejects():
    items = universe()
    anchor = reseal(
        items[2].anchors[0], TrustAnchor, "anchor_hash", valid_until=NOW - dt.timedelta(seconds=1)
    )
    items[2] = reseal(items[2], ContractTrustAnchorRegistry, "registry_hash", anchors=(anchor,))
    assert not verify(items).admission_complete


def test_free_form_authority_fields_are_not_models_anymore():
    with pytest.raises(ValidationError):
        TrustAnchor.model_validate({"anchor_id": "anchor.fake", "authority_id": "fake"})


def test_stale_authority_registry_hash_rejects():
    items = universe()
    items[1] = items[1].model_copy(update={"registry_id": "registry.forged"})
    with pytest.raises(Phase7FContractError, match="authority registry"):
        verify(items)


def test_resealed_authority_chain_mismatch_rejects():
    items = universe()
    items[1] = reseal(
        items[1], ContractAuthorityRegistry, "registry_hash", registry_id="registry.forged"
    )
    assert not verify(items).admission_complete


def test_stale_custody_hash_rejects():
    items = universe()
    items[6] = items[6].model_copy(
        update={"custody": items[6].custody.model_copy(update={"provider_id": "provider.forged"})}
    )
    with pytest.raises(Phase7FContractError, match="artifact"):
        verify(items)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "provider.forged"),
        ("dataset_id", "dataset.forged"),
        ("gate", EvidenceGate.REAL_FX),
        ("scope_id", "scope.forged"),
        ("as_of", NOW - dt.timedelta(days=2)),
    ],
)
def test_resealed_wrong_custody_binding_rejects(field, value):
    items = universe()
    custody = reseal(items[6].custody, CustodyRecord, "custody_hash", **{field: value})
    items[6] = items[6].model_copy(update={"custody": custody})
    refresh_audit(items)
    assert not verify(items).admission_complete


def test_resealed_wrong_custody_anchor_rejects():
    items = universe()
    binding = items[6].custody.anchor.model_copy(update={"anchor_id": "anchor.forged"})
    custody = reseal(items[6].custody, CustodyRecord, "custody_hash", anchor=binding)
    items[6] = items[6].model_copy(update={"custody": custody})
    refresh_audit(items)
    assert not verify(items).admission_complete


def test_source_bytes_changed_with_stale_sha_rejects():
    items = universe()
    items[6] = items[6].model_copy(update={"source_bytes_hex": b"changed".hex()})
    with pytest.raises(Phase7FContractError, match="artifact"):
        verify(items)


def test_source_and_sha_changed_but_custody_old_rejects():
    items = universe()
    source = b"changed"
    items[6] = items[6].model_copy(
        update={
            "source_bytes_hex": source.hex(),
            "source_sha256": hashlib.sha256(source).hexdigest(),
        }
    )
    refresh_audit(items)
    assert not verify(items).admission_complete


def test_missing_audit_is_incomplete_and_stops_before_audit():
    items = universe()
    items[8] = None
    result = verify(items)
    assert not result.admission_complete and len(result.stage_records) == 5


@pytest.mark.parametrize("claim", ["Maker Alice", "Checker Bob"])
def test_auditor_must_be_distinct(claim):
    items = universe()
    items[8] = reseal(items[8], IndependentAuditRecord, "audit_hash", auditor_claim=claim)
    assert not verify(items).admission_complete


def test_auditor_requires_role_and_current_validity():
    items = universe()
    identities = list(items[3].identities)
    identities[2] = identities[2].model_copy(update={"roles": (ReviewerRole.CHECKER,)})
    items[3] = reseal(
        items[3], ContractReviewerIdentityRegistry, "registry_hash", identities=tuple(identities)
    )
    assert not verify(items).admission_complete
    items = universe()
    identities = list(items[3].identities)
    identities[2] = identities[2].model_copy(update={"revoked_at": NOW - dt.timedelta(minutes=1)})
    items[3] = reseal(
        items[3], ContractReviewerIdentityRegistry, "registry_hash", identities=tuple(identities)
    )
    assert not verify(items).admission_complete


@pytest.mark.parametrize(
    "field,value",
    [
        ("verdict", "REJECT"),
        ("audited_at", NOW - dt.timedelta(hours=1)),
        ("snapshot_hash", "f" * 64),
    ],
)
def test_rejected_early_or_stale_audit_is_incomplete(field, value):
    items = universe()
    items[8] = reseal(items[8], IndependentAuditRecord, "audit_hash", **{field: value})
    assert not verify(items).admission_complete


def test_audit_bound_to_different_artifact_is_incomplete():
    items = universe()
    items[8] = reseal(items[8], IndependentAuditRecord, "audit_hash", snapshot_hash="e" * 64)
    assert not verify(items).admission_complete


def test_reject_decision_prevents_later_audit_completion():
    items = universe()
    items[7] = reseal(items[7], ReviewDecision, "decision_hash", decision="REJECT")
    refresh_audit(items)
    assert not verify(items).admission_complete


def test_fake_caller_pass_stage_cannot_be_input_to_verifier():
    items = universe()
    forged = {
        "stage_records": [{"stage": "ADMISSION_COMPLETE", "evidence_hash": "a" * 64}],
        "gate": items[5].gate,
    }
    with pytest.raises(ValidationError):
        from governance.phase7f import ContractAdmissionResult

        ContractAdmissionResult.model_validate(forged)


@pytest.mark.parametrize(
    "left,right",
    [("Alice", "Ａｌｉｃｅ"), ("Café", "Cafe\u0301"), (" Alice\u2003Smith ", "alice smith")],
)
def test_nfkc_whitespace_case_alias_collision(left, right):
    items = universe()
    identities = list(items[3].identities)
    identities[0] = identities[0].model_copy(update={"aliases": (left,)})
    identities[1] = identities[1].model_copy(update={"aliases": (right,)})
    with pytest.raises(ValidationError, match="ambiguous"):
        reseal(
            items[3],
            ContractReviewerIdentityRegistry,
            "registry_hash",
            identities=tuple(identities),
        )


def test_actor_ids_are_opaque_ascii():
    with pytest.raises(ValidationError):
        ReviewerIdentity(
            actor_id="Ａｌｉｃｅ", aliases=("Alice",), roles=(ReviewerRole.MAKER,), valid_from=PAST
        )


def test_model_copy_nested_custody_is_revalidated():
    items = universe()
    items[6] = items[6].model_copy(
        update={"custody": items[6].custody.model_copy(update={"custody_hash": "0" * 64})}
    )
    with pytest.raises(Phase7FContractError):
        verify(items)


def test_model_construct_audit_is_revalidated():
    items = universe()
    values = items[8].model_dump(mode="python")
    values["verdict"] = "REJECT"
    items[8] = IndependentAuditRecord.model_construct(**values)
    with pytest.raises(Phase7FContractError):
        verify(items)


def test_forged_primitive_dict_is_revalidated():
    items = universe()
    forged = items[0].model_dump(mode="json")
    forged["candidate_id"] = "candidate.forged"
    items[0] = forged
    with pytest.raises(Phase7FContractError):
        verify(items)


def test_same_class_instance_does_not_bypass_revalidation():
    items = universe()
    items[1] = items[1].model_copy(update={"registry_hash": "0" * 64})
    with pytest.raises(Phase7FContractError):
        verify(items)


def test_gate_lists_missing_duplicate_conflicting_or_reordered_fail():
    items = universe()
    for gates in (
        tuple(EvidenceGate)[:-1],
        tuple(EvidenceGate) + (EvidenceGate.REAL_FX,),
        tuple(reversed(tuple(EvidenceGate))),
    ):
        with pytest.raises(ValidationError):
            reseal(items[0], ProviderDatasetCandidate, "candidate_hash", required_gates=gates)


@pytest.mark.parametrize(
    "changes",
    [
        {"custody_available_at": NOW - dt.timedelta(minutes=20)},
        {"retrieved_at": NOW - dt.timedelta(minutes=20)},
        {
            "custody_available_at": NOW - dt.timedelta(hours=1),
            "retrieved_at": NOW - dt.timedelta(hours=2),
        },
        {"decided_at": NOW - dt.timedelta(minutes=1), "audited_at": NOW - dt.timedelta(minutes=5)},
        {"audited_at": NOW + dt.timedelta(seconds=1)},
        {"decided_at": NOW + dt.timedelta(seconds=1), "audited_at": NOW + dt.timedelta(seconds=1)},
        {"requested_at": NOW - dt.timedelta(minutes=10)},
    ],
    ids=[
        "decision-before-custody",
        "decision-before-retrieval",
        "retrieval-before-custody",
        "audit-before-decision",
        "audit-after-verifier",
        "decision-after-verifier",
        "request-after-retrieval",
    ],
)
def test_resealed_invalid_causal_chronology_is_incomplete(changes):
    items = universe()
    set_chronology(items, **changes)
    result = verify(items)
    assert not result.admission_complete
    assert AdmissionStage.ADMISSION_COMPLETE not in {x.stage for x in result.stage_records}


def test_exact_equal_causal_boundaries_are_explicitly_allowed():
    items = universe()
    boundary = NOW - dt.timedelta(minutes=30)
    set_chronology(
        items,
        custody_available_at=boundary,
        retrieved_at=boundary,
        decided_at=boundary,
        audited_at=boundary,
    )
    assert verify(items).admission_complete


def test_authority_registry_activated_after_decision_cannot_legitimize_it():
    items = universe()
    items[1] = reseal(
        items[1],
        ContractAuthorityRegistry,
        "registry_hash",
        valid_from=items[7].decided_at + dt.timedelta(seconds=1),
    )
    assert not verify(items).admission_complete


def test_anchor_activated_after_decision_cannot_legitimize_it_even_fully_rebound():
    items = universe()
    replace_anchor(items, activated_at=items[7].decided_at + dt.timedelta(seconds=1))
    assert not verify(items).admission_complete


def test_anchor_valid_at_decision_but_revoked_before_verifier_is_incomplete():
    items = universe()
    replace_anchor(items, revoked_at=NOW - dt.timedelta(minutes=10))
    assert not verify(items).admission_complete


def test_candidate_declared_after_decision_is_incomplete_with_resealed_snapshot():
    items = universe()
    items[0] = reseal(
        items[0],
        ProviderDatasetCandidate,
        "candidate_hash",
        declared_at=items[7].decided_at + dt.timedelta(seconds=1),
    )
    assert not verify(items).admission_complete


def test_policy_effective_after_decision_is_incomplete_with_valid_local_hash():
    items = universe()
    items[4] = reseal(
        items[4],
        ContractPolicy,
        "policy_hash",
        effective_from=items[7].decided_at + dt.timedelta(seconds=1),
    )
    assert not verify(items).admission_complete


def test_auditor_valid_at_audit_but_revoked_before_verifier_is_incomplete():
    items = universe()
    identities = list(items[3].identities)
    identities[2] = identities[2].model_copy(update={"revoked_at": NOW - dt.timedelta(minutes=1)})
    items[3] = reseal(
        items[3], ContractReviewerIdentityRegistry, "registry_hash", identities=tuple(identities)
    )
    assert not verify(items).admission_complete


def test_timestamp_model_copy_with_stale_hash_is_rejected():
    items = universe()
    items[7] = items[7].model_copy(update={"decided_at": NOW - dt.timedelta(hours=3)})
    with pytest.raises(Phase7FContractError, match="decision"):
        verify(items)


def test_model_construct_future_dated_nested_custody_is_incomplete():
    items = universe()
    values = items[6].custody.model_dump(mode="python")
    values["available_at"] = NOW + dt.timedelta(hours=1)
    values["custody_hash"] = typed_hash({k: v for k, v in values.items() if k != "custody_hash"})
    items[6] = items[6].model_copy(update={"custody": CustodyRecord.model_construct(**values)})
    with pytest.raises(Phase7FContractError, match="artifact"):
        verify(items)


def test_forged_primitive_dict_with_valid_hashes_but_bad_chronology_is_incomplete():
    items = universe()
    set_chronology(items, retrieved_at=items[7].decided_at + dt.timedelta(seconds=1))
    primitive = [None if item is None else item.model_dump(mode="json") for item in items]
    assert not verify(primitive).admission_complete


def test_old_audit_snapshot_cannot_cover_mutated_decision_time():
    items = universe()
    old_audit = items[8]
    items[7] = reseal(
        items[7],
        ReviewDecision,
        "decision_hash",
        decided_at=items[7].decided_at - dt.timedelta(minutes=1),
    )
    items[8] = old_audit
    assert not verify(items).admission_complete
