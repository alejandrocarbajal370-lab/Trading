from __future__ import annotations

import datetime
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

VALUE_HYPOTHESIS = (
    "Valuation ratios describe the price paid for reported business economics. Phase 4.2 "
    "measures absolute value conservatively and preserves relative-value context as metadata; "
    "it does not claim that a low multiple is an investment opportunity."
)
VALUE_RULESET_VERSION = "value-v1.0"
RESTRICTED_EV_INDUSTRIES = (
    "bank",
    "banking",
    "capital markets",
    "consumer finance",
    "diversified financial",
    "financial services",
    "insurance",
    "reit",
)
INPUT_METRICS = ("free_cash_flow", "earnings", "ebit", "ebitda", "market_cap", "enterprise_value")
OUTPUT_COLUMNS = [
    "experiment_id",
    "symbol",
    "as_of",
    "metric",
    "value_category",
    "value",
    "unit",
    "currency",
    "period_basis",
    "status",
    "reason",
    "confidence",
    "source_available_at",
    "industry",
    "warnings",
    "lineage",
    "owner_earnings_context",
    "historical_valuation_context",
    "sector_relative_context",
    "quality_context",
]


class ValueContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValueMetricDefinition(ValueContractModel):
    name: str
    formula: str
    numerator: str
    denominator: str
    unit: Literal["ratio", "multiple"]
    primary: bool = True


class ValueFactorContract(ValueContractModel):
    version: str = VALUE_RULESET_VERSION
    hypothesis: str = VALUE_HYPOTHESIS
    required_dataset_columns: tuple[str, ...] = (
        "symbol",
        "valuation_as_of",
        "fiscal_period_end",
        "period_basis",
        "metric",
        "value",
        "unit",
        "currency",
        "available_at",
        "status",
        "reason",
        "confidence",
        "input_lineage",
        "industry",
    )
    definitions: tuple[ValueMetricDefinition, ...]
    absolute_value_metrics: tuple[str, ...]
    relative_value_mode: Literal["metadata_only"] = "metadata_only"
    composite_score: Literal[False] = False
    ranking_calculated: Literal[False] = False


VALUE_CONTRACT = ValueFactorContract(
    definitions=(
        ValueMetricDefinition(name="fcf_yield", formula="free_cash_flow / market_cap", numerator="free_cash_flow", denominator="market_cap", unit="ratio"),
        ValueMetricDefinition(name="earnings_yield", formula="earnings / market_cap", numerator="earnings", denominator="market_cap", unit="ratio"),
        ValueMetricDefinition(name="ebit_yield", formula="ebit / enterprise_value", numerator="ebit", denominator="enterprise_value", unit="ratio"),
        ValueMetricDefinition(name="ev_to_ebit", formula="enterprise_value / ebit", numerator="enterprise_value", denominator="ebit", unit="multiple"),
        ValueMetricDefinition(name="ev_to_ebitda", formula="enterprise_value / ebitda", numerator="enterprise_value", denominator="ebitda", unit="multiple", primary=False),
    ),
    absolute_value_metrics=("fcf_yield", "earnings_yield", "ebit_yield", "ev_to_ebit", "ev_to_ebitda"),
)


@dataclass(frozen=True)
class ValueEvaluation:
    metrics: pd.DataFrame
    health: dict[str, Any]
    lineage: dict[str, Any]
    validation_report: dict[str, Any]


def _clean(value: Any) -> Any:
    return None if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)) else value


def _fail(status: str, reason: str, *, warnings: list[str] | None = None) -> dict[str, Any]:
    return {"value": None, "status": status, "reason": reason, "warnings": warnings or []}


def _parse_lineage(row: pd.Series) -> tuple[list[dict[str, Any]], str | None]:
    raw = _clean(row.get("input_lineage"))
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return [], "input_lineage is not valid JSON"
    if not isinstance(parsed, list) or not parsed or not all(isinstance(item, dict) and item for item in parsed):
        return [], "input_lineage must be a non-empty list of objects"
    if any(not (item.get("source") or item.get("primary_source")) for item in parsed):
        return parsed, "primary source missing from lineage"
    return parsed, None


def _confidence(rows: tuple[pd.Series, pd.Series]) -> tuple[float, str | None]:
    values: list[float] = []
    for row in rows:
        raw = _clean(row.get("confidence"))
        if raw is None:
            return 0.0, "confidence is required"
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.0, "confidence must be numeric between 0 and 1"
        if not math.isfinite(value) or not 0 <= value <= 1:
            return 0.0, "confidence must be finite and between 0 and 1"
        values.append(value)
    return min(values), None


def _pit_error(rows: tuple[pd.Series, pd.Series], as_of: datetime.date) -> str | None:
    cutoff = datetime.datetime.combine(as_of, datetime.time.max, tzinfo=datetime.UTC)
    for row in rows:
        try:
            available = pd.Timestamp(row["available_at"])
        except (TypeError, ValueError):
            return "available_at is invalid"
        if available.tzinfo is None:
            return "available_at must be timezone-aware"
        if available.to_pydatetime().astimezone(datetime.UTC) > cutoff:
            return "PIT violation: input available_at exceeds valuation as_of"
    return None


