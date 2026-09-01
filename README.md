# Trading

Systematic Equity Research & Portfolio Engine built with a capital-preservation-first mandate.

Phases 6 and 7A/7B/7C/7D/7E/7F are integrated; Phase 7F was squash merged as PR #25.
**Phase 7G — Governed External Provisioning Foundation** is proposed in draft form as a
contract-test-only boundary in
[`docs/adr/0002-phase7g-governed-external-provisioning.md`](docs/adr/0002-phase7g-governed-external-provisioning.md).
It builds on the Phase 7F architecture in
[`docs/adr/0001-phase7f-external-trust-boundary.md`](docs/adr/0001-phase7f-external-trust-boundary.md).
It implements only synthetic, governed contract mechanics. Its typed authority registry,
trust-anchor registry, policy, scope, reviewer registry, custody record and independent audit can
prove that a synthetic chain is internally consistent; they cannot prove external authenticity,
WORM/object lock, real reviewer appointment, provider approval or evidence truth. No REAL trust
root or caller-injectable resolver is implemented. Every sensitive input is revalidated from
primitive snapshots and every semantic hash is recomputed. The versioned
`phase7f-admission-temporal-order-v1` policy requires custody availability before retrieval,
retrieval before maker-checker decision, decision before audit, and audit no later than verifier
time. Authorities, anchors and reviewer identities are checked at their historical use time and
again at verifier time, with no grandfathering. Equality is allowed only at the documented causal
boundaries. Phase 7G selection is explicitly neither approval nor admission. External authority
and object-lock verification remain unprovisioned, and all ten real-data gates remain
`OPEN_EXTERNAL`. Phase 7G enforces its own versioned selection-to-evaluation chronology.
Gate-specific envelopes, custody receipts and candidates are matched by gate identity, not
collection position; structured credential capabilities and the complete contractual state chain
are revalidated by the aggregate. Hash agreement remains internal consistency, never WORM or
trust.
Phase 7G uses a code-owned, versioned contract-test manifest to bind every gate to its expected
source/provenance/evidence policy and exact custody bucket/object/version/digest. This prevents
fully re-sealed cross-gate package swaps but does not verify external custody or WORM. Credential
DTOs contain only a non-reversible SHA-256 identity and non-sensitive binding metadata; reversible
locators and secret material remain outside auditable models and hashes. The digest does not prove
credential validity or authentication. Authority remains `NOT_PROVISIONED`; 10/10 gates remain
`OPEN_EXTERNAL`.

## Current stage

Phase 6's research-only QVM scoring engine and the Phase 7A–7F contractual foundations are merged.
Phase 7E formalizes evidence requirements and Phase 7F models the synthetic trust seam. Draft
Phase 7G adds governed provider/dataset selection and external-provisioning candidate contracts,
without approval, admission or REAL verification. Phase 7F admission mechanics complete only when
a canonical independent auditor—distinct from
maker and checker and valid at audit and verifier time—approves a hash of the complete revalidated
snapshot, including chronology, verifier time and temporal-policy version. Reviewer aliases use
Unicode NFKC, whitespace folding and casefold collision detection; this is not universal homoglyph
detection, while canonical actor IDs are constrained opaque ASCII identifiers. Declared scope
dimensions and custody immutability fields remain declarations, never proof. No real historical
provider is admitted. The real route is
`QVM_NOT_READY`, global readiness is
`INSUFFICIENT_REAL_DATA`, and backtesting is `NOT_AUTHORIZED`. All paths remain `NO_TRADE`, with
signals and live execution disabled; no portfolio, target-price, broker, order, execution, or
dashboard/Excel capability is authorized.

The PRE-Phase 6 boundary admits only sealed `GovernedFactorBatch` objects. The packages
`execution/`, `portfolio/`, `backtesting/`, `risk/`, and `database/` are placeholders, not
implemented capabilities.

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

Alpha Vantage has two deliberately separate V1 paths. The operational `PriceSource` uses
`TIME_SERIES_DAILY` with compact output for EOD ingestion. The independent
`MomentumHistoricalPriceSource` uses `TIME_SERIES_DAILY_ADJUSTED` with `outputsize=full`; that
historical adjusted dataset requires premium Alpha Vantage access. The dependency is exposed in
source metadata rather than hidden inside the general EOD adapter.

The historical source retains raw and adjusted closes, provider split/dividend fields, access tier,
dataset version, and lineage. Corporate-action coverage is described narrowly as **provider
corporate actions captured + adjusted/raw relationship validated**; there is no independent
corporate-action source. CSV remains deterministic for tests and offline validation. Momentum
accepts only provider-adjusted prices; raw prices cannot drive Momentum metrics.

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

