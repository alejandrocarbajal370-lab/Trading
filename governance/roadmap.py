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
    STEP6_EXTERNAL_GATE_REMEDIATION_PENDING_CANONICAL_SCHEDULING = (
        "Step 6 External-Gate Remediation — Pending Canonical Scheduling"
    )
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
    EXTERNAL_TRUST_BACKEND_PROVISIONING_CONTRACT_FOUNDATION = (
        "External Trust Backend Provisioning Contract Foundation"
    )
    GOVERNED_SUFFICIENT_OBSERVATION_POLICY_PROVIDER_ADMISSION_EVIDENCE_AGGREGATION_FOUNDATION = (
        "Governed Sufficient Observation Policy & Provider Admission Evidence Aggregation Foundation"
    )
    IBKR_REAL_PROVISIONING_AUTHENTIC_ENTITLEMENT_EVIDENCE_FOUNDATION = (
        "IBKR REAL Provisioning + Authentic Entitlement Evidence Foundation"
    )
    EXTERNAL_TRUST_ATTESTATION_INDEPENDENT_VERIFIER_REAL_FOUNDATION = (
        "External Trust, Attestation & Independent Verifier REAL Foundation"
    )
    DURABLE_CUSTODY_WORM_REPLAY = "Durable Custody + WORM + Replay"
    LICENSING_LEGAL = "Licensing/legal"
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


class NextBlockAuthorization(BaseModel):
    """Fail-closed placeholder until canonical scheduling names a Step 6 block."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[
        RoadmapBlock.STEP6_EXTERNAL_GATE_REMEDIATION_PENDING_CANONICAL_SCHEDULING
    ]
    scheduling_state: Literal["PENDING_CANONICAL_SCHEDULING"]
    foundation_implementation: Literal[ImplementationAuthorization.NOT_AUTHORIZED]
    implementation_authorized: Literal[False]
    real_external_activation: Literal[ImplementationAuthorization.NOT_AUTHORIZED]
    activation_real: Literal[False]
    operating_mode: Literal["NO_IMPLEMENTATION_AUTHORIZED"]
    operating_mode_real: Literal[False]
    scope: tuple[Any, ...] = ()
    gate_states: tuple[tuple[EvidenceGate, Literal[GateState.OPEN_EXTERNAL]], ...]
    trust_root: Literal["NOT_PROVISIONED"]
    durable_replay: Literal["NOT_PROVISIONED"]
    external_custody: Literal["NOT_PROVISIONED"]
    worm_retention: Literal["NOT_PROVISIONED"]
    independent_verifier: Literal["NOT_PROVISIONED"]
    real_route: Literal["QVM_NOT_READY"]
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"]
    trade_decision: Literal["NO_TRADE"]
    signals_generated: Literal[False]
    live_execution_enabled: Literal[False]
    backtesting: Literal["NOT_AUTHORIZED"]

    @model_validator(mode="after")
    def validate_authorization_boundary(self):
        if self.foundation_implementation is not ImplementationAuthorization.NOT_AUTHORIZED:
            raise ValueError("unscheduled roadmap work must remain unauthorized")
        if self.implementation_authorized or self.scope:
            raise ValueError("unscheduled roadmap work cannot carry implementation scope")
        if self.real_external_activation is not ImplementationAuthorization.NOT_AUTHORIZED:
            raise ValueError("REAL activation must remain forbidden")
        if self.gate_states != tuple(
            (gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate
        ):
            raise ValueError("all gates must remain OPEN_EXTERNAL")
        return self


NEXT_BLOCK = NextBlockAuthorization(
    name=RoadmapBlock.STEP6_EXTERNAL_GATE_REMEDIATION_PENDING_CANONICAL_SCHEDULING,
    scheduling_state="PENDING_CANONICAL_SCHEDULING",
    foundation_implementation=ImplementationAuthorization.NOT_AUTHORIZED,
    implementation_authorized=False,
    real_external_activation=ImplementationAuthorization.NOT_AUTHORIZED,
    activation_real=False,
    operating_mode="NO_IMPLEMENTATION_AUTHORIZED",
    operating_mode_real=False,
    scope=(),
    gate_states=tuple((gate, GateState.OPEN_EXTERNAL) for gate in EvidenceGate),
    trust_root="NOT_PROVISIONED",
    durable_replay="NOT_PROVISIONED",
    external_custody="NOT_PROVISIONED",
    worm_retention="NOT_PROVISIONED",
    independent_verifier="NOT_PROVISIONED",
    real_route="QVM_NOT_READY",
    global_readiness="INSUFFICIENT_REAL_DATA",
    trade_decision="NO_TRADE",
    signals_generated=False,
    live_execution_enabled=False,
    backtesting="NOT_AUTHORIZED",
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
