# ADR 0018 — Licensing / Legal Governance Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_PROVISIONED**

## Decision

Step 4 adds a governed, point-in-time contract for legal architecture. It does not encode legal
truth or legal advice. The contract separately represents jurisdiction and applicable scope,
requirements, licensing/registration requirements, evidence references, internal assessment,
external counsel/authority sources, independent review and final admission. No country, exemption,
permission, filing rule, tax rule, rate or treaty conclusion is embedded in code.

`LegalJurisdictionReference`, `LegalRequirementRecord`, and `LegalEvidenceReference` bind canonical
identities, entity/activity scope, versions, provenance digests and effective windows. The contract
has nine independent capability rows: receive/access, internal research, durable storage,
retention, derived data/artifacts, replay/audit, redistribution, paper-trading use, and
live-execution use. Every row starts `REVIEW_REQUIRED`; only matching current requirement and
evidence can make that row `CONTRACT_TEST_ONLY`. Missing rows never inherit permission from another
row. A denied or ambiguous row blocks, while an unknown row requires review. Storage and replay
also remain under review without an explicit retention row.

Evidence is content-addressed to the exact requirement ID/version/hash and policy ID/version/hash,
as well as jurisdiction, scope, use class, provider, dataset, route and legal subject/entity. A v1
reference cannot support a resealed v2 requirement or policy, and evidence cannot cross any of
those context boundaries. Provider, dataset and route references are versioned opaque identifiers;
they do not assert that a provider or data product is admitted for REAL use.

Issuer/source, trusted authority and independent verifier are separate identities. The requirement
records the exact authorized binding for each, and assessment compares all three. They must also be
distinct from one another. The internal evidence operator, reviewer and approver remain separate
assessment actors. This complements ADR 0016 without duplicating its trust roles or provisioning an
external trust path.
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

Committed data contains opaque reference identifiers, versions, metadata and digests only. It must not
contain account numbers, TIN/RFC, passport data, personal addresses, credentials, secrets or the
contents of privileged legal advice. Error and string representations are deliberately generic or
redacted. Public `repr`, `str`, `model_dump`, `model_dump_json` and validation/error boundaries do
not disclose identifier values: serialization replaces identifier-bearing fields with deterministic
opaque digest references. Internal hashing and validation use the original validated values through
a private trusted path; public serialized output is deliberately not a round-trip persistence format.

## Point-in-time and conflict semantics

Every conclusion is assessed at an explicit UTC `assessed_at`. Jurisdictions, requirements and
evidence must be effective then. Evidence enforces `issued_at <= verified_at <= assessed_at` and
`valid_from <= assessed_at < expires_at` where expiry exists. Revocation effective by assessment
fails closed. Future changes do not apply retroactively merely because their metadata exists.

Jurisdiction, entity, activity, capability, provider, dataset, route and scope bind transitively.
Research rights cannot authorize redistribution, paper use cannot authorize live use, one entity's
evidence cannot serve another, and evidence cannot cross jurisdictions. Issuer, authority or
verifier swaps—including a joint issuer+authority swap—fail against the requirement's authorized
bindings. Missing or unknown jurisdiction, stale requirement/policy evidence,
stale/revoked/future evidence, scope mismatch and malformed/tampered versions fail closed. Missing
or unknown rights and missing evidence yield
`REVIEW_REQUIRED`; contradictory requirements and unresolved multi-jurisdiction ambiguity yield
`BLOCKED`. The engine never silently selects the convenient rule.

## Gate and safety boundary

The foundation is governance infrastructure, not legal advice and not proof of compliance. It can
later supply versioned assessment and decision hashes to the existing
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