Each snapshot records the complete versioned ruleset, filter parameters, recording timestamp,
configured rebalance frequency, snapshot date, next expected date, and checksums for both membership
and validation artifacts. The initial schedule is monthly configuration, not hard-coded scheduling
logic. Universe completeness is named `universe_confidence`; financial data confidence remains a
separate contract and cannot determine universe eligibility.

Phase 7 SEC ingestion does not use manually supplied ticker examples as its production universe.
Its governed boundary requires the immutable PIT universe snapshot to carry permanent identities,
then resolves those identities through explicit PIT security-master records to canonical CIKs. The
security-master provider remains external/open, so this is a fail-closed contract rather than a
claim of real-data readiness. See `docs/phase7_real_data_ingestion.md`.

Run a reproducible universe validation for a specific point in time with:

```bash
universe-validate \
  --source tests/fixtures/universe.csv \
  --as-of 2026-08-20 \
  --config config/settings.example.yaml
```

This writes an auditable run under `validation_outputs/<run_id>/` and an immutable snapshot under
`universe_snapshots/<date>/`. Future Quality, Value, and Momentum input schemas are defined in
`factors/contracts.py`; they contain required observations and lineage only, with no factor
calculation, score, rank, signal, or portfolio behavior.

## Phase 4.0 research environment foundation

Phase 4.0 turns a research idea into a governed, reproducible record before any QVM implementation.
Each registry entry identifies the hypothesis and experiment version, creation and preregistration
times, governed universe snapshot and ruleset, analysis period, metrics to evaluate, expected and
observed results, `KEEP`/`DISCARD`/`REVIEW` decision, immutable dataset snapshots, checksums, and
complete lineage. Existing legacy preregistrations remain readable, but Phase 4 execution requires
the complete contract and a `REGISTERED` or `READY` state.

Every dataset is identified by a logical dataset ID, snapshot ID, SHA-256 digest, path, and lineage.
The runner verifies the bytes before use. A mismatch fails by default so revised data cannot silently
change an experiment; an explicit `--dataset-mismatch warn` policy records the mismatch and degrades
health to `WARNING`.

Run a registered experiment reproducibly with:

```bash
research-run \
  --registry research/registry.jsonl \
  --experiment-id foundation-001 \
  --experiment-version 1.0
```

The command writes an immutable `research_config.json` and `research_run.json` beneath
`research_outputs/<experiment>_<version>_<fingerprint>/`. The run records base dataset metrics,
warnings/errors, health, expected versus observed result, decision, and lineage. Its fingerprint is
derived only from the registered experiment, exact dataset bytes, and runner version, so identical
inputs produce identical content and the same output location.

The factor research framework in `research/contracts.py` defines future input, output, metric, and
evaluation boundaries only. To promote a hypothesis later, researchers must preregister it, freeze
the governed universe and datasets, reproduce the foundation run, implement a factor in a separately
authorized phase, evaluate the preregistered metrics out of sample, record the observed result, and
make an explicit `KEEP`, `DISCARD`, or `REVIEW` decision. Phase 4.0 itself performs no Quality,
Value, Momentum, score, rank, portfolio, backtest, broker, order, or execution calculation. Every
research run remains `NO_TRADE` with `live_execution_enabled: false`.

## Phase 4.1 Quality Factor Engine V1.1

Phase 4.1 implements the first research-only QVM component: Quality. Its hypothesis is that durable
returns on invested capital, cash-backed earnings, stable margins, and prudent leverage describe
operating quality. This phase measures those attributes separately; it does not claim that they
predict returns and does not combine them into an investment score.

The engine accepts only immutable, checksum-verified datasets registered by the Phase 4 Research
Environment. Its primary input is the auditable `financial_metrics.csv` contract produced by
Financial Intelligence, including upstream status, reason, confidence, and input lineage. An
upstream `MISSING`, `NOT_COMPUTED`, low-confidence result, conflict, or PIT violation remains visible
and cannot become a passing Quality observation. Missing or null confidence is
`MISSING_CONFIDENCE`; malformed or out-of-range confidence is `LOW_CONFIDENCE`. The output keeps
data, calculation, and economic confidence separate and uses their conservative minimum as the
row-level confidence. Corrupt, empty, or source-free lineage becomes `INVALID_LINEAGE` rather than
being silently repaired.

Quality V1 emits these individual measurements:

