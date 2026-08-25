from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawSnapshotError(RuntimeError):
    """Raised when raw provider evidence cannot be preserved or verified."""


class RawSnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["raw-provider-snapshot-v2"] = "raw-provider-snapshot-v2"
    acquisition_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    provider: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    request_url: str = Field(min_length=1)
    as_of: datetime.datetime
    acquired_at: datetime.datetime
    content_type: str = Field(min_length=1)
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_file: str = Field(min_length=1)
    licensing_status: Literal["PENDING_LEGAL_APPROVAL", "APPROVED"]
    retention_policy: str = Field(min_length=1)
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False

    @field_validator("as_of", "acquired_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return value.astimezone(datetime.UTC)

    @property
    def fetched_at(self) -> datetime.datetime:
        return self.acquired_at


_STORE_LOCK = threading.RLock()


def _atomic_create(path: Path, content: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            created = True
        except FileExistsError:
            created = False
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return created
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class RawSnapshotStore:
    """Atomic logical immutability on local FS; this is not WORM/object lock."""

    root: Path

    def preserve(
        self, *, provider: str, resource: str, request_url: str, payload: bytes,
        content_type: str, licensing_status: Literal["PENDING_LEGAL_APPROVAL", "APPROVED"],
        retention_policy: str, as_of: datetime.datetime | None = None,
        acquired_at: datetime.datetime | None = None,
        fetched_at: datetime.datetime | None = None,
    ) -> RawSnapshotManifest:
        acquired = acquired_at or fetched_at
        cutoff = as_of or acquired
        if acquired is None or cutoff is None:
            raise RawSnapshotError("as_of and acquired_at are required")
        for name, value in (("as_of", cutoff), ("acquired_at", acquired)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise RawSnapshotError(f"{name} must be timezone-aware")
        if not payload:
            raise RawSnapshotError("refusing to preserve an empty provider response")
        digest = hashlib.sha256(payload).hexdigest()
        content_dir = self.root / provider / "content" / digest[:2] / digest
        payload_path = content_dir / "payload.json"
        content_path = content_dir / "content.json"
        content = {"schema_version": "raw-provider-content-v1", "byte_length": len(payload),
                   "content_type": content_type, "payload_file": "payload.json", "sha256": digest}
        content_bytes = (json.dumps(content, indent=2, sort_keys=True) + "\n").encode()
        acquisition_id = uuid.uuid4().hex
        event_dir = self.root / provider / "acquisitions"
        manifest = RawSnapshotManifest(
            acquisition_id=acquisition_id, provider=provider, resource=resource,
            request_url=request_url, as_of=cutoff, acquired_at=acquired,
            content_type=content_type, byte_length=len(payload), sha256=digest,
            payload_file=os.path.relpath(payload_path, event_dir),
            licensing_status=licensing_status, retention_policy=retention_policy,
        )
        serialized = (json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode()
        event_path = event_dir / f"{acquisition_id}.json"
        with _STORE_LOCK:
            if not _atomic_create(payload_path, payload) and payload_path.read_bytes() != payload:
                raise RawSnapshotError("content-address collision or mutated raw snapshot")
            if not _atomic_create(content_path, content_bytes) and content_path.read_bytes() != content_bytes:
                raise RawSnapshotError("content manifest conflict")
            if not _atomic_create(event_path, serialized):
                raise RawSnapshotError("acquisition event collision")
            self.verify(event_path)
        return manifest

    @staticmethod
    def verify(manifest_path: Path) -> RawSnapshotManifest:
        try:
            manifest = RawSnapshotManifest.model_validate_json(manifest_path.read_text("utf-8"))
            payload = (manifest_path.parent / manifest.payload_file).resolve(strict=True).read_bytes()
        except (OSError, ValueError) as error:
            raise RawSnapshotError("raw snapshot manifest or payload is invalid") from error
        if len(payload) != manifest.byte_length:
            raise RawSnapshotError("raw snapshot byte length mismatch")
        if hashlib.sha256(payload).hexdigest() != manifest.sha256:
            raise RawSnapshotError("raw snapshot checksum mismatch")
        return manifest
