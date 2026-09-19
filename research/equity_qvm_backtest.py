"""Deterministic, research-only Equity QVM portfolio simulation.

This module consumes checksum-pinned PIT manifests and canonical Phase 6 QVM
artifacts.  Portfolio returns are deliberately supplied through a separate
total-return contract: factor-research adjusted prices are never reused.
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from governance.canonical import typed_hash
from research.datasets import file_sha256
from research.phase6_qvm import RULESET_VERSION, Phase6ResearchArtifact

ENGINE_VERSION = "equity-qvm-backtest-v1"
STRATEGY_VERSION = "equal-weight-top-cohort-next-rebalance-v1"
RETURN_CONVENTION = "USD_TOTAL_RETURN_WITH_DISTRIBUTIONS_AND_DELISTINGS"
RETURN_INPUT_SCHEMA = "backtest-total-return-input-v1"


class BacktestValidationError(ValueError):
    """Raised when a simulation input cannot be used without bias or silent loss."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HistoricalPITCut(FrozenModel):
    """One immutable PIT signal cut and the canonical QVM result derived from it."""

    cutoff: datetime.datetime
    signal_available_at: datetime.datetime
    holdings_effective_at: datetime.datetime
    manifest_path: Path
    manifest_sha256: str
    qvm: Phase6ResearchArtifact

    @model_validator(mode="after")
    def validate_chronology(self) -> Self:
        values = (self.cutoff, self.signal_available_at, self.holdings_effective_at)
        if any(value.tzinfo is None or value.utcoffset() is None for value in values):
            raise ValueError("cutoff chronology must be timezone-aware")
        if self.signal_available_at > self.cutoff:
            raise ValueError("look-ahead signal: availability exceeds cutoff")
        if self.holdings_effective_at <= self.cutoff:
            raise ValueError("holdings must begin after the signal cutoff")
        return self


class SecurityPeriodReturn(FrozenModel):
    security_id: str
    period_start: datetime.datetime
    period_end: datetime.datetime
    total_return: float
    available_at: datetime.datetime
    delisting_treatment: Literal["NO_DELISTING", "DELISTING_RETURN_INCLUDED"]
    delisting_event_id: str | None = None
    source_observation_id: str
    observation_hash: str

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        if self.security_id != self.security_id.strip().upper() or not self.security_id:
            raise ValueError("security_id must be canonical uppercase identity")
        if not self.source_observation_id.strip():
            raise ValueError("source observation identity is required")
        if not math.isfinite(self.total_return) or self.total_return < -1:
            raise ValueError("security total return must be finite and at least -100%")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("return availability must be timezone-aware")
        if not self.period_start < self.period_end:
            raise ValueError("return observation period is invalid")
        if self.delisting_treatment == "DELISTING_RETURN_INCLUDED" and not self.delisting_event_id:
            raise ValueError("included delisting return requires an event identity")
        if self.delisting_treatment == "NO_DELISTING" and self.delisting_event_id is not None:
            raise ValueError("non-delisting return cannot name a delisting event")
        expected = typed_hash(self.model_dump(mode="python", exclude={"observation_hash"}))
        if self.observation_hash != expected:
            raise ValueError("security return observation hash mismatch")
        return self


