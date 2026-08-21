from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

QUALITY_HYPOTHESIS = (
    "Companies with durable returns on invested capital, cash-backed earnings, stable margins, "
    "and prudent leverage exhibit higher operating quality. Phase 4.1 measures these attributes "
    "individually and does not assert or calculate an investment score."
)
QUALITY_RULESET_VERSION = "quality-v1.0"
DIRECT_METRICS = {
    "roic_v1": "roic",
    "free_cash_flow_margin": "fcf_margin",
    "cfo_to_net_income": "cfo_conversion",
    "net_debt_to_ebitda": "net_debt_to_ebitda",
    "accrual_ratio": "accrual_quality",
}
OUTPUT_COLUMNS = [
    "experiment_id",
    "symbol",
    "as_of",
    "metric",
    "value",
    "status",
    "reason",
    "confidence",
    "lineage",
]


class QualityContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QualityMetricDefinition(QualityContractModel):
    name: str
    formula: str
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...] = ()


class QualityFactorContract(QualityContractModel):
    version: str = QUALITY_RULESET_VERSION
    hypothesis: str = QUALITY_HYPOTHESIS
    required_dataset_columns: tuple[str, ...] = (
        "symbol",
        "fiscal_period_end",
        "metric",
        "value",
        "status",
        "reason",
        "input_lineage",
    )
    optional_dataset_columns: tuple[str, ...] = (
        "period_type",
        "period_basis",
        "confidence",
    )
    definitions: tuple[QualityMetricDefinition, ...]
    output_fields: tuple[str, ...] = tuple(OUTPUT_COLUMNS)
    composite_score: Literal[False] = False
    weights: None = None


QUALITY_CONTRACT = QualityFactorContract(
    definitions=(
        QualityMetricDefinition(
            name="roic",
            formula="operating_income * (1 - tax_rate) / (total_debt + total_equity - cash)",
            required_inputs=("roic_v1",),
        ),
        QualityMetricDefinition(
            name="roic_stability",
            formula="population standard deviation of comparable historical ROIC observations",
            required_inputs=("roic_v1 history",),
        ),
        QualityMetricDefinition(
            name="fcf_margin",
            formula="(cash_from_operations - capital_expenditures) / revenue",
            required_inputs=("free_cash_flow_margin",),
        ),
        QualityMetricDefinition(
            name="cfo_conversion",
            formula="cash_from_operations / net_income",
            required_inputs=("cfo_to_net_income",),
        ),
        QualityMetricDefinition(
            name="net_debt_to_ebitda",
            formula="(total_debt - cash) / EBITDA",
            required_inputs=("net_debt_to_ebitda",),
        ),
        QualityMetricDefinition(
            name="accrual_quality",
            formula="(net_income - cash_from_operations) / total_assets",
            required_inputs=("accrual_ratio",),
        ),
        QualityMetricDefinition(
            name="margin_stability",
            formula="population standard deviation of comparable historical FCF margins",
            required_inputs=("free_cash_flow_margin history",),
        ),
    )
)


@dataclass(frozen=True)
class QualityEvaluation:
    metrics: pd.DataFrame
    health: dict[str, Any]


def _lineage(row: pd.Series, *, dataset_lineage: dict[str, Any]) -> str:
    raw = row.get("input_lineage", "[]")
    try:
        inputs = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        inputs = [{"unparsed_input_lineage": str(raw)}]
    return json.dumps({"dataset": dataset_lineage, "financial_inputs": inputs}, sort_keys=True)


def _confidence(row: pd.Series) -> float:
    value = row.get("confidence", 1.0)
    if pd.isna(value):
        return 1.0
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("confidence must be finite and between 0 and 1")
    return result


