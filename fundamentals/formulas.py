from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FormulaResult:
    value: float | None
    status: str
    reason: str | None = None


def _finite_inputs(**inputs: float) -> FormulaResult | None:
    invalid = [name for name, value in inputs.items() if not math.isfinite(value)]
    if invalid:
        return FormulaResult(None, "NOT_COMPUTED", f"non-finite input: {', '.join(invalid)}")
    return None


def subtract(left: float, right: float) -> FormulaResult:
    if invalid := _finite_inputs(left=left, right=right):
        return invalid
    value = left - right
    return FormulaResult(value, "PASS")


def free_cash_flow(cfo: float, capital_expenditures: float) -> FormulaResult:
    """CFO less CapEx, where CapEx is a positive cash-outflow magnitude."""
    if invalid := _finite_inputs(cfo=cfo, capital_expenditures=capital_expenditures):
        return invalid
    if capital_expenditures < 0:
        return FormulaResult(
            None, "NOT_COMPUTED", "capital_expenditures must be a non-negative outflow magnitude"
        )
    return FormulaResult(cfo - capital_expenditures, "PASS")


def ratio(numerator: float, denominator: float, *, denominator_name: str) -> FormulaResult:
    if invalid := _finite_inputs(numerator=numerator, denominator=denominator):
        return invalid
    if denominator == 0:
        return FormulaResult(None, "NOT_COMPUTED", f"{denominator_name} is zero")
    return FormulaResult(numerator / denominator, "PASS")


def positive_denominator_ratio(
    numerator: float, denominator: float, *, denominator_name: str
) -> FormulaResult:
    if invalid := _finite_inputs(numerator=numerator, denominator=denominator):
        return invalid
    if denominator <= 0:
        return FormulaResult(None, "NOT_COMPUTED", f"{denominator_name} must be positive")
    return FormulaResult(numerator / denominator, "PASS")


def roic_v1(
    operating_income: float,
    tax_rate: float,
    total_debt: float,
    total_equity: float,
    cash: float,
) -> FormulaResult:
    """Return NOPAT / invested capital; IC = debt + equity - cash."""
    if invalid := _finite_inputs(
        operating_income=operating_income,
        tax_rate=tax_rate,
        total_debt=total_debt,
        total_equity=total_equity,
        cash=cash,
    ):
        return invalid
    if not 0 <= tax_rate <= 1:
        return FormulaResult(None, "NOT_COMPUTED", "tax_rate must be between 0 and 1")
    nopat = operating_income * (1 - tax_rate)
    invested_capital = total_debt + total_equity - cash
    if invested_capital <= 0:
        return FormulaResult(None, "NOT_COMPUTED", "invested capital must be positive")
    return FormulaResult(nopat / invested_capital, "PASS")
