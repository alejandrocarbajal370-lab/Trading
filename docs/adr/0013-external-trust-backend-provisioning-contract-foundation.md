# ADR 0013 — External Trust Backend Provisioning Contract Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

## Decision

After **IBKR Observation External Authenticity Foundation**, the next minimum block is
**External Trust Backend Provisioning Contract Foundation**. The user explicitly authorized the
architectural decision that ADR 0012 left undetermined. Implementation is limited to a new Draft PR
after #36 under `AFTER_CURRENT_BLOCK_MERGED` and `NEW_PR_REQUIRED`; REAL activation remains
`NOT_AUTHORIZED` and `NOT_PROVISIONED`.

Provider evidence cannot be admitted until an external boundary can identify a backend, pin its
deployment and configuration, distinguish attester from verifier, bind their authority and
revocation lifecycles, and refer to externally provisioned trust and operational evidence. This
block makes that contract machine-readable without naming Vault, KMS, HSM or any vendor and without
shipping an injectable signer, key, verifier, registry, endpoint or credential.

## Contract and binding

The contract binds `provider.ibkr` to digest-only backend deployment, endpoint and configuration
references. Seven ordered, distinct external principals cover provisioning maker, provisioning
checker, runtime operator, attester, verifier, authority and revocation ownership, each with
independent effective, availability, expiry and revocation semantics checked again at assessment
time. Maker and checker preserve the dual-control provisioning boundary established by earlier
foundations; the runtime operator is a separate identity accountable for operating the deployed
backend. None is decorative: every role and lifecycle is included in the canonical manifest hash
and revalidated at assessment time.

The provisioning manifest binds the exact PR #35 request and observation binding hashes and the
exact PR #36 authenticity assessment and entitlement hashes. It separately references trust anchor,
authority registry, durable replay service, custody evidence, WORM evidence and legal approval.
These are content-addressed references, not proof that any service, control, entitlement or approval
exists. The trust-anchor object and authority-registry object must have distinct digests because
they are different governed artifacts. The replay, custody, WORM and legal references may share an
external evidence root (including equal digests), and principal authority-reference digests may
refer to the same registry; neither case implies identity collapse or confers trust. Principal IDs
and external identity digests are independently unique across all seven roles, and principal IDs
must be canonical lowercase ASCII/NFKC so Unicode aliases and confusables fail closed. Account IDs,
secrets, tokens, private key material and credentials remain outside the repository and domain.

Contract-test sealing and validation can yield only `CONTRACT_TEST_VALIDATED`. Public boundaries
deeply reconstruct nested primitives and reject extra fields, altered hashes, cross-provider,
cross-security, cross-request, cross-observation and cross-assessment substitutions, lifecycle
invalidity and principal collapse. Provisioning assessment time must be canonical UTC and cannot
precede the deeply revalidated upstream authenticity verification time; equality is valid. The
bound request/retrieval/observation chronology must precede authenticity verification, and a
manifest that binds that authenticity result cannot become effective before verification. Hostile
validation failures are generic and discard exception
chains. The REAL entry point accepts no injected backend and always returns `NOT_PROVISIONED`.

## Admission and successor

This block does not aggregate observations or admit a provider. Market-data mode, a callback,
localhost connectivity or successful TWS/Gateway connection is never entitlement or admission.
All ten gates remain `OPEN_EXTERNAL`; trust anchor, authority registry, authentic entitlement,
independent verifier, replay/custody, WORM/legal and provider admission remain `NOT_PROVISIONED`.

The machine-readable successor remains
`UNDETERMINED / NOT_AUTHORIZED / ARCHITECTURAL_DECISION_REQUIRED`. A future
provider-admission evidence aggregation block must define an explicit governed sufficient-observation
policy and prevent cross-gate/provider/security/request/route swaps, but is not authorized or
implemented here. QVM remains blocked until sufficient REAL observations are independently verified
and admitted.

## Frozen safety state

`trade_decision=NO_TRADE`, `live_execution_enabled=false`, `signals_generated=false`, backtesting
`NOT_AUTHORIZED`, `QVM_NOT_READY`, and `INSUFFICIENT_REAL_DATA`. No scoring, shortlist, portfolio,
sizing, rebalance, target, order, execution or account mutation is introduced.
