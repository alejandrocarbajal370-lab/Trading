from __future__ import annotations

import math
from collections import defaultdict
from enum import StrEnum
from statistics import NormalDist, median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from factors.qvm import (
    METRIC_SEMANTICS_REGISTRY,
    FactorObservation,
    factor_observation_hash,
    metric_semantics_registry_identity,
)
from governance.canonical import RuntimeFingerprint, runtime_fingerprint, typed_hash
from governance.research_chain import GovernedFactorBatch
from research.pre_phase6_readiness import (
    PrePhase6Admission,
    admit_sealed_for_phase6,
)

RULESET_VERSION = "phase6-qvm-research-engine-v1"
TRANSFORMATION_VERSION = "rank-gaussian-5mad-v1"
WEIGHT_POLICY_VERSION = "phase6-frozen-baseline-weights-v1"
OVERLAY_POLICY_VERSION = "capital-preservation-overlay-v1"
COHORT_POLICY_VERSION = "phase6-research-cohorts-v1"
GOVERNANCE_ORDER_IDENTITY_VERSION = "phase6-governance-order-identity-v1"

PRIMARY_WEIGHTS: dict[str, dict[str, float]] = {
    "Quality": {
        "roic": 0.20,
        "fcf_margin": 0.20,
        "cfo_conversion": 0.15,
        "raw_accrual_ratio": 0.15,
        "roic_stability": 0.10,
        "margin_stability": 0.10,
        "net_debt_to_ebitda": 0.10,
    },
    "Value": {"fcf_yield": 0.40, "ebit_yield": 0.35, "earnings_yield": 0.25},
    "Momentum": {"momentum_12_1": 0.60, "volatility_adjusted_momentum_12_1": 0.40},
}


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeferredOverlayControl(ResearchModel):
    control_id: Literal[
        "dilution",
        "restatement-materiality",
        "FCF-history",
        "corporate-action",
    ]
    state: Literal["DEFERRED"] = "DEFERRED"
    reason: Literal["MISSING_GOVERNED_PIT_CONTRACT_OR_PROVIDER"] = (
        "MISSING_GOVERNED_PIT_CONTRACT_OR_PROVIDER"
    )


class OverlayPolicy(ResearchModel):
    policy_version: Literal["capital-preservation-overlay-v1"] = OVERLAY_POLICY_VERSION
    leverage_review_threshold: float = 4.0
    leverage_block_threshold: float = 6.0
    cfo_conversion_review_threshold: float = 0.8
    accrual_review_threshold: float = 0.10
    leverage_block_flag: Literal["EXTREME_LEVERAGE_BLOCK"] = "EXTREME_LEVERAGE_BLOCK"
    leverage_review_flag: Literal["EXTREME_LEVERAGE_REVIEW"] = "EXTREME_LEVERAGE_REVIEW"
    cfo_review_flag: Literal["CFO_CONVERSION_REVIEW"] = "CFO_CONVERSION_REVIEW"
    accrual_review_flag: Literal["ACCRUAL_REVIEW"] = "ACCRUAL_REVIEW"
    missing_metric_semantics: Literal["NO_FLAG"] = "NO_FLAG"
    deferred_controls: tuple[DeferredOverlayControl, ...] = (
        DeferredOverlayControl(control_id="dilution"),
        DeferredOverlayControl(control_id="restatement-materiality"),
        DeferredOverlayControl(control_id="FCF-history"),
        DeferredOverlayControl(control_id="corporate-action"),
    )
    outcome_mapping: tuple[str, ...] = ("PASS", "REVIEW", "BLOCK")
    governance_position: Literal["AFTER_COMPOSITE_ELIGIBILITY"] = (
        "AFTER_COMPOSITE_ELIGIBILITY"
    )
    policy_hash: str

    @model_validator(mode="after")
    def verify_policy_hash(self, info: ValidationInfo) -> OverlayPolicy:
        required = {"dilution", "restatement-materiality", "FCF-history", "corporate-action"}
        if {control.control_id for control in self.deferred_controls} != required or len(
            self.deferred_controls
        ) != len(required):
            raise ValueError("overlay policy missing required deferred controls")
        if not (info.context and info.context.get("skip_hash")) and typed_hash(
            self.model_dump(mode="python", exclude={"policy_hash"})
        ) != self.policy_hash:
            raise ValueError("overlay policy hash mismatch")
        return self


