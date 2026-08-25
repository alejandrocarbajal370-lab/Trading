from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

QUALITY_HYPOTHESIS = (
    "Companies with durable returns on invested capital, cash-backed earnings, stable margins, "
    "and prudent leverage exhibit higher operating quality. Phase 4.1 measures these attributes "
    "individually and does not assert or calculate an investment score."
)
QUALITY_RULESET_VERSION = "quality-v1.2"
DIRECT_METRICS = {
    "roic_v1": "roic",
    "free_cash_flow_margin": "fcf_margin",
    "cfo_to_net_income": "cfo_conversion",
    "net_debt_to_ebitda": "net_debt_to_ebitda",
    "accrual_ratio": "raw_accrual_ratio",
    "share_count_change": "share_count_change",
    "reinvestment_rate": "reinvestment_rate",
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
    "data_confidence",
    "calculation_confidence",
    "economic_confidence",
    "sector",
    "industry",
    "sector_percentile",
    "industry_percentile",
    "primary_source",
    "source_available_at",
    "source_fiscal_period_end",
    "pit_metadata",
    "warnings",
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
        "data_confidence",
        "calculation_confidence",
        "economic_confidence",
        "sector",
        "industry",
        "sector_percentile",
        "industry_percentile",
        "pit_metadata",
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
            name="raw_accrual_ratio",
            formula="(net_income - cash_from_operations) / total_assets",
            required_inputs=("accrual_ratio",),
        ),
        QualityMetricDefinition(
            name="margin_stability",
            formula="population standard deviation of comparable historical FCF margins",
            required_inputs=("free_cash_flow_margin history",),
        ),
        QualityMetricDefinition(
            name="roic_consistency",
            formula="positive ROIC periods / valid periods",
            required_inputs=("roic_v1 history",),
        ),
        QualityMetricDefinition(
            name="roic_positive_years",
            formula="count of positive ROIC periods",
            required_inputs=("roic_v1 history",),
        ),
        QualityMetricDefinition(
            name="fcf_consistency",
            formula="positive FCF-margin periods / valid periods",
            required_inputs=("free_cash_flow_margin history",),
        ),
        QualityMetricDefinition(
            name="fcf_positive_years",
            formula="count of positive FCF-margin periods",
            required_inputs=("free_cash_flow_margin history",),
        ),
        QualityMetricDefinition(
            name="margin_persistence",
            formula="non-declining FCF-margin transitions / comparable transitions",
            required_inputs=("free_cash_flow_margin history",),
        ),
        QualityMetricDefinition(
            name="share_count_change",
            formula="reported share-count change; no score",
            required_inputs=(),
            optional_inputs=("share_count_change",),
        ),
        QualityMetricDefinition(
            name="reinvestment_rate",
            formula="reported reinvestment metadata; no score",
            required_inputs=(),
            optional_inputs=("reinvestment_rate",),
        ),
    )
)


@dataclass(frozen=True)
class QualityEvaluation:
    metrics: pd.DataFrame
    health: dict[str, Any]


def _lineage(
    row: pd.Series, *, dataset_lineage: dict[str, Any]
) -> tuple[str, str | None, dict[str, Any]]:
    raw = row.get("input_lineage")
    try:
        inputs = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return (
            json.dumps({"dataset": dataset_lineage, "financial_inputs": []}, sort_keys=True),
            "invalid input_lineage JSON",
            {},
        )
    if (
        not isinstance(inputs, list)
        or not inputs
        or not all(isinstance(item, dict) and item for item in inputs)
    ):
        return (
            json.dumps({"dataset": dataset_lineage, "financial_inputs": []}, sort_keys=True),
            "input_lineage must be a non-empty list of objects",
            {},
        )
    source = inputs[0]
    if not (source.get("primary_source") or source.get("source")):
        return (
            json.dumps({"dataset": dataset_lineage, "financial_inputs": inputs}, sort_keys=True),
            "primary source missing from lineage",
            source,
        )
    return (
        json.dumps({"dataset": dataset_lineage, "financial_inputs": inputs}, sort_keys=True),
        None,
        source,
    )


def _confidence(row: pd.Series) -> tuple[float, float, float, float, str | None, str | None]:
    fallback = row.get("confidence")
    values: list[float] = []
    missing = invalid = False
    for name in ("data_confidence", "calculation_confidence", "economic_confidence"):
        raw = row.get(name, fallback)
        if raw is None or pd.isna(raw):
            missing, value = True, 0.0
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                invalid, value = True, 0.0
            if not math.isfinite(value) or not 0 <= value <= 1:
                invalid, value = True, 0.0
        values.append(value)
    if invalid:
        return (
            min(values),
            *values,
            "LOW_CONFIDENCE",
            "invalid confidence; expected finite values between 0 and 1",
        )
    if missing:
        return (
            min(values),
            *values,
            "MISSING_CONFIDENCE",
            "confidence is required and was missing or null",
        )
    return min(values), *values, None, None


