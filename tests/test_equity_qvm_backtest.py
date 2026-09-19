from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from factors.qvm import metric_semantics_registry_identity
from governance.canonical import runtime_fingerprint, typed_hash
from research.datasets import file_sha256
from research.equity_qvm_backtest import (
    BacktestParameters,
    BacktestValidationError,
    HistoricalPITCut,
    HoldingPeriod,
    SecurityPeriodReturn,
    run_equity_qvm_backtest,
    write_backtest_result,
)
from research.phase6_qvm import (
    COHORT_POLICY,
    NORMALIZATION_POLICY_IDENTITY,
    OVERLAY_POLICY,
    WEIGHT_POLICY_IDENTITY,
    Phase6ResearchArtifact,
    ResearchCohortResult,
    _hashed,
)

UTC = datetime.UTC


def _qvm(top: tuple[str, ...], identity: str) -> Phase6ResearchArtifact:
    cohorts = tuple(
        _hashed(
            ResearchCohortResult,
            {
                "symbol": symbol,
                "display_position": index,
                "economic_rank": float(index),
                "percentile": index / 10,
                "bucket": "QUINTILE_1",
                "cohort": "TOP",
                "overlay": "PASS",
            },
        )
        for index, symbol in enumerate(top, start=1)
    )
    governance_order = ("availability", "entity_resolution")
    active = ("Quality.roic",)
    return _hashed(
        Phase6ResearchArtifact,
        {
            "admission_contract_version": "sealed-pre-phase6-admission-v2",
            "admission_artifact_hash": typed_hash({"cut": identity}),
            "qvm_sealed_lineage_hash": typed_hash({"lineage": identity}),
            "factor_batch_hashes": {"Quality": typed_hash({"batch": identity})},
            "metric_registry_identity": metric_semantics_registry_identity(),
            "peer_assignment_hash": typed_hash({"peers": identity}),
            "normalization_policy_identity": NORMALIZATION_POLICY_IDENTITY,
            "weight_policy_identity": WEIGHT_POLICY_IDENTITY,
            "overlay_policy": OVERLAY_POLICY,
            "cohort_policy": COHORT_POLICY,
            "governance_order_version": "fixture-v1",
            "governance_order": governance_order,
            "governance_order_identity": typed_hash(
                {
                    "schema_version": "phase6-governance-order-identity-v1",
                    "version": "fixture-v1",
                    "order": governance_order,
                }
            ),
            "active_metric_set": active,
            "active_metric_set_identity": typed_hash(
                {"schema_version": "phase6-active-metric-set-v1", "metrics": active}
            ),
            "runtime": runtime_fingerprint(),
            "metrics": (),
            "factors": (),
            "composites": (),
            "cohorts": cohorts,
            "cohort_publication_status": "PASS",
            "cohort_publication_reason": None,
        },
        field="artifact_hash",
    )