class CohortPolicy(ResearchModel):
    policy_version: Literal["phase6-research-cohorts-v1"] = COHORT_POLICY_VERSION
    cohort_mode_hierarchy: tuple[Literal["DECILES", "QUINTILES", "NONE"], ...] = (
        "DECILES", "QUINTILES", "NONE",
    )
    decile_minimum_eligible_count: int = 100
    quintile_minimum_eligible_count: int = 50
    decile_bucket_count: Literal[10] = 10
    quintile_bucket_count: Literal[5] = 5
    decile_top_fraction: float = 0.10
    quintile_top_fraction: float = 0.20
    middle_lower_fraction: float = 0.40
    middle_upper_fraction: float = 0.60
    decile_bottom_fraction: float = 0.10
    quintile_bottom_fraction: float = 0.20
    cohort_definitions: tuple[str, ...] = (
        "DECILES_TOP_10_MIDDLE_40_60_BOTTOM_10",
        "QUINTILES_TOP_20_MIDDLE_40_60_BOTTOM_20_FALLBACK",
        "NONE_BELOW_50",
    )
    tie_boundary_policy: Literal["EXPAND_DO_NOT_SPLIT_EQUAL_COMPOSITES"] = (
        "EXPAND_DO_NOT_SPLIT_EQUAL_COMPOSITES"
    )
    economic_order: tuple[str, ...] = ("composite", "quality", "value", "momentum")
    display_tiebreaker: Literal["SYMBOL_ONLY"] = "SYMBOL_ONLY"
    minimum_complete_fraction: float = 0.60
    top_review_semantics: Literal["EXCLUDE_FROM_TOP"] = "EXCLUDE_FROM_TOP"
    research_only: Literal[True] = True
    policy_hash: str

    @model_validator(mode="after")
    def verify_policy_hash(self, info: ValidationInfo) -> CohortPolicy:
        if self.cohort_mode_hierarchy != ("DECILES", "QUINTILES", "NONE"):
            raise ValueError("invalid cohort mode hierarchy")
        if (
            self.decile_minimum_eligible_count != 100
            or self.quintile_minimum_eligible_count != 50
        ):
            raise ValueError("invalid cohort eligibility thresholds")
        if not (info.context and info.context.get("skip_hash")) and typed_hash(
            self.model_dump(mode="python", exclude={"policy_hash"})
        ) != self.policy_hash:
            raise ValueError("cohort policy hash mismatch")
        return self


class MetricStatus(StrEnum):
    SCORED = "SCORED"
    INACTIVE = "INACTIVE"
    INELIGIBLE = "INELIGIBLE"


class MissingClass(StrEnum):
    STRUCTURAL_MISSING = "STRUCTURAL_MISSING"
    PROVIDER_MISSING = "PROVIDER_MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PIT_UNAVAILABLE = "PIT_UNAVAILABLE"
    INVALID_QUALITY = "INVALID_QUALITY"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class NormalizedMetricResult(ResearchModel):
    schema_version: Literal["phase6-normalized-metric-v1"] = "phase6-normalized-metric-v1"
    symbol: str
    factor: Literal["Quality", "Value", "Momentum"]
    metric: str
    raw_value: float | None
    directed_value: float | None
    clipped_value: float | None
    clip_lower: float | None
    clip_upper: float | None
    peer_type: Literal["INDUSTRY", "SECTOR", "MARKET", "MARKET_FALLBACK"] | None
    peer_id: str | None
    peer_size: int = Field(ge=0)
    rank: float | None
    percentile: float | None
    score: float | None
    status: MetricStatus
    reason: str | None
    missing_class: MissingClass | None
    active_metric: bool
    source_observation_hash: str
    transformation_version: Literal["rank-gaussian-5mad-v1"] = TRANSFORMATION_VERSION
    result_hash: str

    @model_validator(mode="after")
    def verify_hash(self, info: ValidationInfo) -> NormalizedMetricResult:
        if info.context and info.context.get("skip_hash"):
            return self
        if typed_hash(self.model_dump(mode="python", exclude={"result_hash"})) != self.result_hash:
            raise ValueError("normalized metric result hash mismatch")
        return self


