import datetime as dt
import json
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread

import pytest
from test_external_trust_verifier import graph

from governance.canonical import typed_hash
from governance.durable_custody import (
    SCHEMA_VERSION,
    AccessAuditEvidence,
    ArtifactKind,
    BackendProvisioningEvidence,
    CustodyPrincipalEvidence,
    CustodyReceipt,
    CustodyRole,
    DurableCustodyError,
    DurableReplayStateEvidence,
    Lifecycle,
    LockMode,
    ProvisioningState,
    ReplayJournalEvidence,
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
    values["store"] = store
    return values, store, (raw_bytes, derived_bytes)


def assess(values):
    return assess_contract_test_custody(**values)


def reseal(value, field, **changes):
    raw = value.model_dump(mode="python", exclude={field}); raw.update(changes)
    return seal_contract_test(type(value), field, **raw)


def rebind_step3(values):
    receipts = tuple(
        reseal(
            item,
            "receipt_hash",
            backend_evidence_hash=values["backend"].evidence_hash,
            policy_evidence_hash=values["policy"].evidence_hash,
            custody_operator_evidence_hash=values["custody_principals"][0].evidence_hash,
        )
        for item in values["receipts"]
    )
    replay = derive_replay_identity(receipts[0])
    entry = reseal(
        values["replay_entry"],
        "entry_hash",
        replay_identity=replay,
        receipt_hashes=tuple(item.receipt_hash for item in receipts),
    )
    audit = reseal(
        values["access_audit"],
        "event_digest",
        receipt_hash=receipts[0].receipt_hash,
        replay_identity_hash=replay.identity_hash,
        operator_evidence_hash=values["custody_principals"][0].evidence_hash,
    )
    restore = reseal(
        values["restore"],
        "evidence_hash",
        receipt_hash=receipts[0].receipt_hash,
        replay_entry_hash=entry.entry_hash,
    )
    values.update(receipts=receipts, replay_entry=entry, access_audit=audit, restore=restore)


def advance(store, values, *, committed_at):
    content = b'{"conId":272093,"next":true}'
    old = values["receipts"][0]
    artifact = artifact_identity(
        artifact_id="artifact.raw.msft.002", kind=ArtifactKind.RAW,
        scope_id=old.artifact.scope_id, media_type=old.artifact.media_type, content=content,
        material_digest=D("next-material"), provenance_digest=D("next-provenance"),
        lineage_digest=D("next-lineage"),
    )
    receipt = reseal(
        old, "receipt_hash", receipt_id="receipt.raw.msft.002", artifact=artifact,
        stored_at=committed_at,
    )
    entry = store.store_and_consume(
        ((receipt, content),), derive_replay_identity(receipt), committed_at=committed_at
    )
    return receipt, entry, content


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
    reopened = build_contract_test_store(
        path, expected_store_id=store.store_id, expected_checkpoint=store.checkpoint
    )
    batch = tuple(zip(values["receipts"], contents, strict=True))
    with pytest.raises(DurableCustodyError, match="already consumed"):
        reopened.store_and_consume(batch, values["replay_entry"].replay_identity, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError, match="replacement"):
        build_contract_test_store(
            path, expected_store_id="store.wrong", expected_checkpoint=store.checkpoint
        )


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
        f"expected_store_id={store.store_id!r},"
        f"expected_checkpoint={store.checkpoint.model_dump_json()!r});"
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


def test_restore_rejects_stale_and_fabricated_unpersisted_journals(tmp_path):
    values, store, _ = built(tmp_path)
    old_entry = values["replay_entry"]
    advance(store, values, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError, match="current durable state"):
        verify_restore(
            store=store, artifact=values["receipts"][0].artifact,
            replay_entry=old_entry, auditor=values["custody_principals"][1],
            receipt=values["receipts"][0], verified_at=values["assessed_at"],
            restore_id="restore.stale.msft.001",
        )
    fabricated = seal_contract_test(
        ReplayJournalEvidence, "entry_hash", store_id="store.fabricated",
        schema_version=SCHEMA_VERSION, sequence=999,
        replay_identity=old_entry.replay_identity,
        receipt_hashes=(values["receipts"][0].receipt_hash,),
        previous_entry_hash="f" * 64, committed_at=old_entry.committed_at,
    )
    with pytest.raises(DurableCustodyError, match="current durable state"):
        verify_restore(
            store=store, artifact=values["receipts"][0].artifact,
            replay_entry=fabricated, auditor=values["custody_principals"][1],
            receipt=values["receipts"][0], verified_at=values["assessed_at"],
            restore_id="restore.fabricated.msft.001",
        )


def test_assessment_rejects_membership_after_store_advances(tmp_path):
    values, store, _ = built(tmp_path)
    advance(store, values, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError):
        assess(values)


@pytest.mark.parametrize(
    "pause_phase", ("snapshot_fixed", "snapshot_validated", "before_current_head_check")
)
def test_assessment_rejects_advance_during_current_state_revalidation(
    tmp_path, monkeypatch, pause_phase
):
    values, store, _ = built(tmp_path)
    writer = build_contract_test_store(
        tmp_path / "custody.sqlite",
        expected_store_id=store.store_id,
        expected_checkpoint=store.checkpoint,
    )
    paused = Event()
    advanced = Event()

    def hook(phase):
        if phase == pause_phase:
            paused.set()
            assert advanced.wait(5), "writer did not commit while assessment was paused"

    monkeypatch.setattr(store, "_validation_hook", hook)

    def write():
        assert paused.wait(5), "assessment did not reach deterministic pause"
        advance(writer, values, committed_at=values["assessed_at"])
        advanced.set()

    thread = Thread(target=write)
    thread.start()
    with pytest.raises(DurableCustodyError, match="failed closed"):
        assess(values)
    thread.join(5)
    assert not thread.is_alive()
    assert writer.checkpoint.sequence == 2


def test_writer_before_snapshot_requires_new_current_membership(tmp_path):
    values, store, _ = built(tmp_path)
    receipt, entry, _ = advance(store, values, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError):
        assess(values)
    current = store.current_state_evidence(
        artifact=receipt.artifact,
        replay_entry=entry,
        validated_at=values["assessed_at"],
    )
    assert current.checkpoint_sequence == 2


def test_writer_cannot_commit_between_final_generation_check_and_return(
    tmp_path, monkeypatch
):
    values, store, _ = built(tmp_path)
    writer = build_contract_test_store(
        tmp_path / "custody.sqlite",
        expected_store_id=store.store_id,
        expected_checkpoint=store.checkpoint,
    )
    writer_started = Event()
    writer_finished = Event()
    thread = None

    def write():
        writer_started.set()
        advance(writer, values, committed_at=values["assessed_at"])
        writer_finished.set()

    def hook(phase):
        nonlocal thread
        if phase == "current_head_validated":
            thread = Thread(target=write)
            thread.start()
            assert writer_started.wait(5)
            assert not writer_finished.wait(0.1)

    monkeypatch.setattr(store, "_validation_hook", hook)
    assert assess(values).state is ProvisioningState.CONTRACT_TEST_ONLY
    assert thread is not None
    thread.join(5)
    assert writer_finished.is_set()


@pytest.mark.parametrize(
    "field",
    ("checkpoint_sequence", "journal_head_hash", "checkpoint_hash", "journal_entry_sequence"),
)
def test_resealed_or_constructed_membership_cannot_fabricate_persistence(tmp_path, field):
    values, _, _ = built(tmp_path)
    state = values["restore"].durable_state
    replacement = state.checkpoint_sequence + 1 if "sequence" in field else "f" * 64
    try:
        attack = reseal(state, "evidence_hash", **{field: replacement})
        restore = reseal(values["restore"], "evidence_hash", durable_state=attack)
        changed = dict(values); changed["restore"] = restore
        with pytest.raises(DurableCustodyError):
            assess(changed)
    except DurableCustodyError:
        pass
    constructed = DurableReplayStateEvidence.model_construct(**state.model_dump())
    object.__setattr__(constructed, "checkpoint_hash", "f" * 64)
    with pytest.raises(DurableCustodyError):
        reseal(values["restore"], "evidence_hash", durable_state=constructed)


def test_cross_store_membership_and_current_restart_behavior(tmp_path):
    values, store, _ = built(tmp_path)
    other = build_contract_test_store(tmp_path / "other.sqlite")
    changed = dict(values); changed["store"] = other
    with pytest.raises(DurableCustodyError):
        assess(changed)
    reopened = build_contract_test_store(
        tmp_path / "custody.sqlite", expected_store_id=store.store_id,
        expected_checkpoint=store.checkpoint,
    )
    values["store"] = reopened
    assert assess(values).replay_restore_contract_validated is True


def test_concurrent_consumers_have_one_winner(tmp_path):
    values, _, contents = built(tmp_path); path = tmp_path/"concurrent.sqlite"
    seed = build_contract_test_store(path); batch = tuple(zip(values["receipts"], contents, strict=True))
    def attempt(_):
        try:
            contender = build_contract_test_store(
                path, expected_store_id=seed.store_id, expected_checkpoint=seed.checkpoint
            )
            contender.store_and_consume(
                batch, values["replay_entry"].replay_identity, committed_at=values["assessed_at"])
            return contender.checkpoint
        except DurableCustodyError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(attempt, range(8)))
    winners = tuple(item for item in results if item is not False)
    assert len(winners) == 1
    assert build_contract_test_store(path, expected_checkpoint=winners[0]).checkpoint == winners[0]


