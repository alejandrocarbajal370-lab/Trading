from __future__ import annotations

import datetime
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from data.market_calendar import TradingCalendar, get_trading_calendar

MOMENTUM_HYPOTHESIS = (
    "Trailing price persistence can be described with point-in-time, market-data-aware "
    "metrics. Phase 4.3 calculates individual observations only and makes no investment claim."
)
MOMENTUM_RULESET_VERSION = "momentum-v1.1"
LOG_TRANSFORM = {
    "input_price": "adjusted_close",
    "transform": "natural_log",
    "formula": "log_price_t = ln(adjusted_close_t)",
    "version": "log-price-v1",
}
OUTPUT_COLUMNS = [
    "experiment_id",
    "symbol",
    "metric",
    "value",
    "unit",
    "currency",
    "as_of",
    "available_at",
    "confidence",
    "status",
    "reason",
    "benchmark_symbol",
    "price_basis",
    "corporate_action_status",
    "trading_calendar",
    "warnings",
    "lineage",
]


class MomentumContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MomentumMetricDefinition(MomentumContractModel):
    name: str
    formula: str
    unit: Literal["return", "return_per_volatility", "r_squared"]
    lookback_sessions: int = Field(gt=0)


class MomentumFactorContract(MomentumContractModel):
    version: str = MOMENTUM_RULESET_VERSION
    hypothesis: str = MOMENTUM_HYPOTHESIS
    required_dataset_columns: tuple[str, ...] = (
        "symbol",
        "date",
        "adjusted_close",
        "currency",
        "available_at",
        "confidence",
        "input_lineage",
        "price_basis",
        "corporate_action_status",
        "trading_calendar",
        "session_status",
        "timing_policy",
        "historical_provider",
        "historical_dataset",
        "historical_dataset_version",
        "historical_access_tier",
    )
    definitions: tuple[MomentumMetricDefinition, ...]
    benchmark_configurable: Literal[True] = True
    composite_score: Literal[False] = False
    ranking_calculated: Literal[False] = False


MOMENTUM_CONTRACT = MomentumFactorContract(
    definitions=(
        MomentumMetricDefinition(
            name="momentum_12_1",
            formula="adjusted_close[t-21] / adjusted_close[t-252] - 1",
            unit="return",
            lookback_sessions=252,
        ),
        MomentumMetricDefinition(
            name="momentum_6m",
            formula="adjusted_close[t] / adjusted_close[t-126] - 1",
            unit="return",
            lookback_sessions=126,
        ),
        MomentumMetricDefinition(
            name="relative_strength_6m",
            formula="asset 126-session return - compatible benchmark 126-session return",
            unit="return",
            lookback_sessions=126,
        ),
        MomentumMetricDefinition(
            name="volatility_adjusted_momentum_12_1",
            formula="12-1 percentage return / annualized std of daily log returns",
            unit="return_per_volatility",
            lookback_sessions=252,
        ),
        MomentumMetricDefinition(
            name="trend_stability_12m",
            formula="R-squared of OLS log(adjusted_close) on market-session index over 252 sessions",
            unit="r_squared",
            lookback_sessions=252,
        ),
    )
)


@dataclass(frozen=True)
class MomentumEvaluation:
    metrics: pd.DataFrame
    health: dict[str, Any]
    lineage: dict[str, Any]
    validation_report: dict[str, Any]


def _empty_row(
    *,
    experiment_id: str,
    symbol: str,
    metric: MomentumMetricDefinition,
    as_of: datetime.date,
    benchmark_symbol: str,
    dataset_lineage: dict[str, Any],
) -> dict[str, Any]:
    lineage = {"dataset": dataset_lineage, "price_inputs": [], "transformation": LOG_TRANSFORM}
    return {
        "experiment_id": experiment_id,
        "symbol": symbol,
        "metric": metric.name,
        "value": None,
        "unit": metric.unit,
        "currency": None,
        "as_of": as_of.isoformat(),
        "available_at": None,
        "confidence": 0.0,
        "status": "NOT_COMPUTED",
        "reason": None,
        "benchmark_symbol": benchmark_symbol if metric.name == "relative_strength_6m" else None,
        "price_basis": None,
        "corporate_action_status": None,
        "trading_calendar": None,
        "warnings": "[]",
        "lineage": json.dumps(lineage, sort_keys=True),
    }