def _select(metrics: pd.DataFrame, symbol: str, metric: str) -> tuple[pd.Series | None, str | None]:
    candidates = metrics[(metrics["symbol"].astype(str) == symbol) & (metrics["metric"] == metric)]
    if candidates.empty:
        return None, f"missing input: {metric}"
    latest_end = candidates["fiscal_period_end"].astype(str).max()
    latest = candidates[candidates["fiscal_period_end"].astype(str) == latest_end]
    if len(latest) != 1:
        return None, f"duplicate or conflicting input: {metric}"
    return latest.iloc[0], None


def _evaluate_definition(
    definition: ValueMetricDefinition,
    *,
    metrics: pd.DataFrame,
    symbol: str,
    experiment_id: str,
    as_of: datetime.date,
    dataset_lineage: dict[str, Any],
    low_confidence_threshold: float,
) -> dict[str, Any]:
    numerator, numerator_error = _select(metrics, symbol, definition.numerator)
    denominator, denominator_error = _select(metrics, symbol, definition.denominator)
    base = {
        "experiment_id": experiment_id,
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "metric": definition.name,
        "value_category": "ABSOLUTE",
        "unit": definition.unit,
        "currency": None,
        "period_basis": None,
        "confidence": 0.0,
        "source_available_at": None,
        "industry": None,
        "lineage": json.dumps({"dataset": dataset_lineage, "financial_inputs": []}, sort_keys=True),
        "owner_earnings_context": "metadata_only" if definition.name == "fcf_yield" else None,
        "historical_valuation_context": "not_implemented",
        "sector_relative_context": "metadata_only",
        "quality_context": "future_linkage_required",
    }
    error = numerator_error or denominator_error
    if error:
        result = _fail("MISSING", error)
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    assert numerator is not None and denominator is not None
    rows = (numerator, denominator)
    industry = str(_clean(numerator.get("industry")) or _clean(denominator.get("industry")) or "")
    base["industry"] = industry or None
    base["source_available_at"] = max(str(row["available_at"]) for row in rows)
    statuses = [(str(row["status"]), _clean(row.get("reason"))) for row in rows if row["status"] != "PASS"]
    if statuses:
        result = _fail(statuses[0][0], str(statuses[0][1] or "upstream input is not PASS"))
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    currencies = {str(_clean(row.get("currency")) or "") for row in rows}
    units = {str(_clean(row.get("unit")) or "") for row in rows}
    if "" in currencies or len(currencies) != 1:
        result = _fail("INVALID_CURRENCY", "inputs require the same explicit currency")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    if units != {"currency"}:
        result = _fail("INVALID_UNIT", "valuation inputs must use unit=currency")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    base["currency"] = next(iter(currencies))
    flow_rows = [row for row in rows if row["metric"] not in ("market_cap", "enterprise_value")]
    instant_rows = [row for row in rows if row["metric"] in ("market_cap", "enterprise_value")]
    if any(str(row["period_basis"]).upper() not in {"FY", "TTM"} for row in flow_rows):
        result = _fail("PERIOD_MISMATCH", "flow inputs require period_basis FY or TTM")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    if any(str(row["period_basis"]).upper() != "INSTANT" for row in instant_rows):
        result = _fail("PERIOD_MISMATCH", "market value inputs require period_basis INSTANT")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    base["period_basis"] = str(flow_rows[0]["period_basis"]).upper()
    lineage: list[dict[str, Any]] = []
    for row in rows:
        parsed, lineage_error = _parse_lineage(row)
        lineage.extend(parsed)
        if lineage_error:
            result = _fail("INVALID_LINEAGE", lineage_error)
            return {**base, **result, "warnings": json.dumps(result["warnings"])}
    base["lineage"] = json.dumps({"dataset": dataset_lineage, "financial_inputs": lineage}, sort_keys=True)
    confidence, confidence_error = _confidence(rows)
    base["confidence"] = confidence
    if confidence_error:
        result = _fail("MISSING_CONFIDENCE", confidence_error)
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    pit_error = _pit_error(rows, as_of)
    if pit_error:
        result = _fail("PIT_VIOLATION", pit_error)
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    uses_ev = definition.denominator == "enterprise_value" or definition.numerator == "enterprise_value"
    if uses_ev and any(term in industry.lower() for term in RESTRICTED_EV_INDUSTRIES):
        result = _fail("INDUSTRY_RESTRICTED", "EV metrics are not appropriate for this industry")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    numerator_value, denominator_value = float(numerator["value"]), float(denominator["value"])
    if not math.isfinite(numerator_value) or not math.isfinite(denominator_value):
        result = _fail("NOT_COMPUTED", "non-finite valuation input")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    ev_rows = [row for row in rows if row["metric"] == "enterprise_value"]
    if ev_rows and float(ev_rows[0]["value"]) <= 0:
        result = _fail("INVALID_DENOMINATOR", "enterprise_value must be positive")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    if definition.name == "ev_to_ebit" and denominator_value < 0:
        result = _fail(
            "WARNING",
            "negative EBIT makes EV/EBIT economically uninterpretable",
            warnings=["negative EBIT is operating stress context, not a normal value signal"],
        )
        return {**base, **result, "warnings": json.dumps(result["warnings"], sort_keys=True)}
    if denominator_value <= 0:
        result = _fail("INVALID_DENOMINATOR", f"{definition.denominator} must be positive")
        return {**base, **result, "warnings": json.dumps(result["warnings"])}
    value = numerator_value / denominator_value
    warnings: list[str] = []
    status, reason = "PASS", None
    if definition.name == "fcf_yield" and numerator_value < 0:
        status, reason = "WARNING", "negative FCF is financial stress context, not a normal value signal"
        warnings.append("reported FCF may differ from maintenance-capex-adjusted owner earnings")
    if definition.name == "earnings_yield" and numerator_value < 0:
        status, reason = (
            "WARNING",
            "negative earnings are loss-making context, not a normal value signal",
        )
        warnings.append("earnings yield is not economically comparable while earnings are negative")
    if definition.name == "ebit_yield" and numerator_value < 0:
        status, reason = (
            "WARNING",
            "negative EBIT is operating stress context, not a normal value signal",
        )
        warnings.append("EBIT yield is not economically comparable while EBIT is negative")
    if definition.name == "ev_to_ebitda":
        warnings.append("secondary metric: EBITDA ignores capital intensity and depreciation economics")
    extreme = abs(value) > (1 if definition.unit == "ratio" else 100)
    if extreme:
        status = "WARNING"
        reason = reason or "economically extreme valuation; verify source economics and denominator"
        warnings.append("economic sanity check flagged an extreme multiple")
    if confidence < low_confidence_threshold and status == "PASS":
        status, reason = "LOW_CONFIDENCE", f"input confidence {confidence:.4f} below {low_confidence_threshold:.4f}"
    return {**base, "value": value, "status": status, "reason": reason, "warnings": json.dumps(warnings, sort_keys=True)}