- ROIC V1: reported-period NOPAT divided by invested capital.
- ROIC stability: population standard deviation of at least two comparable historical ROIC values.
- FCF margin: reported-period free cash flow divided by revenue.
- CFO conversion: cash from operations divided by net income.
- Net Debt / EBITDA when EBITDA is positive and the upstream metric is available.
- Accrual quality: `(Net Income - CFO) / Total Assets`, when supplied by the validated accounting
  quality output.
- Margin stability: population standard deviation of at least two comparable historical FCF
  margins.
- ROIC and FCF consistency, positive-period counts, and margin persistence as separate historical
  measurements, never as a composite score.
- Optional share-count change and reinvestment-rate observations as capital-allocation foundations.
  M&A remains a documented placeholder with no inferred metric.

Sector and industry labels plus optional precomputed relative percentiles are preserved for future
normalization. V1.1 does not calculate cross-sectional percentiles, rankings, or scores. Each output
also exposes the primary source, source availability time, source fiscal-period end, and PIT metadata.
Extreme but mathematically valid ROIC remains available with a warning. Contradictions such as high
ROIC alongside elevated leverage or deteriorating margin persistence emit explanatory warnings;
they do not change a metric into a score or automatically block it.

Standard deviation is an unweighted dispersion statistic, not a score: lower dispersion may
describe stability, but V1 assigns neither a preferred direction nor a weight. Negative ROIC, FCF
margin, CFO conversion, leverage (net cash), or accrual values can be economically meaningful and
are retained when mathematically valid. Non-finite values, invalid upstream domains, duplicate or
conflicting observations, incompatible period bases, insufficient history, and incomplete schemas
produce explicit non-passing statuses and reasons.

Run a registered Quality experiment with:

```bash
quality-research-run \
  --registry research/registry.jsonl \
  --experiment-id quality-001 \
  --experiment-version 1.0 \
  --assumption "Only like-for-like reporting periods are compared"
```

The immutable output directory contains `quality_metrics.csv` and
`quality_research_run.json`. Every metric row includes `value`, `status`, `reason`, data
`confidence` components, sector/industry context, warnings, primary-source fields, PIT metadata, and
complete dataset/input `lineage`. The run records experiment, dataset and universe
snapshots, universe and Quality ruleset versions, assumptions, reproducibility fingerprint, and
factor health.

V1.1 limitations are intentional: it does not calculate sector rankings, annualize partial periods, impute
missing facts, select thresholds, assign weights, calculate a composite score or rank, evaluate
forward returns, construct a portfolio, run a complete backtest, connect a broker, or execute.
Value and Momentum remain outside this Quality phase. Every output stays `NO_TRADE` and
`live_execution_enabled: false`.

## Phase 4.2 Value Factor Engine V1

Phase 4.2 adds a conservative research-only Value layer with individual FCF Yield, Earnings Yield,
EBIT Yield, EV/EBIT, and secondary EV/EBITDA metrics. Absolute Value is calculated independently;
historical and sector-relative Value remain metadata foundations. Invalid currency, units, periods,
PIT timestamps, confidence, lineage, denominators, or restricted industries fail closed. Negative FCF
or earnings, negative EBIT, and economically extreme valuations are warnings, never normal signals.
Value execution requires a verified Phase 3.6 universe snapshot whose identity, ruleset, checksums,
health, and research-only safety state match the registered experiment. The reproducibility
fingerprint covers the dataset, governed universe, contract, experiment, assumptions, and runtime
dependency versions.

The engine does not calculate a composite score, ranking, portfolio, or trade. Owner Earnings Yield
and Quality linkage are explicitly reserved for future work. See
[`research/VALUE_VALIDATION.md`](research/VALUE_VALIDATION.md) for contracts, limitations, and output
definitions. Every Value run preserves `NO_TRADE` and `live_execution_enabled=false`.

## Phase 4.3 Momentum Factor Engine V1.1

Phase 4.3 calculates research-only 12-1, six-month, relative-strength,
volatility-adjusted, and trend-stability observations from adjusted prices. Windows use market
sessions (252/21 and 126), volatility uses daily log returns and calendar-configured annualization,
and expected sessions are compared with observed sessions. Corporate actions, staleness, PIT,
confidence, lineage, and asset/benchmark basis, calendar, and timing compatibility fail closed.

The runner writes `momentum_metrics.csv`, `momentum_health.json`, `momentum_lineage.json`, and
`momentum_validation_report.json`. See
[`research/MOMENTUM_VALIDATION.md`](research/MOMENTUM_VALIDATION.md) for the completed market-data
audit and remaining safety boundary. No score, rank, QVM, portfolio, backtest, signal, or execution
is produced; `NO_TRADE` and `live_execution_enabled=false` remain mandatory.