def _lineage(frame: pd.DataFrame, dataset_lineage: dict[str, Any]) -> tuple[str, str | None]:
    inputs: list[dict[str, Any]] = []
    for raw in frame["input_lineage"]:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if (
            not isinstance(parsed, list)
            or not parsed
            or not all(isinstance(x, dict) and x for x in parsed)
        ):
            document = {
                "dataset": dataset_lineage,
                "price_inputs": [],
                "transformation": LOG_TRANSFORM,
            }
            return json.dumps(
                document, sort_keys=True
            ), "input_lineage must be a non-empty JSON list of objects"
        if any(not (x.get("source") or x.get("primary_source")) for x in parsed):
            document = {
                "dataset": dataset_lineage,
                "price_inputs": parsed,
                "transformation": LOG_TRANSFORM,
            }
            return json.dumps(document, sort_keys=True), "primary source missing from lineage"
        inputs.extend(parsed)
    unique = {json.dumps(item, sort_keys=True): item for item in inputs}
    corporate_actions: list[str] = []
    if "corporate_action_type" in frame:
        applied = frame["corporate_action_status"] == "APPLIED"
        corporate_actions = sorted(
            set(frame.loc[applied, "corporate_action_type"].dropna().astype(str))
        )
    document = {
        "dataset": dataset_lineage,
        "price_inputs": list(unique.values()),
        "price_field": "adjusted_close",
        "raw_close_role": "auxiliary_audit_only",
        "transformation": LOG_TRANSFORM,
        "corporate_actions": corporate_actions,
    }
    return json.dumps(document, sort_keys=True), None


def _prepare(
    frame: pd.DataFrame, as_of: datetime.date
) -> tuple[pd.DataFrame, str | None, TradingCalendar | None]:
    data = frame.copy()
    try:
        data["date"] = pd.to_datetime(data["date"], errors="raise").dt.date
        data["available_at"] = pd.to_datetime(data["available_at"], errors="raise", utc=False)
    except (TypeError, ValueError) as error:
        return data, f"invalid market-data date: {error}", None
    if any(value.tzinfo is None or value.utcoffset() is None for value in data["available_at"]):
        return data, "available_at must be timezone-aware", None
    cutoff = datetime.datetime.combine(as_of, datetime.time.max, tzinfo=datetime.UTC)
    if (data["date"] > as_of).any():
        return data, "future price date exceeds as_of", None
    if any(
        value.to_pydatetime().astimezone(datetime.UTC) > cutoff for value in data["available_at"]
    ):
        return data, "PIT violation: available_at exceeds as_of", None
    if data["date"].duplicated().any():
        return data, "duplicate market sessions", None
    if data["adjusted_close"].isna().any():
        return data, "missing adjusted prices", None
    try:
        data["adjusted_close"] = data["adjusted_close"].astype(float)
    except (TypeError, ValueError):
        return data, "adjusted prices must be numeric", None
    if (~np.isfinite(data["adjusted_close"])).any() or (data["adjusted_close"] <= 0).any():
        return data, "log transformation requires finite adjusted_close > 0", None
    data["log_adjusted_close"] = np.log(data["adjusted_close"])
    if (data["session_status"].astype(str) != "PRESENT").any():
        return data, "market-data gaps declared by session_status", None
    if set(data["price_basis"].astype(str)) != {"ADJUSTED"}:
        return data, "Momentum requires price_basis=ADJUSTED; unadjusted prices are rejected", None
    calendar_names = set(data["trading_calendar"].astype(str))
    if len(calendar_names) != 1:
        return data, "one explicit trading_calendar is required", None
    try:
        calendar = get_trading_calendar(next(iter(calendar_names)))
    except ValueError as error:
        return data, str(error), None
    data = data.sort_values("date").reset_index(drop=True)
    try:
        expected = set(calendar.sessions(data.iloc[0]["date"], data.iloc[-1]["date"]))
    except ValueError as error:
        return data, str(error), calendar
    observed = set(data["date"])
    missing = sorted(expected - observed)
    if missing:
        preview = ", ".join(day.isoformat() for day in missing[:3])
        return data, f"missing expected market sessions: {preview}", calendar
    unexpected = sorted(observed - expected)
    if unexpected:
        preview = ", ".join(day.isoformat() for day in unexpected[:3])
        return data, f"observations on non-market sessions: {preview}", calendar
    actions = set(data["corporate_action_status"].astype(str))
    if not actions or actions - {"NONE", "APPLIED"}:
        return data, "corporate_action_status must be provider-validated NONE or APPLIED", calendar
    if "APPLIED" in actions:
        if not {"corporate_action_type", "adjustment_factor"} <= set(data.columns):
            return data, "applied corporate actions require type and adjustment_factor", calendar
        affected = data["corporate_action_status"] == "APPLIED"
        types = set(data.loc[affected, "corporate_action_type"].dropna().astype(str))
        factors = pd.to_numeric(data.loc[affected, "adjustment_factor"], errors="coerce")
        if not types or types - {"SPLIT", "DIVIDEND", "SPLIT_AND_DIVIDEND"}:
            return data, "invalid corporate action type", calendar
        if factors.isna().any() or (~np.isfinite(factors)).any() or (factors <= 0).any():
            return data, "invalid corporate action adjustment_factor", calendar
        if "raw_close" in data:
            raw = pd.to_numeric(data.loc[affected, "raw_close"], errors="coerce")
            observed = data.loc[affected, "adjusted_close"] / raw
            if (
                raw.isna().any()
                or (~np.isfinite(raw)).any()
                or (raw <= 0).any()
                or not np.allclose(observed, factors, rtol=1e-10, atol=1e-12)
            ):
                return data, "adjusted/raw relationship does not validate", calendar
    return data, None, calendar


