# Validation outputs

Runtime validation artifacts are generated locally under a folder named by `run_id` and are intentionally ignored by Git.

Expected artifacts will grow by phase, for example:

```text
validation_outputs/<run_id>/
├── validation_manifest.json
├── 00_run_summary.json
├── 01_data_health.csv
├── 02_financial_validation.csv
├── 03_factor_diagnostics.csv
├── 04_factor_correlations.csv
├── 05_ic_history.csv
├── 06_decile_analysis.csv
├── 07_backtest_summary.csv
├── 08_drawdowns.csv
├── 09_ablation_results.csv
├── 10_parameter_sensitivity.csv
├── 11_robustness_tests.csv
├── 12_portfolio_validation.csv
├── 13_risk_checks.csv
├── 14_orders.csv
├── 15_execution_validation.csv
├── 16_reconciliation.csv
├── 17_model_live_gap.csv
└── validation_report.xlsx
```

Phase 0 currently emits `ingested_prices.csv`, `data_health.json`, `run_summary.json`, and
`validation_manifest.json`. Every Phase 0 summary explicitly records live execution as disabled
and the trade decision as `NO_TRADE`.

Not all files exist in Phase 0. A report is enabled only when its underlying subsystem exists.
