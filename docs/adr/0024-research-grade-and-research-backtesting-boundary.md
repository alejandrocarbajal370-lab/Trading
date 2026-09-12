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

Admission evaluates one complete, identified dataset snapshot from canonical repository artifacts.
It requires independently verifiable evidence for:

- PIT chronology and no look-ahead;
- provenance and lineage;
- dataset identity and checksum verification;
- reproducibility;
- restatement handling;
- universe and survivorship handling;
- corporate-action handling; and
- prohibition of silent imputation.

Caller-declared control states, hashes, fingerprints, lineage strings, and `NOT_REQUIRED` reasons
are not evidence. Dataset checksums are recomputed against the registered file through
`research/datasets.py`; governed universe snapshots are verified through the same existing module.
A checksum or snapshot verification error yields `FAILED_RESEARCH_DATA`.

The repository does not yet expose canonical artifacts that jointly verify PIT/no-lookahead,
content-bound lineage, reproducibility, restatement applicability and handling, corporate-action
applicability and handling, and absence of silent imputation. Therefore even currently valid
dataset and universe artifacts yield `INSUFFICIENT_RESEARCH_DATA`. There is intentionally no
positive authorization path until every required condition can be machine-verified. A conditional
control may be treated as not applicable only when a future canonical artifact makes that
determination; free-form caller justification is never sufficient.

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