class FactorScoreResult(ResearchModel):
    schema_version: Literal["phase6-factor-score-v1"] = "phase6-factor-score-v1"
    symbol: str
    factor: Literal["Quality", "Value", "Momentum"]
    score: float | None
    eligible: bool
    coverage: float
    active_denominator: float
    available_weight: float
    active_metrics: tuple[str, ...]
    available_metrics: tuple[str, ...]
    reason: str | None
    weight_policy_version: Literal["phase6-frozen-baseline-weights-v1"] = WEIGHT_POLICY_VERSION
    result_hash: str

    @model_validator(mode="after")
    def verify_hash(self, info: ValidationInfo) -> FactorScoreResult:
        if info.context and info.context.get("skip_hash"):
            return self
        if typed_hash(self.model_dump(mode="python", exclude={"result_hash"})) != self.result_hash:
            raise ValueError("factor score result hash mismatch")
        return self


class QVMCompositeResult(ResearchModel):
    schema_version: Literal["phase6-qvm-composite-v1"] = "phase6-qvm-composite-v1"
    symbol: str
    quality: float | None
    value: float | None
    momentum: float | None
    composite: float | None
    all_primary_equal_sensitivity: float | None
    model_status: Literal["ELIGIBLE", "MODEL_INELIGIBLE", "BLOCKED"]
    overlay: Literal["PASS", "REVIEW", "BLOCK"]
    overlay_flags: tuple[str, ...]
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    research_only: Literal[True] = True
    result_hash: str

    @model_validator(mode="after")
    def verify_hash(self, info: ValidationInfo) -> QVMCompositeResult:
        if info.context and info.context.get("skip_hash"):
            return self
        if typed_hash(self.model_dump(mode="python", exclude={"result_hash"})) != self.result_hash:
            raise ValueError("QVM composite result hash mismatch")
        return self


class ResearchCohortResult(ResearchModel):
    schema_version: Literal["phase6-research-cohort-v1"] = "phase6-research-cohort-v1"
    symbol: str
    display_position: int
    economic_rank: float
    percentile: float
    bucket: str
    cohort: Literal["TOP", "MIDDLE", "BOTTOM"] | None
    overlay: Literal["PASS", "REVIEW", "BLOCK"]
    research_only: Literal[True] = True
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    result_hash: str

    @model_validator(mode="after")
    def verify_hash(self, info: ValidationInfo) -> ResearchCohortResult:
        if info.context and info.context.get("skip_hash"):
            return self
        if typed_hash(self.model_dump(mode="python", exclude={"result_hash"})) != self.result_hash:
            raise ValueError("research cohort result hash mismatch")
        return self


