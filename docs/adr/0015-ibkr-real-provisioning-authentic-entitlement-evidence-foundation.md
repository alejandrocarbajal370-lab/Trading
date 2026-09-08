# ADR 0015 — IBKR REAL Provisioning + Authentic Entitlement Evidence Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

Delivery order is `AFTER_CURRENT_BLOCK_MERGED` and `NEW_PR_REQUIRED`. REAL activation is
`NOT_AUTHORIZED`.

## Decision

Paso 1 de la secuencia aprobada introduces separate typed contracts for an operational, read-only
IBKR session and authentic market-data entitlement evidence. Session evidence proves only that a
bound external session was operational. Socket connectivity, handshake, callbacks, ticks and the
`DELAYED`/`REALTIME` market mode never prove entitlement, trust or provider admission.

All credential-backend, deployment, session, entitlement-authority and evidence references are
opaque SHA-256 digests. Usernames, passwords, 2FA material, tokens, account identifiers and raw
secrets are outside every domain model, serialization and error. The contracts bind provider IBKR,
adapter, dataset, route, request, MSFT security identity/`conId`, session evidence and explicit UTC
requested/available/effective/verified/expired/revoked lifecycle.

Public assessment reconstructs nested input and fails closed on copy/construct/JSON/extras,
noncanonical identifiers, hash changes, temporal invalidity, replay/reseal and cross-scope swaps.
Contract fixtures can validate the shape only. A repository-local hash, HMAC, signer, monkeypatch,
fixture or callback cannot authenticate REAL entitlement. The honest REAL checker remains
`NOT_PROVISIONED` until an independently provisioned external verifier exists.

## Roadmap and safety

The successor remains `UNDETERMINED / NOT_AUTHORIZED / ARCHITECTURAL_DECISION_REQUIRED`. The
intended sequence points toward **External trust / attestation / verifier REAL**, but naming it as an
authorized machine-readable successor would falsely imply readiness.

All 10/10 gates remain `OPEN_EXTERNAL`; provider admission, authentic REAL entitlement and the
independent verifier remain `NOT_PROVISIONED`. `trade_decision=NO_TRADE`,
`live_execution_enabled=false`, `signals_generated=false`, backtesting `NOT_AUTHORIZED`,
`QVM_NOT_READY`, and `INSUFFICIENT_REAL_DATA` remain fixed. This ADR authorizes no scoring,
shortlist, portfolio, sizing, rebalancing, targets, orders, execution or account mutation.
