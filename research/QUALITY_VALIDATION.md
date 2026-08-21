# Quality Validation Report

Phase 4.1.2 validates whether Quality V1.1 observes the governed investment universe coherently before any Value, Momentum, ranking, portfolio, or execution work begins.

## Purpose

The report is descriptive research infrastructure. It answers four questions:

1. What fraction of the eligible universe has observable and passing Quality metrics?
2. What do the cross-sectional metric distributions look like, including descriptive outliers?
3. Which eligible companies have no usable Quality observations and therefore must remain visible rather than disappear from research?
4. Do historical ROIC, free cash flow, and FCF-margin inputs show improvement or deterioration over the available validated history?

The report never creates a Quality score, ranking, trade recommendation, portfolio target, or order. Every run records `NO_TRADE` and `live_execution_enabled=false`.

## Inputs

`quality-validation-run` consumes:

- a `quality_metrics.csv` produced by Quality V1.1;
- a governed `universe_membership.csv`;
- optionally the validated financial-metrics history used for descriptive trend analysis.

The caller also supplies the experiment ID, universe snapshot ID, and financial dataset snapshot ID. Input file SHA-256 hashes are embedded in the reproducibility fingerprint.

## Coverage

Coverage is measured against **eligible universe members**, not only companies that happen to have Quality data.

For each core Quality metric the report records:

- eligible symbols;
- observed symbols;
- passing symbols;
- observed coverage;
- pass coverage;
- status counts.

An eligible company with no Quality data is retained in `quality_availability.csv` as `DATA_UNAVAILABLE`. A company with Quality observations but no passing metrics is retained as `NO_PASSING_QUALITY_METRICS`.

The default minimum pass-coverage warning threshold is 70% and is configurable. It is a research-health threshold, not an investment threshold.

## Distributions and outliers

For passing observations only, the report records P10/P25/P50/P75/P90, minimum, maximum, and sample count. Descriptive outliers use the standard 1.5x-IQR rule. Outlier status does not imply that an observation is wrong or unattractive; it only requires research review.

## Trends

When validated historical financial metrics are supplied, the report emits descriptive trends for:

- `roic_v1` -> `roic_trend`;
- `free_cash_flow` -> `fcf_trend`;
- `free_cash_flow_margin` -> `margin_trend`.

Direction is based only on the sign of the change between the first and latest comparable passing observation: `IMPROVING`, `DECLINING`, or `FLAT`. V1.2 intentionally assigns no economic score or materiality threshold to that direction.

## Health

The validation health is:

- `FAIL` for an empty eligible universe, invalid lineage, PIT violations, or no passing Quality metrics across the eligible universe;
- `WARNING` for insufficient coverage, unavailable eligible companies, or descriptive outliers;
- `PASS` otherwise.

Lineage and PIT failures are never silently downgraded.

## Outputs

A reproducible run writes:

- `quality_validation_report.json`;
- `quality_availability.csv`;
- `quality_trends.csv`.

These outputs are intentionally dashboard-ready but remain research artifacts rather than trading inputs.

## Example

```bash
quality-validation-run \
  --quality-metrics research_outputs/quality_run/quality_metrics.csv \
  --universe-membership validation_outputs/universe_run/universe_membership.csv \
  --financial-metrics validation_outputs/financial_run/financial_metrics.csv \
  --experiment-id quality-validation-001 \
  --universe-snapshot-id universe-2026-08-01 \
  --dataset-snapshot-id financial-2026-08-01
```
