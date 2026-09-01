# ADR 0002 — Phase 7G Governed External Provisioning Foundation

Status: **DRAFT; CONTRACT_TEST_ONLY; NO REAL EVIDENCE ADMITTED**

## Context and decision

Phase 7F left provider/dataset selection, external authority provisioning, licensing approval,
authoritative custody and authentic evidence as explicit future work. Phase 7G introduces the next
fail-closed contract layer. It distinguishes selection, provisioning, external verification and
gate closure; none implies another.

A selection record binds provider, dataset, version, scope, temporal validity, legal/licensing
state and a maker-checker decision. The versioned `phase7g-temporal-causality-v1` policy requires
`valid_from ≤ selected_at ≤ provisioning ≤ retrieval ≤ custody receipt ≤ observation ≤ evidence
pending ≤ verifier_time < expiry`. Selection and declared legal/licensing windows must be valid at
historical use and verifier time; retroactive legitimation and expiry at the verifier boundary are
rejected. Selection is always `NOT_APPROVED` and `NOT_ADMITTED` here.
Commercial and contract metadata are declarations. `EXTERNALLY_VERIFIED` legal state is rejected.

Credentials are auditable, non-secret identities only: `CredentialReference` contains a fixed
SHA-256 `credential_reference_digest` produced outside this contract, code-owned version/purpose
literals and its structural hash. It accepts no caller-controlled provider, dataset, scope, adapter
or locator metadata, so those fields cannot be repurposed as a secret channel. Provider, dataset,
scope and adapter bindings instead come from the revalidated selection, gate envelopes and the
code-owned canonical manifest. Secret material and the reversible secret-store locator live outside
every Phase 7G DTO and hash. The digest is neither credential validity nor authentication. There is
no callable or duck-typed resolver and no fixture-to-REAL promotion.

External authorities remain `NOT_PROVISIONED`. Fingerprints, validity and revocation metadata are
reserved for a later integration backed by real keys/certificates and an independently provisioned
verifier. Self-declaration is rejected. Object-lock receipts distinguish declarations from proof:
bucket/object/version, retention and legal-hold declarations plus a hash do not prove WORM. A
code-owned, versioned `phase7g-canonical-gate-manifest-v1` independently fixes the expected
contract-test bucket, object, version, source, provenance policy, evidence policy, adapter and
artifact digest for every gate. Each receipt must match that expectation and the selected
provider/dataset/version/scope; its ID must resolve from the envelope to that exact receipt. This is
object/version binding only, never provider-originated WORM verification.

Each canonical Phase 7E gate receives exactly one bound evidence candidate. The canonical manifest
is internal to the assessor, cannot be supplied alongside a caller package, and is contractual—not
external truth or knowledge of a REAL provider. Candidates bind selection, gate, canonical source,
provenance and evidence policies, credential digest, artifact, authority foundation, exact custody
object and validity window. Collections are resolved by canonical gate identity rather than list
position. Duplicate/missing/extra gates and fully re-sealed cross-gate package swaps fail against
the independent manifest. A candidate can only be `EXTERNAL_EVIDENCE_PENDING`; every official gate
remains `OPEN_EXTERNAL`.

## State machine

The implemented contractual chain is `UNSELECTED → SELECTED → PROVISIONING_PENDING →
PROVISIONED_CONTRACT_ONLY → EXTERNAL_EVIDENCE_PENDING`. Each adjacent transition contains
previous/current state, causal time, selection hash and its own semantic hash. The aggregate
reconstructs all records, requires the complete ordered chain and derives the terminal state;
skips, reversals and caller-authored terminal states fail. `PROVISIONED_CONTRACT_ONLY` and
`EXTERNAL_EVIDENCE_PENDING` never imply external verification, REAL admission or gate closure.
This phase never exposes `REAL_APPROVED`. Later transitions require a separately authorized,
independently provisioned external verifier.

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

The authority/trust root remains `NOT_PROVISIONED`. Selection and provisioning are not provider
approval, external verification or gate closure, and all ten gates remain `OPEN_EXTERNAL`.

## Next external integration acceptance criteria

A later, separately authorized phase must provision a real external trust root outside caller
control; verify signatures or equivalent provider authentication; obtain explicit legal/licensing
approval; retrieve immutable artifacts through a production adapter using secret handles; validate
provider-originated object-lock evidence; appoint independent maker/checker roles; and produce
gate-specific, timely evidence. Only an independent gate verifier may then consider a transition
from `OPEN_EXTERNAL`, one gate at a time. Phase 7G cannot perform that transition.
