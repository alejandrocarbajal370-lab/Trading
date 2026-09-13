# Historical PIT Equity dataset files

`pit-equity-qvm-build` turns four checksum-pinned CSV exports into the existing canonical
cross-layer artifacts and runs the research-only Equity QVM engine. It does not download data or
change readiness, trading, execution, or provider-admission state.

The manifest uses schema `pit-equity-research-files-v1` and declares:

- `universe.csv`: the columns in `universe.validation.REQUIRED_COLUMNS`; a stable `permanent_id`
  is strongly recommended. Every membership timestamp must be known by `as_of`.
- `market_data.csv`: the columns in `data.market_data.REQUIRED_COLUMNS`, plus explicit confidence
  inputs. Daily sessions must be complete, raw and adjusted prices must reconcile through
  `adjustment_factor`, and applied corporate actions must name a supported type.
- `accounting.csv`: the columns in `fundamentals.governance.ACCOUNTING_REQUIRED_COLUMNS`, plus
  `fiscal_period_start`, `period_type`, and confidence inputs. The file must contain the complete
  revision chain available by `as_of`, not merely the latest values.
- `fx.csv`: the columns in `data.fx.FX_REQUIRED_COLUMNS`, including fix and availability times.

Each `files` entry has a path relative to the manifest and the SHA-256 of the exact raw export.
The remaining fields specify timezone-aware `as_of` and `dataset_available_at`, provider source
and version, base currency, benchmark, calendar, explicit staleness limits, universe rules, and
the required fundamental metrics.

```json
{
  "schema_version": "pit-equity-research-files-v1",
  "source": "licensed-provider-file-export",
  "dataset_version": "provider-release-id",
  "experiment_id": "pilot-2025-03-15",
  "as_of": "2025-03-15T23:59:00Z",
  "dataset_available_at": "2025-03-15T23:59:00Z",
  "base_currency": "USD",
  "benchmark_symbol": "SPY",
  "trading_calendar": "XNYS",
  "maximum_price_staleness_sessions": 1,
  "maximum_fx_staleness_sessions": 5,
  "universe_rules": {"allowed_exchanges": ["NYSE", "NASDAQ"]},
  "required_fundamentals": [
    "capital_expenditures", "cash", "cash_from_operations", "ebit", "ebitda",
    "net_income", "operating_income", "revenue", "tax_rate", "total_assets",
    "total_debt", "total_equity"
  ],
  "files": {
    "universe": {"path": "universe.csv", "sha256": "<sha256>"},
    "market_data": {"path": "market_data.csv", "sha256": "<sha256>"},
    "accounting": {"path": "accounting.csv", "sha256": "<sha256>"},
    "fx": {"path": "fx.csv", "sha256": "<sha256>"}
  }
}
```

Run `pit-equity-qvm-build --manifest manifest.json --output-root research_outputs/pit`. The output
contains canonical universe, market, accounting and FX conversion artifacts; their manifest and
fingerprints; Q/V/M metric files; and `qvm_coverage.json`. A series for backtesting is formed by
running one immutable manifest per historical cutoff. Real-data readiness remains `NOT_READY`.
