from __future__ import annotations

import datetime
import json
import time
import tracemalloc
from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from data.provider_contracts import ProviderKind, ProviderSnapshot
from governance.research_chain import GovernedFactorBatch

BLIND_COVERAGE_CONTRACT_VERSION = "blind-coverage-v1"
ADMISSION_CONTRACT_VERSION = "sealed-pre-phase6-admission-v1"


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
        history_sufficiency={},
        failures=tuple(failures),
        runtime_seconds=time.perf_counter() - started,
        peak_memory_bytes=peak,
    )


class PrePhase6Admission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["sealed-pre-phase6-admission-v1"] = ADMISSION_CONTRACT_VERSION
    batches: tuple[GovernedFactorBatch, ...]
    admitted: Literal[True] = True
    scores_calculated: Literal[False] = False
    ranking_calculated: Literal[False] = False
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False


def admit_sealed_for_phase6(*, batches: tuple[GovernedFactorBatch, ...]) -> PrePhase6Admission:
    """Exclusive non-legacy admission boundary; deliberately has no scoring implementation."""
    if not batches or any(type(item) is not GovernedFactorBatch for item in batches):
        raise TypeError("PRE-Phase 6 admission accepts only exact GovernedFactorBatch contracts")
    return PrePhase6Admission(batches=batches)


def main() -> None:
    """Emit an honest not-run report until governed real providers are supplied by code."""
    now = datetime.datetime.now(datetime.UTC)
    report = run_blind_coverage(batches=(), providers=(), as_of=now)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