def _quality_row(
    *,
    experiment_id: str,
    symbol: str,
    as_of: object,
    metric: str,
    value: float | None,
    status: str,
    reason: str | None,
    confidence: tuple[float, float, float, float, str | None, str | None],
    lineage: str,
    context: dict[str, Any],
    warnings: list[str] | None,
    low_confidence_threshold: float,
) -> dict[str, object]:
    (
        overall,
        data_confidence,
        calculation_confidence,
        economic_confidence,
        confidence_status,
        confidence_reason,
    ) = confidence
    if value is not None and not math.isfinite(float(value)):
        value, status, reason = None, "NOT_COMPUTED", "non-finite metric value"
    if status == "PASS" and confidence_status:
        status, reason = confidence_status, confidence_reason
    elif status == "PASS" and overall < low_confidence_threshold:
        status = "LOW_CONFIDENCE"
        reason = f"input confidence {overall:.4f} below {low_confidence_threshold:.4f}"
    warning_list = list(warnings or [])
    if metric == "roic" and value is not None and abs(float(value)) > 1:
        warning_list.append(f"extreme ROIC {value:.4f}; verify denominator and source economics")
    return {
        "experiment_id": experiment_id,
        "symbol": symbol,
        "as_of": str(as_of),
        "metric": metric,
        "value": value,
        "status": status,
        "reason": reason,
        "confidence": overall,
        "data_confidence": data_confidence,
        "calculation_confidence": calculation_confidence,
        "economic_confidence": economic_confidence,
        **context,
        "warnings": json.dumps(warning_list, sort_keys=True),
        "lineage": lineage,
    }


def _source_context(row: pd.Series, source: dict[str, Any]) -> dict[str, Any]:
    def clean(name: str) -> Any:
        value = row.get(name)
        return (
            None
            if value is None or (not isinstance(value, (dict, list)) and pd.isna(value))
            else value
        )

    pit = clean("pit_metadata")
    if isinstance(pit, str):
        try:
            pit = json.loads(pit)
        except json.JSONDecodeError:
            pit = {"unparsed": pit}
    return {
        "sector": clean("sector"),
        "industry": clean("industry"),
        "sector_percentile": clean("sector_percentile"),
        "industry_percentile": clean("industry_percentile"),
        "primary_source": source.get("primary_source") or source.get("source"),
        "source_available_at": source.get("available_at"),
        "source_fiscal_period_end": source.get("fiscal_period_end") or clean("fiscal_period_end"),
        "pit_metadata": json.dumps(pit or {}, sort_keys=True),
    }


