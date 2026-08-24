from __future__ import annotations

import datetime
import json
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from factors.momentum import MomentumEvaluation, evaluate_momentum_metrics
from factors.quality import QualityEvaluation, evaluate_quality_metrics
from factors.qvm import (
    FactorBatch,
    FactorObservation,
    QVMEvaluation,
    evaluate_qvm_research,
    factor_dataset_hash,
    observation_from_row,
    qvm_lineage_hash,
)
from factors.value import ValueEvaluation, evaluate_value_metrics
from fundamentals.financial_engine import INSTANT_INPUTS, calculate_financial_metrics
from governance.canonical import RuntimeFingerprint, runtime_fingerprint, typed_hash
from governance.integration import (
    VALUE_TEMPORAL_SELECTION_POLICY_VERSION,
    CrossLayerGovernanceError,
    CrossLayerGovernanceResult,
    CrossLayerManifest,
    _frame_hash,
    eligible_symbols_hash,
)
from governance.pre_phase6 import (
    CLASSIFICATION_CONTRACT_VERSION,
    CONFIDENCE_POLICY_VERSION,
    ClassificationRecord,
    ConfidenceVector,
    conservative_confidence,
    governed_status,
    peer_assignment_hash,
)


class ResearchChainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GovernedFactorBatch(ResearchChainModel):
    identity_schema_version: Literal["governed-factor-batch-identity-v2"] = (
        "governed-factor-batch-identity-v2"
    )
    factor: Literal["Quality", "Value", "Momentum"]
    as_of: datetime.datetime
    cross_layer_contract_version: str
    cross_layer_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    universe_snapshot_id: str
    universe_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    membership_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_symbols_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability_policy_version: str
    entity_policy_version: str
    base_currency: str
    unit_ontology_version: str
    calendar_alignment_policy_version: str
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    accounting_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_canonical_id: str
    fx_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_conversions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_data_canonical_id: str
    market_data_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_data_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification_contract_version: Literal["pit-classification-v1"] = (
        CLASSIFICATION_CONTRACT_VERSION
    )
    classification_taxonomy: str
    classification_taxonomy_version: str
    peer_assignment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification_records: tuple[ClassificationRecord, ...]
    factor_dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations: tuple[FactorObservation, ...]
    runtime: RuntimeFingerprint
    batch_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    governance_order: tuple[str, ...] = (
        "confidence",
        "applicability_activation",
        "peer_fallback",
        "coverage",
    )
    phase6_eligible: Literal[True] = True
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    scores_calculated: Literal[False] = False
    ranking_calculated: Literal[False] = False
    portfolio_constructed: Literal[False] = False
    backtesting_performed: Literal[False] = False
    signals_generated: Literal[False] = False
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_time(self) -> GovernedFactorBatch:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("factor as_of must be timezone-aware")
        if any(item.as_of != self.as_of.date() for item in self.observations):
            raise ValueError("factor observation as_of mismatch")
        if factor_dataset_hash(self.observations) != self.factor_dataset_hash:
            raise ValueError("factor dataset hash mismatch")
        expected_peer_hash = peer_assignment_hash(
            list(self.classification_records),
            as_of=self.as_of,
            universe_snapshot_hash=self.universe_snapshot_hash,
        )
        if expected_peer_hash != self.peer_assignment_hash:
            raise ValueError("peer assignment hash mismatch")
        if {item.symbol for item in self.classification_records} != {
            item.symbol for item in self.observations
        }:
            raise ValueError("classification symbols do not match observations")
        for item in self.observations:
            governed_status(item.status)
        if governed_factor_batch_identity(self) != self.batch_identity_hash:
            raise ValueError("governed factor batch identity mismatch")
        return self


