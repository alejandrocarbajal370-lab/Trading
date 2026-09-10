# ADR 0020 — Aurora Human-Only Execution and Canonical Portfolio Ledger

Status: **ACCEPTED; FROZEN PROJECT MANDATE; INTENDED ARCHITECTURE NOT IMPLEMENTED**

## Decision and supersession

Aurora is a research, portfolio-intelligence, monitoring, analysis and decision-support system. It
is not a real-execution bot. In REAL production:

- `human_execution_required = true`
- `execution_authority = HUMAN_ONLY`
- `live_execution_enabled = false`

Aurora may propose trades and rebalances for human review, but it must not submit, modify, cancel
or transmit an order. It must not initiate a cash transfer or withdrawal, change a banking
instruction, or integrate with an Account Management or cash-movement capability that could move
funds. No production `placeOrder()` or equivalent adapter is authorized.

This ADR supersedes every earlier roadmap, scope or architecture statement that suggests eventual
automatic/live broker execution by Aurora, including language that describes live execution as a
later gated phase. The decision cannot be reversed by configuration or a runtime toggle. Reversal
requires an explicit future project mandate and a formal superseding ADR.

## Frozen role map

| Component | Frozen role |
| --- | --- |
| IBKR | Production `MARKET_DATA_RESEARCH` observation source; read-only access to the user's/Aurora real account where applicable |
| IBKR Paper | Temporary paper-trading, testing and validation environment only |
| Broker X | Future real-capital broker/custodian and source of portfolio/custody truth; manual execution outside Aurora |
| PostgreSQL | Intended canonical portfolio ledger, state and truth consumed by Aurora |
| Google Sheets, CSV, XLSX and manual entry | Ingestion interfaces only; never canonical before validation and reconciliation |
| Aurora | Analytics, research, monitoring, decision support and dashboard; no funds or order authority |
| Human | Sole final execution authority |

IBKR is not Aurora's real custody or execution destination under this mandate. Aurora must not
implement a production IBKR order adapter. Broker X will provide real custody and real execution,
but execution is `HUMAN_ONLY` and manual outside Aurora. Aurora will have no Broker X API for
orders, cancellations, modifications, transmission, cash movement, withdrawals or banking
changes. Broker X has not been selected and its provider details are not known.

## Broker Execution Profile

A future, separately authorized **Broker Execution Profile** must define at least:

- commissions and fees;
- FX/conversion spreads and currency handling;
- available instruments and fractional-share support;
- minimum order and lot sizes;
- order types;
- settlement and cash availability;
- taxes, withholding and reporting where relevant;
- corporate actions;
- market hours and access;
- statement, CSV and XLSX formats; and
- the reconciliation process.

The profile describes the constraints used by decision support and reconciliation. It does not
grant Aurora execution or funds authority.

## Canonical portfolio architecture

PostgreSQL is the intended canonical portfolio ledger/state/truth for Aurora. Imports from Broker X
statements, CSV, XLSX, Google Sheets or manual entry are untrusted ingestion inputs until validated
and reconciled. Aurora and its dashboard consume the canonical layer read-only; the dashboard must
not query Broker X directly.

The minimum canonical model must preserve:

1. Portfolio snapshots: `instrument_id`, `quantity`, `cash`, and `as_of`.
2. Transaction ledger: `BUY`/`SELL`, instrument, quantity, execution price, commission, execution
   time, currency and source.
3. Cash ledger: deposits, withdrawals, dividends, fees and FX conversions.
4. Provenance, timestamps and reconciliation status.

Derived views may calculate NAV, weights, cost basis, realized/unrealized P&L, returns, cash
percentage, drift and rebalance requirements. Current positions alone are insufficient for
auditable cost basis, P&L or history.

The governed target flows are:

```text
IBKR market/research -> governed ingestion -> canonical data layer -> Aurora -> Dashboard
Human executes at Broker X -> statement/CSV/XLSX/Google Sheet/manual validated import
                           -> PostgreSQL -> Aurora
```

Transaction ingestion must conceptually validate instrument, currency, quantity, timestamp,
reasonable price against observed market data where appropriate, duplicates, cash reconciliation,
portfolio before/after, and source/provenance. Exact schemas, controls and implementations require
future authorization.

## Broker Asset Protection invariant

Compromise of GitHub, the dashboard or the research engine must not itself provide a path to submit
real orders, withdraw funds, transfer cash or change banking instructions. This protection is an
architectural, layered separation of authority and capability, not merely a TWS checkbox.

## Roadmap

The governed sequence is preserved:

1. Step 5 — **CLOSED**.
2. Step 6 — capture sufficient authentic evidence.
3. Close external gates.
4. Provider Admission REAL.
5. SEC + IBKR to QVM REAL.
6. Auxiliary cross-checks.
7. Shortlist.
8. Governed backtesting.
9. Portfolio construction.
10. IBKR Paper validation.
11. Production manual execution at Broker X by a human.

There is no production auto-execution phase under the current mandate. Sequence position does not
authorize implementation or relax a gate. Step 6 is `NOT STARTED`.

## Current safety state and implementation boundary

- Gate #2: `OPEN_EXTERNAL`
- all 10/10 gates: `OPEN_EXTERNAL`
- REAL legal, authority, trust, custody and provider admission: `NOT_PROVISIONED`
- real route: `QVM_NOT_READY`
- global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`
- `signals_generated=false`
- `live_execution_enabled=false`
- backtesting: `NOT_AUTHORIZED`

This ADR records architecture only. It does not implement PostgreSQL, Broker X, the Broker
Execution Profile, canonical portfolio ingestion or reconciliation, portfolio construction,
backtesting, provider admission, QVM REAL, order handling or execution. **Paso 6: NOT STARTED. NO
EXECUTION IMPLEMENTED.**
