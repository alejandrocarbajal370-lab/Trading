from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

FACTOR_NAMES = ("Quality", "Value", "Momentum")
QVM_RULESET_VERSION = "qvm-research-v1.0"
NOT_AVAILABLE = "NOT_AVAILABLE"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class MetricSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Literal["higher_is_better", "lower_is_better", "contextual", "non_directional"]
    comparison_group: str | None
    economic_meaning: str


METRIC_SEMANTICS_REGISTRY: Mapping[str, MetricSemantics] = {
    "roic": MetricSemantics(
        direction="higher_is_better",
        comparison_group="profitability_ratio",
        economic_meaning="return on invested capital",
    ),
    "fcf_margin": MetricSemantics(
        direction="higher_is_better",
        comparison_group="profitability_ratio",
        economic_meaning="free-cash-flow margin",
    ),
    "cfo_conversion": MetricSemantics(
        direction="higher_is_better",
        comparison_group="cash_conversion_ratio",
        economic_meaning="cash conversion",
    ),
    "accrual_quality": MetricSemantics(
        direction="higher_is_better",
        comparison_group="cash_conversion_ratio",
        economic_meaning="accrual quality",
    ),
    "fcf_yield": MetricSemantics(
        direction="higher_is_better",
        comparison_group="valuation_yield",
        economic_meaning="free-cash-flow yield",
    ),
    "earnings_yield": MetricSemantics(
        direction="higher_is_better",
        comparison_group="valuation_yield",
        economic_meaning="earnings yield",
    ),
    "ebit_yield": MetricSemantics(
        direction="higher_is_better",
        comparison_group="valuation_yield",
        economic_meaning="EBIT yield",
    ),
    "ev_to_ebit": MetricSemantics(
        direction="lower_is_better",
        comparison_group="valuation_multiple",
        economic_meaning="EV/EBIT valuation multiple",
    ),
    "ev_to_ebitda": MetricSemantics(
        direction="lower_is_better",
        comparison_group="valuation_multiple",
        economic_meaning="EV/EBITDA valuation multiple",
    ),
    "momentum_12_1": MetricSemantics(
        direction="higher_is_better",
        comparison_group="price_return",
        economic_meaning="12-1 price momentum",
    ),
    "momentum_6m": MetricSemantics(
        direction="higher_is_better",
        comparison_group="price_return",
        economic_meaning="six-month price momentum",
    ),
    "relative_strength_6m": MetricSemantics(
        direction="higher_is_better",
        comparison_group="price_return",
        economic_meaning="six-month relative strength",
    ),
    "volatility_adjusted_momentum_12_1": MetricSemantics(
        direction="higher_is_better",
        comparison_group="risk_adjusted_return",
        economic_meaning="volatility-adjusted momentum",
    ),
    "trend_stability_12m": MetricSemantics(
        direction="higher_is_better",
        comparison_group="trend_stability",
        economic_meaning="trend stability",
    ),
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


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
    universe_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    factor_dataset_hash: str = Field(pattern=SHA256_PATTERN)
    lineage_hash: str = Field(pattern=SHA256_PATTERN)
    observations: tuple[FactorObservation, ...]


@dataclass(frozen=True)
class QVMEvaluation:
    matrix: pd.DataFrame
    health: dict[str, Any]
    lineage: dict[str, Any]
    validation_report: dict[str, Any]


def factor_dataset_hash(observations: Sequence[FactorObservation]) -> str:
    return _sha256([item.model_dump(mode="json") for item in observations])


def qvm_lineage_identity(
    *,
    universe_snapshot_id: str,
    universe_snapshot_hash: str,
    factor_dataset_hashes: Mapping[str, str],
    as_of: datetime.date,
    availability_policy: str,
    entity_policy: str,
) -> dict[str, Any]:
    return {
        "schema_version": "qvm-lineage-identity-v1",
        "ruleset_version": QVM_RULESET_VERSION,
        "universe_snapshot": {"id": universe_snapshot_id, "hash": universe_snapshot_hash},
        "factor_dataset_hashes": dict(sorted(factor_dataset_hashes.items())),
        "as_of": as_of.isoformat(),
        "availability_policy": availability_policy,
        "entity_policy": entity_policy,
    }


def qvm_lineage_hash(**identity_parts: Any) -> str:
    return _sha256(qvm_lineage_identity(**identity_parts))


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
        symbol=str(row["symbol"]),
        factor=factor,
        metric=str(row["metric"]),
        value=value,
        unit=str(unit),
        as_of=as_of,
        available_at=pd.Timestamp(available).to_pydatetime(),
        confidence=float(row["confidence"]),
        lineage=lineage,
        universe_snapshot_id=universe_snapshot_id,
        status=str(row["status"]),
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
        "universe snapshot hash": {batch.universe_snapshot_hash for batch in batches},
        "lineage hash": {batch.lineage_hash for batch in batches},
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

    dataset_hashes = {batch.factor: factor_dataset_hash(batch.observations) for batch in batches}
    mismatched_datasets = sorted(
        batch.factor
        for batch in batches
        if batch.factor_dataset_hash != dataset_hashes[batch.factor]
    )
    if mismatched_datasets:
        raise ValueError(f"factor dataset hash mismatch: {', '.join(mismatched_datasets)}")
    common = batches[0]
    expected = qvm_lineage_hash(
        universe_snapshot_id=common.universe_snapshot_id,
        universe_snapshot_hash=common.universe_snapshot_hash,
        factor_dataset_hashes=dataset_hashes,
        as_of=common.as_of,
        availability_policy=common.availability_policy,
        entity_policy=common.entity_policy,
    )
    if any(batch.lineage_hash != expected for batch in batches):
        raise ValueError("QVM lineage hash mismatch")


def _metric_semantics(metric: str) -> MetricSemantics | None:
    return METRIC_SEMANTICS_REGISTRY.get(metric)


def _correlations(frame: pd.DataFrame) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    metrics = sorted(frame["metric"].unique())
    for left, right in combinations(metrics, 2):
        left_semantics = _metric_semantics(left)
        right_semantics = _metric_semantics(right)
        base = {"left_metric": left, "right_metric": right}
        if left_semantics is None or right_semantics is None:
            missing = sorted(
                metric
                for metric, semantics in ((left, left_semantics), (right, right_semantics))
                if semantics is None
            )
            diagnostics.append(
                base
                | {
                    "status": NOT_AVAILABLE,
                    "reason": f"metric semantics not registered: {', '.join(missing)}",
                    "correlation": None,
                }
            )
            continue
        if (
            left_semantics.comparison_group is None
            or left_semantics.comparison_group != right_semantics.comparison_group
        ):
            diagnostics.append(
                base
                | {
                    "status": NOT_AVAILABLE,
                    "reason": "metrics are not semantically comparable",
                    "correlation": None,
                }
            )
            continue
        pair = frame.loc[frame["metric"].isin((left, right)), ["symbol", "metric", "value"]]
        values = pair.pivot(index="symbol", columns="metric", values="value").dropna()
        if len(values) < 2:
            diagnostics.append(
                base
                | {
                    "status": NOT_AVAILABLE,
                    "reason": "fewer than two paired observations",
                    "correlation": None,
                }
            )
            continue
        correlation = values[left].corr(values[right])
        if pd.isna(correlation):
            diagnostics.append(
                base
                | {
                    "status": NOT_AVAILABLE,
                    "reason": "correlation is undefined for constant data",
                    "correlation": None,
                }
            )
            continue
        diagnostics.append(
            base
            | {
                "status": "AVAILABLE",
                "reason": None,
                "comparison_group": left_semantics.comparison_group,
                "observations": len(values),
                "correlation": float(correlation),
            }
        )
    return diagnostics


def _economic_conflicts(frame: pd.DataFrame) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for metric, group in frame.groupby("metric", sort=True):
        semantics = _metric_semantics(str(metric))
        if semantics is None:
            exclusions.append({"metric": str(metric), "reason": "metric semantics not registered"})
            continue
        if semantics.direction in {"contextual", "non_directional"}:
            exclusions.append(
                {
                    "metric": str(metric),
                    "reason": f"{semantics.direction} metrics have no economic direction",
                }
            )
            continue
        numeric = pd.to_numeric(group["value"], errors="coerce")
        reference = numeric.median()
        if pd.isna(reference):
            exclusions.append({"metric": str(metric), "reason": "no numeric observations"})
            continue
        for index, value in numeric.items():
            if pd.isna(value) or value == reference:
                continue
            direction = "positive" if value > reference else "negative"
            if semantics.direction == "lower_is_better":
                direction = "negative" if direction == "positive" else "positive"
            row = frame.loc[index]
            signals.append(
                {
                    "symbol": str(row["symbol"]),
                    "factor": str(row["factor"]),
                    "metric": str(metric),
                    "economic_signal": direction,
                    "reference": float(reference),
                    "meaning": semantics.economic_meaning,
                }
            )
    conflicts = []
    signal_frame = pd.DataFrame(signals)
    if not signal_frame.empty:
        for symbol, group in signal_frame.groupby("symbol", sort=True):
            by_factor = group.groupby("factor")["economic_signal"].agg(
                lambda values: sorted(set(values))
            )
            directional = {
                factor: values[0] for factor, values in by_factor.items() if len(values) == 1
            }
            if len(set(directional.values())) > 1:
                conflicts.append(
                    {
                        "symbol": str(symbol),
                        "factor_signals": directional,
                        "evidence": group.to_dict(orient="records"),
                    }
                )
    return {
        "status": "AVAILABLE",
        "conflicts": conflicts,
        "count": len(conflicts),
        "excluded_metrics": exclusions,
    }


def evaluate_qvm_research(batches: tuple[FactorBatch, ...]) -> QVMEvaluation:
    _validate_alignment(batches)
    rows = [
        observation.model_dump(mode="json")
        for batch in batches
        for observation in batch.observations
    ]
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
    status_matrix = long.pivot(index="symbol", columns="column", values="status").add_suffix(
        "__status"
    )
    matrix = value_matrix.join(status_matrix).sort_index(axis=1).reset_index()
    coverage = {
        factor: len(symbols) / len(governed_symbols) for factor, symbols in universe_sets.items()
    }
    missingness = {
        factor: float(group["value"].isna().mean())
        for factor, group in long.groupby("factor", sort=True)
    }
    sector = {}
    if long["sector"].notna().any():
        counts = (
            long.dropna(subset=["sector"])[["symbol", "sector"]]
            .drop_duplicates()["sector"]
            .value_counts()
        )
        sector = {str(name): int(count) for name, count in counts.sort_index().items()}
    diagnostics = {
        "coverage_by_factor": coverage,
        "missingness_by_factor": missingness,
        "universe_overlap": {
            "symbols": len(overlap),
            "ratio": len(overlap) / len(governed_symbols),
        },
        "metric_correlations": _correlations(long),
        "sector_concentration": sector or {"status": "NOT_AVAILABLE"},
        "factor_conflicts": _economic_conflicts(long),
    }
    health_status = (
        "PASS"
        if len(overlap) == len(governed_symbols) and not any(missingness.values())
        else "WARNING"
    )
    health = {
        "schema_version": "qvm-health-v1",
        "status": health_status,
        "observations": len(long),
        "symbols": len(governed_symbols),
        "diagnostics": diagnostics,
        "normalization": {
            "z_score": "metadata_only",
            "percentile": "metadata_only",
            "winsorization": "metadata_only",
        },
        "composite_score_calculated": False,
        "weights_assigned": False,
        "ranking_calculated": False,
        "portfolio_constructed": False,
        "backtest_executed": False,
        "signals_generated": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
    identity = qvm_lineage_identity(
        universe_snapshot_id=common.universe_snapshot_id,
        universe_snapshot_hash=common.universe_snapshot_hash,
        factor_dataset_hashes={batch.factor: batch.factor_dataset_hash for batch in batches},
        as_of=common.as_of,
        availability_policy=common.availability_policy,
        entity_policy=common.entity_policy,
    )
    lineage = {
        "schema_version": "qvm-lineage-v2",
        "identity": identity,
        "lineage_hash": common.lineage_hash,
        "factors": {
            batch.factor: [item.lineage for item in batch.observations] for batch in batches
        },
    }
    report = {
        "schema_version": "qvm-validation-report-v1",
        "status": health_status,
        "checks": {
            "common_contract": "PASS",
            "PIT_alignment": "PASS",
            "universe_alignment": "PASS",
            "availability_alignment": "PASS",
            "entity_alignment": "PASS",
            "lineage_alignment": "PASS",
            "individual_factor_preservation": "PASS",
        },
        "prohibited_outputs": {
            "score": False,
            "weights": False,
            "ranking": False,
            "selection": False,
            "portfolio": False,
            "backtest": False,
            "broker": False,
            "execution": False,
        },
    }
    return QVMEvaluation(matrix, health, lineage, report)
