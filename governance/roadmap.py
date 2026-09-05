"""Machine-readable authorization boundary for the next non-REAL foundation."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from governance.phase7e import EvidenceGate, GateState


class ImplementationAuthorization(StrEnum):
    AUTHORIZED_TO_IMPLEMENT = "AUTHORIZED_TO_IMPLEMENT"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class FutureCapabilityStatus(StrEnum):
    FUTURE_AUTHORIZED = "FUTURE_AUTHORIZED"


class RoadmapBlock(StrEnum):
    EXTERNAL_PROVIDER_ADAPTER_DURABLE_VERIFICATION_INTERFACE_FOUNDATION = (
        "External Provider Adapter & Durable Verification Interface Foundation"
    )
    DURABLE_REPLAY_PERSISTENCE_CUSTODY_BOUNDARY_FOUNDATION = (
        "Durable Replay Persistence & Custody Boundary Foundation"
    )
    EXTERNAL_CUSTODY_RETENTION_VERIFICATION_BOUNDARY_FOUNDATION = (
        "External Custody & Retention Verification Boundary Foundation"
    )
    TRUST_ANCHOR_AUTHORITY_PROVISIONING_CONTRACT_FOUNDATION = (
        "Trust-Anchor & Authority Provisioning Contract Foundation"
    )
    EXTERNAL_TRUST_ANCHOR_EVIDENCE_VERIFICATION_ADMISSION_FOUNDATION = (
        "External Trust-Anchor Evidence Verification & Admission Foundation"
    )
    IBKR_READ_ONLY_MARKET_OBSERVATION_ADAPTER_FOUNDATION = (
        "IBKR Read-Only Market Observation Adapter Foundation"
    )
    IBKR_PROVISIONED_READ_ONLY_OBSERVATION_EVIDENCE_FOUNDATION = (
        "IBKR Provisioned Read-Only Observation Evidence Foundation"
    )
    IBKR_REPRODUCIBLE_READ_ONLY_LOCAL_OBSERVATION_PROBE = (
        "IBKR Reproducible Read-Only Local Observation Probe (Unauthenticated)"
    )
    IBKR_OBSERVATION_EXTERNAL_AUTHENTICITY_FOUNDATION = (
        "IBKR Observation External Authenticity Foundation"
    )
    TAX_LOT_TAX_AWARE_PORTFOLIO_GOVERNANCE = (
        "Tax Lot & Tax-Aware Portfolio Governance"
    )


class TaxLotContractField(StrEnum):
    TAX_LOT_ID = "tax_lot_id"
    SECURITY_ID = "security_id"
    ACQUIRED_AT = "acquired_at"
    QUANTITY = "quantity"
    COST_BASIS_ASSET_CCY = "cost_basis_asset_ccy"
    COST_BASIS_REPORTING_CCY = "cost_basis_reporting_ccy"
    FX_RATE_AT_ACQUISITION = "fx_rate_at_acquisition"
    FX_LINEAGE_HASH = "fx_lineage_hash"
    REALIZED_PROCEEDS_ASSET_CCY = "realized_proceeds_asset_ccy"
    REALIZED_PROCEEDS_REPORTING_CCY = "realized_proceeds_reporting_ccy"
    FX_RATE_AT_DISPOSAL = "fx_rate_at_disposal"
    REALIZED_GAIN_LOSS_REPORTING_CCY = "realized_gain_loss_reporting_ccy"
    DIVIDEND_INCOME = "dividend_income"
    FOREIGN_WITHHOLDING = "foreign_withholding"
    HOLDING_PERIOD_DAYS = "holding_period_days"
    TAX_POLICY_VERSION = "tax_policy_version"
    JURISDICTION = "jurisdiction"
    EVIDENCE_HASH = "evidence_hash"


class TaxAwareDependency(StrEnum):
    REAL_PROVIDER_DATA_OBSERVED_VERIFIED_ADMITTED = (
        "REAL_PROVIDER_DATA_OBSERVED_VERIFIED_ADMITTED"
    )
    REAL_QVM_SCORING_GOVERNED_READY = "REAL_QVM_SCORING_GOVERNED_READY"
    BACKTESTING_AUTHORIZED_VALIDATED = "BACKTESTING_AUTHORIZED_VALIDATED"


class TaxAwareScope(StrEnum):
    ACQUISITION_LOT_LEDGER = "ACQUISITION_LOT_LEDGER"
    ASSET_AND_REPORTING_CURRENCY_BASIS_PROCEEDS = (
        "ASSET_AND_REPORTING_CURRENCY_BASIS_PROCEEDS"
    )
    FX_PIT_LINEAGE = "FX_PIT_LINEAGE"
    REALIZED_AND_UNREALIZED_GAIN_LOSS = "REALIZED_AND_UNREALIZED_GAIN_LOSS"
    DIVIDEND_WITHHOLDING_AND_FOREIGN_TAX_CREDIT_EVIDENCE = (
        "DIVIDEND_WITHHOLDING_AND_FOREIGN_TAX_CREDIT_EVIDENCE"
    )
    HOLDING_PERIOD_AND_LOT_SELECTION_POLICY = "HOLDING_PERIOD_AND_LOT_SELECTION_POLICY"
    TAX_AWARE_TURNOVER_AND_REALIZATION_COST = "TAX_AWARE_TURNOVER_AND_REALIZATION_COST"
    PRE_TAX_VS_AFTER_TAX_EXPECTED_RETURN = "PRE_TAX_VS_AFTER_TAX_EXPECTED_RETURN"
    DIRECT_EQUITY_AND_FUTURE_WRAPPER_COMPARISON = (
        "DIRECT_EQUITY_AND_FUTURE_WRAPPER_COMPARISON"
    )
    REPORTING_AND_RECONCILIATION_TRACEABILITY = (
        "REPORTING_AND_RECONCILIATION_TRACEABILITY"
    )


class NextBlockScope(StrEnum):
    EXTERNAL_ATTESTATION_BINDING = "EXTERNAL_ATTESTATION_BINDING"
    INDEPENDENT_ACTOR_SEPARATION = "INDEPENDENT_ACTOR_SEPARATION"
    TRUST_LIFECYCLE_AND_REVOCATION = "TRUST_LIFECYCLE_AND_REVOCATION"
    AUTHENTIC_ENTITLEMENT_REFERENCE = "AUTHENTIC_ENTITLEMENT_REFERENCE"
    PROVIDER_ADMISSION_FOUNDATION_ONLY = "PROVIDER_ADMISSION_FOUNDATION_ONLY"


class MergeOrder(StrEnum):
    AFTER_CURRENT_BLOCK_MERGED = "AFTER_CURRENT_BLOCK_MERGED"


class NextBlockAuthorization(BaseModel):
    """Code-owned authorization to build a foundation, never to activate REAL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_block: Literal[
        RoadmapBlock.IBKR_REPRODUCIBLE_READ_ONLY_LOCAL_OBSERVATION_PROBE
    ]
    name: Literal[
        RoadmapBlock.IBKR_OBSERVATION_EXTERNAL_AUTHENTICITY_FOUNDATION
    ]
    foundation_implementation: Literal[
        ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT
    ]
    implementation_authorized: Literal[True]
    real_external_activation: Literal[ImplementationAuthorization.NOT_AUTHORIZED]
    activation_real: Literal[False]
    operating_mode: Literal["CONTRACT_TEST_ONLY"]
    operating_mode_real: Literal[False]
    merge_order: Literal[MergeOrder.AFTER_CURRENT_BLOCK_MERGED]
    successor_pr: Literal["NEW_PR_REQUIRED"]
    scope: tuple[NextBlockScope, ...]
    evidence_states: tuple[
        Literal["OBSERVED_UNTRUSTED"],
    ]
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    trust_root: Literal["NOT_PROVISIONED"]
    durable_replay: Literal["NOT_PROVISIONED"]
    independent_verifier: Literal["NOT_PROVISIONED"]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]

    @model_validator(mode="after")
    def validate_authorization_boundary(self):
        if self.current_block.value == self.name.value:
            raise ValueError("roadmap successor cannot reference the current block")
        if not self.scope:
            raise ValueError("roadmap successor must have implementable scope")
        if self.foundation_implementation is not ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT:
            raise ValueError("roadmap successor must be explicitly authorized to implement")
        if self.real_external_activation is not ImplementationAuthorization.NOT_AUTHORIZED:
            raise ValueError("REAL activation must remain forbidden")
        if self.gate_states != tuple(
            (gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate
        ):
            raise ValueError("all gates must remain OPEN_EXTERNAL")
        return self


NEXT_BLOCK = NextBlockAuthorization(
    current_block=RoadmapBlock.IBKR_REPRODUCIBLE_READ_ONLY_LOCAL_OBSERVATION_PROBE,
    name=RoadmapBlock.IBKR_OBSERVATION_EXTERNAL_AUTHENTICITY_FOUNDATION,
    foundation_implementation=ImplementationAuthorization.AUTHORIZED_TO_IMPLEMENT,
    implementation_authorized=True,
    real_external_activation=ImplementationAuthorization.NOT_AUTHORIZED,
    activation_real=False,
    operating_mode="CONTRACT_TEST_ONLY",
    operating_mode_real=False,
    merge_order=MergeOrder.AFTER_CURRENT_BLOCK_MERGED,
    successor_pr="NEW_PR_REQUIRED",
    scope=tuple(NextBlockScope),
    evidence_states=("OBSERVED_UNTRUSTED",),
    gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    trust_root="NOT_PROVISIONED",
    durable_replay="NOT_PROVISIONED",
    independent_verifier="NOT_PROVISIONED",
    real_route="QVM_NOT_READY",
    global_readiness="INSUFFICIENT_REAL_DATA",
    trade_decision="NO_TRADE",
    signals_generated=False,
    live_execution_enabled=False,
    backtesting="NOT_AUTHORIZED",
)


class AfterNextBlockCandidate(BaseModel):
    """No successor beyond the authorized foundation has been selected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    after: Literal[
        RoadmapBlock.IBKR_OBSERVATION_EXTERNAL_AUTHENTICITY_FOUNDATION
    ]
    name: Literal["UNDETERMINED"]
    implementation_authorized: Literal[False]
    activation_real: Literal[False]
    decision_state: Literal["ARCHITECTURAL_DECISION_REQUIRED"]


AFTER_NEXT_BLOCK = AfterNextBlockCandidate(
    after=RoadmapBlock.IBKR_OBSERVATION_EXTERNAL_AUTHENTICITY_FOUNDATION,
    name="UNDETERMINED",
    implementation_authorized=False,
    activation_real=False,
    decision_state="ARCHITECTURAL_DECISION_REQUIRED",
)


class FutureTaxAwareCapability(BaseModel):
    """Future optimizer dependency; scope authority is not activation authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[RoadmapBlock.TAX_LOT_TAX_AWARE_PORTFOLIO_GOVERNANCE]
    status: Literal[FutureCapabilityStatus.FUTURE_AUTHORIZED]
    current_next_block: Literal[False]
    implementation_authorized: Literal[False]
    activation_authorized: Literal[False]
    dependencies: tuple[TaxAwareDependency, ...]
    scope: tuple[TaxAwareScope, ...]
    required_before: tuple[Literal["PORTFOLIO_OPTIMIZER_REBALANCE_LIVE"], ...]
    contract_fields: tuple[TaxLotContractField, ...]
    reporting_base_currency: Literal["CONFIGURABLE"]
    asset_currency: Literal["MULTI_CURRENCY"]
    fx_pit_lineage_required: Literal[True]
    tax_policy_source: Literal["VERSIONED_JURISDICTION_TAX_POLICY_REGISTRY"]
    policy_effective_dates_required: Literal[True]
    tax_estimate_separate_from_tax_filing_truth: Literal[True]
    enables_trading: Literal[False]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]

    @model_validator(mode="after")
    def validate_future_boundary(self):
        if self.dependencies != tuple(TaxAwareDependency):
            raise ValueError("tax-aware dependencies must remain complete and ordered")
        if self.contract_fields != tuple(TaxLotContractField):
            raise ValueError("tax-lot placeholder contract must remain complete")
        if self.scope != tuple(TaxAwareScope):
            raise ValueError("tax-aware future scope must remain complete")
        return self


