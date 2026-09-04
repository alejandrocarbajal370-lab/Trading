# ADR 0011 — IBKR Reproducible Read-Only Local Observation Probe (Unauthenticated)

Status: **AUTHORIZED_TO_IMPLEMENT; EXPLICIT_LOCAL_OBSERVATION_UNAUTHENTICATED; PROVIDER ADMISSION NOT_AUTHORIZED**

## Decision

After PR #34, the user authorized an IBKR reproducible read-only observation probe under
`NEW_PR_REQUIRED` and `AFTER_CURRENT_BLOCK_MERGED`. It may run only by an
explicit local command against `127.0.0.1:7496`. It exposes only contract resolution, server time,
market-data-type selection/callback, bounded streaming observation, and bounded historical bars.
It has no account, position, balance, order, execution, signal, portfolio, sizing, rebalance or
backtest operation.

The pinned `ibapi==9.81.1.post1` dependency is optional (`ibkr-probe` extra), so ordinary CI and
research installations acquire no broker SDK. Deterministic CI transports are
`CONTRACT_TEST_ONLY`; the public capture boundary always derives that classification and ignores
caller provenance claims. The localhost path emits only
`LOCAL_IBKR_OBSERVATION_UNAUTHENTICATED`. Python code, methods, classes, callbacks and process-local
secrets cannot establish external authenticity because all are caller-replaceable. No local signer,
HMAC key or boundary attestation exists. A cryptographically authenticated REAL classification is
deferred until an independently provisioned external trust root and attester exist. Automatic
account-list callbacks are discarded before logging or storage.
Errors persist only request ID, numeric code and a governed category; provider text and exception
chains are discarded.

MSFT is the sole allowed instrument. Its code-owned binding fixes symbol, type, SMART route,
NASDAQ primary exchange, USD and IBKR conId 272093. The resolved contract must match every field.
The binding is observation lineage only and explicitly `NOT_PROVISIONED` for provider admission.
ASCII literals and exact enums reject Unicode confusables and ambiguous substitutions.

## Evidence and trust boundary

Evidence binds provider/adapter/API/server versions, request ID/hash, instrument and symbology
lineage, resolved contract, UTC request/retrieval/observation/server/event timestamps, the official
IBKR mode code and distinct `REALTIME`, `FROZEN`, `DELAYED`, `DELAYED_FROZEN`, and `UNKNOWN`
semantics, tick presence or `ABSENT_TIMEOUT`, bounded OHLCV, sanitized status/error metadata, and
internally computed raw/material/provenance/evidence digests. These hashes bind content but do not
authenticate its external origin. The callback-derived mode describes only the reported observation
and cannot authenticate the transport. A timeout never becomes a price,
volume, zero tick, or realtime claim. Streaming and historical channels carry separate statuses;
historical-only evidence is `PARTIAL` with streaming `TIMEOUT_NO_DATA`, never aggregate `SUCCESS`.
Daily bar dates are canonical UTC session dates and must fall inside the request's sealed two-day
window. Deep validation recomputes raw and material digests from the canonical observed fields.
Rejected external values and nested validation errors are erased before a sanitized boundary error
is raised, including exception cause/context. Caller-controlled dumps, serializers, properties,
representations and string conversions execute only inside that sanitizing boundary.

All output remains `OBSERVED_UNTRUSTED`: never `VERIFIED`, `TRUSTED`, `QVM_ADMISSIBLE`, provider
admission, custody, WORM, legal evidence, gate closure or REAL truth created by fixtures. All ten
gates remain `OPEN_EXTERNAL`; `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`, `NO_TRADE`, disabled signals
and live execution, and `NOT_AUTHORIZED` backtesting remain frozen.

## Successor

No machine-readable successor is selected. `AFTER_NEXT_BLOCK` remains `UNDETERMINED`,
`implementation_authorized=false`, `activation_real=false`, and
`ARCHITECTURAL_DECISION_REQUIRED`. Tax Lot remains future-only.
