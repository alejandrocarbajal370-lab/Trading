# Phase 4.3 — Momentum Factor Engine V1.1 audit

This is a research-only metric layer. It does not calculate a composite Momentum score, rank
securities, combine Quality/Value/Momentum, construct portfolios, backtest, generate signals, or
execute trades.

## Adjusted and log-price foundation

`adjusted_close` is the only permitted Momentum price input. `raw_close`, when present, is retained
only for audit and reconciliation. A series labelled unadjusted, an unknown corporate-action state,
or a non-positive adjusted price fails closed. The derived layer records `log(adjusted_close)` with
the exact input, natural-log formula, and `log-price-v1` transformation version in lineage.

Outputs that represent performance remain ordinary percentage returns. Daily log returns are used
for volatility because they are additive through time; trend stability regresses log adjusted price
on the market-session index.

## Session-based definitions

- `momentum_12_1`: `adjusted_close[t-21] / adjusted_close[t-252] - 1`.
- `momentum_6m`: `adjusted_close[t] / adjusted_close[t-126] - 1`.
- `relative_strength_6m`: the asset 126-session return minus the compatible benchmark return.
- `volatility_adjusted_momentum_12_1`: 12-1 return divided by sample volatility of daily log
  returns, annualized with the configured calendar's sessions per year.
- `trend_stability_12m`: R-squared of log adjusted price against session index over 252 sessions.

## Market-data audit result

The V1.1 audit is complete for the implemented contract. It verifies PIT availability, explicit
confidence and source lineage, provider-validated split/dividend metadata, expected versus observed
XNYS sessions, session-based staleness, and asset/benchmark compatibility for adjusted-price policy,
calendar, timing policy, and observed sessions. The Alpha Vantage adapter requests the full
`TIME_SERIES_DAILY_ADJUSTED` history and preserves raw close, adjusted close, dividend amount, split
coefficient, adjustment factor, and provider-function lineage.

Universe identity, ruleset, checksums, and research-only safety state remain mandatory inputs to the
runner. Quality and Value integration was regression-tested, but no QVM combination exists in this
phase. Reproducibility covers the registered experiment, immutable dataset, governed universe,
contract, assumptions, and runtime versions.

The audit approves the data and metric foundation only. It does not approve a factor score or live
use. Every output preserves `trade_decision=NO_TRADE` and `live_execution_enabled=false`.
