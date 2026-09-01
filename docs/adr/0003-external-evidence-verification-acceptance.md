# ADR 0003 — External Evidence Verification Acceptance Foundation

Status: **DRAFT; CONTRACT_TEST_ONLY; NO REAL EVIDENCE ADMITTED**

## Decision and naming

ADR 0002 does not name a Phase 7H. It identifies a later, separately authorized integration phase
that must authenticate provider evidence, use an independently provisioned verifier, control replay
and staleness, and consider gates independently. This ADR implements the next foundation under that
descriptive name rather than inventing a phase number.

The foundation has three non-equivalent layers: externally observed receipts,
`TECHNICALLY_CHECKED_NOT_TRUSTED` candidates, and official gate state. A matching synthetic
fingerprint is only a validation hook result. It is never authority, legal approval, evidence truth,
provider approval, immutable custody proof, or gate closure.

## Contracts and boundary

A code-owned, `CONTRACT_TEST_ONLY` manifest is reconstructed inside the assessor. For every gate it
fixes provider, dataset and dataset-version references, adapter and adapter-release references,
receipt and evidence policies, and the accepted synthetic artifact digests. The caller cannot
supply or replace this manifest. Receipt, authority, decision, revocation review and candidate
objects bind the gate-specific expectation hash.

The manifest alone is not enough: a separate adapter-facing material-observation boundary requires
bytes, computes SHA-256 internally, and emits a `CONTRACT_TEST_ONLY` observation bound to canonical
gate, provider, dataset/version, adapter/release, policies, observer and observation time. The
aggregate rebuilds that object from primitives, strictly decodes the embedded material and
recomputes its digest. It requires both canonical expectation and material observation, and fails
closed if material is absent. Consequently, changing every declared gate, expectation, digest,
receipt ID, nonce, assessment identity and dependent hash without changing the underlying bytes
fails. Changing the bytes while retaining mismatched provenance also fails. Collection position is
never semantic authority. This is internal content binding only, not evidence authentication.

Provider/dataset/adapter/version strings are absent from public intake and result DTOs. Intake uses
only the code-owned manifest reference and fixed-format SHA-256 identities. This structurally
removes those fields as arbitrary secret/locator channels. Hash agreement proves only internal
contract consistency and does not prove authentication, legal validity, immutable custody or
external trust.

Authority is modeled per gate as an independently observed, explicitly
`ACTIVE_UNTRUSTED` snapshot, and revocation has an explicit fail-closed status rather than a bare
check timestamp. Both bind gate expectation, receipt, assessment identity, fixed canonical
observer/maker/checker/reviewer roles, decision and verifier time where causally available. The
code-owned chronology is:

1. authority validity begins and its snapshot is captured;
2. provider issuance and evidence observation occur;
3. maker decision, checker check and independent reviewer review occur in order;
4. revocation is reviewed against observation, decision and verifier times;
5. assessment occurs at `verifier_time`.

Authority captured or activated after observation cannot legitimize past evidence. Snapshot and
receipt maximum age are each 24 hours; revocation review maximum age is one hour. Equality at the
24-hour receipt boundary is allowed only while the receipt and authority validity windows remain
open; expiry equality fails closed. `UNKNOWN`, `REVOKED` and `NOT_PROVISIONED` technical status,
retroactivity, future observations and revocation at or before a relevant time all fail.

The aggregate reconstructs every caller input from primitives, recomputes hashes and requires
exactly ten unique gates. It also requires an explicit verifier-owned replay ledger external to the
aggregate. Replay identity is recomputed internally from material digest, canonical gate
expectation, provider/dataset/version, adapter/release and the versioned temporal policy; receipt IDs
and nonces are not replay authority. The in-memory `CONTRACT_TEST_ONLY` ledger atomically consumes a
complete validated batch within one process, so identical cross-call evidence and fully re-sealed
receipt/nonce renames fail. It does not claim distributed, crash-safe or durable guarantees. A REAL
persistent/atomic backend is `NOT_PROVISIONED`, and omission or invalid provisioning fails closed.

`validate_external_verification_result` is the sole public result truth boundary:
it again reconstructs primitives, enforces code-owned literals, canonical gate coverage and the
result hash. `model_copy` or `model_construct` can create an invalid in-memory Pydantic object, but
that object, nested variants and promoted JSON cannot cross this boundary as trusted state.
A real provider-specific verifier and external trust root remain absent. Material digest agreement
does not prove provider authenticity, cryptographic signature validity, legal/licensing validity,
WORM retention or external trust.

## Frozen safety state

- authority/trust root: `NOT_PROVISIONED`
- 10/10 gates: `OPEN_EXTERNAL`
- real route: `QVM_NOT_READY`; global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`; live execution and signals disabled
- backtesting: `NOT_AUTHORIZED`

Observed evidence can become only a technically checked candidate. External trust/verification is
still unavailable, and gate closure is a separate unavailable state transition.

No fixture-to-REAL promotion, provider approval, WORM proof, scoring/ranking, portfolio, target,
broker, order, execution, backtest, dashboard or Excel capability is introduced. Independent audit
is required before adding any real adapter, trust root, legal authority or gate-state transition.
