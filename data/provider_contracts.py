from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from governance.canonical import typed_hash

PROVIDER_CONTRACT_VERSION = "real-provider-readiness-v1"


class ProviderKind(StrEnum):
    FUNDAMENTALS_PIT = "FUNDAMENTALS_PIT"
    FX = "FX"
    SECURITY_MASTER = "SECURITY_MASTER"
    RESTATEMENTS = "RESTATEMENTS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    SHARES_OUTSTANDING_PIT = "SHARES_OUTSTANDING_PIT"


class ProviderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["real-provider-readiness-v1"] = PROVIDER_CONTRACT_VERSION
    kind: ProviderKind
    source: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    canonical_id: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_at: datetime.datetime
    pit_semantics: str = Field(min_length=1)
    raw_snapshot_reference: str = Field(min_length=1)
    raw_snapshot_retention: str = Field(min_length=1)
    lineage: tuple[str, ...] = Field(min_length=1)
    real_data: bool
    licensed_for_use: bool
    bound_factor_batch_hashes: tuple[str, ...] = ()
    coverage_symbols_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    history_sufficiency_verified: bool = False
    observed_symbols: tuple[str, ...] = ()
    observed_metrics: tuple[str, ...] = ()
    history_rows_by_symbol: dict[str, int] = {}
    peer_membership_by_symbol: dict[str, str] = {}
    snapshot_payload_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_behavior: Literal["FAIL_CLOSED"] = "FAIL_CLOSED"

    @field_validator("available_at")
    @classmethod
    def require_aware(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider available_at must be timezone-aware")
        return value

    def evidence_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "kind": self.kind,
            "source": self.source,
            "dataset_version": self.dataset_version,
            "available_at": self.available_at,
            "pit_semantics": self.pit_semantics,
            "raw_snapshot_reference": self.raw_snapshot_reference,
            "lineage": self.lineage,
            "observed_symbols": tuple(sorted(self.observed_symbols)),
            "observed_metrics": tuple(sorted(self.observed_metrics)),
            "history_rows_by_symbol": self.history_rows_by_symbol,
            "peer_membership_by_symbol": self.peer_membership_by_symbol,
        }

    @model_validator(mode="after")
    def validate_evidence_identity(self) -> ProviderSnapshot:
        symbols = tuple(symbol.strip().upper() for symbol in self.observed_symbols)
        if len(symbols) != len(set(symbols)):
            raise ValueError("provider evidence contains duplicate symbols")
        if set(self.history_rows_by_symbol) - set(symbols):
            raise ValueError("history evidence references an unobserved symbol")
        if set(self.peer_membership_by_symbol) - set(symbols):
            raise ValueError("peer evidence references an unobserved symbol")
        if self.snapshot_payload_hash is not None:
            observed = typed_hash(self.evidence_payload())
            if observed != self.snapshot_payload_hash:
                raise ValueError("provider snapshot payload hash mismatch")
            if self.checksum != observed or self.canonical_id != f"provider-snapshot:{observed}":
                raise ValueError("provider canonical_id/checksum do not bind evidence payload")
        return self

    @property
    def operationally_ready(self) -> bool:
        return (
            self.real_data
            and self.licensed_for_use
            and bool(self.bound_factor_batch_hashes)
            and self.coverage_symbols_hash is not None
            and self.history_sufficiency_verified
            and self.snapshot_payload_hash is not None
            and bool(self.observed_symbols)
            and bool(self.observed_metrics)
            and set(self.history_rows_by_symbol) == set(self.observed_symbols)
            and all(count > 0 for count in self.history_rows_by_symbol.values())
        )


@runtime_checkable
class GovernedRealProvider(Protocol):
    @property
    def kind(self) -> ProviderKind: ...

    def snapshot(self, *, as_of: datetime.datetime) -> ProviderSnapshot: ...


def require_real_provider(snapshot: ProviderSnapshot, *, expected: ProviderKind) -> None:
    if snapshot.kind != expected:
        raise ValueError(f"provider kind mismatch: expected {expected}, got {snapshot.kind}")
    if not snapshot.operationally_ready:
        raise ValueError(f"{expected} is CONTRACT-CLOSED / REAL-DATA-OPEN")
