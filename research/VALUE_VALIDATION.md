# Phase 4.2 — Value Factor Engine V1

Value V1 is a research-only, fail-closed measurement layer. It calculates individual valuation
metrics and never produces a score, rank, portfolio, backtest, order, or trade recommendation.
Every run preserves `trade_decision=NO_TRADE` and `live_execution_enabled=false`.

## Absolute and relative value

Absolute value compares reported company economics with the contemporaneous price paid:

- `fcf_yield = free_cash_flow / market_cap`
- `earnings_yield = earnings / market_cap`
- `ebit_yield = ebit / enterprise_value`
- `ev_to_ebit = enterprise_value / ebit`
- `ev_to_ebitda = enterprise_value / ebitda` (secondary)

Relative value compares the same measures with a governed peer group, sector, history, or regime.
V1 keeps sector-relative and historical fields as metadata foundations only. It does not calculate
percentiles, rankings, or normalization. This prevents a peer label from silently changing an
absolute metric.

## Conservative contract

Each monetary input requires an explicit currency, `unit=currency`, FY or TTM basis for flows,
`INSTANT` basis for market capitalization and enterprise value, a timezone-aware `available_at`, a
common `valuation_as_of`, confidence in `[0, 1]`, upstream status/reason, and non-empty source
lineage. Information available after the valuation date is a PIT violation. Invalid inputs produce
a null metric and an explicit status/reason rather than an inferred value.

Every Value run also requires the governed Phase 3.6 universe snapshot directory. Membership and
validation checksums, usable health, ruleset version, research-only safety state, and the canonical
`universe-YYYY-MM-DD` snapshot identity must match the registered experiment. A mismatch fails
closed and writes an immutable `value_governance_audit.json` failure record.

EV metrics are disabled for industries such as banks, insurance, consumer finance, capital markets,
and REITs, where enterprise value and operating debt do not have the same interpretation as for a
typical industrial company. Non-positive denominators fail closed. Extreme yields or multiples
remain visible but are marked `WARNING` for economic review.

Negative earnings and negative EBIT are explicit `WARNING` economics, never ordinary cheapness.
EV/EBIT with negative EBIT has no meaningful multiple, so its value remains null with an explicit
warning reason; zero EBIT remains an invalid denominator.

## Why EV/EBITDA is secondary

EBITDA ignores depreciation and amortization and can obscure the recurring capital expenditure
needed to sustain a business. This is especially fragile for capital-intensive companies. V1 emits
EV/EBITDA for context, always documents the limitation in its warnings, and does not convert the
multiple into an investment signal.

## Value without Quality

A cheap security can be a deteriorating business, a cyclical peak, an accounting anomaly, or a
capital structure under stress. Value V1 exposes `quality_context=future_linkage_required` and does
not interpret “cheap” as “good.” Linking validated Quality context is reserved for a later phase and
must not alter the raw Value measurements.

Reported FCF is not owner earnings. Maintenance capex is rarely cleanly observable, so V1 preserves
an Owner Earnings Yield metadata foundation without estimating it. Historical valuation context,
sector-relative valuation, and Quality linkage are foundations, not implemented signals.

## Outputs

- `value_metrics.csv`: individual observations, statuses, warnings, confidence, PIT data, and lineage.
- `value_health.json`: coverage and status counts with research-only safety flags.
- `value_lineage.json`: dataset and per-metric input lineage.
- `value_validation_report.json`: initial validation-layer structure and implementation status.
- `value_research_run.json`: fingerprinted dataset, universe identity/checksums, runtime dependencies,
  assumptions, foundations, and safety state.