def governed_factor_batch_identity(batch: GovernedFactorBatch | dict[str, Any]) -> str:
    values = batch if isinstance(batch, dict) else batch.model_dump(mode="python")
    fields = (
        "factor",
        "as_of",
        "cross_layer_contract_version",
        "cross_layer_fingerprint",
        "universe_snapshot_id",
        "universe_snapshot_hash",
        "membership_hash",
        "validation_hash",
        "eligible_symbols_hash",
        "availability_policy_version",
        "entity_policy_version",
        "base_currency",
        "unit_ontology_version",
        "calendar_alignment_policy_version",
        "accounting_canonical_id",
        "accounting_checksum",
        "accounting_snapshot_sha256",
        "fx_canonical_id",
        "fx_checksum",
        "fx_conversions_sha256",
        "market_data_canonical_id",
        "market_data_checksum",
        "market_data_snapshot_sha256",
        "classification_contract_version",
        "classification_taxonomy",
        "classification_taxonomy_version",
        "peer_assignment_hash",
        "factor_dataset_hash",
        "runtime",
    )
    identity = {
        "schema_version": "governed-factor-batch-identity-v2",
        **{key: values[key] for key in fields if key in values},
    }
    return typed_hash(identity)


def _eligible_symbols(result: CrossLayerGovernanceResult) -> set[str]:
    return set(
        result.universe_membership.loc[
            result.universe_membership["eligibility_status"] == "ELIGIBLE", "symbol"
        ]
        .astype(str)
        .str.strip()
        .str.upper()
    )


def _verify_result(result: CrossLayerGovernanceResult) -> set[str]:
    manifest = CrossLayerManifest.model_validate(result.manifest.model_dump())
    symbols = _eligible_symbols(result)
    if eligible_symbols_hash(symbols) != manifest.eligible_symbols_hash:
        raise CrossLayerGovernanceError("eligible symbols hash mismatch")
    if len(symbols) != manifest.eligible_symbols_count:
        raise CrossLayerGovernanceError("eligible symbols count mismatch")
    observed_hashes = {
        "market data snapshot": _frame_hash(result.market_snapshot, ["symbol", "date"]),
        "accounting snapshot": _frame_hash(
            result.accounting_snapshot, ["entity", "metric", "period_end", "revision"]
        ),
        "FX conversions": _frame_hash(result.fx_conversions, ["entity", "metric", "period_end"]),
    }
    expected_hashes = {
        "market data snapshot": manifest.market_data_snapshot_sha256,
        "accounting snapshot": manifest.accounting_snapshot_sha256,
        "FX conversions": manifest.fx_conversions_sha256,
    }
    for name, observed in observed_hashes.items():
        if observed != expected_hashes[name]:
            raise CrossLayerGovernanceError(f"{name} hash mismatch after governance")
    return symbols