class Phase6ResearchArtifact(ResearchModel):
    schema_version: Literal["phase6-qvm-research-artifact-v1"] = (
        "phase6-qvm-research-artifact-v1"
    )
    ruleset_version: Literal["phase6-qvm-research-engine-v1"] = RULESET_VERSION
    admission_contract_version: Literal["sealed-pre-phase6-admission-v2"]
    admission_artifact_hash: str
    qvm_sealed_lineage_hash: str
    factor_batch_hashes: dict[str, str]
    metric_registry_identity: str
    peer_assignment_hash: str
    normalization_policy_identity: str
    weight_policy_identity: str
    overlay_policy: OverlayPolicy
    cohort_policy: CohortPolicy
    governance_order_version: str
    governance_order: tuple[str, ...]
    governance_order_identity: str
    active_metric_set: tuple[str, ...]
    active_metric_set_identity: str
    runtime: RuntimeFingerprint
    metrics: tuple[NormalizedMetricResult, ...]
    factors: tuple[FactorScoreResult, ...]
    composites: tuple[QVMCompositeResult, ...]
    cohorts: tuple[ResearchCohortResult, ...]
    cohort_publication_status: Literal["PASS", "FAIL"]
    cohort_publication_reason: str | None
    real_data_readiness: Literal["NOT_READY"] = "NOT_READY"
    synthetic_contract_only: Literal[True] = True
    portfolio_constructed: Literal[False] = False
    backtesting_performed: Literal[False] = False
    execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    artifact_hash: str

    @model_validator(mode="after")
    def verify_hash(self, info: ValidationInfo) -> Phase6ResearchArtifact:
        if info.context and info.context.get("skip_hash"):
            return self
        if self.metric_registry_identity != metric_semantics_registry_identity():
            raise ValueError("metric registry identity mismatch")
        if self.normalization_policy_identity != NORMALIZATION_POLICY_IDENTITY:
            raise ValueError("normalization policy identity mismatch")
        if self.weight_policy_identity != WEIGHT_POLICY_IDENTITY:
            raise ValueError("weight policy identity mismatch")
        if self.overlay_policy != OVERLAY_POLICY:
            raise ValueError("overlay policy is not the executed policy")
        if self.cohort_policy != COHORT_POLICY:
            raise ValueError("cohort policy is not the executed policy")
        expected_governance = typed_hash(
            {
                "schema_version": GOVERNANCE_ORDER_IDENTITY_VERSION,
                "version": self.governance_order_version,
                "order": self.governance_order,
            }
        )
        if self.governance_order_identity != expected_governance:
            raise ValueError("governance order identity mismatch")
        expected_active = typed_hash(
            {"schema_version": "phase6-active-metric-set-v1", "metrics": self.active_metric_set}
        )
        if self.active_metric_set_identity != expected_active:
            raise ValueError("active metric set identity mismatch")
        if typed_hash(self.model_dump(mode="python", exclude={"artifact_hash"})) != self.artifact_hash:
            raise ValueError("Phase 6 artifact hash mismatch")
        return self


def _hashed(model: type[BaseModel], values: dict[str, Any], field: str = "result_hash") -> Any:
    provisional = model.model_validate(
        {**values, field: "0" * 64}, context={"skip_hash": True}
    )
    values[field] = typed_hash(provisional.model_dump(mode="python", exclude={field}))
    return model(**values)


OVERLAY_POLICY = _hashed(OverlayPolicy, {}, field="policy_hash")
COHORT_POLICY = _hashed(CohortPolicy, {}, field="policy_hash")
NORMALIZATION_POLICY_IDENTITY = typed_hash(
    {
        "policy_version": TRANSFORMATION_VERSION,
        "clipping": "median-plus-minus-5-MAD",
        "zero_scale": "INACTIVE",
        "ranking": "MIDRANK",
        "transform": "RANK_GAUSSIAN",
        "score_bounds": (-3.0, 3.0),
        "peer_minimums": {"industry": 20, "sector": 30, "market": 100},
        "peer_fallback_order": ("industry", "sector", "market"),
    }
)
WEIGHT_POLICY_IDENTITY = typed_hash(
    {
        "policy_version": WEIGHT_POLICY_VERSION,
        "within_factor_weights": PRIMARY_WEIGHTS,
        "composite_weights": {"Quality": 1 / 3, "Value": 1 / 3, "Momentum": 1 / 3},
        "missingness": "ACTIVE_DENOMINATOR_NO_IMPUTATION",
    }
)


def _missing_class(observation: FactorObservation) -> MissingClass:
    if observation.status == "NOT_APPLICABLE":
        return MissingClass.NOT_APPLICABLE
    if observation.status == "PIT_VIOLATION":
        return MissingClass.PIT_UNAVAILABLE
    if observation.status in {"MISSING", "NOT_COMPUTED"}:
        if "history" in (observation.reason or "").lower():
            return MissingClass.INSUFFICIENT_HISTORY
        return MissingClass.PROVIDER_MISSING
    return MissingClass.INVALID_QUALITY


