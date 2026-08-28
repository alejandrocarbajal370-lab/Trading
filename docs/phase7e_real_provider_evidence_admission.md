# Phase 7E — Real Provider Evidence Admission & External Gate Closure Design

Status: **REMEDIATED CONTRACT DESIGN; INDEPENDENT RE-AUDIT REQUIRED; NOT COMPLETE**. Phase 7E defines how external
evidence may be admitted; it does not supply that evidence, select a provider, or authorize real
readiness. The real route remains `QVM_NOT_READY`, global readiness remains
`INSUFFICIENT_REAL_DATA`, and backtesting remains `NOT_AUTHORIZED`.

## Purpose and boundary

Phase 7E is the provider-agnostic governance phase after the integrated Phase 7A–7D foundations.
Its purpose is to make every remaining real-data claim reviewable, scoped, and fail-closed. A
provider name, credential, successful request, fixture, declaration, checksum, or self-hash is not
evidence that licensing, completeness, retention, or operations controls are satisfied. A
self-hash proves integrity of the hashed bytes, not authenticity or truth of their claims.

In scope now (**INTERNAL-CONTRACT**) are the canonical gate matrix, typed/versioned evidence and
review envelopes, exact provider/dataset binding, maker-checker separation, synthetic-fixture
classification, and a fail-closed assessment. **OPEN_EXTERNAL** work is the acquisition and
independent review of real evidence. **FUTURE**, after provider selection and evidence acceptance,
is adapter integration, real-data validation, scale qualification, and a separately authorized
readiness transition.

Out of scope are provider selection, commercial commitments, data procurement, fabricated proof,
live provider integration, QVM readiness promotion, scoring changes, portfolio construction or
sizing, target prices, signals, backtesting, dashboards/Excel, brokers, orders, and execution.

## Prerequisites and admission order

The immutable prerequisites are merged Phase 7A (SEC ingestion), 7B (security master and
constituents PIT), 7C (SEC/accounting binding), and independently re-audited and merged Phase 7D
(confidence, FX PIT, and QVM admission). Admission proceeds in this order:

1. identify the candidate provider and exact dataset/version without treating selection as approval;
2. assemble source records for each gate, bound to that same provider/dataset and declared scope;
3. have a maker submit each record and a distinct checker accept or reject it;
4. recompute the versioned bundle hash for integrity and resolve every referenced source through
   an independently provisioned, canonical trust anchor;
5. record gate results; missing, rejected, stale, mismatched, or fixture evidence stays
   `OPEN_EXTERNAL`;
6. only after every gate is accepted by a future real verifier backed by custody and identity
   trust anchors may Phase 7E be called `EVIDENCE_REVIEW_COMPLETE`; the current repository cannot
   produce that state;
7. a future, separately authorized phase must integrate and validate real data before any readiness
   transition. Completing Phase 7E alone never changes `QVM_NOT_READY`.

## Canonical evidence-gate matrix

Allowed gate states are `OPEN_EXTERNAL`, `UNDER_REVIEW`, and `VERIFIED`. Only a governed bundle of
`REAL_EXTERNAL` records accepted by a distinct checker can derive `VERIFIED`; callers cannot set a
gate state. The current repository contains no such bundle, so every gate is `OPEN_EXTERNAL`.

| Gate | Concrete evidence required to close it | Current state |
|---|---|---|
| Historical PIT + security master | Licensed snapshots/events, effective/availability timestamps, identifiers, delistings and gap-free declared coverage replay | `OPEN_EXTERNAL` |
| Licensing/legal | Executed entitlement or counsel/compliance approval naming datasets, uses, users, storage, derived artifacts and retention rights | `OPEN_EXTERNAL` |
| Historical completeness/coverage | Independently checked symbols, dates, fields, corrections, missingness, survivorship and delisting coverage against declared scope | `OPEN_EXTERNAL` |
| Retention/WORM | Configured immutable storage, retention/expiry policy, access/audit logs, restore test and derived-artifact lineage/retention proof | `OPEN_EXTERNAL` |
| Operations/monitoring | Runbooks, ownership/on-call, SLIs/alerts, freshness and reconciliation controls, incident test and recovery evidence | `OPEN_EXTERNAL` |
| Real FX | Licensed PIT FX observations with publication/availability timestamps, exact lineage, correction policy and coverage validation | `OPEN_EXTERNAL` |
| Shares outstanding PIT | Multiyear as-reported share facts with availability/restatement history, split treatment, lineage and coverage tests | `OPEN_EXTERNAL` |
| Restatement materiality | Approved materiality policy plus replayable original/amended facts, decision records and reviewer evidence | `OPEN_EXTERNAL` |
| Corporate-action economics | Approved split, dividend, merger, spin-off, rights and delisting economic-treatment policy with independent event reconciliation | `OPEN_EXTERNAL` |
| Scale/operational validation | Representative-volume load, latency, rate-limit, retry, recovery, reconciliation and capacity results under governed acceptance thresholds | `OPEN_EXTERNAL` |

## Evidence classes and contractual artifacts

`REAL_EXTERNAL` means a source record obtained from an authoritative external or independently
controlled system and retained under governed custody. `CONTRACT_TEST_ONLY` means synthetic,
mock, sample, sandbox, or adversarial data. Contract tests can prove parser and gate behavior but
can never promote a provider, gate, real route, or global readiness.

The implementation now exposes two non-convertible result domains. The contract verifier accepts
only `ContractTestEvidence`, `ContractTestCustodyContext`, and a synthetic reviewer registry; it
can prove that the ten typed schemas, policies, scope/time rules, and maker-checker mechanics work,
but its result is `ContractGateVerification`, never real admission. The real verifier returns all
gates `OPEN_EXTERNAL` because no independently provisioned custody resolver, reviewer registry,
legal authority, or canonical trust policy exists in this repository. Caller-created contexts,
enums, strings, aliases, resealed objects, `model_validate`, and mutually matching hashes cannot
change that outcome.

Each gate has a distinct discriminated payload schema. Evidence is bound to provider, dataset,
as-of, scope, coverage window, policy version/hash, and its approval. Approvals bind the exact
evidence hash and canonical reviewer identities; mutation invalidates them. Contract policy may
specify a maximum age, but no undocumented economic freshness duration is invented for real use.
Retention evidence must identify an immutability-control artifact and derived-artifact policy:
a content hash is not WORM. Real maker-checker authenticity requires a separately governed
identity source; two display strings are not two governed actors.

Before real readiness can even be considered, all of these artifacts must exist: provider and
dataset selection decision; licensing/legal approval; declared coverage specification; immutable
raw acquisition manifests; PIT/security-master, FX, shares, restatement and corporate-action
evidence bundles; retention/WORM control proof; operations and scale validation reports; distinct
maker/checker identities and review decisions; resolvable source records; hashes for integrity;
and an independent final admission audit. Authenticity must come from source custody and review,
not from self-hashing.

## Acceptance and exit criteria

This design phase may be accepted only after independent re-audit of the remediated SHA confirms
that the canonical document and typed tests persistently enforce
the matrix, concrete proof requirements, maker-checker rule, fixture boundary, and fail-closed
defaults. Its external-evidence exit is stricter: a provider/dataset is selected; all ten gates
have scope-matched, resolvable, real records accepted by independent checkers; the bundle is
independently audited; no unresolved exception remains; and a subsequent phase is explicitly
authorized. Phase 7E records `EVIDENCE_REVIEW_COMPLETE`; it deliberately has no transition to real
QVM or global readiness. Even a later merge of Phase 7E would not imply provider selection,
authentic evidence admission, or real-provider readiness.

## Permanent safety invariants

- `trade_decision=NO_TRADE`
- `live_execution_enabled=false`
- `signals_generated=false`
- real route `QVM_NOT_READY`
- `global_readiness=INSUFFICIENT_REAL_DATA`
- backtesting `NOT_AUTHORIZED`
- no portfolio construction/sizing, target prices, broker/orders/execution, or dashboard/Excel
- no fake provider, readiness, licensing, completeness, retention, operations, or other evidence
