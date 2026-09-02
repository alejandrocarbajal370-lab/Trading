# ADR 0004 — External Provider Adapter & Durable Verification Interface Foundation

Status: **DRAFT; PR #27 INTEGRATED; CONTRACT_TEST_ONLY; NO REAL ACTIVATION**

## Dependency and merge order

This block depends on the authorization and frozen safety state integrated from PR #27 in
`governance.roadmap.NEXT_BLOCK` and ADR 0003. PR #28 is retargeted to the resulting `main` and
remains draft pending complete validation and explicit merge authorization.

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

Handoff validation independently reconstructs the observation binding from the canonical route,
material digest, provenance digest and observation time. Re-sealing an outer handoff cannot replace
any one of those values while retaining an unrelated observation identity.

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

## Successor and merge order

The next minimum block is **Durable Replay Persistence & Custody Boundary Foundation**. This block
exposes a replay port but intentionally supplies only process-local `CONTRACT_TEST_ONLY` behavior;
restart/cross-process continuity, atomic persistence and a custody/retention boundary are therefore
the first unimplemented prerequisite owned directly by this interface.

`governance.roadmap.NEXT_BLOCK` is the machine-readable authorization. The successor's non-REAL
foundation implementation is `AUTHORIZED_TO_IMPLEMENT`, while REAL activation is
`NOT_AUTHORIZED`. PR #28 remains independently mergeable and must not contain the successor
implementation. After PR #28 is explicitly authorized and merged, the successor must start in a
new PR based on the integrated PR #28 head. No successor PR is authorized while PR #28 remains
unmerged.
