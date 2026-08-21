# Phase 5 — QVM Research Framework V1

## Scope

This phase aligns and describes existing Quality, Value, and Momentum observations. It does
not combine them into an investment signal. The common contract preserves each individual
metric, its point-in-time availability, confidence, lineage, and governed-universe identity.

## Integration audit

| Boundary | Control | Result |
|---|---|---|
| Quality / Value / Momentum | Existing factor outputs are adapted, not recalculated | PASS |
| Governed universe | The snapshot store is verified and its membership SHA-256 must match every batch | PASS |
| Point in time | One `as_of`; every `available_at` must be known by that date | PASS |
| Availability | One explicit availability policy is required | PASS |
| Entity | One entity policy and matching symbols are required | PASS |
| Lineage | Canonical universe, factor-dataset, PIT, ruleset, and policy identity is verified by SHA-256 | PASS |
| Market data | Momentum's adjusted-price and calendar lineage remains intact | PASS |
| Reproducibility | Canonical input and governance fingerprint; immutable outputs | PASS |

Each factor dataset hash is recomputed after sorting its observations canonically, so input order
does not alter dataset identity. The integrated lineage
hash is then recomputed from the universe snapshot, factor hashes, PIT date, ruleset version,
availability policy, and entity policy. Any declared/recomputed mismatch fails closed before a
matrix is generated. The QVM runner also requires the governed Universe Snapshot Store, verifies
its files and checksums, derives its snapshot ID, and compares its observed membership hash with
the batch declaration.

Correlation diagnostics are metric-to-metric only. The Metric Semantics Registry is keyed by
`(factor, metric)` and governs the owning factor, expected unit, economic direction, and comparison
group. Unknown ownership or a unit mismatch fails closed. A calculation is permitted only when
both metrics share an explicit comparison group; incompatible pairs return `NOT_AVAILABLE` and an
explicit reason. No aggregate factor correlation is emitted.

Conflict diagnostics also use the registry. `higher_is_better` and `lower_is_better` metrics are
interpreted relative to the governed cross-sectional median; `contextual` and `non_directional`
metrics are excluded. Thus a high positive EV/EBIT value is economically negative (expensive),
not positive merely because its numeric sign is positive.

Economic diagnostics have an explicit eligibility policy: only `PASS` observations participate.
`WARNING`, `LOW_CONFIDENCE`, invalid, missing, and not-computed statuses remain visible in the
matrix and exclusions, but cannot contribute correlation or directional-conflict evidence.
Coverage reports usable `PASS` values rather than repeating the already-enforced universe gate.

## Outputs

- `qvm_factor_matrix.csv` contains individual factor metrics and statuses by symbol.
- `qvm_health.json` contains coverage, missingness, overlap, correlation, sector, and conflict
  diagnostics.
- `qvm_lineage.json` preserves common and observation-level lineage.
- `qvm_validation_report.json` records alignment controls and prohibited-output assertions.

Normalization is metadata-only in V1. Z-score, percentile, and winsorization policy fields are
reserved, but no transformation is applied and no composite value is produced.

## Safety invariant

`NO_TRADE` remains active and `live_execution_enabled` remains `false`. No score, weights,
ranking, selection, portfolio, backtest, broker integration, order, or execution path exists.
