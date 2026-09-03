# ADR 0009 — IBKR Read-Only Market Observation Adapter Foundation

Status: **AUTHORIZED_TO_IMPLEMENT; CONTRACT_TEST_ONLY; REAL NOT_AUTHORIZED / NOT_PROVISIONED**

## Decision

PR #32 completed **External Trust-Anchor Evidence Verification & Admission Foundation**. The next
code-owned block is **IBKR Read-Only Market Observation Adapter Foundation**, built in a new PR
`AFTER_CURRENT_BLOCK_MERGED`. IBKR is the first provider/venue-specific observation adapter, not the
only historical truth source and not an admitted REAL provider.
The implementation boundary is `NEW_PR_REQUIRED`.

The adapter exposes only `MARKET_OBSERVATION_READ_ONLY`. It has no order, execution, account,
portfolio, sizing or rebalancing capability. Prices/OHLCV are the sole initial dataset and are
`CONTRACT_TEST_ONLY`; corporate actions, security-master/symbology, shares PIT, FX and complementary
fundamentals remain `NOT_YET_PROVISIONED`.

Credentials remain outside the repository. The model stores only a SHA-256 reference digest and
always reports `NOT_PROVISIONED`. CI uses a hermetic fixture with no IBKR network access. Fixtures,
mocks and caller-controlled adapters cannot enter the sealed REAL route or claim
`PROVISIONED_REAL`.

Each raw envelope binds exact provider, adapter, dataset, endpoint, read-only scope, permanent
instrument identity and symbology lineage, requested and returned market-data mode, payload digest
and size, event/retrieval/observation UTC timestamps, status/error fields, and ordered cursor-linked
pagination. `UNKNOWN` fails closed for timing-sensitive use. Event time is distinct from retrieval
and availability time, preserving point-in-time semantics without claiming historical completeness.

## Trust and persistence boundary

The only handoff is `OBSERVED_UNTRUSTED`. No hash is authenticity, admission or legal evidence. No
fixture can yield `VERIFIED`, `TRUSTED`, `CLOSED`, QVM-admissible data, provider admission, custody,
WORM, authority, trust-root or independent-verifier receipts. Durable anti-replay storage is outside
this block and remains `NOT_PROVISIONED`; duplicate envelopes therefore make no REAL persistence or
replay-prevention claim.

All ten gates remain `OPEN_EXTERNAL`; `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`, `NO_TRADE`, disabled
signals and live execution, and unauthorized backtesting remain frozen.

## Successor condition

A later **IBKR Provisioned Read-Only Observation Evidence Foundation** may become the machine-readable
successor only after an explicit architectural decision defines secure external credential handling,
approved connectivity and licensing, operational ownership, and REAL capture evidence. Those
external conditions are absent, so this ADR does not authorize or invent that successor.
