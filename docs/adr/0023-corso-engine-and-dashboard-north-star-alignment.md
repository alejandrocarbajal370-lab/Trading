# ADR 0023 — CORSO Engine and Dashboard North Star Alignment

Status: **ACCEPTED TARGET DIRECTION; DOCUMENTATION ONLY; NO IMPLEMENTATION AUTHORIZATION**

## Decision

CORSO adopts two separate canonical target-direction documents:

- [Investment OS Engine North Star](../scope/corso-investment-os-north-star.md); and
- [Dashboard Multi-Asset Experience North Star](../scope/corso-dashboard-north-star.md).

They are separated from this ADR so the decision, engine scope and interaction architecture can
evolve through governed changes without turning one ADR into a monolith. ADR 0020's permanent
human-only boundary, ADR 0021's Step 6 state and ADR 0022's valid USA/Mexico, Fixed Income,
recovery/LGD, curve and multi-asset scope remain binding except for the narrow supersessions below.

## Scope-state vocabulary

- `IMPLEMENTED`: repository evidence provides the working capability.
- `FOUNDATION`: contracts or mechanics exist, but do not prove REAL readiness.
- `ACTIVE SECONDARY DEVELOPMENT TRACK`: roadmap priority only; not implementation authority.
- `FUTURE / NOT_IMPLEMENTED / NOT_AUTHORIZED`: target direction with no current capability or work
  authorization.

Documentation, schema, interface, fixture and connectivity are not implementation, entitlement,
trust, admission or REAL evidence.

## Supersessions and interpretation

1. Fixed Income is now an `ACTIVE SECONDARY DEVELOPMENT TRACK` in target roadmap direction, rather
   than an indefinite future idea. It remains `NOT_IMPLEMENTED`, and each work still requires
   separate authorization after applicable prerequisites.
2. Broker X/GBM is absolutely disconnected from CORSO. Earlier ADR 0020 and README target language
   that allows Broker X statements, CSV, XLSX, screenshots, photos, PDFs, reports, uploads or other
   files as ingestion interfaces is superseded. No Broker X API, scraping, browser automation,
   stored credential or order route is permitted. Human-executed real operations enter through
   structured manual CORSO Data Intake only.
3. The valid architecture behind those historical ingestion descriptions—append-only economic
   events, validation, reconciliation, provenance, corrections/void/supersession and audit—is
   preserved and reused.
4. `PAPER_IBKR` is the official future simulated-trading test environment; it is distinct from
   `RESEARCH` and `PRODUCTION_EXTERNAL`. This does not authorize paper workflows now.
5. AURORA terminology in immutable historical records is interpreted as the former name. Current
   canonical product direction uses CORSO; compatibility-sensitive identifiers are not renamed by
   this documentation work.

## Roadmap reconciliation

The target direction is transition audit and scope alignment, Equity V1, Equity Shadow with a
minimal research UI, FI Foundation in parallel, FI validation, full institutional dashboard,
advanced engines and finally a separately authorized Portfolio Engine.

That target sequence is subordinate to the current real roadmap. It cannot bypass Step 6 external
gates, REAL provider admission, PIT/data governance or later explicit authorizations. The current
machine-readable `NEXT_BLOCK` remains **Durable Custody + WORM + Replay**, `CONTRACT_TEST_ONLY`,
`NEW_PR_REQUIRED`; REAL activation remains unauthorized. Its named successor Licensing/legal
remains `NOT_AUTHORIZED / ARCHITECTURAL_DECISION_REQUIRED`.

## Classification of existing architecture

| Decision | Existing material | Treatment |
| --- | --- | --- |
| KEEP | ADR 0021 and current fail-closed Step 6/gate state | Unchanged and authoritative |
| KEEP | ADR 0020 human-only execution and structural asset protection | Permanent boundary |
| REUSE | ADR 0022 USA/Mexico, FI, recovery/LGD, curves and multi-asset target | Incorporated by reference and refined |
| REUSE | append-only ledger, validation, reconciliation, provenance and audit concepts | Retained behind manual Data Intake |
| ALIGN | FI roadmap priority and narrow Phase 1 universe | Active secondary direction, not current implementation |
| ALIGN | dashboard, environment semantics, identity and capability admission | Defined in the Dashboard North Star |
| DEPRECATE_LATER | historical AURORA naming and Broker X file-ingestion assumptions | Preserve history; supersede active interpretation |
| OUT_OF_SCOPE_NEW_WORK | engine/dashboard code, PostgreSQL, optimizer, backtesting, live/paper execution | Not performed or authorized |

## Safety state

- Step 5: `CLOSED`.
- Step 6: **STARTED — FOUNDATION ONLY; NO GATES CLOSED**.
- 10/10 gates: `OPEN_EXTERNAL`.
- REAL dependencies: `NOT_PROVISIONED` where current governance states so.
- REAL route: `QVM_NOT_READY`; global readiness: `INSUFFICIENT_REAL_DATA`.
- `trade_decision=NO_TRADE`; `signals_generated=false`.
- `execution_authority=HUMAN_ONLY`; `human_execution_required=true`;
  `live_execution_enabled=false`.
- Backtesting and portfolio construction: `NOT_AUTHORIZED`.

This ADR authorizes no engine, dashboard, FI, optimizer, database, provider, backtest, paper-trading
or execution implementation and closes no gate.
