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

The contracts bind public provider/dataset/adapter identity, receipt times and replay identity,
independent authority snapshots, and maker-checker decisions. Credential material and reversible
secret locators are not representable. The aggregate reconstructs primitive inputs, recomputes
hashes, requires exactly ten gates, and rejects binding, replay, staleness, signature, chronology,
revocation-timing and caller-authored-truth attacks. The 24-hour maximum evidence age is code-owned,
not caller-configurable. A real provider-specific verifier and external
trust root remain absent.

## Frozen safety state

- authority/trust root: `NOT_PROVISIONED`
- 10/10 gates: `OPEN_EXTERNAL`
- real route: `QVM_NOT_READY`; global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`; live execution and signals disabled
- backtesting: `NOT_AUTHORIZED`

No fixture-to-REAL promotion, provider approval, WORM proof, scoring/ranking, portfolio, target,
broker, order, execution, backtest, dashboard or Excel capability is introduced. Independent audit
is required before adding any real adapter, trust root, legal authority or gate-state transition.
