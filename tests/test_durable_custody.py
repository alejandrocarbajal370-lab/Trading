import datetime as dt
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_external_trust_verifier import graph

from governance.canonical import typed_hash
from governance.durable_custody import (
    AccessAuditEvidence,
    ArtifactKind,
    BackendProvisioningEvidence,
    CustodyPrincipalEvidence,
    CustodyReceipt,
    CustodyRole,
    DurableCustodyError,
    Lifecycle,
    LockMode,
    ProvisioningState,
    WormPolicyEvidence,
    artifact_identity,
    assess_contract_test_custody,
    build_contract_test_store,
    derive_replay_identity,
    seal_contract_test,
    verify_real_custody,
    verify_restore,
)
from governance.phase7e import EvidenceGate, GateState

D = lambda value: typed_hash({"custody-fixture": value})


def built(tmp_path):
    values = graph(); now = values["assessed_at"]
    lifecycle = seal_contract_test(
        Lifecycle, "lifecycle_hash", available_at=now-dt.timedelta(minutes=4),
        effective_at=now-dt.timedelta(minutes=3), verified_at=now-dt.timedelta(minutes=2),
        expires_at=now+dt.timedelta(days=3), revoked_at=None,
    )
    registry = values["authority_registry"]
    backend = seal_contract_test(
        BackendProvisioningEvidence, "evidence_hash", backend_id="backend.custody.contract",
        deployment_id="deployment.custody.contract", backend_reference_digest=D("backend"),
        deployment_reference_digest=D("deployment"), provisioning_material_digest=D("provision"),
        authority_registry_evidence_hash=registry.evidence_hash, lifecycle=lifecycle,
        state=ProvisioningState.CONTRACT_TEST_ONLY,
    )
    policy = seal_contract_test(
        WormPolicyEvidence, "evidence_hash", policy_id="policy.retention.contract",
        policy_version="version.001", backend_evidence_hash=backend.evidence_hash,
        authority_registry_evidence_hash=registry.evidence_hash, retention_seconds=172800,
        lock_mode=LockMode.COMPLIANCE, effective_at=now-dt.timedelta(minutes=1),
        retain_until=now-dt.timedelta(minutes=1)+dt.timedelta(days=2),
        expires_at=now+dt.timedelta(days=3), revoked_at=None,
        configuration_digest=D("policy"), state=ProvisioningState.CONTRACT_TEST_ONLY,
        immutability_proof_real=ProvisioningState.NOT_PROVISIONED,
    )
    actors = tuple(seal_contract_test(
        CustodyPrincipalEvidence, "evidence_hash",
        principal_id=f"principal.{role.value.lower().replace('_', '-')}", role=role,
        principal_reference_digest=D(role.value), authority_registry_evidence_hash=registry.evidence_hash,
        lifecycle=lifecycle, state=ProvisioningState.CONTRACT_TEST_ONLY,
    ) for role in CustodyRole)
    raw_bytes, derived_bytes = b'{"conId":272093}', b"derived-fixture"
    envelope = values["attestations"][0]
    raw = artifact_identity(
        artifact_id="artifact.raw.msft.001", kind=ArtifactKind.RAW,
        scope_id="gate.retention-worm.msft", media_type="application/json", content=raw_bytes,
        material_digest=envelope.material_digest, provenance_digest=envelope.provenance_digest,
        lineage_digest=envelope.lineage_digest,
    )
    derived = artifact_identity(
        artifact_id="artifact.derived.msft.001", kind=ArtifactKind.DERIVED,
        scope_id="gate.retention-worm.msft", media_type="application/json", content=derived_bytes,
        material_digest=D("derived-material"), provenance_digest=D("derived-provenance"),
        lineage_digest=D("derived-lineage"), raw_source_identity_hash=raw.identity_hash,
    )
    stored_at = now+dt.timedelta(minutes=1)
    common = {
        "provider": "provider.ibkr", "session_binding_hash": values["session"].binding_hash,
        "adapter_id": values["session"].adapter_id, "dataset_id": values["session"].dataset_id,
        "route_id": values["session"].route_id, "request_id": values["session"].request_id,
        "request_hash": values["session"].request_hash,
        "security_master_id": values["session"].security_master_id,
        "con_id": values["session"].con_id,
        "entitlement_evidence_hash": values["entitlement"].evidence_hash,
        "observation_digest": values["observation"].observation_digest,
        "attestation_envelope_hash": envelope.envelope_hash,
        "independent_verification_hash": values["verification"].result_hash,
        "backend_evidence_hash": backend.evidence_hash, "policy_evidence_hash": policy.evidence_hash,
        "custody_operator_evidence_hash": actors[0].evidence_hash, "stored_at": stored_at,
        "state": ProvisioningState.CONTRACT_TEST_ONLY,
        "external_custody_real": ProvisioningState.NOT_PROVISIONED,
        "worm_real": ProvisioningState.NOT_PROVISIONED,
    }
    receipts = (
        seal_contract_test(CustodyReceipt, "receipt_hash", receipt_id="receipt.raw.msft.001", artifact=raw, **common),
        seal_contract_test(CustodyReceipt, "receipt_hash", receipt_id="receipt.derived.msft.001", artifact=derived, **common),
    )
    store = build_contract_test_store(tmp_path/"custody.sqlite")
    replay = derive_replay_identity(receipts[0]); committed = stored_at+dt.timedelta(minutes=1)
    entry = store.store_and_consume(((receipts[0], raw_bytes), (receipts[1], derived_bytes)), replay, committed_at=committed)
    audit = seal_contract_test(
        AccessAuditEvidence, "event_digest", event_id="audit.store.msft.001",
        receipt_hash=receipts[0].receipt_hash, replay_identity_hash=replay.identity_hash,
        operator_evidence_hash=actors[0].evidence_hash, action="STORE_AND_CONSUME",
        occurred_at=committed,
    )
    restore = verify_restore(
        store=store, artifact=raw, replay_entry=entry, auditor=actors[1], receipt=receipts[0],
        verified_at=committed+dt.timedelta(minutes=1), restore_id="restore.raw.msft.001",
    )
    values["assessed_at"] = committed+dt.timedelta(minutes=2)
    values.update(backend=backend, policy=policy, custody_principals=actors, receipts=receipts,
                  replay_entry=entry, access_audit=audit, restore=restore)
    return values, store, (raw_bytes, derived_bytes)


