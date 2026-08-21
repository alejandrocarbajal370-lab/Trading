from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from research.datasets import DatasetVersionError, VerifiedDataset, verify_dataset
from research.registry import ResearchExperiment, ResearchRegistry


@dataclass(frozen=True)
class ResearchRunResult:
    output_dir: Path
    research_run: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable research output differs: {path}")
    path.write_text(payload, encoding="utf-8")


def _dataset_metrics(dataset: VerifiedDataset) -> dict[str, Any]:
    path = dataset.resolved_path
    metrics: dict[str, Any] = {
        "dataset_id": dataset.registration.dataset_id,
        "snapshot_id": dataset.registration.snapshot_id,
        "sha256": dataset.observed_sha256,
        "bytes": path.stat().st_size,
    }
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, [])
            rows = list(reader)
        metrics.update(
            rows=len(rows),
            columns=len(header),
            column_names=header,
            missing_cells=sum(cell.strip() == "" for row in rows for cell in row),
        )
    return metrics


def _fingerprint(experiment: ResearchExperiment, datasets: list[VerifiedDataset]) -> str:
    document = {
        "experiment": experiment.to_dict(),
        "verified_datasets": [
            {
                "dataset_id": item.registration.dataset_id,
                "snapshot_id": item.registration.snapshot_id,
                "sha256": item.observed_sha256,
            }
            for item in datasets
        ],
        "runner_version": "phase4-research-foundation-v1",
    }
    return hashlib.sha256(_canonical_json(document).encode()).hexdigest()


def run_registered_experiment(
    *,
    registry_path: Path,
    experiment_id: str,
    experiment_version: str,
    output_root: Path = Path("research_outputs"),
    mismatch_policy: str = "fail",
) -> ResearchRunResult:
    registry = ResearchRegistry(registry_path)
    experiment = registry.get(experiment_id, experiment_version)
    verified: list[VerifiedDataset] = []
    warnings: list[str] = []
    for registration in experiment.datasets:
        dataset, warning = verify_dataset(
            registration,
            registry_root=registry_path.parent,
            mismatch_policy=mismatch_policy,
        )
        verified.append(dataset)
        if warning:
            warnings.append(warning)

    fingerprint = _fingerprint(experiment, verified)
    run_id = f"{experiment.experiment_id}_{experiment.experiment_version}_{fingerprint[:12]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "dataset_count": len(verified),
        "total_bytes": sum(item.resolved_path.stat().st_size for item in verified),
        "datasets": [_dataset_metrics(item) for item in verified],
    }
    observed_result = (
        f"Foundation validation completed for {len(verified)} immutable dataset snapshot(s); "
        "no factor calculation was performed."
    )
    research_run = {
        "schema_version": "research-run-v1",
        "run_id": run_id,
        "reproducibility_fingerprint": fingerprint,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "hypothesis": experiment.hypothesis,
        "universe": {
            "description": experiment.universe,
            "snapshot_id": experiment.universe_snapshot_id,
            "ruleset_version": experiment.ruleset_version,
        },
        "analysis_period": {"start": experiment.sample_start, "end": experiment.sample_end},
        "metrics_evaluated": list(experiment.metrics_evaluated),
        "expected_result": experiment.expected_result,
        "observed_result": observed_result,
        "decision": experiment.decision,
        "health": "WARNING" if warnings else "PASS",
        "metrics": metrics,
        "warnings": warnings,
        "errors": [],
        "lineage": {
            "experiment": list(experiment.data_lineage),
            "datasets": [asdict(item.registration) for item in verified],
        },
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "factor_calculations_performed": False,
    }
    configuration = {
        "experiment": experiment.to_dict(),
        "mismatch_policy": mismatch_policy,
        "runner_version": "phase4-research-foundation-v1",
    }
    _write_json(output_dir / "research_config.json", configuration)
    _write_json(output_dir / "research_run.json", research_run)
    return ResearchRunResult(output_dir=output_dir, research_run=research_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and reproduce a registered research experiment without factor calculation"
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--experiment-version", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("research_outputs"))
    parser.add_argument("--dataset-mismatch", choices=("fail", "warn"), default="fail")
    args = parser.parse_args()
    try:
        result = run_registered_experiment(
            registry_path=args.registry,
            experiment_id=args.experiment_id,
            experiment_version=args.experiment_version,
            output_root=args.output_root,
            mismatch_policy=args.dataset_mismatch,
        )
    except DatasetVersionError as error:
        parser.error(str(error))
    print(result.output_dir)


if __name__ == "__main__":
    main()
