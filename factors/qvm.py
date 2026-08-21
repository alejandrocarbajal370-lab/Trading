from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

FACTOR_NAMES = ("Quality", "Value", "Momentum")
QVM_RULESET_VERSION = "qvm-research-v1.0"


class QVMContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NormalizationMetadata(QVMContractModel):
    method: Literal["none", "z_score", "percentile"] = "none"
    reference_population: str = "governed_universe"
    winsorization: Literal["none", "metadata_only"] = "metadata_only"
    lower_bound: float | None = None
    upper_bound: float | None = None
    applied: Literal[False] = False


class FactorObservation(QVMContractModel):
    symbol: str = Field(min_length=1)
    factor: Literal["Quality", "Value", "Momentum"]
    metric: str = Field(min_length=1)
    value: float | None
    normalized_value: float | None = None
    unit: str = Field(min_length=1)
    as_of: datetime.date
    available_at: datetime.datetime
    confidence: float = Field(ge=0, le=1)
    lineage: dict[str, Any]
    universe_snapshot_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str | None = None
    sector: str | None = None
    normalization: NormalizationMetadata = NormalizationMetadata()

    @model_validator(mode="after")
    def validate_governance(self) -> FactorObservation:
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        cutoff = datetime.datetime.combine(self.as_of, datetime.time.max, tzinfo=datetime.UTC)
        if self.available_at.astimezone(datetime.UTC) > cutoff:
            raise ValueError("available_at exceeds the common PIT as_of")
        if not self.lineage:
            raise ValueError("lineage must be non-empty")
        return self


class FactorBatch(QVMContractModel):
    factor: Literal["Quality", "Value", "Momentum"]
    universe_snapshot_id: str
    as_of: datetime.date
    availability_policy: str
    entity_policy: str = "symbol"
    lineage_id: str
    observations: tuple[FactorObservation, ...]


@dataclass(frozen=True)
class QVMEvaluation:
    matrix: pd.DataFrame
    health: dict[str, Any]
    lineage: dict[str, Any]
    validation_report: dict[str, Any]


def observation_from_row(
    row: pd.Series,
    *,
    factor: Literal["Quality", "Value", "Momentum"],
    universe_snapshot_id: str,
    as_of: datetime.date,
) -> FactorObservation:
    available = row.get("available_at", row.get("source_available_at"))
    if available is None or pd.isna(available):
        raise ValueError(f"{factor} observation missing available_at")
    raw_lineage = row.get("lineage")
    try:
        lineage = json.loads(raw_lineage) if isinstance(raw_lineage, str) else raw_lineage
    except json.JSONDecodeError as error:
        raise ValueError(f"{factor} observation has invalid lineage") from error
    unit = row.get("unit")
    if unit is None or pd.isna(unit):
        unit = "ratio" if factor in {"Quality", "Value"} else "dimensionless"
    value = row.get("value")
    value = None if value is None or pd.isna(value) else float(value)
    return FactorObservation(
        symbol=str(row["symbol"]), factor=factor, metric=str(row["metric"]), value=value,
        unit=str(unit), as_of=as_of, available_at=pd.Timestamp(available).to_pydatetime(),
        confidence=float(row["confidence"]), lineage=lineage,
        universe_snapshot_id=universe_snapshot_id, status=str(row["status"]),
        reason=None if pd.isna(row.get("reason")) else str(row.get("reason")),
        sector=None if pd.isna(row.get("sector")) else str(row.get("sector")),
    )


def _validate_alignment(batches: tuple[FactorBatch, ...]) -> None:
    by_factor = {batch.factor: batch for batch in batches}
    missing = sorted(set(FACTOR_NAMES) - set(by_factor))
    if missing:
        raise ValueError(f"factor missing: {', '.join(missing)}")
    if len(by_factor) != len(batches):
        raise ValueError("duplicate factor batch")
    checks = {
        "universe": {batch.universe_snapshot_id for batch in batches},
        "PIT as_of": {batch.as_of for batch in batches},
        "availability policy": {batch.availability_policy for batch in batches},
        "entity policy": {batch.entity_policy for batch in batches},
        "lineage": {batch.lineage_id for batch in batches},
    }
    mismatches = [name for name, values in checks.items() if len(values) != 1]
    if mismatches:
        raise ValueError(f"QVM alignment mismatch: {', '.join(mismatches)}")
    for batch in batches:
        if not batch.observations:
            raise ValueError(f"factor missing observations: {batch.factor}")
        for observation in batch.observations:
            if observation.factor != batch.factor:
                raise ValueError("observation factor does not match its batch")
            if observation.as_of != batch.as_of:
                raise ValueError("QVM alignment mismatch: observation PIT as_of")
            if observation.universe_snapshot_id != batch.universe_snapshot_id:
                raise ValueError("QVM alignment mismatch: observation universe")
    symbol_sets = [{item.symbol for item in batch.observations} for batch in batches]
    if any(symbols != symbol_sets[0] for symbols in symbol_sets[1:]):
        raise ValueError("QVM alignment mismatch: governed universe membership")


