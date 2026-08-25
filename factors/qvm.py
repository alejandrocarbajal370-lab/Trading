from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from governance.canonical import typed_hash
from governance.pre_phase6 import (
    APPLICABILITY_POLICY_VERSION,
    STATUS_TAXONOMY_VERSION,
    GovernedStatus,
    governed_status,
    metric_applicability,
)

FACTOR_NAMES = ("Quality", "Value", "Momentum")
QVM_RULESET_VERSION = "qvm-research-v1.1"
NOT_AVAILABLE = "NOT_AVAILABLE"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class MetricSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: Literal["Quality", "Value", "Momentum"]
    metric: str
    expected_unit: str
    direction: Literal["higher_is_better", "lower_is_better", "contextual", "non_directional"]
    comparison_group: str | None
    economic_meaning: str


def _semantics(
    factor: Literal["Quality", "Value", "Momentum"],
    metric: str,
    expected_unit: str,
    direction: Literal["higher_is_better", "lower_is_better", "contextual", "non_directional"],
    comparison_group: str | None,
    economic_meaning: str,
) -> MetricSemantics:
    return MetricSemantics(
        factor=factor,
        metric=metric,
        expected_unit=expected_unit,
        direction=direction,
        comparison_group=comparison_group,
        economic_meaning=economic_meaning,
    )


