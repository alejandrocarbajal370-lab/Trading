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
    "integrate_governed_inputs",
    "write_governed_inputs",
]
