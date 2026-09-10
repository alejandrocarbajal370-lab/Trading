"""Step 6 governed evidence-capture foundation.

Capture preserves canonical upstream facts.  It does not authenticate evidence,
admit a provider, close a gate, or make an observation countable by Step 5.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.external_evidence_verification import (
    MaterializedObservedEvidence,
    canonical_gate_verification_manifest,
)
from governance.phase7e import EvidenceGate, GateState
from governance.sufficient_observation_policy import CLASS_GATE, ObservationClass

CONTRACT_VERSION = "corso-governed-evidence-capture-v1"
STORE_SCHEMA_VERSION = "corso-local-evidence-capture-store-v1"
SHA256 = r"^[0-9a-f]{64}$"
SAFE_REF = r"^[a-z0-9][a-z0-9._:-]{1,127}$"


class EvidenceCaptureError(ValueError):
    """Untrusted capture material failed closed without echoing its contents."""

    def __init__(self, reason: str = "INVALID_GOVERNED_EVIDENCE_CAPTURE") -> None:
        self.reason = reason
        super().__init__(reason)


class CaptureState(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    NOT_PROVISIONED = "NOT_PROVISIONED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CaptureAssurance(StrEnum):
    CONTRACT_TEST_ONLY = "CONTRACT_TEST_ONLY"
    LOCAL_CAPTURE_ONLY = "LOCAL_CAPTURE_ONLY"


class SourceEventState(StrEnum):
    SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"
    NOT_PROVISIONED = "NOT_PROVISIONED"


class LifecycleStatus(StrEnum):
    CURRENT_LOCAL_OBSERVATION = "CURRENT_LOCAL_OBSERVATION"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REPLACED = "REPLACED"
    FUTURE = "FUTURE"


CLASS_BY_GATE = {gate: cls for cls, gate in CLASS_GATE.items()}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except BaseException:  # noqa: BLE001
            raise EvidenceCaptureError("invalid governed evidence capture") from None

    def __repr_args__(self):
        return [("redacted", True)]

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False):
        raw = BaseModel.model_dump(self, mode="python")
        if update:
            raw.update(update)
        del deep
        return type(self).model_validate(raw)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any):
        del _fields_set
        return cls.model_validate(values)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any):
        try:
            return super().model_validate(obj, **kwargs)
        except BaseException:  # noqa: BLE001
            raise EvidenceCaptureError("invalid governed evidence capture") from None

    @classmethod
    def model_validate_json(cls, value: str | bytes | bytearray, **kwargs: Any):
        try:
            return super().model_validate_json(value, **kwargs)
        except BaseException:  # noqa: BLE001
            raise EvidenceCaptureError("invalid governed evidence capture") from None


class EvidenceCaptureRecord(_Model):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    evidence_class: ObservationClass
    gate: EvidenceGate
    upstream_contract: Literal["material-observation-contract-test-v1"]
    upstream_artifact_digest: str = Field(pattern=SHA256)
    upstream_artifact_ref: str = Field(pattern=SHA256)
    provider_ref: str = Field(pattern=SAFE_REF)
    dataset_ref: str = Field(pattern=SAFE_REF)
    dataset_version_ref: str = Field(pattern=SAFE_REF)
    route_ref: None = None
    capability_id: None = None
    instrument_ref: None = None
    entity_ref: None = None
    policy_ref: str = Field(pattern=SAFE_REF)
    policy_version: None = None
    provenance_ref: str = Field(pattern=SHA256)
    trust_attestation_ref: None = None
    custody_ref: None = None
    observation_identity_ref: None = None
    source_event_state: Literal[SourceEventState.SYNTHETIC_TEST_ONLY]
    observed_at: dt.datetime
    available_at: dt.datetime
    captured_at: dt.datetime
    evaluated_at: dt.datetime
    expires_at: None = None
    revoked_at: None = None
    replacement_ref: None = None
    lifecycle_status: Literal[LifecycleStatus.CURRENT_LOCAL_OBSERVATION]
    payload_digest: str = Field(pattern=SHA256)
    counting_semantics: Literal["NOT_PRODUCTION_COUNTABLE"]
    assurance: Literal[CaptureAssurance.CONTRACT_TEST_ONLY]
    capture_state: Literal[CaptureState.INCOMPLETE]
    missing_bindings: tuple[str, ...]
    record_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        if CLASS_BY_GATE.get(self.gate) is not self.evidence_class:
            raise ValueError
        for value in (self.observed_at, self.available_at, self.captured_at, self.evaluated_at):
            _utc(value)
        if not self.observed_at <= self.available_at <= self.captured_at:
            raise ValueError
        if any(value > self.evaluated_at for value in (
            self.observed_at, self.available_at, self.captured_at
        )):
            raise ValueError
        required = (
            "capability_id", "custody_ref", "entity_or_instrument_ref",
            "observation_identity_ref", "policy_version", "route_ref", "trust_attestation_ref",
        )
        if self.missing_bindings != required:
            raise ValueError
        _hash(self, "record_digest")
        return self

    @property
    def production_countable(self) -> Literal[False]:
        return False


class CaptureConflict(_Model):
    semantic_identity: str = Field(pattern=SHA256)
    record_digests: tuple[str, ...]
    state: Literal[CaptureState.REVIEW_REQUIRED]
    conflict_digest: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def validate_value(self):
        if len(self.record_digests) < 2 or tuple(sorted(set(self.record_digests))) != self.record_digests:
            raise ValueError
        _hash(self, "conflict_digest")
        return self


class Step5CaptureProjection(_Model):
    capture_digest: str = Field(pattern=SHA256)
    eligible: Literal[False]
    state: Literal[CaptureState.NOT_PROVISIONED, CaptureState.REVIEW_REQUIRED]
    reason: Literal["CANONICAL_BINDINGS_NOT_PROVISIONED", "CAPTURE_CONFLICT"]
    observation: None = None
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]

    @model_validator(mode="after")
    def validate_value(self):
        if self.gate_states != tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate):
            raise ValueError
        return self


def capture_contract_test_observation(
    upstream: Any, *, available_at: dt.datetime, captured_at: dt.datetime,
    evaluated_at: dt.datetime,
) -> EvidenceCaptureRecord:
    """Capture only a validator-owned canonical fixture observation."""
    try:
        item = MaterializedObservedEvidence.model_validate(
            upstream.model_dump(mode="python") if isinstance(upstream, BaseModel) else upstream
        )
        manifest = canonical_gate_verification_manifest()
        expectation = {entry.gate: entry for entry in manifest.expectations}[item.gate]
        expected = (
            expectation.expectation_hash, expectation.provider_ref, expectation.dataset_ref,
            expectation.dataset_version_ref, expectation.adapter_ref,
            expectation.adapter_release_ref, expectation.evidence_policy_ref,
            expectation.receipt_policy_ref, item.material_digest,
        )
        actual = (
            item.expectation_hash, item.provider_ref, item.dataset_ref, item.dataset_version_ref,
            item.adapter_ref, item.adapter_release_ref, item.evidence_policy_ref,
            item.receipt_policy_ref, item.material_digest,
        )
        if actual != expected or item.material_digest not in expectation.accepted_artifact_digests:
            raise ValueError
        _utc(item.observed_at)
        _utc(available_at)
        _utc(captured_at)
        _utc(evaluated_at)
        if any(value > evaluated_at for value in (
            item.observed_at, available_at, captured_at
        )):
            raise EvidenceCaptureError("PIT_FUTURE_TIMESTAMP")
        if not item.observed_at <= available_at <= captured_at:
            raise EvidenceCaptureError("PIT_CHRONOLOGY_INVALID")
        values = {
            "evidence_class": CLASS_BY_GATE[item.gate], "gate": item.gate,
            "upstream_contract": item.version,
            "upstream_artifact_digest": item.observation_hash,
            "upstream_artifact_ref": item.observation_hash, "provider_ref": item.provider_ref,
            "dataset_ref": item.dataset_ref, "dataset_version_ref": item.dataset_version_ref,
            "policy_ref": item.evidence_policy_ref,
            "provenance_ref": typed_hash({"adapter": item.adapter_ref,
                                           "release": item.adapter_release_ref,
                                           "identity": item.adapter_identity_hash}),
            "source_event_state": SourceEventState.SYNTHETIC_TEST_ONLY,
            "observed_at": item.observed_at, "available_at": available_at,
            "captured_at": captured_at, "evaluated_at": evaluated_at,
            "lifecycle_status": LifecycleStatus.CURRENT_LOCAL_OBSERVATION,
            "payload_digest": item.material_digest,
            "counting_semantics": "NOT_PRODUCTION_COUNTABLE",
            "assurance": CaptureAssurance.CONTRACT_TEST_ONLY,
            "capture_state": CaptureState.INCOMPLETE,
            "missing_bindings": ("capability_id", "custody_ref", "entity_or_instrument_ref",
                                 "observation_identity_ref", "policy_version", "route_ref",
                                 "trust_attestation_ref"),
        }
        return _seal(EvidenceCaptureRecord, "record_digest", **values)
    except EvidenceCaptureError:
        raise
    except BaseException:  # noqa: BLE001
        raise EvidenceCaptureError("canonical upstream observation not provisioned") from None


def semantic_identity(record: Any) -> str:
    item = _rebuild(EvidenceCaptureRecord, record)
    return typed_hash({"gate": item.gate, "provider": item.provider_ref,
                       "dataset": item.dataset_ref, "observed_at": item.observed_at})


def canonicalize_captures(records: tuple[Any, ...]) -> tuple[tuple[EvidenceCaptureRecord, ...], tuple[CaptureConflict, ...]]:
    """Deduplicate aliases/replays and quarantine same-identity payload conflicts."""
    groups: dict[str, list[EvidenceCaptureRecord]] = {}
    for value in records:
        item = _rebuild(EvidenceCaptureRecord, value)
        groups.setdefault(semantic_identity(item), []).append(item)
    accepted: list[EvidenceCaptureRecord] = []
    conflicts: list[CaptureConflict] = []
    for identity, items in sorted(groups.items()):
        payloads = {item.payload_digest for item in items}
        if len(payloads) > 1:
            digests = tuple(sorted({item.record_digest for item in items}))
            conflicts.append(_seal(CaptureConflict, "conflict_digest", semantic_identity=identity,
                                   record_digests=digests, state=CaptureState.REVIEW_REQUIRED))
        else:
            accepted.append(min(items, key=lambda item: item.record_digest))
    return tuple(accepted), tuple(conflicts)


def project_to_step5(value: Any) -> Step5CaptureProjection:
    if isinstance(value, CaptureConflict):
        return Step5CaptureProjection(capture_digest=value.conflict_digest, eligible=False,
                                      state=CaptureState.REVIEW_REQUIRED,
                                      reason="CAPTURE_CONFLICT", observation=None,
                                      gate_states=_open_gates())
    item = _rebuild(EvidenceCaptureRecord, value)
    return Step5CaptureProjection(capture_digest=item.record_digest, eligible=False,
                                  state=CaptureState.NOT_PROVISIONED,
                                  reason="CANONICAL_BINDINGS_NOT_PROVISIONED", observation=None,
                                  gate_states=_open_gates())


class LocalEvidenceCaptureStore:
    """SQLite contract-test registry; local durability is not REAL custody or WORM."""

    assurance = CaptureAssurance.LOCAL_CAPTURE_ONLY

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS captures (digest TEXT PRIMARY KEY, body TEXT NOT NULL)")
            row = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
            if row is None:
                db.execute("INSERT INTO metadata VALUES ('schema', ?)", (STORE_SCHEMA_VERSION,))
            elif row[0] != STORE_SCHEMA_VERSION:
                raise EvidenceCaptureError("local capture store schema mismatch")
        self.load()

    def _connect(self):
        return sqlite3.connect(self._path)

    def put(self, record: Any) -> EvidenceCaptureRecord:
        item = _rebuild(EvidenceCaptureRecord, record)
        body = json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as db:
            row = db.execute("SELECT body FROM captures WHERE digest=?", (item.record_digest,)).fetchone()
            if row is not None and row[0] != body:
                raise EvidenceCaptureError("capture digest conflict")
            db.execute("INSERT OR IGNORE INTO captures VALUES (?, ?)", (item.record_digest, body))
        return item

    def load(self) -> tuple[EvidenceCaptureRecord, ...]:
        try:
            with self._connect() as db:
                rows = db.execute("SELECT digest, body FROM captures ORDER BY digest").fetchall()
            result = tuple(EvidenceCaptureRecord.model_validate_json(body) for _, body in rows)
            if any(digest != item.record_digest for (digest, _), item in zip(rows, result, strict=True)):
                raise ValueError
            return result
        except EvidenceCaptureError:
            raise
        except BaseException:  # noqa: BLE001
            raise EvidenceCaptureError("invalid local capture store") from None


def _open_gates():
    return tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate)


T = TypeVar("T", bound=_Model)


def _seal(model: type[T], hash_field: str, **values: Any) -> T:
    draft = BaseModel.model_construct.__func__(model, **values, **{hash_field: "0" * 64})
    values[hash_field] = typed_hash(draft.model_dump(mode="json", exclude={hash_field}))
    return model(**values)


def _rebuild(model: type[T], value: Any) -> T:
    try:
        raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
        return model.model_validate(raw)
    except EvidenceCaptureError:
        raise
    except BaseException:  # noqa: BLE001
        raise EvidenceCaptureError("invalid governed evidence capture") from None


def _hash(value: BaseModel, field: str) -> None:
    if typed_hash(value.model_dump(mode="json", exclude={field})) != getattr(value, field):
        raise ValueError


def _utc(value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError
