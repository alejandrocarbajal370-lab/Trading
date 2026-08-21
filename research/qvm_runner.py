from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factors.qvm import FactorBatch, QVMEvaluation, evaluate_qvm_research
from research.datasets import DatasetVersionError, verify_universe_snapshot


@dataclass(frozen=True)
class QVMResearchRunResult:
    output_dir: Path
    research_run: dict[str, Any]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def run_qvm_research(
    *, batches: tuple[FactorBatch, ...], output_root: Path, universe_snapshot_dir: Path
) -> QVMResearchRunResult:
    universe = verify_universe_snapshot(universe_snapshot_dir)
    expected_snapshot_id = f"universe-{str(universe.metadata.get('as_of', ''))[:10]}"
    for batch in batches:
        if batch.universe_snapshot_id != expected_snapshot_id:
            raise DatasetVersionError(
                "governed universe snapshot_id does not match QVM batch snapshot_id"
            )
        if batch.universe_snapshot_hash != universe.membership_sha256:
            raise DatasetVersionError(
                "governed universe membership hash does not match QVM batch universe hash"
            )
    evaluation: QVMEvaluation = evaluate_qvm_research(batches)
    universe_identity = {
        "snapshot_id": expected_snapshot_id,
        "as_of": universe.metadata.get("as_of"),
        "membership_sha256": universe.membership_sha256,
        "validation_sha256": universe.validation_sha256,
        "health": universe.validation.get("status"),
        "ruleset_version": universe.metadata.get("ruleset", {}).get("version"),
    }
    fingerprint = hashlib.sha256(
        _canonical(
            {
                "universe_governance": universe_identity,
                "health": evaluation.health,
                "lineage": evaluation.lineage,
            }
        ).encode()
    ).hexdigest()
    output_dir = output_root / f"qvm_research_{fingerprint[:12]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "qvm_factor_matrix.csv": evaluation.matrix.to_csv(index=False, lineterminator="\n"),
        "qvm_health.json": json.dumps(evaluation.health, indent=2, sort_keys=True) + "\n",
        "qvm_lineage.json": json.dumps(evaluation.lineage, indent=2, sort_keys=True) + "\n",
        "qvm_validation_report.json": json.dumps(
            evaluation.validation_report, indent=2, sort_keys=True
        )
        + "\n",
    }
    run = {
        "schema_version": "qvm-research-run-v1",
        "reproducibility_fingerprint": fingerprint,
        "outputs": {name.rsplit(".", 1)[0]: name for name in payloads},
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "universe_governance": universe.to_dict(),
        "composite_score_calculated": False,
        "ranking_calculated": False,
        "portfolio_constructed": False,
        "backtest_executed": False,
    }
    payloads["qvm_research_run.json"] = json.dumps(run, indent=2, sort_keys=True) + "\n"
    for name, payload in payloads.items():
        path = output_dir / name
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise RuntimeError(f"immutable research output differs: {path}")
        path.write_text(payload, encoding="utf-8")
    return QVMResearchRunResult(output_dir, run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize aligned research-only QVM outputs")
    parser.add_argument("--batches", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("research_outputs"))
    parser.add_argument("--universe-snapshot-dir", required=True, type=Path)
    args = parser.parse_args()
    documents = json.loads(args.batches.read_text(encoding="utf-8"))
    result = run_qvm_research(
        batches=tuple(FactorBatch.model_validate(item) for item in documents),
        output_root=args.output_root,
        universe_snapshot_dir=args.universe_snapshot_dir,
    )
    print(result.output_dir)


if __name__ == "__main__":
    main()
