# Future capability — Tax Lot & Tax-Aware Portfolio Governance

Status: **FUTURE_AUTHORIZED SCOPE; NOT CURRENT NEXT_BLOCK; NOT AUTHORIZED TO IMPLEMENT OR ACTIVATE**

## Placement and dependency

This capability is a mandatory future dependency of portfolio construction, position sizing and
rebalancing. The selection model may exist earlier, but an optimizer must not decide sales or
turnover without tax-lot state and an approximate realization cost. The governed order is:

1. REAL provider data is observed, verified and admitted;
2. REAL QVM/scoring is governed and ready;
3. backtesting is explicitly authorized and validated;
4. Tax Lot & Tax-Aware Portfolio Governance is implemented and separately activated; then
5. portfolio optimizer/rebalancing may be considered, followed only later by separately governed
   broker order generation and live execution.

This document does not change `governance.roadmap.NEXT_BLOCK`, the REAL route, QVM admission or any
readiness gate. The machine-readable future scope is
`governance.roadmap.FUTURE_TAX_AWARE_CAPABILITY`.
Its ordered prerequisites are `REAL_PROVIDER_DATA_OBSERVED_VERIFIED_ADMITTED`,
`REAL_QVM_SCORING_GOVERNED_READY`, and `BACKTESTING_AUTHORIZED_VALIDATED`.

## Future functional scope

The future layer will track acquisition tax lots, acquisition/disposal dates and quantities;
cost basis and proceeds in asset and configurable reporting currencies; point-in-time FX and its
lineage; realized and unrealized gains/losses; dividends, foreign withholding and applicable
foreign-tax-credit evidence; holding period and lot-selection policy; and evidence sufficient for
reporting and reconciliation. Portfolio construction may then treat tax-aware turnover and
estimated realization cost as constraints or penalties and compare expected pre-tax and after-tax
returns.

The machine-readable scope identifiers are `ACQUISITION_LOT_LEDGER`,
`ASSET_AND_REPORTING_CURRENCY_BASIS_PROCEEDS`, `FX_PIT_LINEAGE`,
`REALIZED_AND_UNREALIZED_GAIN_LOSS`,
`DIVIDEND_WITHHOLDING_AND_FOREIGN_TAX_CREDIT_EVIDENCE`,
`HOLDING_PERIOD_AND_LOT_SELECTION_POLICY`, `TAX_AWARE_TURNOVER_AND_REALIZATION_COST`,
`PRE_TAX_VS_AFTER_TAX_EXPECTED_RETURN`, `DIRECT_EQUITY_AND_FUTURE_WRAPPER_COMPARISON`, and
`REPORTING_AND_RECONCILIATION_TRACEABILITY`.

The architecture is multi-currency. A configuration may use MXN as reporting base and USD as an
asset currency, but no identity or personal default is hardcoded. Direct equities are supported in
scope; future governed analysis may compare local, US and UCITS ETF or other wrappers. The engine
must draw no jurisdiction-specific conclusion until governed rules exist.

## Minimum placeholder contract

The machine-readable field registry contains `tax_lot_id`, `security_id`, `acquired_at`, `quantity`,
`cost_basis_asset_ccy`, `cost_basis_reporting_ccy`, `fx_rate_at_acquisition`, `fx_lineage_hash`,
`realized_proceeds_asset_ccy`, `realized_proceeds_reporting_ccy`, `fx_rate_at_disposal`,
`realized_gain_loss_reporting_ccy`, `dividend_income`, `foreign_withholding`,
`holding_period_days`, `tax_policy_version`, `jurisdiction`, and `evidence_hash`.

No tax rates, treaty rates, tax thresholds or SAT/IRS rules are embedded now. Future rules must come
from a versioned jurisdiction/tax-policy registry with effective dates. `tax_estimate` is strictly
separate from `tax_filing_truth`: estimates may inform portfolio decisions, but the system cannot
state a definitive filing obligation without a specific governed policy/legal layer. This is
traceability and decision-support scope, not tax advice or a definitive legal calculation.

## Frozen safety boundary

No scoring, backtest authorization, portfolio/sizing, target price, broker/order/execution, filing
automation or evasion logic is added. `trade_decision=NO_TRADE`, `signals_generated=false` and
`live_execution_enabled=false` remain fixed. This capability cannot activate before all three
upstream dependencies and never enables trading by itself.
