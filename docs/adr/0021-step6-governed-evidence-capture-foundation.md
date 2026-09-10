# ADR 0021 — Step 6 Governed Evidence Capture Foundation

Status: **STARTED — FOUNDATION ONLY; NO GATES CLOSED**

## Decision

Step 6 introduces CORSO's versioned, immutable, content-addressed
`EvidenceCaptureRecord` and a validator-owned adapter from the existing canonical
`MaterializedObservedEvidence` contract-test fixtures. Capture preserves upstream facts; it does
not turn local material into REAL evidence, create external verification, admit a provider, close
a gate or change Step 5 sufficiency.

Every accepted capture binds its Step 5 class and gate, exact upstream observation hash and payload
digest, provider, dataset/version, policy reference, derived provenance digest, and strict-UTC
`observed_at`, `available_at` and `captured_at`. Facts absent from the upstream contract remain
literal `None` and appear in the fixed `missing_bindings` list. The caller cannot supply them.
Consequently every current capture is `INCOMPLETE`, `CONTRACT_TEST_ONLY`, synthetic/test-only and
`NOT_PRODUCTION_COUNTABLE`.

## Seven-class evidence-gap matrix

The Step 5 policy requires exact provider/dataset/capability/scope, canonical event identity,
payload and provenance plus applicable trust, authority, legal and custody artifacts, all current
as of assessment. The existing canonical manifest supplies the same limited binding set for each
class: gate, provider, dataset/version, adapter/release, evidence/receipt policy refs, observation
hash, payload digest and `observed_at`. It supplies neither a provider-authentic event identity nor
the complete Step 5 scope/lifecycle/dependency graph.

| Step 5 class → gate | Existing canonical upstream artifact | Available canonical bindings | Missing bindings/lifecycle | External dependency and capture ceiling |
|---|---|---|---|---|
| `REAL_MARKET` → `HISTORICAL_PIT_SECURITY_MASTER` | `MaterializedObservedEvidence` contract fixture | gate, provider, dataset/version, adapter, policy ref, payload/observation digest, observed time | capability, route, instrument/entity, canonical source event, policy version, availability source, expiry/revocation/replacement | Licensed provider identity, authority/trust, legal rights and REAL custody remain `NOT_PROVISIONED`; local capture only |
| `FX` → `REAL_FX` | same typed fixture for `REAL_FX` | same | pair/instrument scope and all common missing bindings | Licensed PIT FX source/event and external dependencies remain `NOT_PROVISIONED`; local capture only |
| `SHARES_OUTSTANDING_PIT` → `SHARES_OUTSTANDING_PIT` | same typed fixture | same | issuer/security identity, as-reported/restatement event and all common missing bindings | Authentic issuer facts, legal/trust/custody remain external; local capture only |
| `HISTORICAL_COVERAGE` → `HISTORICAL_COMPLETENESS` | same typed fixture | same | universe/symbol/date/field coverage, correction/delisting identity and common bindings | Independent coverage validation and authority remain external; local capture only |
| `OPERATIONS` → `OPERATIONS_MONITORING` | same typed fixture | same | SLI/runbook/incident/owner/capability identity and lifecycle | Operational authority and externally governed records remain external; local capture only |
| `CUSTODY_REPLAY` → `RETENTION_WORM` | fixture plus separate SQLite durable-custody contract foundation | fixture bindings; restart-safe local contract semantics exist separately | canonical cross-contract binding, REAL WORM/retention authority, external anchor and common bindings | Local SQLite is never WORM or REAL custody; those remain `NOT_PROVISIONED` |
| `LEGAL_LICENSING` → `LICENSING_LEGAL` | fixture plus separate legal-governance contract foundation | fixture bindings; typed local legal contract mechanics exist separately | executed entitlement/counsel authority, exact governed cross-binding, lifecycle and common bindings | REAL legal authority, trust and entitlement remain `NOT_PROVISIONED` |

The three other external gates—restatement materiality, corporate-action economics and scale
operational validation—remain outside the seven Step 5 observation classes and remain
`OPEN_EXTERNAL`. Nothing in Step 6 changes any of the ten official gate states.

## Identity, aliases and conflicts

The current upstream fixture lacks canonical provider source-event identity. Step 6 therefore uses
a local semantic slot only for deterministic mechanics: gate + provider + dataset + observed time.
Exact replays and aliases with one payload count once in the local registry. Two canonically valid
fixture payloads in the same slot are quarantined as `REVIEW_REQUIRED`; neither is projected to
Step 5. This local key is never described as provider event independence.

## PIT and lifecycle

All timestamps must be UTC and satisfy
`observed_at <= available_at <= captured_at <= evaluated_at`; equality is accepted.
`evaluated_at` is an explicit, caller-injected current-as-of cutoff that is sealed into the capture;
validation does not read the wall clock. Each of `observed_at`, `available_at` and `captured_at`
must be no later than that cutoff. `available_at` is capture metadata supplied at the boundary, not
a claim of provider publication time. A value after the cutoff fails closed with
`PIT_FUTURE_TIMESTAMP`; an internally impossible chronology fails with `PIT_CHRONOLOGY_INVALID`.
Non-UTC values also fail closed. The current
upstream fixture has no compatible expiry/revocation/replacement lifecycle, so capture cannot
invent one. Future adapters must validate those fields through their owning upstream validators
and evaluate them current-as-of without look-ahead.

## Local durability and privacy

`LocalEvidenceCaptureStore` provides deterministic SQLite restart/replay mechanics for contract
tests. Its ceiling is `LOCAL_CAPTURE_ONLY`; it is not WORM, independent custody, an external trust
anchor or the future PostgreSQL portfolio ledger. Rows are revalidated and content hashes checked
on every open/load. Duplicate inserts are idempotent and corrupt or mismatched rows fail closed.

Models forbid extra fields, are frozen, revalidate copy/construct/JSON paths and redact reprs.
They contain only governed references/digests and no credentials, secrets or account IDs. Public
errors are constant and do not echo hostile values.

## Step 5 boundary

`project_to_step5` is an explicit adapter boundary, not a promotion path. It returns no
`ObservationEvidence`: current captures lack canonical source-event identity and required scope,
policy, trust, attestation and custody bindings. The projection is always `NOT_PROVISIONED`, or
`REVIEW_REQUIRED` for conflicts, and preserves all ten gates as `OPEN_EXTERNAL`. Step 5 itself is
not weakened or modified.

## Safety and non-goals

Production remains `human_execution_required=true`, `execution_authority=HUMAN_ONLY`, with order
submission/modification/cancellation/transmission and cash transfer/withdrawal/banking instruction
changes prohibited. `live_execution_enabled=false`; Broker X is future/manual; IBKR production is
read-only market/research and IBKR Paper is testing only.

This ADR does not authorize or implement REAL Provider Admission, external verification, gate
closure, QVM/scoring/ranking, auxiliary cross-checks, shortlist, backtesting, portfolio sizing,
Broker X, PostgreSQL, orders, banking or dashboard execution controls. Safety remains
`QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`, `NO_TRADE`, `signals_generated=false`, backtesting
`NOT_AUTHORIZED`, and 10/10 gates `OPEN_EXTERNAL`.

The active-name edits in README, ADR 0020 and tax-aware governance are nomenclature-only:
**Aurora → CORSO**. They do not alter the approved architecture.
