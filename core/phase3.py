from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.phase2 import Phase2Result, run_phase2
from fundamentals.financial_engine import calculate_financial_metrics


@dataclass(frozen=True)
class Phase3Result:
    phase2: Phase2Result
    metrics: pd.DataFrame


def run_phase3(
    *,
    symbols: set[str],
    data_date: datetime.date | datetime.datetime,
    source_path: Path,
    output_root: Path = Path("validation_outputs"),
    now: datetime.datetime | None = None,
) -> Phase3Result:
    phase2 = run_phase2(
        symbols=symbols,
        data_date=data_date,
        source_path=source_path,
        output_root=output_root,
        now=now,
    )
    metrics = calculate_financial_metrics(phase2.snapshot)
    metrics.to_csv(phase2.output_dir / "financial_metrics.csv", index=False)
    counts = metrics["status"].value_counts().to_dict()
    status = "PASS" if set(counts) <= {"PASS"} else "WARNING"
    health = {"status": status, "metric_status_counts": counts, "records": len(metrics)}
    (phase2.output_dir / "financial_health.json").write_text(
        json.dumps(health, indent=2, sort_keys=True), encoding="utf-8"
    )
    for filename in ("run_summary.json", "validation_manifest.json"):
        path = phase2.output_dir / filename
        document = json.loads(path.read_text(encoding="utf-8"))
        document["financial_health"] = status
        document["overall_status"] = status
        if filename == "validation_manifest.json":
            document["warnings"] = 0 if status == "PASS" else 1
            document["checks"]["financial_metrics"] = status
        document["live_execution_enabled"] = False
        document["trade_decision"] = "NO_TRADE"
        path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return Phase3Result(phase2=phase2, metrics=metrics)