def _peer_key(
    observation: FactorObservation, eligible: list[FactorObservation]
) -> tuple[str | None, str | None, list[FactorObservation]]:
    if observation.factor == "Momentum":
        return ("MARKET", "MARKET", eligible) if len(eligible) >= 100 else (None, None, [])
    industry = [item for item in eligible if item.industry == observation.industry]
    if observation.industry and len(industry) >= 20:
        return "INDUSTRY", observation.industry, industry
    sector = [item for item in eligible if item.sector == observation.sector]
    if observation.sector and len(sector) >= 30:
        return "SECTOR", observation.sector, sector
    if len(eligible) >= 100:
        return "MARKET_FALLBACK", "MARKET", eligible
    return None, None, []


def _midranks(values: list[float]) -> list[float]:
    positions: dict[float, list[int]] = defaultdict(list)
    for index, value in enumerate(values):
        positions[value].append(index)
    ranks: dict[float, float] = {}
    cursor = 1
    for value in sorted(positions):
        count = len(positions[value])
        ranks[value] = (cursor + cursor + count - 1) / 2
        cursor += count
    return [ranks[value] for value in values]


def _normalize_metric(
    observations: list[FactorObservation], active: bool
) -> list[NormalizedMetricResult]:
    eligible = [
        item
        for item in observations
        if item.status == "PASS"
        and item.applicability == "APPLICABLE"
        and item.value is not None
        and math.isfinite(item.value)
        and item.confidence >= 0.80
    ]
    output: list[NormalizedMetricResult] = []
    cache: dict[tuple[str, str], dict[str, tuple[float, float, float, float, float]]] = {}
    for item in sorted(observations, key=lambda value: value.symbol.strip().upper()):
        base = {
            "symbol": item.symbol.strip().upper(), "factor": item.factor, "metric": item.metric,
            "raw_value": item.value, "source_observation_hash": factor_observation_hash(item),
        }
        if not active:
            output.append(_hashed(NormalizedMetricResult, base | {
                "directed_value": None, "clipped_value": None, "clip_lower": None,
                "clip_upper": None, "peer_type": None, "peer_id": None, "peer_size": 0,
                "rank": None, "percentile": None, "score": None, "status": "INACTIVE",
                "reason": "METRIC_ACTIVATION_FAILED", "missing_class": None,
                "active_metric": False,
            }))
            continue
        if item not in eligible:
            output.append(_hashed(NormalizedMetricResult, base | {
                "directed_value": None, "clipped_value": None, "clip_lower": None,
                "clip_upper": None, "peer_type": None, "peer_id": None, "peer_size": 0,
                "rank": None, "percentile": None, "score": None, "status": "INELIGIBLE",
                "reason": item.reason or str(item.status), "missing_class": _missing_class(item),
                "active_metric": True,
            }))
            continue
        peer_type, peer_id, peers = _peer_key(item, eligible)
        if not peers:
            output.append(_hashed(NormalizedMetricResult, base | {
                "directed_value": None, "clipped_value": None, "clip_lower": None,
                "clip_upper": None, "peer_type": None, "peer_id": None, "peer_size": 0,
                "rank": None, "percentile": None, "score": None, "status": "INELIGIBLE",
                "reason": "INSUFFICIENT_PEER_GROUP", "missing_class": None,
                "active_metric": True,
            }))
            continue
        key = (str(peer_type), str(peer_id))
        if key not in cache:
            semantics = METRIC_SEMANTICS_REGISTRY[(item.factor, item.metric)]
            sign = -1.0 if semantics.direction == "lower_is_better" else 1.0
            directed = [sign * float(peer.value) for peer in peers if peer.value is not None]
            center = median(directed)
            scale = 1.4826 * median([abs(value - center) for value in directed])
            if scale == 0:
                cache[key] = {}
            else:
                lower, upper = center - 5 * scale, center + 5 * scale
                clipped = [min(max(value, lower), upper) for value in directed]
                ranks = _midranks(clipped)
                cache[key] = {
                    peer.symbol.strip().upper(): (
                        directed[index], clipped[index], lower, upper, ranks[index]
                    ) for index, peer in enumerate(peers)
                }
        peer_values = cache[key]
        if not peer_values:
            output.append(_hashed(NormalizedMetricResult, base | {
                "directed_value": None, "clipped_value": None, "clip_lower": None,
                "clip_upper": None, "peer_type": peer_type, "peer_id": peer_id,
                "peer_size": len(peers), "rank": None, "percentile": None, "score": None,
                "status": "INACTIVE", "reason": "NO_CROSS_SECTIONAL_VARIATION",
                "missing_class": None, "active_metric": False,
            }))
            continue
        directed, clipped, lower, upper, rank = peer_values[item.symbol.strip().upper()]
        percentile = (rank - 0.5) / len(peers)
        score = max(-3.0, min(3.0, NormalDist().inv_cdf(percentile)))
        output.append(_hashed(NormalizedMetricResult, base | {
            "directed_value": directed, "clipped_value": clipped, "clip_lower": lower,
            "clip_upper": upper, "peer_type": peer_type, "peer_id": peer_id,
            "peer_size": len(peers), "rank": rank, "percentile": percentile, "score": score,
            "status": "SCORED", "reason": None, "missing_class": None,
            "active_metric": True,
        }))
    return output