METRIC_SEMANTICS_REGISTRY: Mapping[tuple[str, str], MetricSemantics] = {
    (item.factor, item.metric): item
    for item in (
        _semantics(
            "Quality",
            "roic",
            "percentage",
            direction="higher_is_better",
            comparison_group="profitability_ratio",
            economic_meaning="return on invested capital",
        ),
        _semantics(
            "Quality",
            "roic_stability",
            "ratio",
            direction="lower_is_better",
            comparison_group="stability_ratio",
            economic_meaning="ROIC dispersion",
        ),
        _semantics(
            "Quality",
            "fcf_margin",
            "percentage",
            direction="higher_is_better",
            comparison_group="profitability_ratio",
            economic_meaning="free-cash-flow margin",
        ),
        _semantics(
            "Quality",
            "cfo_conversion",
            "ratio",
            direction="higher_is_better",
            comparison_group="cash_conversion_ratio",
            economic_meaning="cash conversion",
        ),
        _semantics(
            "Quality",
            "net_debt_to_ebitda",
            "multiple",
            direction="lower_is_better",
            comparison_group="leverage_multiple",
            economic_meaning="net debt relative to EBITDA",
        ),
        _semantics(
            "Quality",
            "raw_accrual_ratio",
            "ratio",
            direction="lower_is_better",
            comparison_group="cash_conversion_ratio",
            economic_meaning="raw accrual ratio: (net income - CFO) / assets; lower is better",
        ),
        _semantics(
            "Quality",
            "margin_stability",
            "ratio",
            direction="lower_is_better",
            comparison_group="stability_ratio",
            economic_meaning="free-cash-flow margin dispersion",
        ),
        _semantics(
            "Quality",
            "roic_consistency",
            "ratio",
            direction="higher_is_better",
            comparison_group="consistency_ratio",
            economic_meaning="share of periods with positive ROIC",
        ),
        _semantics(
            "Quality",
            "roic_positive_years",
            "count",
            direction="higher_is_better",
            comparison_group="positive_period_count",
            economic_meaning="count of positive ROIC periods",
        ),
        _semantics(
            "Quality",
            "fcf_consistency",
            "ratio",
            direction="higher_is_better",
            comparison_group="consistency_ratio",
            economic_meaning="share of periods with positive free-cash-flow margin",
        ),
        _semantics(
            "Quality",
            "fcf_positive_years",
            "count",
            direction="higher_is_better",
            comparison_group="positive_period_count",
            economic_meaning="count of positive free-cash-flow periods",
        ),
        _semantics(
            "Quality",
            "margin_persistence",
            "ratio",
            direction="higher_is_better",
            comparison_group="consistency_ratio",
            economic_meaning="share of non-declining margin transitions",
        ),
        _semantics(
            "Quality",
            "share_count_change",
            "ratio",
            direction="contextual",
            comparison_group=None,
            economic_meaning="reported change in shares outstanding",
        ),
        _semantics(
            "Quality",
            "reinvestment_rate",
            "ratio",
            direction="contextual",
            comparison_group=None,
            economic_meaning="reported reinvestment rate",
        ),
        _semantics(
            "Value",
            "fcf_yield",
            "ratio",
            direction="higher_is_better",
            comparison_group="valuation_yield",
            economic_meaning="free-cash-flow yield",
        ),
        _semantics(
            "Value",
            "earnings_yield",
            "ratio",
            direction="higher_is_better",
            comparison_group="valuation_yield",
            economic_meaning="earnings yield",
        ),
        _semantics(
            "Value",
            "ebit_yield",
            "ratio",
            direction="higher_is_better",
            comparison_group="valuation_yield",
            economic_meaning="EBIT yield",
        ),
        _semantics(
            "Value",
            "ev_to_ebit",
            "multiple",
            direction="lower_is_better",
            comparison_group="valuation_multiple",
            economic_meaning="EV/EBIT valuation multiple",
        ),
        _semantics(
            "Value",
            "ev_to_ebitda",
            "multiple",
            direction="lower_is_better",
            comparison_group="valuation_multiple",
            economic_meaning="EV/EBITDA valuation multiple",
        ),
        _semantics(
            "Momentum",
            "momentum_12_1",
            "return",
            direction="higher_is_better",
            comparison_group="price_return",
            economic_meaning="12-1 price momentum",
        ),
        _semantics(
            "Momentum",
            "momentum_6m",
            "return",
            direction="higher_is_better",
            comparison_group="price_return",
            economic_meaning="six-month price momentum",
        ),
        _semantics(
            "Momentum",
            "relative_strength_6m",
            "return",
            direction="higher_is_better",
            comparison_group="price_return",
            economic_meaning="six-month relative strength",
        ),
        _semantics(
            "Momentum",
            "volatility_adjusted_momentum_12_1",
            "return_per_volatility",
            direction="higher_is_better",
            comparison_group="risk_adjusted_return",
            economic_meaning="volatility-adjusted momentum",
        ),
        _semantics(
            "Momentum",
            "trend_stability_12m",
            "r_squared",
            direction="higher_is_better",
            comparison_group="trend_stability",
            economic_meaning="trend stability",
        ),
    )
}

METRIC_SEMANTICS_REGISTRY_VERSION = "qvm-metric-semantics-registry-v1"


def metric_semantics_registry_identity() -> str:
    """Identity of the single canonical QVM metric-semantics authority."""
    return typed_hash(
        {
            "schema_version": METRIC_SEMANTICS_REGISTRY_VERSION,
            "metrics": tuple(
                METRIC_SEMANTICS_REGISTRY[key]
                for key in sorted(METRIC_SEMANTICS_REGISTRY)
            ),
        }
    )


def validate_observation_semantics(observation: FactorObservation) -> MetricSemantics:
    """Fail closed when a sealed observation is not registered exactly."""
    semantics = METRIC_SEMANTICS_REGISTRY.get((observation.factor, observation.metric))
    if semantics is None:
        registered_factors = {
            factor for factor, metric in METRIC_SEMANTICS_REGISTRY if metric == observation.metric
        }
        if registered_factors:
            raise ValueError(
                f"metric {observation.metric} is not registered for factor {observation.factor}"
            )
        raise ValueError(
            f"unknown metric semantics: {observation.factor}.{observation.metric}"
        )
    if observation.unit != semantics.expected_unit:
        raise ValueError(
            f"unit mismatch for {observation.factor}.{observation.metric}: "
            f"expected {semantics.expected_unit}, got {observation.unit}"
        )
    return semantics

