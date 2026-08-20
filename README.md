# Trading

Systematic Equity Research & Portfolio Engine built with a capital-preservation-first mandate.

## Current stage

`phase-1-market-data` introduces a replaceable EOD price-source contract and a real provider
adapter while preserving the Phase 0 validation bundle. No live trading logic is enabled.

## Core principles

- Validate edge before building production complexity.
- No leverage, margin borrowing, short selling, or live swing sleeve in V1.
- Critical data/integrity failures mean `NO_TRADE`.
- PostgreSQL will be the operational source of truth; DuckDB/Parquet will hold research history.
- Excel and Streamlit are reporting layers, never execution sources.
- Every model run receives a reproducible `run_id` and validation manifest.
- System Health answers “did the machine run correctly today?”; Model Quality answers “does the strategy still have evidence?”

## Initial workflow

```text
External Data
    -> Data Ingest
    -> Data Health
    -> Financial / Factor Calculations
    -> Model QA
    -> Signals
    -> Portfolio
    -> Risk
    -> Human Review
    -> Execution
    -> Broker
    -> Ledger / Reconciliation
    -> Validation Outputs
    -> Dashboard / Excel
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
pytest
```

## Phase 0 validation flow

The first functional flow uses a reproducible CSV price snapshot. It normalizes the ingest,
runs Data Health, creates a `run_id`, and writes validation artifacts without producing orders.

```bash
phase0-validate \
  --source data/sample/prices_2026-08-19.csv \
  --symbols AAPL,MSFT \
  --data-date 2026-08-19
```

The command writes `ingested_prices.csv`, `data_health.json`, `run_summary.json`, and
`validation_manifest.json` under `validation_outputs/<run_id>/`. The run summary always records
`live_execution_enabled: false` and `trade_decision: NO_TRADE` in this phase.

## Phase 1 EOD provider

Alpha Vantage is the V1 real-data adapter because its documented `TIME_SERIES_DAILY` endpoint
provides the required daily OHLCV fields through a small API-key-authenticated HTTP interface.
The adapter is isolated behind `PriceSource`, while CSV remains the deterministic source for
tests, fixtures, and offline validation. Phase 1 uses unadjusted daily prices intentionally;
corporate-action adjustment policy remains outside this minimal ingest phase.

Copy `.env.example` to your local environment configuration and set the value without committing
it, or export the credential directly:

```bash
export ALPHA_VANTAGE_API_KEY="..."
phase0-validate \
  --provider alpha-vantage \
  --symbols AAPL,MSFT \
  --data-date 2026-08-19
```

Requests use a 10-second timeout and two retries with short exponential backoff. Missing
credentials, transport exhaustion, provider rate-limit/error messages, malformed payloads, and
missing requested EOD rows produce explicit source errors. CI tests use mocks and fixtures and do
not access the network.

## Phase 2 point-in-time fundamentals

Phase 2 adds a deliberately small, fixture-backed `FundamentalSource` contract. Every normalized
fact carries `period_type` (`duration` or `instant`), nullable `fiscal_period_start`, required
`fiscal_period_end`, and `unit`, separately from filing and public availability timestamps
(`filed_at`, `available_at`). Duration facts require a start; instant facts require a null start.
A snapshot includes only records whose
`available_at` is at or before the requested cutoff. When multiple versions of the same
symbol/start/end/type/metric identity are available, the latest publicly available amendment
replaces the earlier version. Facts with the same end but a different start or type remain
distinct. The validation bundle adds `fundamental_snapshot.csv` and `fundamental_health.json`.

A `data_date` supplied without a time is interpreted as end-of-day
(`23:59:59.999999`) in `America/New_York`, then converted to UTC. A timezone-aware `datetime`
keeps its exact instant and is normalized to UTC; a naive `datetime` is interpreted as UTC.

CSV is the first adapter so point-in-time behavior remains deterministic and CI stays offline.
Provider-specific network ingestion and credentials are intentionally deferred; future adapters
must implement the same interface and retain their raw availability timestamps. A future SEC
adapter must normalize monetary values to a documented canonical currency/scale per company
before calculation; the engine never converts currencies or scales silently.

This phase performs ingest, normalization, PIT gating, and validation only. It does not calculate
ratios, scores, signals, valuation, portfolios, orders, or backtests. Every run remains
`NO_TRADE` with live execution disabled.

## Phase 3 financial calculation engine V1

Phase 3 calculates a deliberately small set of auditable metrics only from the Phase 2 PIT
snapshot. Missing facts remain `MISSING`; duplicate, conflicting, non-finite, or mathematically
invalid inputs remain `NOT_COMPUTED` with a reason. No input is silently replaced by zero or a
proxy. Each output retains symbol, start/end, period type/basis, metric, value, result unit,
status, reason, and per-input lineage (source, availability, unit, start/end, and period type).

Flow inputs combined by a formula must have the same start and end. FCF requires matching CFO
and CapEx periods; FCF margin also requires matching Revenue; CFO / Net Income requires matching
periods. Flow/instant ratios use balance facts exactly at the flow `period_end`. Period or unit
incompatibility is `NOT_COMPUTED`; there is no automatic reconciliation or conversion. Monetary
arithmetic requires one identical currency/scale unit, while Tax Rate must use `RATIO`.