def _factor_results(metrics: list[NormalizedMetricResult]) -> list[FactorScoreResult]:
    by_symbol = defaultdict(list)
    for item in metrics:
        by_symbol[(item.symbol, item.factor)].append(item)
    output = []
    for (symbol, factor), items in sorted(by_symbol.items()):
        weights = PRIMARY_WEIGHTS[factor]
        active = tuple(sorted(metric for metric in weights if any(
            item.metric == metric and item.active_metric for item in items
        )))
        available = tuple(sorted(item.metric for item in items if item.metric in weights and item.score is not None))
        active_denominator = sum(weights[name] for name in active)
        available_weight = sum(weights[name] for name in available)
        coverage = available_weight / active_denominator if active_denominator else 0.0
        anchors = True
        if factor == "Quality":
            anchors = bool({"roic", "fcf_margin"} & set(available)) and bool(
                {"cfo_conversion", "raw_accrual_ratio"} & set(available)
            )
            passes = coverage >= 0.70 and anchors
        elif factor == "Value":
            anchors = bool({"fcf_yield", "ebit_yield"} & set(available))
            passes = coverage >= 0.65 and anchors
        else:
            passes = set(available) == set(weights)
        score = None
        if passes and available_weight:
            score = sum(weights[item.metric] * float(item.score) for item in items if item.metric in available) / available_weight
            score = max(-3.0, min(3.0, score))
        output.append(_hashed(FactorScoreResult, {
            "symbol": symbol, "factor": factor, "score": score, "eligible": score is not None,
            "coverage": coverage, "active_denominator": active_denominator,
            "available_weight": available_weight, "active_metrics": active,
            "available_metrics": available,
            "reason": None if score is not None else "FACTOR_COVERAGE_GATE_FAILED",
        }))
    return output


def _overlay(
    symbol_metrics: list[NormalizedMetricResult], policy: OverlayPolicy = OVERLAY_POLICY
) -> tuple[str, tuple[str, ...]]:
    raw = {item.metric: item.raw_value for item in symbol_metrics if item.raw_value is not None}
    flags: list[str] = []
    outcome = "PASS"
    leverage = raw.get("net_debt_to_ebitda")
    if leverage is not None and leverage >= policy.leverage_block_threshold:
        return "BLOCK", (policy.leverage_block_flag,)
    if leverage is not None and leverage >= policy.leverage_review_threshold:
        flags.append(policy.leverage_review_flag)
    if raw.get("cfo_conversion", math.inf) < policy.cfo_conversion_review_threshold:
        flags.append(policy.cfo_review_flag)
    if raw.get("raw_accrual_ratio", -math.inf) > policy.accrual_review_threshold:
        flags.append(policy.accrual_review_flag)
    if flags:
        outcome = "REVIEW"
    return outcome, tuple(sorted(flags))


