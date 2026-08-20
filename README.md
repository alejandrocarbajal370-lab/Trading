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

## Safety

This repository is not authorized for unattended live trading. Live execution is a later gated phase after research, backtesting, paper trading, reconciliation, and operational validation.