def test_partial_batch_failure_rolls_back_and_restore_fails(tmp_path):
    values, _, contents = built(tmp_path); store = build_contract_test_store(tmp_path/"rollback.sqlite")
    checkpoint = store.checkpoint
    with pytest.raises(DurableCustodyError):
        store.store_and_consume(((values["receipts"][0], contents[0]), (values["receipts"][1], b"tamper")),
                               values["replay_entry"].replay_identity, committed_at=values["assessed_at"])
    with pytest.raises(DurableCustodyError, match="missing"):
        store.restore(values["receipts"][0].artifact)
    assert store.checkpoint == checkpoint
    assert build_contract_test_store(
        tmp_path / "rollback.sqlite", expected_checkpoint=checkpoint
    ).checkpoint == checkpoint


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
        build_contract_test_store(
            path, expected_store_id=store.store_id, expected_checkpoint=store.checkpoint
        )


def test_snapshot_rollback_and_checkpoint_mismatch_fail_closed(tmp_path):
    values, _, contents = built(tmp_path)
    path = tmp_path / "snapshot-target.sqlite"
    old_database = tmp_path / "old.sqlite"
    store = build_contract_test_store(path)
    old_checkpoint = store.checkpoint
    shutil.copy2(path, old_database)
    store.store_and_consume(
        tuple(zip(values["receipts"], contents, strict=True)),
        values["replay_entry"].replay_identity,
        committed_at=values["assessed_at"],
    )
    current_checkpoint = store.checkpoint
    with pytest.raises(DurableCustodyError, match="checkpoint"):
        build_contract_test_store(path, expected_checkpoint=old_checkpoint)
    shutil.copy2(old_database, path)
    with pytest.raises(DurableCustodyError, match="checkpoint"):
        build_contract_test_store(
            path, expected_store_id=store.store_id, expected_checkpoint=current_checkpoint
        )
    with pytest.raises(DurableCustodyError, match="expected checkpoint"):
        build_contract_test_store(path, expected_store_id=store.store_id)
    # A matching rolled-back pair is locally indistinguishable; strong semantics require
    # the independently retained current reference and never claim REAL anchoring.
    locally_reopened = build_contract_test_store(
        path, expected_store_id=store.store_id, expected_checkpoint=old_checkpoint
    )
    assert locally_reopened.checkpoint.external_authoritative_anchor_real is ProvisioningState.NOT_PROVISIONED
    with pytest.raises(DurableCustodyError, match="checkpoint"):
        build_contract_test_store(
            path, expected_store_id=store.store_id, expected_checkpoint=current_checkpoint
        )