def _composites(
    factors: list[FactorScoreResult], metrics: list[NormalizedMetricResult]
) -> list[QVMCompositeResult]:
    factor_map = {(item.symbol, item.factor): item for item in factors}
    metric_map = defaultdict(list)
    for item in metrics:
        metric_map[item.symbol].append(item)
    output = []
    for symbol in sorted(metric_map):
        scores = {name: factor_map.get((symbol, name)) for name in PRIMARY_WEIGHTS}
        overlay, flags = _overlay(metric_map[symbol])
        complete = all(item is not None and item.score is not None for item in scores.values())
        composite = sum(float(item.score) for item in scores.values()) / 3 if complete else None
        primary_scores = [item.score for item in metric_map[symbol] if item.metric in PRIMARY_WEIGHTS[item.factor] and item.score is not None]
        sensitivity = sum(primary_scores) / len(primary_scores) if complete and primary_scores else None
        status = "BLOCKED" if overlay == "BLOCK" else "ELIGIBLE" if complete else "MODEL_INELIGIBLE"
        if status == "BLOCKED":
            composite = None
            sensitivity = None
        output.append(_hashed(QVMCompositeResult, {
            "symbol": symbol,
            "quality": scores["Quality"].score if scores["Quality"] else None,
            "value": scores["Value"].score if scores["Value"] else None,
            "momentum": scores["Momentum"].score if scores["Momentum"] else None,
            "composite": composite, "all_primary_equal_sensitivity": sensitivity,
            "model_status": status, "overlay": overlay, "overlay_flags": flags,
        }))
    return output


def _cohorts(
    composites: list[QVMCompositeResult], policy: CohortPolicy = COHORT_POLICY
) -> tuple[list[ResearchCohortResult], str, str | None]:
    eligible = [item for item in composites if item.model_status == "ELIGIBLE" and item.composite is not None]
    governed_count = len(composites)
    if len(eligible) < policy.quintile_minimum_eligible_count or (
        governed_count and len(eligible) / governed_count < policy.minimum_complete_fraction
    ):
        return [], "FAIL", "requires at least 50 and 60% complete composite scores"
    if len(eligible) >= policy.decile_minimum_eligible_count:
        mode = "DECILE"
        bucket_count = policy.decile_bucket_count
        top_fraction = policy.decile_top_fraction
        bottom_fraction = policy.decile_bottom_fraction
    else:
        mode = "QUINTILE"
        bucket_count = policy.quintile_bucket_count
        top_fraction = policy.quintile_top_fraction
        bottom_fraction = policy.quintile_bottom_fraction
    ordered = sorted(eligible, key=lambda item: (
        -float(item.composite), -float(item.quality), -float(item.value),
        -float(item.momentum), item.symbol,
    ))
    economic_values = [-float(item.composite) for item in ordered]
    ranks = _midranks(economic_values)
    output = []
    n = len(ordered)
    top_cutoff = float(ordered[math.ceil(n * top_fraction) - 1].composite)
    middle_high = float(ordered[math.floor(n * policy.middle_lower_fraction)].composite)
    middle_low = float(ordered[math.ceil(n * policy.middle_upper_fraction) - 1].composite)
    bottom_cutoff = float(ordered[math.floor(n * (1 - bottom_fraction))].composite)
    for position, (item, rank) in enumerate(zip(ordered, ranks, strict=True), start=1):
        percentile = (rank - 0.5) / n
        bucket = min(bucket_count, int((rank - 1) * bucket_count / n) + 1)
        composite = float(item.composite)
        cohort = (
            "TOP" if composite >= top_cutoff else
            "BOTTOM" if composite <= bottom_cutoff else
            "MIDDLE" if middle_low <= composite <= middle_high else None
        )
        if cohort == "TOP" and item.overlay == "REVIEW":
            cohort = None
        output.append(_hashed(ResearchCohortResult, {
            "symbol": item.symbol, "display_position": position, "economic_rank": rank,
            "percentile": percentile, "bucket": f"{mode}_{bucket}", "cohort": cohort,
            "overlay": item.overlay,
        }))
    return output, "PASS", None


