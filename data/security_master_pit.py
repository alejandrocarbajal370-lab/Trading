from __future__ import annotations

import datetime
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from governance.canonical import typed_hash

SECURITY_MASTER_PIT_VERSION = "security-master-pit-v3"
CONSTITUENTS_PIT_VERSION = "historical-constituents-pit-v3"
ARTIFACT_VERSION = "security-master-constituents-artifact-v3"
SEC_BRIDGE_VERSION = "phase7b-sec-mapping-bridge-v2"
LISTING_POLICY_VERSION = "listing-state-half-open-v1"
SYMBOL_IDENTITY_POLICY_VERSION = "us-symbology-nfkc-uppercase-ascii-v2"
RELATIONSHIP_POLICY_VERSION = "structural-lineage-paired-semantics-v2"
BITEMPORAL_POLICY_VERSION = "effective-knowledge-supersession-v2"
COVERAGE_MANIFEST_VERSION = "historical-provider-coverage-v3"
PLACEHOLDERS = frozenset({"", "nan", "none", "null", "n/a", "na", "unknown", "placeholder"})
HASH_PATTERN = r"^[0-9a-f]{64}$"


class SecurityMasterPITError(ValueError):
    """PIT identity or membership evidence is incomplete, ambiguous, or stale."""


def _text(value: object, field: str) -> str:
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    if missing:
        raise ValueError(f"{field} is missing")
    text = str(value).strip()
    if text.casefold() in PLACEHOLDERS:
        raise ValueError(f"{field} is missing or a placeholder")
    return text


def _canonical_us_text(value: object, field: str) -> str:
    text = unicodedata.normalize("NFKC", _text(value, field)).strip().upper()
    if not text.isascii():
        raise ValueError(f"{field} must use ASCII under the US symbology policy")
    return text


def _aware(value: datetime.datetime | None, field: str) -> datetime.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(datetime.UTC)


def _overlap(start_a, end_a, start_b, end_b) -> bool:
    ceiling = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    return start_a < (end_b or ceiling) and start_b < (end_a or ceiling)


class CoverageCompleteness(StrEnum):
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    VERIFIED_WITHIN_DECLARED_SCOPE = "VERIFIED_WITHIN_DECLARED_SCOPE"


class ProviderIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    version: str
    licensing: str
    retention: str
    state: Literal["PARTIAL_REAL_PROVIDER", "OPEN_EXTERNAL"]

    @field_validator("name", "version", "licensing", "retention", mode="before")
    @classmethod
    def complete(cls, value: object, info) -> str:
        return _text(value, info.field_name)


