from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawSnapshotError(RuntimeError):
    """Raised when raw provider evidence cannot be preserved or verified."""


class RawSnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["raw-provider-snapshot-v1"] = "raw-provider-snapshot-v1"
    provider: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    request_url: str = Field(min_length=1)
    fetched_at: datetime.datetime
    content_type: str = Field(min_length=1)
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_file: str = Field(min_length=1)
    licensing_status: Literal["PENDING_LEGAL_APPROVAL", "APPROVED"]
    retention_policy: str = Field(min_length=1)
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False

    @field_validator("fetched_at")
    @classmethod
    def fetched_at_is_aware(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value


@dataclass(frozen=True)
class RawSnapshotStore:
    """Append-only content-addressed storage for exact provider response bytes."""

    root: Path

    def preserve(
        self,
        *,
        provider: str,
        resource: str,
        request_url: str,
        payload: bytes,
        fetched_at: datetime.datetime,
        content_type: str,
        licensing_status: Literal["PENDING_LEGAL_APPROVAL", "APPROVED"],
        retention_policy: str,
    ) -> RawSnapshotManifest:
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise RawSnapshotError("fetched_at must be timezone-aware")
        if not payload:
            raise RawSnapshotError("refusing to preserve an empty provider response")
        digest = hashlib.sha256(payload).hexdigest()
        directory = self.root / provider / digest[:2] / digest
        payload_name = "payload.json"
        manifest_name = "manifest.json"
        manifest = RawSnapshotManifest(
            provider=provider,
            resource=resource,
            request_url=request_url,
            fetched_at=fetched_at,
            content_type=content_type,
            byte_length=len(payload),
            sha256=digest,
            payload_file=payload_name,
            licensing_status=licensing_status,
            retention_policy=retention_policy,
        )
        directory.mkdir(parents=True, exist_ok=True)
        payload_path = directory / payload_name
        manifest_path = directory / manifest_name
        if payload_path.exists() and payload_path.read_bytes() != payload:
            raise RawSnapshotError("content-address collision or mutated raw snapshot")
        if not payload_path.exists():
            payload_path.write_bytes(payload)
        serialized = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != serialized:
            raise RawSnapshotError("raw snapshot manifest is immutable")
        if not manifest_path.exists():
            manifest_path.write_text(serialized, encoding="utf-8")
        self.verify(manifest_path)
        return manifest

    @staticmethod
    def verify(manifest_path: Path) -> RawSnapshotManifest:
        manifest = RawSnapshotManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        payload = (manifest_path.parent / manifest.payload_file).read_bytes()
        if len(payload) != manifest.byte_length:
            raise RawSnapshotError("raw snapshot byte length mismatch")
        if hashlib.sha256(payload).hexdigest() != manifest.sha256:
            raise RawSnapshotError("raw snapshot checksum mismatch")
        return manifest
