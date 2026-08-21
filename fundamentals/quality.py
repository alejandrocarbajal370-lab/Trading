from __future__ import annotations

import pandas as pd

from fundamentals.financial_engine import calculate_financial_metrics

QUALITY_COLUMNS = ["symbol", "fiscal_period_end", "check", "value", "status", "warning"]


def evaluate_accounting_quality(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Diagnostic accounting checks derived with the same period/unit rules as Phase 3."""
    metrics = calculate_financial_metrics(snapshot)
    rows: list[dict[str, object]] = []
    specifications = {
        "cfo_to_net_income": ("cfo_to_net_income", lambda value: value < 0.5, "weak cash conversion (<0.5)"),
        "accrual_ratio": ("accrual_ratio", lambda value: value > 0.1, "high positive accruals (>0.1)"),
    }
    for source_metric, (check, warning_rule, warning_text) in specifications.items():
        selected = metrics.loc[metrics["metric"] == source_metric]
        if selected.empty:
            continue
        for row in selected.itertuples(index=False):
            status = str(row.status)
            warning = row.reason
            value = None if pd.isna(row.value) else float(row.value)
            if status == "PASS" and value is not None and warning_rule(value):
                status = "WARNING"
                warning = warning_text
            rows.append(
                {
                    "symbol": row.symbol,
                    "fiscal_period_end": row.fiscal_period_end,
                    "check": check,
                    "value": value,
                    "status": status,
                    "warning": warning,
                }
            )
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def accounting_quality_health(checks: pd.DataFrame) -> dict[str, object]:
    warnings = int(checks["status"].eq("WARNING").sum()) if not checks.empty else 0
    invalid = (
        int(checks["status"].isin(["MISSING", "NOT_COMPUTED"]).sum()) if not checks.empty else 0
    )
    failures = int(checks["status"].eq("FAIL").sum()) if not checks.empty else 0
    if checks.empty or failures:
        status = "FAIL"
    elif warnings or invalid:
        status = "WARNING"
    else:
        status = "PASS"
    return {
        "status": status,
        "checks": len(checks),
        "warnings": warnings,
        "invalid": invalid,
        "failures": failures,
        "is_investment_signal": False,
    }