def test_current_database_rejects_rolled_back_tampered_or_missing_checkpoint(tmp_path):
    _, store, _ = built(tmp_path); path = tmp_path / "custody.sqlite"
    empty = build_contract_test_store(tmp_path / "empty.sqlite").checkpoint
    with pytest.raises(DurableCustodyError, match="checkpoint"):
        build_contract_test_store(path, expected_checkpoint=empty)
    tampered = json.loads(store.checkpoint.model_dump_json())
    tampered["journal_head_hash"] = "0" * 64
    with pytest.raises(DurableCustodyError):
        build_contract_test_store(path, expected_checkpoint=tampered)
    with pytest.raises(DurableCustodyError, match="expected checkpoint"):
        build_contract_test_store(path)


@pytest.mark.parametrize("kind", (ArtifactKind.RAW, ArtifactKind.DERIVED))
def test_missing_journal_object_rejects_store_open(tmp_path, kind):
    values, store, _ = built(tmp_path); path = tmp_path / "custody.sqlite"
    target = next(item for item in values["receipts"] if item.artifact.kind is kind)
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM objects WHERE identity_hash=?", (target.artifact.identity_hash,))
    connection.commit(); connection.close()
    with pytest.raises(DurableCustodyError, match="missing"):
        build_contract_test_store(path, expected_checkpoint=store.checkpoint)


