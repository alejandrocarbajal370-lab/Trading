"""Durable custody, WORM and replay contract foundation.

The SQLite adapter proves only restart-safe contract semantics.  It is neither
external custody nor WORM storage and can never activate a REAL route.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import unicodedata
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.external_trust_verifier import (
    AuthorityRegistryEvidence,
    ExternalAttestationEnvelope,
    IndependentVerificationResult,
    ProvisioningState,
    TrustAnchorProvisioningEvidence,
    assess_contract_test,
)
from governance.ibkr_real_provisioning import (
    AuthenticEntitlementEvidence,
    IBKRSessionBinding,
    SessionObservation,
)
from governance.phase7e import EvidenceGate, GateState

CONTRACT_VERSION = "durable-custody-worm-replay-v1"
SCHEMA_VERSION = "contract-test-durable-custody-schema-v2"
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{2,127}$"


class DurableCustodyError(ValueError):
    """Untrusted custody input failed closed without reflecting its contents."""


class ArtifactKind(StrEnum):
    RAW = "RAW"
    DERIVED = "DERIVED"


class LockMode(StrEnum):
    GOVERNANCE = "GOVERNANCE"
    COMPLIANCE = "COMPLIANCE"


class CustodyRole(StrEnum):
    CUSTODY_OPERATOR = "CUSTODY_OPERATOR"
    CONTINUITY_AUDITOR = "CONTINUITY_AUDITOR"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001
            raise DurableCustodyError("invalid durable custody value") from None


class Lifecycle(_Model):
    available_at: dt.datetime
    effective_at: dt.datetime
    verified_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    lifecycle_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_lifecycle(self):
        for value in (self.available_at, self.effective_at, self.verified_at, self.expires_at):
            _utc(value)
        if self.revoked_at is not None:
            _utc(self.revoked_at)
        if not self.available_at <= self.effective_at <= self.verified_at < self.expires_at:
            raise ValueError("invalid lifecycle")
        if self.revoked_at is not None and self.revoked_at < self.available_at:
            raise ValueError("invalid revocation")
        _hash(self, "lifecycle_hash")
        return self


class BackendProvisioningEvidence(_Model):
    backend_id: str = Field(pattern=IDENTIFIER)
    deployment_id: str = Field(pattern=IDENTIFIER)
    backend_reference_digest: str = Field(pattern=SHA256)
    deployment_reference_digest: str = Field(pattern=SHA256)
    provisioning_material_digest: str = Field(pattern=SHA256)
    authority_registry_evidence_hash: str = Field(pattern=SHA256)
    lifecycle: Lifecycle
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.backend_id)
        _identifier(self.deployment_id)
        object.__setattr__(self, "lifecycle", _rebuild(Lifecycle, self.lifecycle))
        _hash(self, "evidence_hash")
        return self


class CustodyPrincipalEvidence(_Model):
    principal_id: str = Field(pattern=IDENTIFIER)
    role: CustodyRole
    principal_reference_digest: str = Field(pattern=SHA256)
    authority_registry_evidence_hash: str = Field(pattern=SHA256)
    lifecycle: Lifecycle
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.principal_id)
        object.__setattr__(self, "lifecycle", _rebuild(Lifecycle, self.lifecycle))
        _hash(self, "evidence_hash")
        return self


class WormPolicyEvidence(_Model):
    policy_id: str = Field(pattern=IDENTIFIER)
    policy_version: str = Field(pattern=IDENTIFIER)
    backend_evidence_hash: str = Field(pattern=SHA256)
    authority_registry_evidence_hash: str = Field(pattern=SHA256)
    retention_seconds: int = Field(gt=0)
    lock_mode: LockMode
    effective_at: dt.datetime
    retain_until: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    configuration_digest: str = Field(pattern=SHA256)
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    immutability_proof_real: Literal[ProvisioningState.NOT_PROVISIONED]
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.policy_id)
        _identifier(self.policy_version)
        for value in (self.effective_at, self.retain_until, self.expires_at):
            _utc(value)
        if self.revoked_at is not None:
            _utc(self.revoked_at)
        if not self.effective_at < self.retain_until <= self.expires_at:
            raise ValueError("invalid retention chronology")
        if int((self.retain_until - self.effective_at).total_seconds()) != self.retention_seconds:
            raise ValueError("retention duration mismatch")
        _hash(self, "evidence_hash")
        return self


class ArtifactIdentity(_Model):
    artifact_id: str = Field(pattern=IDENTIFIER)
    kind: ArtifactKind
    scope_id: str = Field(pattern=IDENTIFIER)
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")
    content_hash: str = Field(pattern=SHA256)
    size_bytes: int = Field(gt=0)
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    lineage_digest: str = Field(pattern=SHA256)
    raw_source_identity_hash: str | None = Field(default=None, pattern=SHA256)
    identity_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.artifact_id)
        _identifier(self.scope_id)
        if (self.kind is ArtifactKind.RAW) != (self.raw_source_identity_hash is None):
            raise ValueError("raw/derived lineage ambiguity")
        _hash(self, "identity_hash")
        return self


class CustodyReceipt(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    receipt_id: str = Field(pattern=IDENTIFIER)
    provider: Literal["provider.ibkr"]
    adapter_id: str = Field(pattern=IDENTIFIER)
    dataset_id: str = Field(pattern=IDENTIFIER)
    route_id: str = Field(pattern=IDENTIFIER)
    request_id: str = Field(pattern=IDENTIFIER)
    request_hash: str = Field(pattern=SHA256)
    security_master_id: Literal["security.us.msft.xnas"]
    con_id: Literal[272093]
    session_binding_hash: str = Field(pattern=SHA256)
    entitlement_evidence_hash: str = Field(pattern=SHA256)
    observation_digest: str = Field(pattern=SHA256)
    attestation_envelope_hash: str = Field(pattern=SHA256)
    independent_verification_hash: str = Field(pattern=SHA256)
    backend_evidence_hash: str = Field(pattern=SHA256)
    policy_evidence_hash: str = Field(pattern=SHA256)
    custody_operator_evidence_hash: str = Field(pattern=SHA256)
    artifact: ArtifactIdentity
    stored_at: dt.datetime
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    external_custody_real: Literal[ProvisioningState.NOT_PROVISIONED]
    worm_real: Literal[ProvisioningState.NOT_PROVISIONED]
    receipt_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.receipt_id)
        for value in (self.adapter_id, self.dataset_id, self.route_id, self.request_id):
            _identifier(value)
        _utc(self.stored_at)
        object.__setattr__(self, "artifact", _rebuild(ArtifactIdentity, self.artifact))
        _hash(self, "receipt_hash")
        return self


class ReplayIdentity(_Model):
    provider: Literal["provider.ibkr"]
    semantic_scope_hash: str = Field(pattern=SHA256)
    raw_artifact_identity_hash: str = Field(pattern=SHA256)
    attestation_envelope_hash: str = Field(pattern=SHA256)
    independent_verification_hash: str = Field(pattern=SHA256)
    backend_evidence_hash: str = Field(pattern=SHA256)
    policy_evidence_hash: str = Field(pattern=SHA256)
    identity_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        expected = typed_hash(
            {
                "provider": self.provider,
                "semantic_scope_hash": self.semantic_scope_hash,
                "attestation_envelope_hash": self.attestation_envelope_hash,
                "independent_verification_hash": self.independent_verification_hash,
                "backend_evidence_hash": self.backend_evidence_hash,
                "policy_evidence_hash": self.policy_evidence_hash,
            }
        )
        if self.identity_hash != expected:
            raise ValueError("replay identity mismatch")
        return self


class AccessAuditEvidence(_Model):
    event_id: str = Field(pattern=IDENTIFIER)
    receipt_hash: str = Field(pattern=SHA256)
    replay_identity_hash: str = Field(pattern=SHA256)
    operator_evidence_hash: str = Field(pattern=SHA256)
    action: Literal["STORE_AND_CONSUME"]
    occurred_at: dt.datetime
    event_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.event_id)
        _utc(self.occurred_at)
        _hash(self, "event_digest")
        return self


class ReplayJournalEvidence(_Model):
    store_id: str = Field(pattern=IDENTIFIER)
    schema_version: Literal[SCHEMA_VERSION]
    sequence: int = Field(gt=0)
    replay_identity: ReplayIdentity
    receipt_hashes: tuple[str, ...] = Field(min_length=1)
    previous_entry_hash: str = Field(pattern=SHA256)
    committed_at: dt.datetime
    entry_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.store_id)
        _utc(self.committed_at)
        object.__setattr__(self, "replay_identity", _rebuild(ReplayIdentity, self.replay_identity))
        if len(set(self.receipt_hashes)) != len(self.receipt_hashes):
            raise ValueError("duplicate receipt in journal entry")
        _hash(self, "entry_hash")
        return self


class DurableReplayCheckpointReference(_Model):
    """Caller-custodied reference; only an external authority can make it REAL."""

    store_id: str = Field(pattern=IDENTIFIER)
    schema_version: Literal[SCHEMA_VERSION]
    sequence: int = Field(ge=0)
    journal_head_hash: str = Field(pattern=SHA256)
    external_authoritative_anchor_real: Literal[ProvisioningState.NOT_PROVISIONED]
    checkpoint_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.store_id)
        if self.sequence == 0 and self.journal_head_hash != "0" * 64:
            raise ValueError("invalid empty checkpoint")
        _hash(self, "checkpoint_hash")
        return self


class RestoreVerificationEvidence(_Model):
    restore_id: str = Field(pattern=IDENTIFIER)
    receipt_hash: str = Field(pattern=SHA256)
    artifact_identity_hash: str = Field(pattern=SHA256)
    replay_entry_hash: str = Field(pattern=SHA256)
    continuity_auditor_evidence_hash: str = Field(pattern=SHA256)
    restored_content_hash: str = Field(pattern=SHA256)
    restored_size_bytes: int = Field(gt=0)
    verified_at: dt.datetime
    evidence_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        _identifier(self.restore_id)
        _utc(self.verified_at)
        _hash(self, "evidence_hash")
        return self


class DurableCustodyAssessment(_Model):
    state: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    custody_contract_validated: Literal[True]
    replay_restore_contract_validated: Literal[True]
    content_hash_is_worm_proof: Literal[False]
    external_custody_real: Literal[ProvisioningState.NOT_PROVISIONED]
    worm_real: Literal[ProvisioningState.NOT_PROVISIONED]
    durable_replay_real: Literal[ProvisioningState.NOT_PROVISIONED]
    legal_licensing_real: Literal[ProvisioningState.NOT_PROVISIONED]
    provider_admission_real: Literal[ProvisioningState.NOT_PROVISIONED]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]


class ContractTestDurableStore:
    """Factory-only local adapter with transactional object + replay persistence."""

    provisioning_state = ProvisioningState.CONTRACT_TEST_ONLY

    def __init__(
        self,
        path: Path,
        *,
        token: object,
        expected_store_id: str | None,
        expected_checkpoint: DurableReplayCheckpointReference | None,
    ) -> None:
        if token is not _FACTORY_TOKEN:
            raise DurableCustodyError("durable store must be factory-created")
        self._path = path
        initialize = not path.exists()
        if not initialize and expected_checkpoint is None:
            raise DurableCustodyError("expected checkpoint required for existing durable store")
        connection = self._connect(initialize=initialize)
        try:
            self.store_id = connection.execute(
                "SELECT value FROM metadata WHERE key='store_id'"
            ).fetchone()[0]
            if expected_store_id is not None and self.store_id != expected_store_id:
                raise DurableCustodyError("durable store replacement detected")
            checkpoint = self._checkpoint_from_connection(connection)
            if expected_checkpoint is not None:
                expected = _rebuild(DurableReplayCheckpointReference, expected_checkpoint)
                if checkpoint != expected:
                    raise DurableCustodyError("durable store checkpoint rollback or replacement detected")
            self._checkpoint = checkpoint
        finally:
            connection.close()

    @property
    def checkpoint(self) -> DurableReplayCheckpointReference:
        """Export the reference that an independent caller must persist monotonically."""
        return self._checkpoint

    def store_and_consume(
        self,
        items: tuple[tuple[CustodyReceipt, bytes], ...],
        replay_identity: ReplayIdentity,
        *,
        committed_at: dt.datetime,
    ) -> ReplayJournalEvidence:
        _utc(committed_at)
        replay = _rebuild(ReplayIdentity, replay_identity)
        if type(items) is not tuple or not items:
            raise DurableCustodyError("non-empty exact batch required")
        canonical: list[tuple[CustodyReceipt, bytes]] = []
        for item in items:
            if type(item) is not tuple or len(item) != 2 or type(item[1]) is not bytes:
                raise DurableCustodyError("invalid custody batch")
            receipt = _rebuild(CustodyReceipt, item[0])
            content = item[1]
            if not content or len(content) != receipt.artifact.size_bytes:
                raise DurableCustodyError("artifact size mismatch")
            if hashlib.sha256(content).hexdigest() != receipt.artifact.content_hash:
                raise DurableCustodyError("artifact content mismatch")
            canonical.append((receipt, content))
        if any(receipt.stored_at > committed_at for receipt, _ in canonical):
            raise DurableCustodyError("storage commit chronology invalid")
        hashes = tuple(item[0].receipt_hash for item in canonical)
        identities = tuple(item[0].artifact.identity_hash for item in canonical)
        if len(set(hashes)) != len(hashes) or len(set(identities)) != len(identities):
            raise DurableCustodyError("duplicate artifact or receipt in batch")
        raw = tuple(item for item, _ in canonical if item.artifact.kind is ArtifactKind.RAW)
        if len(raw) != 1 or raw[0].artifact.identity_hash != replay.raw_artifact_identity_hash:
            raise DurableCustodyError("replay/raw artifact binding mismatch")
        if any(
            item.artifact.kind is ArtifactKind.DERIVED
            and item.artifact.raw_source_identity_hash != raw[0].artifact.identity_hash
            for item, _ in canonical
        ):
            raise DurableCustodyError("derived artifact lineage mismatch")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if self._checkpoint_from_connection(connection) != self._checkpoint:
                raise DurableCustodyError("durable store checkpoint changed or rolled back")
            if connection.execute(
                "SELECT 1 FROM journal WHERE replay_identity_hash=?", (replay.identity_hash,)
            ).fetchone():
                raise DurableCustodyError("replay identity already consumed")
            row = connection.execute(
                "SELECT sequence, entry_hash FROM journal ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence, previous = (1, "0" * 64) if row is None else (row[0] + 1, row[1])
            entry = seal_contract_test(
                ReplayJournalEvidence,
                "entry_hash",
                store_id=self.store_id,
                schema_version=SCHEMA_VERSION,
                sequence=sequence,
                replay_identity=replay,
                receipt_hashes=hashes,
                previous_entry_hash=previous,
                committed_at=committed_at,
            )
            for receipt, content in canonical:
                connection.execute(
                    "INSERT INTO objects(identity_hash,receipt_hash,receipt_json,content) VALUES(?,?,?,?)",
                    (receipt.artifact.identity_hash, receipt.receipt_hash, receipt.model_dump_json(), content),
                )
            connection.execute(
                "INSERT INTO journal(sequence,replay_identity_hash,entry_json,entry_hash) VALUES(?,?,?,?)",
                (sequence, replay.identity_hash, entry.model_dump_json(), entry.entry_hash),
            )
            connection.commit()
            self._checkpoint = _checkpoint(self.store_id, sequence, entry.entry_hash)
            return entry
        except DurableCustodyError:
            connection.rollback()
            raise
        except (OSError, sqlite3.Error):
            connection.rollback()
            raise DurableCustodyError("durable batch commit unavailable or ambiguous") from None
        finally:
            connection.close()

    def restore(self, artifact: ArtifactIdentity) -> tuple[CustodyReceipt, bytes]:
        identity = _rebuild(ArtifactIdentity, artifact)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT receipt_json, content FROM objects WHERE identity_hash=?",
                (identity.identity_hash,),
            ).fetchone()
        except (OSError, sqlite3.Error):
            raise DurableCustodyError("durable restore unavailable") from None
        finally:
            connection.close()
        if row is None:
            raise DurableCustodyError("durable object missing")
        receipt = _rebuild(CustodyReceipt, row[0])
        content = bytes(row[1])
        if receipt.artifact != identity or hashlib.sha256(content).hexdigest() != identity.content_hash:
            raise DurableCustodyError("durable object corrupt or mismatched")
        if len(content) != identity.size_bytes:
            raise DurableCustodyError("durable object truncated")
        return receipt, content

    def _connect(self, *, initialize: bool = False) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._path, timeout=10, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if initialize:
                if version != 0:
                    raise DurableCustodyError("new durable store has ambiguous schema")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                connection.execute(
                    "CREATE TABLE objects(identity_hash TEXT PRIMARY KEY,receipt_hash TEXT UNIQUE NOT NULL,receipt_json TEXT NOT NULL,content BLOB NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE journal(sequence INTEGER PRIMARY KEY,replay_identity_hash TEXT UNIQUE NOT NULL,entry_json TEXT NOT NULL,entry_hash TEXT NOT NULL)"
                )
                store_id = f"store.{uuid.uuid4().hex}"
                connection.executemany(
                    "INSERT INTO metadata(key,value) VALUES(?,?)",
                    (("schema_version", SCHEMA_VERSION), ("store_id", store_id)),
                )
                connection.execute("PRAGMA user_version=2")
                connection.commit()
            if version not in {0 if initialize else 2, 2}:
                raise DurableCustodyError("unknown durable store schema")
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise DurableCustodyError("durable store integrity check failed")
            metadata = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
            if metadata.get("schema_version") != SCHEMA_VERSION or not _valid_identifier(
                metadata.get("store_id")
            ):
                raise DurableCustodyError("durable store metadata mismatch")
            self._checkpoint_from_connection(connection)
            return connection
        except DurableCustodyError:
            if connection is not None:
                connection.close()
            raise
        except (OSError, sqlite3.Error):
            if connection is not None:
                connection.close()
            raise DurableCustodyError("durable store unavailable or corrupt") from None

    @staticmethod
    def _checkpoint_from_connection(
        connection: sqlite3.Connection,
    ) -> DurableReplayCheckpointReference:
        metadata = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
        store_id = metadata["store_id"]
        objects: dict[str, CustodyReceipt] = {}
        identities: set[str] = set()
        for identity_hash, receipt_hash, receipt_json, content in connection.execute(
            "SELECT identity_hash,receipt_hash,receipt_json,content FROM objects"
        ):
            receipt = _rebuild(CustodyReceipt, receipt_json)
            payload = bytes(content)
            if (
                identity_hash != receipt.artifact.identity_hash
                or receipt_hash != receipt.receipt_hash
                or receipt_hash in objects
                or identity_hash in identities
                or len(payload) != receipt.artifact.size_bytes
                or hashlib.sha256(payload).hexdigest() != receipt.artifact.content_hash
            ):
                raise DurableCustodyError("durable object receipt or content mismatch")
            objects[receipt_hash] = receipt
            identities.add(identity_hash)
        previous = "0" * 64
        sequence = 0
        claimed: set[str] = set()
        for row_sequence, payload, entry_hash in connection.execute(
                "SELECT sequence,entry_json,entry_hash FROM journal ORDER BY sequence"
            ):
            sequence += 1
            entry = _rebuild(ReplayJournalEvidence, payload)
            if (
                entry.store_id != store_id
                or row_sequence != sequence
                or entry.sequence != sequence
                or entry.previous_entry_hash != previous
                or entry.entry_hash != entry_hash
            ):
                raise DurableCustodyError("durable replay journal rollback or corruption")
            receipts = []
            for receipt_hash in entry.receipt_hashes:
                if receipt_hash in claimed or receipt_hash not in objects:
                    raise DurableCustodyError("durable journal object missing or ambiguous")
                claimed.add(receipt_hash)
                receipts.append(objects[receipt_hash])
            raw = tuple(item for item in receipts if item.artifact.kind is ArtifactKind.RAW)
            if (
                len(raw) != 1
                or raw[0].artifact.identity_hash != entry.replay_identity.raw_artifact_identity_hash
                or derive_replay_identity(raw[0]) != entry.replay_identity
                or any(item.stored_at > entry.committed_at for item in receipts)
                or any(
                    item.artifact.kind is ArtifactKind.DERIVED
                    and item.artifact.raw_source_identity_hash != raw[0].artifact.identity_hash
                    for item in receipts
                )
            ):
                raise DurableCustodyError("durable journal object binding mismatch")
            previous = entry.entry_hash
        if claimed != set(objects):
            raise DurableCustodyError("durable object is not bound to journal")
        return _checkpoint(store_id, sequence, previous)


_FACTORY_TOKEN = object()


def build_contract_test_store(
    database: os.PathLike[str] | str,
    *,
    expected_store_id: str | None = None,
    expected_checkpoint: DurableReplayCheckpointReference | dict[str, Any] | str | None = None,
) -> ContractTestDurableStore:
    path = Path(database)
    if not path.exists() and any(Path(f"{path}{suffix}").exists() for suffix in ("-wal", "-shm")):
        raise DurableCustodyError("orphaned durable store state detected")
    if path.exists() and not path.is_file():
        raise DurableCustodyError("durable store path must be a file")
    if not path.parent.is_dir():
        raise DurableCustodyError("durable store parent must exist")
    if expected_store_id is not None:
        _identifier(expected_store_id)
    checkpoint = (
        None
        if expected_checkpoint is None
        else _rebuild(DurableReplayCheckpointReference, expected_checkpoint)
    )
    return ContractTestDurableStore(
        path,
        token=_FACTORY_TOKEN,
        expected_store_id=expected_store_id,
        expected_checkpoint=checkpoint,
    )


def artifact_identity(
    *, artifact_id: str, kind: ArtifactKind, scope_id: str, media_type: str, content: bytes,
    material_digest: str, provenance_digest: str, lineage_digest: str,
    raw_source_identity_hash: str | None = None,
) -> ArtifactIdentity:
    if type(content) is not bytes or not content:
        raise DurableCustodyError("artifact bytes required")
    return seal_contract_test(
        ArtifactIdentity, "identity_hash", artifact_id=artifact_id, kind=kind,
        scope_id=scope_id, media_type=media_type, content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content), material_digest=material_digest,
        provenance_digest=provenance_digest, lineage_digest=lineage_digest,
        raw_source_identity_hash=raw_source_identity_hash,
    )


def derive_replay_identity(receipt: Any) -> ReplayIdentity:
    value = _rebuild(CustodyReceipt, receipt)
    if value.artifact.kind is not ArtifactKind.RAW:
        raise DurableCustodyError("replay identity requires raw artifact")
    semantic_scope_hash = typed_hash(
        {
            "provider": value.provider,
            "session": value.session_binding_hash,
            "entitlement": value.entitlement_evidence_hash,
            "observation": value.observation_digest,
            "material": value.artifact.material_digest,
            "provenance": value.artifact.provenance_digest,
            "lineage": value.artifact.lineage_digest,
            "scope": value.artifact.scope_id,
            "content": value.artifact.content_hash,
        }
    )
    identity_hash = typed_hash(
        {
            "provider": value.provider,
            "semantic_scope_hash": semantic_scope_hash,
            "attestation_envelope_hash": value.attestation_envelope_hash,
            "independent_verification_hash": value.independent_verification_hash,
            "backend_evidence_hash": value.backend_evidence_hash,
            "policy_evidence_hash": value.policy_evidence_hash,
        }
    )
    return ReplayIdentity(
        provider=value.provider,
        semantic_scope_hash=semantic_scope_hash,
        raw_artifact_identity_hash=value.artifact.identity_hash,
        attestation_envelope_hash=value.attestation_envelope_hash,
        independent_verification_hash=value.independent_verification_hash,
        backend_evidence_hash=value.backend_evidence_hash,
        policy_evidence_hash=value.policy_evidence_hash,
        identity_hash=identity_hash,
    )


def verify_restore(
    *, store: ContractTestDurableStore, artifact: Any, replay_entry: Any,
    auditor: Any, receipt: Any, verified_at: dt.datetime, restore_id: str,
) -> RestoreVerificationEvidence:
    if type(store) is not ContractTestDurableStore:
        raise DurableCustodyError("contract-test store required")
    identity = _rebuild(ArtifactIdentity, artifact)
    entry = _rebuild(ReplayJournalEvidence, replay_entry)
    actor = _rebuild(CustodyPrincipalEvidence, auditor)
    bound_receipt = _rebuild(CustodyReceipt, receipt)
    _utc(verified_at)
    if actor.role is not CustodyRole.CONTINUITY_AUDITOR:
        raise DurableCustodyError("distinct continuity auditor required")
    _current(actor.lifecycle, verified_at)
    restored_receipt, content = store.restore(identity)
    if restored_receipt != bound_receipt or bound_receipt.receipt_hash not in entry.receipt_hashes:
        raise DurableCustodyError("restore receipt/version mismatch")
    if verified_at < entry.committed_at or verified_at >= _policy_expiry_placeholder(bound_receipt):
        raise DurableCustodyError("restore chronology invalid")
    return seal_contract_test(
        RestoreVerificationEvidence, "evidence_hash", restore_id=restore_id,
        receipt_hash=bound_receipt.receipt_hash, artifact_identity_hash=identity.identity_hash,
        replay_entry_hash=entry.entry_hash, continuity_auditor_evidence_hash=actor.evidence_hash,
        restored_content_hash=hashlib.sha256(content).hexdigest(), restored_size_bytes=len(content),
        verified_at=verified_at,
    )


def assess_contract_test_custody(
    *, session: Any, entitlement: Any, observation: Any, trust_anchor: Any,
    authority_registry: Any, principals: tuple[Any, ...], attestations: tuple[Any, ...],
    verification: Any, backend: Any, policy: Any, custody_principals: tuple[Any, ...],
    receipts: tuple[Any, ...], replay_entry: Any, access_audit: Any, restore: Any,
    assessed_at: dt.datetime,
) -> DurableCustodyAssessment:
    """Rebuild and bind the complete Step 1→3 graph; never grant REAL status."""
    try:
        assess_contract_test(
            session=session, entitlement=entitlement, observation=observation,
            trust_anchor=trust_anchor, authority_registry=authority_registry,
            principals=principals, attestations=attestations, verification=verification,
            assessed_at=assessed_at,
        )
        session = _upstream(IBKRSessionBinding, session)
        entitlement = _upstream(AuthenticEntitlementEvidence, entitlement)
        observation = _upstream(SessionObservation, observation)
        anchor = _upstream(TrustAnchorProvisioningEvidence, trust_anchor)
        registry = _upstream(AuthorityRegistryEvidence, authority_registry)
        envelope = _upstream(ExternalAttestationEnvelope, attestations[0])
        result = _upstream(IndependentVerificationResult, verification)
        backend = _rebuild(BackendProvisioningEvidence, backend)
        policy = _rebuild(WormPolicyEvidence, policy)
        if type(custody_principals) is not tuple:
            raise TypeError
        actors = tuple(_rebuild(CustodyPrincipalEvidence, item) for item in custody_principals)
        if tuple(item.role for item in actors) != tuple(CustodyRole):
            raise ValueError
        if len({item.principal_id for item in actors}) != len(actors):
            raise ValueError
        if type(receipts) is not tuple or not receipts:
            raise ValueError
        receipts = tuple(_rebuild(CustodyReceipt, item) for item in receipts)
        entry = _rebuild(ReplayJournalEvidence, replay_entry)
        audit = _rebuild(AccessAuditEvidence, access_audit)
        restored = _rebuild(RestoreVerificationEvidence, restore)
        _utc(assessed_at)
        if backend.authority_registry_evidence_hash != registry.evidence_hash:
            raise ValueError
        if policy.backend_evidence_hash != backend.evidence_hash or policy.authority_registry_evidence_hash != registry.evidence_hash:
            raise ValueError
        for actor in actors:
            if actor.authority_registry_evidence_hash != registry.evidence_hash:
                raise ValueError
            _current(actor.lifecycle, assessed_at)
        _current(backend.lifecycle, assessed_at)
        _policy_current(policy, assessed_at)
        operator = actors[0]
        for receipt in receipts:
            if (
                any(
                    getattr(receipt, field) != getattr(session, field)
                    for field in (
                        "provider", "adapter_id", "dataset_id", "route_id", "request_id",
                        "request_hash", "security_master_id", "con_id",
                    )
                )
                or
                receipt.session_binding_hash != session.binding_hash
                or receipt.entitlement_evidence_hash != entitlement.evidence_hash
                or receipt.observation_digest != observation.observation_digest
                or receipt.attestation_envelope_hash != envelope.envelope_hash
                or receipt.independent_verification_hash != result.result_hash
                or receipt.backend_evidence_hash != backend.evidence_hash
                or receipt.policy_evidence_hash != policy.evidence_hash
                or receipt.custody_operator_evidence_hash != operator.evidence_hash
                or receipt.stored_at < result.verified_at
                or receipt.stored_at > entry.committed_at
            ):
                raise ValueError
            _current(backend.lifecycle, receipt.stored_at)
            _current(operator.lifecycle, receipt.stored_at)
            _policy_current(policy, receipt.stored_at)
        raw = tuple(item for item in receipts if item.artifact.kind is ArtifactKind.RAW)
        if len(raw) != 1 or any(
            item.artifact.kind is ArtifactKind.DERIVED
            and item.artifact.raw_source_identity_hash != raw[0].artifact.identity_hash
            for item in receipts
        ):
            raise ValueError
        replay = derive_replay_identity(raw[0])
        if entry.replay_identity != replay or entry.receipt_hashes != tuple(item.receipt_hash for item in receipts):
            raise ValueError
        if audit.receipt_hash != raw[0].receipt_hash or audit.replay_identity_hash != replay.identity_hash or audit.operator_evidence_hash != operator.evidence_hash:
            raise ValueError
        if audit.occurred_at != entry.committed_at:
            raise ValueError
        auditor = actors[1]
        if restored.receipt_hash not in entry.receipt_hashes or restored.replay_entry_hash != entry.entry_hash or restored.continuity_auditor_evidence_hash != auditor.evidence_hash:
            raise ValueError
        restored_receipt = next(item for item in receipts if item.receipt_hash == restored.receipt_hash)
        if restored.artifact_identity_hash != restored_receipt.artifact.identity_hash or restored.restored_content_hash != restored_receipt.artifact.content_hash or restored.restored_size_bytes != restored_receipt.artifact.size_bytes:
            raise ValueError
        if not entry.committed_at <= restored.verified_at <= assessed_at:
            raise ValueError
        del anchor
    except BaseException:  # noqa: BLE001
        raise DurableCustodyError("durable custody assessment failed closed") from None
    return DurableCustodyAssessment(
        state=ProvisioningState.CONTRACT_TEST_ONLY,
        custody_contract_validated=True, replay_restore_contract_validated=True,
        content_hash_is_worm_proof=False,
        external_custody_real=ProvisioningState.NOT_PROVISIONED,
        worm_real=ProvisioningState.NOT_PROVISIONED,
        durable_replay_real=ProvisioningState.NOT_PROVISIONED,
        legal_licensing_real=ProvisioningState.NOT_PROVISIONED,
        provider_admission_real=ProvisioningState.NOT_PROVISIONED,
        gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
        real_route="QVM_NOT_READY", global_readiness="INSUFFICIENT_REAL_DATA",
        trade_decision="NO_TRADE", signals_generated=False, live_execution_enabled=False,
        backtesting="NOT_AUTHORIZED",
    )


def verify_real_custody(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise DurableCustodyError("REAL durable custody, WORM and replay are NOT_PROVISIONED")


T = TypeVar("T", bound=_Model)


def seal_contract_test(model: type[T], hash_field: str, **values: Any) -> T:
    try:
        if _SEAL_FIELDS.get(model) != hash_field or hash_field in values:
            raise TypeError
        provisional = model.model_construct(**values, **{hash_field: "0" * 64})
        raw = object.__getattribute__(provisional, "__dict__")
        values = {
            name: _safe(dict.__getitem__(raw, name))
            for name in model.model_fields
            if name != hash_field
        }
        values[hash_field] = typed_hash(values)
        return model(**values)
    except BaseException:  # noqa: BLE001
        raise DurableCustodyError("invalid durable custody value") from None


def _rebuild(model: type[T], value: Any) -> T:
    try:
        if type(value) is str:
            raw = json.loads(value)
        elif type(value) is model:
            raw = {
                name: _safe(object.__getattribute__(value, "__dict__")[name])
                for name in model.model_fields
            }
        elif type(value) is dict:
            raw = _safe(value)
        else:
            raise TypeError
        return model.model_validate(raw)
    except BaseException:  # noqa: BLE001
        raise DurableCustodyError("invalid durable custody value") from None


def _upstream(model: type[Any], value: Any) -> Any:
    if type(value) is model:
        value = BaseModel.model_dump(value, mode="python")
    elif type(value) is str:
        value = json.loads(value)
    if type(value) is not dict:
        raise DurableCustodyError("invalid upstream value")
    return model.model_validate(value)


def _safe(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int, float, dt.datetime, bytes}:
        if type(value) is dt.datetime:
            _utc(value)
        return value
    if isinstance(value, StrEnum):
        return value
    if type(value) is dict:
        if any(type(key) is not str for key in dict.keys(value)):
            raise TypeError
        return {key: _safe(item) for key, item in dict.items(value)}
    if type(value) in {tuple, list}:
        return type(value)(_safe(item) for item in value)
    if type(value) in _SEAL_FIELDS:
        raw = object.__getattribute__(value, "__dict__")
        return {name: _safe(dict.__getitem__(raw, name)) for name in type(value).model_fields}
    raise TypeError


def _hash(value: BaseModel, field: str) -> None:
    raw = object.__getattribute__(value, "__dict__")
    expected = typed_hash({name: _safe(dict.__getitem__(raw, name)) for name in type(value).model_fields if name != field})
    if dict.__getitem__(raw, field) != expected:
        raise ValueError("digest mismatch")


def _utc(value: dt.datetime) -> None:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError("canonical UTC required")


def _identifier(value: str) -> None:
    if not _valid_identifier(value):
        raise ValueError("noncanonical identifier")


def _valid_identifier(value: Any) -> bool:
    return type(value) is str and value.isascii() and value == value.casefold() and value == unicodedata.normalize("NFKC", value) and 3 <= len(value) <= 127 and all(character.islower() or character.isdigit() or character in "._:-" for character in value)


def _current(lifecycle: Lifecycle, at: dt.datetime) -> None:
    if not lifecycle.verified_at <= at < lifecycle.expires_at:
        raise ValueError("lifecycle unavailable")
    if lifecycle.revoked_at is not None and lifecycle.revoked_at <= at:
        raise ValueError("lifecycle revoked")


def _policy_current(policy: WormPolicyEvidence, at: dt.datetime) -> None:
    if not policy.effective_at <= at < min(policy.retain_until, policy.expires_at):
        raise ValueError("policy unavailable")
    if policy.revoked_at is not None and policy.revoked_at <= at:
        raise ValueError("policy revoked")


def _checkpoint(
    store_id: str, sequence: int, journal_head_hash: str
) -> DurableReplayCheckpointReference:
    return seal_contract_test(
        DurableReplayCheckpointReference,
        "checkpoint_hash",
        store_id=store_id,
        schema_version=SCHEMA_VERSION,
        sequence=sequence,
        journal_head_hash=journal_head_hash,
        external_authoritative_anchor_real=ProvisioningState.NOT_PROVISIONED,
    )


def _policy_expiry_placeholder(receipt: CustodyReceipt) -> dt.datetime:
    # Receipt intentionally carries no caller-selected expiry; assessment owns policy validation.
    return receipt.stored_at + dt.timedelta(days=36500)


_SEAL_FIELDS: dict[type[_Model], str] = {
    Lifecycle: "lifecycle_hash",
    BackendProvisioningEvidence: "evidence_hash",
    CustodyPrincipalEvidence: "evidence_hash",
    WormPolicyEvidence: "evidence_hash",
    ArtifactIdentity: "identity_hash",
    CustodyReceipt: "receipt_hash",
    ReplayIdentity: "identity_hash",
    AccessAuditEvidence: "event_digest",
    ReplayJournalEvidence: "entry_hash",
    DurableReplayCheckpointReference: "checkpoint_hash",
    RestoreVerificationEvidence: "evidence_hash",
}