def seal_factor_output(
    *,
    factor: Literal["Quality", "Value", "Momentum"],
    metrics: pd.DataFrame,
    cross_layer: CrossLayerGovernanceResult,
) -> GovernedFactorBatch:
    """Seal real factor output to the verified Phase 5.6 chain.

    The legacy factor engines remain research-only. A batch is Phase-6-eligible only after this
    function validates its complete eligible population and upstream identities.
    """
    symbols = _verify_result(cross_layer)
    observed = set(metrics["symbol"].astype(str).str.strip().str.upper())
    if observed != symbols:
        raise CrossLayerGovernanceError(
            f"{factor} symbols do not exactly match governed eligible universe"
        )
    manifest = cross_layer.manifest
    if "as_of" not in metrics:
        raise CrossLayerGovernanceError(f"{factor} output is missing as_of")
    if factor == "Value":
        if "currency" not in metrics or metrics["currency"].isna().any():
            raise CrossLayerGovernanceError("Value output requires explicit currency")
        if set(metrics["currency"].astype(str).str.upper()) != {manifest.base_currency}:
            raise CrossLayerGovernanceError("Value currency is not governed base_currency")
    classifications = [
        ClassificationRecord(
            symbol=str(row.symbol),
            sector=str(row.sector),
            industry=str(row.industry),
            source=str(row.source),
            taxonomy="provider-supplied-sector-industry",
            taxonomy_version=manifest.universe_ruleset_version,
            available_at=pd.Timestamp(row.available_at).to_pydatetime(),
        )
        for row in cross_layer.universe_membership.itertuples(index=False)
        if str(row.eligibility_status) == "ELIGIBLE"
    ]
    classification_by_symbol = {item.symbol.strip().upper(): item for item in classifications}
    enriched = metrics.copy(deep=True)
    enriched["sector"] = (
        enriched["symbol"]
        .astype(str)
        .str.upper()
        .map(lambda symbol: classification_by_symbol[symbol].sector)
    )
    enriched["industry"] = (
        enriched["symbol"]
        .astype(str)
        .str.upper()
        .map(lambda symbol: classification_by_symbol[symbol].industry)
    )
    observations = tuple(
        observation_from_row(
            row,
            factor=factor,
            universe_snapshot_id=manifest.universe_snapshot_id,
            as_of=manifest.as_of.date(),
        )
        for _, row in enriched.iterrows()
    )
    values: dict[str, Any] = {
        "factor": factor,
        "as_of": manifest.as_of,
        "cross_layer_contract_version": manifest.contract_version,
        "cross_layer_fingerprint": manifest.cross_layer_fingerprint,
        "universe_snapshot_id": manifest.universe_snapshot_id,
        "universe_snapshot_hash": manifest.universe_snapshot_hash,
        "membership_hash": manifest.membership_hash,
        "validation_hash": manifest.validation_hash,
        "eligible_symbols_hash": manifest.eligible_symbols_hash,
        "availability_policy_version": manifest.availability_policy_version,
        "entity_policy_version": manifest.entity_policy_version,
        "base_currency": manifest.base_currency,
        "unit_ontology_version": manifest.unit_ontology_version,
        "calendar_alignment_policy_version": manifest.calendar_alignment_policy_version,
        "accounting_canonical_id": manifest.accounting_canonical_id,
        "accounting_checksum": manifest.accounting_checksum,
        "accounting_snapshot_sha256": manifest.accounting_snapshot_sha256,
        "fx_canonical_id": manifest.fx_canonical_id,
        "fx_checksum": manifest.fx_checksum,
        "fx_conversions_sha256": manifest.fx_conversions_sha256,
        "market_data_canonical_id": manifest.market_data_canonical_id,
        "market_data_checksum": manifest.market_data_checksum,
        "market_data_snapshot_sha256": manifest.market_data_snapshot_sha256,
        "classification_contract_version": CLASSIFICATION_CONTRACT_VERSION,
        "classification_taxonomy": "provider-supplied-sector-industry",
        "classification_taxonomy_version": manifest.universe_ruleset_version,
        "peer_assignment_hash": peer_assignment_hash(
            classifications,
            as_of=manifest.as_of,
            universe_snapshot_hash=manifest.universe_snapshot_hash,
        ),
        "classification_records": tuple(classifications),
        "factor_dataset_hash": factor_dataset_hash(observations),
        "observations": observations,
        "runtime": runtime_fingerprint(),
    }
    values["batch_identity_hash"] = governed_factor_batch_identity(values)
    return GovernedFactorBatch(**values)