def _correlations(frame: pd.DataFrame) -> dict[str, Any]:
    per_factor = frame.groupby(["symbol", "factor"], sort=True)["value"].mean().unstack()
    correlations = per_factor.corr(min_periods=2)
    return {
        left: {
            right: (None if pd.isna(correlations.loc[left, right]) else float(correlations.loc[left, right]))
            for right in correlations.columns
        }
        for left in correlations.index
    }


def evaluate_qvm_research(batches: tuple[FactorBatch, ...]) -> QVMEvaluation:
    _validate_alignment(batches)
    rows = [observation.model_dump(mode="json") for batch in batches for observation in batch.observations]
    long = pd.DataFrame(rows)
    universe_sets = {
        factor: set(long.loc[long["factor"] == factor, "symbol"].astype(str))
        for factor in FACTOR_NAMES
    }
    governed_symbols = set.union(*universe_sets.values())
    overlap = set.intersection(*universe_sets.values())
    common = batches[0]
    long["column"] = long["factor"].str.lower() + "__" + long["metric"]
    value_matrix = long.pivot(index="symbol", columns="column", values="value")
    status_matrix = long.pivot(index="symbol", columns="column", values="status").add_suffix("__status")
    matrix = value_matrix.join(status_matrix).sort_index(axis=1).reset_index()
    coverage = {factor: len(symbols) / len(governed_symbols) for factor, symbols in universe_sets.items()}
    missingness = {
        factor: float(group["value"].isna().mean())
        for factor, group in long.groupby("factor", sort=True)
    }
    conflicts = []
    directions = long.assign(direction=np.sign(pd.to_numeric(long["value"], errors="coerce")))
    for symbol, group in directions.groupby("symbol", sort=True):
        signs = {factor: set(values.dropna().astype(int)) for factor, values in group.groupby("factor")["direction"]}
        if any(positive in {1, -1} and -positive in other for values in signs.values() for positive in values for other in signs.values()):
            conflicts.append(str(symbol))
    sector = {}
    if long["sector"].notna().any():
        counts = long.dropna(subset=["sector"])[["symbol", "sector"]].drop_duplicates()["sector"].value_counts()
        sector = {str(name): int(count) for name, count in counts.sort_index().items()}
    diagnostics = {
        "coverage_by_factor": coverage,
        "missingness_by_factor": missingness,
        "universe_overlap": {"symbols": len(overlap), "ratio": len(overlap) / len(governed_symbols)},
        "factor_correlations": _correlations(long),
        "sector_concentration": sector or {"status": "NOT_AVAILABLE"},
        "factor_conflicts": {"symbols": conflicts, "count": len(conflicts)},
    }
    health_status = "PASS" if len(overlap) == len(governed_symbols) and not any(missingness.values()) else "WARNING"
    health = {
        "schema_version": "qvm-health-v1", "status": health_status,
        "observations": len(long), "symbols": len(governed_symbols), "diagnostics": diagnostics,
        "normalization": {"z_score": "metadata_only", "percentile": "metadata_only", "winsorization": "metadata_only"},
        "composite_score_calculated": False, "weights_assigned": False,
        "ranking_calculated": False, "portfolio_constructed": False,
        "backtest_executed": False, "signals_generated": False,
        "trade_decision": "NO_TRADE", "live_execution_enabled": False,
    }
    lineage = {
        "schema_version": "qvm-lineage-v1", "ruleset_version": QVM_RULESET_VERSION,
        "universe_snapshot_id": common.universe_snapshot_id, "as_of": common.as_of.isoformat(),
        "availability_policy": common.availability_policy, "entity_policy": common.entity_policy,
        "lineage_id": common.lineage_id,
        "factors": {batch.factor: [item.lineage for item in batch.observations] for batch in batches},
    }
    report = {
        "schema_version": "qvm-validation-report-v1", "status": health_status,
        "checks": {"common_contract": "PASS", "PIT_alignment": "PASS", "universe_alignment": "PASS",
                   "availability_alignment": "PASS", "entity_alignment": "PASS", "lineage_alignment": "PASS",
                   "individual_factor_preservation": "PASS"},
        "prohibited_outputs": {"score": False, "weights": False, "ranking": False, "selection": False,
                               "portfolio": False, "backtest": False, "broker": False, "execution": False},
    }
    return QVMEvaluation(matrix, health, lineage, report)
