from __future__ import annotations

import argparse
import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.phase36 import run_phase36
from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from data.market_data import LineageEntry, govern_market_data
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.integration import (
    CrossLayerGovernanceResult,
    integrate_governed_inputs,
    write_governed_inputs,
)
from research.datasets import DatasetVersionError, file_sha256
from research.equity_qvm import EquityQVMResearchResult, run_equity_qvm_research
from universe.validation import UniverseRules

PIT_RESEARCH_DATASET_SCHEMA = "pit-equity-research-files-v1"
REQUIRED_FILES = ("universe", "market_data", "accounting", "fx")


@dataclass(frozen=True)
class PITDatasetBuild:
    cross_layer: CrossLayerGovernanceResult
    output_dir: Path
    source_hashes: dict[str, str]


@dataclass(frozen=True)
class PITQVMBuild:
    dataset: PITDatasetBuild
    research: EquityQVMResearchResult
    coverage_path: Path


def _aware(value: object, *, field: str) -> datetime.datetime:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DatasetVersionError(f"{field} must be timezone-aware")
    return parsed.tz_convert("UTC").to_pydatetime()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetVersionError(f"invalid PIT dataset manifest: {error}") from error
    if manifest.get("schema_version") != PIT_RESEARCH_DATASET_SCHEMA:
        raise DatasetVersionError("unsupported PIT dataset manifest schema")
    return manifest


def _verified_sources(
    manifest_path: Path, manifest: dict[str, Any]
) -> tuple[dict[str, Path], dict[str, str]]:
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(REQUIRED_FILES):
        raise DatasetVersionError(
            f"PIT dataset manifest requires exactly: {', '.join(REQUIRED_FILES)}"
        )
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for name in REQUIRED_FILES:
        declaration = files.get(name)
        if not isinstance(declaration, dict):
            raise DatasetVersionError(f"invalid file declaration: {name}")
        source = Path(str(declaration.get("path", "")))
        source = source if source.is_absolute() else manifest_path.parent / source
        if not source.is_file():
            raise DatasetVersionError(f"PIT source file not found: {name}: {source}")
        observed = file_sha256(source)
        if observed != declaration.get("sha256"):
            raise DatasetVersionError(f"PIT source checksum mismatch: {name}")
        paths[name], hashes[name] = source, observed
    return paths, hashes


def build_pit_equity_dataset(*, manifest_path: Path, output_root: Path) -> PITDatasetBuild:
    """Build one canonical PIT cross-section from checksum-pinned provider CSV files."""
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)
    paths, source_hashes = _verified_sources(manifest_path, manifest)
    as_of = _aware(manifest.get("as_of"), field="as_of")
    available_at = _aware(manifest.get("dataset_available_at"), field="dataset_available_at")
    if available_at > as_of:
        raise DatasetVersionError("PIT dataset availability exceeds as_of")

    source = str(manifest.get("source", "")).strip()
    version = str(manifest.get("dataset_version", "")).strip()
    if not source or not version:
        raise DatasetVersionError("source and dataset_version are required")

    rules_payload = manifest.get("universe_rules", {})
    if not isinstance(rules_payload, dict):
        raise DatasetVersionError("universe_rules must be an object")
    for key in ("allowed_asset_types", "allowed_exchanges"):
        if key in rules_payload:
            rules_payload[key] = tuple(rules_payload[key])
    universe = run_phase36(
        source_path=paths["universe"],
        rules=UniverseRules(**rules_payload),
        as_of=as_of,
        now=as_of,
        output_root=output_root / "universe_validation",
        snapshot_root=output_root / "universe_snapshots",
    )

    market = govern_market_data(
        pd.read_csv(paths["market_data"]),
        source=source,
        dataset_version=version,
        available_at=available_at,
        lineage=(
            LineageEntry(source=source, dataset="adjusted_prices", dataset_version=version),
        ),
        trading_calendar=str(manifest.get("trading_calendar", "XNYS")),
        as_of=as_of,
        maximum_staleness_sessions=int(manifest.get("maximum_price_staleness_sessions", 1)),
    )
    accounting = govern_accounting(
        pd.read_csv(paths["accounting"]),
        source=source,
        dataset_version=version,
        available_at=available_at,
        lineage=(
            AccountingLineageEntry(
                source=source, dataset="revision_aware_fundamentals", dataset_version=version
            ),
        ),
        as_of=as_of,
    )
    fx = govern_fx(
        pd.read_csv(paths["fx"]),
        source=source,
        dataset_version=version,
        available_at=available_at,
        lineage=(FXLineageEntry(source=source, dataset="historical_fx", dataset_version=version),),
        as_of=as_of,
        staleness_policy=FXStalenessPolicy(
            maximum_sessions=int(manifest.get("maximum_fx_staleness_sessions", 5))
        ),
    )
    required = manifest.get("required_fundamentals")
    if not isinstance(required, list) or not required:
        raise DatasetVersionError("required_fundamentals must be a non-empty list")
    benchmark = str(manifest.get("benchmark_symbol", "")).strip().upper()
    result = integrate_governed_inputs(
        universe_snapshot_dir=universe.snapshot_dir,
        market_data=market,
        fx=fx,
        accounting=accounting,
        as_of=as_of,
        base_currency=str(manifest.get("base_currency", "USD")),
        required_fundamentals=set(map(str, required)),
        reference_symbols={benchmark} if benchmark else set(),
    )
    output_dir = write_governed_inputs(result, output_root=output_root / "canonical")
    source_manifest = {
        "schema_version": PIT_RESEARCH_DATASET_SCHEMA,
        "source_files_sha256": source_hashes,
        "cross_layer_fingerprint": result.manifest.cross_layer_fingerprint,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "real_data_readiness": "NOT_READY",
    }
    source_manifest_path = output_dir / "source_manifest.json"
    source_manifest_payload = json.dumps(source_manifest, indent=2, sort_keys=True) + "\n"
    if (
        source_manifest_path.exists()
        and source_manifest_path.read_text(encoding="utf-8") != source_manifest_payload
    ):
        raise DatasetVersionError("immutable PIT source manifest conflict")
    source_manifest_path.write_text(source_manifest_payload, encoding="utf-8")
    return PITDatasetBuild(result, output_dir, source_hashes)


