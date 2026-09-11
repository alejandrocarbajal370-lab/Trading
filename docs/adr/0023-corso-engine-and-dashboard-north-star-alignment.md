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
machine-readable `NEXT_BLOCK` is **Step 6 External-Gate Remediation — Pending Canonical
Scheduling**. It is a fail-closed placeholder with `PENDING_CANONICAL_SCHEDULING`,
`NO_IMPLEMENTATION_AUTHORIZED`, empty implementation scope and REAL activation unauthorized.
The repository does not canonically select a more specific successor after the already integrated
Durable Custody + WORM + Replay (PR #41), Licensing/legal (PR #42), Step 5 (PR #43) and Step 6
foundation (PR #45), so no phase is invented here.

## Deferred GBM Broker Execution Profile

GBM is the selected Broker X but remains completely disconnected from CORSO: no API, scraping,
browser automation, credentials, sessions/tokens, CSV/XLSX/Excel, PDF, screenshots, photos, OCR,
broker reports, file upload, automated ingestion or order routing. The only future path is
`HUMAN_VALIDATED_MANUAL_ENTRY` / `MANUAL_STRUCTURED_INPUT` through Data Intake; real operations
must never be hard-coded. This is deferred target scope only and implements neither Data Intake nor
a ledger.

A future versioned Broker Execution Profile and validation metadata must keep broker particulars
out of universal core rules and must:

- distinguish `GBM_TRADING_MX` and `GBM_TRADING_USA` as account/broker environments or account
  types, with manual `strategy_id` where applicable; keep universe/model eligibility separate from
  GBM executability;
- support Trading USA fractional shares with exact `DECIMAL`/`NUMERIC` quantity as source of truth,
  never `INTEGER` or `FLOAT`; record DriveWealth only as optional intermediary/custodian metadata
  when relevant, while GBM remains the broker;
- preserve original currency, at minimum MXN/USD, without destructive presentation conversion;
  preserve separate `proposal_timestamp`, `manual_order_timestamp`, `execution_timestamp`,
  `trade_date` and `settlement_date` when available;
- represent settled, unsettled, available-to-trade and available-to-withdraw cash separately only
  when reliable support exists; treat manually observed fees/commissions as facts and broker fee
  schedules only as versioned validation references that never overwrite execution facts;
- record tax, W-8BEN and withholding only as observed metadata/events—CORSO is not a tax engine;
- provide an event taxonomy including `DIVIDEND`, `STOCK_DIVIDEND`, `SPLIT`, `REVERSE_SPLIT`,
  `SPIN_OFF`, `MERGER`, `TENDER`, `RETURN_OF_CAPITAL`, `SYMBOL_CHANGE`, `CASH_IN_LIEU` and applicable
  FI-specific events; a split is never a fabricated purchase;
- maintain future lots/cost basis under `corso_lot_id` without relying on GBM cost basis for
  reconstruction; reconciliation is manual-assisted and differences become
  `RECONCILIATION_EXCEPTION`, never silent correction;
- correct promoted history only through linked `CORRECTION`, `REVERSAL`, `VOID` or `SUPERSESSION`,
  never physical deletion; mark suspected duplicates `POTENTIAL_DUPLICATE` without automatic
  deduplication; and
- preserve minimum provenance `source_type=MANUAL_ENTRY`, `external_source=GBM`,
  `entered_by=HUMAN`, never `GBM_API`, under the truth hierarchy Real World Execution → Human
  Validated Input → Canonical Ledger → Calculated State → Investment Intelligence. Higher layers
  never rewrite lower layers to force agreement.

Fractionals, DriveWealth, order types, fees, funding, settlement, W-8BEN and similar details belong
in that versionable profile/validation metadata, not in universal core logic.

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
