# Phase 4.3 — Momentum Factor Engine V1

This phase is a research-only metric layer. It does not calculate a composite Momentum score,
rank securities, combine QVM, construct portfolios, backtest, generate signals, or execute trades.

## Metric definitions

- `momentum_12_1`: `P(as_of - 1 month) / P(as_of - 12 months) - 1`. The most recent
  month is excluded and every selected observation must have been available by `as_of`.
- `momentum_6m`: `P(as_of) / P(as_of - 6 months) - 1`.
- `relative_strength_6m`: the asset's six-month return minus the six-month return of the
  explicitly configured benchmark. It is a difference in returns, not a cross-sectional rank.
- `volatility_adjusted_momentum_12_1`: 12-1 return divided by the annualized sample standard
  deviation of daily log returns in the same window, using `sqrt(252)`. Zero or non-finite
  volatility fails closed.
- `trend_stability_12m`: R-squared from an OLS relationship between log close and elapsed
  calendar days over the trailing year. It describes fit consistency and is not a factor score.

## Limitations and safety boundary

The fixed 30/183/365-calendar-day anchors are resolved to the latest prior observation within
seven calendar days. Annualizing with 252 sessions is a convention and may not fit every market.
Volatility-adjusted momentum is not a Sharpe ratio: no risk-free rate is subtracted, and the
return numerator is not annualized. Trend R-squared does not encode trend direction or economic
magnitude. Relative strength depends materially on benchmark choice.

The contract records adjusted versus unadjusted prices, corporate-action state, trading calendar,
missing-session state, staleness, confidence, lineage, and point-in-time availability. Unadjusted
prices are explicitly warned because splits and dividends may distort returns. These controls are
a safety foundation only; the complete market-data audit remains a mandatory gate before Momentum
can be approved.

All outputs preserve `trade_decision=NO_TRADE` and `live_execution_enabled=false`.
