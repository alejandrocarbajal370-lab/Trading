from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.phase2 import Phase2Result, run_phase2
from fundamentals.financial_engine import calculate_financial_metrics, financial_health


@dataclass(frozen=True)
class Phase3Result:
    phase2: Phase2Result
    metrics: pd.DataFrame


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")


def _update_audit(phase2: Phase2Result, *, status: str, error: Exception | None = None) -> None:
    summary_path = phase2.output_dir / "run_summary.json"
    manifest_path = phase2.output_dir / "validation_manifest.json"
    summary = _read(summary_path)
    manifest = _read(manifest_path)
    summary.update(
        {
            "financial_health": status,
            "overall_status": status,
            "live_execution_enabled": False,
            "trade_decision": "NO_TRADE",
        }
    )
    checks = manifest.setdefault("checks", {})
    assert isinstance(checks, dict)
    checks["financial_metrics"] = status
    checks["live_execution"] = "DISABLED"
    checks["trade_decision"] = "NO_TRADE"
    manifest["overall_status"] = status
    manifest["warnings"] = int(manifest.get("warnings", 0)) + (1 if status == "WARNING" else 0)
    manifest["critical_errors"] = int(manifest.get("critical_errors", 0)) + (
        1 if status == "FAIL" else 0
    )
    if error is not None:
        details = {"error_type": type(error).__name__, "error_message": str(error)}
        summary.update(details)
        manifest.update(details)
    _write(summary_path, summary)
    _write(manifest_path, manifest)


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
    try:
        metrics = calculate_financial_metrics(phase2.snapshot)
        health = financial_health(metrics, snapshot_empty=phase2.snapshot.empty)
        status = str(health["status"])
        metrics.to_csv(phase2.output_dir / "financial_metrics.csv", index=False)
        _write(phase2.output_dir / "financial_health.json", health)
        _update_audit(phase2, status=status)
    except Exception as error:
        failure = {
            "status": "FAIL",
            "records": 0,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        _write(phase2.output_dir / "financial_health.json", failure)
        _update_audit(phase2, status="FAIL", error=error)
        raise
    return Phase3Result(phase2=phase2, metrics=metrics)
