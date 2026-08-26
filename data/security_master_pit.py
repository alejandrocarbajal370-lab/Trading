from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from governance.canonical import typed_hash

SECURITY_MASTER_PIT_VERSION = "security-master-pit-v1"
CONSTITUENTS_PIT_VERSION = "historical-constituents-pit-v1"
PLACEHOLDERS = frozenset({"", "nan", "none", "null", "n/a", "na", "unknown", "placeholder"})


class SecurityMasterPITError(ValueError):
    """PIT identity or membership evidence is incomplete, ambiguous, or stale."""


def _text(value: str, field: str) -> str:
    text = str(value).strip()
    if text.casefold() in PLACEHOLDERS:
        raise ValueError(f"{field} is missing or a placeholder")
    return text


def _aware(value: datetime.datetime | None, field: str) -> datetime.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(datetime.UTC)


class ProviderIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    version: str
    licensing: str
    retention: str
    state: Literal["PARTIAL_REAL_PROVIDER", "OPEN_EXTERNAL"]

    @field_validator("name", "version", "licensing", "retention")
    @classmethod
    def complete(cls, value: str, info) -> str:
        return _text(value, info.field_name)


class SecurityIdentityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["security-master-pit-v1"] = SECURITY_MASTER_PIT_VERSION
    permanent_id: str
    issuer_id: str | None = None
    symbol: str
    exchange: str
    listing_start: datetime.datetime
    listing_end: datetime.datetime | None = None
    delisting_status: Literal["ACTIVE", "DELISTED", "UNKNOWN"]
    delisting_reason: str | None = None
    share_class: str
    security_type: str
    canonical_cik: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    cik_lineage: str | None = None
    source: str
    source_record_id: str
    available_at: datetime.datetime
    valid_from: datetime.datetime
    valid_to: datetime.datetime | None = None
    relationship_type: Literal[
        "SAME_SECURITY", "MERGER_PREDECESSOR", "MERGER_SUCCESSOR", "SPINOFF_PARENT", "SPINOFF_CHILD"
    ] | None = None
    related_permanent_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "permanent_id", "symbol", "exchange", "share_class", "security_type", "source",
        "source_record_id",
    )
    @classmethod
    def required_text(cls, value: str, info) -> str:
        return _text(value, info.field_name)

    @field_validator("issuer_id", "cik_lineage", "delisting_reason", "related_permanent_id")
    @classmethod
    def optional_text(cls, value: str | None, info) -> str | None:
        return None if value is None else _text(value, info.field_name)

    @field_validator("listing_start", "listing_end", "available_at", "valid_from", "valid_to")
    @classmethod
    def timestamps(cls, value: datetime.datetime | None, info) -> datetime.datetime | None:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def coherent(self) -> SecurityIdentityRecord:
        if self.listing_end is not None and self.listing_end <= self.listing_start:
            raise ValueError("listing validity window is invalid")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("record validity window is invalid")
        if (self.canonical_cik is None) != (self.cik_lineage is None):
            raise ValueError("CIK and CIK lineage must be present together")
        if self.canonical_cik == "0000000000":
            raise ValueError("CIK is a placeholder")
        if (self.relationship_type is None) != (self.related_permanent_id is None):
            raise ValueError("structural relationship is incomplete")
        return self


class ConstituentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["historical-constituents-pit-v1"] = CONSTITUENTS_PIT_VERSION
    universe_id: str
    permanent_id: str
    entry_at: datetime.datetime
    exit_at: datetime.datetime | None = None
    source: str
    source_record_id: str
    available_at: datetime.datetime
    valid_from: datetime.datetime
    valid_to: datetime.datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("universe_id", "permanent_id", "source", "source_record_id")
    @classmethod
    def required_text(cls, value: str, info) -> str:
        return _text(value, info.field_name)

    @field_validator("entry_at", "exit_at", "available_at", "valid_from", "valid_to")
    @classmethod
    def timestamps(cls, value: datetime.datetime | None, info) -> datetime.datetime | None:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def coherent(self) -> ConstituentRecord:
        if self.exit_at is not None and self.exit_at <= self.entry_at:
            raise ValueError("membership validity window is invalid")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("membership record validity window is invalid")
        return self


class PITUniverseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_version: Literal["security-master-constituents-artifact-v1"] = (
        "security-master-constituents-artifact-v1"
    )
    as_of: datetime.datetime
    universe_id: str
    provider: ProviderIdentity
    source_hashes: tuple[str, ...]
    permanent_identities: tuple[str, ...]
    membership_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    security_master_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cik_mapping_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_code_fingerprint: str
    historical_completeness: Literal[False] = False
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"artifact_hash"})

    @model_validator(mode="after")
    def sealed(self) -> PITUniverseArtifact:
        if tuple(sorted(self.permanent_identities)) != self.permanent_identities:
            raise ValueError("permanent identities are not canonical")
        if tuple(sorted(self.source_hashes)) != self.source_hashes:
            raise ValueError("source hashes are not canonical")
        if typed_hash(self.identity_payload()) != self.artifact_hash:
            raise ValueError("PIT artifact hash mismatch")
        return self


@dataclass(frozen=True)
class PITReconstruction:
    securities: tuple[SecurityIdentityRecord, ...]
    memberships: tuple[ConstituentRecord, ...]
    artifact: PITUniverseArtifact


def _overlap(start_a, end_a, start_b, end_b) -> bool:
    ceiling = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    return start_a < (end_b or ceiling) and start_b < (end_a or ceiling)


