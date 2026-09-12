from __future__ import annotations

import datetime
from dataclasses import dataclass

from data.fx import FXDataset, FXGovernanceError
from data.market_data import MarketDataDataset, MarketDataGovernanceError
from factors.momentum import MomentumEvaluation
from factors.quality import QualityEvaluation
from factors.value import ValueEvaluation
from fundamentals.governance import AccountingDataset, AccountingGovernanceError
from governance.integration import CrossLayerGovernanceError, CrossLayerGovernanceResult
from governance.research_chain import (
    GovernedFactorBatch,
    evaluate_governed_momentum,
    evaluate_governed_quality,
    evaluate_governed_value,
)
from research.phase6_qvm import Phase6ResearchArtifact, run_phase6_qvm_research
from research.pre_phase6_readiness import PrePhase6Admission, admit_sealed_for_phase6


@dataclass(frozen=True)
class EquityQVMResearchResult:
    """End-to-end research output derived from one canonical PIT input cut."""

    quality: QualityEvaluation
    value: ValueEvaluation
    momentum: MomentumEvaluation
    batches: tuple[GovernedFactorBatch, ...]
    admission: PrePhase6Admission
    qvm: Phase6ResearchArtifact


def _verify_canonical_sources(cross_layer: CrossLayerGovernanceResult) -> None:
    manifest = cross_layer.manifest
    try:
        datasets = (
            (
                "market data",
                MarketDataDataset(cross_layer.market_data.frame, cross_layer.market_data.metadata),
                manifest.market_data_canonical_id,
                manifest.market_data_checksum,
            ),
            (
                "FX",
                FXDataset(cross_layer.fx_data.frame, cross_layer.fx_data.metadata),
                manifest.fx_canonical_id,
                manifest.fx_checksum,
            ),
            (
                "accounting",
                AccountingDataset(
                    cross_layer.accounting_data.frame, cross_layer.accounting_data.metadata
                ),
                manifest.accounting_canonical_id,
                manifest.accounting_checksum,
            ),
        )
    except (MarketDataGovernanceError, FXGovernanceError, AccountingGovernanceError) as error:
        raise CrossLayerGovernanceError(f"canonical source verification failed: {error}") from error
    cutoff = manifest.as_of.astimezone(datetime.UTC)
    for name, dataset, expected_id, expected_checksum in datasets:
        if dataset.metadata.available_at.astimezone(datetime.UTC) > cutoff:
            raise CrossLayerGovernanceError(f"PIT violation: {name} availability exceeds as_of")
        if (
            dataset.metadata.canonical_id != expected_id
            or dataset.metadata.checksum != expected_checksum
        ):
            raise CrossLayerGovernanceError(f"{name} canonical identity mismatch")


def run_equity_qvm_research(
    *,
    cross_layer: CrossLayerGovernanceResult,
    experiment_id: str,
    benchmark_symbol: str,
) -> EquityQVMResearchResult:
    """Compute Q/V/M and Phase 6 scores from a verified historical artifact.

    ``cross_layer`` is the existing canonical dataset boundary. Its universe, market,
    accounting, FX, availability and checksum identities are revalidated by the factor
    sealers and Phase 6 admission before any score is returned.
    """
    _verify_canonical_sources(cross_layer)
    quality, quality_batch = evaluate_governed_quality(
        cross_layer=cross_layer, experiment_id=f"{experiment_id}-quality"
    )
    value, value_batch = evaluate_governed_value(
        cross_layer=cross_layer, experiment_id=f"{experiment_id}-value"
    )
    momentum, momentum_batch = evaluate_governed_momentum(
        cross_layer=cross_layer,
        experiment_id=f"{experiment_id}-momentum",
        benchmark_symbol=benchmark_symbol,
    )
    batches = (quality_batch, value_batch, momentum_batch)
    admission = admit_sealed_for_phase6(batches=batches)
    qvm = run_phase6_qvm_research(admission=admission, batches=batches)
    return EquityQVMResearchResult(
        quality=quality,
        value=value,
        momentum=momentum,
        batches=batches,
        admission=admission,
        qvm=qvm,
    )
