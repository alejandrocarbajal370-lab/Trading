# CORSO Dashboard — Multi-Asset Experience North Star

Status: **TARGET DIRECTION; FUTURE / NOT_IMPLEMENTED / NOT_AUTHORIZED**

## Product identity and authority boundary

The dashboard's stable identity is the **Institutional Liquid Command Center**: institutional
first, premium second and technological third, with structured density rather than decorative
complexity. It is CORSO's unified interaction layer, never the owner or inventor of model logic.
The backend calculates and owns canonical semantics; the frontend presents them, their state and
their provenance.

Every unavailable value must use an explicit state such as `NOT_SUPPORTED`, `MISSING`, `UNKNOWN`,
`NOT_APPLICABLE` or `PARTIAL`. The interface must never fabricate, infer or cosmetically replace a
missing model output. Missing analytics do not erase an otherwise valid security.

This North Star defines future scope only. No dashboard, engine, execution, backtesting or
portfolio capability is implemented or authorized by this document.

## Primary navigation

The product has **exactly seven primary tabs**:

1. Overview
2. Portfolio
3. Research
4. Operations
5. Intelligence
6. Scenarios
7. Audit

Equity and Fixed Income are asset classes, not top-level tabs. A floating Top Dock provides global
context and navigation. The target global Command Center/search resolves instruments, issuers,
portfolios, research cases, operations and audit records according to authorization and capability.

## Multi-asset contract

A multi-asset abstraction and capability registry determine which common and asset-specific views
are valid. First-class target assets are Equity, Fixed Income and Cash. Future asset classes must
not force premature implementation now.

Identity is stable and never ticker-only. `Security != Issuer`; one issuer may have multiple equity
listings and debt instruments. Issuer exposure aggregates those securities without losing their
instrument-level identity, currency, seniority, terms or provenance.

Admission is separated into:

- security admission: the instrument and identity are valid;
- capability admission: a particular calculation/view is supported for it; and
- model admission: a model is validated and authorized for the intended use.

A failure in one layer does not silently promote or delete another. Global context includes
portfolio, reporting currency, `as_of`, PIT cutoff, environment and data/model versions. Visible
data states include provenance, freshness, quality, partiality and admission status.

## Seven-tab purpose

### Overview

Executive state of portfolio, markets, research, operations and exceptions. Multi-asset summaries
appear only when canonical outputs exist and retain currency, PIT and completeness context.

### Portfolio

Positions, cash, issuer exposure, asset allocation, currency, performance and risk through
capability-driven views. Common dimensions coexist with conditional Equity and FI diagnostics.
No optimization, candidate allocation or rebalance is invented when the Portfolio Engine is absent.

### Research

Common research-case shell with asset-specific modules. Equity may expose QVM, Fundamental
Context, Expectations, Capital Loss and Confidence. FI may expose terms, cash flows, valuation,
rates/spread risk, credit, relative value and confidence only when those are canonical engine
outputs.

### Operations

Data intake status, validation, reconciliation, cash/transaction events, exceptions and readiness.
Economic history uses append-only event semantics with corrections, voids and supersession; no
physical deletion of promoted history.

### Intelligence

Cross-asset issuer, macro, regime, rates, spread, liquidity and FX intelligence. Relationships are
shown without conflating security and issuer or observed and expected values.

### Scenarios

Capability-driven shocks and multi-asset scenarios. Rates, curve, spread, credit, equity, FX and
cash-flow effects appear only when supported by governed inputs and models. No invented scenario
output or implied forecast is permitted.

### Audit

Every material number supports drill-down to calculation, inputs, sources, versions, timestamps,
status and lineage. The audit view must make corrections and supersession visible and distinguish
observed facts, assumptions, estimates and model outputs.

## Security Detail

Security Detail uses a common shell polymorphic by asset class: identity, issuer, currency,
admission, data state, provenance, timeline and related research are shared; the body renders only
valid capabilities. FI views may include contractual terms, pricing, cash-flow schedule, curves,
spread/risk and credit. `clean_price != dirty_price`, `coupon != dividend`, and expected values are
never presented as observed facts.

Maturity, credit, rates and spread views appear only after canonical FI outputs exist. Equity and
FI comparisons retain their distinct economic meanings rather than coercing them into one score.

## Data Intake mini-app

Data Intake is a separate administrative mini-app, not an eighth primary tab. It provides adaptive,
structured manual entry by instrument type, validation preview, duplicate detection, reconciliation,
maker/checker controls where required and immutable promotion into canonical economic history.
Corrections use linked correcting/voiding/superseding events; promoted records are not physically
deleted.

## Absolute Broker X / GBM policy

Broker X, including GBM if it is selected, has **no connection to CORSO**. The following are
prohibited for Broker X data or workflows:

- Broker X API or direct dashboard query;
- CSV, XLSX/Excel, screenshots, photos, PDF statements or broker reports;
- file upload, automated ingestion, scraping or browser automation;
- stored Broker X credentials; and
- order routing, submission, modification, cancellation or transmission.

Real operations executed manually at Broker X are represented only by a human entering the
economic facts through CORSO Data Intake. This policy supersedes earlier canonical target
assumptions about `BROKER_X_FILE`, statements or CSV/XLSX ingestion while preserving the valid
append-only validation, reconciliation, provenance and audit architecture.

## Environments and execution boundary

The interface preserves three explicit semantics:

- `RESEARCH`: analysis only; no simulated or real execution;
- `PAPER_IBKR`: the official simulated-trading test environment only; and
- `PRODUCTION_EXTERNAL`: real activity executed by a human outside CORSO.

`PAPER_IBKR != PRODUCTION_EXTERNAL`. If a separately authorized simulated workflow requires an
execution venue, it uses IBKR Paper. That target does not authorize paper execution now, live
execution, backtesting or a production order adapter. Production remains
`execution_authority=HUMAN_ONLY`, `human_execution_required=true`, and
`live_execution_enabled=false`.

## Performance, benchmarks and scenarios

Performance, benchmarks, multi-currency attribution and scenarios are capability-driven. Local
asset return, base-currency return, FX effect, cash flows, fees and taxes remain distinct and use
PIT-governed inputs. Unsupported histories, benchmarks or analytics show explicit states rather
than interpolation or invention.

## Visual and component system

The visual hierarchy uses four governed surfaces: Ambient, Primary, Reading and Solid. Light and
dark themes share semantic design tokens for color, typography, spacing, density, elevation,
status and motion. Accessibility includes contrast, keyboard navigation, visible focus, non-color
status cues, reduced-motion support and readable dense-data layouts. Motion communicates state and
hierarchy, never hides uncertainty or delays access to material data.

Reusable components encode presentation and accessibility, not financial calculations. The
frontend must not recompute canonical returns, prices, yields, risk, scores or audit status.

Historical AURORA visual records remain historical. In current canonical product language their
visual principles are interpreted under the CORSO name; this does not require gratuitous mutation
of immutable records or compatibility-sensitive identifiers.

## Current truth boundary

Step 6 remains **STARTED — FOUNDATION ONLY; NO GATES CLOSED**; 10/10 gates remain
`OPEN_EXTERNAL`; REAL dependencies remain `NOT_PROVISIONED`; the REAL route is `QVM_NOT_READY`;
readiness is `INSUFFICIENT_REAL_DATA`; `trade_decision=NO_TRADE`; `signals_generated=false`;
backtesting and portfolio construction remain `NOT_AUTHORIZED`; and this dashboard is
`NOT_IMPLEMENTED / NOT_AUTHORIZED`.