### Phase 5.5.2 — FX and currency governance

`data/fx.py` defines a provider-neutral, typed FX dataset boundary with distinct market and
availability timestamps. Snapshots and conversions are point-in-time validated, content-addressed
with a canonical checksum, staleness checked, and linked to their upstream lineage. The versioned
`fx-weekday-sessions-utc-v1` policy counts Monday-Friday UTC dates after a fixing through the
reference date and deliberately infers no holiday calendar; its session limit and reciprocal-rate
tolerance are stored with dataset metadata. The selected fixing is checked again at conversion
time, and simultaneous direct/inverse rates must reconcile within that governed tolerance.
Historical
conversion selects only a rate whose market timestamp is no later than the requested historical
instant and whose availability timestamp is no later than the research cutoff; ambiguity or missing
currency fails closed. Identity conversion is explicitly marked and carries no synthetic fixing
timestamp or FX lineage. This layer creates no scores, rankings, weights, signals, portfolios,
backtests, or execution behavior. `NO_TRADE` remains active and `live_execution_enabled=false`.

### Phase 5.5.3 — Accounting PIT and restatement governance

`fundamentals/governance.py` defines the typed, provider-neutral boundary for financial facts and
keeps fiscal period, filing time, and public availability time separate. Complete revision chains
are retained: an original fact starts at revision zero, every restatement explicitly supersedes the
prior revision, and snapshots select only the latest revision known at their requested cutoff.
Future filings or availability, invalid chronology, duplicate facts, revision gaps, provider
metadata mismatches, missing required fundamentals, and checksum mutations fail closed.

Accounting history is content-addressed with a canonical checksum that is independent of row order.
Dataset identity, contract version, missing-data policy, source version, and upstream lineage are
immutable metadata, so historical snapshots remain reproducible and later restatements cannot
silently rewrite them. This governance layer creates no scores, rankings, weights, signals,
portfolios, backtests, or execution behavior. `NO_TRADE` remains active and
`live_execution_enabled=false`.

### Phase 5.6 — Cross-layer governance integration

`governance/integration.py` admits a verified Universe Snapshot plus market data, FX, and accounting
history through one fail-closed point-in-time boundary. Eligible symbols are materialized only from
the checksum-verified snapshot under `exact-eligible-set-v1`; callers cannot supply a replacement
set. The gate requires one shared timezone-aware cutoff, selects the accounting revision known at
that cutoff, and translates
monetary facts to the configured research currency using only the governed fiscal-period-end FX
observation. Non-monetary units are preserved without inference.

`explicit-market-cap-currency-v1` requires every Universe market cap to carry its own governed
ISO currency; price currency is never used as a proxy. Non-base market caps require a governed FX
fixing with complete conversion lineage. Base-currency market caps record an explicit identity
conversion with no synthetic fixing. Enterprise value is formed only after market cap, debt, and
cash are comparable in the configured base currency.

Accounting duration facts carry their explicit fiscal start and end through
`accounting-period-semantics-v1`; no calendar-year start is manufactured. The fingerprinted
`value-fy-flow-and-period-end-instant-v1` policy chooses the latest complete eligible FY at the
valuation cutoff, requires all flow inputs from that exact duration period, and requires cash and
debt instants at its period end. Quarters, incompatible periods, and duplicate temporal identities
are never mixed and fail closed when they make selection ambiguous.

The immutable output bundle binds all upstream canonical IDs and checksums to the exact market,
accounting, and conversion snapshots with a deterministic cross-layer fingerprint. Missing required
fundamentals, entity or currency disagreement, future availability, stale FX, unsupported contracts,
or post-governance mutation fails closed. `unit-ontology-v1` classifies monetary and non-monetary
units explicitly, while `cross-layer-temporal-alignment-v1` preserves the distinct Universe,
market-session, FX-weekday, and accounting-availability policies without inventing an FX holiday
calendar. `governance/research_chain.py` is the only Phase-6-eligible path: it seals Quality, Value,
and Momentum batches to the same cross-layer fingerprint and QVM verifies every upstream identity
against the expected manifest. Direct factor/QVM APIs remain `research_legacy` and explicitly
`phase6_eligible=false`.

This phase creates no score, weights, rank, signal,
portfolio, backtest, broker action, or execution. `NO_TRADE` remains active and
`live_execution_enabled=false`.

## Safety

This repository is not authorized for unattended live trading. Live execution is a later gated phase after research, backtesting, paper trading, reconciliation, and operational validation.
