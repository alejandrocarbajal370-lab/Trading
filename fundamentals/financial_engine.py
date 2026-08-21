from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from fundamentals.formulas import (
    FormulaResult,
    free_cash_flow,
    positive_denominator_ratio,
    ratio,
    roic_v1,
    subtract,
)


@dataclass(frozen=True)
class MetricDefinition:
    inputs: tuple[str, ...]
    result_unit: str
    basis_input: str


DEFINITIONS = {
    "free_cash_flow": MetricDefinition(
        ("cash_from_operations", "capital_expenditures"), "input_currency", "cash_from_operations"
    ),
    "free_cash_flow_margin": MetricDefinition(
        ("cash_from_operations", "capital_expenditures", "revenue"),
        "ratio",
        "cash_from_operations",
    ),
    "net_debt": MetricDefinition(("total_debt", "cash"), "input_currency", "total_debt"),
    "net_debt_to_ebitda": MetricDefinition(("total_debt", "cash", "ebitda"), "ratio", "ebitda"),
    "cfo_to_net_income": MetricDefinition(
        ("cash_from_operations", "net_income"), "ratio", "cash_from_operations"
    ),
    "accrual_ratio": MetricDefinition(
        ("net_income", "cash_from_operations", "total_assets"), "ratio", "net_income"
    ),
    "roic_v1": MetricDefinition(
        ("operating_income", "tax_rate", "total_debt", "total_equity", "cash"),
        "ratio",
        "operating_income",
    ),
}

OUTPUT_COLUMNS = [
    "symbol",
    "fiscal_period_start",
    "fiscal_period_end",
    "period_type",
    "period_basis",
    "metric",
    "value",
    "unit",
    "result_unit",
    "status",
    "reason",
    "confidence",
    "input_lineage",
]
FLOW_INPUTS = {
    "cash_from_operations",
    "capital_expenditures",
    "revenue",
    "net_income",
    "operating_income",
    "ebitda",
}
INSTANT_INPUTS = {"total_debt", "cash", "total_equity", "total_assets"}


def _calculate(metric: str, values: dict[str, float]) -> FormulaResult:
    if metric == "free_cash_flow":
        return free_cash_flow(values["cash_from_operations"], values["capital_expenditures"])
    if metric == "free_cash_flow_margin":
        fcf = free_cash_flow(values["cash_from_operations"], values["capital_expenditures"])
        if fcf.status != "PASS":
            return fcf
        assert fcf.value is not None
        return ratio(fcf.value, values["revenue"], denominator_name="revenue")
    if metric == "net_debt":
        return subtract(values["total_debt"], values["cash"])
    if metric == "net_debt_to_ebitda":
        net_debt = subtract(values["total_debt"], values["cash"])
        if net_debt.status != "PASS":
            return net_debt
        assert net_debt.value is not None
        return positive_denominator_ratio(
            net_debt.value, values["ebitda"], denominator_name="ebitda"
        )
    if metric == "cfo_to_net_income":
        return ratio(
            values["cash_from_operations"], values["net_income"], denominator_name="net_income"
        )
    if metric == "accrual_ratio":
        return ratio(
            values["net_income"] - values["cash_from_operations"],
            values["total_assets"],
            denominator_name="total_assets",
        )
    return roic_v1(
        values["operating_income"],
        values["tax_rate"],
        values["total_debt"],
        values["total_equity"],
        values["cash"],
    )


def _period_key(row: pd.Series) -> tuple[object, object, object]:
    return (row["fiscal_period_start"], row["fiscal_period_end"], row["period_type"])


def _validation_reason(rows: dict[str, pd.Series]) -> str | None:
    for name, row in rows.items():
        expected = (
            "duration" if name in FLOW_INPUTS else "instant" if name in INSTANT_INPUTS else None
        )
        if expected and row["period_type"] != expected:
            return f"invalid period_type for {name}: expected {expected}"
    flows = [rows[name] for name in rows if name in FLOW_INPUTS]
    if len({_period_key(row) for row in flows}) > 1:
        return "incompatible accounting periods"
    if flows:
        flow_end = flows[0]["fiscal_period_end"]
        if any(
            rows[name]["fiscal_period_end"] != flow_end for name in rows if name in INSTANT_INPUTS
        ):
            return "incompatible accounting periods: balance date must equal flow period_end"
    units = {name: row["unit"] for name, row in rows.items()}
    currency_names = [name for name in rows if name != "tax_rate"]
    if len({units[name] for name in currency_names}) > 1:
        return "incompatible units"
    if "tax_rate" in units and units["tax_rate"] != "RATIO":
        return "tax_rate unit must be RATIO"
    return None