def assess(values):
    return assess_contract_test_custody(**values)


def reseal(value, field, **changes):
    raw = value.model_dump(mode="python", exclude={field}); raw.update(changes)
    return seal_contract_test(type(value), field, **raw)


def test_complete_graph_is_contract_only_and_all_real_gates_stay_closed(tmp_path):
    values, _, _ = built(tmp_path); result = assess(values)
    assert result.content_hash_is_worm_proof is False
    assert {result.external_custody_real, result.worm_real, result.durable_replay_real,
            result.legal_licensing_real, result.provider_admission_real} == {ProvisioningState.NOT_PROVISIONED}
    assert result.gate_states == tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)
    assert (result.real_route, result.global_readiness, result.trade_decision) == ("QVM_NOT_READY", "INSUFFICIENT_REAL_DATA", "NO_TRADE")
    assert not result.signals_generated and not result.live_execution_enabled
    assert result.backtesting == "NOT_AUTHORIZED"
    with pytest.raises(DurableCustodyError, match="NOT_PROVISIONED"):
        verify_real_custody(chmod=True, signed_json=True, local_hmac=True)


def test_restart_duplicate_and_store_replacement_fail_closed(tmp_path):
    values, store, contents = built(tmp_path); path = tmp_path/"custody.sqlite"
    reopened = build_contract_test_store(path, expected_store_id=store.store_id)
    batch = tuple(zip(values["receipts"], contents, strict=True))
    with pytest.raises(DurableCustodyError, match="already consumed"):
        reopened.store_and_consume(batch, values["replay_entry"].replay_identity, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError, match="replacement"):
        build_contract_test_store(path, expected_store_id="store.wrong")


def test_alias_or_reseal_cannot_change_semantic_replay_key(tmp_path):
    values, _, _ = built(tmp_path)
    original = values["receipts"][0]
    alias_artifact = reseal(original.artifact, "identity_hash", artifact_id="artifact.raw.alias.999")
    alias_receipt = reseal(original, "receipt_hash", artifact=alias_artifact)
    assert alias_artifact.identity_hash != original.artifact.identity_hash
    assert derive_replay_identity(alias_receipt).identity_hash == derive_replay_identity(original).identity_hash


def test_fresh_process_reopens_and_validates_persisted_journal(tmp_path):
    _, store, _ = built(tmp_path)
    code = (
        "from governance.durable_custody import build_contract_test_store;"
        f"s=build_contract_test_store({str(tmp_path / 'custody.sqlite')!r},"
        f"expected_store_id={store.store_id!r});"
        "assert s.store_id"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        check=True,
        capture_output=True,
        text=True,
    )


def test_concurrent_consumers_have_one_winner(tmp_path):
    values, _, contents = built(tmp_path); path = tmp_path/"concurrent.sqlite"
    seed = build_contract_test_store(path); batch = tuple(zip(values["receipts"], contents, strict=True))
    def attempt(_):
        try:
            build_contract_test_store(path, expected_store_id=seed.store_id).store_and_consume(
                batch, values["replay_entry"].replay_identity, committed_at=values["assessed_at"])
            return True
        except DurableCustodyError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1


