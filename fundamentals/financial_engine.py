from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from fundamentals.formulas import (
    FormulaResult,
    positive_denominator_ratio,
    ratio,
    roic_v1,
    subtract,
)


@dataclass(frozen=True)
class MetricDefinition:
    inputs: tuple[str, ...]


DEFINITIONS = {
    "free_cash_flow": MetricDefinition(("cash_from_operations", "capital_expenditures")),
    "free_cash_flow_margin": MetricDefinition(
        ("cash_from_operations", "capital_expenditures", "revenue")
    ),
    "net_debt": MetricDefinition(("total_debt", "cash")),
    "net_debt_to_ebitda": MetricDefinition(("total_debt", "cash", "ebitda")),
    "cfo_to_net_income": MetricDefinition(("cash_from_operations", "net_income")),
    "roic_v1": MetricDefinition(
        ("operating_income", "tax_rate", "total_debt", "total_equity", "cash")
    ),
}


def _calculate(metric: str, values: dict[str, float]) -> FormulaResult:
    if metric == "free_cash_flow":
        return subtract(values["cash_from_operations"], values["capital_expenditures"])
    if metric == "free_cash_flow_margin":
        fcf = subtract(values["cash_from_operations"], values["capital_expenditures"])
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
    return roic_v1(
        values["operating_income"],
        values["tax_rate"],
        values["total_debt"],
        values["total_equity"],
        values["cash"],
    )


def calculate_financial_metrics(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Calculate V1 metrics from an already-selected point-in-time snapshot."""
    output: list[dict[str, object]] = []
    group_columns = ["symbol", "fiscal_period_end"]
    for (symbol, period), group in snapshot.groupby(group_columns, sort=True):
        duplicates = group[group.duplicated("metric", keep=False)]
        conflicts = set(
            duplicates.groupby("metric")["value"].nunique().loc[lambda values: values > 1].index
        )
        duplicate_names = set(duplicates["metric"])
        facts = group.drop_duplicates("metric", keep="last").set_index("metric")
        for metric, definition in DEFINITIONS.items():
            required = set(definition.inputs)
            conflicting = sorted(required & conflicts)
            repeated = sorted((required & duplicate_names) - conflicts)
            missing = sorted(required - set(facts.index))
            reason = None
            status = "PASS"
            result_value: float | None = None
            if conflicting:
                status, reason = "NOT_COMPUTED", f"conflicting inputs: {', '.join(conflicting)}"
            elif repeated:
                status, reason = "NOT_COMPUTED", f"duplicate inputs: {', '.join(repeated)}"
            elif missing:
                status, reason = "MISSING", f"missing inputs: {', '.join(missing)}"
            else:
                values = {name: float(facts.loc[name, "value"]) for name in definition.inputs}
                result = _calculate(metric, values)
                result_value, status, reason = result.value, result.status, result.reason
            lineage = []
            for name in definition.inputs:
                if name in facts.index:
                    row = facts.loc[name]
                    lineage.append(
                        {
                            "metric": name,
                            "source": row["source"],
                            "available_at": pd.Timestamp(row["available_at"]).isoformat(),
                        }
                    )
            output.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period,
                    "metric": metric,
                    "value": result_value,
                    "status": status,
                    "reason": reason,
                    "input_lineage": json.dumps(lineage, sort_keys=True),
                }
            )
    return pd.DataFrame(output)
