# ADR 0001 — Phase 7F External Trust Boundary Architecture

Status: **DRAFT; CONTRACT_TEST_ONLY; NO REAL EVIDENCE ADMITTED**

## Context and boundary

Phase 7E is integrated at `4c0825a662c9d0bc086dad9d81a2fc3f929686c3` and deliberately
leaves all ten real gates `OPEN_EXTERNAL`. Phase 7F models the internal contract seam needed before
a future independently provisioned external authority could be connected. It does not select a
provider, implement a production resolver, authenticate evidence, appoint real reviewers, or
establish a real trust root.

Every Phase 7F object is domain-tagged `CONTRACT_TEST_ONLY`. A caller can build an entirely
synthetic authority/custody universe whose mechanics pass. That result proves only canonical
semantic consistency. Self-hashes are not signatures or external provenance. Custody fields that
declare immutability or object lock are declarations, not WORM/object-lock proof. There is no REAL
authority capability, duck-typed resolver, or fixture-to-REAL promotion path in this phase.

## Decision

Phase 7F implements these synthetic governed contracts:

1. `ContractAuthorityRegistry` contains canonically ordered, versioned authorities with opaque IDs,
   classes, capabilities, validity, revocation and a typed provenance record. All nested and
   registry hashes are recomputed at the consumer boundary.
2. Each trust anchor binds the complete authority-registry identity, authority hash and provenance
   hash. Anchor IDs are globally unique, anchors are canonically ordered, and activation, expiry,
   revocation, source identity and authorized artifact class are rechecked at their use time and
   verifier time.
3. Onboarding binds candidate ID and timestamp, provider/dataset/version, a typed declared coverage
   scope, a governed policy artifact, all ten gates in their exact canonical order, and complete
   anchor identity tuples. A scope remains a declaration and cannot prove external completeness.
4. Custody is a typed canonical record binding its issuing synthetic authority, anchor identity,
   provider, dataset, artifact, version, gate, scope, timestamps and source SHA-256. Verification
   recalculates the record hash and source digest and compares every binding to request, artifact,
   onboarding, policy, anchor and authority registries.
5. Reviewer registries bind their issuing authority and anchor, carry their own validity and
   revocation, and use stable opaque ASCII actor IDs. Maker and checker must be valid both at the
   decision time and verifier time. Registry, authority and anchor must be valid at the decision
   and verifier; audit dependencies must be valid at audit and verifier. There is no grandfathering.
6. Alias collision detection applies Unicode NFKC, Unicode-whitespace folding and Unicode
   `casefold`, in that order. This closes compatibility/composed-form/case/whitespace collisions;
   it does not claim universal homoglyph detection.
7. Admission is a verifier-derived canonical stage prefix: authority registry, trust anchor,
   onboarding, artifact custody, maker/checker, independent audit, then completion. Processing
   stops at the first failure. Result DTOs and stage records are non-authoritative and are never
   accepted back as evidence.
8. Completion requires a current reviewer with `INDEPENDENT_AUDITOR`, distinct from maker and
   checker. The auditor and its registry/authority/anchor are checked at audit time and verifier
   time. The audit must follow the decision, use `APPROVE`, and bind the exact authority, anchor,
   onboarding, policy, request, artifact/custody, decision and reviewer snapshots plus verifier time
   and both Phase 7F contract and temporal-policy versions. Missing, rejected, stale, mismatched or
   caller-forged audits cannot complete admission.
9. `phase7f-admission-temporal-order-v1` makes the stage machine causal. Candidate declaration and
   request creation must precede the decision; policy, authority and anchor must already authorize
   each event they support. The required evidence chain is
   `custody.effective_at <= custody.available_at <= artifact.retrieved_at <= decision.decided_at <=
   audit.audited_at <= verifier_time`, with `request.requested_at <= artifact.retrieved_at` and
   `candidate.declared_at <= request.requested_at`. Equality is intentionally allowed at these
   explicit boundaries because the contract timestamps have no finer causal ordering. No other
   future-dated prerequisite can enable a consuming stage.
10. The canonical audit snapshot includes every nested timestamp, `verifier_time`, the contract
    version and the temporal-policy version. Changing chronology requires changing downstream
    hashes and still cannot bypass the temporal predicates.

## Revalidation and failure semantics

The public verifier first converts every sensitive input—including nested registries, custody and
audit—to JSON primitives, reconstructs the exact expected model, and recomputes all semantic
hashes. Same-class instances, dictionaries, subclasses, `model_copy`, and `model_construct` receive
no special trust. Unknown/ambiguous identities, stale hashes, invalid chronology, missing or
reordered gates, mismatched bindings, revocation, expiry and future-dated records fail closed.

## External work still required

External authority provisioning, signatures or equivalent authentication, provider and dataset
selection, authoritative custody endpoints, real reviewer appointments, licensing approval,
retention/WORM proof, and authentic evidence for PIT/security master, completeness, operations,
FX, shares PIT, restatements, corporate actions and scale remain outside the repository. Connecting
such a capability will require a separately authorized future phase and cannot be achieved by
passing a caller-authored object to Phase 7F.

## Permanent safety state

- all ten Phase 7E real gates: `OPEN_EXTERNAL`
- real route: `QVM_NOT_READY`
- global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`
- `live_execution_enabled=false`
- `signals_generated=false`
- backtesting: `NOT_AUTHORIZED`
- no real provider selected

Phase 7F authorizes no scoring/ranking, portfolio/sizing, target prices, broker/orders/execution,
dashboard/Excel work or Phase 7G. A new independent audit of the exact remediated SHA is required
before any merge decision.
