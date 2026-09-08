# ADR 0016 — External Trust, Attestation & Independent Verifier REAL Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

Delivery order is `AFTER_CURRENT_BLOCK_MERGED` and `NEW_PR_REQUIRED`. REAL activation is
`NOT_AUTHORIZED`.

## Decision

Paso 2 de la secuencia aprobada defines typed, digest-only contracts for external trust-anchor
provisioning, authority-registry evidence, external principal provisioning/lifecycle, an
attestation envelope over the ADR 0015 IBKR session/entitlement/observation graph, and a separate
independent-verification result. The canonical block name is **External Trust, Attestation &
Independent Verifier REAL Foundation**.

The graph binds provider IBKR; adapter, dataset, route, request, security identity and `conId`;
session and authentic-entitlement evidence; backend and deployment references; trust anchor and
authority registry; distinct attester and verifier principals; UTC lifecycle; and material,
provenance, lineage and evidence digests. Attestation can occur only after upstream evidence exists.
Independent verification can occur only after attestation, and assessment only after verification.
Expiry and revocation boundaries are exclusive and fail closed. Anchor, authority, attester or
verifier rotation invalidates evidence that has not been transitively rebound.

All seven roles are exact, ordered and pairwise distinct: `AUTHORITY`, `REVOCATION_OWNER`,
`ATTESTER`, `VERIFIER`, `PROVISIONING_MAKER`, `PROVISIONING_CHECKER`, and `RUNTIME_OPERATOR`.
Canonical lowercase ASCII identifiers reject Unicode/confusable aliases. Exact-type reconstruction
rejects subclasses, duck objects, callbacks and alternate Pydantic construction paths.

## No local self-authentication

The repository contains no REAL resolver, trust root, private key, signer, HMAC, attester or
independent verifier. Contract fixtures demonstrate shape and causal binding only; their strongest
state is `CONTRACT_TEST_ONLY`. Hash or digest presence is internal consistency, not a signature,
trust, custody, WORM, replay durability, licensing, provider admission or QVM readiness. The REAL
entry point accepts no injected collaborators and remains `NOT_PROVISIONED`. Credentials, keys,
account identifiers and secret material are excluded from models, serialization and sanitized
errors.

## Roadmap and safety

The approved sequence is:

1. IBKR REAL provisioning + entitlement — closed in PR #39.
2. External trust / attestation / verifier REAL — this foundation.
3. Durable custody + WORM + replay.
4. Licensing/legal.
5. REAL sufficient-observation policy.
6. Capture sufficient evidence.
7. Close ten gates.
8. Provider Admission REAL.
9. SEC + IBKR to QVM REAL.

The named successor is **Durable Custody + WORM + Replay**, but remains
`NOT_AUTHORIZED / ARCHITECTURAL_DECISION_REQUIRED`; naming sequence position grants no readiness or
implementation authority. All 10/10 gates remain `OPEN_EXTERNAL`. Trust anchor, authority registry,
attester, independent verifier, custody/WORM/replay, legal/licensing and provider admission REAL
remain `NOT_PROVISIONED`. `trade_decision=NO_TRADE`, `live_execution_enabled=false`,
`signals_generated=false`, backtesting `NOT_AUTHORIZED`, `QVM_NOT_READY`, and
`INSUFFICIENT_REAL_DATA` remain fixed.