ECONOMIC_DIAGNOSTIC_ELIGIBLE_STATUSES = frozenset({"PASS"})


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
    status: GovernedStatus
    reason: str | None = None
    sector: str | None = None
    industry: str | None = None
    applicability: Literal["APPLICABLE", "NOT_APPLICABLE", "REVIEW"] = "APPLICABLE"
    applicability_policy_version: Literal["sector-applicability-v1"] = (
        APPLICABILITY_POLICY_VERSION
    )
    status_taxonomy_version: Literal["factor-status-taxonomy-v1"] = STATUS_TAXONOMY_VERSION
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
        status = governed_status(self.status)
        expected = metric_applicability(self.metric, self.sector, self.industry)
        if self.applicability != expected.state:
            raise ValueError("observation applicability does not match governed policy")
        if expected.state != "APPLICABLE" and status != GovernedStatus.NOT_APPLICABLE:
            raise ValueError("non-applicable observation must use NOT_APPLICABLE")
        if status == GovernedStatus.NOT_APPLICABLE and self.value is not None:
            raise ValueError("NOT_APPLICABLE observations cannot carry a value")
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
    documents = sorted(
        (item.model_dump(mode="python") for item in observations),
        key=lambda item: (str(item["symbol"]), str(item["metric"]), str(item["factor"])),
    )
    return typed_hash({"schema_version": "factor-dataset-identity-v2", "observations": documents})


def factor_observation_hash(observation: FactorObservation) -> str:
    return typed_hash(
        {
            "schema_version": "factor-observation-identity-v2",
            "observation": observation,
        }
    )


def factor_batch_identity(batch: FactorBatch) -> str:
    return typed_hash(
        {
            "schema_version": "factor-batch-identity-v2",
            "factor": batch.factor,
            "universe_snapshot_id": batch.universe_snapshot_id,
            "universe_snapshot_hash": batch.universe_snapshot_hash,
            "as_of": batch.as_of,
            "availability_policy": batch.availability_policy,
            "entity_policy": batch.entity_policy,
            "factor_dataset_hash": batch.factor_dataset_hash,
            "lineage_hash": batch.lineage_hash,
        }
    )


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
    return typed_hash(qvm_lineage_identity(**identity_parts))


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
        semantics = METRIC_SEMANTICS_REGISTRY.get((factor, str(row["metric"])))
        if semantics is None:
            raise ValueError(f"metric semantics not registered: {factor}.{row['metric']}")
        unit = semantics.expected_unit
    value = row.get("value")
    value = None if value is None or pd.isna(value) else float(value)
    applicability = metric_applicability(
        str(row["metric"]),
        None if pd.isna(row.get("sector")) else str(row.get("sector")),
        None if pd.isna(row.get("industry")) else str(row.get("industry")),
    )
    status = governed_status(row["status"])
    if applicability.state != "APPLICABLE":
        status = GovernedStatus.NOT_APPLICABLE
        value = None
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
        status=status,
        reason=(
            applicability.reason
            if applicability.state != "APPLICABLE"
            else None if pd.isna(row.get("reason")) else str(row.get("reason"))
        ),
        sector=None if pd.isna(row.get("sector")) else str(row.get("sector")),
        industry=None if pd.isna(row.get("industry")) else str(row.get("industry")),
        applicability=applicability.state,
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


def _metric_semantics(factor: str, metric: str) -> MetricSemantics | None:
    return METRIC_SEMANTICS_REGISTRY.get((factor, metric))


def _validate_metric_semantics(frame: pd.DataFrame) -> None:
    for row in frame.itertuples():
        semantics = _metric_semantics(str(row.factor), str(row.metric))
        if semantics is None:
            raise ValueError(f"metric semantics not registered: {row.factor}.{row.metric}")
        if str(row.unit) != semantics.expected_unit:
            raise ValueError(
                "metric unit does not match semantics registry: "
                f"{row.factor}.{row.metric} expected {semantics.expected_unit}, got {row.unit}"
            )