V1 definitions:

- `Free Cash Flow = Cash from Operations - Capital Expenditures`. Capital expenditures are
  expected as a positive cash outflow magnitude.
- `Free Cash Flow Margin = Free Cash Flow / Revenue`; zero revenue is not computed.
- `Net Debt = Total Debt - Cash`. Explicit zero debt is valid; missing debt is not zero.
- `Net Debt / EBITDA = Net Debt / EBITDA`; zero or negative EBITDA is not computed.
- `CFO / Net Income = Cash from Operations / Net Income`; zero net income is not computed.
- `ROIC V1 (period) = NOPAT / Invested Capital`, where `NOPAT = Operating Income * (1 - Tax Rate)` and
  `Invested Capital = Total Debt + Total Equity - Cash`. Tax rate must be within `[0, 1]`, and
  invested capital must be positive. These inputs must be reported facts; no effective-tax or
  balance-sheet proxy is inferred. The output is explicitly the reported flow period's ROIC and
  is not annualized; only an FY/TTM input period can be interpreted as FY/TTM.

The validation bundle adds `financial_metrics.csv` and `financial_health.json`; manifest and run
summary status is `PASS` when all emitted metrics pass, `WARNING` when PASS is mixed with
`MISSING`/`NOT_COMPUTED`, and `FAIL` for an empty snapshot, no emitted expected metrics, or no
PASS metric. Financial-stage exceptions overwrite the earlier Phase 2 PASS audit state with
error type/message, financial `FAIL`, `NO_TRADE`, and live execution disabled, then re-raise the
original exception. The manifest preserves existing critical checks and counts. It always records
`NO_TRADE` and
`live_execution_enabled: false`. Phase 3 contains no scores, signals, ranking, valuation,
portfolio construction, backtesting, broker integration, or execution.

## Pre-QVM hardening foundation

Before Quality/Value/Momentum work, the fundamental layer also provides non-investment
infrastructure:

- Raw provider concepts remain separate from canonical metrics. Normalization accepts only
  explicit `(source, raw_concept)` mappings and rejects unknown concepts; it never uses proxies.
- `fundamental_history.csv` preserves filing/restatement versions by `filed_at` and
  `available_at`; historical snapshots select only versions public at their cutoff.
- Period utilities classify instant, quarterly, FY, and YTD facts. TTM requires four contiguous,
  non-overlapping quarters available at the PIT cutoff and retains component lineage.
- Reporting currency, functional currency, and optional FX rate/date/source metadata are stored
  separately. No value is converted automatically.
- Accounting-quality diagnostics emit CFO/Net Income and accrual-ratio checks. Their health
  document declares `is_investment_signal: false`; warnings are QA, not alpha inputs.
- Per-fact data confidence documents source quality, completeness, same-version conflicts, and
  numeric validation. It measures data reliability, not expected return.
- PIT-aware sector and management/capital-allocation contracts are defined without rankings or
  scores.
- The append-only research registry preregisters hypothesis, outcome, universe, and sample window
  under a unique experiment ID to reduce repeated-test and overfitting risk.

Phase 2 adds `fundamental_history.csv` and `data_confidence.csv`; Phase 3 adds
`accounting_quality.csv` and `accounting_quality_health.json`. These layers do not implement QVM,
alpha scores, portfolio construction, backtesting, or execution. `NO_TRADE` and
`live_execution_enabled: false` remain mandatory.

## Phase 3.6 investment universe foundation

Phase 3.6 defines which assets the research system may evaluate. The source contract requires
symbol, exchange, asset type, country/region, optional sector/industry metadata, market cap,
average share and dollar volume, listing date, source, source timestamp, and PIT availability.
Validation emits `universe_membership.csv` without dropping any asset: each row is `ELIGIBLE` or
`EXCLUDED`, with all applicable exclusion reasons, deterministic completeness confidence, and
source lineage. `universe_validation.json` records counts, reasons, and the exact rules used.

Market-cap, volume, dollar-liquidity, listing-age, asset-type, and exchange rules are configuration
inputs rather than constants. Missing data needed by an enabled rule causes an explicit exclusion;
duplicate symbols, unknown asset types, invalid timestamps, and malformed schemas fail the run and
leave an audit trail. This foundation contains no QVM, alpha score, ranking, portfolio,
backtesting, broker integration, or execution. It always remains `NO_TRADE` with live execution
disabled.

Universe validation also writes immutable, date-addressed snapshots so a historical eligible set
can be reconstructed without substituting today's listings. Diagnostics report eligible/excluded
counts, sector/industry/country/exchange and market-cap distributions, concentration, and entries or
exits versus the previous snapshot. Threshold stress scenarios expose coverage loss. Health is an
auditable `PASS`, `WARNING`, or `FAIL`; an empty or undersized universe fails, while destructive
coverage, concentration, and threshold sensitivity produce warnings. No alpha or QVM logic is
included.

## Safety

This repository is not authorized for unattended live trading. Live execution is a later gated phase after research, backtesting, paper trading, reconciliation, and operational validation.