def evaluate_value_metrics(
    metrics: pd.DataFrame,
    *,
    experiment_id: str,
    dataset_lineage: dict[str, Any],
    low_confidence_threshold: float = 0.7,
) -> ValueEvaluation:
    if not math.isfinite(low_confidence_threshold) or not 0 <= low_confidence_threshold <= 1:
        raise ValueError("low_confidence_threshold must be finite and between 0 and 1")
    missing = sorted(set(VALUE_CONTRACT.required_dataset_columns) - set(metrics.columns))
    if missing:
        raise ValueError(f"missing value input columns: {', '.join(missing)}")
    if metrics.empty:
        raise ValueError("value input dataset is empty")
    symbols = sorted(metrics["symbol"].dropna().astype(str).unique())
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_rows = metrics[metrics["symbol"].astype(str) == symbol]
        try:
            valuation_dates = symbol_rows["valuation_as_of"].dropna().astype(str).unique()
            if len(valuation_dates) != 1:
                raise ValueError("valuation_as_of must be identical for all symbol inputs")
            as_of = datetime.date.fromisoformat(valuation_dates[0])
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid valuation_as_of for {symbol}: {error}") from error
        for definition in VALUE_CONTRACT.definitions:
            rows.append(_evaluate_definition(
                definition, metrics=metrics, symbol=symbol, experiment_id=experiment_id,
                as_of=as_of, dataset_lineage=dataset_lineage,
                low_confidence_threshold=low_confidence_threshold,
            ))
    output = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values(["symbol", "metric"]).reset_index(drop=True)
    counts = {str(key): int(value) for key, value in output["status"].value_counts().sort_index().items()}
    invalid = int((~output["status"].isin(["PASS", "WARNING"])).sum())
    health_status = "FAIL" if invalid else ("WARNING" if (output["status"] == "WARNING").any() else "PASS")
    health = {
        "schema_version": "value-health-v1",
        "status": health_status,
        "observations": len(output),
        "status_counts": counts,
        "absolute_value_calculated": True,
        "relative_value_calculated": False,
        "composite_score_calculated": False,
        "ranking_calculated": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "governance_mode": "research_legacy",
        "phase6_eligible": False,
    }
    lineage = {
        "schema_version": "value-lineage-v1",
        "dataset": dataset_lineage,
        "metrics": [
            {"symbol": row["symbol"], "metric": row["metric"], "lineage": json.loads(row["lineage"])}
            for row in rows
        ],
    }
    validation_report = {
        "schema_version": "value-validation-report-v1",
        "status": health_status,
        "checks": {
            "contracts": "implemented",
            "currency_and_units": "implemented",
            "period_compatibility": "implemented",
            "point_in_time": "implemented",
            "economic_sanity": "implemented",
            "industry_restrictions": "implemented",
            "historical_context": "foundation_only",
            "sector_relative_validation": "foundation_only",
            "quality_context": "future_linkage",
        },
        "errors": invalid,
        "warnings": int((output["status"] == "WARNING").sum()),
    }
    return ValueEvaluation(output, health, lineage, validation_report)
