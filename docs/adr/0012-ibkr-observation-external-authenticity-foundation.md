# ADR 0012 — IBKR Observation External Authenticity Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

Authorization is `AUTHORIZED_TO_IMPLEMENT` in `CONTRACT_TEST_ONLY` mode,
`AFTER_CURRENT_BLOCK_MERGED`, through a `NEW_PR_REQUIRED`. REAL activation remains
`NOT_AUTHORIZED`.

## Decision

The block after the unauthenticated PR #35 probe is the **IBKR Observation External Authenticity
Foundation**. It binds that probe's exact observation and request hashes, governed MSFT security
identity, provider, adapter, dataset, callback-reported market mode, timestamps, and raw, material,
lineage and provenance digests to an external-attestation envelope.

This is a provisioning contract, not a local trust root. The contract-test builder produces only
`CONTRACT_TEST_ONLY`; its strongest outcome is `CONTRACT_TEST_VERIFIED`. The REAL entry point has no
injectable backend, signer, key or verifier and fails with `NOT_PROVISIONED`. Therefore fixtures,
mocks, monkeypatches, subclassing, duck objects, closure/default/global/class-attribute inspection,
or a wholly resealed local graph cannot produce `REAL`, `VERIFIED`, `TRUSTED`, gate closure or
provider admission. A future REAL adapter must name and pin independently provisioned external
infrastructure before that sealed entry point can be replaced under a separately authorized change.

## Trust and actor boundary

The attester, verifier, runtime operator, provisioning maker, authority and revocation owner are
distinct identities. The attester and authority digests are bound into the envelope; the verifier
digest is bound into the assessment. The trust anchor and authority lifecycle records independent
effective, availability, expiry and revocation times. Verification rejects evidence issued before
availability, at or after revocation/expiry, after attestation expiry, before observation, or after
an ambiguous/non-UTC timestamp.

Only public-material, registry, actor, assertion, credential-reference, account-reference and
entitlement-evidence digests cross the boundary. Raw secrets and account IDs are not domain fields.
Public validation errors discard hostile values and exception chains.

## Entitlement, replay, custody and admission

Entitlement is a separate external evidence reference bound to provider, dataset, security and its
own validity window. `REALTIME`, `DELAYED`, `FROZEN` and `DELAYED_FROZEN` remain observation metadata;
none proves entitlement. Content identity is reusable by the existing replay foundation, but this
block claims neither durable custody nor WORM/legal approval.

Provider admission stays `NOT_PROVISIONED`. All ten gates remain `OPEN_EXTERNAL`; REAL authenticity
and entitlement remain `NOT_PROVISIONED`; `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`, `NO_TRADE`,
disabled signals/live execution and unauthorized backtesting remain frozen.

## Successor

At integration time no later block was selected. ADR 0013 subsequently selects **External Trust
Backend Provisioning Contract Foundation** as the next minimum block. REAL provider admission still
requires a named external
attester/trust backend, provisioned anchor and authority registry, authentic entitlement evidence,
external verifier operation, durable replay/custody evidence, WORM/legal approval and sufficient
admitted observations. QVM remains blocked until those requirements are satisfied. Tax Lot remains
future-only.
