from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data.connectors.sec_edgar import (
    SEC_HTTP_POLICY_VERSION,
    SecEdgarFundamentalsSource,
    SecFundamentalsResult,
)
from governance.canonical import typed_hash
from research.datasets import DatasetVersionError, verify_universe_snapshot

SEC_UNIVERSE_BINDING_VERSION = "universe-security-master-sec-binding-v1"
SECURITY_MASTER_REQUIRED_COLUMNS = (
    "permanent_id",
    "cik",
    "valid_from",
    "valid_to",
    "available_at",
    "source",
    "source_record_id",
)
TEXT_PLACEHOLDERS = frozenset({"nan", "none", "null", "n/a", "na", "unknown"})


class SecUniverseBindingError(ValueError):
    """The Universe -> permanent identity -> CIK boundary is not trustworthy."""


class SecIssuerBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permanent_ids: tuple[str, ...] = Field(min_length=1)
    canonical_cik: str = Field(pattern=r"^[0-9]{10}$")
    security_master_source: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    mapping_available_at: datetime.datetime
    mapping_valid_from: datetime.datetime
    mapping_valid_to: datetime.datetime | None = None

    @field_validator("security_master_source", "source_record_id", mode="before")
    @classmethod
    def valid_lineage_text(cls, value: object) -> str:
        return _canonical_text(value, "security-master lineage")

    @field_validator("permanent_ids", mode="before")
    @classmethod
    def valid_permanent_ids(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise TypeError("permanent identities must be a sequence")
        return tuple(_canonical_text(item, "permanent identity") for item in value)

    @field_validator("mapping_available_at", "mapping_valid_from", "mapping_valid_to")
    @classmethod
    def aware(cls, value: datetime.datetime | None) -> datetime.datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("security-master timestamps must be timezone-aware")
        return value.astimezone(datetime.UTC) if value is not None else None


class SecAcquisitionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["universe-security-master-sec-binding-v1"] = (
        SEC_UNIVERSE_BINDING_VERSION
    )
    as_of: datetime.datetime
    universe_snapshot_id: str = Field(min_length=1)
    universe_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    universe_validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_permanent_ids: tuple[str, ...] = Field(min_length=1)
    issuers: tuple[SecIssuerBinding, ...] = Field(min_length=1)
    provider: Literal["sec_edgar"] = "sec_edgar"
    provider_policy_version: Literal["sec-fair-access-http-v2"] = SEC_HTTP_POLICY_VERSION
    security_master_provider_state: Literal["OPEN_EXTERNAL"] = "OPEN_EXTERNAL"
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    qvm_binding_state: Literal["INGESTION_ONLY_NOT_ACCOUNTING_OR_QVM_BOUND"] = (
        "INGESTION_ONLY_NOT_ACCOUNTING_OR_QVM_BOUND"
    )
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False

    @field_validator("as_of")
    @classmethod
    def aware_as_of(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(datetime.UTC)

    def identity_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "as_of": self.as_of,
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_membership_sha256": self.universe_membership_sha256,
            "universe_validation_sha256": self.universe_validation_sha256,
            "eligible_permanent_ids": self.eligible_permanent_ids,
            "issuers": [item.model_dump(mode="python") for item in self.issuers],
            "provider": self.provider,
            "provider_policy_version": self.provider_policy_version,
            "security_master_provider_state": self.security_master_provider_state,
            "global_readiness": self.global_readiness,
            "qvm_binding_state": self.qvm_binding_state,
            "trade_decision": self.trade_decision,
            "live_execution_enabled": self.live_execution_enabled,
            "signals_generated": self.signals_generated,
        }

    @model_validator(mode="after")
    def verify_identity(self) -> SecAcquisitionPlan:
        if tuple(sorted(self.eligible_permanent_ids)) != self.eligible_permanent_ids:
            raise ValueError("eligible permanent identities are not canonical")
        bound = tuple(sorted(item for issuer in self.issuers for item in issuer.permanent_ids))
        if bound != self.eligible_permanent_ids:
            raise ValueError("issuer bindings do not exactly cover the eligible universe")
        if tuple(sorted(self.issuers, key=lambda item: item.canonical_cik)) != self.issuers:
            raise ValueError("issuer bindings are not canonical")
        if any(
            issuer.mapping_available_at > self.as_of
            or issuer.mapping_valid_from > self.as_of
            or (
                issuer.mapping_valid_to is not None
                and issuer.mapping_valid_to < self.as_of
            )
            for issuer in self.issuers
        ):
            raise ValueError("issuer binding chronology is invalid at plan as_of")
        if typed_hash(self.identity_payload()) != self.plan_hash:
            raise ValueError("SEC acquisition plan hash mismatch")
        return self


@dataclass(frozen=True)
class GovernedSecIngestionResult:
    plan: SecAcquisitionPlan
    sec: SecFundamentalsResult
    raw_acquisition_ids: tuple[str, ...]
    lineage_hash: str
    global_readiness: str = "INSUFFICIENT_REAL_DATA"
    qvm_binding_state: str = "INGESTION_ONLY_NOT_ACCOUNTING_OR_QVM_BOUND"
    trade_decision: str = "NO_TRADE"
    live_execution_enabled: bool = False
    signals_generated: bool = False


def _canonical_cik(value: object) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,10}", text):
        raise SecUniverseBindingError("security-master CIK is malformed")
    cik = text.zfill(10)
    if cik == "0000000000":
        raise SecUniverseBindingError("security-master CIK is a placeholder")
    return cik