def _session_return(
    frame: pd.DataFrame, lookback: int, skip_recent: int = 0
) -> tuple[float | None, pd.DataFrame]:
    end_index = len(frame) - 1 - skip_recent
    start_index = len(frame) - 1 - lookback
    if start_index < 0 or end_index <= start_index:
        return None, frame.iloc[0:0]
    window = frame.iloc[start_index : end_index + 1]
    log_return = window.iloc[-1]["log_adjusted_close"] - window.iloc[0]["log_adjusted_close"]
    return float(math.expm1(log_return)), window


def _compatible_benchmark(asset: pd.DataFrame, benchmark: pd.DataFrame) -> str | None:
    for column in ("price_basis", "trading_calendar", "timing_policy"):
        if set(asset[column].astype(str)) != set(benchmark[column].astype(str)):
            return f"benchmark {column} mismatch"
    if tuple(asset.tail(127)["date"]) != tuple(benchmark.tail(127)["date"]):
        return "benchmark session calendar/timing mismatch"
    return None


def _metric_value(
    name: str, frame: pd.DataFrame, benchmark: pd.DataFrame | None, sessions_per_year: int
) -> tuple[float | None, pd.DataFrame, str | None]:
    if name == "momentum_12_1":
        value, window = _session_return(frame, 252, 21)
        return (
            value,
            window,
            None if value is not None else "insufficient prices for 252/21-session window",
        )
    if name == "momentum_6m":
        value, window = _session_return(frame, 126)
        return (
            value,
            window,
            None if value is not None else "insufficient prices for 126-session window",
        )
    if name == "relative_strength_6m":
        asset, window = _session_return(frame, 126)
        if benchmark is None:
            return None, window, "configured benchmark is missing"
        mismatch = _compatible_benchmark(frame, benchmark)
        if mismatch:
            return None, pd.concat([window, benchmark.tail(127)]), mismatch
        bench, bench_window = _session_return(benchmark, 126)
        if asset is None or bench is None:
            return (
                None,
                pd.concat([window, bench_window]),
                "insufficient asset or benchmark prices for relative strength",
            )
        return asset - bench, pd.concat([window, bench_window]), None
    if name == "volatility_adjusted_momentum_12_1":
        momentum, window = _session_return(frame, 252, 21)
        if momentum is None:
            return None, window, "insufficient prices for volatility-adjusted momentum"
        volatility = float(
            window["log_adjusted_close"].diff().dropna().std(ddof=1) * math.sqrt(sessions_per_year)
        )
        if not math.isfinite(volatility) or volatility <= 0:
            return None, window, "volatility is zero or invalid"
        return momentum / volatility, window, None
    if len(frame) < 253:
        return None, frame.iloc[0:0], "insufficient prices for 252-session trend stability"
    window = frame.tail(253)
    y = window["log_adjusted_close"].to_numpy(dtype=float)
    if np.var(y) == 0:
        return None, window, "trend variance is zero or invalid"
    return float(np.corrcoef(np.arange(len(window), dtype=float), y)[0, 1] ** 2), window, None