def run_phase6_qvm_research(
    *, admission: PrePhase6Admission, batches: tuple[GovernedFactorBatch, ...]
) -> Phase6ResearchArtifact:
    if type(admission) is not PrePhase6Admission:
        raise TypeError("Phase 6 accepts only exact PrePhase6Admission artifacts")
    if any(type(item) is not GovernedFactorBatch for item in batches):
        raise TypeError("Phase 6 accepts only exact GovernedFactorBatch inputs")
    validated_admission = PrePhase6Admission.model_validate(admission.model_dump(mode="python"))
    fresh = admit_sealed_for_phase6(batches=batches)
    if fresh != validated_admission:
        raise ValueError("admission artifact is not bound to the supplied governed batches")
    validated_batches = tuple(GovernedFactorBatch.model_validate(item.model_dump(mode="python")) for item in batches)
    universe_count = len(validated_admission.expected_symbols)
    observations = [item for batch in validated_batches for item in batch.observations]
    primary_groups = {
        (factor, metric): [item for item in observations if item.factor == factor and item.metric == metric]
        for factor, weights in PRIMARY_WEIGHTS.items() for metric in weights
    }
    active = {
        key: len([item for item in values if item.status == "PASS" and item.value is not None and item.confidence >= 0.80 and item.applicability == "APPLICABLE"]) >= 30
        and len([item for item in values if item.status == "PASS" and item.value is not None and item.confidence >= 0.80 and item.applicability == "APPLICABLE"]) / universe_count >= 0.40
        for key, values in primary_groups.items()
    }
    metrics = [result for key, values in sorted(primary_groups.items()) for result in _normalize_metric(values, active[key])]
    factors = _factor_results(metrics)
    composites = _composites(factors, metrics)
    cohorts, cohort_status, cohort_reason = _cohorts(composites)
    first = validated_batches[0]
    governance_order_identity = typed_hash(
        {
            "schema_version": GOVERNANCE_ORDER_IDENTITY_VERSION,
            "version": first.governance_order_version,
            "order": first.governance_order,
        }
    )
    active_metric_set = tuple(
        sorted(f"{factor}.{metric}" for (factor, metric), state in active.items() if state)
    )
    values = {
        "admission_contract_version": validated_admission.contract_version,
        "admission_artifact_hash": validated_admission.admission_artifact_hash,
        "qvm_sealed_lineage_hash": validated_admission.qvm_sealed_lineage_hash,
        "factor_batch_hashes": dict(sorted(validated_admission.factor_batch_hashes.items())),
        "metric_registry_identity": validated_admission.metric_registry_identity,
        "peer_assignment_hash": first.peer_assignment_hash,
        "normalization_policy_identity": NORMALIZATION_POLICY_IDENTITY,
        "weight_policy_identity": WEIGHT_POLICY_IDENTITY,
        "overlay_policy": OVERLAY_POLICY,
        "cohort_policy": COHORT_POLICY,
        "governance_order_version": first.governance_order_version,
        "governance_order": first.governance_order,
        "governance_order_identity": governance_order_identity,
        "active_metric_set": active_metric_set,
        "active_metric_set_identity": typed_hash(
            {"schema_version": "phase6-active-metric-set-v1", "metrics": active_metric_set}
        ),
        "runtime": runtime_fingerprint(), "metrics": tuple(metrics), "factors": tuple(factors),
        "composites": tuple(composites), "cohorts": tuple(cohorts),
        "cohort_publication_status": cohort_status,
        "cohort_publication_reason": cohort_reason,
    }
    provisional = Phase6ResearchArtifact.model_construct(**values, artifact_hash="0" * 64)
    values["artifact_hash"] = typed_hash(
        provisional.model_dump(mode="python", exclude={"artifact_hash"})
    )
    return Phase6ResearchArtifact(**values)
