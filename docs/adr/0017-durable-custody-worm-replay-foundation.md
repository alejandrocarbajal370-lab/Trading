# ADR 0017 — Durable Custody + WORM + Replay Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

Delivery order is `AFTER_CURRENT_BLOCK_MERGED` and `NEW_PR_REQUIRED`. REAL activation is
`NOT_AUTHORIZED`.

## Decision

Paso 3 defines typed evidence for custody backend/deployment provisioning, retention/WORM policy,
distinct custody operator and continuity auditor lifecycle, exact raw and derived artifact
identities, custody receipts, access audit, persistent replay journal, and restore verification.
Every receipt binds provider IBKR and the complete session, authentic entitlement, observation,
attestation and independent-verification chain from ADRs 0015 and 0016. It also binds content,
material, provenance, lineage, scope, backend, deployment, policy, timestamps and content-addressed
hashes. Derived artifacts must point to the exact raw identity.

The two new roles are deliberately separate: `CUSTODY_OPERATOR` emits persistence/custody events;
`CONTINUITY_AUDITOR` verifies restore and continuity. They do not replace or reuse any of ADR
0016's seven roles. Registry, trust, backend, policy and actors remain lifecycle-bound and are
revalidated current-as-of assessment; expiry or revocation at the boundary fails closed.

## Durable replay and restore

The factory-only local SQLite adapter demonstrates `CONTRACT_TEST_ONLY` persistence across process
restart, atomic consume-if-new, concurrent single-winner behavior, integral batch rollback,
schema/integrity checking, journal hash-chain continuity, explicit store identity, duplicate
rejection, and exact restore hash/size/version checks. Every journal receipt is resolved and
revalidated against the exact persisted object at open. Missing, ambiguous, swapped or corrupt
objects fail closed.

Reopening an existing store requires a caller-custodied checkpoint reference binding the store
identity, monotonic journal sequence and current journal head hash. A database snapshot older or
newer than that independently retained reference fails closed, as does a missing or tampered
reference; the reference advances only after a successful database commit. A database and its old
checkpoint copied or rolled back together remain indistinguishable to local code. Therefore this
mechanism proves anti-rollback only relative to the independently supplied expected reference. A
REAL guarantee requires an externally authoritative monotonic anchor, which is not provisioned.
Local files, metadata, hashes or hidden secrets are not such an anchor and never promote this
adapter beyond `CONTRACT_TEST_ONLY`.

Temporal causality is inclusive at commit: upstream verification must precede storage,
`stored_at <= committed_at <= restore.verified_at <= assessed_at`. Backend, custody operator and
retention policy must be effective, unexpired and unrevoked at storage, and the relevant evidence
must remain current through assessment. UTC is mandatory; equality at expiry or revocation fails
closed. Corrupt or truncated state is never silently initialized as empty.

Replay identity is rederived from semantic upstream scope and exact raw artifact, attestation,
verification, backend and policy hashes. Caller aliases, metadata changes, copies or reseals cannot
choose a new replay identity without invalidating the transitive graph.

## WORM and REAL boundary

Content hashes establish integrity only. Retention duration, lock mode, effective/retain-until,
expiry, revocation and configuration digest are contract evidence; they are not external
immutability proof. SQLite, local files, chmod/read-only flags, Git commits, hashes, signed JSON,
HMACs and local keys cannot prove REAL WORM or custody. No S3 Object Lock, bucket, KMS, legal hold,
storage vendor or external auditor is claimed. Fixtures and the local adapter reach at most
`CONTRACT_TEST_ONLY`; REAL custody, WORM and durable replay remain `NOT_PROVISIONED`.

Receipt presence is not licensing, legal approval, provider admission or gate closure. All 10/10
gates remain `OPEN_EXTERNAL`; provider admission and legal/licensing remain `NOT_PROVISIONED`.
`trade_decision=NO_TRADE`, `live_execution_enabled=false`, `signals_generated=false`, backtesting
`NOT_AUTHORIZED`, `QVM_NOT_READY`, and `INSUFFICIENT_REAL_DATA` remain fixed.

## Roadmap

1. IBKR REAL provisioning + entitlement — closed in PR #39.
2. External trust / attestation / verifier REAL — closed in PR #40.
3. Durable Custody + WORM + Replay — this foundation.
4. Licensing/legal.
5. REAL sufficient-observation policy.
6. Capture sufficient evidence.
7. Close ten gates.
8. Provider Admission REAL.
9. SEC + IBKR to QVM REAL.

The named successor is **Licensing/legal**, but remains `NOT_AUTHORIZED /
ARCHITECTURAL_DECISION_REQUIRED`. Naming it does not grant implementation or readiness.
