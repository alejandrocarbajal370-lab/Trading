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
UNIVERSE_PROVENANCE_COLUMNS = (
    "membership_as_of",
    "membership_source",
    "membership_snapshot_id",
)
PRICE_ADJUSTMENT_SCOPES = {"SPLIT_ONLY", "SPLIT_AND_CASH_DIVIDEND"}
BACKTEST_BLOCKERS = (
    "SURVIVORSHIP_SAFE_PIT_HISTORICAL_INPUTS",
)


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


def _validate_universe_provenance(
    frame: pd.DataFrame, *, manifest: dict[str, Any], as_of: datetime.datetime, source: str
) -> None:
    missing = sorted(set(UNIVERSE_PROVENANCE_COLUMNS) - set(frame.columns))
    if missing:
        raise DatasetVersionError(
            "universe membership provenance missing fields: " + ", ".join(missing)
        )
    declaration = manifest.get("universe_snapshot")
    if not isinstance(declaration, dict):
        raise DatasetVersionError("universe_snapshot provenance declaration is required")
    if declaration.get("claim") != "PROVIDER_SUPPLIED_PIT_SNAPSHOT":
        raise DatasetVersionError(
            "universe_snapshot claim must be PROVIDER_SUPPLIED_PIT_SNAPSHOT"
        )
    snapshot_id = str(declaration.get("snapshot_id", "")).strip()
    if not snapshot_id:
        raise DatasetVersionError("universe_snapshot snapshot_id is required")
    declared_as_of = _aware(declaration.get("as_of"), field="universe_snapshot.as_of")
    if declared_as_of != as_of:
        raise DatasetVersionError("universe_snapshot as_of must equal manifest as_of")
    if str(declaration.get("source", "")).strip() != source:
        raise DatasetVersionError("universe_snapshot source must equal manifest source")

    row_as_of = pd.to_datetime(frame["membership_as_of"], errors="raise", utc=True)
    if not (row_as_of == pd.Timestamp(as_of)).all():
        raise DatasetVersionError("every universe row must be bound to manifest as_of")
    if not (frame["membership_source"].astype(str).str.strip() == source).all():
        raise DatasetVersionError("every universe row must be bound to manifest source")
    if not (frame["membership_snapshot_id"].astype(str).str.strip() == snapshot_id).all():
        raise DatasetVersionError("every universe row must be bound to universe snapshot_id")


def _validate_price_adjustment_declaration(
    frame: pd.DataFrame, *, manifest: dict[str, Any]
) -> dict[str, Any]:
    declaration = manifest.get("price_adjustment")
    if not isinstance(declaration, dict):
        raise DatasetVersionError("price_adjustment declaration is required")
    if declaration.get("series_usage") != "FACTOR_RESEARCH_ONLY":
        raise DatasetVersionError("price_adjustment series_usage must be FACTOR_RESEARCH_ONLY")
    scope = declaration.get("adjustment_scope")
    if scope not in PRICE_ADJUSTMENT_SCOPES:
        raise DatasetVersionError(
            "price_adjustment adjustment_scope must explicitly declare SPLIT_ONLY or "
            "SPLIT_AND_CASH_DIVIDEND"
        )
    if declaration.get("portfolio_return_eligible") is not False:
        raise DatasetVersionError("adjusted prices must not be marked portfolio-return eligible")
    required_columns = {"corporate_action_status", "corporate_action_type"}
    if not required_columns <= set(frame.columns):
        raise DatasetVersionError("market data lacks corporate-action fields")
    action_types = set(
        frame.loc[
            frame["corporate_action_status"].astype(str) == "APPLIED",
            "corporate_action_type",
        ]
        .dropna()
        .astype(str)
    )
    if scope == "SPLIT_ONLY" and action_types & {"DIVIDEND", "SPLIT_AND_DIVIDEND"}:
        raise DatasetVersionError("dividend action conflicts with SPLIT_ONLY adjustment scope")
    return declaration


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

    universe_frame = pd.read_csv(paths["universe"])
    _validate_universe_provenance(
        universe_frame, manifest=manifest, as_of=as_of, source=source
    )
    market_frame = pd.read_csv(paths["market_data"])
    price_adjustment = _validate_price_adjustment_declaration(
        market_frame, manifest=manifest
    )

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
        market_frame,
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
        "universe_snapshot": manifest["universe_snapshot"],
        "price_adjustment": price_adjustment,
        "research_limitations": {
            "survivorship_free_history_verified": False,
            "portfolio_return_ready": False,
            "remaining_backtest_blockers": list(BACKTEST_BLOCKERS),
        },
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
        "universe_claim": "PROVIDER_SUPPLIED_PIT_SNAPSHOT",
        "survivorship_free_history_verified": False,
        "price_series_usage": "FACTOR_RESEARCH_ONLY",
        "portfolio_return_ready": False,
        "remaining_backtest_blockers": list(BACKTEST_BLOCKERS),
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
