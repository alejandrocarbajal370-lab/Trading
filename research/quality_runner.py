from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from factors.quality import QUALITY_CONTRACT, evaluate_quality_metrics
from research.datasets import DatasetVersionError, VerifiedDataset, verify_dataset
from research.registry import ResearchExperiment, ResearchRegistry


@dataclass(frozen=True)
class QualityResearchRunResult:
    output_dir: Path
    research_run: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_immutable(path: Path, payload: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable research output differs: {path}")
    path.write_text(payload, encoding="utf-8")


def _find_financial_dataset(
    datasets: list[VerifiedDataset],
) -> tuple[VerifiedDataset, pd.DataFrame]:
    matches: list[tuple[VerifiedDataset, pd.DataFrame]] = []
    for dataset in datasets:
        if dataset.resolved_path.suffix.lower() != ".csv":
            continue
        frame = pd.read_csv(dataset.resolved_path)
        required = set(QUALITY_CONTRACT.required_dataset_columns)
        if required <= set(frame.columns):
            matches.append((dataset, frame))
    if not matches:
        raise ValueError("no registered dataset satisfies the Quality V1 financial metric contract")
    if len(matches) > 1:
        raise ValueError("multiple registered datasets satisfy the Quality V1 financial contract")
    return matches[0]


def _fingerprint(
    experiment: ResearchExperiment, datasets: list[VerifiedDataset], assumptions: tuple[str, ...]
) -> str:
    document = {
        "experiment": experiment.to_dict(),
        "datasets": [
            {
                "dataset_id": item.registration.dataset_id,
                "snapshot_id": item.registration.snapshot_id,
                "sha256": item.observed_sha256,
            }
            for item in datasets
        ],
        "quality_ruleset": QUALITY_CONTRACT.model_dump(mode="json"),
        "assumptions": assumptions,
        "runner_version": "phase4.1-quality-research-v1",
    }
    return hashlib.sha256(_canonical_json(document).encode()).hexdigest()


def run_quality_experiment(
    *,
    registry_path: Path,
    experiment_id: str,
    experiment_version: str,
    output_root: Path = Path("research_outputs"),
    mismatch_policy: str = "fail",
    low_confidence_threshold: float = 0.7,
    assumptions: tuple[str, ...] = (),
) -> QualityResearchRunResult:
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
    financial_dataset, financial_metrics = _find_financial_dataset(verified)
    dataset_lineage = {
        "dataset_id": financial_dataset.registration.dataset_id,
        "snapshot_id": financial_dataset.registration.snapshot_id,
        "sha256": financial_dataset.observed_sha256,
        "registered_lineage": list(financial_dataset.registration.lineage),
    }
    evaluation = evaluate_quality_metrics(
        financial_metrics,
        experiment_id=experiment.experiment_id,
        dataset_lineage=dataset_lineage,
        low_confidence_threshold=low_confidence_threshold,
    )
    fingerprint = _fingerprint(experiment, verified, assumptions)
    run_id = (
        f"{experiment.experiment_id}_{experiment.experiment_version}_quality_{fingerprint[:12]}"
    )
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    health = evaluation.health["status"]
    if warnings and health == "PASS":
        health = "WARNING"
    run = {
        "schema_version": "quality-research-run-v1",
        "run_id": run_id,
        "reproducibility_fingerprint": fingerprint,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "hypothesis": QUALITY_CONTRACT.hypothesis,
        "dataset_snapshots": [
            {
                "dataset_id": item.registration.dataset_id,
                "snapshot_id": item.registration.snapshot_id,
                "sha256": item.observed_sha256,
            }
            for item in verified
        ],
        "universe_snapshot_id": experiment.universe_snapshot_id,
        "ruleset_version": experiment.ruleset_version,
        "quality_ruleset_version": QUALITY_CONTRACT.version,
        "analysis_period": {"start": experiment.sample_start, "end": experiment.sample_end},
        "assumptions": list(assumptions),
        "health": health,
        "factor_health": evaluation.health,
        "warnings": warnings,
        "errors": [],
        "lineage": {
            "experiment": list(experiment.data_lineage),
            "datasets": [asdict(item.registration) for item in verified],
        },
        "outputs": {"quality_metrics": "quality_metrics.csv"},
        "composite_score_calculated": False,
        "weights_assigned": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
    csv_payload = evaluation.metrics.to_csv(index=False, lineterminator="\n")
    json_payload = json.dumps(run, indent=2, sort_keys=True) + "\n"
    _write_immutable(output_dir / "quality_metrics.csv", csv_payload)
    _write_immutable(output_dir / "quality_research_run.json", json_payload)
    return QualityResearchRunResult(output_dir=output_dir, research_run=run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the research-only Quality Factor V1")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--experiment-version", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("research_outputs"))
    parser.add_argument("--dataset-mismatch", choices=("fail", "warn"), default="fail")
    parser.add_argument("--low-confidence-threshold", type=float, default=0.7)
    parser.add_argument("--assumption", action="append", default=[])
    args = parser.parse_args()
    try:
        result = run_quality_experiment(
            registry_path=args.registry,
            experiment_id=args.experiment_id,
            experiment_version=args.experiment_version,
            output_root=args.output_root,
            mismatch_policy=args.dataset_mismatch,
            low_confidence_threshold=args.low_confidence_threshold,
            assumptions=tuple(args.assumption),
        )
    except DatasetVersionError as error:
        parser.error(str(error))
    print(result.output_dir)


if __name__ == "__main__":
    main()