class TotalReturnInputArtifact(FrozenModel):
    schema_version: Literal["backtest-total-return-input-v1"] = RETURN_INPUT_SCHEMA
    period_start: datetime.datetime
    period_end: datetime.datetime
    convention: Literal["USD_TOTAL_RETURN_WITH_DISTRIBUTIONS_AND_DELISTINGS"] = (
        RETURN_CONVENTION
    )
    series_usage: Literal["PORTFOLIO_TOTAL_RETURN_ONLY"] = "PORTFOLIO_TOTAL_RETURN_ONLY"
    source_data_class: Literal["GOVERNED_TOTAL_RETURN_OBSERVATIONS"] = (
        "GOVERNED_TOTAL_RETURN_OBSERVATIONS"
    )
    factor_price_derived: Literal[False] = False
    pit_valid: Literal[True] = True
    source_identity: str
    corporate_action_semantics: str
    delisting_semantics: str
    observations: tuple[SecurityPeriodReturn, ...]
    artifact_hash: str

    @model_validator(mode="after")
    def validate_artifact(self, info: ValidationInfo) -> Self:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.period_start, self.period_end)
        ):
            raise ValueError("return input period must be timezone-aware")
        if not self.source_identity.strip():
            raise ValueError("return source identity is required")
        ordered = tuple(sorted(self.observations, key=lambda item: item.security_id))
        if self.observations != ordered:
            raise ValueError("return observations must use canonical security-id order")
        ids = [item.security_id.strip().upper() for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate security return observation")
        if any(
            item.period_start != self.period_start or item.period_end != self.period_end
            for item in self.observations
        ):
            raise ValueError("return observation period does not match input artifact")
        if not info.context or not info.context.get("skip_hash"):
            expected = typed_hash(self.model_dump(mode="python", exclude={"artifact_hash"}))
            if self.artifact_hash != expected:
                raise ValueError("total-return input artifact hash mismatch")
        return self


class HoldingPeriod(FrozenModel):
    signal_cutoff: datetime.datetime
    start: datetime.datetime
    end: datetime.datetime
    return_input: TotalReturnInputArtifact
    benchmark_input: TotalReturnInputArtifact | None = None

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if not self.start < self.end:
            raise ValueError("holding period end must follow start")
        if (self.return_input.period_start, self.return_input.period_end) != (self.start, self.end):
            raise ValueError("return input period does not match holding period")
        if any(item.available_at < self.end for item in self.return_input.observations):
            raise ValueError("future period return was available before period end")
        if self.benchmark_input is not None:
            if (self.benchmark_input.period_start, self.benchmark_input.period_end) != (
                self.start, self.end
            ):
                raise ValueError("benchmark input period does not match holding period")
            if len(self.benchmark_input.observations) != 1:
                raise ValueError("benchmark input requires exactly one observation")
            if self.benchmark_input.observations[0].available_at < self.end:
                raise ValueError("benchmark return cannot be available before period end")
        return self


class BacktestParameters(FrozenModel):
    transaction_cost_bps: float = Field(default=10.0, ge=0.0, le=50.0)
    annual_periods: int = Field(default=12, ge=1, le=366)
    annual_risk_free_rate: float = Field(default=0.0, ge=0.0, le=0.10)
    claim_legitimate_backtest: bool = False

    @property
    def run_classification(self) -> Literal["PREREGISTERED_BASELINE", "SENSITIVITY"]:
        return "PREREGISTERED_BASELINE" if self.transaction_cost_bps == 10.0 else "SENSITIVITY"


class BacktestPeriodResult(FrozenModel):
    signal_cutoff: datetime.datetime
    start: datetime.datetime
    end: datetime.datetime
    weights: dict[str, float]
    pre_trade_weights: dict[str, float]
    end_weights: dict[str, float]
    return_input_identity: str
    used_return_observations: tuple[SecurityPeriodReturn, ...]
    turnover: float
    transaction_cost: float
    gross_return: float
    net_return: float
    benchmark_return: float | None


class BacktestStatistics(FrozenModel):
    cumulative_return: float
    annualized_return: float | None
    annualized_volatility: float | None
    sharpe: float | None
    max_drawdown: float
    mean_turnover: float
    total_turnover: float
    rebalances: int
    observations: int
    hit_rate: float
    reporting_qualification: Literal[
        "INSUFFICIENT_SAMPLE_FOR_INFERENCE", "MECHANICAL_ONLY_NOT_RESEARCH_GRADE"
    ]
    cadence: Literal["MONTHLY"]


class EquityQVMBacktestResult(FrozenModel):
    schema_version: Literal["equity-qvm-backtest-result-v1"] = (
        "equity-qvm-backtest-result-v1"
    )
    engine_version: Literal["equity-qvm-backtest-v1"] = ENGINE_VERSION
    model_version: Literal["phase6-qvm-research-engine-v1"] = RULESET_VERSION
    strategy_version: Literal["equal-weight-top-cohort-next-rebalance-v1"] = STRATEGY_VERSION
    portfolio_rule: Literal["EQUAL_WEIGHT_QVM_TOP_COHORT_OVERLAY_PASS"] = (
        "EQUAL_WEIGHT_QVM_TOP_COHORT_OVERLAY_PASS"
    )
    lag_convention: Literal["SIGNAL_AT_CUTOFF_HOLD_FROM_NEXT_DECLARED_REBALANCE"] = (
        "SIGNAL_AT_CUTOFF_HOLD_FROM_NEXT_DECLARED_REBALANCE"
    )
    return_price_convention: Literal[
        "USD_TOTAL_RETURN_WITH_DISTRIBUTIONS_AND_DELISTINGS"
    ] = RETURN_CONVENTION
    parameters: BacktestParameters
    run_classification: Literal["PREREGISTERED_BASELINE", "SENSITIVITY"]
    cutoff_start: datetime.datetime
    cutoff_end: datetime.datetime
    input_manifest_identities: tuple[str, ...]
    qvm_artifact_identities: tuple[str, ...]
    periods: tuple[BacktestPeriodResult, ...]
    statistics: BacktestStatistics
    benchmark_status: Literal["AVAILABLE", "NOT_AVAILABLE"]
    benchmark_input_identities: tuple[str, ...]
    holding_convention: Literal["BUY_AND_HOLD_BETWEEN_DECLARED_REBALANCES"] = (
        "BUY_AND_HOLD_BETWEEN_DECLARED_REBALANCES"
    )
    cost_timing: Literal["ENTRY_REBALANCE_SIMPLE_RETURN_DEDUCTION"] = (
        "ENTRY_REBALANCE_SIMPLE_RETURN_DEDUCTION"
    )
    fully_invested: Literal[True] = True
    leverage_allowed: Literal[False] = False
    research_status: Literal["DETERMINISTIC_FIXTURE_BACKTEST"] = (
        "DETERMINISTIC_FIXTURE_BACKTEST"
    )
    survivorship_safe_history_verified: Literal[False] = False
    research_grade_backtest: Literal[False] = False
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    execution_authority: Literal["HUMAN_ONLY"] = "HUMAN_ONLY"
    live_execution_enabled: Literal[False] = False
    real_data_readiness: Literal["NOT_READY"] = "NOT_READY"
    artifact_hash: str

    @model_validator(mode="after")
    def validate_hash(self, info: ValidationInfo) -> Self:
        if info.context and info.context.get("skip_hash"):
            return self
        expected = typed_hash(self.model_dump(mode="python", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ValueError("backtest artifact hash mismatch")
        return self


def _manifest_identity(cut: HistoricalPITCut) -> str:
    path = cut.manifest_path.resolve()
    if not path.is_file() or file_sha256(path) != cut.manifest_sha256:
        raise BacktestValidationError("PIT manifest checksum mismatch")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BacktestValidationError(f"invalid PIT manifest: {error}") from error
    manifest_cutoff = datetime.datetime.fromisoformat(str(manifest.get("as_of", "")))
    if manifest_cutoff.tzinfo is None or manifest_cutoff.astimezone(datetime.UTC) != (
        cut.cutoff.astimezone(datetime.UTC)
    ):
        raise BacktestValidationError("PIT manifest cutoff does not match signal cut")
    if manifest.get("cross_layer_fingerprint") != cut.qvm.cross_layer_fingerprint:
        raise BacktestValidationError("QVM is not bound to the exact PIT manifest lineage")
    if cut.qvm.as_of.tzinfo is None or cut.qvm.as_of.utcoffset() is None:
        raise BacktestValidationError("QVM cutoff must be timezone-aware")
    if cut.qvm.as_of.astimezone(datetime.UTC) != cut.cutoff.astimezone(datetime.UTC):
        raise BacktestValidationError("QVM cutoff does not match signal cut")
    limitations = manifest.get("research_limitations", {})
    source_limitations = limitations if isinstance(limitations, dict) else {}
    if manifest.get("portfolio_return_ready") is True or source_limitations.get(
        "portfolio_return_ready"
    ) is True:
        raise BacktestValidationError(
            "V1 cannot promote provider declarations to legitimate backtest authority"
        )
    return cut.manifest_sha256


def _weights(qvm: Phase6ResearchArtifact) -> dict[str, float]:
    if qvm.cohort_publication_status != "PASS":
        raise BacktestValidationError("canonical QVM cohort publication did not pass")
    symbols = sorted(
        row.symbol.strip().upper()
        for row in qvm.cohorts
        if row.cohort == "TOP" and row.overlay == "PASS"
    )
    if not symbols:
        raise BacktestValidationError("QVM top cohort contains no overlay-PASS securities")
    if len(symbols) != len(set(symbols)):
        raise BacktestValidationError("conflicting QVM security identity in top cohort")
    weight = 1.0 / len(symbols)
    return {symbol: weight for symbol in symbols}


def _turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    if not previous:
        return 1.0
    return 0.5 * sum(
        abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0))
        for symbol in set(previous) | set(current)
    )


def _statistics(
    periods: list[BacktestPeriodResult], parameters: BacktestParameters
) -> BacktestStatistics:
    returns = [item.net_return for item in periods]
    wealth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        max_drawdown = min(max_drawdown, wealth / peak - 1.0)
    count = len(returns)
    annualized = wealth ** (parameters.annual_periods / count) - 1.0 if count else None
    volatility = None
    sharpe = None
    if count >= 2:
        mean = sum(returns) / count
        variance = sum((value - mean) ** 2 for value in returns) / (count - 1)
        volatility = math.sqrt(variance * parameters.annual_periods)
        if volatility > 0:
            sharpe = (mean * parameters.annual_periods - parameters.annual_risk_free_rate) / volatility
    turnovers = [item.turnover for item in periods]
    return BacktestStatistics(
        cumulative_return=wealth - 1.0,
        annualized_return=annualized,
        annualized_volatility=volatility,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        mean_turnover=sum(turnovers) / count,
        total_turnover=sum(turnovers),
        rebalances=count,
        observations=count,
        hit_rate=sum(value > 0 for value in returns) / count,
        reporting_qualification=(
            "INSUFFICIENT_SAMPLE_FOR_INFERENCE"
            if count < parameters.annual_periods
            else "MECHANICAL_ONLY_NOT_RESEARCH_GRADE"
        ),
        cadence="MONTHLY",
    )


def run_equity_qvm_backtest(
    *,
    cuts: tuple[HistoricalPITCut, ...],
    holding_periods: tuple[HoldingPeriod, ...],
    parameters: BacktestParameters | None = None,
) -> EquityQVMBacktestResult:
    """Simulate the frozen equal-weight top-cohort baseline, with a one-period lag."""
    parameters = parameters or BacktestParameters()
    cuts = tuple(HistoricalPITCut.model_validate(cut.model_dump(mode="python")) for cut in cuts)
    holding_periods = tuple(
        HoldingPeriod.model_validate(period.model_dump(mode="python"))
        for period in holding_periods
    )
    if parameters.claim_legitimate_backtest:
        raise BacktestValidationError(
            "legitimate backtest claim rejected: authentic Research Grade authorization, "
            "survivorship-safe history, and verified corporate-action economics are absent"
        )
    if not cuts or len(cuts) != len(holding_periods):
        raise BacktestValidationError("one holding period is required for every PIT cut")
    if parameters.annual_periods != 12:
        raise BacktestValidationError("monthly V1 holding periods require annual_periods=12")
    cutoffs = [cut.cutoff.astimezone(datetime.UTC) for cut in cuts]
    if cutoffs != sorted(cutoffs) or len(cutoffs) != len(set(cutoffs)):
        raise BacktestValidationError("PIT cutoffs must be unique and strictly increasing")
    manifest_ids = tuple(_manifest_identity(cut) for cut in cuts)
    if len(manifest_ids) != len(set(manifest_ids)):
        raise BacktestValidationError("duplicate PIT manifest identity")
    starts = [period.start.astimezone(datetime.UTC) for period in holding_periods]
    ends = [period.end.astimezone(datetime.UTC) for period in holding_periods]
    if any(
        not 20 <= (end - start).total_seconds() / 86_400 <= 35
        for start, end in zip(starts, ends, strict=True)
    ):
        raise BacktestValidationError("monthly V1 holding periods must span 20 to 35 days")
    if starts != sorted(starts) or any(
        starts[index] < ends[index - 1] for index in range(1, len(starts))
    ):
        raise BacktestValidationError("holding periods must be ordered and non-overlapping")

    previous: dict[str, float] = {}
    results: list[BacktestPeriodResult] = []
    benchmark_states: list[bool] = []
    for cut, period in zip(cuts, holding_periods, strict=True):
        if period.signal_cutoff != cut.cutoff or period.start != cut.holdings_effective_at:
            raise BacktestValidationError("holding period is not bound to its lagged signal cut")
        weights = _weights(cut.qvm)
        observations = {
            item.security_id.strip().upper(): item
            for item in period.return_input.observations
        }
        missing = sorted(set(weights) - set(observations))
        if missing:
            raise BacktestValidationError(
                "missing held-security return (delistings may not be silently dropped): "
                + ", ".join(missing)
            )
        turnover = _turnover(previous, weights)
        gross = sum(weights[symbol] * observations[symbol].total_return for symbol in weights)
        cost = turnover * parameters.transaction_cost_bps / 10_000.0
        if gross - cost <= -1.0:
            raise BacktestValidationError("net portfolio return cannot be -100% or lower")
        end_values = {
            symbol: weights[symbol] * (1.0 + observations[symbol].total_return)
            for symbol in weights
        }
        gross_wealth = sum(end_values.values())
        end_weights = (
            {symbol: value / gross_wealth for symbol, value in end_values.items()}
            if gross_wealth > 0
            else {}
        )
        used = tuple(observations[symbol] for symbol in sorted(weights))
        results.append(
            BacktestPeriodResult(
                signal_cutoff=cut.cutoff,
                start=period.start,
                end=period.end,
                weights=weights,
                pre_trade_weights=dict(sorted(previous.items())),
                end_weights=dict(sorted(end_weights.items())),
                return_input_identity=period.return_input.artifact_hash,
                used_return_observations=used,
                turnover=turnover,
                transaction_cost=cost,
                gross_return=gross,
                net_return=gross - cost,
                benchmark_return=(
                    period.benchmark_input.observations[0].total_return
                    if period.benchmark_input is not None
                    else None
                ),
            )
        )
        benchmark_states.append(period.benchmark_input is not None)
        previous = end_weights
    if any(benchmark_states) and not all(benchmark_states):
        raise BacktestValidationError("benchmark comparison must cover every holding period")

    payload = {
        "parameters": parameters,
        "run_classification": parameters.run_classification,
        "cutoff_start": cuts[0].cutoff,
        "cutoff_end": cuts[-1].cutoff,
        "input_manifest_identities": manifest_ids,
        "qvm_artifact_identities": tuple(cut.qvm.artifact_hash for cut in cuts),
        "periods": tuple(results),
        "statistics": _statistics(results, parameters),
        "benchmark_status": "AVAILABLE" if all(benchmark_states) else "NOT_AVAILABLE",
        "benchmark_input_identities": tuple(
            period.benchmark_input.artifact_hash
            for period in holding_periods
            if period.benchmark_input is not None
        ),
    }
    provisional = EquityQVMBacktestResult.model_validate(
        {**payload, "artifact_hash": "0" * 64}, context={"skip_hash": True}
    )
    artifact_hash = typed_hash(provisional.model_dump(mode="python", exclude={"artifact_hash"}))
    return EquityQVMBacktestResult(**payload, artifact_hash=artifact_hash)


def write_backtest_result(result: EquityQVMBacktestResult, *, output_root: Path) -> Path:
    """Write a content-addressed immutable result artifact."""
    output_dir = output_root / result.artifact_hash
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "backtest_result.json"
    payload = json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise BacktestValidationError("immutable backtest artifact conflict")
    path.write_text(payload, encoding="utf-8")
    return path
