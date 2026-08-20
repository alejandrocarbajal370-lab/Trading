from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.phase0 import _git_commit
from core.run_context import RunContext, build_run_context
from monitoring.manifest import ValidationManifest, write_manifest
from universe.validation import UniverseRules, universe_health, validate_universe


@dataclass(frozen=True)
class Phase36Result:
    context: RunContext
    membership: pd.DataFrame
    output_dir: Path


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def run_phase36(
    *,
    source_path: Path,
    rules: UniverseRules,
    as_of: datetime.date | datetime.datetime,
    output_root: Path = Path("validation_outputs"),
    now: datetime.datetime | None = None,
) -> Phase36Result:
    context = build_run_context(
        mode="validation",
        model_version="phase3.6-investment-universe-v0.1",
        git_commit=_git_commit(),
        data_date=as_of.isoformat(),
        now=now,
    )
    output_dir = output_root / context.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        records = pd.read_csv(source_path)
        membership = validate_universe(records, rules=rules, as_of=pd.Timestamp(as_of))
        validation = universe_health(membership, rules=rules)
        status = str(validation["status"])
        membership.to_csv(output_dir / "universe_membership.csv", index=False)
        _write(output_dir / "universe_validation.json", validation)
        _write(
            output_dir / "run_summary.json",
            {
                "run_id": context.run_id,
                "overall_status": status,
                "universe_validation": status,
                "eligible_assets": validation["eligible"],
                "excluded_assets": validation["excluded"],
                "trade_decision": "NO_TRADE",
                "live_execution_enabled": False,
            },
        )
        write_manifest(
            ValidationManifest(
                context=context,
                overall_status=status,
                critical_errors=0,
                warnings=1 if status == "WARNING" else 0,
                checks={
                    "universe_contract": "PASS",
                    "universe_validation": status,
                    "live_execution": "DISABLED",
                    "trade_decision": "NO_TRADE",
                },
            ),
            output_dir,
        )
    except Exception as error:
        failure = {
            "status": "FAIL",
            "records": 0,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "rules": rules.to_dict(),
            "trade_decision": "NO_TRADE",
            "live_execution_enabled": False,
        }
        _write(output_dir / "universe_validation.json", failure)
        _write(
            output_dir / "run_summary.json",
            {
                "run_id": context.run_id,
                "overall_status": "FAIL",
                "universe_validation": "FAIL",
                "error_type": type(error).__name__,
                "error_message": str(error),
                "trade_decision": "NO_TRADE",
                "live_execution_enabled": False,
            },
        )
        write_manifest(
            ValidationManifest(
                context=context,
                overall_status="FAIL",
                critical_errors=1,
                warnings=0,
                checks={
                    "universe_contract": "FAIL",
                    "universe_validation": "FAIL",
                    "live_execution": "DISABLED",
                    "trade_decision": "NO_TRADE",
                },
            ),
            output_dir,
        )
        raise
    return Phase36Result(context=context, membership=membership, output_dir=output_dir)