def _input_confidence(rows: dict[str, pd.Series]) -> float | None:
    values: list[float] = []
    for row in rows.values():
        if "confidence" not in row.index or pd.isna(row["confidence"]):
            return None
        value = float(row["confidence"])
        if not 0 <= value <= 1:
            return None
        values.append(value)
    return min(values) if values else None


def calculate_financial_metrics(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Calculate auditable PIT metrics; flow results are never annualized."""
    if snapshot.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    output: list[dict[str, object]] = []
    grouped = snapshot.groupby(["symbol", "fiscal_period_end"], sort=True, dropna=False)
    for (symbol, period_end), group in grouped:
        symbol_metrics = set(snapshot.loc[snapshot["symbol"] == symbol, "metric"])
        by_metric = {name: part for name, part in group.groupby("metric", sort=False)}
        for metric, definition in DEFINITIONS.items():
            missing = sorted(set(definition.inputs) - set(by_metric))
            displaced = sorted(set(missing) & symbol_metrics)
            repeated = sorted(
                name for name in definition.inputs if name in by_metric and len(by_metric[name]) > 1
            )
            conflicting = sorted(
                name for name in repeated if by_metric[name]["value"].nunique() > 1
            )
            rows = {
                name: by_metric[name].iloc[-1] for name in definition.inputs if name in by_metric
            }
            reason: str | None = None
            status = "PASS"
            value: float | None = None
            if conflicting:
                status, reason = "NOT_COMPUTED", f"conflicting inputs: {', '.join(conflicting)}"
            elif repeated:
                status, reason = (
                    "NOT_COMPUTED",
                    f"duplicate or ambiguous inputs: {', '.join(repeated)}",
                )
            elif displaced:
                status, reason = "NOT_COMPUTED", "incompatible accounting periods"
            elif missing:
                status, reason = "MISSING", f"missing inputs: {', '.join(missing)}"
            elif reason := _validation_reason(rows):
                status = "NOT_COMPUTED"
            else:
                result = _calculate(
                    metric, {name: float(row["value"]) for name, row in rows.items()}
                )
                value, status, reason = result.value, result.status, result.reason
            basis = rows.get(definition.basis_input)
            result_unit = (
                "RATIO"
                if definition.result_unit == "ratio"
                else (basis["unit"] if basis is not None else None)
            )
            lineage = [
                {
                    "metric": name,
                    "source": row["source"],
                    "available_at": pd.Timestamp(row["available_at"]).isoformat(),
                    "unit": row["unit"],
                    "fiscal_period_start": None
                    if pd.isna(row["fiscal_period_start"])
                    else str(row["fiscal_period_start"]),
                    "fiscal_period_end": str(row["fiscal_period_end"]),
                    "period_type": row["period_type"],
                    "confidence": None
                    if "confidence" not in row.index or pd.isna(row["confidence"])
                    else float(row["confidence"]),
                }
                for name, row in rows.items()
            ]
            output.append(
                {
                    "symbol": symbol,
                    "fiscal_period_start": None
                    if basis is None or pd.isna(basis["fiscal_period_start"])
                    else basis["fiscal_period_start"],
                    "fiscal_period_end": period_end,
                    "period_type": None if basis is None else basis["period_type"],
                    "period_basis": None
                    if basis is None
                    else (
                        "instant"
                        if basis["period_type"] == "instant"
                        else "period (not annualized)"
                    ),
                    "metric": metric,
                    "value": value,
                    "unit": result_unit,
                    "result_unit": result_unit,
                    "status": status,
                    "reason": reason,
                    "confidence": _input_confidence(rows),
                    "input_lineage": json.dumps(lineage, sort_keys=True),
                }
            )
    return pd.DataFrame(output, columns=OUTPUT_COLUMNS)


def financial_health(metrics: pd.DataFrame, *, snapshot_empty: bool = False) -> dict[str, object]:
    counts = metrics["status"].value_counts().to_dict() if not metrics.empty else {}
    passed = int(counts.get("PASS", 0))
    if snapshot_empty or metrics.empty or passed == 0:
        status = "FAIL"
    elif passed == len(metrics):
        status = "PASS"
    else:
        status = "WARNING"
    return {"status": status, "metric_status_counts": counts, "records": len(metrics)}
