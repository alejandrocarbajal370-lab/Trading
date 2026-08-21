from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from research.datasets import file_sha256

QUALITY_VALIDATION_SCHEMA_VERSION = "quality-validation-v1"
DEFAULT_MIN_PASS_COVERAGE = 0.70
CORE_QUALITY_METRICS = (
    "roic",
    "fcf_margin",
    "cfo_conversion",
    "net_debt_to_ebitda",
    "roic_stability",
    "margin_stability",
    "roic_consistency",
    "fcf_consistency",
    "margin_persistence",
)
TREND_SOURCE_METRICS = {
    "roic_v1": "roic_trend",
    "free_cash_flow": "fcf_trend",
    "free_cash_flow_margin": "margin_trend",
}
QUALITY_REQUIRED_COLUMNS = {
    "symbol",
    "metric",
    "value",
    "status",
    "lineage",
}
UNIVERSE_REQUIRED_COLUMNS = {
    "symbol",
    "eligibility_status",
    "exclusion_reason",
    "universe_confidence",
    "lineage",
}
FINANCIAL_REQUIRED_COLUMNS = {
    "symbol",
    "fiscal_period_end",
    "metric",
    "value",
    "status",
    "reason",
    "input_lineage",
}


@dataclass(frozen=True)
class QualityValidationResult:
    output_dir: Path
    report: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_immutable(path: Path, payload: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable quality-validation output differs: {path}")
    path.write_text(payload, encoding="utf-8")


def _require_columns(frame: pd.DataFrame, required: set[str], *, label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _valid_json_lineage(value: object) -> bool:
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return False
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, (dict, list)) and bool(parsed)


def _normalize_symbol(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["symbol"] = result["symbol"].astype("string").str.strip().str.upper()
    if result["symbol"].isna().any() or (result["symbol"] == "").any():
        raise ValueError("symbol must be present in quality validation inputs")
    return result


def _eligible_universe(universe: pd.DataFrame) -> pd.DataFrame:
    frame = _normalize_symbol(universe)
    duplicates = sorted(frame.loc[frame["symbol"].duplicated(keep=False), "symbol"].unique())
    if duplicates:
        raise ValueError(f"duplicate universe symbols: {', '.join(duplicates)}")
    return frame[frame["eligibility_status"] == "ELIGIBLE"].copy()


def _metric_coverage(
    quality: pd.DataFrame,
    eligible: pd.DataFrame,
    *,
    metric: str,
) -> dict[str, Any]:
    universe_symbols = set(eligible["symbol"])
    rows = quality[(quality["metric"] == metric) & quality["symbol"].isin(universe_symbols)].copy()
    observed_symbols = set(rows["symbol"])
    passing = rows[
        rows["status"].eq("PASS")
        & pd.to_numeric(rows["value"], errors="coerce").notna()
    ]
    passing_symbols = set(passing["symbol"])
    denominator = len(universe_symbols)
    return {
        "metric": metric,
        "eligible_symbols": denominator,
        "observed_symbols": len(observed_symbols),
        "passing_symbols": len(passing_symbols),
        "observed_coverage": round(len(observed_symbols) / denominator, 6) if denominator else 0.0,
        "pass_coverage": round(len(passing_symbols) / denominator, 6) if denominator else 0.0,
        "status_counts": rows["status"].value_counts().sort_index().to_dict(),
    }


def _coverage_by_group(
    quality: pd.DataFrame,
    eligible: pd.DataFrame,
    *,
    group: str,
    metric: str,
) -> list[dict[str, Any]]:
    if group not in eligible.columns:
        return []
    merged = eligible[["symbol", group]].merge(
        quality[quality["metric"] == metric][["symbol", "status", "value"]],
        on="symbol",
        how="left",
    )
    output: list[dict[str, Any]] = []
    for group_value, rows in merged.groupby(group, dropna=False, sort=True):
        passing = rows[
            rows["status"].eq("PASS")
            & pd.to_numeric(rows["value"], errors="coerce").notna()
        ]
        count = len(rows)
        output.append(
            {
                group: None if pd.isna(group_value) else str(group_value),
                "metric": metric,
                "eligible_symbols": count,
                "passing_symbols": int(passing["symbol"].nunique()),
                "pass_coverage": (
                    round(passing["symbol"].nunique() / count, 6) if count else 0.0
                ),
            }
        )
    return output


def _distribution(rows: pd.DataFrame, *, metric: str) -> dict[str, Any]:
    valid = rows[rows["status"].eq("PASS")].copy()
    valid["numeric_value"] = pd.to_numeric(valid["value"], errors="coerce")
    if valid.empty:
        return {"metric": metric, "count": 0, "percentiles": {}, "outliers": []}
    finite_mask = valid["numeric_value"].map(
        lambda value: math.isfinite(float(value)) if pd.notna(value) else False
    )
    valid = valid.loc[finite_mask].copy()
    if valid.empty:
        return {"metric": metric, "count": 0, "percentiles": {}, "outliers": []}
    values = valid["numeric_value"]
    quantiles = values.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    q1 = float(quantiles.loc[0.25])
    q3 = float(quantiles.loc[0.75])
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = valid[(valid["numeric_value"] < lower) | (valid["numeric_value"] > upper)]
    return {
        "metric": metric,
        "count": len(values),
        "min": float(values.min()),
        "max": float(values.max()),
        "percentiles": {
            "p10": float(quantiles.loc[0.10]),
            "p25": q1,
            "p50": float(quantiles.loc[0.50]),
            "p75": q3,
            "p90": float(quantiles.loc[0.90]),
        },
        "outlier_rule": "1.5x_IQR_descriptive_only",
        "outliers": [
            {
                "symbol": str(row["symbol"]),
                "value": float(row["numeric_value"]),
            }
            for _, row in outliers.sort_values(["symbol"]).iterrows()
        ],
    }


def _availability(quality: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, member in eligible.sort_values("symbol").iterrows():
        symbol = str(member["symbol"])
        observed = quality[quality["symbol"] == symbol]
        passing = observed[observed["status"].eq("PASS")]
        if observed.empty:
            status = "DATA_UNAVAILABLE"
            reason = "no Quality observations for eligible universe member"
        elif passing.empty:
            statuses = sorted(set(observed["status"].astype(str)))
            status = "NO_PASSING_QUALITY_METRICS"
            reason = f"Quality observations exist but none pass: {', '.join(statuses)}"
        else:
            status = "AVAILABLE"
            reason = None
        rows.append(
            {
                "symbol": symbol,
                "availability_status": status,
                "reason": reason,
                "observed_metrics": int(observed["metric"].nunique()),
                "passing_metrics": int(passing["metric"].nunique()),
                "universe_confidence": member.get("universe_confidence"),
                "universe_lineage": member.get("lineage"),
            }
        )
    return pd.DataFrame(rows)


def _trend_rows(financial: pd.DataFrame, eligible_symbols: set[str]) -> pd.DataFrame:
    if financial.empty:
        return pd.DataFrame(
            columns=["symbol", "metric", "observations", "start", "end", "delta", "direction"]
        )
    frame = _normalize_symbol(financial)
    frame["fiscal_period_end"] = pd.to_datetime(frame["fiscal_period_end"], errors="coerce")
    output: list[dict[str, Any]] = []
    for source_metric, result_metric in TREND_SOURCE_METRICS.items():
        selected = frame[
            (frame["metric"] == source_metric)
            & frame["symbol"].isin(eligible_symbols)
            & frame["status"].eq("PASS")
        ].copy()
        selected["numeric_value"] = pd.to_numeric(selected["value"], errors="coerce")
        selected = selected[
            selected["numeric_value"].notna() & selected["fiscal_period_end"].notna()
        ]
        for symbol, history in selected.groupby("symbol", sort=True):
            history = history.sort_values("fiscal_period_end")
            if history["fiscal_period_end"].duplicated().any() or len(history) < 2:
                continue
            start = float(history.iloc[0]["numeric_value"])
            end = float(history.iloc[-1]["numeric_value"])
            delta = end - start
            direction = "IMPROVING" if delta > 0 else "DECLINING" if delta < 0 else "FLAT"
            output.append(
                {
                    "symbol": str(symbol),
                    "metric": result_metric,
                    "observations": len(history),
                    "start": start,
                    "end": end,
                    "delta": delta,
                    "direction": direction,
                }
            )
    return pd.DataFrame(
        output,
        columns=["symbol", "metric", "observations", "start", "end", "delta", "direction"],
    )


def build_quality_validation_report(
    quality_metrics: pd.DataFrame,
    universe_membership: pd.DataFrame,
    *,
    experiment_id: str,
    universe_snapshot_id: str,
    dataset_snapshot_id: str,
    financial_metrics: pd.DataFrame | None = None,
    minimum_pass_coverage: float = DEFAULT_MIN_PASS_COVERAGE,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if not 0 <= minimum_pass_coverage <= 1:
        raise ValueError("minimum_pass_coverage must be between 0 and 1")
    _require_columns(quality_metrics, QUALITY_REQUIRED_COLUMNS, label="quality")
    _require_columns(universe_membership, UNIVERSE_REQUIRED_COLUMNS, label="universe")
    if financial_metrics is not None:
        _require_columns(financial_metrics, FINANCIAL_REQUIRED_COLUMNS, label="financial")
    quality = _normalize_symbol(quality_metrics)
    universe = _normalize_symbol(universe_membership)
    eligible = _eligible_universe(universe)
    eligible_symbols = set(eligible["symbol"])
    quality_eligible = quality[quality["symbol"].isin(eligible_symbols)].copy()
    quality_symbols_outside_universe = sorted(set(quality["symbol"]) - eligible_symbols)
    invalid_quality_lineage = int((~quality["lineage"].map(_valid_json_lineage)).sum())
    invalid_universe_lineage = int((~universe["lineage"].map(_valid_json_lineage)).sum())
    pit_mask = (
        quality.get("reason", pd.Series(index=quality.index, dtype="object"))
        .astype("string")
        .str.contains("PIT violation", case=False, na=False)
    )
    if financial_metrics is not None:
        pit_mask_financial = financial_metrics["reason"].astype("string").str.contains(
            "PIT violation", case=False, na=False
        )
        pit_violations = int(pit_mask.sum() + pit_mask_financial.sum())
    else:
        pit_violations = int(pit_mask.sum())
    coverage = [
        _metric_coverage(quality, eligible, metric=metric) for metric in CORE_QUALITY_METRICS
    ]
    distributions = [
        _distribution(quality_eligible[quality_eligible["metric"] == metric], metric=metric)
        for metric in CORE_QUALITY_METRICS
    ]
    coverage_by_sector = [
        item
        for metric in CORE_QUALITY_METRICS
        for item in _coverage_by_group(quality, eligible, group="sector", metric=metric)
    ]
    coverage_by_industry = [
        item
        for metric in CORE_QUALITY_METRICS
        for item in _coverage_by_group(quality, eligible, group="industry", metric=metric)
    ]
    availability = _availability(quality, eligible)
    financial = financial_metrics if financial_metrics is not None else pd.DataFrame()
    trends = _trend_rows(financial, eligible_symbols)
    warnings: list[str] = []
    for item in coverage:
        if item["pass_coverage"] < minimum_pass_coverage:
            warnings.append(
                f"low pass coverage for {item['metric']}: {item['pass_coverage']:.2%}"
            )
    unavailable = (
        int((availability["availability_status"] != "AVAILABLE").sum())
        if not availability.empty
        else 0
    )
    outlier_count = sum(len(item["outliers"]) for item in distributions)
    if unavailable:
        warnings.append(f"{unavailable} eligible universe members lack passing Quality coverage")
    if outlier_count:
        warnings.append(f"{outlier_count} descriptive Quality outliers require review")
    if quality_symbols_outside_universe:
        warnings.append(
            f"{len(quality_symbols_outside_universe)} Quality symbols are outside the eligible universe"
        )
    failures: list[str] = []
    if eligible.empty:
        failures.append("eligible universe is empty")
    if invalid_quality_lineage or invalid_universe_lineage:
        failures.append("invalid lineage detected in Quality or universe inputs")
    if pit_violations:
        failures.append(f"{pit_violations} PIT violations detected")
    if not any(item["passing_symbols"] for item in coverage):
        failures.append("no passing Quality metrics across eligible universe")
    health = "FAIL" if failures else "WARNING" if warnings else "PASS"
    report = {
        "schema_version": QUALITY_VALIDATION_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "universe_snapshot_id": universe_snapshot_id,
        "dataset_snapshot_id": dataset_snapshot_id,
        "health": health,
        "eligible_universe_size": len(eligible),
        "quality_symbols_observed": int(quality_eligible["symbol"].nunique()),
        "quality_symbols_outside_eligible_universe": quality_symbols_outside_universe,
        "minimum_pass_coverage": minimum_pass_coverage,
        "coverage": coverage,
        "coverage_by_sector": coverage_by_sector,
        "coverage_by_industry": coverage_by_industry,
        "distributions": distributions,
        "availability_summary": (
            availability["availability_status"].value_counts().sort_index().to_dict()
            if not availability.empty
            else {}
        ),
        "trend_summary": (
            trends.groupby(["metric", "direction"]).size().to_dict() if not trends.empty else {}
        ),
        "lineage_health": {
            "invalid_quality_lineage": invalid_quality_lineage,
            "invalid_universe_lineage": invalid_universe_lineage,
        },
        "pit_violations": pit_violations,
        "warnings": warnings,
        "failures": failures,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "ranking_calculated": False,
        "composite_score_calculated": False,
    }
    report["trend_summary"] = {
        f"{metric}:{direction}": int(count)
        for (metric, direction), count in report["trend_summary"].items()
    }
    return report, trends


def run_quality_validation(
    *,
    quality_metrics_path: Path,
    universe_membership_path: Path,
    experiment_id: str,
    universe_snapshot_id: str,
    dataset_snapshot_id: str,
    financial_metrics_path: Path | None = None,
    output_root: Path = Path("research_outputs"),
    minimum_pass_coverage: float = DEFAULT_MIN_PASS_COVERAGE,
) -> QualityValidationResult:
    quality = pd.read_csv(quality_metrics_path)
    universe = pd.read_csv(universe_membership_path)
    financial = pd.read_csv(financial_metrics_path) if financial_metrics_path is not None else None
    report, trends = build_quality_validation_report(
        quality,
        universe,
        experiment_id=experiment_id,
        universe_snapshot_id=universe_snapshot_id,
        dataset_snapshot_id=dataset_snapshot_id,
        financial_metrics=financial,
        minimum_pass_coverage=minimum_pass_coverage,
    )
    input_hashes = {
        "quality_metrics": file_sha256(quality_metrics_path),
        "universe_membership": file_sha256(universe_membership_path),
        "financial_metrics": file_sha256(financial_metrics_path) if financial_metrics_path else None,
    }
    fingerprint_payload = {
        "schema_version": QUALITY_VALIDATION_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "universe_snapshot_id": universe_snapshot_id,
        "dataset_snapshot_id": dataset_snapshot_id,
        "minimum_pass_coverage": minimum_pass_coverage,
        "input_hashes": input_hashes,
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_payload).encode()).hexdigest()
    run_id = f"{experiment_id}_quality_validation_{fingerprint[:12]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    availability = _availability(_normalize_symbol(quality), _eligible_universe(universe))
    report.update(
        {
            "run_id": run_id,
            "reproducibility_fingerprint": fingerprint,
            "input_hashes": input_hashes,
            "outputs": {
                "report": "quality_validation_report.json",
                "availability": "quality_availability.csv",
                "trends": "quality_trends.csv",
            },
        }
    )
    _write_immutable(
        output_dir / "quality_validation_report.json",
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    _write_immutable(
        output_dir / "quality_availability.csv",
        availability.to_csv(index=False, lineterminator="\n"),
    )
    _write_immutable(
        output_dir / "quality_trends.csv",
        trends.to_csv(index=False, lineterminator="\n"),
    )
    return QualityValidationResult(output_dir=output_dir, report=report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the research-only Quality validation report")
    parser.add_argument("--quality-metrics", required=True, type=Path)
    parser.add_argument("--universe-membership", required=True, type=Path)
    parser.add_argument("--financial-metrics", type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--universe-snapshot-id", required=True)
    parser.add_argument("--dataset-snapshot-id", required=True)
    parser.add_argument("--minimum-pass-coverage", type=float, default=DEFAULT_MIN_PASS_COVERAGE)
    parser.add_argument("--output-root", type=Path, default=Path("research_outputs"))
    args = parser.parse_args()
    result = run_quality_validation(
        quality_metrics_path=args.quality_metrics,
        universe_membership_path=args.universe_membership,
        financial_metrics_path=args.financial_metrics,
        experiment_id=args.experiment_id,
        universe_snapshot_id=args.universe_snapshot_id,
        dataset_snapshot_id=args.dataset_snapshot_id,
        output_root=args.output_root,
        minimum_pass_coverage=args.minimum_pass_coverage,
    )
    print(result.output_dir)


if __name__ == "__main__":
    main()