def financial_metrics_from_governed_accounting(
    cross_layer: CrossLayerGovernanceResult,
) -> pd.DataFrame:
    """Run the existing Financial Engine only from the verified accounting PIT snapshot."""
    _verify_result(cross_layer)
    facts = cross_layer.accounting_snapshot.copy(deep=True)
    facts["symbol"] = facts["entity"]
    facts["fiscal_period_end"] = pd.to_datetime(facts["period_end"]).dt.date
    facts["fiscal_period_start"] = pd.to_datetime(
        facts["fiscal_period_start"], errors="coerce"
    ).dt.date
    facts["period_type"] = facts["period_type"].astype(str).str.lower()
    expected_types = facts["metric"].map(
        lambda metric: "instant" if metric in INSTANT_INPUTS else "duration"
    )
    if (facts["period_type"] != expected_types).any():
        raise CrossLayerGovernanceError("accounting period_type conflicts with metric semantics")
    duration = facts["period_type"] == "duration"
    if facts.loc[duration, "fiscal_period_start"].isna().any():
        raise CrossLayerGovernanceError("duration accounting fact lacks fiscal_period_start")
    if facts.loc[~duration, "fiscal_period_start"].notna().any():
        raise CrossLayerGovernanceError("instant accounting fact has fiscal_period_start")
    required_confidence = {"data_confidence", "calculation_confidence", "economic_confidence"}
    missing_confidence = sorted(required_confidence - set(facts.columns))
    if missing_confidence:
        raise CrossLayerGovernanceError(
            "governed accounting confidence is required; missing: " + ", ".join(missing_confidence)
        )
    vectors: list[ConfidenceVector] = []
    for row in facts.itertuples(index=False):
        try:
            vectors.append(
                ConfidenceVector(
                    data_confidence=row.data_confidence,
                    calculation_confidence=row.calculation_confidence,
                    economic_confidence=row.economic_confidence,
                )
            )
        except ValueError as error:
            raise CrossLayerGovernanceError(
                f"invalid governed accounting confidence: {error}"
            ) from error
    facts["confidence"] = [item.governed_confidence for item in vectors]
    engine_columns = [
        "symbol",
        "fiscal_period_start",
        "fiscal_period_end",
        "period_type",
        "available_at",
        "metric",
        "value",
        "unit",
        "source",
        "confidence",
    ]
    metrics = calculate_financial_metrics(facts.loc[:, engine_columns])
    def derived_available_at(raw: str) -> pd.Timestamp | None:
        timestamps = [
            pd.Timestamp(item["available_at"])
            for item in json.loads(raw)
            if item.get("available_at") is not None
        ]
        return max(timestamps) if timestamps else None

    metrics["available_at"] = metrics["input_lineage"].map(derived_available_at)
    provenance = {
        "accounting_contract_version": cross_layer.manifest.accounting_contract_version,
        "accounting_canonical_id": cross_layer.manifest.accounting_canonical_id,
        "accounting_checksum": cross_layer.manifest.accounting_checksum,
        "accounting_snapshot_sha256": cross_layer.manifest.accounting_snapshot_sha256,
        "accounting_cutoff": cross_layer.manifest.as_of.isoformat(),
        "confidence_policy_version": CONFIDENCE_POLICY_VERSION,
        "cross_layer_fingerprint": cross_layer.manifest.cross_layer_fingerprint,
    }
    for index, raw in metrics["input_lineage"].items():
        lineage = json.loads(raw)
        metrics.at[index, "input_lineage"] = json.dumps(
            [*lineage, {"source": "phase5.6_cross_layer", **provenance}], sort_keys=True
        )
    return metrics


