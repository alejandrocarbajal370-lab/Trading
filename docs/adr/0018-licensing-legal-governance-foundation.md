# ADR 0018 — Licensing / Legal Governance Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

## Decision

Step 4 adds a governed, point-in-time contract for legal architecture. It does not encode legal
truth or legal advice. The contract separately represents jurisdiction and applicable scope,
requirements, licensing/registration requirements, evidence references, internal assessment,
external counsel/authority sources, independent review and final admission. No country, exemption,
permission, filing rule, tax rule, rate or treaty conclusion is embedded in code.

`LegalJurisdictionReference`, `LegalRequirementRecord`, and `LegalEvidenceReference` bind canonical
identities, entity/activity scope, versions, provenance digests and effective windows.
`LegalAssessmentEvidence` is an internal synthesis and cannot self-promote. `LegalAdmissionDecision`
enforces distinct evidence operator, reviewer and approver identities and preserves all REAL states
as `NOT_PROVISIONED`. External counsel and authorities are source identities, not new internal trust
roles; the seven ADR 0016 trust roles are not duplicated.

## Architecture versus legal truth

Local JSON, fixtures, hashes, HMACs, self-signatures and locally resealed records prove at most
contract integrity. They do not prove authenticity, legal effect, regulator approval, an exemption
or permission. Absence of a requirement or evidence never means permitted or exempt. A valid local
graph reaches only `CONTRACT_TEST_ONLY`. The REAL entry point fails closed because an authentic
authority registry, trust anchor, external verification and legal admission policy are not
provisioned.

Committed data contains reference identifiers, versions, metadata and digests only. It must not
contain account numbers, TIN/RFC, passport data, personal addresses, credentials, secrets or the
contents of privileged legal advice. Error and string representations are deliberately generic or
redacted.

## Point-in-time and conflict semantics

Every conclusion is assessed at an explicit UTC `assessed_at`. Jurisdictions, requirements and
evidence must be effective then. Evidence enforces `issued_at <= verified_at <= assessed_at` and
`valid_from <= assessed_at < expires_at` where expiry exists. Revocation effective by assessment
fails closed. Future changes do not apply retroactively merely because their metadata exists.

Jurisdiction, entity, activity and scope bind transitively. Research evidence cannot authorize
execution, one entity's evidence cannot serve another, and counsel evidence cannot cross
jurisdictions. Missing or unknown jurisdiction, authority mismatch, stale/revoked/future evidence,
scope mismatch and malformed/tampered versions fail closed. Missing evidence yields
`REVIEW_REQUIRED`; contradictory requirements and unresolved multi-jurisdiction ambiguity yield
`BLOCKED`. The engine never silently selects the convenient rule.

## Gate and safety boundary

The foundation can later supply versioned assessment and decision hashes to the existing
`LICENSING_LEGAL` gate. It does not close that gate. All 10/10 gates remain `OPEN_EXTERNAL` because
the authority/counsel trust path and legal truth are external and `NOT_PROVISIONED`. Provider
admission, custody/WORM/durable replay REAL and legal/licensing REAL remain `NOT_PROVISIONED`.

The resulting safety state remains `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`,
`trade_decision=NO_TRADE`, `signals_generated=false`, `live_execution_enabled=false`, and
backtesting `NOT_AUTHORIZED`. This step adds no scoring, shortlist, portfolio construction, sizing,
rebalance, targets, broker/order/execution path or account mutation.

## Successor

Step 5 is governed sufficient-observations REAL policy/evidence work. It may begin only in a new PR
after this Step 4 is audited and merged. This ADR neither implements nor authorizes Step 5.
