import datetime
import hashlib

import pytest
from pydantic import ValidationError

from governance.canonical import typed_hash
from governance.phase7e import EvidenceGate, GateState
from governance.phase7f import (
    ArtifactClass,
    ArtifactRequest,
    ContractReviewerIdentityRegistry,
    ContractTrustAnchorRegistry,
    Phase7FContractError,
    ProviderDatasetCandidate,
    ResolvedArtifact,
    ReviewDecision,
    ReviewerIdentity,
    ReviewerRole,
    TrustAnchor,
    verify_contract_admission,
)

NOW = datetime.datetime(2026, 8, 29, tzinfo=datetime.UTC)
PAST = NOW - datetime.timedelta(days=30)


def _seal(cls, hash_field, **values):
    raw = cls.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(raw.model_dump(mode="json", exclude={hash_field}))
    return cls(**values)


def _objects():
    anchor = _seal(
        TrustAnchor,
        "anchor_hash",
        anchor_id="contract-anchor",
        source_system_id="contract-custody",
        authority_id="contract-authority",
        artifact_classes=(ArtifactClass.EVIDENCE,),
        activated_at=PAST,
        authority_provenance_hash="a" * 64,
    )
    anchors = _seal(ContractTrustAnchorRegistry, "registry_hash", anchors=(anchor,))
    identities = (
        ReviewerIdentity(
            actor_id="actor-maker",
            aliases=("Maker One",),
            roles=(ReviewerRole.MAKER,),
            valid_from=PAST,
            authority_provenance_hash="b" * 64,
        ),
        ReviewerIdentity(
            actor_id="actor-checker",
            aliases=("Checker Two",),
            roles=(ReviewerRole.CHECKER,),
            valid_from=PAST,
            authority_provenance_hash="c" * 64,
        ),
    )
    reviewers = _seal(ContractReviewerIdentityRegistry, "registry_hash", identities=identities)
    candidate = _seal(
        ProviderDatasetCandidate,
        "candidate_hash",
        candidate_id="candidate-1",
        provider_id="contract-provider",
        dataset_id="contract-dataset",
        dataset_version="v1",
        scope_id="declared-scope",
        policy_id="policy-1",
        policy_hash="d" * 64,
        required_anchor_ids=(anchor.anchor_id,),
        required_gates=tuple(EvidenceGate),
        declared_at=PAST,
    )
    request = ArtifactRequest(
        request_id="request-1",
        candidate_hash=candidate.candidate_hash,
        anchor_id=anchor.anchor_id,
        source_system_id=anchor.source_system_id,
        canonical_source_id="custody://immutable/evidence/1",
        artifact_class=ArtifactClass.EVIDENCE,
        artifact_version="version-1",
        gate=EvidenceGate.LICENSING_LEGAL,
        provider_id=candidate.provider_id,
        dataset_id=candidate.dataset_id,
        dataset_version=candidate.dataset_version,
        scope_id=candidate.scope_id,
        policy_hash=candidate.policy_hash,
        as_of=NOW - datetime.timedelta(days=1),
    )
    source = b"synthetic contract evidence"
    artifact = ResolvedArtifact(
        request_hash=typed_hash(request.model_dump(mode="json")),
        anchor_hash=anchor.anchor_hash,
        canonical_source_id=request.canonical_source_id,
        artifact_version=request.artifact_version,
        retrieved_at=NOW - datetime.timedelta(hours=1),
        custody_record_id="contract-record",
        custody_hash="e" * 64,
        source_bytes_hex=source.hex(),
        source_sha256=hashlib.sha256(source).hexdigest(),
    )
    decision = _seal(
        ReviewDecision,
        "decision_hash",
        candidate_hash=candidate.candidate_hash,
        request_hash=typed_hash(request.model_dump(mode="json")),
        artifact_hash=typed_hash(artifact.model_dump(mode="json")),
        gate=request.gate,
        provider_id=candidate.provider_id,
        dataset_id=candidate.dataset_id,
        dataset_version=candidate.dataset_version,
        scope_id=candidate.scope_id,
        policy_hash=candidate.policy_hash,
        maker_claim="Maker One",
        checker_claim="Checker Two",
        decided_at=NOW - datetime.timedelta(minutes=30),
        decision="ACCEPT",
    )
    return candidate, anchors, reviewers, request, artifact, decision


