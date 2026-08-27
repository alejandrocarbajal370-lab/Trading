# Phase 7D — Governed confidence, FX PIT, and QVM admission foundation

Status: **CONTRACT-CLOSED / REAL-DATA-OPEN / QVM_NOT_READY**. This is research-only work.
It does not authorize backtesting, signals, portfolio construction, orders, or execution. Every
artifact retains `trade_decision=NO_TRADE`, `live_execution_enabled=false`, and
`signals_generated=false`; global readiness remains `INSUFFICIENT_REAL_DATA`.

## Governed confidence

`governed-confidence-evidence-v1` replaces declarative floats at the SEC Accounting boundary with
sealed components: `data_confidence`, `mapping_confidence`, and `calculation_confidence`.
`economic_confidence` is optional and may only be present with legitimate evidence. Each scored
component binds a source, record identity, version, evidence type, evidence reference hash, reason
code, and its own content hash. Missing evidence produces `UNKNOWN`; it never produces a default.

The aggregation policy is the minimum of all required controls. The `0.80` boundary means only
"at least 80% under a deterministic contractual-control rubric." It is **not empirical or
predictive confidence**, has not been calibrated against returns, and must not be described as such.
A score of `1.0` is possible only when every explicitly evidenced deterministic control reports
complete satisfaction; it is not a claim of economic certainty. Mutated evidence or an outer proof
is rejected as stale.

## FX PIT

The repository already had the provider-neutral `fx-governance-v1` dataset with base/quote,
market timestamp, knowledge time, source/dataset lineage, content identity, staleness policy, PIT
cutoff, and finite positive rates. Phase 7D adds `fx-exact-direct-no-fill-v1` at the Value boundary:

- same-currency conversion is an explicit identity;
- cross-currency conversion requires an exact direct governed observation;
- no implicit inverse, triangulation, forward fill, pair heuristic, or stale/future observation;
- conversion evidence is sealed to both FX and Accounting identities.

No licensed, retention-approved, operational historical FX provider is established in this phase.
Fixtures validate the contract only. Provider status is therefore `OPEN-EXTERNAL`.

## Metric sufficiency

The sealed `qv-metric-sufficiency-v1` matrix is included in adapter and admission proofs.

| Factor | Can be formed from current canonical metrics | Still blocked |
|---|---|---|
| Quality | FCF margin, CFO conversion; raw accrual ratio as diagnostic, subject to complete periods and governed confidence | ROIC (EBIT/tax/debt), leverage (debt/EBITDA), shares history, adequate history for stability |
| Value | FCF and earnings numerators | governed market cap, EV, exact EBIT, EBITDA, FX comparability |

`operating_income` is not EBIT. There is no EBITDA, debt, shares, market-cap, or EV proxy. Missing
required inputs remain `MISSING_REQUIRED` or `DEFERRED_UNMAPPED`; they are never filled or zeroed.
Sector applicability is evaluated by the existing governed policy before Phase 6 admission, and
`NOT_APPLICABLE` is not treated as `PASS`.

## Accounting adapters and admission V3

`accounting-qv-adapter-v1` accepts only the exact `AccountingDataset` type, reconstructs its
checksum/canonical identity, verifies the confidence proof binding, takes a PIT snapshot, and emits
per-factor/per-metric states sealed to Accounting, confidence, and the sufficiency matrix. Legacy
DataFrames cannot enter this boundary.

`qvm-real-data-admission-v3` verifies Accounting, confidence, required-metric states, FX proof when
cross-currency Value is used, provider readiness, sufficiency identity, runtime identity, and exact
governed Q/V/M batches. Only after these gates are clear does it call the existing Phase 6 V2
admission. It never reimplements scoring. Any unresolved dependency returns `QVM_NOT_READY` with
reasons and does not create a Phase 6 admission artifact.

The hashed readiness vocabulary is `RAW_INGESTED -> CANONICAL_MAPPED -> ACCOUNTING_BOUND ->
CONFIDENCE_BOUND -> FX_BOUND` (when needed) `-> FACTOR_INPUTS_PARTIAL -> QVM_NOT_READY` or
`QVM_ADMISSIBLE`. A state proof requires prerequisite hashes; an enum value or locally resealed
declaration is not upstream evidence.

## Closure ledger

| Area | State |
|---|---|
| Confidence evidence/aggregation contract | CONTRACT-CLOSED |
| SEC-derived deterministic confidence production | PARTIAL; evidence must be supplied per run |
| FX dataset and exact-direct use contract | CONTRACT-CLOSED |
| Real historical FX provider/legal/retention/operations | OPEN-EXTERNAL |
| Q/V sufficiency and Accounting adapter | CONTRACT-CLOSED |
| Quality from real complete periods | PARTIAL |
| Value denominators and currency-comparable real inputs | OPEN-EXTERNAL |
| Momentum provider confidence/readiness | PARTIAL / unchanged |
| Shares PIT, restatement materiality, corporate-action economics | OPEN-EXTERNAL |
| Complete Q/V/M real-data admission | QVM_NOT_READY |
| Global real-data readiness | INSUFFICIENT_REAL_DATA |

An independent integral and adversarial audit is required before merge. Even a future successful
research-only admission remains `NO_TRADE` and does not authorize any downstream trading activity.
