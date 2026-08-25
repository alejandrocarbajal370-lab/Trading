from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.phase2 import Phase2Result, run_phase2
from fundamentals.financial_engine import calculate_financial_metrics, financial_health
from fundamentals.quality import accounting_quality_health, evaluate_accounting_quality


@dataclass(frozen=True)
class Phase3Result:
    phase2: Phase2Result
    metrics: pd.DataFrame


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")


def _update_audit(
    phase2: Phase2Result,
    *,
    financial_status: str,
    quality_status: str = "NOT_RUN",
    error: Exception | None = None,
) -> None:
    summary_path = phase2.output_dir / "run_summary.json"
    manifest_path = phase2.output_dir / "validation_manifest.json"
    summary = _read(summary_path)
    manifest = _read(manifest_path)
    statuses = {financial_status, quality_status}
    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"
    summary.update(
        {
            "financial_health": financial_status,
            "accounting_quality_health": quality_status,
            "overall_status": overall_status,
            "live_execution_enabled": False,
            "trade_decision": "NO_TRADE",
        }
    )
    checks = manifest.setdefault("checks", {})
    assert isinstance(checks, dict)
    checks["financial_metrics"] = financial_status
    checks["accounting_quality"] = quality_status
    checks["live_execution"] = "DISABLED"
    checks["trade_decision"] = "NO_TRADE"
    manifest["overall_status"] = overall_status
    manifest["warnings"] = sum(check == "WARNING" for check in (financial_status, quality_status))
    manifest["critical_errors"] = sum(
        check == "FAIL" for check in (financial_status, quality_status)
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
        quality = evaluate_accounting_quality(phase2.snapshot)
        quality_health = accounting_quality_health(quality)
        status = str(health["status"])
        metrics.to_csv(phase2.output_dir / "financial_metrics.csv", index=False)
        _write(phase2.output_dir / "financial_health.json", health)
        quality.to_csv(phase2.output_dir / "accounting_quality.csv", index=False)
        _write(phase2.output_dir / "accounting_quality_health.json", quality_health)
        _update_audit(
            phase2,
            financial_status=status,
            quality_status=str(quality_health["status"]),
        )
    except Exception as error:
        failure = {
            "status": "FAIL",
            "records": 0,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        _write(phase2.output_dir / "financial_health.json", failure)
        _update_audit(phase2, financial_status="FAIL", error=error)
        raise
    return Phase3Result(phase2=phase2, metrics=metrics)
