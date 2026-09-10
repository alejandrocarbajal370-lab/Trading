# ADR 0019 — Governed Sufficient Observation Policy REAL Foundation

Status: **CONTRACT MECHANICS VALIDATED; CANONICAL PACKAGE NOT_PROVISIONED; REAL POLICY APPROVAL NOT_PROVISIONED**

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

Counting uses `canonical-upstream-event-required-v4`; its resolver semantics version is bound into
the policy hash. Step5 does not establish authenticity or independent event identity. A caller
digest, provider-event key, session, date or window is only local metadata. Current PR38--42 APIs
do not expose one canonical upstream observation artifact carrying all required identity, scope,
time, payload, provenance, attestation and custody bindings. The local record is therefore
explicitly `SYNTHETIC_TEST_EVENT_IDENTITY`, has no canonical upstream observation digest and always
adds `SOURCE_EVENT_NOT_PROVISIONED`. It can exercise deterministic threshold mechanics but cannot
produce `SUFFICIENT_FOR_EXTERNAL_VERIFICATION`.

Synthetic aliases map to one local grouping key and count once in mechanics diagnostics.
Conflicting wrappers produce deterministic review. Different caller-selected keys, sessions,
dates or windows never prove independent provider events and never lift the package out of
`NOT_PROVISIONED`. Distinct production-like events may count only after a future adapter derives
identity from distinct canonical upstream observation artifacts through owning validators. No such
adapter and no REAL provider source-event registry is provisioned here.

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
custody/WORM/replay requirements. Critical dependency states are not caller-supplied enums, and a
caller digest or Step5 wrapper is never authority. The old public dependency-record factory now
fails closed and `DependencyArtifactRecord` is a legacy, non-member wrapper. The resolver accepts
only exact owning-module types: PR40 `IndependentVerificationResult` and
`AuthorityRegistryEvidence`, PR41 `RestoreVerificationEvidence`, and PR42
`LegalAdmissionDecision`. It reconstructs each through its owning validator and recomputes its
owning hash. Arbitrary dictionaries, subclasses, local Step5 records, forged schema/provenance,
JSON/reseal/model-copy/model-construct products cannot create membership.

Those canonical artifacts do not carry every Step5 provider, dataset, route, entity, capability,
policy, canonical source-event and payload binding, and some lack a compatible expiry/replacement
lifecycle. Step5 therefore records the validated digest only as an unsupported capability and does
not resolve it as a satisfied dependency. All four kinds remain `NOT_PROVISIONED`. Wrapper hashes
protect wrapper consistency only. A future adapter may promote a dependency only when the owning
canonical artifact exposes all applicable bindings and current-as-of semantics; missing facts are
never synthesized locally.

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

`SUFFICIENT_FOR_EXTERNAL_VERIFICATION` is reserved for a locally complete package composed of
canonical upstream contract-test artifacts accepted by complete adapters. It would still mean only
`LOCAL_PACKAGE_COMPLETENESS_ONLY`, never authenticity or a REAL conclusion. With the current
PR38--42 APIs, canonical event independence and complete dependency bindings are unavailable, so
the state is unreachable and evaluations fail closed as `NOT_PROVISIONED` (or
`REVIEW_REQUIRED` for conflicts or tampering).

Step 6—capturing sufficient authentic evidence—has not started. This change does not capture bulk
or REAL evidence, close a gate, admit a provider, score QVM, create a shortlist, backtest, construct
or rebalance a portfolio, produce targets, place orders, mutate an account, or enable any execution
path.
