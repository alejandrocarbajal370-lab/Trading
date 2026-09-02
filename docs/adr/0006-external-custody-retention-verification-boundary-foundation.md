# ADR 0006 — External Custody & Retention Verification Boundary Foundation

Status: **AUTHORIZED TO IMPLEMENT AFTER PR #29 MERGES; CONTRACT_TEST_ONLY; NO REAL ACTIVATION**

## Evidence and dependency

PR #29 supplies durable, atomic replay continuity and explicitly labels its persistence receipt as
local acknowledgement rather than external custody, WORM retention, legal approval or a trust
root. The Phase 7E gate matrix separately requires immutable-storage configuration, retention and
expiry policy, audit/restore evidence and lineage. The smallest next block is therefore the seam
between a durable replay receipt and raw custody-control evidence; it requires no provider or IBKR
credential.

## Decision and minimum scope

The foundation implements typed, content-addressed `CONTRACT_TEST_ONLY` models for:

- a canonical storage provider/container/object/version identity;
- a retention declaration with a positive effective interval and explicit legal-hold declaration;
- non-empty raw custody evidence hashed from bytes inside the observation boundary;
- binding to the deeply revalidated replay identity and persistence receipt;
- canonical UTC timestamps and causality
  `replay committed_at <= retained_from/observed_at <= assessed_at`, with observation
  strictly before retention expiry; and
- an `OBSERVED_UNTRUSTED` assessment that leaves every external truth field unprovisioned.

Location, retention and legal-hold values are declarations, not proof. A content hash proves
integrity only. Contract evidence cannot establish external custody, object lock/WORM, legal
approval, authenticity, independent verification, provider admission or gate closure. The REAL
entry point owns no caller-injectable backend, authority or trust root and always fails closed as
`NOT_PROVISIONED`.
The assessor requires the raw bytes again and recomputes size and SHA-256. Object identifiers reject
empty, `.` and `..` path segments so one storage subject cannot acquire path aliases.

## Machine-readable authorization

This implementation belongs in a new PR based on the integrated PR #29 main. After this block,
`governance.roadmap.NEXT_BLOCK` identifies **Trust-Anchor & Authority Provisioning Contract
Foundation** as the next non-REAL architectural dependency and records `AUTHORIZED_TO_IMPLEMENT`,
`CONTRACT_TEST_ONLY`, `NEW_PR_REQUIRED`, and `AFTER_CURRENT_BLOCK_MERGED`. REAL activation remains
`NOT_AUTHORIZED`; the roadmap cannot appoint a real authority or trust root.

## Frozen safety state

All ten gates remain `OPEN_EXTERNAL`. Evidence is never promoted beyond observed/untrusted. Trust
root, independent verifier, external custody, WORM and legal approval remain `NOT_PROVISIONED`.
The real route remains `QVM_NOT_READY`; global readiness remains `INSUFFICIENT_REAL_DATA`;
backtesting is `NOT_AUTHORIZED`; `trade_decision=NO_TRADE`, `signals_generated=false`, and
`live_execution_enabled=false`. This block adds no score, portfolio, target, broker, order,
execution or REAL provider promotion.
