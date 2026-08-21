from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from factors.value import VALUE_CONTRACT, evaluate_value_metrics
from research.datasets import DatasetVersionError, VerifiedDataset, verify_dataset
from research.registry import ResearchRegistry


@dataclass(frozen=True)
class ValueResearchRunResult:
    output_dir: Path
    research_run: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_immutable(path: Path, payload: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable research output differs: {path}")
    path.write_text(payload, encoding="utf-8")


def _find_financial_dataset(datasets: list[VerifiedDataset]) -> tuple[VerifiedDataset, pd.DataFrame]:
    matches: list[tuple[VerifiedDataset, pd.DataFrame]] = []
    required = set(VALUE_CONTRACT.required_dataset_columns)
    for dataset in datasets:
        if dataset.resolved_path.suffix.lower() == ".csv":
            frame = pd.read_csv(dataset.resolved_path)
            if required <= set(frame.columns):
                matches.append((dataset, frame))
    if len(matches) != 1:
        raise ValueError("exactly one registered dataset must satisfy the Value V1 contract")
    return matches[0]


def run_value_experiment(
    *,
    registry_path: Path,
    experiment_id: str,
    experiment_version: str,
    output_root: Path = Path("research_outputs"),
    mismatch_policy: str = "fail",
    low_confidence_threshold: float = 0.7,
    assumptions: tuple[str, ...] = (),
) -> ValueResearchRunResult:
    experiment = ResearchRegistry(registry_path).get(experiment_id, experiment_version)
    verified: list[VerifiedDataset] = []
    dataset_warnings: list[str] = []
    for registration in experiment.datasets:
        dataset, warning = verify_dataset(
            registration, registry_root=registry_path.parent, mismatch_policy=mismatch_policy
        )
        verified.append(dataset)
        if warning:
            dataset_warnings.append(warning)
    financial_dataset, frame = _find_financial_dataset(verified)
    dataset_lineage = {
        "dataset_id": financial_dataset.registration.dataset_id,
        "snapshot_id": financial_dataset.registration.snapshot_id,
        "sha256": financial_dataset.observed_sha256,
        "registered_lineage": list(financial_dataset.registration.lineage),
    }
    evaluation = evaluate_value_metrics(
        frame,
        experiment_id=experiment.experiment_id,
        dataset_lineage=dataset_lineage,
        low_confidence_threshold=low_confidence_threshold,
    )
    fingerprint_document = {
        "experiment": experiment.to_dict(),
        "datasets": dataset_lineage,
        "contract": VALUE_CONTRACT.model_dump(mode="json"),
        "assumptions": assumptions,
        "runner_version": "phase4.2-value-research-v1.0",
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_document).encode()).hexdigest()
    run_id = f"{experiment.experiment_id}_{experiment.experiment_version}_value_{fingerprint[:12]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    health = evaluation.health["status"]
    if dataset_warnings and health == "PASS":
        health = "WARNING"
    run = {
        "schema_version": "value-research-run-v1",
        "run_id": run_id,
        "reproducibility_fingerprint": fingerprint,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "hypothesis": VALUE_CONTRACT.hypothesis,
        "value_ruleset_version": VALUE_CONTRACT.version,
        "dataset_snapshot": dataset_lineage,
        "analysis_period": {"start": experiment.sample_start, "end": experiment.sample_end},
        "assumptions": list(assumptions),
        "health": health,
        "warnings": dataset_warnings,
        "absolute_value": {"calculated": True, "metrics": list(VALUE_CONTRACT.absolute_value_metrics)},
        "relative_value": {"calculated": False, "mode": "metadata_only"},
        "foundations": {
            "owner_earnings_yield": "metadata_only",
            "historical_valuation_context": "not_implemented",
            "sector_relative_valuation": "metadata_only",
            "quality_context_linkage": "future",
        },
        "outputs": {
            "value_metrics": "value_metrics.csv",
            "value_health": "value_health.json",
            "value_lineage": "value_lineage.json",
            "value_validation_report": "value_validation_report.json",
        },
        "composite_score_calculated": False,
        "ranking_calculated": False,
        "portfolio_constructed": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
    payloads = {
        "value_metrics.csv": evaluation.metrics.to_csv(index=False, lineterminator="\n"),
        "value_health.json": json.dumps(evaluation.health, indent=2, sort_keys=True) + "\n",
        "value_lineage.json": json.dumps(evaluation.lineage, indent=2, sort_keys=True) + "\n",
        "value_validation_report.json": json.dumps(evaluation.validation_report, indent=2, sort_keys=True) + "\n",
        "value_research_run.json": json.dumps(run, indent=2, sort_keys=True) + "\n",
    }
    for name, payload in payloads.items():
        _write_immutable(output_dir / name, payload)
    return ValueResearchRunResult(output_dir, run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the research-only Value Factor V1")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--experiment-version", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("research_outputs"))
    parser.add_argument("--dataset-mismatch", choices=("fail", "warn"), default="fail")
    parser.add_argument("--low-confidence-threshold", type=float, default=0.7)
    parser.add_argument("--assumption", action="append", default=[])
    args = parser.parse_args()
    try:
        result = run_value_experiment(
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
