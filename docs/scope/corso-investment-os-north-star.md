# CORSO Investment OS — Engine North Star

Status: **TARGET DIRECTION; ACTIVE SECONDARY FI TRACK; NOT AN IMPLEMENTATION OR ACTIVATION AUTHORIZATION**

## Purpose and authority

This document defines the durable target direction for the CORSO model/engine. It preserves valid
foundations and does not claim that target capabilities exist. Current implementation and safety
state are governed by the roadmap and accepted ADRs; where this North Star describes a future
capability, its state is `FUTURE / NOT_IMPLEMENTED / NOT_AUTHORIZED` unless a later, explicit work
authorization says otherwise.

CORSO's destination is an institutional multi-asset Investment Operating System for the USA and
Mexico across Equity and Fixed Income. Its economic objective is to minimize the probability and
magnitude of permanent capital loss while seeking sustainable, robust and monetizable alpha
subject to risk. It makes no return, hit-rate or loss-elimination promise.

The decision flow is:

```text
data -> information -> research -> investment intelligence -> risk understanding
     -> portfolio decision support -> human decision -> external execution
```

Production execution remains external and `HUMAN_ONLY`.

Future Engine/Ledger work may consume GBM facts only through the deferred, versioned Broker
Execution Profile and `HUMAN_VALIDATED_MANUAL_ENTRY` / `MANUAL_STRUCTURED_INPUT` Data Intake
contract defined by ADR 0023. It must preserve exact fractional quantities, original currency,
separate execution/settlement timestamps, observed fees/tax/events, linked corrections, lots under
`corso_lot_id`, provenance and manual-assisted reconciliation. Broker-specific executability and
metadata never become universal model-eligibility rules. No ledger or Data Intake is implemented
or authorized here.

## Governing principles

1. `Signal != Risk != Confidence != Position Size`.
2. Complexity must earn its existence through economic rationale and robust evidence.
3. Point-in-time correctness precedes apparent alpha.
4. `Net Alpha > Gross Alpha`: costs, capacity, liquidity and taxes cannot be ignored.
5. Confidence must empirically predict confidence or be simplified/removed.
6. Research degrees of freedom, challengers and changes must be governed.
7. Missing or incomplete facts produce explicit exclusion/review states, never invented data.
8. Research output is not an execution instruction.
9. Reuse sound foundations; introduce and govern only necessary new complexity.
10. Documentation, schemas, interfaces and fixtures do not constitute a functioning REAL engine.

## Target architecture

```text
                        Governed Data Core
           identity / PIT / provenance / lineage / versions
                         /                    \
                Equity Engine           Fixed Income Engine
                         \                    /
                    Cross-Asset Intelligence
                 issuer / macro / FX / liquidity
                              |
                    future Portfolio Engine
                              |
                    human-reviewed candidates
                              |
                 human-only external execution
```

The Portfolio Engine remains separate and future until explicitly authorized. It must not be
smuggled into either asset engine.

## Governed Data Core

Equity and Fixed Income share infrastructure where economically appropriate: Security Master,
Issuer Master, stable instrument and listing identity, CUSIP/ISIN where licensed and applicable,
currencies, PIT FX, timestamps, calendars, corporate/debt actions, prices, curves, accounting
observations, issuer mapping, data-quality states, provenance, lineage, fingerprints and source
versions. `Security != Issuer`; identity is never ticker-only.

Temporal fields include, where applicable, `effective_at`, `available_at`, `as_of`, `ingested_at`,
`source`, `source_version`, `lineage` and `fingerprint`. Historical admission requires
`available_at <= as_of`. Corrections and restatements preserve their own temporal identity.

Content-addressed dependencies should support selective incremental recomputation: a new filing
may affect accounting and related Equity dimensions without recalculating unrelated bond cash
flows; a new curve may affect FI valuation and risk without recalculating Equity Quality. This is a
target design property, not a claim of current implementation.

## Equity target

Equity remains the primary alpha-research track. Its target output is a research case that keeps
these dimensions distinct:

- Quality: profitability, cash conversion, persistence/stability and financial safety;
- Value: economically appropriate yields and valuation diagnostics without duplicate information;
- Momentum: governed baselines such as 12–1 and volatility-adjusted 12–1;
- Fundamental Context: growth quality, reinvestment, capital allocation and competitive economics;
- Expectations: reverse valuation/implied expectations, initially diagnostic rather than a
  pseudo-precise target price;
- Capital Loss: balance-sheet, liquidity, deterioration, accounting, capital-structure and event
  risk, with clear `PASS / REVIEW / BLOCK` semantics; and