def _quality_row(
    *,
    experiment_id: str,
    symbol: str,
    as_of: object,
    metric: str,
    value: float | None,
    status: str,
    reason: str | None,
    confidence: float,
    lineage: str,
    low_confidence_threshold: float,
) -> dict[str, object]:
    if value is not None and not math.isfinite(float(value)):
        value, status, reason = None, "NOT_COMPUTED", "non-finite metric value"
    if status == "PASS" and confidence < low_confidence_threshold:
        status = "LOW_CONFIDENCE"
        reason = f"input confidence {confidence:.4f} below {low_confidence_threshold:.4f}"
    return {
        "experiment_id": experiment_id,
        "symbol": symbol,
        "as_of": str(as_of),
        "metric": metric,
        "value": value,
        "status": status,
        "reason": reason,
        "confidence": confidence,
        "lineage": lineage,
    }


def _validate_input(metrics: pd.DataFrame) -> None:
    missing = sorted(set(QUALITY_CONTRACT.required_dataset_columns) - set(metrics.columns))
    if missing:
        raise ValueError(f"missing quality input columns: {', '.join(missing)}")
    if metrics.empty:
        raise ValueError("quality input dataset is empty")


def _direct_rows(
    metrics: pd.DataFrame,
    *,
    experiment_id: str,
    dataset_lineage: dict[str, Any],
    low_confidence_threshold: float,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    relevant = metrics[metrics["metric"].isin(DIRECT_METRICS)]
    for (symbol, source_metric), history in relevant.groupby(["symbol", "metric"], sort=True):
        latest_end = history["fiscal_period_end"].max()
        latest = history[history["fiscal_period_end"] == latest_end]
        values = latest["value"].dropna().astype(float)
        if len(latest) > 1:
            conflicting = values.nunique() > 1 or latest["status"].nunique() > 1
            reason = (
                "conflicting metrics for the same symbol, metric, and period"
                if conflicting
                else "duplicate metric for the same symbol, metric, and period"
            )
            output.append(
                _quality_row(
                    experiment_id=experiment_id,
                    symbol=str(symbol),
                    as_of=latest_end,
                    metric=DIRECT_METRICS[str(source_metric)],
                    value=None,
                    status="NOT_COMPUTED",
                    reason=reason,
                    confidence=min(_confidence(row) for _, row in latest.iterrows()),
                    lineage=json.dumps(
                        {
                            "dataset": dataset_lineage,
                            "duplicate_rows": [
                                json.loads(_lineage(row, dataset_lineage=dataset_lineage))
                                for _, row in latest.iterrows()
                            ],
                        },
                        sort_keys=True,
                    ),
                    low_confidence_threshold=low_confidence_threshold,
                )
            )
            continue
        row = latest.iloc[0]
        output.append(
            _quality_row(
                experiment_id=experiment_id,
                symbol=str(symbol),
                as_of=latest_end,
                metric=DIRECT_METRICS[str(source_metric)],
                value=None if pd.isna(row["value"]) else float(row["value"]),
                status=str(row["status"]),
                reason=None if pd.isna(row["reason"]) else str(row["reason"]),
                confidence=_confidence(row),
                lineage=_lineage(row, dataset_lineage=dataset_lineage),
                low_confidence_threshold=low_confidence_threshold,
            )
        )
    return output


def _stability_rows(
    metrics: pd.DataFrame,
    *,
    experiment_id: str,
    dataset_lineage: dict[str, Any],
    low_confidence_threshold: float,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for source_metric, result_metric in (
        ("roic_v1", "roic_stability"),
        ("free_cash_flow_margin", "margin_stability"),
    ):
        selected = metrics[metrics["metric"] == source_metric]
        for symbol, history in selected.groupby("symbol", sort=True):
            history = history.sort_values("fiscal_period_end")
            as_of = history["fiscal_period_end"].max()
            confidence = min(_confidence(row) for _, row in history.iterrows())
            reason: str | None = None
            status = "PASS"
            value: float | None = None
            comparable_columns = [
                name for name in ("period_type", "period_basis") if name in history.columns
            ]
            if any(history[name].dropna().nunique() > 1 for name in comparable_columns):
                status, reason = "NOT_COMPUTED", "incompatible periods in metric history"
            elif history["fiscal_period_end"].duplicated().any():
                status, reason = "NOT_COMPUTED", "duplicate or conflicting metric history"
            elif not history["status"].eq("PASS").all():
                bad = history.loc[~history["status"].eq("PASS")].iloc[-1]
                status = str(bad["status"])
                reason = (
                    f"history contains invalid observation: {bad['reason']}"
                    if not pd.isna(bad["reason"])
                    else "history contains invalid observation"
                )
            else:
                values = history["value"].dropna().astype(float).tolist()
                if len(values) < 2:
                    status, reason = "MISSING", "at least two historical observations are required"
                elif not all(math.isfinite(item) for item in values):
                    status, reason = "NOT_COMPUTED", "non-finite value in metric history"
                else:
                    value = statistics.pstdev(values)
            lineage = json.dumps(
                {
                    "dataset": dataset_lineage,
                    "method": "population_standard_deviation",
                    "source_metric": source_metric,
                    "observations": [
                        json.loads(_lineage(row, dataset_lineage=dataset_lineage))
                        for _, row in history.iterrows()
                    ],
                },
                sort_keys=True,
            )
            output.append(
                _quality_row(
                    experiment_id=experiment_id,
                    symbol=str(symbol),
                    as_of=as_of,
                    metric=result_metric,
                    value=value,
                    status=status,
                    reason=reason,
                    confidence=confidence,
                    lineage=lineage,
                    low_confidence_threshold=low_confidence_threshold,
                )
            )
    return output


def evaluate_quality_metrics(
    metrics: pd.DataFrame,
    *,
    experiment_id: str,
    dataset_lineage: dict[str, Any],
    low_confidence_threshold: float = 0.7,
) -> QualityEvaluation:
    """Measure Quality V1 attributes without aggregating, weighting, ranking, or signaling."""
    _validate_input(metrics)
    if not 0 <= low_confidence_threshold <= 1:
        raise ValueError("low_confidence_threshold must be between 0 and 1")
    rows = _direct_rows(
        metrics,
        experiment_id=experiment_id,
        dataset_lineage=dataset_lineage,
        low_confidence_threshold=low_confidence_threshold,
    )
    rows.extend(
        _stability_rows(
            metrics,
            experiment_id=experiment_id,
            dataset_lineage=dataset_lineage,
            low_confidence_threshold=low_confidence_threshold,
        )
    )
    expected = set(DIRECT_METRICS.values()) | {"roic_stability", "margin_stability"}
    for symbol, symbol_rows in metrics.groupby("symbol", sort=True):
        emitted = {str(row["metric"]) for row in rows if row["symbol"] == str(symbol)}
        as_of = symbol_rows["fiscal_period_end"].max()
        for metric in sorted(expected - emitted):
            rows.append(
                _quality_row(
                    experiment_id=experiment_id,
                    symbol=str(symbol),
                    as_of=as_of,
                    metric=metric,
                    value=None,
                    status="MISSING",
                    reason="required validated metric history is absent",
                    confidence=0.0,
                    lineage=json.dumps(
                        {"dataset": dataset_lineage, "financial_inputs": []},
                        sort_keys=True,
                    ),
                    low_confidence_threshold=low_confidence_threshold,
                )
            )
    result = (
        pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        .sort_values(["symbol", "metric"])
        .reset_index(drop=True)
    )
    counts = result["status"].value_counts().to_dict()
    passed = int(counts.get("PASS", 0))
    if result.empty or passed == 0:
        status = "FAIL"
    elif passed == len(result):
        status = "PASS"
    else:
        status = "WARNING"
    return QualityEvaluation(
        metrics=result,
        health={
            "status": status,
            "records": len(result),
            "metric_status_counts": counts,
            "composite_score_calculated": False,
            "weights_assigned": False,
            "is_investment_signal": False,
        },
    )
