# ADR 0004 — External Provider Adapter & Durable Verification Interface Foundation

Status: **DRAFT; STACKED ON PR #27; CONTRACT_TEST_ONLY; NO REAL ACTIVATION**

## Dependency and merge order

This block is stacked on commit `64e228feaa17f20d2bd89277c4de3dfe59975e2e` from PR #27.
Its name, implementation authorization, scope and frozen safety state are defined by
`governance.roadmap.NEXT_BLOCK` and ADR 0003, which are not present on `main`. PR #27 must merge
first. This PR must then be rebased or retargeted onto the merged result and revalidated; it must
not merge before PR #27.

## Decision

Implement typed ports and fail-closed scaffolding for provider adapters, canonical route
resolution, material observation, attestation verification, durable replay, independent
verification and gate-specific handoff. This is an interface foundation only.

Provider, dataset and adapter identities are closed enums resolved from a code-owned registry by
canonical `EvidenceGate`. Callers cannot supply provider/dataset/adapter strings. The registry
binds every one of the ten gates to one exact route and seals it with an integrity hash.

The material boundary accepts non-empty bytes, calculates material and provenance SHA-256 digests
internally, records an aware observation timestamp and emits only `OBSERVED`. Hashes demonstrate
internal integrity, not provider authenticity. Handoffs bind the exact gate, canonical route,
material, provenance, observation and handoff times, and an attestation result. Temporal reversal
fails closed.

The attestation hook can return only `NOT_PROVISIONED` or `UNVERIFIED`; the foundation implementation
returns `NOT_PROVISIONED`. The durable replay and independent-verifier REAL ports are also
`NOT_PROVISIONED` and raise on use. A process-local fake exists only behind an explicitly
factory-created `ContractTestContext`. The sealed REAL entry point rejects that fake and any
caller substitution. One context owns its replay instance for its complete lifecycle, so changing
adapter instances cannot evade duplicate detection. A new context is a separately declared test
lifecycle and does not claim REAL continuity.

All sensitive public result boundaries reconstruct primitive snapshots, validate nested models,
closed literals and canonical gate order, and recompute hashes. Direct constructors,
`model_validate`, JSON, `model_copy`, `model_construct`, nested forged values and fully recomputed
cross-gate packages cannot promote authority.

## Explicit non-capabilities

No REAL provider, adapter, credential, signature, attestation, trust root, legal approval, WORM
store, durable replay service or independent authority is provisioned. There is no gate closure,
readiness promotion, QVM scoring, backtesting, portfolio construction, targets, signals, broker,
orders, execution, dashboard or Excel work.

The only evidence state emitted is `OBSERVED`. `VERIFIED`, `TRUSTED` and `CLOSED` remain distinct
unavailable states. External evidence and authority are required for every transition beyond
`OBSERVED`.

## Frozen safety state

- 10/10 gates: `OPEN_EXTERNAL`
- trust root: `NOT_PROVISIONED`
- REAL durable replay: `NOT_PROVISIONED`
- independent verifier: `NOT_PROVISIONED`
- real route: `QVM_NOT_READY`
- global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`
- `live_execution_enabled=false`
- `signals_generated=false`
- backtesting: `NOT_AUTHORIZED`