def _correlations(frame: pd.DataFrame) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    eligible = frame.loc[frame["status"].isin(ECONOMIC_DIAGNOSTIC_ELIGIBLE_STATUSES)]
    metrics = sorted(set(zip(eligible["factor"], eligible["metric"], strict=False)))
    for left, right in combinations(metrics, 2):
        left_semantics = _metric_semantics(*left)
        right_semantics = _metric_semantics(*right)
        assert left_semantics is not None and right_semantics is not None
        base = {
            "left_factor": left[0],
            "left_metric": left[1],
            "right_factor": right[0],
            "right_metric": right[1],
        }
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
        left_values = eligible.loc[
            (eligible["factor"] == left[0]) & (eligible["metric"] == left[1]),
            ["symbol", "value"],
        ].set_index("symbol")["value"]
        right_values = eligible.loc[
            (eligible["factor"] == right[0]) & (eligible["metric"] == right[1]),
            ["symbol", "value"],
        ].set_index("symbol")["value"]
        values = pd.concat([left_values, right_values], axis=1).dropna()
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
        correlation = values.iloc[:, 0].corr(values.iloc[:, 1])
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
    ineligible = frame.loc[~frame["status"].isin(ECONOMIC_DIAGNOSTIC_ELIGIBLE_STATUSES)]
    for row in ineligible.itertuples():
        exclusions.append(
            {
                "factor": str(row.factor),
                "metric": str(row.metric),
                "reason": f"status {row.status} is not eligible for economic diagnostics",
            }
        )
    eligible = frame.loc[frame["status"].isin(ECONOMIC_DIAGNOSTIC_ELIGIBLE_STATUSES)]
    for (factor, metric), group in eligible.groupby(["factor", "metric"], sort=True):
        semantics = _metric_semantics(str(factor), str(metric))
        assert semantics is not None
        if semantics.direction in {"contextual", "non_directional"}:
            exclusions.append(
                {
                    "factor": str(factor),
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
                    "economic_direction": direction,
                    "reference": float(reference),
                    "meaning": semantics.economic_meaning,
                }
            )
    conflicts = []
    signal_frame = pd.DataFrame(signals)
    if not signal_frame.empty:
        for symbol, group in signal_frame.groupby("symbol", sort=True):
            by_factor = group.groupby("factor")["economic_direction"].agg(
                lambda values: sorted(set(values))
            )
            directional = {
                factor: values[0] for factor, values in by_factor.items() if len(values) == 1
            }
            if len(set(directional.values())) > 1:
                conflicts.append(
                    {
                        "symbol": str(symbol),
                        "factor_diagnostics": directional,
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
    _validate_metric_semantics(long)
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
    eligible = long.loc[
        long["status"].isin(ECONOMIC_DIAGNOSTIC_ELIGIBLE_STATUSES) & long["value"].notna()
    ]
    coverage = {
        factor: eligible.loc[eligible["factor"] == factor, "symbol"].nunique()
        / len(governed_symbols)
        for factor in FACTOR_NAMES
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
        "economic_diagnostic_eligibility": {
            "eligible_statuses": sorted(ECONOMIC_DIAGNOSTIC_ELIGIBLE_STATUSES),
            "ineligible_observations": int(len(long) - len(eligible)),
        },
        "sector_concentration": sector or {"status": "NOT_AVAILABLE"},
        "factor_conflicts": _economic_conflicts(long),
    }
    health_status = (
        "PASS"
        if (
            len(overlap) == len(governed_symbols)
            and not any(missingness.values())
            and len(eligible) == len(long)
        )
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
        "governance_mode": "research_legacy",
        "phase6_eligible": False,
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
