# ADR 0010 — IBKR Provisioned Read-Only Observation Evidence Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_AUTHORIZED / NOT_PROVISIONED**

## Decision

PR #33 completed **IBKR Read-Only Market Observation Adapter Foundation**. The next code-owned
block is **IBKR Provisioned Read-Only Observation Evidence Foundation**, in a separate Draft PR under
`NEW_PR_REQUIRED` and `AFTER_CURRENT_BLOCK_MERGED`. Foundation implementation is
`AUTHORIZED_TO_IMPLEMENT`; REAL activation is `NOT_AUTHORIZED`, `activation_real=false`, and
`operating_mode_real=false`.

The five architectural decisions are now `DEFINED` at contract level:

1. `SECURE_EXTERNAL_CREDENTIAL_HANDLING_DEFINED`: secrets live beyond the repository and domain
   model. Only sanitized, content-addressed references cross the boundary. `SecretResolver` is a
   runtime injection seam; no backend, secret, plaintext fallback, default, fixture, serialized
   secret, log value or exception value is provisioned here.
2. `APPROVED_CONNECTIVITY_DEFINED`: observation uses an IBKR Gateway/TWS API private-controlled
   boundary, operationally preferring a future dedicated Gateway session. The governed connection
   reference contains no caller-selectable host or port, allows no public inbound exposure, and has
   only `NOT_CONFIGURED → CONFIGURED_REFERENCE_ONLY → CONNECTING → OBSERVING_READ_ONLY` states.
3. `LICENSING_DEFINED`: entitlement evidence binds provider, account reference, prices/OHLCV feed,
   mode, use/display class, storage/derivative declarations, retention terms, effective/expiry
   times, source digest and policy. Contract fixtures validate shape only; authentic entitlement
   evidence remains `NOT_PROVISIONED`.
4. `OPERATIONAL_OWNERSHIP_DEFINED`: maker, independent checker, runtime operator and revocation owner
   are distinct governed roles. Maker-checker collapse, spoofing and revoked actors fail closed.
   Only contract actor IDs exist; a REAL actor registry remains `NOT_PROVISIONED`.
5. `REAL_CAPTURE_EVIDENCE_DEFINED`: immutable evidence binds the complete #33 observation batch and
   permanent identity/lineage, route, request, raw payload digest/size, event/availability/retrieval/
   observation timestamps, mode, pagination, sanitized transport, connection, credential digest,
   entitlement and operator/provisioning approval.

## Trust, persistence and readiness boundary

Captured bytes remain `OBSERVED_UNTRUSTED`; capture alone never means `VERIFIED`, `TRUSTED` or
`CLOSED`. REAL trust root, authority, independent verifier, provider admission, external custody,
WORM and legal approval remain `NOT_PROVISIONED`.

Phase #29 persistence accepts a different governed `MaterialObservation` replay identity and cannot
truthfully bind the #33 IBKR envelope in this block. Therefore the capture records
`NOT_INTEGRATED_WITH_PHASE29_IDENTITY`, accepts no persistence receipt, and claims no durable
anti-replay, WORM or custody guarantee. A bridge would require a separately authorized decision.

Actual secret backend/credential, Gateway/TWS session, authentic market-data entitlement evidence
and external actor identities are also `NOT_PROVISIONED`. Fixtures, mocks and injected resolvers
cannot promote the REAL route. All ten gates remain `OPEN_EXTERNAL`; `QVM_NOT_READY`,
`INSUFFICIENT_REAL_DATA`, `NO_TRADE`, disabled signals and live execution, and unauthorized
backtesting remain frozen.

## Successor

No unequivocal successor is selected. Any block after this foundation is `NOT_AUTHORIZED` pending a
new architectural decision and explicit authorization. Tax Lot & Tax-Aware Portfolio Governance
remains future-only and is neither the current `NEXT_BLOCK` nor authorized to implement or activate.
