from __future__ import annotations

import pandas as pd

SOURCE_CONFIDENCE = {"sec": 1.0, "sec_fixture": 1.0, "manual_fixture": 0.8}


def metric_confidence(records: pd.DataFrame) -> pd.DataFrame:
    """Data confidence, never expected return or investment conviction."""
    rows: list[dict[str, object]] = []
    keys = ["symbol", "fiscal_period_start", "fiscal_period_end", "period_type", "metric"]
    for identity, group in records.groupby(keys, dropna=False):
        source = min(SOURCE_CONFIDENCE.get(str(item), 0.6) for item in group["source"])
        completeness = 1.0 - float(group.iloc[-1].isna().mean())
        conflict = group["value"].nunique() > 1 and group["available_at"].nunique() == 1
        validation = 1.0 if pd.to_numeric(group["value"], errors="coerce").notna().all() else 0.0
        score = round(
            max(
                0.0,
                min(
                    1.0,
                    0.4 * source + 0.25 * completeness + 0.2 * (not conflict) + 0.15 * validation,
                ),
            ),
            4,
        )
        rows.append(
            dict(
                zip(keys, identity, strict=True),
                confidence=score,
                source_quality=source,
                completeness=round(completeness, 4),
                conflict=bool(conflict),
                validation=validation,
            )
        )
    return pd.DataFrame(rows)