class SourceEvidence(BaseModel):
    """Content-addressed upstream material; a hash without material is not evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_identity: str
    material: dict[str, object]
    source_hash: str = Field(pattern=HASH_PATTERN)

    @field_validator("source_identity", mode="before")
    @classmethod
    def valid_identity(cls, value: object) -> str:
        return _text(value, "source_identity")

    @model_validator(mode="after")
    def sealed(self) -> SourceEvidence:
        if typed_hash(self.material) != self.source_hash:
            raise ValueError("source evidence hash mismatch")
        return self


class CoverageEvidenceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sequence_number: int = Field(ge=1)
    snapshot_identity: str
    raw_evidence: dict[str, object]
    evidence_material: dict[str, object]
    raw_source_hash: str = Field(pattern=HASH_PATTERN)
    evidence_hash: str = Field(pattern=HASH_PATTERN)
    effective_from: datetime.datetime
    effective_to: datetime.datetime
    available_at: datetime.datetime
    acquired_at: datetime.datetime
    source: str
    provider_identity: str

    @field_validator("snapshot_identity", "source", "provider_identity", mode="before")
    @classmethod
    def text_fields(cls, value: object, info) -> str:
        return _text(value, info.field_name)

    @field_validator("effective_from", "effective_to", "available_at", "acquired_at")
    @classmethod
    def time_fields(cls, value: datetime.datetime, info) -> datetime.datetime:
        result = _aware(value, info.field_name)
        assert result is not None
        return result

    @model_validator(mode="after")
    def coherent(self) -> CoverageEvidenceEntry:
        if self.effective_to <= self.effective_from:
            raise ValueError("coverage evidence window is invalid")
        if self.available_at > self.acquired_at:
            raise ValueError("coverage evidence cannot be known after acquisition")
        if typed_hash(self.raw_evidence) != self.raw_source_hash:
            raise ValueError("coverage raw evidence hash mismatch")
        if typed_hash(self.evidence_material) != self.evidence_hash:
            raise ValueError("coverage evidence material hash mismatch")
        if self.evidence_material.get("raw_source_hash") != self.raw_source_hash:
            raise ValueError("coverage evidence material is not bound to raw evidence")
        if self.evidence_material.get("snapshot_identity") != self.snapshot_identity:
            raise ValueError("coverage evidence material is not bound to snapshot identity")
        return self


class ProviderCoverageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["historical-provider-coverage-v3"] = COVERAGE_MANIFEST_VERSION
    provider: str
    dataset: str
    dataset_version: str
    universe_scope: str
    temporal_coverage_from: datetime.datetime
    temporal_coverage_to: datetime.datetime
    entries: tuple[CoverageEvidenceEntry, ...] = ()
    completeness_state: CoverageCompleteness = CoverageCompleteness.UNKNOWN
    correction_policy: str
    revision_policy: str
    licensing_state: str
    retention_state: str
    acquired_at: datetime.datetime
    available_at: datetime.datetime
    current_only: bool = True
    manifest_hash: str = Field(pattern=HASH_PATTERN)

    @field_validator(
        "provider",
        "dataset",
        "dataset_version",
        "universe_scope",
        "correction_policy",
        "revision_policy",
        "licensing_state",
        "retention_state",
        mode="before",
    )
    @classmethod
    def text_fields(cls, value: object, info) -> str:
        return _text(value, info.field_name)

    @field_validator(
        "temporal_coverage_from", "temporal_coverage_to", "acquired_at", "available_at"
    )
    @classmethod
    def time_fields(cls, value: datetime.datetime, info) -> datetime.datetime:
        result = _aware(value, info.field_name)
        assert result is not None
        return result

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"manifest_hash"})

    @model_validator(mode="after")
    def evidence_bound(self) -> ProviderCoverageManifest:
        if self.temporal_coverage_to <= self.temporal_coverage_from:
            raise ValueError("coverage window is invalid")
        if self.available_at > self.acquired_at:
            raise ValueError("available_at cannot follow acquired_at")
        canonical = tuple(sorted(self.entries, key=lambda item: item.sequence_number))
        if canonical != self.entries:
            raise ValueError("coverage evidence entries are not canonical")
        sequences = tuple(item.sequence_number for item in self.entries)
        identities = tuple(item.snapshot_identity for item in self.entries)
        raw_hashes = tuple(item.raw_source_hash for item in self.entries)
        evidence_hashes = tuple(item.evidence_hash for item in self.entries)
        if len(sequences) != len(set(sequences)) or len(identities) != len(set(identities)):
            raise ValueError("coverage evidence identity must be one-to-one")
        if len(raw_hashes) != len(set(raw_hashes)) or len(evidence_hashes) != len(
            set(evidence_hashes)
        ):
            raise ValueError("coverage evidence hashes must be one-to-one")
        expected = tuple(range(1, len(sequences) + 1))
        verified = self.completeness_state == CoverageCompleteness.VERIFIED_WITHIN_DECLARED_SCOPE
        if verified and (self.current_only or not self.entries or sequences != expected):
            raise ValueError(
                "verified coverage requires evidence and a gap-free historical sequence"
            )
        for index, entry in enumerate(self.entries):
            if (
                entry.effective_from < self.temporal_coverage_from
                or entry.effective_to > self.temporal_coverage_to
            ):
                raise ValueError("coverage evidence is outside declared scope")
            if index and entry.effective_from < self.entries[index - 1].effective_to:
                raise ValueError("coverage evidence windows overlap")
            if verified and index and entry.effective_from != self.entries[index - 1].effective_to:
                raise ValueError("verified coverage contains a temporal gap")
        if verified and (
            self.entries[0].effective_from != self.temporal_coverage_from
            or self.entries[-1].effective_to != self.temporal_coverage_to
        ):
            raise ValueError("verified coverage does not exactly span declared scope")
        if typed_hash(self.identity_payload()) != self.manifest_hash:
            raise ValueError("coverage manifest hash mismatch")
        return self

    @property
    def ready_within_declared_scope(self) -> bool:
        return self.completeness_state == CoverageCompleteness.VERIFIED_WITHIN_DECLARED_SCOPE


class SecurityIdentityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["security-master-pit-v3"] = SECURITY_MASTER_PIT_VERSION
    permanent_id: str
    issuer_id: str
    symbol: str
    exchange: str
    listing_start: datetime.datetime
    listing_end: datetime.datetime | None = None
    delisting_status: Literal["ACTIVE", "DELISTED"]
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
    relationship_type: (
        Literal["MERGER_PREDECESSOR", "MERGER_SUCCESSOR", "SPINOFF_PARENT", "SPINOFF_CHILD"] | None
    ) = None
    related_permanent_id: str | None = None
    relationship_available_at: datetime.datetime | None = None
    relationship_effective_at: datetime.datetime | None = None
    revision_id: str = "ORIGINAL"
    supersedes_source_record_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "permanent_id",
        "issuer_id",
        "symbol",
        "exchange",
        "share_class",
        "security_type",
        "source",
        "source_record_id",
        "revision_id",
        mode="before",
    )
    @classmethod
    def required_text(cls, value: object, info) -> str:
        return _text(value, info.field_name)

    @field_validator("symbol", "exchange", "share_class", "security_type", mode="before")
    @classmethod
    def canonical_symbology(cls, value: object, info) -> str:
        return _canonical_us_text(value, info.field_name)

    @field_validator(
        "cik_lineage",
        "delisting_reason",
        "related_permanent_id",
        "supersedes_source_record_id",
        mode="before",
    )
    @classmethod
    def optional_text(cls, value: object | None, info) -> str | None:
        return None if value is None else _text(value, info.field_name)

    @field_validator(
        "listing_start",
        "listing_end",
        "available_at",
        "valid_from",
        "valid_to",
        "relationship_available_at",
        "relationship_effective_at",
    )
    @classmethod
    def timestamps(cls, value: datetime.datetime | None, info) -> datetime.datetime | None:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def coherent(self) -> SecurityIdentityRecord:
        if self.listing_end is not None and self.listing_end <= self.listing_start:
            raise ValueError("listing validity window is invalid")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("record validity window is invalid")
        if self.valid_from < self.listing_start:
            raise ValueError("mapping validity cannot precede listing window")
        if (
            self.valid_to is not None
            and self.listing_end is not None
            and self.valid_to > self.listing_end
        ):
            raise ValueError("mapping validity cannot extend beyond listing window")
        if self.delisting_status == "DELISTED" and self.listing_end is None:
            raise ValueError("DELISTED requires listing_end")
        if self.delisting_status == "ACTIVE" and self.listing_end is not None:
            raise ValueError("ACTIVE cannot have listing_end")
        if (self.canonical_cik is None) != (self.cik_lineage is None):
            raise ValueError("CIK and CIK lineage must be present together")
        if self.canonical_cik == "0000000000":
            raise ValueError("CIK is a placeholder")
        if self.related_permanent_id == self.permanent_id:
            raise ValueError("structural relationship self-link is forbidden")
        relationship = (
            self.relationship_type,
            self.related_permanent_id,
            self.relationship_available_at,
            self.relationship_effective_at,
        )
        if any(item is None for item in relationship) != all(item is None for item in relationship):
            raise ValueError("structural relationship is incomplete")
        if (
            self.relationship_available_at is not None
            and self.relationship_available_at < self.available_at
        ):
            raise ValueError("relationship cannot be known before its source record")
        if (
            self.relationship_effective_at is not None
            and self.relationship_effective_at < self.listing_start
        ):
            raise ValueError("relationship effective time precedes source listing")
        return self

    @property
    def symbology_key(self) -> tuple[str, str, str, str]:
        return (self.symbol, self.exchange, self.share_class, self.security_type)


class ConstituentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["historical-constituents-pit-v3"] = CONSTITUENTS_PIT_VERSION
    universe_id: str
    permanent_id: str
    entry_at: datetime.datetime
    exit_at: datetime.datetime | None = None
    source: str
    source_record_id: str
    available_at: datetime.datetime
    valid_from: datetime.datetime
    valid_to: datetime.datetime | None = None
    revision_id: str = "ORIGINAL"
    supersedes_source_record_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "universe_id", "permanent_id", "source", "source_record_id", "revision_id", mode="before"
    )
    @classmethod
    def required_text(cls, value: object, info) -> str:
        return _text(value, info.field_name)

    @field_validator("supersedes_source_record_id", mode="before")
    @classmethod
    def optional_text(cls, value: object | None, info) -> str | None:
        return None if value is None else _text(value, info.field_name)

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
        if self.valid_from < self.entry_at:
            raise ValueError("membership record validity cannot precede entry")
        return self


class PITUniverseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_version: Literal["security-master-constituents-artifact-v3"] = ARTIFACT_VERSION
    security_master_version: Literal["security-master-pit-v3"] = SECURITY_MASTER_PIT_VERSION
    constituents_version: Literal["historical-constituents-pit-v3"] = CONSTITUENTS_PIT_VERSION
    listing_policy_version: Literal["listing-state-half-open-v1"] = LISTING_POLICY_VERSION
    symbol_identity_policy_version: Literal["us-symbology-nfkc-uppercase-ascii-v2"] = (
        SYMBOL_IDENTITY_POLICY_VERSION
    )
    relationship_policy_version: Literal["structural-lineage-paired-semantics-v2"] = (
        RELATIONSHIP_POLICY_VERSION
    )
    bitemporal_policy_version: Literal["effective-knowledge-supersession-v2"] = (
        BITEMPORAL_POLICY_VERSION
    )
    as_of: datetime.datetime
    universe_id: str
    provider: ProviderIdentity
    coverage_manifest_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    source_hashes: tuple[str, ...]
    permanent_identities: tuple[str, ...]
    membership_hash: str = Field(pattern=HASH_PATTERN)
    security_master_hash: str = Field(pattern=HASH_PATTERN)
    cik_mapping_hash: str = Field(pattern=HASH_PATTERN)
    relationship_hash: str = Field(pattern=HASH_PATTERN)
    runtime_code_fingerprint: str
    historical_completeness: Literal[False] = False
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    artifact_hash: str = Field(pattern=HASH_PATTERN)

    @field_validator("as_of")
    @classmethod
    def aware_as_of(cls, value: datetime.datetime) -> datetime.datetime:
        result = _aware(value, "as_of")
        assert result is not None
        return result

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


class Phase7BSecMappingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permanent_id: str
    issuer_id: str
    canonical_cik: str = Field(pattern=r"^[0-9]{10}$")
    cik_lineage: str
    source: str
    source_record_id: str
    available_at: datetime.datetime
    valid_from: datetime.datetime
    valid_to: datetime.datetime | None = None
    share_class: str
    security_type: str


def _cik_mapping_payload(rows: tuple[SecurityIdentityRecord, ...] | list[SecurityIdentityRecord]):
    return [
        {
            "permanent_id": row.permanent_id,
            "issuer_id": row.issuer_id,
            "canonical_cik": row.canonical_cik,
            "cik_lineage": row.cik_lineage,
            "source": row.source,
            "source_record_id": row.source_record_id,
            "available_at": row.available_at,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
            "share_class": row.share_class,
            "security_type": row.security_type,
        }
        for row in rows
    ]


def _relationship_payload(rows: tuple[SecurityIdentityRecord, ...] | list[SecurityIdentityRecord]):
    return [
        {
            "permanent_id": row.permanent_id,
            "type": row.relationship_type,
            "related_permanent_id": row.related_permanent_id,
            "available_at": row.relationship_available_at,
            "effective_at": row.relationship_effective_at,
            "source": row.source,
            "source_record_id": row.source_record_id,
            "revision_id": row.revision_id,
            "policy": RELATIONSHIP_POLICY_VERSION,
        }
        for row in rows
        if row.relationship_type is not None
    ]


class Phase7BBridgeProofEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proof_version: Literal["phase7b-artifact-proof-v1"] = "phase7b-artifact-proof-v1"
    artifact: PITUniverseArtifact
    security_records: tuple[SecurityIdentityRecord, ...]
    security_revision_records: tuple[SecurityIdentityRecord, ...]
    membership_records: tuple[ConstituentRecord, ...]
    coverage_manifest: ProviderCoverageManifest | None = None
    source_evidence: tuple[SourceEvidence, ...]

    @model_validator(mode="after")
    def verify_content_commitments(self) -> Phase7BBridgeProofEnvelope:
        security_payload = [row.model_dump(mode="python") for row in self.security_revision_records]
        membership_payload = [row.model_dump(mode="python") for row in self.membership_records]
        # Re-run the semantic validators as well as the byte commitments. A fully
        # resealed but invalid proof must not become valid merely by recomputing hashes.
        _validate_record_sets(list(self.security_revision_records))
        _validate_membership_chains(list(self.membership_records))
        _validate_security_graph(list(self.security_revision_records), self.artifact.as_of)
        ids = tuple(row.permanent_id for row in self.security_records)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("proof security records are not unique and canonical")
        if self.artifact.permanent_identities != ids:
            raise ValueError("proof identities do not match artifact")
        if not all(row in self.security_revision_records for row in self.security_records):
            raise ValueError("selected security record is absent from revision proof")
        if typed_hash(security_payload) != self.artifact.security_master_hash:
            raise ValueError("proof security-master commitment mismatch")
        if typed_hash(membership_payload) != self.artifact.membership_hash:
            raise ValueError("proof membership commitment mismatch")
        if (
            typed_hash(_cik_mapping_payload(self.security_records))
            != self.artifact.cik_mapping_hash
        ):
            raise ValueError("proof CIK mapping commitment mismatch")
        if (
            typed_hash(_relationship_payload(self.security_revision_records))
            != self.artifact.relationship_hash
        ):
            raise ValueError("proof relationship commitment mismatch")
        proved_coverage = self.coverage_manifest.manifest_hash if self.coverage_manifest else None
        if proved_coverage != self.artifact.coverage_manifest_hash:
            raise ValueError("proof coverage commitment mismatch")
        if self.coverage_manifest is not None:
            ProviderCoverageManifest.model_validate(
                self.coverage_manifest.model_dump(mode="python")
            )
        source_ids = tuple(item.source_identity for item in self.source_evidence)
        source_hashes = tuple(item.source_hash for item in self.source_evidence)
        if source_ids != tuple(sorted(source_ids)) or len(source_ids) != len(set(source_ids)):
            raise ValueError("source evidence is not unique and canonical")
        if tuple(sorted(source_hashes)) != self.artifact.source_hashes:
            raise ValueError("source evidence differs from artifact commitments")
        recomputed = reconstruct_pit_universe(
            security_records=list(self.security_revision_records),
            constituent_records=list(self.membership_records),
            universe_id=self.artifact.universe_id,
            as_of=self.artifact.as_of,
            provider=self.artifact.provider,
            source_evidence=self.source_evidence,
            runtime_code_fingerprint=self.artifact.runtime_code_fingerprint,
            require_cik=True,
            coverage_manifest=self.coverage_manifest,
        )
        if recomputed.artifact != self.artifact or recomputed.securities != self.security_records:
            raise ValueError("proof does not reproduce selected Phase 7B artifact content")
        return self


class Phase7BSecMappingBridge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bridge_version: Literal["phase7b-sec-mapping-bridge-v2"] = SEC_BRIDGE_VERSION
    proof: Phase7BBridgeProofEnvelope
    eligible_permanent_ids: tuple[str, ...]
    records: tuple[Phase7BSecMappingRecord, ...]
    bridge_hash: str = Field(pattern=HASH_PATTERN)

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"bridge_hash"})

    @model_validator(mode="after")
    def sealed(self) -> Phase7BSecMappingBridge:
        record_ids = tuple(row.permanent_id for row in self.records)
        if tuple(sorted(record_ids)) != record_ids or record_ids != self.eligible_permanent_ids:
            raise ValueError(
                "bridge records do not exactly and canonically cover Phase 7B identities"
            )
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("bridge contains duplicate permanent identity")
        if self.proof.artifact.permanent_identities != self.eligible_permanent_ids:
            raise ValueError("bridge coverage differs from proved artifact")
        derived = tuple(
            Phase7BSecMappingRecord(
                permanent_id=row.permanent_id,
                issuer_id=row.issuer_id,
                canonical_cik=row.canonical_cik,
                cik_lineage=row.cik_lineage,
                source=row.source,
                source_record_id=row.source_record_id,
                available_at=row.available_at,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                share_class=row.share_class,
                security_type=row.security_type,
            )
            for row in self.proof.security_records
        )
        if derived != self.records:
            raise ValueError("bridge records differ from proved security-master content")
        if typed_hash(self.identity_payload()) != self.bridge_hash:
            raise ValueError("Phase 7B SEC bridge hash mismatch")
        return self

    def to_phase7a_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "permanent_id": row.permanent_id,
                    "cik": row.canonical_cik,
                    "valid_from": row.valid_from,
                    "valid_to": row.valid_to,
                    "available_at": row.available_at,
                    "source": row.source,
                    "source_record_id": row.source_record_id,
                    "issuer_id": row.issuer_id,
                    "cik_lineage": row.cik_lineage,
                    "share_class": row.share_class,
                    "security_type": row.security_type,
                }
                for row in self.records
            ]
        )

    @property
    def artifact_hash(self) -> str:
        return self.proof.artifact.artifact_hash

    @property
    def artifact_as_of(self) -> datetime.datetime:
        return self.proof.artifact.as_of


@dataclass(frozen=True)
class PITReconstruction:
    securities: tuple[SecurityIdentityRecord, ...]
    memberships: tuple[ConstituentRecord, ...]
    artifact: PITUniverseArtifact
    security_proof_records: tuple[SecurityIdentityRecord, ...] = ()
    membership_proof_records: tuple[ConstituentRecord, ...] = ()
    coverage_manifest: ProviderCoverageManifest | None = None
    source_evidence: tuple[SourceEvidence, ...] = ()


def _canonical_rows(rows: list[BaseModel]) -> list[BaseModel]:
    hashes = [typed_hash(row.model_dump(mode="python")) for row in rows]
    if len(hashes) != len(set(hashes)):
        raise SecurityMasterPITError("exact duplicate row identity is forbidden")
    return [row for _, row in sorted(zip(hashes, rows), key=lambda item: item[0])]


def _validate_security_graph(
    records: list[SecurityIdentityRecord], cutoff: datetime.datetime
) -> None:
    known_ids = {row.permanent_id for row in records}
    edges: dict[tuple[str, str], SecurityIdentityRecord] = {}
    graph: dict[str, set[str]] = {item: set() for item in known_ids}
    for row in records:
        if row.relationship_type is None:
            continue
        assert row.related_permanent_id is not None
        assert row.relationship_available_at is not None
        assert row.relationship_effective_at is not None
        if row.related_permanent_id not in known_ids:
            raise SecurityMasterPITError("structural relationship references unknown permanent ID")
        if row.relationship_available_at > cutoff:
            raise SecurityMasterPITError("future structural relationship relative to as_of")
        edge = (row.permanent_id, row.related_permanent_id)
        if edge in edges:
            raise SecurityMasterPITError("duplicate/conflicting structural relationship")
        target_rows = [item for item in records if item.permanent_id == row.related_permanent_id]
        if not any(
            item.listing_start <= row.relationship_effective_at
            and (item.listing_end is None or row.relationship_effective_at < item.listing_end)
            for item in target_rows
        ):
            raise SecurityMasterPITError("structural relationship is temporally incompatible")
        edges[edge] = row
    reciprocal = {
        "MERGER_PREDECESSOR": "MERGER_SUCCESSOR",
        "MERGER_SUCCESSOR": "MERGER_PREDECESSOR",
        "SPINOFF_PARENT": "SPINOFF_CHILD",
        "SPINOFF_CHILD": "SPINOFF_PARENT",
    }
    for (source, target), row in edges.items():
        reverse = edges.get((target, source))
        if reverse is None or reverse.relationship_type != reciprocal[row.relationship_type]:
            raise SecurityMasterPITError("structural relationship lacks paired canonical evidence")
        if reverse.relationship_effective_at != row.relationship_effective_at:
            raise SecurityMasterPITError(
                "paired structural relationship has conflicting effective time"
            )
        if row.relationship_type in {"MERGER_PREDECESSOR", "SPINOFF_PARENT"}:
            graph[source].add(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise SecurityMasterPITError("structural relationship cycle is forbidden")
        if node in visited:
            return
        visiting.add(node)
        for child in graph[node]:
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    incoming: dict[tuple[str, str], set[str]] = {}
    outgoing: dict[tuple[str, str], set[str]] = {}
    for (source, target), row in edges.items():
        if row.relationship_type not in {"MERGER_PREDECESSOR", "SPINOFF_PARENT"}:
            continue
        family = "MERGER" if row.relationship_type.startswith("MERGER") else "SPINOFF"
        incoming.setdefault((target, family), set()).add(source)
        outgoing.setdefault((source, family), set()).add(target)
    if any(len(items) > 1 for items in (*incoming.values(), *outgoing.values())):
        raise SecurityMasterPITError("ambiguous structural parent/child mapping")


def _validate_record_sets(records: list[SecurityIdentityRecord]) -> None:
    revision_ids: set[tuple[str, datetime.datetime, str]] = set()
    by_episode: dict[tuple[str, datetime.datetime], list[SecurityIdentityRecord]] = {}
    for index, left in enumerate(records):
        revision_key = (left.permanent_id, left.listing_start, left.revision_id)
        if revision_key in revision_ids:
            raise SecurityMasterPITError("duplicate security revision identity")
        revision_ids.add(revision_key)
        by_episode.setdefault((left.permanent_id, left.listing_start), []).append(left)
        for right in records[index + 1 :]:
            effective = _overlap(
                left.listing_start, left.listing_end, right.listing_start, right.listing_end
            )
            knowledge = _overlap(left.valid_from, left.valid_to, right.valid_from, right.valid_to)
            if (
                left.permanent_id == right.permanent_id
                and effective
                and knowledge
                and left.listing_start != right.listing_start
            ):
                raise SecurityMasterPITError(
                    "overlapping conflicting windows for one permanent identity"
                )
            if left.source_record_id == right.source_record_id and left != right:
                raise SecurityMasterPITError("duplicate source record identity")
            if (
                left.permanent_id != right.permanent_id
                and left.symbology_key == right.symbology_key
                and effective
            ):
                raise SecurityMasterPITError("overlapping identical symbology is ambiguous")
    for rows in by_episode.values():
        if len(rows) == 1:
            continue
        by_source = {row.source_record_id: row for row in rows}
        roots = [row.source_record_id for row in rows if row.supersedes_source_record_id is None]
        children: dict[str, list[str]] = {}
        for row in rows:
            predecessor = row.supersedes_source_record_id
            if predecessor is None:
                continue
            if predecessor not in by_source:
                raise SecurityMasterPITError("security revision references missing predecessor")
            if by_source[predecessor].available_at >= row.available_at:
                raise SecurityMasterPITError("security correction knowledge time is not increasing")
            children.setdefault(predecessor, []).append(row.source_record_id)
        if len(roots) != 1 or any(len(items) > 1 for items in children.values()):
            raise SecurityMasterPITError("ambiguous or forked security revision chain")
        visited: set[str] = set()
        current = roots[0]
        while current not in visited:
            visited.add(current)
            next_items = children.get(current, [])
            if not next_items:
                break
            current = next_items[0]
        if visited != set(by_source):
            raise SecurityMasterPITError("security revision chain is disconnected or cyclic")


def _validate_membership_chains(records: list[ConstituentRecord]) -> None:
    by_identity: dict[tuple[str, str], list[ConstituentRecord]] = {}
    source_ids: set[tuple[str, str]] = set()
    revisions: set[tuple[str, str, str]] = set()
    for row in records:
        source_key = (row.source, row.source_record_id)
        if source_key in source_ids:
            raise SecurityMasterPITError("duplicate constituent source record identity")
        source_ids.add(source_key)
        revision_key = (row.universe_id, row.permanent_id, row.revision_id)
        if revision_key in revisions:
            raise SecurityMasterPITError("duplicate constituent revision identity")
        revisions.add(revision_key)
        by_identity.setdefault((row.universe_id, row.permanent_id), []).append(row)
    for identity, rows in by_identity.items():
        by_source = {row.source_record_id: row for row in rows}
        children: dict[str, list[str]] = {}
        roots = []
        for row in rows:
            predecessor = row.supersedes_source_record_id
            if predecessor is None:
                roots.append(row.source_record_id)
                continue
            if predecessor not in by_source:
                raise SecurityMasterPITError("constituent revision references missing predecessor")
            if by_source[predecessor].available_at >= row.available_at:
                raise SecurityMasterPITError(
                    "constituent correction knowledge time is not increasing"
                )
            children.setdefault(predecessor, []).append(row.source_record_id)
        if len(roots) != 1:
            raise SecurityMasterPITError(f"ambiguous constituent revision root for {identity}")
        if any(len(items) > 1 for items in children.values()):
            raise SecurityMasterPITError("constituent revision fork is forbidden")
        visited: set[str] = set()
        current = roots[0]
        while True:
            if current in visited:
                raise SecurityMasterPITError("constituent revision cycle is forbidden")
            visited.add(current)
            next_items = children.get(current, [])
            if not next_items:
                break
            current = next_items[0]
        if visited != set(by_source):
            raise SecurityMasterPITError("constituent revision chain is disconnected or cyclic")


def _latest_known_memberships(
    records: list[ConstituentRecord], universe_id: str, cutoff: datetime.datetime
) -> list[ConstituentRecord]:
    selected: list[ConstituentRecord] = []
    identities = sorted({row.permanent_id for row in records if row.universe_id == universe_id})
    for permanent_id in identities:
        rows = [
            row
            for row in records
            if row.universe_id == universe_id
            and row.permanent_id == permanent_id
            and row.available_at <= cutoff
        ]
        if rows:
            selected.append(max(rows, key=lambda row: row.available_at))
    return selected


def reconstruct_pit_universe(
    *,
    security_records: list[SecurityIdentityRecord],
    constituent_records: list[ConstituentRecord],
    universe_id: str,
    as_of: datetime.datetime,
    provider: ProviderIdentity,
    source_evidence: tuple[SourceEvidence, ...],
    runtime_code_fingerprint: str,
    require_cik: bool = True,
    coverage_manifest: ProviderCoverageManifest | None = None,
) -> PITReconstruction:
    cutoff = _aware(as_of, "as_of")
    assert cutoff is not None
    universe_id = _text(universe_id, "universe_id")
    runtime_code_fingerprint = _text(runtime_code_fingerprint, "runtime_code_fingerprint")
    if not source_evidence:
        raise SecurityMasterPITError("recomputable source evidence is required")
    source_evidence = tuple(sorted(source_evidence, key=lambda item: item.source_identity))
    if len({item.source_identity for item in source_evidence}) != len(source_evidence):
        raise SecurityMasterPITError("duplicate source evidence identity")
    source_hashes = tuple(sorted(item.source_hash for item in source_evidence))
    if coverage_manifest is not None:
        ProviderCoverageManifest.model_validate(coverage_manifest.model_dump(mode="python"))
    security_rows = list(_canonical_rows(security_records))
    constituent_rows = list(_canonical_rows(constituent_records))
    _validate_record_sets(security_rows)
    _validate_membership_chains(constituent_rows)
    _validate_security_graph(security_rows, cutoff)
    selected_membership_revisions = _latest_known_memberships(constituent_rows, universe_id, cutoff)
    memberships = [
        row
        for row in selected_membership_revisions
        if row.entry_at <= cutoff
        and (row.exit_at is None or cutoff < row.exit_at)
        and row.valid_from <= cutoff
        and (row.valid_to is None or cutoff < row.valid_to)
    ]
    member_ids = [row.permanent_id for row in memberships]
    if len(member_ids) != len(set(member_ids)):
        raise SecurityMasterPITError("duplicate or conflicting membership identity")
    if not member_ids:
        if any(
            row.available_at > cutoff
            and row.universe_id == universe_id
            and row.entry_at <= cutoff
            and (row.exit_at is None or cutoff < row.exit_at)
            and row.valid_from <= cutoff
            and (row.valid_to is None or cutoff < row.valid_to)
            for row in constituent_rows
        ):
            raise SecurityMasterPITError("future membership evidence relative to as_of")
        raise SecurityMasterPITError("membership cannot be demonstrated at as_of")
    active = [
        row
        for row in security_rows
        if row.available_at <= cutoff
        and row.permanent_id in set(member_ids)
        and row.listing_start <= cutoff
        and (row.listing_end is None or cutoff < row.listing_end)
        and row.valid_from <= cutoff
        and (row.valid_to is None or cutoff < row.valid_to)
    ]
    future_security = [
        row
        for row in security_rows
        if row.available_at > cutoff
        and row.permanent_id in set(member_ids)
        and row.listing_start <= cutoff
        and (row.listing_end is None or cutoff < row.listing_end)
        and row.valid_from <= cutoff
        and (row.valid_to is None or cutoff < row.valid_to)
    ]
    if future_security and not active:
        raise SecurityMasterPITError("future security mapping relative to as_of")
    by_id: dict[str, list[SecurityIdentityRecord]] = {}
    for row in active:
        by_id.setdefault(row.permanent_id, []).append(row)
    if set(by_id) != set(member_ids):
        raise SecurityMasterPITError("membership identity cannot be uniquely demonstrated")
    selected: list[SecurityIdentityRecord] = []
    for rows in by_id.values():
        rows.sort(key=lambda row: row.available_at, reverse=True)
        if len(rows) > 1 and rows[0].supersedes_source_record_id != rows[1].source_record_id:
            raise SecurityMasterPITError("membership identity cannot be uniquely demonstrated")
        selected.append(rows[0])
    securities = tuple(sorted(selected, key=lambda row: row.permanent_id))
    if require_cik and any(row.canonical_cik is None for row in securities):
        raise SecurityMasterPITError("canonical CIK is required but missing")
    memberships_tuple = tuple(sorted(memberships, key=lambda row: row.permanent_id))
    membership_proof_records = tuple(
        sorted(
            (
                row
                for row in constituent_rows
                if row.universe_id == universe_id and row.available_at <= cutoff
            ),
            key=lambda row: (
                row.universe_id,
                row.permanent_id,
                row.available_at,
                row.source_record_id,
            ),
        )
    )
    membership_hash = typed_hash(
        [row.model_dump(mode="python") for row in membership_proof_records]
    )
    security_proof_records = tuple(
        sorted(
            (
                row
                for row in security_rows
                if row.available_at <= cutoff and row.permanent_id in set(member_ids)
            ),
            key=lambda row: (
                row.permanent_id,
                row.listing_start,
                row.available_at,
                row.source_record_id,
            ),
        )
    )
    master_hash = typed_hash([row.model_dump(mode="python") for row in security_proof_records])
    cik_payload = _cik_mapping_payload(securities)
    relationship_payload = _relationship_payload(security_proof_records)
    values = {
        "as_of": cutoff,
        "universe_id": universe_id,
        "provider": provider,
        "coverage_manifest_hash": coverage_manifest.manifest_hash if coverage_manifest else None,
        "source_hashes": source_hashes,
        "permanent_identities": tuple(row.permanent_id for row in securities),
        "membership_hash": membership_hash,
        "security_master_hash": master_hash,
        "cik_mapping_hash": typed_hash(cik_payload),
        "relationship_hash": typed_hash(relationship_payload),
        "runtime_code_fingerprint": runtime_code_fingerprint,
    }
    draft = PITUniverseArtifact.model_construct(**values, artifact_hash="0" * 64)
    artifact = PITUniverseArtifact(**values, artifact_hash=typed_hash(draft.identity_payload()))
    return PITReconstruction(
        securities,
        memberships_tuple,
        artifact,
        security_proof_records,
        membership_proof_records,
        coverage_manifest,
        source_evidence,
    )


def phase7b_sec_mapping_bridge(reconstruction: PITReconstruction) -> Phase7BSecMappingBridge:
    artifact = PITUniverseArtifact.model_validate(reconstruction.artifact.model_dump(mode="python"))
    securities = tuple(sorted(reconstruction.securities, key=lambda row: row.permanent_id))
    memberships = tuple(
        sorted(
            reconstruction.membership_proof_records or reconstruction.memberships,
            key=lambda row: (
                row.universe_id,
                row.permanent_id,
                row.available_at,
                row.source_record_id,
            ),
        )
    )
    security_revision_records = reconstruction.security_proof_records or securities
    if not all(row in security_revision_records for row in securities):
        raise SecurityMasterPITError("selected security reconstruction is stale relative to proof")
    if (
        typed_hash([row.model_dump(mode="python") for row in security_revision_records])
        != artifact.security_master_hash
    ):
        raise SecurityMasterPITError("security reconstruction is stale relative to artifact")
    if (
        typed_hash([row.model_dump(mode="python") for row in memberships])
        != artifact.membership_hash
    ):
        raise SecurityMasterPITError("membership reconstruction is stale relative to artifact")
    if any(row.canonical_cik is None or row.cik_lineage is None for row in securities):
        raise SecurityMasterPITError("Phase 7B SEC bridge requires complete CIK lineage")
    records = tuple(
        Phase7BSecMappingRecord(
            permanent_id=row.permanent_id,
            issuer_id=row.issuer_id,
            canonical_cik=row.canonical_cik,
            cik_lineage=row.cik_lineage,
            source=row.source,
            source_record_id=row.source_record_id,
            available_at=row.available_at,
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            share_class=row.share_class,
            security_type=row.security_type,
        )
        for row in securities
    )
    proof = Phase7BBridgeProofEnvelope(
        artifact=artifact,
        security_records=securities,
        security_revision_records=security_revision_records,
        membership_records=memberships,
        coverage_manifest=reconstruction.coverage_manifest,
        source_evidence=reconstruction.source_evidence,
    )
    values = {
        "proof": proof,
        "eligible_permanent_ids": artifact.permanent_identities,
        "records": records,
    }
    draft = Phase7BSecMappingBridge.model_construct(**values, bridge_hash="0" * 64)
    return Phase7BSecMappingBridge(**values, bridge_hash=typed_hash(draft.identity_payload()))


def universe_source_records(
    reconstruction: PITReconstruction, observations: pd.DataFrame
) -> pd.DataFrame:
    phase7b_sec_mapping_bridge(reconstruction)
    required = {
        "permanent_id",
        "asset_type",
        "country",
        "region",
        "sector",
        "industry",
        "market_cap",
        "market_cap_currency",
        "average_volume",
        "average_dollar_volume",
        "source_timestamp",
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
        [
            {
                "permanent_id": row.permanent_id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "listing_date": row.listing_start,
                "source": row.source,
            }
            for row in reconstruction.securities
        ]
    )
    frame = frame.drop(
        columns=[
            column for column in ("symbol", "exchange", "listing_date", "source") if column in frame
        ]
    )
    return identity.merge(frame, on="permanent_id", validate="one_to_one")