def _value_inputs(cross_layer: CrossLayerGovernanceResult, financial: pd.DataFrame) -> pd.DataFrame:
    facts = cross_layer.accounting_snapshot
    rows: list[dict[str, Any]] = []
    for symbol in sorted(_eligible_symbols(cross_layer)):
        symbol_facts = facts.loc[facts["entity"] == symbol].copy()
        valuation_date = cross_layer.manifest.as_of.date()
        symbol_facts["period_end"] = pd.to_datetime(symbol_facts["period_end"]).dt.date
        symbol_facts["fiscal_period_start"] = pd.to_datetime(
            symbol_facts["fiscal_period_start"], errors="coerce"
        ).dt.date
        membership = cross_layer.universe_membership.loc[
            cross_layer.universe_membership["symbol"] == symbol
        ].iloc[0]
        required_flows = {"net_income", "operating_income", "ebitda"}
        required_stocks = {"total_debt", "cash"}
        required_facts = required_flows | required_stocks
        if not required_facts <= set(symbol_facts["metric"]):
            raise CrossLayerGovernanceError(
                f"Value governed adapter missing accounting facts for {symbol}: "
                f"{', '.join(sorted(required_facts - set(symbol_facts['metric'])))}"
            )
        flows = symbol_facts.loc[
            symbol_facts["metric"].isin(required_flows)
            & (symbol_facts["period_type"] == "duration")
            & symbol_facts["fiscal_period"].astype(str).str.upper().str.startswith("FY")
            & (symbol_facts["period_end"] <= valuation_date)
        ]
        duplicate_keys = ["metric", "fiscal_period_start", "period_end", "period_type"]
        if flows.duplicated(duplicate_keys, keep=False).any():
            raise CrossLayerGovernanceError(f"ambiguous Value flow facts for {symbol}")
        complete_periods: list[tuple[datetime.date, datetime.date]] = []
        for key, group in flows.groupby(["fiscal_period_start", "period_end"], dropna=False):
            if set(group["metric"]) == required_flows and len(group) == len(required_flows):
                complete_periods.append(key)
        if not complete_periods:
            raise CrossLayerGovernanceError(f"no compatible Value flow period for {symbol}")
        selected_start, selected_end = max(complete_periods, key=lambda item: item[1])
        selected_flows = flows.loc[
            (flows["fiscal_period_start"] == selected_start) & (flows["period_end"] == selected_end)
        ]
        fact_map = selected_flows.set_index("metric")
        stocks = symbol_facts.loc[
            symbol_facts["metric"].isin(required_stocks)
            & (symbol_facts["period_type"] == "instant")
            & (symbol_facts["period_end"] == selected_end)
        ]
        if len(stocks) != len(required_stocks) or set(stocks["metric"]) != required_stocks:
            raise CrossLayerGovernanceError(f"stock and flow periods are incompatible for {symbol}")
        if stocks.duplicated("metric", keep=False).any():
            raise CrossLayerGovernanceError(f"ambiguous Value stock facts for {symbol}")
        stock_map = stocks.set_index("metric")
        selected_metrics = financial.loc[
            (financial["symbol"] == symbol)
            & (financial["fiscal_period_start"] == selected_start)
            & (financial["fiscal_period_end"] == selected_end)
            & (financial["metric"] == "free_cash_flow")
            & (financial["status"] == "PASS")
        ]
        if len(selected_metrics) != 1:
            raise CrossLayerGovernanceError(
                f"Value governed adapter requires one compatible free_cash_flow for {symbol}"
            )
        fcf = selected_metrics.iloc[0]
        market_cap = float(membership["market_cap"])
        enterprise_value = (
            market_cap
            + float(stock_map.loc["total_debt", "value"])
            - float(stock_map.loc["cash", "value"])
        )
        values = {
            "free_cash_flow": float(fcf["value"]),
            "earnings": float(fact_map.loc["net_income", "value"]),
            "ebit": float(fact_map.loc["operating_income", "value"]),
            "ebitda": float(fact_map.loc["ebitda", "value"]),
            "market_cap": market_cap,
            "enterprise_value": enterprise_value,
        }
        confidence_sources = {
            "free_cash_flow": [fcf],
            "earnings": [fact_map.loc["net_income"]],
            "ebit": [fact_map.loc["operating_income"]],
            "ebitda": [fact_map.loc["ebitda"]],
            "market_cap": [],
            "enterprise_value": [stock_map.loc["total_debt"], stock_map.loc["cash"]],
        }
        for metric, value in values.items():
            instant = metric in {"market_cap", "enterprise_value"}
            sources = confidence_sources[metric]
            if metric in {"market_cap", "enterprise_value"}:
                universe_confidence = membership.get("universe_confidence")
                if universe_confidence is None or pd.isna(universe_confidence):
                    raise CrossLayerGovernanceError(
                        f"Value {metric} requires governed universe_confidence for {symbol}"
                    )
                sources = [
                    *sources,
                    {"confidence": universe_confidence, "available_at": membership["available_at"]},
                ]
            vectors = [
                ConfidenceVector(
                    data_confidence=float(source.get("data_confidence", source.get("confidence"))),
                    calculation_confidence=float(
                        source.get("calculation_confidence", source.get("confidence"))
                    ),
                    economic_confidence=float(
                        source.get("economic_confidence", source.get("confidence"))
                    ),
                )
                for source in sources
            ]
            aggregate = conservative_confidence(vectors)
            available_at = max(
                pd.Timestamp(
                    source.get("available_at", source.get("source_available_at"))
                ).to_pydatetime()
                for source in sources
            )
            rows.append(
                {
                    "symbol": symbol,
                    "valuation_as_of": cross_layer.manifest.as_of.date(),
                    "fiscal_period_end": selected_end,
                    "period_basis": "INSTANT" if instant else "FY",
                    "metric": metric,
                    "value": value,
                    "unit": "currency",
                    "currency": cross_layer.manifest.base_currency,
                    "available_at": available_at,
                    "status": "PASS",
                    "reason": None,
                    "confidence": aggregate.governed_confidence,
                    "data_confidence": aggregate.data_confidence,
                    "calculation_confidence": aggregate.calculation_confidence,
                    "economic_confidence": aggregate.economic_confidence,
                    "input_lineage": json.dumps(
                        [
                            {
                                "source": "phase5.6_cross_layer",
                                "cross_layer_fingerprint": cross_layer.manifest.cross_layer_fingerprint,
                                "accounting_canonical_id": cross_layer.manifest.accounting_canonical_id,
                                "fx_canonical_id": cross_layer.manifest.fx_canonical_id,
                                "market_data_canonical_id": cross_layer.manifest.market_data_canonical_id,
                                "value_temporal_selection_policy_version": VALUE_TEMPORAL_SELECTION_POLICY_VERSION,
                                "selected_fiscal_period_start": str(selected_start),
                                "selected_fiscal_period_end": str(selected_end),
                            }
                        ],
                        sort_keys=True,
                    ),
                    "industry": membership.get("industry"),
                }
            )
    return pd.DataFrame(rows)