def _verify(objects):
    return verify_contract_admission(*objects, verifier_time=NOW)


def test_complete_contract_path_cannot_close_real_gate():
    result = _verify(_objects())
    assert result.mechanics_valid and result.real_gate_state == GateState.OPEN_EXTERNAL
    assert result.real_route == "QVM_NOT_READY"
    assert result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert result.trade_decision == "NO_TRADE"
    assert not result.live_execution_enabled and not result.signals_generated
    assert result.backtesting == "NOT_AUTHORIZED"


@pytest.mark.parametrize(
    "index,field,value",
    [(3, "scope_id", "partial"), (3, "dataset_version", "other"), (5, "decision", "REJECT")],
)
def test_mismatched_bindings_fail_closed(index, field, value):
    objects = list(_objects())
    changed = objects[index].model_dump(
        mode="python", exclude={"decision_hash"} if index == 5 else set()
    )
    changed[field] = value
    objects[index] = (
        _seal(
            ReviewDecision, "decision_hash", **{k: v for k, v in changed.items() if k != "version"}
        )
        if index == 5
        else objects[index].model_copy(update={field: value})
    )
    assert not _verify(objects).mechanics_valid


def test_same_canonical_actor_cannot_be_maker_and_checker():
    objects = list(_objects())
    values = objects[5].model_dump(mode="python", exclude={"version", "decision_hash"})
    values["checker_claim"] = "actor-maker"
    objects[5] = _seal(ReviewDecision, "decision_hash", **values)
    assert not _verify(objects).mechanics_valid


def test_duplicate_alias_across_registry_is_rejected():
    identities = list(_objects()[2].identities)
    identities[1] = identities[1].model_copy(update={"aliases": (" maker one ",)})
    with pytest.raises(ValidationError, match="ambiguous"):
        _seal(ContractReviewerIdentityRegistry, "registry_hash", identities=tuple(identities))


def test_revoked_anchor_fails_at_verifier_time():
    objects = list(_objects())
    values = objects[1].anchors[0].model_dump(mode="python", exclude={"version", "anchor_hash"})
    values["revoked_at"] = NOW - datetime.timedelta(seconds=1)
    revoked = _seal(TrustAnchor, "anchor_hash", **values)
    objects[1] = _seal(ContractTrustAnchorRegistry, "registry_hash", anchors=(revoked,))
    with pytest.raises(Phase7FContractError, match="inactive"):
        _verify(objects)


def test_revoked_reviewer_fails_closed():
    objects = list(_objects())
    identities = list(objects[2].identities)
    identities[1] = identities[1].model_copy(
        update={"revoked_at": NOW - datetime.timedelta(hours=1)}
    )
    objects[2] = _seal(
        ContractReviewerIdentityRegistry, "registry_hash", identities=tuple(identities)
    )
    assert not _verify(objects).mechanics_valid


def test_mutated_source_bytes_and_stale_digest_are_rejected():
    objects = list(_objects())
    objects[4] = objects[4].model_copy(update={"source_bytes_hex": b"forged".hex()})
    with pytest.raises(Phase7FContractError, match="invalid resolved artifact"):
        _verify(objects)


def test_stale_canonical_hashes_are_revalidated_at_consumer_boundary():
    objects = list(_objects())
    objects[0] = objects[0].model_copy(update={"scope_id": "forged"})
    with pytest.raises(Phase7FContractError, match="invalid candidate"):
        _verify(objects)


def test_caller_authored_result_cannot_become_real():
    result = _verify(_objects())
    forged = result.model_copy(update={"real_gate_state": GateState.VERIFIED})
    with pytest.raises(ValidationError):
        type(result).model_validate(forged.model_dump(mode="json"))


def test_naive_verifier_time_is_rejected():
    with pytest.raises(Phase7FContractError, match="timezone-aware"):
        verify_contract_admission(*_objects(), verifier_time=NOW.replace(tzinfo=None))