def test_partial_batch_failure_rolls_back_and_restore_fails(tmp_path):
    values, _, contents = built(tmp_path); store = build_contract_test_store(tmp_path/"rollback.sqlite")
    with pytest.raises(DurableCustodyError):
        store.store_and_consume(((values["receipts"][0], contents[0]), (values["receipts"][1], b"tamper")),
                               values["replay_entry"].replay_identity, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError, match="missing"):
        store.restore(values["receipts"][0].artifact)


@pytest.mark.parametrize("damage", ("truncate", "schema", "journal"))
def test_corruption_schema_and_journal_tamper_fail_closed(tmp_path, damage):
    _, store, _ = built(tmp_path); path = tmp_path/"custody.sqlite"
    if damage == "truncate": path.write_bytes(path.read_bytes()[:100])
    else:
        connection = sqlite3.connect(path)
        if damage == "schema": connection.execute("PRAGMA user_version=99")
        else: connection.execute("UPDATE journal SET entry_hash=?", ("0"*64,))
        connection.commit(); connection.close()
    with pytest.raises(DurableCustodyError):
        build_contract_test_store(path, expected_store_id=store.store_id)


@pytest.mark.parametrize("target", ("backend", "policy", "roles", "audit", "restore", "artifact"))
def test_swaps_missing_evidence_and_raw_derived_confusion_fail_closed(tmp_path, target):
    values, _, _ = built(tmp_path)
    if target == "backend": values["backend"] = reseal(values["backend"], "evidence_hash", deployment_reference_digest=D("swap"))
    elif target == "policy": values["policy"] = reseal(values["policy"], "evidence_hash", configuration_digest=D("swap"))
    elif target == "roles": values["custody_principals"] = values["custody_principals"][::-1]
    elif target == "audit": values["access_audit"] = None
    elif target == "restore": values["restore"] = None
    else:
        changed = reseal(values["receipts"][1].artifact, "identity_hash", raw_source_identity_hash="0"*64)
        values["receipts"] = (values["receipts"][0], reseal(values["receipts"][1], "receipt_hash", artifact=changed))
    with pytest.raises(DurableCustodyError): assess(values)


@pytest.mark.parametrize("target", ("backend", "policy", "operator", "auditor"))
@pytest.mark.parametrize("boundary", ("expiry", "revocation"))
def test_lifecycle_equality_at_assessment_fails_closed(tmp_path, target, boundary):
    values, _, _ = built(tmp_path); now = values["assessed_at"]
    if target == "policy":
        changes = {"revoked_at": now}
        if boundary == "expiry":
            changes = {
                "retain_until": now,
                "retention_seconds": int((now - values["policy"].effective_at).total_seconds()),
            }
        values["policy"] = reseal(values["policy"], "evidence_hash", **changes)
    else:
        item = values["backend"] if target == "backend" else values["custody_principals"][0 if target == "operator" else 1]
        life = reseal(item.lifecycle, "lifecycle_hash", **({"expires_at": now} if boundary == "expiry" else {"revoked_at": now}))
        changed = reseal(item, "evidence_hash", lifecycle=life)
        if target == "backend": values["backend"] = changed
        else:
            actors = list(values["custody_principals"]); actors[0 if target == "operator" else 1] = changed
            values["custody_principals"] = tuple(actors)
    with pytest.raises(DurableCustodyError): assess(values)


def test_model_copy_construct_extras_subclass_unicode_and_duck_fail_closed(tmp_path):
    values, _, _ = built(tmp_path); receipt = values["receipts"][0]
    attacks = (receipt.model_copy(update={"provider": "provider.other"}),
               CustodyReceipt.model_construct(**{**receipt.model_dump(), "worm_real": "REAL"}),
               {**receipt.model_dump(), "private_key": "SECRET"},
               type("Sub", (CustodyReceipt,), {}).model_construct(**receipt.model_dump()))
    for attack in attacks:
        changed = dict(values); changed["receipts"] = (attack, values["receipts"][1])
        with pytest.raises(DurableCustodyError): assess(changed)
    with pytest.raises(DurableCustodyError):
        reseal(values["backend"], "evidence_hash", backend_id="backend.custоdy")

    class Hostile:
        def __str__(self): raise RuntimeError("SECRET")
        __repr__ = __str__
        @property
        def __dict__(self): raise RuntimeError("SECRET")
    values["restore"] = Hostile()
    with pytest.raises(DurableCustodyError) as caught: assess(values)
    assert "SECRET" not in str(caught.value)
