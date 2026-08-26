# Phase 7C — SEC canonical fundamentals and Accounting binding

Phase 7C is a contractual/research-only foundation. It does not enable signals,
backtesting, portfolio construction, orders, or live execution. Global readiness is
`INSUFFICIENT_REAL_DATA` and every emitted decision remains `NO_TRADE`.

## Evidence chain

`Phase 7B permanent security identity → issuer/CIK acquisition plan → immutable SEC
submissions + Company Facts snapshots → hashed exact-concept mapping registry →
issuer-level canonical facts → governed AccountingDataset`

Canonical facts commit to the acquisition-plan hash, Company Facts hash, submissions
hashes, mapping-registry hash, accession, form, SEC acceptance time, fiscal period,
currency, issuer identity, applicable permanent security IDs, and runtime fingerprint.
Issuer facts are stored once. Multiple share classes appear only in the applicability
lineage and never cause duplicated economics.

## Registry v1 scope

Registry version: `sec-canonical-fundamentals-v1`.

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

Everything else is explicitly `UNMAPPED`, including custom concepts, `dei` metadata,
IFRS concepts without a registered equivalence, EBITDA, tax rate, shares, total debt,
market cap, enterprise value, and debt tags with different economic scope. No label, substring,
statement-role, ticker, or unit heuristic creates a mapping.

## Selection and period policy

- Knowledge time is SEC `acceptanceDateTime`; missing, naive, or future acceptance fails.
- Instant and duration semantics must exactly match the registry.
- Duration start/end are mandatory. FY and quarter labels must have compatible bounded
  duration, while non-calendar fiscal years are preserved unchanged.
- Exact duplicate observations may collapse only when all sealed semantics are equal.
  Different frames/contexts, same-time conflicts, or ambiguous revisions fail closed.
- Amendments form a chronological revision chain. A later amendment remains invisible
  to an earlier Accounting snapshot.
- TTM is not derived. Restatement materiality is not inferred.

## Units, confidence, and QVM

Currency is preserved exactly; no FX conversion occurs. `SHARES`, `PURE`, ratios,
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