def evaluate_momentum_metrics(
    prices: pd.DataFrame,
    *,
    experiment_id: str,
    dataset_lineage: dict[str, Any],
    as_of: datetime.date,
    benchmark_symbol: str,
    low_confidence_threshold: float = 0.7,
    stale_after_sessions: int = 5,
    stale_after_days: int | None = None,
) -> MomentumEvaluation:
    if not benchmark_symbol.strip():
        raise ValueError("benchmark_symbol is required")
    if not math.isfinite(low_confidence_threshold) or not 0 <= low_confidence_threshold <= 1:
        raise ValueError("low_confidence_threshold must be finite and between 0 and 1")
    if stale_after_days is not None:
        stale_after_sessions = stale_after_days
    missing = sorted(set(MOMENTUM_CONTRACT.required_dataset_columns) - set(prices.columns))
    if missing:
        raise ValueError(f"missing momentum input columns: {', '.join(missing)}")
    if prices.empty:
        raise ValueError("momentum input dataset is empty")
    grouped = {str(symbol): group for symbol, group in prices.groupby("symbol", sort=True)}
    prepared = {symbol: _prepare(group, as_of) for symbol, group in grouped.items()}
    benchmark_key = benchmark_symbol.strip()
    benchmark_tuple = prepared.get(benchmark_key)
    if not any(symbol != benchmark_key for symbol in grouped):
        raise ValueError("momentum dataset must contain at least one non-benchmark symbol")
    rows: list[dict[str, Any]] = []
    for symbol in sorted(key for key in grouped if key != benchmark_key):
        frame, input_error, calendar = prepared[symbol]
        for definition in MOMENTUM_CONTRACT.definitions:
            row = _empty_row(
                experiment_id=experiment_id,
                symbol=symbol,
                metric=definition,
                as_of=as_of,
                benchmark_symbol=benchmark_key,
                dataset_lineage=dataset_lineage,
            )
            if input_error:
                row.update(
                    status="PIT_VIOLATION" if "PIT violation" in input_error else "INVALID_DATA",
                    reason=input_error,
                )
                rows.append(row)
                continue
            assert calendar is not None
            benchmark_frame = None
            if definition.name == "relative_strength_6m" and benchmark_tuple:
                benchmark_frame, benchmark_error, _ = benchmark_tuple
                if benchmark_error:
                    row.update(status="INVALID_DATA", reason=f"benchmark: {benchmark_error}")
                    rows.append(row)
                    continue
            value, used, error = _metric_value(
                definition.name, frame, benchmark_frame, calendar.sessions_per_year
            )
            sources = used if not used.empty else frame
            lineage, lineage_error = _lineage(sources, dataset_lineage)
            confidence_values = pd.to_numeric(sources["confidence"], errors="coerce")
            confidence = (
                float(confidence_values.min())
                if not confidence_values.empty and confidence_values.notna().all()
                else 0.0
            )
            currencies = set(frame["currency"].dropna().astype(str))
            actions = set(frame["corporate_action_status"].astype(str))
            status, reason = "PASS", None
            stale_sessions = len(
                calendar.sessions(frame.iloc[-1]["date"] + datetime.timedelta(days=1), as_of)
            )
            if stale_sessions > stale_after_sessions:
                status, reason = "STALE_PRICE", "latest adjusted price is stale in market sessions"
            elif error:
                status = "INVALID_DATA" if error.startswith("benchmark ") else "NOT_COMPUTED"
                reason = error
            elif lineage_error:
                status, reason = "INVALID_LINEAGE", lineage_error
            elif (
                confidence_values.isna().any()
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                status, reason = (
                    "MISSING_CONFIDENCE",
                    "confidence is required and must be finite between 0 and 1",
                )
            elif len(currencies) != 1 or "" in currencies:
                status, reason = "INVALID_DATA", "one explicit asset currency is required"
            elif confidence < low_confidence_threshold:
                status, reason = (
                    "LOW_CONFIDENCE",
                    f"input confidence {confidence:.4f} below {low_confidence_threshold:.4f}",
                )
            row.update(
                value=value,
                currency=next(iter(currencies)) if len(currencies) == 1 else None,
                available_at=max(str(x) for x in sources["available_at"]),
                confidence=confidence,
                status=status,
                reason=reason,
                price_basis="ADJUSTED",
                corporate_action_status=next(iter(actions)) if len(actions) == 1 else "MIXED",
                trading_calendar=calendar.name,
                warnings="[]",
                lineage=lineage,
            )
            rows.append(row)
    output = (
        pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        .sort_values(["symbol", "metric"])
        .reset_index(drop=True)
    )
    counts = {str(k): int(v) for k, v in output["status"].value_counts().sort_index().items()}
    invalid = int((output["status"] != "PASS").sum())
    health_status = "FAIL" if invalid else "PASS"
    safety = {
        "adjusted_prices": "required_fail_closed",
        "raw_close": "auxiliary_only",
        "log_price_layer": "implemented",
        "corporate_actions": "provider_actions_captured_adjusted_raw_relationship_validated",
        "independent_corporate_action_source": False,
        "trading_calendar": "versioned_historical_sessions",
        "trading_calendar_lineage": [
            json.loads(item)
            for item in sorted(
                {
                    json.dumps(calendar.lineage, sort_keys=True)
                    for _, error, calendar in prepared.values()
                    if error is None and calendar is not None
                }
            )
        ],
        "missing_sessions": "compared_expected_vs_observed",
        "stale_prices": "market_session_based",
        "benchmark_compatibility": "basis_calendar_timing_enforced",
        "same_close_timing": "research_only_no_execution",
        "full_market_data_audit": "completed",
    }
    health = {
        "schema_version": "momentum-health-v1.1",
        "status": health_status,
        "observations": len(output),
        "status_counts": counts,
        "market_data_safety": safety,
        "composite_score_calculated": False,
        "ranking_calculated": False,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "governance_mode": "research_legacy",
        "phase6_eligible": False,
    }
    lineage_doc = {
        "schema_version": "momentum-lineage-v1.1",
        "dataset": dataset_lineage,
        "benchmark_symbol": benchmark_key,
        "price_foundation": {"primary": "adjusted_close", "raw_close": "auxiliary_audit_only"},
        "corporate_action_policy": (
            "provider corporate actions captured + adjusted/raw relationship validated"
        ),
        "independent_corporate_action_source": False,
        "transformation": LOG_TRANSFORM,
        "metrics": [
            {"symbol": r["symbol"], "metric": r["metric"], "lineage": json.loads(r["lineage"])}
            for r in rows
        ],
    }
    report = {
        "schema_version": "momentum-validation-report-v1.1",
        "status": health_status,
        "checks": {
            "contracts": "implemented",
            "point_in_time": "implemented",
            "future_dates": "implemented",
            "adjusted_price_foundation": "implemented",
            "log_transformation": "implemented",
            "non_positive_prices": "fail_closed",
            "corporate_actions": (
                "provider_captured_adjusted_raw_relationship_validated_not_independent"
            ),
            "expected_market_sessions": "implemented",
            "stale_prices": "implemented",
            "session_windows": "implemented",
            "calendar_annualization": "implemented",
            "benchmark_compatibility": "implemented",
            "lineage_and_confidence": "implemented",
            "reproducibility": "runner_enforced",
            "market_data_audit": "completed",
        },
        "errors": invalid,
        "warnings": 0,
    }
    return MomentumEvaluation(output, health, lineage_doc, report)
