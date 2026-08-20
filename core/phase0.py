from __future__ import annotations

import argparse
import datetime
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.run_context import RunContext, build_run_context
from data.connectors.alpha_vantage import AlphaVantagePriceSource
from data.connectors.base import PriceSource
from data.connectors.csv_prices import CsvPriceSource
from data.validation.health import DataHealthResult, HealthStatus
from data.validation.prices import validate_prices
from monitoring.manifest import ValidationManifest, write_manifest


@dataclass(frozen=True)
class Phase0Result:
    context: RunContext
    health: DataHealthResult
    output_dir: Path


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def run_phase0(
    *,
    source_path: Path | None = None,
    price_source: PriceSource | None = None,
    symbols: set[str],
    data_date: datetime.date,
    output_root: Path = Path("validation_outputs"),
    now: datetime.datetime | None = None,
) -> Phase0Result:
    """Run data ingest and validation only; this phase has no execution path."""
    context = build_run_context(
        mode="validation",
        model_version="phase0-v0.1",
        git_commit=_git_commit(),
        data_date=data_date.isoformat(),
        now=now,
    )
    output_dir = output_root / context.run_id

    if price_source is None:
        if source_path is None:
            raise ValueError("source_path is required when price_source is not provided")
        price_source = CsvPriceSource(source_path)
    prices = price_source.fetch(symbols=symbols, data_date=data_date)
    health = validate_prices(prices, expected_symbols=symbols, data_date=data_date)
    output_dir.mkdir(parents=True, exist_ok=False)
    prices.to_csv(output_dir / "ingested_prices.csv", index=False)
    (output_dir / "data_health.json").write_text(
        json.dumps(health.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "data_source": price_source.name,
                "source_path": str(source_path) if source_path is not None else None,
                "live_execution_enabled": False,
                "trade_decision": "NO_TRADE",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = ValidationManifest(
        context=context,
        overall_status=health.status.value,
        critical_errors=int(health.status is HealthStatus.FAIL),
        warnings=int(health.status is HealthStatus.WARNING),
        checks={"data_health": health.status.value, "live_execution": "DISABLED"},
    )
    write_manifest(manifest, output_dir)
    return Phase0Result(context=context, health=health, output_dir=output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal Phase 0 validation flow")
    parser.add_argument("--provider", choices=("csv", "alpha-vantage"), default="csv")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--symbols", required=True, help="Comma-separated expected symbols")
    parser.add_argument("--data-date", type=datetime.date.fromisoformat, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("validation_outputs"))
    args = parser.parse_args()
    if args.provider == "csv" and args.source is None:
        parser.error("--source is required when --provider=csv")
    price_source = AlphaVantagePriceSource.from_env() if args.provider == "alpha-vantage" else None
    result = run_phase0(
        source_path=args.source,
        price_source=price_source,
        symbols={symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()},
        data_date=args.data_date,
        output_root=args.output_root,
    )
    print(result.output_dir)


if __name__ == "__main__":
    main()
