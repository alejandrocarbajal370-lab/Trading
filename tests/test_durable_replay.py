import concurrent.futures
import datetime as dt
import multiprocessing
import sqlite3

import pytest
from pydantic import ValidationError

from governance.durable_replay import (
    ContractTestPersistentReplay,
    CustodyProofState,
    PersistenceReceipt,
    ReplayDisposition,
    build_contract_test_persistent_replay,
    derive_replay_identity,
)
from governance.external_provider_foundation import (
    FoundationError,
    ProviderRegistry,
    ProvisioningState,
    _seal,
    observe_material,
)
from governance.phase7e import EvidenceGate

NOW = dt.datetime(2026, 9, 2, 18, tzinfo=dt.UTC)


def identity(gate=EvidenceGate.REAL_FX, material=b"material", provenance=b"provenance"):
    observation = observe_material(ProviderRegistry.resolve(gate), material, provenance, NOW)
    return derive_replay_identity(observation)


def _consume_in_fresh_process(database, item, output):
    try:
        build_contract_test_persistent_replay(database).consume_if_new((item,), committed_at=NOW)
        output.put("consumed")
    except FoundationError as exc:
        output.put(str(exc))


def test_identity_binds_route_material_and_provenance():
    baseline = identity()
    assert baseline != identity(EvidenceGate.LICENSING_LEGAL)
    assert baseline != identity(material=b"other")
    assert baseline != identity(provenance=b"other")


def test_consumption_survives_adapter_restart(tmp_path):
    database = tmp_path / "replay.sqlite3"
    first = build_contract_test_persistent_replay(database)
    receipts = first.consume_if_new((identity(),), committed_at=NOW)
    restarted = build_contract_test_persistent_replay(database)
    assert restarted.receipt_for(identity()) == receipts[0]
    with pytest.raises(FoundationError, match="already consumed"):
        restarted.consume_if_new((identity(),), committed_at=NOW)


def test_consumption_is_visible_to_a_fresh_process(tmp_path):
    database = tmp_path / "replay.sqlite3"
    item = identity()
    build_contract_test_persistent_replay(database).consume_if_new((item,), committed_at=NOW)
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=_consume_in_fresh_process, args=(database, item, output))
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0
    assert output.get(timeout=1) == "replay identity already consumed"


def test_atomic_batch_rolls_back_when_any_identity_is_duplicate(tmp_path):
    replay = build_contract_test_persistent_replay(tmp_path / "replay.sqlite3")
    existing = identity()
    new = identity(material=b"new")
    replay.consume_if_new((existing,), committed_at=NOW)
    with pytest.raises(FoundationError, match="already consumed"):
        replay.consume_if_new((existing, new), committed_at=NOW)
    assert replay.receipt_for(new) is None


def test_concurrent_consumers_have_exactly_one_winner(tmp_path):
    database = tmp_path / "replay.sqlite3"
    item = identity()
    assert build_contract_test_persistent_replay(database).receipt_for(item) is None

    def consume():
        adapter = build_contract_test_persistent_replay(database)
        try:
            return adapter.consume_if_new((item,), committed_at=NOW)[0]
        except FoundationError as exc:
            return str(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: consume(), range(16)))
    assert sum(isinstance(value, PersistenceReceipt) for value in outcomes) == 1
    assert sum(value == "replay identity already consumed" for value in outcomes) == 15


def test_receipt_is_local_acknowledgement_not_external_custody_or_worm(tmp_path):
    replay = build_contract_test_persistent_replay(tmp_path / "replay.sqlite3")
    receipt = replay.consume_if_new((identity(),), committed_at=NOW)[0]
    assert receipt.disposition is ReplayDisposition.CONSUMED_NEW
    assert receipt.adapter_mode is ProvisioningState.CONTRACT_TEST_ONLY
    assert receipt.custody_proof is CustodyProofState.LOCAL_PERSISTENCE_ACKNOWLEDGED
    assert receipt.external_custody == "NOT_PROVISIONED"
    assert receipt.worm_retention == "NOT_PROVISIONED"
    assert receipt.legal_retention_approval == "NOT_PROVISIONED"
    assert receipt.trust_root == "NOT_PROVISIONED"


def test_resealed_receipt_cannot_claim_external_custody(tmp_path):
    receipt = build_contract_test_persistent_replay(tmp_path / "replay.sqlite3").consume_if_new(
        (identity(),), committed_at=NOW
    )[0]
    raw = receipt.model_dump(mode="python")
    raw["external_custody"] = ProvisioningState.CONTRACT_TEST_ONLY
    raw.pop("receipt_hash")
    with pytest.raises(ValidationError):
        _seal(PersistenceReceipt, "receipt_hash", **raw)


def test_mutated_stored_receipt_fails_closed(tmp_path):
    database = tmp_path / "replay.sqlite3"
    replay = build_contract_test_persistent_replay(database)
    item = identity()
    replay.consume_if_new((item,), committed_at=NOW)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE replay_consumption SET receipt_json = ? WHERE identity_hash = ?",
            ('{"forged":true}', item.identity_hash),
        )
    with pytest.raises(FoundationError, match="stored persistence receipt"):
        replay.receipt_for(item)


def test_unknown_or_inconsistent_schema_fails_closed(tmp_path):
    database = tmp_path / "replay.sqlite3"
    build_contract_test_persistent_replay(database).consume_if_new((identity(),), committed_at=NOW)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(FoundationError, match="unknown replay schema"):
        build_contract_test_persistent_replay(database).receipt_for(identity())


def test_truncated_or_replaced_storage_cannot_be_reinitialized(tmp_path):
    database = tmp_path / "replay.sqlite3"
    build_contract_test_persistent_replay(database).consume_if_new((identity(),), committed_at=NOW)
    database.write_bytes(database.read_bytes()[:137])
    with pytest.raises(FoundationError, match="schema|storage"):
        build_contract_test_persistent_replay(database)

    replacement = tmp_path / "replacement.sqlite3"
    sqlite3.connect(replacement).close()
    with pytest.raises(FoundationError, match="schema"):
        build_contract_test_persistent_replay(replacement)


def test_empty_duplicate_naive_time_and_invalid_storage_are_rejected(tmp_path):
    replay = build_contract_test_persistent_replay(tmp_path / "replay.sqlite3")
    item = identity()
    with pytest.raises(FoundationError, match="cannot be empty"):
        replay.consume_if_new((), committed_at=NOW)
    with pytest.raises(FoundationError, match="within batch"):
        replay.consume_if_new((item, item), committed_at=NOW)
    with pytest.raises(FoundationError, match="timezone-aware"):
        replay.consume_if_new((item,), committed_at=NOW.replace(tzinfo=None))
    with pytest.raises(FoundationError, match="must be a file"):
        build_contract_test_persistent_replay(tmp_path)


def test_adapter_constructor_is_sealed(tmp_path):
    with pytest.raises(FoundationError, match="factory-created"):
        ContractTestPersistentReplay(tmp_path / "replay.sqlite3", _factory_token=object())