def _canonical_text(value: object, name: str) -> str:
    """Validate governed textual identity/lineage before any string coercion."""
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    if missing:
        raise ValueError(f"{name} is null")
    text = str(value).strip()
    if not text or text.casefold() in TEXT_PLACEHOLDERS:
        raise ValueError(f"{name} is empty or a placeholder")
    return text


def _timestamp(value: object, name: str, *, nullable: bool = False) -> datetime.datetime | None:
    if nullable and pd.isna(value):
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise SecUniverseBindingError(f"{name} is invalid") from error
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecUniverseBindingError(f"{name} must be timezone-aware")
    return parsed.tz_convert("UTC").to_pydatetime()


def build_sec_acquisition_plan(
    *,
    universe_snapshot_dir: Path,
    security_master_records: pd.DataFrame,
    as_of: datetime.datetime,
) -> SecAcquisitionPlan:
    """Build an exact PIT issuer plan; this is a contract, not a real security-master provider."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SecUniverseBindingError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(datetime.UTC)
    try:
        verified = verify_universe_snapshot(universe_snapshot_dir)
    except DatasetVersionError as error:
        raise SecUniverseBindingError(str(error)) from error
    universe_as_of = _timestamp(verified.metadata.get("as_of"), "universe as_of")
    if universe_as_of != cutoff:
        raise SecUniverseBindingError("universe snapshot as_of does not match acquisition as_of")
    membership = pd.read_csv(verified.membership_path, dtype={"permanent_id": "string"})
    if "permanent_id" not in membership:
        raise SecUniverseBindingError("eligible universe lacks permanent identity")
    eligible = membership.loc[membership["eligibility_status"] == "ELIGIBLE"].copy()
    identities = eligible["permanent_id"].astype("string").str.strip()
    if identities.isna().any() or (identities == "").any():
        raise SecUniverseBindingError("eligible universe lacks permanent identity")
    if identities.str.lower().isin({"unknown", "n/a", "na", "none", "null"}).any():
        raise SecUniverseBindingError("eligible universe contains placeholder permanent identity")
    if identities.duplicated(keep=False).any():
        raise SecUniverseBindingError("eligible universe contains duplicate permanent identity")
    eligible_ids = tuple(sorted(identities.tolist()))

    missing = sorted(set(SECURITY_MASTER_REQUIRED_COLUMNS) - set(security_master_records.columns))
    if missing:
        raise SecUniverseBindingError(
            f"security-master mapping lacks required fields: {', '.join(missing)}"
        )
    records = security_master_records.loc[:, SECURITY_MASTER_REQUIRED_COLUMNS].copy()
    records["permanent_id"] = records["permanent_id"].astype("string").str.strip()
    relevant = records.loc[records["permanent_id"].isin(eligible_ids)].copy()
    unknown = set(eligible_ids) - set(relevant["permanent_id"])
    if unknown:
        raise SecUniverseBindingError("eligible permanent identity has no CIK mapping")
    if relevant["permanent_id"].duplicated(keep=False).any():
        raise SecUniverseBindingError("duplicate/conflicting permanent identity mapping")

    normalized: list[dict[str, object]] = []
    for row in relevant.to_dict("records"):
        available = _timestamp(row["available_at"], "mapping available_at")
        valid_from = _timestamp(row["valid_from"], "mapping valid_from")
        valid_to = _timestamp(row["valid_to"], "mapping valid_to", nullable=True)
        if available > cutoff or valid_from > cutoff:
            raise SecUniverseBindingError("future security-master mapping relative to as_of")
        if valid_to is not None and valid_to < cutoff:
            raise SecUniverseBindingError("stale security-master mapping relative to as_of")
        try:
            source = _canonical_text(row["source"], "security-master source")
            record_id = _canonical_text(
                row["source_record_id"], "security-master source_record_id"
            )
        except ValueError as error:
            raise SecUniverseBindingError("security-master lineage is incomplete") from error
        normalized.append(
            {
                "permanent_id": str(row["permanent_id"]),
                "canonical_cik": _canonical_cik(row["cik"]),
                "security_master_source": source,
                "source_record_id": record_id,
                "mapping_available_at": available,
                "mapping_valid_from": valid_from,
                "mapping_valid_to": valid_to,
            }
        )

    issuers: list[SecIssuerBinding] = []
    for cik in sorted({str(row["canonical_cik"]) for row in normalized}):
        rows = [row for row in normalized if row["canonical_cik"] == cik]
        lineage = {
            (str(row["security_master_source"]), str(row["source_record_id"])) for row in rows
        }
        chronology = {
            (row["mapping_available_at"], row["mapping_valid_from"], row["mapping_valid_to"])
            for row in rows
        }
        if len(lineage) != 1 or len(chronology) != 1:
            raise SecUniverseBindingError("conflicting mappings for one SEC issuer")
        row = rows[0]
        issuers.append(
            SecIssuerBinding(
                permanent_ids=tuple(sorted(str(item["permanent_id"]) for item in rows)),
                canonical_cik=cik,
                security_master_source=str(row["security_master_source"]),
                source_record_id=str(row["source_record_id"]),
                mapping_available_at=row["mapping_available_at"],
                mapping_valid_from=row["mapping_valid_from"],
                mapping_valid_to=row["mapping_valid_to"],
            )
        )
    values = {
        "as_of": cutoff,
        "universe_snapshot_id": f"universe-{cutoff.date().isoformat()}",
        "universe_membership_sha256": verified.membership_sha256,
        "universe_validation_sha256": verified.validation_sha256,
        "eligible_permanent_ids": eligible_ids,
        "issuers": tuple(issuers),
    }
    draft = SecAcquisitionPlan.model_construct(plan_hash="0" * 64, **values)
    return SecAcquisitionPlan(**values, plan_hash=typed_hash(draft.identity_payload()))


def ingest_governed_universe(
    *, plan: SecAcquisitionPlan, source: SecEdgarFundamentalsSource
) -> GovernedSecIngestionResult:
    """Execute only the sealed issuer set. Tickers are never accepted at this boundary."""
    verified = SecAcquisitionPlan.model_validate(plan.model_dump(mode="python"))
    cik_by_identity = {
        issuer.permanent_ids[0]: issuer.canonical_cik for issuer in verified.issuers
    }
    sec = source.fetch(cik_by_symbol=cik_by_identity, as_of=verified.as_of)
    raw_ids = tuple(sorted(manifest.acquisition_id for manifest in sec.raw_manifests))
    lineage_hash = typed_hash(
        {
            "schema_version": SEC_UNIVERSE_BINDING_VERSION,
            "plan_hash": verified.plan_hash,
            "raw_acquisition_ids": raw_ids,
            "raw_content_sha256": tuple(sorted(item.sha256 for item in sec.raw_manifests)),
        }
    )
    return GovernedSecIngestionResult(verified, sec, raw_ids, lineage_hash)