def build_and_run_pit_qvm(*, manifest_path: Path, output_root: Path) -> PITQVMBuild:
    """Materialize a canonical cut and run the existing research-only QVM engine."""
    manifest = _load_manifest(manifest_path)
    dataset = build_pit_equity_dataset(manifest_path=manifest_path, output_root=output_root)
    benchmark = str(manifest.get("benchmark_symbol", "")).strip().upper()
    if not benchmark:
        raise DatasetVersionError("benchmark_symbol is required for a QVM run")
    research = run_equity_qvm_research(
        cross_layer=dataset.cross_layer,
        experiment_id=str(manifest.get("experiment_id", "pit-equity-qvm")),
        benchmark_symbol=benchmark,
    )
    metric_frames = {
        "quality": research.quality.metrics,
        "value": research.value.metrics,
        "momentum": research.momentum.metrics,
    }
    for name, frame in metric_frames.items():
        frame.sort_values(["symbol", "metric"], kind="stable").to_csv(
            dataset.output_dir / f"{name}_metrics.csv", index=False, lineterminator="\n"
        )
    expected = set(dataset.cross_layer.manifest.required_fundamentals)
    coverage = {
        name: {
            "passing_observations": int((frame["status"] == "PASS").sum()),
            "passing_symbols": int(frame.loc[frame["status"] == "PASS", "symbol"].nunique()),
            "metrics": sorted(frame.loc[frame["status"] == "PASS", "metric"].unique()),
        }
        for name, frame in metric_frames.items()
    }
    report = {
        "as_of": dataset.cross_layer.manifest.as_of.isoformat(),
        "eligible_symbols": dataset.cross_layer.manifest.eligible_symbols_count,
        "required_fundamentals": sorted(expected),
        "coverage": coverage,
        "model_eligible_symbols": sum(
            row.model_status == "ELIGIBLE" for row in research.qvm.composites
        ),
        "cohort_publication": research.qvm.cohort_publication_status,
        "trade_decision": research.qvm.trade_decision,
        "live_execution_enabled": research.qvm.live_execution_enabled,
        "real_data_readiness": research.qvm.real_data_readiness,
    }
    coverage_path = dataset.output_dir / "qvm_coverage.json"
    coverage_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return PITQVMBuild(dataset, research, coverage_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a canonical PIT equity dataset and run research-only QVM"
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    result = build_and_run_pit_qvm(
        manifest_path=args.manifest, output_root=args.output_root
    )
    print(result.dataset.output_dir)


if __name__ == "__main__":
    main()