- Confidence: observable data quality, coverage, agreement and stability, distinct from expected
  return and position size.

QVM is the initial attractiveness framework and equal weighting may remain its benchmark unless a
governed alternative earns admission. CORSO must not collapse all information into an arbitrary
monolithic score. Metric families must be economically appropriate for normal corporates, banks,
insurance, REITs/FIBRAs, utilities and specialized structures.

Equity admission requires a Data Reality Gate: canonical identity, no PIT violation, complete
critical Q/V/M inputs for an admitted security, no silent critical imputation, resolved material
corporate actions, valid freshness, full provenance/lineage and reproducible historical snapshots.
Raw-universe coverage may be incomplete; admitted-security integrity may not be.

Signal admission and model research require true out-of-sample evaluation, a factor benchmark,
after-cost/capacity analysis and controlled degrees of freedom. Machine learning is a challenger
only after it earns existence against simpler baselines; it is never the automatic default.

## Fixed Income strategic track

Fixed Income is an **ACTIVE SECONDARY DEVELOPMENT TRACK** in roadmap priority and direction. This
replaces the interpretation that it is an indefinite future idea, but does not claim an FI engine
exists and does not authorize implementation outside a separately approved work.

The first target foundation is deliberately narrow:

```text
US investment-grade corporate bonds
USD / fixed-rate / bullet / non-callable / non-puttable
```

Its target capabilities are deterministic contractual cash flows; settlement and day-count
conventions; accrued interest; clean and dirty price; YTM; governed reference and risk-free curve
inputs; G-spread; duration, modified duration, DV01 and convexity; basic issuer credit, relative
value and confidence outputs; and explicit validation gates and numerical tolerances. Clean price
is not dirty price, and coupon is not dividend.

Validation must include independently calculated examples, edge cases, convention checks,
reconciliation to governed references where legally available, PIT/provenance controls and
documented tolerances. A plausible number is not sufficient evidence.

Later, separately authorized phases may add advanced curves/spreads and optionality, credit
intelligence, capital structure/recovery, scenario analysis and complex FI. Existing Mexico scope
is preserved as a future target, including CETES, Bonos M and Udibonos; nominal versus real basis;
benchmark/reference versus risk-free distinctions; recovery assumptions, recovery hierarchy,
LGD and expected loss; and instrument-appropriate currency, inflation and tax treatment.

## Cross-asset issuer intelligence

The shared issuer layer should eventually connect an issuer's equity fundamentals with its debt,
capital structure, liquidity, refinancing and recovery context without forcing comparable scores.
Cross-asset evidence must preserve security-level facts, issuer aggregation, source boundaries and
time. Equity attractiveness must not silently become bond credit quality, or vice versa.

## Build-versus-buy and governance

Each material capability requires a governed build-versus-buy decision considering licensing,
methodological control, PIT availability, coverage, auditability, cost, maintenance and operational
risk. Connectivity is not entitlement, trust, admission or permission to use data.

Models and material analytics require model cards, owner, intended use, applicability limits,
inputs, versions, validation evidence, known failure modes and change history. Admission decisions
use explicit `GO / REMEDIATE / NO-GO / STOP` outcomes. Changes that expand scope or risk require
new authorization; documentation cannot activate them.

## Development sequence and Step 6 precedence

Target development direction:

1. transition audit and canonical scope alignment;
2. Equity V1;
3. Equity Shadow plus a minimal research UI;
4. FI Foundation in parallel while Equity Shadow accumulates temporal evidence;
5. FI validation;
6. full institutional dashboard;
7. advanced asset engines; and
8. future Portfolio Engine.

This sequence is subordinate to the current safety/governance prerequisites. Step 5 is `CLOSED`.
Step 6 remains **STARTED — FOUNDATION ONLY; NO GATES CLOSED**. No Equity REAL/shadow use, FI REAL
implementation, governed backtesting or portfolio work may bypass external gates, provider
admission, PIT/data governance or a separate authorization. The machine-readable current
`NEXT_BLOCK` remains authoritative.

## Current truth boundary

- 10/10 gates: `OPEN_EXTERNAL`;
- REAL dependencies: `NOT_PROVISIONED` where stated by current governance;
- REAL route: `QVM_NOT_READY`;
- readiness: `INSUFFICIENT_REAL_DATA`;
- `trade_decision=NO_TRADE` and `signals_generated=false`;
- `execution_authority=HUMAN_ONLY`, `human_execution_required=true`,
  `live_execution_enabled=false`;
- backtesting and portfolio construction: `NOT_AUTHORIZED`; and
- Equity/FI target expansion in this document: `NOT_IMPLEMENTED`.
