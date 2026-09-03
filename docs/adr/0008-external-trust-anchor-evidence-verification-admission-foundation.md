# ADR 0008 — External Trust-Anchor Evidence Verification & Admission Foundation

Status: **DRAFT; CONTRACT_TEST_ONLY; NO REAL ACTIVATION**

## Decision

The foundation accepts non-empty external evidence bytes only through a content-addressed
observation. The sealed observation binds its payload digest and size to the exact provider, gate,
scope, policy, authority contract and independent trust-anchor registration lifecycle.

Contract-test verification requires exact expected registry and verifier hashes. The verifier is
itself sealed to that registry and authority. The authority must have `VERIFY_EVIDENCE`; the
registry must contain the exact authority and anchor; and every scope and lifecycle binding must
match. Authority and anchor availability and revocation are resolved independently. Evidence
before either availability fails, as do verification before observation and verification at or
after either revocation boundary.

All public inputs are deeply reconstructed. Payload modification, forged or substituted
registry/verifier values, cross-provider/gate/scope swaps, lifecycle swaps, nested mutation,
`model_copy`, `model_construct`, extra fields and resealing against unrelated bindings fail closed.

## Admission semantics

The name “admission” describes only the contract-test decision boundary. Its strongest state is
`CONTRACT_TEST_VERIFIED`; it does not mean `VERIFIED`, `TRUSTED` or `CLOSED` for any REAL provider.
The result explicitly preserves `OPEN_EXTERNAL`, `NOT_PROVISIONED` for trust root, independent
verifier and REAL provider admission, `NO_TRADE`, disabled signals/live execution and unauthorized
backtesting. The REAL entry point always fails closed and accepts no injected registry, verifier,
trust root or backend.

## Frozen safety state

All ten gates remain `OPEN_EXTERNAL`. Durable external custody/WORM, legal approval, trust root,
independent verifier, REAL evidence and IBKR credentials remain unprovisioned. The system remains
`QVM_NOT_READY` and `INSUFFICIENT_REAL_DATA`, with no REAL scoring, portfolio construction, sizing,
rebalancing, target prices, broker, orders or execution.
