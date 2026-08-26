# Phase 7B — Security Master + Historical Constituents PIT Foundation

Phase 7B contract-closes the synthetic/research boundary
`historical constituents + security master -> PIT reconstruction -> governed Universe -> sealed
Phase 7B/7A bridge -> SEC issuer plan`. It does not establish real historical-data readiness, map SEC
facts into Accounting/QVM, or authorize backtesting, signals, portfolios, orders, or execution.

The fixed state remains `global_readiness=INSUFFICIENT_REAL_DATA`, `trade_decision=NO_TRADE`,
`live_execution_enabled=false`, and `signals_generated=false`.

## Contract inventory

| Contract or policy | Version | State |
|---|---|---|
| Security Master PIT | `security-master-pit-v2` | CONTRACT-CLOSED with synthetic/adversarial evidence |
| Historical Constituents PIT | `historical-constituents-pit-v2` | CONTRACT-CLOSED with synthetic/adversarial evidence |
| Canonical artifact | `security-master-constituents-artifact-v2` | CONTRACT-CLOSED |
| Phase 7B -> Phase 7A SEC bridge | `phase7b-sec-mapping-bridge-v1` | CONTRACT-CLOSED |
| Listing state | `listing-state-half-open-v1` | CONTRACT-CLOSED |
| Symbology | `symbology-ticker-venue-class-type-v1` | CONTRACT-CLOSED |
| Structural relationships | `structural-lineage-dag-v1` | CONTRACT-CLOSED for the four supported structural types only |
| Bitemporal semantics | `effective-knowledge-correction-v1` | CONTRACT-CLOSED |
| Provider coverage manifest | `historical-provider-coverage-v1` | CONTRACT-CLOSED harness; real evidence OPEN-EXTERNAL |
| Real provider and licensed history | n/a | OPEN-EXTERNAL |
| Global real-data readiness | n/a | `INSUFFICIENT_REAL_DATA` |

`CONTRACT-CLOSED` means the typed synthetic contract and its negative tests are implemented. It does
not mean `REAL-DATA-VALIDATED`.

## Identity, listing, and symbology

`permanent_id` is security identity; `issuer_id` is issuer identity; ticker is only a temporal
attribute. Windows are half-open `[start, end)`. `DELISTED` requires `listing_end`; `ACTIVE` forbids it;
mapping validity cannot precede the listing or extend past a closed listing. Same-ID relisting is
represented by disjoint windows. A new security remains a new permanent ID.

The canonical symbology key is `(ticker, venue, share_class, security_type)`. Reuse by different IDs in
disjoint windows is allowed. Identical overlapping symbology is rejected. Same ticker on a different
venue or class is distinct under v1, but never becomes permanent identity.

## Structural relationship policy

Only `MERGER_PREDECESSOR`, `MERGER_SUCCESSOR`, `SPINOFF_PARENT`, and `SPINOFF_CHILD` are accepted.
They are representational identity lineage only. A separate graph validator rejects self-links,
unknown IDs, future knowledge, conflicting duplicate edges, cycles, and ambiguous multi-parent
mappings. It never rewrites historical permanent identity and contains no prices, ratios, allocation,
or other corporate-action economics. All other relation types are unsupported and fail Pydantic's
closed enum.

## Phase 7B -> SEC bridge and hashing

The bridge is built only from the sealed `PITReconstruction.securities`. It retains every
security-level `permanent_id`, `issuer_id`, CIK lineage, source record, availability, and validity
window while Phase 7A deduplicates issuer fetches by canonical CIK. The bridge binds its records to the
Phase 7B artifact hash, `as_of`, security-master hash, CIK mapping hash, and its own typed hash. The SEC
plan carries both artifact and bridge hashes. A stale/mutated record, artifact, bridge, universe
snapshot, plan, CIK, lineage, or `as_of` fails closed. Ticker inference and consumer-created mappings
are not part of this path.

All behavioral fields participate in the appropriate canonical `typed_hash`: security/issuer identity,
symbology and windows, CIK and source lineage, listing state, constituent entry/exit and revision
lineage, supported relationships, provider identity, coverage manifest, `as_of`, raw/source hashes,
runtime fingerprint, and every policy version. Both input collections are canonicalized, so real input
reordering preserves the artifact identity.

## Bitemporal and provider coverage semantics

Effective time is expressed by listing/member windows. Knowledge time is `available_at`; a fact cannot
appear before it was available even if economically effective earlier. Corrections are append-only,
carry revision/supersession lineage, and cannot rewrite an already reconstructed earlier snapshot.

The coverage manifest separates `available_at` from `acquired_at` and binds provider, dataset/version,
scope, temporal bounds, ordered snapshot/change sequence, raw hashes, evidence hashes, correction and
revision semantics, licensing, retention, and a conservative completeness enum. A current-only
snapshot, a sequence gap, missing evidence, or mutated raw hash cannot claim
`VERIFIED_WITHIN_DECLARED_SCOPE`. Even that scoped state does not change Phase 7B's fixed
`historical_completeness=false` or global readiness. An omitted exit is therefore never treated as
proof of continuing membership unless a future gap-free evidence sequence supports the claimed scope.

## Provider and legal gates

No real provider is connected. SEC ticker/CIK associations and Nasdaq symbol directories are current
or partial directories, not historical PIT membership/security-master completeness. Current web lists
must not be used as historical proxies. S&P DJI or another licensed historical provider requires a
separate approved agreement covering use, retention, derived artifacts, and redistribution, plus raw
content-addressed acquisitions and independent validation of coverage, corrections, chronology, and
stable identity.

SEC->Accounting/QVM, real confidence, FX, restatement materiality, corporate-action economics, shares
PIT, production WORM/object lock, provider scale/operations, and legal approval remain outside this
foundation and OPEN-EXTERNAL where applicable.

An independent integral audit of the new head is required before merge. The PR must remain DRAFT until
that audit distinguishes contractual correctness from real-data validation.