FUTURE_TAX_AWARE_CAPABILITY = FutureTaxAwareCapability(
    name=RoadmapBlock.TAX_LOT_TAX_AWARE_PORTFOLIO_GOVERNANCE,
    status=FutureCapabilityStatus.FUTURE_AUTHORIZED,
    current_next_block=False,
    implementation_authorized=False,
    activation_authorized=False,
    dependencies=tuple(TaxAwareDependency),
    scope=tuple(TaxAwareScope),
    required_before=("PORTFOLIO_OPTIMIZER_REBALANCE_LIVE",),
    contract_fields=tuple(TaxLotContractField),
    reporting_base_currency="CONFIGURABLE",
    asset_currency="MULTI_CURRENCY",
    fx_pit_lineage_required=True,
    tax_policy_source="VERSIONED_JURISDICTION_TAX_POLICY_REGISTRY",
    policy_effective_dates_required=True,
    tax_estimate_separate_from_tax_filing_truth=True,
    enables_trading=False,
    trade_decision="NO_TRADE",
    signals_generated=False,
    live_execution_enabled=False,
)


def validate_next_block(value: Any) -> NextBlockAuthorization:
    """Reconstruct untrusted roadmap values at the public truth boundary."""
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise ValueError("roadmap model contains undeclared fields")
        value = value.model_dump(mode="json", warnings=False)
    if isinstance(value, str):
        return NextBlockAuthorization.model_validate_json(value)
    return NextBlockAuthorization.model_validate(value)
