from __future__ import annotations

import pandas as pd

from fundamentals.formulas import ratio

QUALITY_COLUMNS = ["symbol", "fiscal_period_end", "check", "value", "status", "warning"]


def evaluate_accounting_quality(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Diagnostic accounting checks only; outputs are not investment signals."""
    rows: list[dict[str, object]] = []
    for (symbol, period_end), group in snapshot.groupby(["symbol", "fiscal_period_end"]):
        values = group.set_index("metric")["value"].to_dict()
        if not {"cash_from_operations", "net_income"} <= values.keys():
            rows.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period_end,
                    "check": "cfo_to_net_income",
                    "value": None,
                    "status": "MISSING",
                    "warning": "requires cash_from_operations and net_income",
                }
            )
        else:
            result = ratio(
                values["cash_from_operations"], values["net_income"], denominator_name="net_income"
            )
            warning = result.value is not None and result.value < 0.5
            rows.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period_end,
                    "check": "cfo_to_net_income",
                    "value": result.value,
                    "status": "WARNING" if warning else result.status,
                    "warning": "weak cash conversion (<0.5)" if warning else result.reason,
                }
            )
        required = {"net_income", "cash_from_operations", "total_assets"}
        if not required <= values.keys():
            rows.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period_end,
                    "check": "accrual_ratio",
                    "value": None,
                    "status": "MISSING",
                    "warning": "requires net_income, cash_from_operations, and total_assets",
                }
            )
        else:
            result = ratio(
                values["net_income"] - values["cash_from_operations"],
                values["total_assets"],
                denominator_name="total_assets",
            )
            warning = result.value is not None and result.value > 0.1
            rows.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period_end,
                    "check": "accrual_ratio",
                    "value": result.value,
                    "status": "WARNING" if warning else result.status,
                    "warning": "high positive accruals (>0.1)" if warning else result.reason,
                }
            )
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def accounting_quality_health(checks: pd.DataFrame) -> dict[str, object]:
    warnings = int(checks["status"].eq("WARNING").sum()) if not checks.empty else 0
    invalid = (
        int(checks["status"].isin(["MISSING", "NOT_COMPUTED"]).sum()) if not checks.empty else 0
    )
    return {
        "status": "WARNING" if warnings or invalid else "PASS",
        "checks": len(checks),
        "warnings": warnings,
        "invalid": invalid,
        "is_investment_signal": False,
    }