def evaluate_governed_quality(
    *, cross_layer: CrossLayerGovernanceResult, experiment_id: str
) -> tuple[QualityEvaluation, GovernedFactorBatch]:
    financial = financial_metrics_from_governed_accounting(cross_layer)
    evaluation = evaluate_quality_metrics(
        financial,
        experiment_id=experiment_id,
        dataset_lineage={
            "cross_layer_fingerprint": cross_layer.manifest.cross_layer_fingerprint,
            "accounting_canonical_id": cross_layer.manifest.accounting_canonical_id,
        },
    )
    return evaluation, seal_factor_output(
        factor="Quality", metrics=evaluation.metrics, cross_layer=cross_layer
    )


def evaluate_governed_value(
    *, cross_layer: CrossLayerGovernanceResult, experiment_id: str
) -> tuple[ValueEvaluation, GovernedFactorBatch]:
    financial = financial_metrics_from_governed_accounting(cross_layer)
    inputs = _value_inputs(cross_layer, financial)
    evaluation = evaluate_value_metrics(
        inputs,
        experiment_id=experiment_id,
        dataset_lineage={
            "cross_layer_fingerprint": cross_layer.manifest.cross_layer_fingerprint,
            "accounting_canonical_id": cross_layer.manifest.accounting_canonical_id,
            "fx_canonical_id": cross_layer.manifest.fx_canonical_id,
        },
    )
    return evaluation, seal_factor_output(
        factor="Value", metrics=evaluation.metrics, cross_layer=cross_layer
    )


def evaluate_governed_momentum(
    *, cross_layer: CrossLayerGovernanceResult, experiment_id: str, benchmark_symbol: str
) -> tuple[MomentumEvaluation, GovernedFactorBatch]:
    if (
        cross_layer.market_data.metadata.canonical_id
        != cross_layer.manifest.market_data_canonical_id
    ):
        raise CrossLayerGovernanceError("Market Data canonical mismatch")
    prices = cross_layer.market_data.momentum_frame()
    evaluation = evaluate_momentum_metrics(
        prices,
        experiment_id=experiment_id,
        dataset_lineage={
            "cross_layer_fingerprint": cross_layer.manifest.cross_layer_fingerprint,
            "market_data_canonical_id": cross_layer.manifest.market_data_canonical_id,
            "market_data_checksum": cross_layer.manifest.market_data_checksum,
        },
        as_of=cross_layer.manifest.as_of.date(),
        benchmark_symbol=benchmark_symbol,
    )
    return evaluation, seal_factor_output(
        factor="Momentum", metrics=evaluation.metrics, cross_layer=cross_layer
    )


