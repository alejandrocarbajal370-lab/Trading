# Phase 7C — SEC canonical fundamentals and Accounting binding

Phase 7C is a contractual/research-only foundation. It does not enable signals,
backtesting, portfolio construction, orders, or live execution. Global readiness is
`INSUFFICIENT_REAL_DATA` and every emitted decision remains `NO_TRADE`.

## Evidence chain

`Phase 7B permanent security identity → issuer/CIK acquisition plan → immutable SEC
submissions + Company Facts snapshots → hashed exact-concept mapping registry →
issuer-level canonical facts → governed AccountingDataset`

The Accounting consumer requires a `RawSnapshotStore`; a DataFrame and declarative
manifests are never evidence. Every acquisition event is reopened, its payload bytes
are length/SHA verified, and its manifest must exactly equal the declared manifest.
Company Facts are reparsed and compared field-for-field with the incoming canonical
rows. Accession, form, and `acceptanceDateTime` are independently rejoined from verified
recent/historical Submissions. Missing bytes, a wrong CIK/resource, duplicate chronology,
or any locally resealed mutation fails closed.

The resulting `phase7c-raw-proof-v2` envelope commits to the acquisition-plan hash,
physical raw-manifest identities, canonical selection hash, Company Facts and Submissions
content, mapping and unit registries, form-period policy, as-of cutoff, issuer identity,
accession/revision chain, and runtime fingerprint. Its hash is embedded in every
Accounting row and Accounting lineage. A coherent new raw acquisition produces a new
proof and Accounting identity; old commitments cannot be reused.
Every Company Facts, recent Submissions, and historical Submissions manifest must have
an `as_of` exactly equal to the plan/binding cutoff under
`sec-raw-temporal-exact-cutoff-v1`. `acquired_at` remains a separate acquisition event
time and need not equal the cutoff. Old, future, or mixed raw cutoffs fail closed.
Issuer facts are stored once. Multiple share classes appear only in the applicability
lineage and never cause duplicated economics.

## Versioned contracts and minimal metric scope

- mapping registry: `sec-canonical-fundamentals-v2`
- raw proof: `phase7c-raw-proof-v2`
- unit/currency registry: `sec-unit-currency-registry-v1`
- raw temporal policy: `sec-raw-temporal-exact-cutoff-v1`
- form-period policy: `sec-form-period-policy-v2`
- Accounting adapter: `sec-accounting-binding-v3`

Legacy Phase 7C v1 registries/adapters are incompatible and fail validation; they are
not silently reinterpreted.

Exact `us-gaap` mappings:

- `Assets → total_assets` (instant, currency)
- `CashAndCashEquivalentsAtCarryingValue → cash` (instant, currency)
- `NetCashProvidedByUsedInOperatingActivities → cash_from_operations` (duration, currency)
- `NetIncomeLoss → net_income` (duration, currency)
- `OperatingIncomeLoss → operating_income` (duration, currency)
- `PaymentsToAcquirePropertyPlantAndEquipment → capital_expenditures` (duration, currency)
- `RevenueFromContractWithCustomerExcludingAssessedTax → revenue` (duration, currency)
- `Revenues → revenue` (duration, currency)
- `StockholdersEquity → total_equity` (instant, currency)

`operating_income` remains a distinct reported metric and is **not** asserted to equal
EBIT. `total_equity` is retained but is not presently consumed by QVM.

Everything else is explicitly `UNMAPPED`, including custom concepts, `dei` metadata,
IFRS concepts without a registered equivalence, EBITDA, tax rate, shares, total debt,
market cap, enterprise value, and debt tags with different economic scope. No label, substring,
statement-role, ticker, or unit heuristic creates a mapping.

## Selection and period policy

- Knowledge time is SEC `acceptanceDateTime`; missing, naive, or future acceptance fails.
- Instant and duration semantics must exactly match the registry. The same hashed
  form/fp matrix is enforced for both: annual forms allow only `FY`; `10-Q` forms allow
  only `Q1`/`Q2`/`Q3`, including instant facts.
- Duration start/end are mandatory; instant facts forbid a start. `10-K`/`10-K/A` and
  supported `20-F` forms require `FY` and 330–400 days. `10-Q`/`10-Q/A` forbid `FY`;
  Q1 allows `QUARTER` at 60–120 days. Q2 and Q3 classify 60–120 days as `QUARTER` and
  121–210/300 days respectively as `YTD`, so discrete-quarter and SEC YTD presentations
  remain explicit and have distinct canonical identities. `6-K` and `40-F` receive no automatic fiscal semantics.
  Non-calendar fiscal years are preserved unchanged. Form and acceptance are revalidated
  from Submissions, never trusted from the canonical row.
- Duplicate accessions never collapse, even when their rows are identical. Canonical
  accession normalization precedes duplicate detection within recent submissions,
  within history, and across their merge.
- Exact duplicate Company Facts observations may collapse only when all sealed semantics are equal.
  Different frames/contexts, same-time conflicts, or ambiguous revisions fail closed.
- Amendments form a chronological revision chain. A later amendment remains invisible
  to an earlier Accounting snapshot.
- TTM is not derived. Restatement materiality is not inferred.

## Units, confidence, and QVM

Currency uses a closed, hashed Phase 7C allowlist: `CNY`, `EUR`, `GBP`, `JPY`, and `USD`.
The SEC connector canonicalizes raw unit keys to uppercase; surrounding whitespace is
not stripped. `ABC` and custom tokens are rejected. Currency is preserved exactly; no
FX conversion occurs. `SHARES`, `PURE`, ratios,
percentages, and currency are distinct unit families. Cross-currency Value remains
blocked until governed real FX exists.

`data_confidence`, `mapping_confidence`, and `calculation_confidence` remain null. The
registry proves deterministic mapping identity, not empirical data quality. Therefore
the honest terminal state of this phase is `ACCOUNTING_BOUND_QVM_NOT_READY`.

Readiness evidence progression is:

1. `RAW_INGESTED`: verified SEC raw snapshot manifests and acceptance lineage exist.
2. `CANONICAL_MAPPED`: every admitted fact has an exact registry entry and registry hash.
3. `ACCOUNTING_BOUND`: the complete revision history passes Accounting governance and
   has a content-addressed canonical ID.
4. `QVM_BOUND`: intentionally not reached in Phase 7C.

Flags alone cannot promote any state. Real historical security-provider licensing,
legal/retention approval, completeness, governed confidence, FX, restatement
materiality, corporate-action economics, and multi-year shares PIT remain external
open gates.

## Controlled real-SEC probe

On 2026-08-26, one read-only Company Facts request for Apple (`CIK0000320193`)
confirmed real standard-tag diversity without defining an operational universe or
retaining a payload in the repository. `Assets`, `NetIncomeLoss`, and
`PaymentsToAcquirePropertyPlantAndEquipment` reported USD observations;
`RevenueFromContractWithCustomerExcludingAssessedTax` appeared on 10-K/10-Q filings,
while legacy `Revenues` appeared on 10-K filings. This evidence motivated the two
separate, explicit revenue registry entries. It does not prove historical completeness,
licensing approval, operational availability, or QVM readiness.