@pytest.mark.parametrize("column", ("receipt_hash", "receipt_json", "content"))
def test_object_receipt_hash_identity_size_and_content_tamper_rejects_open(tmp_path, column):
    _, store, _ = built(tmp_path); path = tmp_path / "custody.sqlite"
    connection = sqlite3.connect(path)
    value = "0" * 64 if column == "receipt_hash" else ("{}" if column == "receipt_json" else b"tamper")
    connection.execute(f"UPDATE objects SET {column}=? WHERE rowid=1", (value,))
    connection.commit(); connection.close()
    with pytest.raises(DurableCustodyError):
        build_contract_test_store(path, expected_checkpoint=store.checkpoint)


@pytest.mark.parametrize("field", ("artifact_id", "content_hash", "size_bytes"))
def test_validly_resealed_artifact_version_hash_or_size_mismatch_rejects_open(tmp_path, field):
    values, store, _ = built(tmp_path); path = tmp_path / "custody.sqlite"
    receipt = values["receipts"][0]
    replacement = {
        "artifact_id": "artifact.raw.msft.999",
        "content_hash": "0" * 64,
        "size_bytes": receipt.artifact.size_bytes + 1,
    }[field]
    artifact = reseal(receipt.artifact, "identity_hash", **{field: replacement})
    changed = reseal(receipt, "receipt_hash", artifact=artifact)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE objects SET receipt_hash=?,receipt_json=? WHERE identity_hash=?",
        (changed.receipt_hash, changed.model_dump_json(), receipt.artifact.identity_hash),
    )
    connection.commit(); connection.close()
    with pytest.raises(DurableCustodyError):
        build_contract_test_store(path, expected_checkpoint=store.checkpoint)


