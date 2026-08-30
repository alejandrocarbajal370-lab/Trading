# ADR 0002 — Phase 7G Governed External Provisioning Foundation

Status: **DRAFT; CONTRACT_TEST_ONLY; NO REAL EVIDENCE ADMITTED**

## Context and decision

Phase 7F left provider/dataset selection, external authority provisioning, licensing approval,
authoritative custody and authentic evidence as explicit future work. Phase 7G introduces the next
fail-closed contract layer. It distinguishes selection, provisioning, external verification and
gate closure; none implies another.

A selection record binds provider, dataset, version, scope, temporal validity, legal/licensing
state and a maker-checker decision. Selection is always `NOT_APPROVED` and `NOT_ADMITTED` here.
Commercial and contract metadata are declarations. `EXTERNALLY_VERIFIED` legal state is rejected.

Credentials are indirect environment references or secret-manager handles only. No value is stored
or logged. Artifact envelopes remain `CONTRACT_TEST_ONLY` and bind source identity, retrieval time,
artifact digest, provenance, custody and credential-reference identity. There is no callable or
duck-typed resolver and no fixture-to-REAL promotion.

External authorities remain `NOT_PROVISIONED`. Fingerprints, validity and revocation metadata are
reserved for a later integration backed by real keys/certificates and an independently provisioned
verifier. Self-declaration is rejected. Object-lock receipts distinguish declarations from proof:
bucket/object/version, retention and legal-hold declarations plus a hash do not prove WORM.

Each canonical Phase 7E gate receives exactly one bound evidence candidate. Candidates bind the
selection, artifact, authority foundation, custody receipt, policy and validity window. Revalidation
rejects stale/replayed data and provider, dataset, version, scope, gate or artifact swaps. A
candidate can only be `EXTERNAL_EVIDENCE_PENDING`; every official gate remains `OPEN_EXTERNAL`.

## State machine

The vocabulary is `UNSELECTED → SELECTED → PROVISIONING_PENDING → PROVISIONED_CONTRACT_ONLY →
EXTERNAL_EVIDENCE_PENDING`. This phase never exposes `REAL_APPROVED`. Later transitions require a
separately authorized, independently provisioned external verifier.

## Permanent safety state

- 10/10 Phase 7E gates: `OPEN_EXTERNAL`
- real route: `QVM_NOT_READY`
- global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`
- `live_execution_enabled=false`
- `signals_generated=false`
- backtesting: `NOT_AUTHORIZED`

No scoring/ranking, portfolio construction/sizing, target prices, broker/orders/execution or
dashboard/Excel capability is authorized.

## Next external integration acceptance criteria

A later, separately authorized phase must provision a real external trust root outside caller
control; verify signatures or equivalent provider authentication; obtain explicit legal/licensing
approval; retrieve immutable artifacts through a production adapter using secret handles; validate
provider-originated object-lock evidence; appoint independent maker/checker roles; and produce
gate-specific, timely evidence. Only an independent gate verifier may then consider a transition
from `OPEN_EXTERNAL`, one gate at a time. Phase 7G cannot perform that transition.
