# Phase 7A — governed SEC real-data ingestion foundation

Status: **SEC RAW CONTRACT-CLOSED; REAL-SEC VALIDATION REQUIRED; NOT QVM-BOUND**.
The research-only invariants remain `trade_decision=NO_TRADE`,
`live_execution_enabled=false`, and `signals_generated=false`. Backtesting is not authorized.

## Closed contract surface

The SEC transport is HTTPS-only and allowlisted to `data.sec.gov`, validates redirect targets,
status, JSON media type, encoding, and response size, and supports gzip and both deflate formats
without double-decoding already-decoded bytes. Policy `sec-fair-access-http-v2` applies a monotonic
minimum interval before every attempt (including history and retries), uses a bounded timeout and
retry budget, and honors bounded `Retry-After` values for 429/5xx responses. The identified
non-placeholder `User-Agent` remains mandatory.

CIKs are caller-supplied, canonicalized, and validated; there is no ticker inference. Acceptance
timestamps, never `filed`, determine PIT availability. Missing/null/invalid/naive acceptance values
fail closed by default. Observations after `as_of` are explicitly excluded; a future-only result is
reported as such and fails closed. The exact cutoff boundary is inclusive.

Accession joins and XBRL facts use one validated canonical 10-2-6 SEC identity, accepting the
equivalent 18-digit wire form without inferring missing digits. Identical duplicates deduplicate;
conflicting duplicates fail closed. Fact identity includes taxonomy, concept, unit, form, accession,
start/end and frame, distinguishing duration from instant contexts. Taxonomy coverage remains
explicit (`us-gaap`, `ifrs-full`, `dei`, `srt`, `custom/other`); `dei` is not eligible for automatic
economic mapping. Units such as USD, CNY, SHARES, and PURE remain distinct.

The local raw store separates immutable content identity (SHA-256) from acquisition events. Every
fetch is intentionally a distinct acquisition event; identical bytes reuse the content SHA and
blob. Each event records both economic/PIT `as_of` and real `acquired_at`. Publication uses flushed temporary
files and conflict-safe atomic linking, so re-fetching identical bytes creates a new event while
reusing content. Checksums detect mutation. This is logical local-FS immutability, **not WORM,
object lock, legal hold, or production-grade distributed concurrency**.

Historical SEC references are path-allowlisted and fetched individually without bursts. Required
parallel columns (`accessionNumber`, `acceptanceDateTime`, `filingDate`, `form`) must all exist and
have identical lengths. Declared `filingCount`, `filingFrom`, and `filingTo` must match row bounds;
missing, ambiguous, or inconsistent schema/metadata is conservatively `GAPS_DETECTED`, never
complete. Status is
`COMPLETE_WITHIN_SEC_REFERENCES`, `GAPS_DETECTED`, or unknown/failure; this never claims exhaustive
issuer history beyond SEC's references. For broad coverage, evaluate SEC bulk archives
`companyfacts.zip` and `submissions.zip`; this PR does not claim 5,000-security scale.

## Deliberate boundaries

Forms retained include 10-K/Q, 20-F, 40-F, 6-K and amendments. Foreign issuer reporting,
taxonomy, currency, comparability, and 6-K/40-F availability differ materially from domestic
issuers. `amendment_observed=true` records `/A`; it does **not** infer restatement materiality.
RESTATEMENTS therefore remains `OPEN-EXTERNAL`.

Raw facts always carry `confidence=None`. No SEC response establishes governed economic confidence.
There is no broad concept mapping and no `AccountingDataset` or QVM binding. Every result exposes
`INGESTED_NOT_QVM_BOUND`; `dei` and custom concepts cannot silently enter Fundamentals/QVM.

Legal approval is project-specific and remains `PENDING_LEGAL_APPROVAL` with
`licensed_for_use=false` by default. Retention text is metadata, not legal advice or approval.

## OPEN-EXTERNAL and aggregate readiness

- Fundamentals PIT → Accounting/QVM: economic mapping, governed confidence, coverage and sealed
  binding remain open.
- FX, security master/historical constituents, authoritative restatement resolution, corporate
  actions, and governed shares-outstanding PIT sources remain open.
- Legal approval, production WORM/object-lock storage, distributed locking, bulk-scale operations,
  and full historical completeness remain open.

Consequently global readiness remains `INSUFFICIENT_REAL_DATA`. Provider declarations such as
`real_data=true` or `licensed=true` without verified snapshots and bindings do not change the gate.
