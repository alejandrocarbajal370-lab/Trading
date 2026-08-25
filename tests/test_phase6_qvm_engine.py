from __future__ import annotations

import datetime
import math

import pytest
from pydantic import ValidationError

from factors.qvm import FactorObservation, metric_semantics_registry_identity
from governance.canonical import runtime_fingerprint, typed_hash
from research.phase6_qvm import (
    COHORT_POLICY,
    NORMALIZATION_POLICY_IDENTITY,
    OVERLAY_POLICY,
    WEIGHT_POLICY_IDENTITY,
    CohortPolicy,
    OverlayPolicy,
    Phase6ResearchArtifact,
    QVMCompositeResult,
    _cohorts,
    _factor_results,
    _hashed,
    _midranks,
    _normalize_metric,
)

AS_OF = datetime.date(2025, 1, 31)
AVAILABLE_AT = datetime.datetime(2025, 1, 30, tzinfo=datetime.UTC)


def _observation(
    index: int,
    *,
    factor: str = "Quality",
    metric: str = "roic",
    value: float | None = None,
    sector: str = "Industrials",
    industry: str = "Machinery",
    status: str = "PASS",
    confidence: float = 0.90,
) -> FactorObservation:
    units = {
        "roic": "percentage", "fcf_margin": "percentage", "cfo_conversion": "ratio",
        "raw_accrual_ratio": "ratio", "roic_stability": "ratio",
        "margin_stability": "ratio", "net_debt_to_ebitda": "multiple",
        "fcf_yield": "ratio", "ebit_yield": "ratio", "earnings_yield": "ratio",
        "momentum_12_1": "return", "volatility_adjusted_momentum_12_1": "return_per_volatility",
    }
    return FactorObservation(
        symbol=f"S{index:03d}", factor=factor, metric=metric,
        value=float(index if value is None else value) if status == "PASS" else None,
        unit=units[metric], as_of=AS_OF, available_at=AVAILABLE_AT, confidence=confidence,
        lineage={"fixture": "synthetic-phase6"}, universe_snapshot_id="fixture-universe",
        status=status, sector=sector, industry=industry,
        applicability="NOT_APPLICABLE" if status == "NOT_APPLICABLE" else "APPLICABLE",
    )


def test_frozen_no_variation_and_majority_tie_examples() -> None:
    no_variation = _normalize_metric([_observation(i, value=5) for i in range(20)], True)
    assert {item.reason for item in no_variation} == {"NO_CROSS_SECTIONAL_VARIATION"}
    assert all(item.score is None and not item.active_metric for item in no_variation)
    majority = _normalize_metric(
        [_observation(i, value=0 if i < 20 else 100) for i in range(21)], True
    )
    assert {item.reason for item in majority} == {"NO_CROSS_SECTIONAL_VARIATION"}


def test_frozen_midrank_example() -> None:
    assert _midranks([10, 10, 20, 40]) == [1.5, 1.5, 3.0, 4.0]


def test_peer_minimums_and_fallback_are_inclusive() -> None:
    industry = _normalize_metric([_observation(i) for i in range(20)], True)
    assert {item.peer_type for item in industry} == {"INDUSTRY"}
    sector_rows = [
        _observation(i, industry="A" if i < 19 else "B") for i in range(30)
    ]
    sector = _normalize_metric(sector_rows, True)
    assert {item.peer_type for item in sector} == {"SECTOR"}
    market_rows = [
        _observation(i, sector=f"S{i % 4}", industry=f"I{i % 10}") for i in range(100)
    ]
    market = _normalize_metric(market_rows, True)
    assert {item.peer_type for item in market} == {"MARKET_FALLBACK"}
    insufficient = _normalize_metric(market_rows[:99], True)
    assert {item.reason for item in insufficient} == {"INSUFFICIENT_PEER_GROUP"}


def test_directionality_lower_is_better_and_accrual_not_double_inverted() -> None:
    leverage = _normalize_metric([
        _observation(i, metric="net_debt_to_ebitda", value=i + 1) for i in range(20)
    ], True)
    assert leverage[0].directed_value == -1
    assert leverage[0].score > leverage[-1].score
    accrual = _normalize_metric([
        _observation(i, metric="raw_accrual_ratio", value=i / 100) for i in range(20)
    ], True)
    assert accrual[0].score > accrual[-1].score


def test_inactive_and_not_applicable_never_receive_score_or_weight() -> None:
    inactive = _normalize_metric([_observation(i) for i in range(20)], False)
    assert all(item.status == "INACTIVE" and item.score is None for item in inactive)
    not_applicable = _observation(
        0, metric="net_debt_to_ebitda", sector="Financials", industry="Banks",
        status="NOT_APPLICABLE",
    )
    result = _normalize_metric([not_applicable, *[_observation(
        i, metric="net_debt_to_ebitda") for i in range(1, 21)]], True)[0]
    assert result.missing_class == "NOT_APPLICABLE"
    assert result.score is None


def test_quality_active_denominator_excludes_not_applicable() -> None:
    metrics = []
    for name in ("roic", "fcf_margin", "cfo_conversion", "raw_accrual_ratio"):
        metrics.extend(_normalize_metric([_observation(i, metric=name) for i in range(20)], True))
    factor = next(item for item in _factor_results(metrics) if item.symbol == "S000")
    assert factor.active_denominator == pytest.approx(0.70)
    assert factor.coverage == 1
    assert factor.eligible


