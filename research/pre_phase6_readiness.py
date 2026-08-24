from __future__ import annotations

import datetime
import json
import math
import time
import tracemalloc
from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from data.provider_contracts import ProviderKind, ProviderSnapshot
from factors.qvm import factor_dataset_hash, factor_observation_hash
from governance.canonical import typed_hash
from governance.integration import eligible_symbols_hash
from governance.pre_phase6 import GovernedStatus, governed_status, metric_applicability
from governance.research_chain import GovernedFactorBatch, governed_factor_batch_identity

BLIND_COVERAGE_CONTRACT_VERSION = "blind-coverage-v1"
ADMISSION_CONTRACT_VERSION = "sealed-pre-phase6-admission-v2"


class ReadinessState(StrEnum):
    READY = "READY"
    NOT_RUN = "NOT_RUN"
    INSUFFICIENT_REAL_DATA = "INSUFFICIENT_REAL_DATA"


class CoverageMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    factor: str
    metric: str
    eligible_count: int = Field(ge=0)
    observed_count: int = Field(ge=0)
    coverage_percent: float = Field(ge=0, le=100)


class BlindCoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["blind-coverage-v1"] = BLIND_COVERAGE_CONTRACT_VERSION
    state: ReadinessState
    as_of: datetime.datetime
    synthetic_contract_test: bool
    metrics: tuple[CoverageMetric, ...]
    missing_taxonomy: int = Field(ge=0)
    provider_gaps: tuple[str, ...]
    composite_eligible_count: int = Field(ge=0)
    peer_group_sufficiency: dict[str, int]
    history_sufficiency: dict[str, int]
    failures: tuple[str, ...]
    runtime_seconds: float = Field(ge=0)
    peak_memory_bytes: int = Field(ge=0)
    outcomes_or_returns_used: Literal[False] = False
    thresholds_optimized: Literal[False] = False
    scores_calculated: Literal[False] = False
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False


REQUIRED_REAL_PROVIDERS = frozenset(ProviderKind)


def run_blind_coverage(
    *,
    batches: tuple[GovernedFactorBatch, ...],
    providers: tuple[ProviderSnapshot, ...],
    as_of: datetime.datetime,
    synthetic_contract_test: bool = False,
) -> BlindCoverageReport:
    """Measure only data feasibility. It never reads outcomes, returns, or computes scores."""
    started = time.perf_counter()
    tracemalloc.start()
    failures: list[str] = []
    by_kind = {item.kind: item for item in providers}
    if len(by_kind) != len(providers):
        failures.append("provider kinds must be unique")
    if any(item.available_at > as_of for item in providers):
        failures.append("provider available_at exceeds coverage as_of")
    batch_hashes = {item.batch_identity_hash for item in batches}
    expected_symbols = {item.symbol for batch in batches for item in batch.observations}
    expected_coverage_hash = eligible_symbols_hash(tuple(expected_symbols)) if expected_symbols else None
    for provider in providers:
        if batch_hashes and set(provider.bound_factor_batch_hashes) != batch_hashes:
            failures.append(f"{provider.kind.value} is not bound to the sealed batches")
        if expected_coverage_hash and provider.coverage_symbols_hash != expected_coverage_hash:
            failures.append(f"{provider.kind.value} coverage identity mismatch")
        if not provider.history_sufficiency_verified:
            failures.append(f"{provider.kind.value} lacks verified history sufficiency")
    gaps = sorted(
        kind.value
        for kind in REQUIRED_REAL_PROVIDERS
        if kind not in by_kind or not by_kind[kind].operationally_ready
    )
    if not batches:
        failures.append("no sealed governed factor batches")
    all_symbols = {item.symbol for batch in batches for item in batch.observations}
    counts = Counter(
        (batch.factor, item.metric)
        for batch in batches
        for item in batch.observations
        if item.status == "PASS" and item.value is not None
    )
    metrics = tuple(
        CoverageMetric(
            factor=factor,
            metric=metric,
            eligible_count=len(all_symbols),
            observed_count=count,
            coverage_percent=(100 * count / len(all_symbols)) if all_symbols else 0,
        )
        for (factor, metric), count in sorted(counts.items())
    )
    missing_taxonomy = sum(
        not item.sector or not item.industry for batch in batches for item in batch.observations
    )
    factor_symbols = [
        {item.symbol for item in batch.observations if item.status == "PASS"} for batch in batches
    ]
    composite_eligible = len(set.intersection(*factor_symbols)) if factor_symbols else 0
    peer_counts = Counter(
        item.industry for batch in batches for item in batch.observations if item.industry
    )
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    state = (
        ReadinessState.READY
        if not gaps and not failures and not synthetic_contract_test
        else ReadinessState.INSUFFICIENT_REAL_DATA
        if gaps
        else ReadinessState.NOT_RUN
    )
    return BlindCoverageReport(
        state=state,
        as_of=as_of,
        synthetic_contract_test=synthetic_contract_test,
        metrics=metrics,
        missing_taxonomy=missing_taxonomy,
        provider_gaps=tuple(gaps),
        composite_eligible_count=composite_eligible,
        peer_group_sufficiency=dict(sorted(peer_counts.items())),
        history_sufficiency={
            item.kind.value: int(item.history_sufficiency_verified) for item in providers
        },
        failures=tuple(failures),
        runtime_seconds=time.perf_counter() - started,
        peak_memory_bytes=peak,
    )


