"""Cross-layer research governance boundaries."""

from governance.integration import (
    CROSS_LAYER_CONTRACT_VERSION,
    CrossLayerGovernanceError,
    CrossLayerGovernanceResult,
    integrate_governed_inputs,
    write_governed_inputs,
)
from governance.research_chain import (
    GovernedFactorBatch,
    evaluate_governed_momentum,
    evaluate_governed_quality,
    evaluate_governed_qvm,
    evaluate_governed_value,
    financial_metrics_from_governed_accounting,
    seal_factor_output,
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
