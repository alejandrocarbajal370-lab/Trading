"""Durable replay contract-test boundary; no REAL custody is provisioned."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.external_provider_foundation import (
    FoundationError,
    MaterialObservation,
    ProvisioningState,
)

CONTRACT_VERSION = "durable-replay-custody-boundary-v1"
SCHEMA_VERSION = "contract-test-replay-schema-v1"
SHA256 = r"^[0-9a-f]{64}$"


class ReplayDisposition(StrEnum):
    CONSUMED_NEW = "CONSUMED_NEW"


class CustodyProofState(StrEnum):
    LOCAL_PERSISTENCE_ACKNOWLEDGED = "LOCAL_PERSISTENCE_ACKNOWLEDGED"


class RetentionProofState(StrEnum):
    NOT_PROVISIONED = "NOT_PROVISIONED"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReplayIdentity(_ContractModel):
    contract_version: Literal["durable-replay-custody-boundary-v1"] = CONTRACT_VERSION
    route_hash: str = Field(pattern=SHA256)
    material_digest: str = Field(pattern=SHA256)
    provenance_digest: str = Field(pattern=SHA256)
    identity_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_identity(self):
        _check_hash(self, "identity_hash")
        return self


class PersistenceReceipt(_ContractModel):
    replay_identity: ReplayIdentity
    disposition: Literal[ReplayDisposition.CONSUMED_NEW]
    committed_at: dt.datetime
    adapter_mode: Literal[ProvisioningState.CONTRACT_TEST_ONLY]
    custody_proof: Literal[CustodyProofState.LOCAL_PERSISTENCE_ACKNOWLEDGED]
    external_custody: Literal[ProvisioningState.NOT_PROVISIONED]
    worm_retention: Literal[ProvisioningState.NOT_PROVISIONED]
    legal_retention_approval: Literal[ProvisioningState.NOT_PROVISIONED]
    trust_root: Literal[ProvisioningState.NOT_PROVISIONED]
    receipt_hash: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_receipt(self):
        _revalidate(ReplayIdentity, self.replay_identity, "replay identity")
        _aware(self.committed_at, "committed_at")
        _check_hash(self, "receipt_hash")
        return self


def derive_replay_identity(observation: Any) -> ReplayIdentity:
    """Bind replay identity only to already-governed route, material and provenance."""
    observed = _revalidate(MaterialObservation, observation, "observation")
    return _seal(
        ReplayIdentity,
        "identity_hash",
        route_hash=observed.route.route_hash,
        material_digest=observed.material_digest,
        provenance_digest=observed.provenance_digest,
    )


class ContractTestPersistentReplay:
    """SQLite-backed contract adapter with restart-safe atomic consume-if-new."""

    provisioning_state = ProvisioningState.CONTRACT_TEST_ONLY

    def __init__(self, database: Path, *, _factory_token: object) -> None:
        if _factory_token is not _FACTORY_TOKEN:
            raise FoundationError("persistent replay must be factory-created")
        self._database = database
        connection = self._connect(initialize=not database.exists())
        connection.close()

    def consume_if_new(
        self, identities: tuple[ReplayIdentity, ...], *, committed_at: dt.datetime
    ) -> tuple[PersistenceReceipt, ...]:
        _aware(committed_at, "committed_at")
        canonical = tuple(_revalidate(ReplayIdentity, item, "replay identity") for item in identities)
        if not canonical:
            raise FoundationError("replay batch cannot be empty")
        keys = tuple(item.identity_hash for item in canonical)
        if len(keys) != len(set(keys)):
            raise FoundationError("duplicate replay identity within batch")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT identity_hash FROM replay_consumption WHERE identity_hash IN ({','.join('?' for _ in keys)})",
                keys,
            ).fetchall()
            if existing:
                raise FoundationError("replay identity already consumed")
            receipts = tuple(self._receipt(item, committed_at) for item in canonical)
            connection.executemany(
                "INSERT INTO replay_consumption(identity_hash, identity_json, receipt_json) VALUES (?, ?, ?)",
                (
                    (
                        item.identity_hash,
                        item.model_dump_json(),
                        receipt.model_dump_json(),
                    )
                    for item, receipt in zip(canonical, receipts, strict=True)
                ),
            )
            connection.commit()
            return receipts
        except FoundationError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise FoundationError("durable replay commit unavailable or ambiguous") from exc
        finally:
            connection.close()

    def receipt_for(self, identity: ReplayIdentity) -> PersistenceReceipt | None:
        canonical = _revalidate(ReplayIdentity, identity, "replay identity")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT identity_json, receipt_json FROM replay_consumption WHERE identity_hash = ?",
                (canonical.identity_hash,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise FoundationError("durable replay storage unavailable") from exc
        finally:
            connection.close()
        if row is None:
            return None
        stored_identity = _revalidate(ReplayIdentity, row[0], "stored replay identity")
        if stored_identity != canonical:
            raise FoundationError("replay identity collision or storage corruption")
        receipt = _revalidate(PersistenceReceipt, row[1], "stored persistence receipt")
        if receipt.replay_identity != canonical:
            raise FoundationError("persistence receipt binding mismatch")
        return receipt

    def _connect(self, *, initialize: bool = False) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._database, timeout=5, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if initialize:
                if version != 0:
                    raise FoundationError("new replay storage has unexpected schema version")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE replay_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE replay_consumption ("
                    "identity_hash TEXT PRIMARY KEY, identity_json TEXT NOT NULL, receipt_json TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO replay_metadata(key, value) VALUES ('schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
                connection.execute("PRAGMA user_version=1")
                connection.commit()
            elif version != 1:
                raise FoundationError("unknown replay schema version")
            stored = connection.execute(
                "SELECT value FROM replay_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if stored is None or stored[0] != SCHEMA_VERSION:
                raise FoundationError("replay schema metadata mismatch")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise FoundationError("replay storage integrity check failed")
            return connection
        except FoundationError:
            if connection is not None:
                connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise FoundationError("durable replay storage unavailable") from exc

    @staticmethod
    def _receipt(identity: ReplayIdentity, committed_at: dt.datetime) -> PersistenceReceipt:
        return _seal(
            PersistenceReceipt,
            "receipt_hash",
            replay_identity=identity,
            disposition=ReplayDisposition.CONSUMED_NEW,
            committed_at=committed_at,
            adapter_mode=ProvisioningState.CONTRACT_TEST_ONLY,
            custody_proof=CustodyProofState.LOCAL_PERSISTENCE_ACKNOWLEDGED,
            external_custody=ProvisioningState.NOT_PROVISIONED,
            worm_retention=ProvisioningState.NOT_PROVISIONED,
            legal_retention_approval=ProvisioningState.NOT_PROVISIONED,
            trust_root=ProvisioningState.NOT_PROVISIONED,
        )


_FACTORY_TOKEN = object()


def build_contract_test_persistent_replay(database: os.PathLike[str] | str) -> ContractTestPersistentReplay:
    path = Path(database)
    if path.exists() and not path.is_file():
        raise FoundationError("replay database must be a file")
    if not path.parent.exists() or not path.parent.is_dir():
        raise FoundationError("replay database parent must already exist")
    return ContractTestPersistentReplay(path, _factory_token=_FACTORY_TOKEN)


T = TypeVar("T", bound=BaseModel)


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise FoundationError("model contains undeclared fields")
        value = value.model_dump(mode="json", warnings=False)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise FoundationError("input is not canonically serializable") from exc


def _revalidate(expected: type[T], value: Any, label: str) -> T:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return expected.model_validate(_primitive(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FoundationError(f"invalid {label}") from exc


def _seal(expected: type[T], hash_field: str, **values: Any) -> T:
    raw = expected.model_construct(**values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(raw.model_dump(mode="json", exclude={hash_field}, warnings=False))
    return expected(**values)


def _check_hash(value: BaseModel, hash_field: str) -> None:
    expected = typed_hash(value.model_dump(mode="json", exclude={hash_field}, warnings=False))
    if getattr(value, hash_field) != expected:
        raise ValueError(f"{hash_field} mismatch")


def _aware(value: dt.datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FoundationError(f"{label} must be timezone-aware")
