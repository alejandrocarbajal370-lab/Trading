from __future__ import annotations

import argparse
import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from core.phase0 import _git_commit
from core.run_context import RunContext, build_run_context
from monitoring.manifest import ValidationManifest, write_manifest
from universe.diagnostics import (
    UniverseHealthRules,
    diagnose_universe,
    stress_test_universe,
)
from universe.schedule import UniverseRebalanceSchedule
from universe.snapshots import UniverseSnapshotStore
from universe.validation import UniverseRules, validate_universe


@dataclass(frozen=True)
class Phase36Result:
    context: RunContext
    membership: pd.DataFrame
    output_dir: Path
    snapshot_dir: Path


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def run_phase36(
    *,
    source_path: Path,
    rules: UniverseRules,
    as_of: datetime.date | datetime.datetime,
    output_root: Path = Path("validation_outputs"),
    snapshot_root: Path = Path("universe_snapshots"),
    health_rules: UniverseHealthRules | None = None,
    schedule: UniverseRebalanceSchedule | None = None,
    now: datetime.datetime | None = None,
) -> Phase36Result:
    context = build_run_context(
        mode="validation",
        model_version="phase3.6-investment-universe-v0.2",
        git_commit=_git_commit(),
        data_date=as_of.isoformat(),
        now=now,
    )
    output_dir = output_root / context.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        health_rules = health_rules or UniverseHealthRules()
        schedule = schedule or UniverseRebalanceSchedule()
        records = pd.read_csv(source_path)
        if isinstance(as_of, datetime.datetime):
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise ValueError("universe as_of datetime must be timezone-aware")
            cutoff = pd.Timestamp(as_of)
        else:
            cutoff = pd.Timestamp(
                datetime.datetime.combine(as_of, datetime.time.max, tzinfo=datetime.UTC)
            )
        membership = validate_universe(records, rules=rules, as_of=cutoff)
        store = UniverseSnapshotStore(snapshot_root)
        previous_date = store.previous_date(cutoff)
        previous = store.load(previous_date) if previous_date else None
        previous_metadata = store.metadata(previous_date) if previous_date else None
        stress_tests = stress_test_universe(records, rules=rules, as_of=cutoff)
        validation = diagnose_universe(
            membership,
            rules=rules,
            health_rules=health_rules,
            stress_tests=stress_tests,
            previous=previous,
            previous_ruleset_version=(
                str(previous_metadata["ruleset"]["version"]) if previous_metadata else None
            ),
        )
        status = str(validation["status"])
        membership.to_csv(output_dir / "universe_membership.csv", index=False)
        _write(output_dir / "universe_validation.json", validation)
        _write(
            output_dir / "run_summary.json",
            {
                "run_id": context.run_id,
                "overall_status": status,
                "universe_validation": status,
                "eligible_assets": validation["counts"]["eligible"],
                "excluded_assets": validation["counts"]["excluded"],
                "trade_decision": "NO_TRADE",
                "live_execution_enabled": False,
            },
        )
        write_manifest(
            ValidationManifest(
                context=context,
                overall_status=status,
                critical_errors=1 if status == "FAIL" else 0,
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
        snapshot_dir = store.save(
            membership,
            as_of=cutoff,
            validation=validation,
            rules=rules,
            schedule=schedule,
            recorded_at=pd.Timestamp(context.started_at),
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
    return Phase36Result(
        context=context, membership=membership, output_dir=output_dir, snapshot_dir=snapshot_dir
    )


def _from_config(path: Path) -> tuple[UniverseRules, UniverseHealthRules, UniverseRebalanceSchedule]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = dict(document.get("investment_universe", {}))
    health = dict(config.pop("health", {}))
    schedule = dict(config.pop("rebalance_schedule", {}))
    for key in ("allowed_asset_types", "allowed_exchanges"):
        if key in config:
            config[key] = tuple(config[key])
    return UniverseRules(**config), UniverseHealthRules(**health), UniverseRebalanceSchedule(**schedule)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an auditable point-in-time universe snapshot")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--as-of", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--config", type=Path, default=Path("config/settings.example.yaml"))
    parser.add_argument("--output-root", type=Path, default=Path("validation_outputs"))
    parser.add_argument("--snapshot-root", type=Path, default=Path("universe_snapshots"))
    args = parser.parse_args()
    rules, health_rules, schedule = _from_config(args.config)
    result = run_phase36(
        source_path=args.source,
        rules=rules,
        health_rules=health_rules,
        schedule=schedule,
        as_of=args.as_of,
        output_root=args.output_root,
        snapshot_root=args.snapshot_root,
    )
    print(result.output_dir)
    print(result.snapshot_dir)


if __name__ == "__main__":
    main()
