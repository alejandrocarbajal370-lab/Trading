# Phase 7A — governed real-data ingestion foundation

Status: **PARTIAL / NOT REAL-DATA READY**. Research-only invariants remain
`trade_decision=NO_TRADE`, `live_execution_enabled=false`, and `signals_generated=false`.

## Implementable now

SEC EDGAR `companyfacts` and `submissions` are public, credential-free APIs. The adapter requires
an identified contact `User-Agent`, enforces the SEC fair-access ceiling, preserves exact response
bytes in an append-only content-addressed store, and joins facts to the filing acceptance timestamp.
It never treats the provider `filed` date as an availability timestamp, invents confidence, infers
a CIK from a ticker, or silently accepts incomplete historical submissions.

The source is real, but `licensed_for_use` remains false by default pending project-specific legal
approval of licensing and retention. Even after that approval, ingestion evidence must be mapped,
governed, coverage-tested, and bound to sealed QVM batches before Fundamentals PIT can close.

## OPEN-EXTERNAL

- Fundamentals PIT: SEC ingestion implemented; legal approval, complete historical submission-file
  retrieval, explicit concept coverage/mapping, real confidence policy, and QVM binding remain open.
- FX: authoritative licensed historical PIT source remains open.
- Security master and historical constituents: permanent identity and PIT membership source open.
- Restatements: SEC filing versions are retained, but authoritative materiality/resolution feed open.
- Corporate actions: independent PIT action feed open.
- Shares outstanding PIT: governed multi-year source and dilution contract open.

Therefore the aggregate readiness gate remains `INSUFFICIENT_REAL_DATA`. No fixture or synthetic
payload may be used to change that state.
