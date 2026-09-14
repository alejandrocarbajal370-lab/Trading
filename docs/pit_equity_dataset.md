# Historical PIT Equity dataset files

`pit-equity-qvm-build` turns four checksum-pinned CSV exports into the existing canonical
cross-layer artifacts and runs the research-only Equity QVM engine. It does not download data or
change readiness, trading, execution, or provider-admission state.

The manifest uses schema `pit-equity-research-files-v1` and declares:

- `universe.csv`: the columns in `universe.validation.REQUIRED_COLUMNS`; a stable `permanent_id`
  is strongly recommended. It must also carry `membership_as_of`, `membership_source`, and
  `membership_snapshot_id` on every row. These must exactly match the manifest's cutoff, source,
  and snapshot identity.
- `market_data.csv`: the columns in `data.market_data.REQUIRED_COLUMNS`, plus explicit confidence
  inputs. Daily sessions must be complete, raw and adjusted prices must reconcile through
  `adjustment_factor`, and applied corporate actions must name a supported type. The manifest
  explicitly declares whether the provider series covers splits only or splits and cash dividends.
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
  "universe_snapshot": {
    "claim": "PROVIDER_SUPPLIED_PIT_SNAPSHOT",
    "snapshot_id": "provider-membership-release-id",
    "source": "licensed-provider-file-export",
    "as_of": "2025-03-15T23:59:00Z"
  },
  "price_adjustment": {
    "series_usage": "FACTOR_RESEARCH_ONLY",
    "adjustment_scope": "SPLIT_AND_CASH_DIVIDEND",
    "portfolio_return_eligible": false
  },
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
fingerprints; Q/V/M metric files; and `qvm_coverage.json`. A historical research series is formed by
running one immutable manifest per cutoff; that is not a backtest. Raw-file SHA-256 values identify
the exact export and therefore change when row order changes; canonical normalized fingerprints are
designed to remain invariant when only row order changes.

The universe claim is deliberately limited to **user/provider-supplied PIT universe snapshot**.
The builder binds every row to that claim, source, cutoff, and snapshot ID, but cannot independently
prove historical constituent truth or eliminate survivorship bias. Reconstructing an old universe
from today's surviving securities is prohibited. Authoritative historical membership snapshots are
required before any result can be described as survivorship-safe or Research Grade.

Adjusted prices are admitted only for factor and momentum research. Successful import does not make
them suitable for portfolio returns: dividend timing/reinvestment, delisting returns, and return
accounting are intentionally absent. `source_manifest.json` and `qvm_coverage.json` record
`portfolio_return_ready: false` so downstream consumers cannot silently infer otherwise.

Two blockers remain before the first legitimate backtest:

1. Real licensed or otherwise authorized, survivorship-safe PIT historical inputs with sufficient
   coverage for Research Grade.
2. A backtest engine implementing historical cutoff iteration, portfolio/cohort formation,
   rebalance transitions, delisting handling, transaction costs, portfolio and benchmark returns,
   and statistics.

Neither blocker is resolved by this importer. Real-data readiness remains `NOT_READY`.
