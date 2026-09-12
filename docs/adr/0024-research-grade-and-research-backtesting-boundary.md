# ADR 0024 — Research Grade and Research-Backtesting Boundary

Status: **ACCEPTED — CONTRACT ONLY; NO BACKTESTER OR PRODUCTION AUTHORITY**

## Decision

CORSO has two distinct admission tracks. `RESEARCH_GRADE` is a research-data contract that may
authorize only research backtesting. `PRODUCTION_GRADE` remains a separate future production
admission outcome. Research admission is not an `EvidenceGate` or `GateState`, is outside Step 6,
does not close a REAL gate, and cannot be implicitly promoted to production.

The machine-readable contract lives in `research/data_grade.py`. Its authorization name is
deliberately explicit: `RESEARCH_BACKTESTING_AUTHORIZED`. Existing production-facing
`backtesting="NOT_AUTHORIZED"` declarations retain their current meaning and are unchanged.

## Research-grade admission

Admission evaluates one complete, identified dataset snapshot. It requires immutable dataset
checksums, non-empty lineage, a reproducibility fingerprint, and explicit control states for:

- PIT chronology and no look-ahead;
- provenance and lineage;
- dataset identity and checksum verification;
- reproducibility;
- restatement handling;
- universe and survivorship handling;
- corporate-action handling; and
- prohibition of silent imputation.

PIT/no-lookahead, provenance, identity/checksums, reproducibility, universe/survivorship and no
silent imputation are always required. Restatement and corporate-action handling may be
`NOT_REQUIRED` only when explicitly inapplicable to that dataset. Any `INSUFFICIENT` control yields
`INSUFFICIENT_RESEARCH_DATA`; any `FAILED` control yields `FAILED_RESEARCH_DATA`. Both deny research
backtesting and carry exact reasons. Missing, malformed, extra or ambiguous fields fail validation.

`RESEARCH_GRADE` permits exactly `RESEARCH` and `RESEARCH_BACKTESTING` consumers. This ADR creates
no backtesting engine and does not assert that any existing dataset has passed admission.

## Production, portfolio and execution boundary

Every research admission permanently carries:

- `production_grade=false` and `implicit_production_promotion=false`;
- `portfolio_authorized=false` and `execution_authorized=false`;
- `trade_decision=NO_TRADE` and `signals_generated=false`;
- `execution_authority=HUMAN_ONLY` and `human_execution_required=true`; and
- `live_execution_enabled=false`.

The contract exposes an explicit future consumer boundary that rejects every research admission
and requires a separate `PRODUCTION_GRADE` contract. Future portfolio and execution modules must
accept only that distinct production type/contract; they must never accept or structurally coerce
a `ResearchGradeAdmission`.

## Unchanged production state and non-goals

Step 6 and ADR 0021 remain unchanged. All 10/10 production gates remain `OPEN_EXTERNAL`; REAL trust,
legal, custody/WORM, independent verification and provider admission remain external; the REAL QVM
route remains `QVM_NOT_READY`; global readiness remains `INSUFFICIENT_REAL_DATA`; GBM remains fully
disconnected/manual-only future Data Intake; and PAPER_IBKR remains not operationally authorized.

This ADR does not build a backtester, portfolio simulation, optimizer, fixed-income engine,
dashboard, database, provider admission, canonical upstream observation foundation, portfolio or
execution module. It does not change REAL verification or gate machinery.
