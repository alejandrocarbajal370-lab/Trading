# Equity QVM Backtest Engine V1

This is a deterministic research simulator, not an execution or production component. It consumes
an ordered sequence of checksum-pinned PIT manifests and hash-verified canonical Phase 6 QVM
artifacts. Current outputs are always labelled `DETERMINISTIC_FIXTURE_BACKTEST`; they never claim
Research Grade, survivorship safety, portfolio authority, or real-data readiness.

## Frozen baseline

- Select QVM cohort `TOP` rows whose capital-preservation overlay is `PASS`.
- Equal-weight the selected securities. There is no optimizer or parameter tuning.
- A signal known at cutoff may enter holdings only at its explicitly declared later rebalance time.
- Charge 10 bps times one-way turnover by default. The preregistered V1 range is 0–50 bps.
- Use a zero annual risk-free rate and 12 periods per year by default. Both are explicit inputs.
- Compute gross and net return, turnover, cumulative and annualized return, annualized volatility,
  Sharpe, maximum drawdown, hit rate, and observation/rebalance counts.
- Compare a benchmark only when a complete series is supplied and explicitly declared PIT-valid.

Portfolio returns use the separate convention
`USD_TOTAL_RETURN_WITH_DISTRIBUTIONS_AND_DELISTINGS`. The factor-research adjusted prices admitted
by the PIT dataset builder are forbidden as a silent substitute. Every held security needs an
observation for every period, including an explicit delisting treatment; missing observations fail
the run rather than disappearing from the portfolio.

The result is content-addressed over manifest checksums, canonical QVM artifact hashes, parameters,
engine/model versions, cutoff range, holdings, transitions, returns, and statistics. Input manifest
checksums and QVM model hashes are revalidated when loaded. Duplicate or non-monotonic cutoffs,
duplicate manifests, look-ahead chronology, incomplete benchmark coverage, and inconsistent return
contracts fail closed.

## Remaining boundary

Authentic, authorized, survivorship-safe PIT histories with verified universe snapshots, dividends,
corporate actions, and delisting economics remain external. V1 rejects any request to label a run
legitimate until a future canonical Research Grade authorization can prove those controls. All runs
retain `NO_TRADE`, `HUMAN_ONLY`, `live_execution_enabled=false`, and
`real_data_readiness=NOT_READY`.
