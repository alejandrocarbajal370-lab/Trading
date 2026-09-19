# CORSO Equity/FI Engine Monitor — Dashboard Data Contract

Status: **CONTRACT FOR A FUTURE FEED; UI ALREADY BUILT AGAINST IT.** This document does not
authorize any engine, execution, backtesting or portfolio capability, and does not change Step 6
gate status, `trade_decision` or `signals_generated`. It exists so a future export from this repo
can replace a mock seam in `corso-dashboard` with a real feed, without any UI change.

## Where this lives today

`corso-dashboard`'s Research tab now renders an **Equity Engine Monitor** and a **Fixed Income
Engine Monitor** (`src/components/panels/EngineMonitor.tsx`), reading through the same seam pattern
as every other panel (`src/lib/data-source.ts` → `getEquityMonitor()` / `getFixedIncomeMonitor()`).
Today those functions return static objects in `src/lib/mock-data.ts` (`equityMonitor`,
`fixedIncomeMonitor`) that were populated by reading this repo's actual source — gate names from
`governance/phase7e.py`, factor metric names/formulas from `factors/{quality,value,momentum}.py`,
FI target scope from `docs/scope/corso-investment-os-north-star.md` — not fabricated. Every number
that has no real run behind it renders as `NOT_COMPUTED`, never an invented figure.

To go from "static and accurate as of today" to "live," a future export job in this repo (owned by
this repo's own development, not `corso-dashboard`) needs to produce JSON matching the shapes
below, and `corso-dashboard`'s two seam functions need their bodies changed to fetch it — no
component or type in the dashboard needs to change.

## `EquityMonitorSnapshot`

Mirrors `corso-dashboard/src/lib/types.ts:EquityMonitorSnapshot`.

```jsonc
{
  "asOfCommit": "string — repo ref/commit this snapshot reflects",
  "tradeDecision": "string — current governance/roadmap.py trade_decision, e.g. NO_TRADE",
  "signalsGenerated": false,
  "readiness": "string — current readiness state, e.g. INSUFFICIENT_REAL_DATA",
  "realRoute": "string — current real-route state, e.g. QVM_NOT_READY",
  "gates": [
    { "gate": "HISTORICAL_PIT_SECURITY_MASTER", "state": "OPEN_EXTERNAL" }
    // ... exactly the 10 governance/phase7e.py:EvidenceGate values, each with its GateState
  ],
  "universe": {
    "totalScanned": 0,
    "admitted": 0,
    "excluded": 0,
    "exclusionReasons": [{ "reason": "string", "count": 0 }]
    // populate from universe/diagnostics.py:diagnose_universe() output
  },
  "factorFamilies": [
    {
      "factor": "Quality", // or "Value" / "Momentum"
      "rulesetVersion": "string — e.g. factors/quality.py version/tag",
      "sourceModule": "factors/quality.py:QualityFactorContract",
      "coveragePct": null, // admitted securities with a computed observation / admitted universe size, or null
      "avgConfidence": null, // mean FactorObservation.confidence across admitted observations, or null
      "metrics": [
        {
          "name": "roic", // factors/quality.py metric definition name — do not rename
          "formula": "operating_income * (1 - tax_rate) / (total_debt + total_equity - cash)",
          "unit": "ratio",
          "status": "NOT_COMPUTED", // or "PENDING_REAL_DATA" or "OBSERVED"
          "value": null // only non-null when status is "OBSERVED", and then it's an aggregate
                          // (e.g. cross-sectional median), never a single security's number
        }
        // one entry per metric definition already declared in that factor's contract
      ]
    }
  ],
  "researchDimensions": [
    { "name": "Quality", "status": "PARTIAL", "detail": "string, human-readable" }
    // the 7 dimensions from docs/scope/corso-investment-os-north-star.md's Equity target section:
    // Quality, Value, Momentum, Fundamental Context, Expectations, Capital Loss, Confidence
  ],
  "validation": {
    "overallStatus": "string", // ValidationManifest.overall_status
    "criticalErrors": 0,       // ValidationManifest.critical_errors
    "warnings": 0,             // ValidationManifest.warnings
    "checks": [{ "name": "string", "status": "string" }] // ValidationManifest.checks, flattened
                                                          // from dict[str,str] to a list of pairs
  }
}
```

Aggregation rule for `factorFamilies[].metrics[].value`: this is a monitor, not a security-level
data export. It must never carry a single symbol's observation — only a cross-sectional aggregate
(e.g. median or admitted-universe mean) computed from `FactorObservation` rows already produced by
`evaluate_quality_metrics` / `evaluate_value_metrics` / `evaluate_momentum_metrics`, and only once
those observations exist for an admitted universe under a real run.

## `FixedIncomeMonitorSnapshot`

Mirrors `corso-dashboard/src/lib/types.ts:FixedIncomeMonitorSnapshot`. Today this is intentionally
static — there is no FI engine module yet — and exists to let the dashboard's foundation render
correctly on day one of real FI work, by flipping individual capability statuses as they land:

```jsonc
{
  "status": "FOUNDATION_NOT_STARTED", // flip only when the first FI capability below ships
  "track": "string — current FI track framing, from the Investment OS North Star",
  "targetScope": "US investment-grade corporate bonds — USD / fixed-rate / bullet / non-callable / non-puttable",
  "targetCapabilities": [
    { "name": "Deterministic contractual cash flows", "status": "NOT_IMPLEMENTED" }
    // one entry per capability in the FI Foundation list (Investment OS North Star, FI track
    // section); flip to "IN_PROGRESS" / "IMPLEMENTED" only as each capability is actually built
    // and validated per that section's own validation requirements — never ahead of that work
  ],
  "sharedFoundations": [
    { "name": "Governed Data Core (Security Master, PIT FX, curves)", "status": "IN_PROGRESS" }
  ]
}
```

## Non-goals

This contract is a read-only reporting shape. It must not become a second way to trigger, gate or
authorize engine work — flipping a status in this feed has no side effect other than what the
Dashboard displays. It also does not define how the feed is transported (file, API, database write)
between this repo and `corso-dashboard`; that is a separate, later decision once there is an actual
producer for this data.
