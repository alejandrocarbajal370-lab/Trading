# ADR 0014 — Governed Sufficient Observation Policy & Provider Admission Evidence Aggregation Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

## Decision

After **External Trust Backend Provisioning Contract Foundation**, the next minimum block is
**Governed Sufficient Observation Policy & Provider Admission Evidence Aggregation Foundation**.
The user explicitly authorized the architectural decision that ADR 0013 left undetermined.
Implementation is limited to a new Draft PR after #37 under `AFTER_CURRENT_BLOCK_MERGED` and
`NEW_PR_REQUIRED`; REAL activation remains `NOT_AUTHORIZED` and `NOT_PROVISIONED`.

Provider admission needs a single fail-closed boundary that says what makes repeated observations
sufficient and binds those observations to all ten gate-evidence records. Without it, individually
valid-looking records could be counted twice, combined across providers or routes, or mistaken for
admission. This is the last repository-side contract foundation immediately before independently
provisioned REAL evidence can be evaluated; it does not provide that external evidence.

## Governed sufficient-observation policy

The policy is a content-addressed, authority-referenced, versioned object. It pins provider,
adapter, dataset, permanent security identity and route; a minimum count of distinct observations;
a minimum time span; maximum age; verifier-time skew; approval/effective/expiry lifecycle; all ten
canonical gates; and a separate rationale digest. Contract tests use three distinct observations
over at least twenty minutes solely to exercise the mechanism. Those numbers are fixture policy
data, not an assertion that they are commercially, statistically or operationally sufficient for
REAL admission. A future external governance decision must provision the approved policy.

Observation IDs and evidence hashes must both be unique, the sequence is chronological, and age
and verifier-time rules are rechecked at assessment time. Duplicate/replayed observations,
alias-based double counting, inadequate span, stale observations and mixed verifier times fail
closed.

## Exact aggregation and gate semantics

The bundle binds the exact provider, adapter, dataset, security-master ID, IBKR `conId`, request,
observation binding, authenticity assessment, provisioning backend/manifest/assessment,
entitlement reference, route, observation/authentication/verifier timestamps, material,
provenance, lineage, custody receipt, policy and ten ordered gate-evidence hashes. Each gate record
also binds provider, dataset, security, `conId`, request, route and policy plus external evidence,
authority registry, trust anchor, independent verifier and lifecycle references.

Public boundaries deeply reconstruct nested primitives and reject extras, mutated model copies,
constructed models, Unicode/noncanonical aliases, hash mismatches, cross-provider, adapter,
dataset, security, request, observation, assessment, backend, entitlement, route, policy or gate
swaps. Future, unavailable, expired or revoked evidence fails closed. Bundle resealing cannot alter
semantics because every nested hash and upstream binding is independently revalidated.

`CONTRACT_TEST_ONLY` gate records never derive `VERIFIED`. A successful aggregation means only
`CONTRACT_TEST_VALIDATED` and `observations_sufficient_under_contract_policy=true`; it still emits
10/10 `OPEN_EXTERNAL`, while REAL observation verification, gate closure and provider admission
remain `NOT_PROVISIONED`. Connectivity, localhost, callbacks and market-data mode are deliberately
absent from the admission inputs. Hashes and local persistence cannot fabricate authenticity,
custody, WORM or legal approval. Validation errors are generic and discard secret-bearing causes
and contexts.

## Remaining REAL prerequisites and successor

An independently deployed backend and all seven external principals, trust anchor, authority
registry, attester/verifier, IBKR credential/session and entitlement, durable replay, external
custody, WORM, legal approval, the externally approved observation policy, and authentic evidence
for every one of the ten gates remain required. Only a future REAL adapter backed by those systems
may close every required gate and materialize provider admission.

The machine-readable successor remains
`UNDETERMINED / NOT_AUTHORIZED / ARCHITECTURAL_DECISION_REQUIRED`. After sufficient REAL provider
data is observed, independently verified and admitted, a separately authorized QVM-real readiness
block may be selected. QVM implementation is not part of this block.

## Frozen safety state

`trade_decision=NO_TRADE`, `live_execution_enabled=false`, `signals_generated=false`, backtesting
`NOT_AUTHORIZED`, `QVM_NOT_READY`, and `INSUFFICIENT_REAL_DATA`. No real scoring, shortlist,
portfolio, sizing, rebalancing, targets, orders, execution or account mutation is introduced.
