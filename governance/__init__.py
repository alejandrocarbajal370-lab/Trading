"""Cross-layer research governance boundaries."""

from governance.integration import (
    CROSS_LAYER_CONTRACT_VERSION,
    CrossLayerGovernanceError,
    CrossLayerGovernanceResult,
    integrate_governed_inputs,
    write_governed_inputs,
)

__all__ = [
    "CROSS_LAYER_CONTRACT_VERSION",
    "CrossLayerGovernanceError",
    "CrossLayerGovernanceResult",
    "GovernedFactorBatch",
    "evaluate_governed_momentum",
    "evaluate_governed_quality",
    "evaluate_governed_qvm",
    "evaluate_governed_value",
    "financial_metrics_from_governed_accounting",
    "integrate_governed_inputs",
    "seal_factor_output",
    "write_governed_inputs",
]


def __getattr__(name: str):
    """Load factor-chain exports lazily to keep canonical contracts acyclic."""
    if name in {
        "GovernedFactorBatch",
        "evaluate_governed_momentum",
        "evaluate_governed_quality",
        "evaluate_governed_qvm",
        "evaluate_governed_value",
        "financial_metrics_from_governed_accounting",
        "seal_factor_output",
    }:
        from governance import research_chain

        return getattr(research_chain, name)
    raise AttributeError(name)
