# ADR 0007 — Trust-Anchor & Authority Provisioning Contract Foundation

Status: **AUTHORIZED TO IMPLEMENT AFTER PR #30 MERGES; CONTRACT_TEST_ONLY; NO REAL ACTIVATION**

## Decision

This block defines closed, code-owned identities and versions for authorities, trust anchors,
capabilities and evidence references. Registry metadata is kept separate from provisioning
evidence. References contain only sanitized identifiers, media types, byte counts and SHA-256
digests; private keys, tokens, certificates-as-secrets and credentials are never stored.

Every contract is immutable and content-addressed. It binds authority and anchor identities to one
provider, gate, scope, policy version and exact contract version. Maker, checker, reviewer and
authority approvals are complete, role-specific and performed by distinct canonical actors.
Effective, available, observed, verified and revoked timestamps use canonical UTC. Verification is
historical and verifier-time aware: evidence before effectiveness and verification at or after
revocation fail closed. All nested models are reconstructed at public boundaries.

Only `CONTRACT_TEST_ONLY` construction exists. Its observations remain `OBSERVED_UNTRUSTED`, with
trust root and independent verifier `NOT_PROVISIONED` and the gate `OPEN_EXTERNAL`. The REAL entry
point accepts no caller registry, fixture, trust root or fake authority and always fails closed.
Contract existence does not prove WORM, custody, legal approval, independent verification or REAL
provisioning.

## Machine-readable authorization

After this block, `governance.roadmap.NEXT_BLOCK` identifies **External Trust-Anchor Evidence
Verification & Admission Foundation** and records `AUTHORIZED_TO_IMPLEMENT`, `CONTRACT_TEST_ONLY`,
`NEW_PR_REQUIRED`, and `AFTER_CURRENT_BLOCK_MERGED`. REAL activation remains `NOT_AUTHORIZED`.
It requires a new PR after this block is independently authorized and merged. Tax Lot & Tax-Aware
Portfolio Governance remains future-only in its existing order.

## Frozen safety state

All ten gates remain `OPEN_EXTERNAL`; trust root and independent verifier remain
`NOT_PROVISIONED`. IBKR remains unprovisioned. The real route is `QVM_NOT_READY`, global readiness
is `INSUFFICIENT_REAL_DATA`, backtesting is `NOT_AUTHORIZED`, `trade_decision=NO_TRADE`,
`signals_generated=false`, and `live_execution_enabled=false`. No scoring, portfolio construction,
position sizing, rebalancing, target price, broker, order, execution or REAL provider promotion is
authorized.
