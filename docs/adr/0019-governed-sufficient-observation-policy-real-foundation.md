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

Semantic identity binds the exact policy/counting version, provider/source, instrument, dataset,
observation type, session/date/window, market-data mode, payload digest, provenance digest,
attestation reference and source-event reference. Caller aliases and local wrapper digests are
deliberately excluded, so repeated storage, replay or repackaging of one underlying event cannot
increase a count. Duplicate reason and count reporting is stable. Same scope and time window with
different payload digests is an explicit conflict: all conflicting versions are withheld and the
gate requires review. Ordering is canonical and independent of input order; the evaluator is pure
and immutable, so parallel calls cannot create or double-count persistent state.

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
custody/WORM/replay requirements. A missing or `NOT_PROVISIONED` dependency yields
`NOT_PROVISIONED`; revoked, expired, ambiguous or contract-review material yields
`REVIEW_REQUIRED`; a numeric/coverage shortfall yields `INSUFFICIENT`. Machine-readable reason
codes accompany every gate result. There is no silent fallback from absent provenance, rights,
trust, custody, a provider, dataset or market-data mode.

All timestamps use strict UTC. Future observations, stale observations, observations outside the
policy window, and pre-effective observations where grandfathering is disabled do not count.
Dependency evidence must have existed for the observation and remain current and unrevoked at the
assessment time. Point-in-time meaning and freshness are thus evaluated against the selected policy,
not the wall clock implicitly and not whichever policy happens to be newest.

## Privacy and safety boundary

Public models contain opaque references and digests, never account IDs, TIN/RFC values, addresses,
credentials, tokens, secrets or raw privileged material. Model representations are redacted and
validation errors do not reflect hostile inputs. Content addressing proves deterministic integrity,
not authenticity or external authority.

REAL policy approval, authority/counsel, trust/verifier, legal/licensing, custody/WORM/durable
replay and provider admission remain `NOT_PROVISIONED`. Gate #2 and all 10/10 gates remain
`OPEN_EXTERNAL`. The safety state remains `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`,
`trade_decision=NO_TRADE`, `signals_generated=false`, `live_execution_enabled=false`, and
backtesting `NOT_AUTHORIZED`.

Step 6—capturing sufficient authentic evidence—has not started. This change does not capture bulk
or REAL evidence, close a gate, admit a provider, score QVM, create a shortlist, backtest, construct
or rebalance a portfolio, produce targets, place orders, mutate an account, or enable any execution
path.
