from __future__ import annotations

import hashlib
import json

import pandas as pd


class PeriodAssemblyError(ValueError):
    pass


def classify_period(start: object, end: object, period_type: str) -> str:
    if period_type == "instant":
        return "instant"
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    if 80 <= days <= 100:
        return "quarterly"
    if 350 <= days <= 380:
        return "fy"
    return "ytd"


def _fact_identity(row: pd.Series) -> dict[str, str]:
    fields = {
        "symbol": str(row["symbol"]),
        "metric": str(row["metric"]),
        "unit": str(row["unit"]),
        "fiscal_period_start": str(row["fiscal_period_start"]),
        "fiscal_period_end": str(row["fiscal_period_end"]),
        "filed_at": pd.Timestamp(row["filed_at"]).isoformat(),
        "available_at": pd.Timestamp(row["available_at"]).isoformat(),
        "source": str(row["source"]),
    }
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return {"fact_id": hashlib.sha256(payload.encode()).hexdigest(), **fields}


def assemble_ttm(quarterly: pd.DataFrame, *, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Sum four contiguous, non-overlapping quarter facts available by cutoff."""
    eligible = quarterly[
        (quarterly["available_at"] <= cutoff) & quarterly["period_type"].eq("duration")
    ].copy()
    eligible = eligible[
        eligible.apply(
            lambda row: (
                classify_period(
                    row["fiscal_period_start"], row["fiscal_period_end"], row["period_type"]
                )
                == "quarterly"
            ),
            axis=1,
        )
    ]
    identity = ["symbol", "metric", "unit", "fiscal_period_start", "fiscal_period_end"]
    eligible = eligible.sort_values(identity + ["available_at", "filed_at"]).drop_duplicates(
        identity, keep="last"
    )
    rows: list[dict[str, object]] = []
    for (symbol, metric, unit), group in eligible.groupby(["symbol", "metric", "unit"]):
        group = group.sort_values("fiscal_period_end").tail(4)
        if len(group) != 4:
            continue
        starts = pd.to_datetime(group["fiscal_period_start"]).tolist()
        ends = pd.to_datetime(group["fiscal_period_end"]).tolist()
        if any((starts[index] - ends[index - 1]).days != 1 for index in range(1, 4)):
            raise PeriodAssemblyError(f"non-contiguous quarters for {symbol}/{metric}")
        row = group.iloc[-1].to_dict()
        row.update(
            fiscal_period_start=group.iloc[0]["fiscal_period_start"],
            period_kind="ttm",
            value=float(group["value"].sum()),
            filed_at=group["filed_at"].max(),
            available_at=group["available_at"].max(),
            source="ttm_assembly",
            component_lineage=[_fact_identity(component) for _, component in group.iterrows()],
        )
        rows.append(row)
    return pd.DataFrame(rows)