def test_nan_and_infinity_rejected_before_scoring() -> None:
    nan_rows = [_observation(0, value=math.nan), *[_observation(i) for i in range(1, 21)]]
    assert _normalize_metric(nan_rows, True)[0].status == "INELIGIBLE"
    inf_rows = [_observation(0, value=math.inf), *[_observation(i) for i in range(1, 21)]]
    with pytest.raises(ValueError):
        _normalize_metric(inf_rows, True)


def test_normalized_result_hash_is_mutation_resistant() -> None:
    result = _normalize_metric([_observation(i) for i in range(20)], True)[0]
    payload = result.model_dump(mode="python")
    payload["peer_size"] = 21
    with pytest.raises(ValidationError, match="hash mismatch"):
        type(result)(**payload)


def test_artifact_lineage_fields_are_mutation_resistant() -> None:
    governance_order = ("availability", "entity_resolution")
    governance_identity = typed_hash({
        "schema_version": "phase6-governance-order-identity-v1",
        "version": "fixture-v1", "order": governance_order,
    })
    active_metric_set = ("Quality.roic",)
    artifact = _hashed(Phase6ResearchArtifact, {
        "admission_contract_version": "sealed-pre-phase6-admission-v2",
        "admission_artifact_hash": "a" * 64, "qvm_sealed_lineage_hash": "b" * 64,
        "factor_batch_hashes": {"Quality": "c" * 64},
        "metric_registry_identity": metric_semantics_registry_identity(),
        "peer_assignment_hash": "d" * 64,
        "normalization_policy_identity": NORMALIZATION_POLICY_IDENTITY,
        "weight_policy_identity": WEIGHT_POLICY_IDENTITY,
        "overlay_policy": OVERLAY_POLICY, "cohort_policy": COHORT_POLICY,
        "governance_order_version": "fixture-v1", "governance_order": governance_order,
        "governance_order_identity": governance_identity,
        "active_metric_set": active_metric_set,
        "active_metric_set_identity": typed_hash({
            "schema_version": "phase6-active-metric-set-v1", "metrics": active_metric_set,
        }),
        "runtime": runtime_fingerprint(), "metrics": (), "factors": (), "composites": (),
        "cohorts": (), "cohort_publication_status": "FAIL",
        "cohort_publication_reason": "fixture",
    }, field="artifact_hash")
    for field, value in (
        ("factor_batch_hashes", {"Quality": "e" * 64}),
        ("active_metric_set", ("Quality.fcf_margin",)),
        ("peer_assignment_hash", "f" * 64),
        ("metric_registry_identity", "0" * 64),
        ("normalization_policy_identity", "1" * 64),
        ("weight_policy_identity", "2" * 64),
    ):
        payload = artifact.model_dump(mode="python")
        payload[field] = value
        with pytest.raises(ValidationError, match="(artifact hash|identity) mismatch"):
            Phase6ResearchArtifact(**payload)


def test_reorder_determinism_and_canonical_result_hashes() -> None:
    rows = [_observation(i) for i in range(20)]
    first = _normalize_metric(rows, True)
    second = _normalize_metric(list(reversed(rows)), True)
    assert first == second


def test_overlay_and_cohort_policy_stale_hashes_are_rejected() -> None:
    overlay = OVERLAY_POLICY.model_dump(mode="python")
    overlay["leverage_block_threshold"] = 5.5
    with pytest.raises(ValidationError, match="overlay policy hash mismatch"):
        OverlayPolicy(**overlay)
    cohort = COHORT_POLICY.model_dump(mode="python")
    cohort["minimum_eligible_count"] = 99
    with pytest.raises(ValidationError, match="cohort policy hash mismatch"):
        CohortPolicy(**cohort)


def _composite(index: int, score: float, overlay: str = "PASS") -> QVMCompositeResult:
    return _hashed(QVMCompositeResult, {
        "symbol": f"S{index:03d}", "quality": score, "value": score, "momentum": score,
        "composite": score, "all_primary_equal_sensitivity": score,
        "model_status": "ELIGIBLE", "overlay": overlay, "overlay_flags": (),
    })


def test_cohort_boundary_ties_expand_and_symbol_is_display_only() -> None:
    scores = [100 - i for i in range(100)]
    for index in range(8, 12):
        scores[index] = 91
    cohorts, status, _ = _cohorts([_composite(i, score) for i, score in enumerate(scores)])
    assert status == "PASS"
    assert sum(item.cohort == "TOP" for item in cohorts) == 12
    tied = [item for item in cohorts if item.symbol in {f"S{i:03d}" for i in range(8, 12)}]
    assert len({item.economic_rank for item in tied}) == 1


def test_review_is_not_publishable_in_top_cohort() -> None:
    inputs = [_composite(i, 100 - i, "REVIEW" if i == 0 else "PASS") for i in range(100)]
    cohorts, _, _ = _cohorts(inputs)
    assert next(item for item in cohorts if item.symbol == "S000").cohort is None


def test_cohort_publication_fails_below_one_hundred() -> None:
    cohorts, status, reason = _cohorts([_composite(i, 60 - i) for i in range(60)])
    assert cohorts == []
    assert status == "FAIL"
    assert "100" in str(reason)