def reconstruct_pit_universe(
    *, security_records: list[SecurityIdentityRecord], constituent_records: list[ConstituentRecord],
    universe_id: str, as_of: datetime.datetime, provider: ProviderIdentity,
    source_hashes: tuple[str, ...], runtime_code_fingerprint: str, require_cik: bool = True,
) -> PITReconstruction:
    cutoff = _aware(as_of, "as_of")
    assert cutoff is not None
    universe_id = _text(universe_id, "universe_id")
    _text(runtime_code_fingerprint, "runtime_code_fingerprint")
    if not source_hashes or any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in source_hashes):
        raise SecurityMasterPITError("source hashes are missing or malformed")

    # Reject ambiguous source histories, not merely ambiguity among currently active rows.
    for left_index, left in enumerate(security_records):
        for right in security_records[left_index + 1 :]:
            if left.permanent_id == right.permanent_id and _overlap(
                left.valid_from, left.valid_to, right.valid_from, right.valid_to
            ) and (left.symbol, left.exchange, left.canonical_cik) != (
                right.symbol, right.exchange, right.canonical_cik
            ):
                raise SecurityMasterPITError("overlapping conflicting security mappings")
            if left.source == right.source and left.source_record_id == right.source_record_id:
                raise SecurityMasterPITError("duplicate source record identity")

    memberships = [
        row for row in constituent_records
        if row.universe_id == universe_id and row.entry_at <= cutoff
        and (row.exit_at is None or cutoff < row.exit_at)
        and row.valid_from <= cutoff and (row.valid_to is None or cutoff < row.valid_to)
    ]
    if any(row.available_at > cutoff or row.valid_from > cutoff for row in memberships):
        raise SecurityMasterPITError("future membership evidence relative to as_of")
    member_ids = [row.permanent_id for row in memberships]
    if len(member_ids) != len(set(member_ids)):
        raise SecurityMasterPITError("duplicate or conflicting membership identity")
    if not member_ids:
        raise SecurityMasterPITError("membership cannot be demonstrated at as_of")

    active = [
        row for row in security_records if row.permanent_id in set(member_ids)
        and row.listing_start <= cutoff and (row.listing_end is None or cutoff < row.listing_end)
        and row.valid_from <= cutoff and (row.valid_to is None or cutoff < row.valid_to)
    ]
    if any(row.available_at > cutoff or row.valid_from > cutoff for row in active):
        raise SecurityMasterPITError("future security mapping relative to as_of")
    by_id: dict[str, list[SecurityIdentityRecord]] = {}
    for row in active:
        by_id.setdefault(row.permanent_id, []).append(row)
    if set(by_id) != set(member_ids) or any(len(rows) != 1 for rows in by_id.values()):
        raise SecurityMasterPITError("membership identity cannot be uniquely demonstrated")
    securities = tuple(sorted((rows[0] for rows in by_id.values()), key=lambda row: row.permanent_id))
    if require_cik and any(row.canonical_cik is None for row in securities):
        raise SecurityMasterPITError("canonical CIK is required but missing")

    memberships_tuple = tuple(sorted(memberships, key=lambda row: row.permanent_id))
    membership_hash = typed_hash([row.model_dump(mode="python") for row in memberships_tuple])
    master_hash = typed_hash([row.model_dump(mode="python") for row in securities])
    cik_hash = typed_hash([(row.permanent_id, row.canonical_cik) for row in securities])
    values = {
        "as_of": cutoff,
        "universe_id": universe_id,
        "provider": provider,
        "source_hashes": tuple(sorted(source_hashes)),
        "permanent_identities": tuple(row.permanent_id for row in securities),
        "membership_hash": membership_hash,
        "security_master_hash": master_hash,
        "cik_mapping_hash": cik_hash,
        "runtime_code_fingerprint": runtime_code_fingerprint,
    }
    draft = PITUniverseArtifact.model_construct(**values, artifact_hash="0" * 64)
    artifact = PITUniverseArtifact(**values, artifact_hash=typed_hash(draft.identity_payload()))
    return PITReconstruction(securities, memberships_tuple, artifact)


def universe_source_records(
    reconstruction: PITReconstruction, observations: pd.DataFrame
) -> pd.DataFrame:
    """Bind PIT identities to existing Universe inputs; symbols always come from the master."""
    required = {
        "permanent_id", "asset_type", "country", "region", "sector", "industry", "market_cap",
        "market_cap_currency", "average_volume", "average_dollar_volume", "source_timestamp",
        "available_at",
    }
    if missing := sorted(required - set(observations.columns)):
        raise SecurityMasterPITError(f"universe observations missing fields: {', '.join(missing)}")
    frame = observations.copy()
    if frame["permanent_id"].duplicated().any():
        raise SecurityMasterPITError("duplicate permanent ID conflict in universe observations")
    expected = set(reconstruction.artifact.permanent_identities)
    if set(frame["permanent_id"]) != expected:
        raise SecurityMasterPITError("universe observations do not exactly cover PIT membership")
    identity = pd.DataFrame(
        [{"permanent_id": row.permanent_id, "symbol": row.symbol, "exchange": row.exchange,
          "listing_date": row.listing_start, "source": row.source} for row in reconstruction.securities]
    )
    frame = frame.drop(columns=[column for column in ("symbol", "exchange", "listing_date", "source") if column in frame])
    return identity.merge(frame, on="permanent_id", validate="one_to_one")
