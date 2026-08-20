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
fact keeps its economic period (`fiscal_period_end`) separate from its filing and public
availability timestamps (`filed_at`, `available_at`). A snapshot includes only records whose
`available_at` is at or before the requested cutoff. When multiple versions of the same
symbol/period/metric are available, the latest publicly available amendment replaces the earlier
version. The validation bundle adds `fundamental_snapshot.csv` and `fundamental_health.json`.

A `data_date` supplied without a time is interpreted as end-of-day
(`23:59:59.999999`) in `America/New_York`, then converted to UTC. A timezone-aware `datetime`
keeps its exact instant and is normalized to UTC; a naive `datetime` is interpreted as UTC.

CSV is the first adapter so point-in-time behavior remains deterministic and CI stays offline.
Provider-specific network ingestion and credentials are intentionally deferred; future adapters
must implement the same interface and retain their raw availability timestamps.

This phase performs ingest, normalization, PIT gating, and validation only. It does not calculate
ratios, scores, signals, valuation, portfolios, orders, or backtests. Every run remains
`NO_TRADE` with live execution disabled.

## Phase 3 financial calculation engine V1

Phase 3 calculates a deliberately small set of auditable metrics only from the Phase 2 PIT
snapshot. Missing facts remain `MISSING`; duplicate, conflicting, non-finite, or mathematically
invalid inputs remain `NOT_COMPUTED` with a reason. No input is silently replaced by zero or a
proxy. Each output retains its symbol, fiscal period, status, reason, and input source lineage.

V1 definitions:

- `Free Cash Flow = Cash from Operations - Capital Expenditures`. Capital expenditures are
  expected as a positive cash outflow magnitude.
- `Free Cash Flow Margin = Free Cash Flow / Revenue`; zero revenue is not computed.
- `Net Debt = Total Debt - Cash`. Explicit zero debt is valid; missing debt is not zero.
- `Net Debt / EBITDA = Net Debt / EBITDA`; zero or negative EBITDA is not computed.
- `CFO / Net Income = Cash from Operations / Net Income`; zero net income is not computed.
- `ROIC V1 = NOPAT / Invested Capital`, where `NOPAT = Operating Income * (1 - Tax Rate)` and
  `Invested Capital = Total Debt + Total Equity - Cash`. Tax rate must be within `[0, 1]`, and
  invested capital must be positive. These inputs must be reported facts; no effective-tax or
  balance-sheet proxy is inferred.

The validation bundle adds `financial_metrics.csv` and `financial_health.json`; manifest and run
summary status is `PASS`, `WARNING`, or `FAIL` as applicable and always records `NO_TRADE` and
`live_execution_enabled: false`. Phase 3 contains no scores, signals, ranking, valuation,
portfolio construction, backtesting, broker integration, or execution.

## Safety

This repository is not authorized for unattended live trading. Live execution is a later gated phase after research, backtesting, paper trading, reconciliation, and operational validation.