@pytest.mark.parametrize("damage", ("swap", "ambiguous"))
def test_swapped_or_ambiguous_object_mapping_rejects_open(tmp_path, damage):
    _, store, _ = built(tmp_path); path = tmp_path / "custody.sqlite"
    connection = sqlite3.connect(path)
    rows = connection.execute(
        "SELECT identity_hash,receipt_hash,receipt_json,content FROM objects ORDER BY identity_hash"
    ).fetchall()
    if damage == "swap":
        connection.execute(
            "UPDATE objects SET receipt_json=? WHERE identity_hash=?", (rows[1][2], rows[0][0])
        )
    else:
        connection.execute("ALTER TABLE objects RENAME TO original_objects")
        connection.execute(
            "CREATE TABLE objects(identity_hash TEXT,receipt_hash TEXT,receipt_json TEXT,content BLOB)"
        )
        connection.executemany(
            "INSERT INTO objects VALUES(?,?,?,?)", (rows[0], rows[0], rows[1])
        )
    connection.commit(); connection.close()
    with pytest.raises(DurableCustodyError):
        build_contract_test_store(path, expected_checkpoint=store.checkpoint)


def test_stored_after_commit_rejected_but_equality_accepted(tmp_path):
    values, _, contents = built(tmp_path)
    receipt = values["receipts"][0]
    store = build_contract_test_store(tmp_path / "chronology.sqlite")
    with pytest.raises(DurableCustodyError, match="chronology"):
        store.store_and_consume(
            ((receipt, contents[0]),), derive_replay_identity(receipt),
            committed_at=receipt.stored_at - dt.timedelta(microseconds=1),
        )
    store.store_and_consume(
        ((receipt, contents[0]),), derive_replay_identity(receipt), committed_at=receipt.stored_at
    )


def test_assessment_rejects_stored_after_commit(tmp_path):
    values, _, _ = built(tmp_path)
    future = values["replay_entry"].committed_at + dt.timedelta(microseconds=1)
    values["receipts"] = tuple(
        reseal(item, "receipt_hash", stored_at=future) for item in values["receipts"]
    )
    rebind_step3(values)
    with pytest.raises(DurableCustodyError):
        assess(values)


@pytest.mark.parametrize("target", ("backend", "operator", "policy"))
@pytest.mark.parametrize("boundary", ("not-effective", "expiry", "revocation"))
def test_storage_time_lifecycle_boundaries_fail_closed(tmp_path, target, boundary):
    values, _, _ = built(tmp_path); stored_at = values["receipts"][0].stored_at
    if target == "policy":
        changes = {"effective_at": stored_at + dt.timedelta(microseconds=1)}
        if boundary == "expiry":
            changes = {
                "retain_until": stored_at,
                "expires_at": stored_at,
                "retention_seconds": int(
                    (stored_at - values["policy"].effective_at).total_seconds()
                ),
            }
        elif boundary == "revocation":
            changes = {"revoked_at": stored_at}
        if "effective_at" in changes:
            changes["retain_until"] = changes["effective_at"] + dt.timedelta(
                seconds=values["policy"].retention_seconds
            )
        values["policy"] = reseal(values["policy"], "evidence_hash", **changes)
    else:
        index = 0
        item = values["backend"] if target == "backend" else values["custody_principals"][index]
        if boundary == "not-effective":
            life = reseal(
                item.lifecycle,
                "lifecycle_hash",
                effective_at=stored_at + dt.timedelta(microseconds=1),
                verified_at=stored_at + dt.timedelta(microseconds=2),
            )
        else:
            life = reseal(
                item.lifecycle,
                "lifecycle_hash",
                **({"expires_at": stored_at} if boundary == "expiry" else {"revoked_at": stored_at}),
            )
        changed = reseal(item, "evidence_hash", lifecycle=life)
        if target == "backend":
            values["backend"] = changed
            values["policy"] = reseal(
                values["policy"], "evidence_hash", backend_evidence_hash=changed.evidence_hash
            )
        else:
            actors = list(values["custody_principals"]); actors[index] = changed
            values["custody_principals"] = tuple(actors)
    rebind_step3(values)
    with pytest.raises(DurableCustodyError):
        assess(values)


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
