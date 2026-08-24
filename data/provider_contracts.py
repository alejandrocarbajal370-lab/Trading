from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    failure_behavior: Literal["FAIL_CLOSED"] = "FAIL_CLOSED"

    @field_validator("available_at")
    @classmethod
    def require_aware(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider available_at must be timezone-aware")
        return value

    @property
    def operationally_ready(self) -> bool:
        return (
            self.real_data
            and self.licensed_for_use
            and bool(self.bound_factor_batch_hashes)
            and self.coverage_symbols_hash is not None
            and self.history_sufficiency_verified
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