def evaluate_governed_qvm(
    *, batches: tuple[GovernedFactorBatch, ...], expected: CrossLayerGovernanceResult
) -> QVMEvaluation:
    symbols = _verify_result(expected)
    if {batch.factor for batch in batches} != {"Quality", "Value", "Momentum"} or len(batches) != 3:
        raise CrossLayerGovernanceError(
            "exactly one Quality, Value, and Momentum batch is required"
        )
    manifest = expected.manifest
    identity_fields = {
        "cross_layer_contract_version": manifest.contract_version,
        "cross_layer_fingerprint": manifest.cross_layer_fingerprint,
        "universe_snapshot_id": manifest.universe_snapshot_id,
        "universe_snapshot_hash": manifest.universe_snapshot_hash,
        "membership_hash": manifest.membership_hash,
        "validation_hash": manifest.validation_hash,
        "eligible_symbols_hash": manifest.eligible_symbols_hash,
        "as_of": manifest.as_of,
        "availability_policy_version": manifest.availability_policy_version,
        "entity_policy_version": manifest.entity_policy_version,
        "base_currency": manifest.base_currency,
        "unit_ontology_version": manifest.unit_ontology_version,
        "calendar_alignment_policy_version": manifest.calendar_alignment_policy_version,
        "accounting_canonical_id": manifest.accounting_canonical_id,
        "accounting_checksum": manifest.accounting_checksum,
        "accounting_snapshot_sha256": manifest.accounting_snapshot_sha256,
        "fx_canonical_id": manifest.fx_canonical_id,
        "fx_checksum": manifest.fx_checksum,
        "fx_conversions_sha256": manifest.fx_conversions_sha256,
        "market_data_canonical_id": manifest.market_data_canonical_id,
        "market_data_checksum": manifest.market_data_checksum,
        "market_data_snapshot_sha256": manifest.market_data_snapshot_sha256,
    }
    for batch in batches:
        for name, expected_value in identity_fields.items():
            if getattr(batch, name) != expected_value:
                raise CrossLayerGovernanceError(f"{batch.factor} {name} mismatch")
        if {item.symbol for item in batch.observations} != symbols:
            raise CrossLayerGovernanceError(f"{batch.factor} eligible universe mismatch")
    if len({batch.peer_assignment_hash for batch in batches}) != 1:
        raise CrossLayerGovernanceError("factor batch peer assignment mismatch")
    hashes = {batch.factor: batch.factor_dataset_hash for batch in batches}
    lineage_hash = qvm_lineage_hash(
        universe_snapshot_id=manifest.universe_snapshot_id,
        universe_snapshot_hash=manifest.universe_snapshot_hash,
        factor_dataset_hashes=hashes,
        as_of=manifest.as_of.date(),
        availability_policy=manifest.availability_policy_version,
        entity_policy=manifest.entity_policy_version,
    )
    legacy = tuple(
        FactorBatch(
            factor=batch.factor,
            universe_snapshot_id=batch.universe_snapshot_id,
            as_of=batch.as_of.date(),
            availability_policy=batch.availability_policy_version,
            entity_policy=batch.entity_policy_version,
            universe_snapshot_hash=batch.universe_snapshot_hash,
            factor_dataset_hash=batch.factor_dataset_hash,
            lineage_hash=lineage_hash,
            observations=batch.observations,
        )
        for batch in batches
    )
    evaluation = evaluate_qvm_research(legacy)
    health = dict(evaluation.health)
    health.update(
        governance_mode="phase5.6_cross_layer_verified",
        phase6_eligible=True,
        cross_layer_fingerprint=manifest.cross_layer_fingerprint,
        eligible_symbols_hash=manifest.eligible_symbols_hash,
    )
    return QVMEvaluation(
        evaluation.matrix, health, evaluation.lineage, evaluation.validation_report
    )
