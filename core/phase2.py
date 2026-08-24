from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.phase0 import _git_commit
from core.run_context import RunContext, build_run_context
from fundamentals.confidence import metric_confidence
from fundamentals.csv_source import CsvFundamentalSource
from fundamentals.history import preserve_version_history
from fundamentals.pit import assert_point_in_time, select_point_in_time
from fundamentals.source import FundamentalSource, normalize_data_timestamp
from monitoring.manifest import ValidationManifest, write_manifest


@dataclass(frozen=True)
class Phase2Result:
    context: RunContext
    snapshot: pd.DataFrame
    output_dir: Path


def _write_failure(
    *, context: RunContext, output_dir: Path, source_name: str, error: Exception
) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = {
        "run_id": context.run_id,
        "fundamental_source": source_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "overall_status": "FAIL",
        "fundamental_health": "NOT_RUN",
        "live_execution_enabled": False,
        "trade_decision": "NO_TRADE",
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    write_manifest(
        ValidationManifest(
            context=context,
            overall_status="FAIL",
            critical_errors=1,
            warnings=0,
            checks={
                "fundamental_source": "FAIL",
                "fundamental_health": "NOT_RUN",
                "point_in_time": "FAIL" if "PIT violation" in str(error) else "NOT_RUN",
                "live_execution": "DISABLED",
                "trade_decision": "NO_TRADE",
            },
        ),
        output_dir,
    )


def _attach_confidence(
    snapshot: pd.DataFrame, history: pd.DataFrame, *, data_date: datetime.date | datetime.datetime
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach PIT-safe data confidence to the selected economic facts."""
    cutoff = normalize_data_timestamp(data_date)
    eligible_history = history.loc[history["available_at"] <= cutoff].copy()
    confidence = metric_confidence(eligible_history)
    if snapshot.empty:
        result = snapshot.copy()
        result["confidence"] = pd.Series(dtype=float)
        return result, confidence
    keys = ["symbol", "fiscal_period_start", "fiscal_period_end", "period_type", "metric"]
    enriched = snapshot.merge(
        confidence[keys + ["confidence"]], on=keys, how="left", validate="one_to_one"
    )
    return enriched, confidence


def run_phase2(
    *,
    symbols: set[str],
    data_date: datetime.date | datetime.datetime,
    fundamental_source: FundamentalSource | None = None,
    source_path: Path | None = None,
    output_root: Path = Path("validation_outputs"),
    now: datetime.datetime | None = None,
) -> Phase2Result:
    date_label = data_date.isoformat()
    context = build_run_context(
        mode="validation",
        model_version="phase2-fundamentals-pit-v0.2",
        git_commit=_git_commit(),
        data_date=date_label,
        now=now,
    )
    output_dir = output_root / context.run_id
    source_name = "csv_fundamentals"
    try:
        if fundamental_source is None:
            if source_path is None:
                raise ValueError("source_path is required")
            fundamental_source = CsvFundamentalSource(source_path)
        source_name = fundamental_source.name
        records = fundamental_source.fetch(symbols=symbols)
        history = preserve_version_history(records)
        snapshot = select_point_in_time(history, data_date=data_date)
        assert_point_in_time(snapshot, data_date=data_date)
        snapshot, confidence = _attach_confidence(snapshot, history, data_date=data_date)
    except Exception as error:
        _write_failure(context=context, output_dir=output_dir, source_name=source_name, error=error)
        raise

    output_dir.mkdir(parents=True, exist_ok=False)
    history.to_csv(output_dir / "fundamental_history.csv", index=False)
    snapshot.to_csv(output_dir / "fundamental_snapshot.csv", index=False)
    confidence.to_csv(output_dir / "data_confidence.csv", index=False)
    has_data = not snapshot.empty
    health_status = "PASS" if has_data else "FAIL"
    health = {
        "status": health_status,
        "point_in_time": "PASS",
        "records": len(snapshot),
        "cutoff": date_label,
        "reason": None
        if has_data
        else "no fundamental facts were publicly available at the PIT cutoff",
    }
    (output_dir / "fundamental_health.json").write_text(
        json.dumps(health, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "fundamental_source": source_name,
                "overall_status": health_status,
                "fundamental_health": health_status,
                "live_execution_enabled": False,
                "trade_decision": "NO_TRADE",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    write_manifest(
        ValidationManifest(
            context=context,
            overall_status=health_status,
            critical_errors=0 if has_data else 1,
            warnings=0,
            checks={
                "fundamental_source": "PASS",
                "fundamental_health": health_status,
                "point_in_time": "PASS",
                "live_execution": "DISABLED",
                "trade_decision": "NO_TRADE",
            },
        ),
        output_dir,
    )
    return Phase2Result(context=context, snapshot=snapshot, output_dir=output_dir)
