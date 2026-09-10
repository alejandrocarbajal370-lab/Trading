# ADR 0019 — Governed Sufficient Observation Policy REAL Foundation

Status: **CONTRACT_TEST_VALIDATED; REAL POLICY APPROVAL NOT_PROVISIONED**

## Decision

Step 5 establishes a content-addressed policy contract and deterministic evaluator for deciding
whether an evidence collection is ready to be submitted for external verification. “Sufficient”
is not a global `N` and is not a property that observations can assert about themselves. It is a
governed, versioned decision over identity, scope, time, provenance, dependencies and a particular
gate criterion. A local result named `SUFFICIENT_FOR_EXTERNAL_VERIFICATION` is therefore only a
conservative hand-off state. It is not REAL verification, provider admission, gate closure or QVM
readiness.

`SufficientObservationPolicy` binds a policy ID and version, counting-semantics version, canonical
content hash, creation/review/effective/expiry timestamps, jurisdiction and use-context references,
exception/replacement/revocation metadata, and independently hashed criteria. Numeric count,
session, date, span, age and missingness thresholds are policy parameters. This repository supplies
only provisional contract fixtures with a rationale digest; it embeds no universal business,
market-data or legal conclusion. Market-data modes are typed facts (`DELAYED`, `REALTIME`, or
`NOT_APPLICABLE`) and cannot silently substitute for one another.

The policy lifecycle is `DRAFT`, `REVIEW_REQUIRED`, then
`APPROVED_FOR_EVIDENCE_COLLECTION`. The final state means only that a contract-test policy may
govern collection. It requires distinct maker, reviewer and approver actor hashes plus review
evidence. Copies, unchecked construction APIs, JSON round trips and resealing remain fully
validated. No local actor, fixture, hash or self-signature can create REAL approval. Replacement,
expiry and revocation stop future counting under the unavailable policy.

## Observation identity and deterministic counting

Counting uses `source-event-dominant-v2`, which is bound into the policy content hash and every
observation. The underlying-event key binds policy/counting version, provider, instrument, dataset,
observation type and the required source-event digest. Representation identity separately binds
provenance, attestation and local-wrapper digests. Conflict identity separately binds payload,
mode, session/date and window. Thus additional wrappers, provenance or attestation references for
one source event never increase count, sessions, dates or span. If any representation of that event
disagrees on payload, mode, session/date or window, the entire source event is excluded and the gate
requires review. A missing or malformed source-event digest fails model construction; local wrapper
identity is never used as a fallback. Ordering is canonical and independent of input order.

Providers and datasets are allow-listed per criterion. Multiple providers, datasets or modes do not
combine unless that exact criterion explicitly allows the aggregation. Policy v1 observations do
not count under v2 or a changed counting-semantics version merely because someone resealed them.

## Gate-specific criteria and dependencies

The policy requires separate criteria for real market/provider observations, FX, point-in-time
shares outstanding, historical completeness/coverage, operations/monitoring, custody/WORM/replay,
and legal/licensing evidence. These map to their corresponding existing external gates. Market
observations cannot satisfy legal, custody or operational criteria; evidence is filtered by exact
gate, observation class, capability, provider, dataset and mode before counting.

Each criterion independently defines minimum observations, sessions, dates and span, maximum age,
permitted missingness, required provenance fields, trust/authority requirements, legal rights and
custody/WORM/replay requirements. Critical dependency states are not caller-supplied enums.
`ObservationEvidence` requires separately content-addressed, typed artifact references for
trust/verifier, authority registry, legal right and custody/WORM/replay when the criterion requires
them. Each reference binds provider, dataset, route, entity/instrument, capability and policy
version, source-event and payload digests, plus an allow-listed PR38–42 source-contract identity,
artifact digest and lifecycle. Missing artifacts yield
`NOT_PROVISIONED`; binding mismatch, future availability/verification, expiry or revocation yields
`REVIEW_REQUIRED`. These references are deliberately limited to `CONTRACT_TEST_ONLY`; no local
hash, fixture, seal or reference can assert external verification.

All timestamps use strict UTC. Observation event/window time is distinct from evidence
`available_at`, and dependency availability/effective/verification times are distinct again.
Evidence available after `assessed_at` does not count; availability exactly at `assessed_at` does.
Evidence availability before the event/window ends is invalid. Dependency artifacts must be
available and verified no later than assessment and be effective, unexpired and unrevoked then.
This prevents post-hoc evidence from entering a PIT assessment merely by carrying an older market
window. It does not claim an externally trusted clock: all successful fixtures remain local
contract-test semantics.

## Privacy and safety boundary

Fields whose contract is a sensitive reference accept only `opaque:v1:<sha256>` values. The
sanctioned `opaque_reference` factory immediately and deterministically reduces raw input to that
form before public DTO construction. Direct construction with a raw value fails with a constant,
non-reflective error. Consequently those designated fields retain and serialize only opaque
digests; the implementation makes no broader claim about arbitrary non-reference text fields.
Model representations are redacted. Content addressing proves deterministic integrity, not
authenticity or external authority.

REAL policy approval, authority/counsel, trust/verifier, legal/licensing, custody/WORM/durable
replay and provider admission remain `NOT_PROVISIONED`. Gate #2 and all 10/10 gates remain
`OPEN_EXTERNAL`. The safety state remains `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`,
`trade_decision=NO_TRADE`, `signals_generated=false`, `live_execution_enabled=false`, and
backtesting `NOT_AUTHORIZED`.

Step 6—capturing sufficient authentic evidence—has not started. This change does not capture bulk
or REAL evidence, close a gate, admit a provider, score QVM, create a shortlist, backtest, construct
or rebalance a portfolio, produce targets, place orders, mutate an account, or enable any execution
path.
