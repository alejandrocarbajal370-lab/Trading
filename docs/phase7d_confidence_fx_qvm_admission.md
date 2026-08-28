# Phase 7D — governed confidence, FX PIT, and QVM admission

Status: **INDEPENDENTLY RE-AUDITED AND MERGED (PR #23)**. Real-data readiness
remains `INSUFFICIENT_REAL_DATA`; the real route remains `QVM_NOT_READY`. This phase never
authorizes backtesting, signals, scoring changes, portfolio construction, orders, or execution.
Every admission preserves `NO_TRADE`, `live_execution_enabled=false`, and
`signals_generated=false`.

## Integrity is not authenticity

A self-hash proves only that a local envelope has not changed; it does not prove its claims are
true. Phase 7D therefore separates structural parsing from governed, context-bound verification.
Confidence references resolve to canonical Accounting/mapping/calculation/economic objects; FX
use replays the exact dataset row and every lineage field; readiness prerequisites resolve to the
exact upstream proof; and consumers must rederive both `QVM_ADMISSIBLE` and `QVM_NOT_READY`
with `verify_qvm_admission_v3` before treating an admission as authoritative.

Provider legal access/licensing, historical PIT completeness, retention, and operations monitoring
are `OPEN_EXTERNAL`/unknown by default. A provider is `VERIFIED` only when every required typed
gate-evidence object is supplied and resolved by the governed provider context. A provider name or
dataset identity never auto-certifies those gates. The positive admissible path is a synthetic
`RESEARCH_ONLY` contract fixture; the real route remains `QVM_NOT_READY` and globally
`INSUFFICIENT_REAL_DATA`.

## Confidence v3

The canonical policy `contractual-control-min-0.80-v2` fixes the threshold at exactly `0.80` in a
`Literal` and a policy hash. No public producer or admission API accepts a threshold. A proof that
declares any other threshold is invalid even if locally resealed.

Each component consumes typed upstream proofs bound to the exact Accounting canonical ID,
checksum, and `as_of`. Component and evidence types are fixed (`data` → content verification,
`mapping` → exact replay, `calculation` → calculation replay, and optional `economic` → economic
validation). A 64-hex string or self-hash is integrity metadata, not authenticity. When economic
confidence is supplied it participates in the conservative minimum; low or unknown economic
evidence cannot be ignored. Confidence is contractual, not empirical or predictive.

## Canonical Phase 6 sufficiency policy

`qv-phase6-exact-v2` is an exact immutable specification, not a caller-provided matrix. Primary
Quality metrics include ROIC, ROIC stability, FCF margin, CFO conversion, net-debt/EBITDA, raw
accrual ratio, and margin stability. Primary Value metrics include FCF yield, earnings yield, EBIT
yield, and EV/EBIT. EV/EBITDA and share-count change remain diagnostic. Missing inputs do not
demote a primary metric.

Sector/industry applicability comes from the governed Phase 6 policy. `NOT_APPLICABLE` is a
distinct state, never `PASS`, and callers cannot make an active metric disappear.

## Accounting adapter v2

The adapter accepts only a verified `AccountingDataset` and groups exact inputs by entity, fiscal
year, fiscal-period label and semantics, period start/end, unit, currency, and PIT cutoff. Instant
balance-sheet facts may join duration facts only at the same fiscal period end; duration facts must
retain compatible semantics and starts. It never aggregates by global metric-name presence.

Every output records exact fact IDs, values, units, currency, availability, formula, result, reason,
and lineage. Stability metrics require compatible history. Entity, period, quarter/YTD, unit, or
currency incompatibility yields `NOT_COMPUTED` or `FX_REQUIRED`; there is no proxy, fill, default
zero, or neutralization.

## FX use v2

Cross-currency need is derived from actual Value inputs and the batch base currency. Every required
fact must have an exact typed direct conversion bound to Accounting, adapter, and `FXDataset`
identities. Admission replays amount × direct rate and verifies the exact conversion set. Inverse,
triangulation, forward fill, stale/future observations, empty proofs, and local reseals are rejected.
Same-currency use is an identity with no fabricated provider observation.

## Admission and readiness

`admit_qvm_v3` accepts proofs, not declarations. There are no caller-controlled threshold,
required-state map, cross-currency boolean, provider-ready boolean, or arbitrary sufficiency
matrix. It reparses and recomputes Accounting, confidence, adapter, FX, provider, Q/V/M batch,
runtime, universe/as-of, and Phase 6 identities. The adapter is replayed from Accounting and
governed sector context. Producer and validator use one JSON-safe canonical representation.

Readiness is a typed transition chain beginning at Accounting. `QVM_ADMISSIBLE` requires a verified
`PrePhase6Admission`; direct jumps are invalid. The persistent positive fixture proves only that a
coherent synthetic contract can reach `QVM_ADMISSIBLE` in `RESEARCH_ONLY` mode while retaining
`NO_TRADE`. It does not claim real-provider readiness.

| Area | State after remediation |
|---|---|
| Confidence, sufficiency, adapter, FX, admission/readiness | Remediated; re-audit required |
| Contract fixture | `QVM_ADMISSIBLE`, `RESEARCH_ONLY`, `NO_TRADE` |
| Historical providers, licensing, retention, operations | `OPEN-EXTERNAL` |
| Shares PIT and other real-data gaps | `OPEN-EXTERNAL` |
| Real QVM route | `QVM_NOT_READY` |
| Global readiness | `INSUFFICIENT_REAL_DATA` |

Phase 7D's internal contract is closed by its completed independent adversarial re-audit and merge.
External evidence gates remain open and are governed by the Phase 7E design; this closure does not
claim provider authenticity or real-data readiness.