class PrePhase6Admission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["sealed-pre-phase6-admission-v2"] = ADMISSION_CONTRACT_VERSION
    research_only: Literal[True] = True
    as_of: datetime.datetime
    universe_snapshot_id: str
    universe_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_symbols_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_symbols: tuple[str, ...]
    factor_batch_hashes: dict[Literal["Quality", "Value", "Momentum"], str]
    admitted_observation_hashes: tuple[str, ...]
    qvm_sealed_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted: Literal[True] = True
    scores_calculated: Literal[False] = False
    ranking_calculated: Literal[False] = False
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    portfolio_constructed: Literal[False] = False
    backtesting_performed: Literal[False] = False
    signals_generated: Literal[False] = False
    execution_enabled: Literal[False] = False


def _admission_identity(values: dict[str, object]) -> str:
    return typed_hash(
        {
            "schema_version": ADMISSION_CONTRACT_VERSION,
            **{
                key: value
                for key, value in values.items()
                if key not in {"admission_artifact_hash", "admitted"}
            },
        }
    )


def admit_sealed_for_phase6(*, batches: tuple[GovernedFactorBatch, ...]) -> PrePhase6Admission:
    """Exclusive non-legacy admission boundary; deliberately has no scoring implementation."""
    if any(type(item) is not GovernedFactorBatch for item in batches):
        raise TypeError("PRE-Phase 6 admission accepts only exact GovernedFactorBatch contracts")
    if len(batches) != 3 or {item.factor for item in batches} != {
        "Quality",
        "Value",
        "Momentum",
    }:
        raise ValueError("admission requires exactly one Quality, Value, and Momentum batch")

    # Re-validate serialized values so model_copy/model_construct mutations cannot bypass gates.
    validated: tuple[GovernedFactorBatch, ...] = tuple(
        GovernedFactorBatch.model_validate(item.model_dump(mode="python")) for item in batches
    )
    identity_fields = (
        "as_of",
        "cross_layer_contract_version",
        "cross_layer_fingerprint",
        "universe_snapshot_id",
        "universe_snapshot_hash",
        "membership_hash",
        "validation_hash",
        "eligible_symbols_hash",
        "availability_policy_version",
        "entity_policy_version",
        "base_currency",
        "unit_ontology_version",
        "calendar_alignment_policy_version",
        "accounting_canonical_id",
        "accounting_checksum",
        "accounting_snapshot_sha256",
        "fx_canonical_id",
        "fx_checksum",
        "fx_conversions_sha256",
        "market_data_canonical_id",
        "market_data_checksum",
        "market_data_snapshot_sha256",
        "classification_contract_version",
        "classification_taxonomy",
        "classification_taxonomy_version",
        "peer_assignment_hash",
    )
    mismatches = [
        field for field in identity_fields if len({getattr(item, field) for item in validated}) != 1
    ]
    if mismatches:
        raise ValueError("admission identity mismatch: " + ", ".join(mismatches))
    first = validated[0]
    expected_symbols = tuple(
        sorted(record.symbol.strip().upper() for record in first.classification_records)
    )
    if eligible_symbols_hash(expected_symbols) != first.eligible_symbols_hash:
        raise ValueError("eligible_symbols_hash does not match expected symbols")
    admitted_hashes: list[str] = []
    for batch in validated:
        if factor_dataset_hash(batch.observations) != batch.factor_dataset_hash:
            raise ValueError(f"{batch.factor} factor_dataset_hash mismatch")
        if governed_factor_batch_identity(batch) != batch.batch_identity_hash:
            raise ValueError(f"{batch.factor} batch identity mismatch")
        if batch.runtime.git_commit_sha == "UNAVAILABLE":
            raise ValueError(f"{batch.factor} critical git runtime fingerprint is UNAVAILABLE")
        if batch.runtime.requirements_lock_sha256 == "UNAVAILABLE":
            raise ValueError(f"{batch.factor} critical lock runtime fingerprint is UNAVAILABLE")
        if len({item.runtime.fingerprint for item in validated}) != 1:
            raise ValueError("admission runtime/code fingerprint mismatch")
        symbols = {item.symbol.strip().upper() for item in batch.observations}
        if symbols != set(expected_symbols):
            raise ValueError(f"{batch.factor} observations do not contain exact expected symbols")
        keys = [(item.symbol.strip().upper(), item.metric) for item in batch.observations]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{batch.factor} has duplicate symbol/metric observations")
        admitted_symbols: set[str] = set()
        for observation in batch.observations:
            status = governed_status(observation.status)
            applicability = metric_applicability(
                observation.metric, observation.sector, observation.industry
            )
            if observation.applicability != applicability.state:
                raise ValueError("admission applicability mismatch")
            if status == GovernedStatus.PASS:
                if applicability.state != "APPLICABLE":
                    raise ValueError("non-applicable observation cannot enter admission")
                if observation.value is None or not math.isfinite(observation.value):
                    raise ValueError("admissible observation value must be finite")
                if observation.confidence < 0.80:
                    raise ValueError("admissible observation confidence must be at least 0.80")
                admitted_symbols.add(observation.symbol.strip().upper())
                admitted_hashes.append(factor_observation_hash(observation))
        if admitted_symbols != set(expected_symbols):
            raise ValueError(f"{batch.factor} lacks a PASS admissible observation for every symbol")

    values: dict[str, object] = {
        "as_of": first.as_of,
        "universe_snapshot_id": first.universe_snapshot_id,
        "universe_snapshot_hash": first.universe_snapshot_hash,
        "eligible_symbols_hash": first.eligible_symbols_hash,
        "expected_symbols": expected_symbols,
        "factor_batch_hashes": {
            item.factor: item.batch_identity_hash for item in sorted(validated, key=lambda x: x.factor)
        },
        "admitted_observation_hashes": tuple(sorted(admitted_hashes)),
        "qvm_sealed_lineage_hash": typed_hash(
            {
                "schema_version": "qvm-sealed-lineage-v2",
                "cross_layer_fingerprint": first.cross_layer_fingerprint,
                "peer_assignment_hash": first.peer_assignment_hash,
                "factor_batches": {
                    item.factor: item.batch_identity_hash for item in validated
                },
            }
        ),
        "scores_calculated": False,
        "ranking_calculated": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "portfolio_constructed": False,
        "backtesting_performed": False,
        "signals_generated": False,
        "execution_enabled": False,
        "research_only": True,
    }
    values["admission_artifact_hash"] = _admission_identity(values)
    return PrePhase6Admission(**values)


def main() -> None:
    """Emit an honest not-run report until governed real providers are supplied by code."""
    now = datetime.datetime.now(datetime.UTC)
    report = run_blind_coverage(batches=(), providers=(), as_of=now)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
