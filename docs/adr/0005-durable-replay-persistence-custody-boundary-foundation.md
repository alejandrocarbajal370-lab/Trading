# ADR 0005 — Durable Replay Persistence & Custody Boundary Foundation

Status: **AUTHORIZED TO IMPLEMENT AFTER PR #28 MERGES; CONTRACT_TEST_ONLY; NO REAL ACTIVATION**

## Dependency and merge order

This successor depends on the External Provider Adapter & Durable Verification Interface
Foundation in PR #28. PR #28 may be considered and merged separately. This successor must be
implemented in a new PR created only after PR #28 is merged, with its branch based on the resulting
integrated head. Stacking on the unmerged PR #28 is not authorized.

## Decision and minimum scope

The current provider foundation deliberately has only a process-local replay fake. A fresh test
context represents a separate namespace and provides no restart or cross-process continuity. The
smallest next contract block therefore specifies:

- canonical replay identity derived from the already-bound route, material and provenance;
- atomic consume-if-new semantics with duplicate rejection under concurrency;
- explicit restart and cross-process continuity behavior;
- custody and retention boundaries that distinguish declarations from durable proof;
- fail-closed recovery behavior for partial writes, unavailable storage and ambiguous commits; and
- a sealed `CONTRACT_TEST_ONLY` persistence adapter for contract tests.

This ADR authorizes contract design, truth-bearing models, ports, an isolated fake and adversarial
tests only. It does not authorize a production database, object store, WORM claim, provider route,
credential, external service or operational deployment.

## Explicit authorization boundary

`governance.roadmap.NEXT_BLOCK` is authoritative and machine-readable:

- foundation implementation: `AUTHORIZED_TO_IMPLEMENT`
- operating mode: `CONTRACT_TEST_ONLY`
- REAL external activation: `NOT_AUTHORIZED`
- successor PR: `NEW_PR_REQUIRED`
- merge order: `AFTER_CURRENT_BLOCK_MERGED`

The trust root, REAL durable replay and independent verifier remain `NOT_PROVISIONED`. No local hash,
receipt, persistence acknowledgement or recomputed identity may be treated as authenticity,
external custody, WORM retention, legal approval, provider admission or gate closure.

## Frozen safety state

- 10/10 gates: `OPEN_EXTERNAL`
- evidence beyond `OBSERVED`: unavailable
- trust root: `NOT_PROVISIONED`
- REAL durable replay: `NOT_PROVISIONED`
- independent verifier: `NOT_PROVISIONED`
- real route: `QVM_NOT_READY`
- global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`
- `live_execution_enabled=false`
- `signals_generated=false`
- backtesting: `NOT_AUTHORIZED`

No provider is approved or admitted. No fixture may become REAL. No WORM or legal/licensing approval
is fabricated. Scoring, backtesting, portfolio construction or sizing, targets, brokers, orders and
execution remain outside this authorization.