def _inputs(tmp_path: Path, *, reverse_returns: bool = False):
    starts = (
        datetime.datetime(2025, 2, 3, 14, 30, tzinfo=UTC),
        datetime.datetime(2025, 3, 3, 14, 30, tzinfo=UTC),
        datetime.datetime(2025, 4, 1, 13, 30, tzinfo=UTC),
    )
    cutoffs = (
        datetime.datetime(2025, 1, 31, 21, 0, tzinfo=UTC),
        datetime.datetime(2025, 2, 28, 21, 0, tzinfo=UTC),
        datetime.datetime(2025, 3, 31, 20, 0, tzinfo=UTC),
    )
    ends = (starts[1], starts[2], datetime.datetime(2025, 5, 1, 20, 0, tzinfo=UTC))
    tops = (("AAA", "BBB"), ("BBB", "CCC"), ("BBB", "DDD"))
    values = ({"AAA": 0.10, "BBB": 0.00}, {"BBB": -0.10, "CCC": -0.20}, {"BBB": 0.04, "DDD": 0.06})
    cuts = []
    periods = []
    for index, (cutoff, start, end, top, returns) in enumerate(
        zip(cutoffs, starts, ends, tops, values, strict=True), start=1
    ):
        manifest = tmp_path / f"manifest-{index}.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "pit-equity-research-files-v1",
                    "as_of": cutoff.isoformat(),
                    "research_limitations": {
                        "survivorship_free_history_verified": False,
                        "portfolio_return_ready": False,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        cuts.append(
            HistoricalPITCut(
                cutoff=cutoff,
                signal_available_at=cutoff - datetime.timedelta(minutes=1),
                holdings_effective_at=start,
                manifest_path=manifest,
                manifest_sha256=file_sha256(manifest),
                qvm=_qvm(top, str(index)),
            )
        )
        observations = [
            SecurityPeriodReturn(
                symbol=symbol,
                total_return=value,
                available_at=end,
                delisting_treatment="NO_DELISTING",
            )
            for symbol, value in returns.items()
        ]
        if reverse_returns:
            observations.reverse()
        periods.append(
            HoldingPeriod(
                signal_cutoff=cutoff,
                start=start,
                end=end,
                returns=tuple(observations),
            )
        )
    return tuple(cuts), tuple(periods)


def test_hand_checked_portfolio_math_statistics_and_artifact(tmp_path: Path) -> None:
    cuts, periods = _inputs(tmp_path)
    result = run_equity_qvm_backtest(cuts=cuts, holding_periods=periods)

    assert result.periods[0].weights == {"AAA": 0.5, "BBB": 0.5}
    assert result.periods[1].turnover == pytest.approx(0.5)
    assert result.periods[1].transaction_cost == pytest.approx(0.0005)
    assert result.periods[0].gross_return == pytest.approx(0.05)
    assert result.periods[0].net_return == pytest.approx(0.049)
    assert result.periods[1].net_return == pytest.approx(-0.1505)

    expected_wealth = (1 + 0.049) * (1 - 0.1505) * (1 + 0.0495)
    expected_drawdown = (1 + 0.049) * (1 - 0.1505) / (1 + 0.049) - 1
    assert result.statistics.cumulative_return == pytest.approx(expected_wealth - 1)
    assert result.statistics.max_drawdown == pytest.approx(expected_drawdown)
    assert result.statistics.rebalances == result.statistics.observations == 3
    assert result.benchmark_status == "NOT_AVAILABLE"
    assert result.research_status == "DETERMINISTIC_FIXTURE_BACKTEST"
    assert not result.research_grade_backtest and not result.live_execution_enabled

    path = write_backtest_result(result, output_root=tmp_path / "results")
    assert path.parent.name == result.artifact_hash
    assert json.loads(path.read_text())["artifact_hash"] == result.artifact_hash


def test_return_row_order_does_not_change_result(tmp_path: Path) -> None:
    cuts, periods = _inputs(tmp_path)
    first = run_equity_qvm_backtest(cuts=cuts, holding_periods=periods)
    _, reversed_periods = _inputs(tmp_path, reverse_returns=True)
    second = run_equity_qvm_backtest(cuts=cuts, holding_periods=reversed_periods)
    assert first == second


def test_duplicate_or_non_monotonic_cutoffs_fail(tmp_path: Path) -> None:
    cuts, periods = _inputs(tmp_path)
    with pytest.raises(BacktestValidationError, match="unique and strictly increasing"):
        run_equity_qvm_backtest(cuts=(cuts[0], cuts[0], cuts[2]), holding_periods=periods)
    with pytest.raises(BacktestValidationError, match="unique and strictly increasing"):
        run_equity_qvm_backtest(cuts=(cuts[1], cuts[0], cuts[2]), holding_periods=periods)


def test_lookahead_signal_and_same_period_holding_fail(tmp_path: Path) -> None:
    cuts, _ = _inputs(tmp_path)
    payload = cuts[0].model_dump(mode="python")
    payload["signal_available_at"] = cuts[0].cutoff + datetime.timedelta(seconds=1)
    with pytest.raises(ValidationError, match="look-ahead signal"):
        HistoricalPITCut(**payload)
    payload["signal_available_at"] = cuts[0].cutoff
    payload["holdings_effective_at"] = cuts[0].cutoff
    with pytest.raises(ValidationError, match="holdings must begin after"):
        HistoricalPITCut(**payload)


def test_missing_held_security_return_fails_closed(tmp_path: Path) -> None:
    cuts, periods = _inputs(tmp_path)
    payload = periods[0].model_dump(mode="python")
    payload["returns"] = payload["returns"][:1]
    with pytest.raises(BacktestValidationError, match="delistings may not be silently dropped"):
        run_equity_qvm_backtest(
            cuts=cuts,
            holding_periods=(HoldingPeriod(**payload), *periods[1:]),
        )


def test_inconsistent_price_convention_and_duplicate_identity_fail(tmp_path: Path) -> None:
    _, periods = _inputs(tmp_path)
    payload = periods[0].model_dump(mode="python")
    payload["price_convention"] = "SPLIT_ADJUSTED_CLOSE"
    with pytest.raises(ValidationError):
        HoldingPeriod(**payload)
    payload = periods[0].model_dump(mode="python")
    payload["returns"] = (payload["returns"][0], payload["returns"][0])
    with pytest.raises(ValidationError, match="duplicate security return"):
        HoldingPeriod(**payload)


def test_tampered_manifest_and_legitimate_claim_fail_closed(tmp_path: Path) -> None:
    cuts, periods = _inputs(tmp_path)
    cuts[0].manifest_path.write_text("{}", encoding="utf-8")
    with pytest.raises(BacktestValidationError, match="checksum mismatch"):
        run_equity_qvm_backtest(cuts=cuts, holding_periods=periods)

    cuts, periods = _inputs(tmp_path)
    with pytest.raises(BacktestValidationError, match="legitimate backtest claim rejected"):
        run_equity_qvm_backtest(
            cuts=cuts,
            holding_periods=periods,
            parameters=BacktestParameters(claim_legitimate_backtest=True),
        )


def test_benchmark_is_optional_but_must_be_complete_and_pit_valid(tmp_path: Path) -> None:
    cuts, periods = _inputs(tmp_path)
    payload = periods[0].model_dump(mode="python")
    payload["benchmark_return"] = 0.01
    with pytest.raises(ValidationError, match="PIT-valid"):
        HoldingPeriod(**payload)
    payload["benchmark_pit_valid"] = True
    first = HoldingPeriod(**payload)
    with pytest.raises(BacktestValidationError, match="cover every holding period"):
        run_equity_qvm_backtest(cuts=cuts, holding_periods=(first, *periods[1:]))


def test_transaction_cost_parameter_is_narrow() -> None:
    with pytest.raises(ValidationError):
        BacktestParameters(transaction_cost_bps=50.01)
    assert math.isclose(BacktestParameters().transaction_cost_bps, 10.0)
