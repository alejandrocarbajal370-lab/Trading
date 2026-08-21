from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from factors.momentum import MOMENTUM_CONTRACT, evaluate_momentum_metrics
from research.datasets import (
    DatasetVersionError,
    VerifiedDataset,
    verify_dataset,
    verify_universe_snapshot,
)
from research.registry import ResearchExperiment, ResearchRegistry


@dataclass(frozen=True)
class MomentumResearchRunResult:
    output_dir: Path
    research_run: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_immutable(path: Path, payload: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable research output differs: {path}")
    path.write_text(payload, encoding="utf-8")


def _runtime_environment() -> dict[str, Any]:
    packages = {}
    for name in ("numpy", "pandas", "pydantic", "PyYAML"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "packages": packages,
    }


def _expected_snapshot_id(raw: str) -> str:
    try:
        return f"universe-{pd.Timestamp(raw).date().isoformat()}"
    except (TypeError, ValueError) as error:
        raise DatasetVersionError("governed universe snapshot as_of is invalid") from error


def _failure_audit(
    output_root: Path,
    experiment: ResearchExperiment,
    universe_snapshot_dir: Path | None,
    error: DatasetVersionError,
) -> None:
    audit = {
        "schema_version": "momentum-governance-audit-v1",
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "registered_universe_snapshot_id": experiment.universe_snapshot_id,
        "registered_ruleset_version": experiment.ruleset_version,
        "provided_universe_snapshot_dir": str(universe_snapshot_dir.resolve())
        if universe_snapshot_dir
        else None,
        "status": "FAIL",
        "error_type": type(error).__name__,
        "error_message": str(error),
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
    digest = hashlib.sha256(_canonical_json(audit).encode()).hexdigest()[:12]
    directory = (
        output_root
        / f"{experiment.experiment_id}_{experiment.experiment_version}_momentum_failed_{digest}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    _write_immutable(
        directory / "momentum_governance_audit.json",
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
    )


def _find_dataset(datasets: list[VerifiedDataset]) -> tuple[VerifiedDataset, pd.DataFrame]:
    matches = []
    required = set(MOMENTUM_CONTRACT.required_dataset_columns)
    for dataset in datasets:
        if dataset.resolved_path.suffix.lower() == ".csv":
            frame = pd.read_csv(dataset.resolved_path)
            if required <= set(frame.columns):
                matches.append((dataset, frame))
    if len(matches) != 1:
        raise ValueError("exactly one registered dataset must satisfy the Momentum V1 contract")
    return matches[0]


def run_momentum_experiment(
    *,
    registry_path: Path,
    experiment_id: str,
    experiment_version: str,
    benchmark_symbol: str,
    as_of: datetime.date,
    output_root: Path = Path("research_outputs"),
    mismatch_policy: str = "fail",
    low_confidence_threshold: float = 0.7,
    assumptions: tuple[str, ...] = (),
    universe_snapshot_dir: Path | None = None,
) -> MomentumResearchRunResult:
    experiment = ResearchRegistry(registry_path).get(experiment_id, experiment_version)
    verified, dataset_warnings = [], []
    for registration in experiment.datasets:
        dataset, warning = verify_dataset(
            registration, registry_root=registry_path.parent, mismatch_policy=mismatch_policy
        )
        verified.append(dataset)
        if warning:
            dataset_warnings.append(warning)
    try:
        if universe_snapshot_dir is None:
            raise DatasetVersionError(
                "governed universe snapshot is required for Momentum research"
            )
        universe_governance = verify_universe_snapshot(universe_snapshot_dir).to_dict()
        universe_governance["snapshot_id"] = _expected_snapshot_id(
            str(universe_governance["as_of"])
        )
        if universe_governance["snapshot_id"] != experiment.universe_snapshot_id:
            raise DatasetVersionError(
                "governed universe snapshot_id does not match registered experiment snapshot_id"
            )
        if universe_governance["ruleset_version"] != experiment.ruleset_version:
            raise DatasetVersionError(
                "governed universe ruleset does not match registered experiment ruleset"
            )
    except DatasetVersionError as error:
        _failure_audit(output_root, experiment, universe_snapshot_dir, error)
        raise
    price_dataset, frame = _find_dataset(verified)
    dataset_lineage = {
        "dataset_id": price_dataset.registration.dataset_id,
        "snapshot_id": price_dataset.registration.snapshot_id,
        "sha256": price_dataset.observed_sha256,
        "registered_lineage": list(price_dataset.registration.lineage),
    }
    evaluation = evaluate_momentum_metrics(
        frame,
        experiment_id=experiment.experiment_id,
        dataset_lineage=dataset_lineage,
        as_of=as_of,
        benchmark_symbol=benchmark_symbol,
        low_confidence_threshold=low_confidence_threshold,
    )
    runtime = _runtime_environment()
    fingerprint_document = {
        "experiment": experiment.to_dict(),
        "datasets": dataset_lineage,
        "contract": MOMENTUM_CONTRACT.model_dump(mode="json"),
        "benchmark_symbol": benchmark_symbol,
        "as_of": as_of.isoformat(),
        "assumptions": assumptions,
        "universe_governance": universe_governance,
        "runtime_environment": runtime,
        "runner_version": "phase4.3-momentum-v1.1",
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_document).encode()).hexdigest()
    run_id = (
        f"{experiment.experiment_id}_{experiment.experiment_version}_momentum_{fingerprint[:12]}"
    )
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    health = evaluation.health["status"]
    if dataset_warnings and health == "PASS":
        health = "WARNING"
    run = {
        "schema_version": "momentum-research-run-v1",
        "run_id": run_id,
        "reproducibility_fingerprint": fingerprint,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "hypothesis": MOMENTUM_CONTRACT.hypothesis,
        "momentum_ruleset_version": MOMENTUM_CONTRACT.version,
        "dataset_snapshot": dataset_lineage,
        "universe_snapshot_id": experiment.universe_snapshot_id,
        "ruleset_version": experiment.ruleset_version,
        "universe_governance": universe_governance,
        "runtime_environment": runtime,
        "analysis_period": {"start": experiment.sample_start, "end": experiment.sample_end},
        "as_of": as_of.isoformat(),
        "benchmark_symbol": benchmark_symbol,
        "assumptions": list(assumptions),
        "health": health,
        "warnings": dataset_warnings,
        "metrics_calculated": [item.name for item in MOMENTUM_CONTRACT.definitions],
        "outputs": {
            "momentum_metrics": "momentum_metrics.csv",
            "momentum_health": "momentum_health.json",
            "momentum_lineage": "momentum_lineage.json",
            "momentum_validation_report": "momentum_validation_report.json",
        },
        "market_data_audit_completed": True,
        "composite_score_calculated": False,
        "ranking_calculated": False,
        "qvm_calculated": False,
        "portfolio_constructed": False,
        "backtest_executed": False,
        "signals_generated": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
    payloads = {
        "momentum_metrics.csv": evaluation.metrics.to_csv(index=False, lineterminator="\n"),
        "momentum_health.json": json.dumps(evaluation.health, indent=2, sort_keys=True) + "\n",
        "momentum_lineage.json": json.dumps(evaluation.lineage, indent=2, sort_keys=True) + "\n",
        "momentum_validation_report.json": json.dumps(
            evaluation.validation_report, indent=2, sort_keys=True
        )
        + "\n",
        "momentum_research_run.json": json.dumps(run, indent=2, sort_keys=True) + "\n",
    }
    for name, payload in payloads.items():
        _write_immutable(output_dir / name, payload)
    return MomentumResearchRunResult(output_dir, run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run research-only Momentum Factor V1 metrics")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--experiment-version", required=True)
    parser.add_argument("--benchmark-symbol", required=True)
    parser.add_argument("--as-of", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--output-root", type=Path, default=Path("research_outputs"))
    parser.add_argument("--dataset-mismatch", choices=("fail", "warn"), default="fail")
    parser.add_argument("--low-confidence-threshold", type=float, default=0.7)
    parser.add_argument("--assumption", action="append", default=[])
    parser.add_argument("--universe-snapshot-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run_momentum_experiment(
            registry_path=args.registry,
            experiment_id=args.experiment_id,
            experiment_version=args.experiment_version,
            benchmark_symbol=args.benchmark_symbol,
            as_of=args.as_of,
            output_root=args.output_root,
            mismatch_policy=args.dataset_mismatch,
            low_confidence_threshold=args.low_confidence_threshold,
            assumptions=tuple(args.assumption),
            universe_snapshot_dir=args.universe_snapshot_dir,
        )
    except DatasetVersionError as error:
        parser.error(str(error))
    print(result.output_dir)


if __name__ == "__main__":
    main()