def _evaluated_row(
    *, row: pd.Series, dataset_lineage: dict[str, Any], **kwargs: Any
) -> dict[str, object]:
    lineage, lineage_error, source = _lineage(row, dataset_lineage=dataset_lineage)
    if kwargs["status"] == "PASS" and lineage_error:
        kwargs["status"], kwargs["reason"] = "INVALID_LINEAGE", lineage_error
    return _quality_row(
        **kwargs,
        confidence=_confidence(row),
        lineage=lineage,
        context=_source_context(row, source),
        warnings=None,
    )


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
                _evaluated_row(
                    row=latest.iloc[0],
                    dataset_lineage=dataset_lineage,
                    experiment_id=experiment_id,
                    symbol=str(symbol),
                    as_of=latest_end,
                    metric=DIRECT_METRICS[str(source_metric)],
                    value=None,
                    status="NOT_COMPUTED",
                    reason=reason,
                    low_confidence_threshold=low_confidence_threshold,
                )
            )
            continue
        row = latest.iloc[0]
        output.append(
            _evaluated_row(
                row=row,
                dataset_lineage=dataset_lineage,
                experiment_id=experiment_id,
                symbol=str(symbol),
                as_of=latest_end,
                metric=DIRECT_METRICS[str(source_metric)],
                value=None if pd.isna(row["value"]) else float(row["value"]),
                status=str(row["status"]),
                reason=None if pd.isna(row["reason"]) else str(row["reason"]),
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
    specifications = {
        "roic_v1": (
            ("roic_stability", "stdev"),
            ("roic_consistency", "positive_ratio"),
            ("roic_positive_years", "positive_count"),
        ),
        "free_cash_flow_margin": (
            ("margin_stability", "stdev"),
            ("fcf_consistency", "positive_ratio"),
            ("fcf_positive_years", "positive_count"),
            ("margin_persistence", "nondeclining_ratio"),
        ),
    }
    for source_metric, calculations in specifications.items():
        selected = metrics[metrics["metric"] == source_metric]
        for symbol, history in selected.groupby("symbol", sort=True):
            history = history.sort_values("fiscal_period_end")
            as_of = history["fiscal_period_end"].max()
            reason: str | None = None
            status = "PASS"
            comparable_columns = [
                name for name in ("period_type", "period_basis") if name in history.columns
            ]
            if any(history[name].dropna().nunique() > 1 for name in comparable_columns):
                status, reason = "NOT_COMPUTED", "incompatible periods in metric history"
            elif history["fiscal_period_end"].duplicated().any():
                status, reason = "NOT_COMPUTED", "duplicate or conflicting metric history"
            elif any(
                _lineage(row, dataset_lineage=dataset_lineage)[1] for _, row in history.iterrows()
            ):
                status, reason = (
                    "INVALID_LINEAGE",
                    "history contains corrupt, empty, or invalid lineage",
                )
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
            anchor = history.iloc[-1].copy()
            history_confidences = [_confidence(row) for _, row in history.iterrows()]
            confidence_statuses = {item[4] for item in history_confidences}
            if "LOW_CONFIDENCE" in confidence_statuses:
                anchor["data_confidence"] = "invalid"
            elif "MISSING_CONFIDENCE" in confidence_statuses:
                anchor["data_confidence"] = None
            else:
                anchor["data_confidence"] = min(item[1] for item in history_confidences)
            anchor["calculation_confidence"] = min(item[2] for item in history_confidences)
            anchor["economic_confidence"] = min(item[3] for item in history_confidences)
            observation_lineage = [
                json.loads(_lineage(row, dataset_lineage=dataset_lineage)[0])
                for _, row in history.iterrows()
            ]
            for result_metric, method in calculations:
                metric_status, metric_reason, value = status, reason, None
                if metric_status == "PASS":
                    if method == "stdev":
                        value = statistics.pstdev(values)
                    elif method == "positive_ratio":
                        value = sum(item > 0 for item in values) / len(values)
                    elif method == "positive_count":
                        value = float(sum(item > 0 for item in values))
                    else:
                        value = sum(b >= a for a, b in pairwise(values)) / (len(values) - 1)
                evaluated = _evaluated_row(
                    row=anchor,
                    dataset_lineage=dataset_lineage,
                    experiment_id=experiment_id,
                    symbol=str(symbol),
                    as_of=as_of,
                    metric=result_metric,
                    value=value,
                    status=metric_status,
                    reason=metric_reason,
                    low_confidence_threshold=low_confidence_threshold,
                )
                evaluated["lineage"] = json.dumps(
                    {
                        "dataset": dataset_lineage,
                        "method": method,
                        "source_metric": source_metric,
                        "observations": observation_lineage,
                    },
                    sort_keys=True,
                )
                output.append(evaluated)
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
    expected = {
        definition.name for definition in QUALITY_CONTRACT.definitions if definition.required_inputs
    }
    for symbol, symbol_rows in metrics.groupby("symbol", sort=True):
        emitted = {str(row["metric"]) for row in rows if row["symbol"] == str(symbol)}
        as_of = symbol_rows["fiscal_period_end"].max()
        for metric in sorted(expected - emitted):
            rows.append(
                _evaluated_row(
                    row=symbol_rows.sort_values("fiscal_period_end").iloc[-1],
                    dataset_lineage=dataset_lineage,
                    experiment_id=experiment_id,
                    symbol=str(symbol),
                    as_of=as_of,
                    metric=metric,
                    value=None,
                    status="MISSING",
                    reason="required validated metric history is absent",
                    low_confidence_threshold=low_confidence_threshold,
                )
            )
    by_symbol: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), {})[str(row["metric"])] = row
    for symbol_rows in by_symbol.values():
        roic = symbol_rows.get("roic")
        leverage = symbol_rows.get("net_debt_to_ebitda")
        persistence = symbol_rows.get("margin_persistence")
        warnings: list[str] = []
        if (
            roic
            and leverage
            and roic["value"] is not None
            and leverage["value"] is not None
            and float(roic["value"]) >= 0.20
            and float(leverage["value"]) >= 4
        ):
            warnings.append("high ROIC conflicts with elevated leverage")
        if (
            roic
            and persistence
            and roic["value"] is not None
            and persistence["value"] is not None
            and float(roic["value"]) >= 0.20
            and float(persistence["value"]) < 0.5
        ):
            warnings.append("high ROIC conflicts with deteriorating margin persistence")
        if warnings:
            for row in symbol_rows.values():
                current = json.loads(str(row["warnings"]))
                row["warnings"] = json.dumps(sorted(set(current + warnings)))
    result = (
        pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        .sort_values(["symbol", "metric"])
        .reset_index(drop=True)
    )
    counts = result["status"].value_counts().to_dict()
    warning_records = sum(bool(json.loads(value)) for value in result["warnings"])
    passed = int(counts.get("PASS", 0))
    if result.empty or passed == 0:
        status = "FAIL"
    elif passed == len(result) and warning_records == 0:
        status = "PASS"
    else:
        status = "WARNING"
    return QualityEvaluation(
        metrics=result,
        health={
            "status": status,
            "records": len(result),
            "metric_status_counts": counts,
            "warning_records": warning_records,
            "composite_score_calculated": False,
            "weights_assigned": False,
            "is_investment_signal": False,
            "governance_mode": "research_legacy",
            "phase6_eligible": False,
            "sector_normalization": "metadata-only; no ranking or score",
            "capital_allocation_foundation": {
                "share_count_change": "optional input",
                "reinvestment_rate": "optional input",
                "m_and_a": "documented placeholder",
            },
        },
    )
