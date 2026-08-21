# Phase 5 — QVM Research Framework V1

## Scope

This phase aligns and describes existing Quality, Value, and Momentum observations. It does
not combine them into an investment signal. The common contract preserves each individual
metric, its point-in-time availability, confidence, lineage, and governed-universe identity.

## Integration audit

| Boundary | Control | Result |
|---|---|---|
| Quality / Value / Momentum | Existing factor outputs are adapted, not recalculated | PASS |
| Governed universe | One identical `universe_snapshot_id` is required | PASS |
| Point in time | One `as_of`; every `available_at` must be known by that date | PASS |
| Availability | One explicit availability policy is required | PASS |
| Entity | One entity policy and matching symbols are required | PASS |
| Lineage | One integrated lineage identity plus per-observation lineage is required | PASS |
| Market data | Momentum's adjusted-price and calendar lineage remains intact | PASS |
| Reproducibility | Canonical input and governance fingerprint; immutable outputs | PASS |

Any alignment mismatch fails before a matrix is generated.

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
