# Equity QVM Backtest Engine V1

This is a deterministic research simulator, not an execution or production component. It consumes
an ordered sequence of checksum-pinned PIT manifests and hash-verified canonical Phase 6 QVM
artifacts. Current outputs are always labelled `DETERMINISTIC_FIXTURE_BACKTEST`; they never claim
Research Grade, survivorship safety, portfolio authority, or real-data readiness.

## Frozen baseline

- Select QVM cohort `TOP` rows whose capital-preservation overlay is `PASS`.
- Equal-weight the selected securities. There is no optimizer or parameter tuning.
- Buy and hold between declared rebalances. End-of-period constituent returns produce drifted
  weights, and the next one-way turnover is `0.5 * sum(abs(target - drifted_pre_trade))` across
  the union of securities. Initial entry turnover is `1.0`; the portfolio is fully invested and
  unlevered.
- A signal known at cutoff may enter holdings only at its explicitly declared later rebalance time.
- Charge 10 bps times one-way turnover by default. This is an entry-rebalance simple-return
  deduction (`net = gross - turnover * bps / 10,000`), not full cash accounting. The preregistered
  V1 range is 0–50 bps; every non-10-bps result is identity-bound as `SENSITIVITY`.
- Use a zero annual risk-free rate and 12 monthly periods per year. V1 verifies 20–35 day holding
  periods and rejects any `annual_periods` other than 12.
- Compute gross and net return, turnover, cumulative and annualized return, annualized volatility,
  Sharpe, maximum drawdown, hit rate, and observation/rebalance counts.
- Compare a benchmark only when a complete series is supplied and explicitly declared PIT-valid.

Portfolio returns use the separate convention
`USD_TOTAL_RETURN_WITH_DISTRIBUTIONS_AND_DELISTINGS`. The factor-research adjusted prices admitted
by the PIT dataset builder are forbidden as a silent substitute. Each period requires a hashed
`backtest-total-return-input-v1` artifact declaring `GOVERNED_TOTAL_RETURN_OBSERVATIONS`, exact
source identity, period, distribution/corporate-action semantics, delisting semantics, and
canonically ordered security observations. Every observation binds security ID, period, total
return, availability, source observation ID, delisting treatment/event identity, and its own hash.
Exactly -100% is valid; less than -100% is not. Every held security needs an observation, so a
bankruptcy or delisting cannot silently disappear. Extra non-held observations are deterministically
ignored for return arithmetic, but remain bound through the return-input artifact hash.

The result is content-addressed over manifest checksums, canonical QVM artifact hashes, parameters,
engine/model versions, cutoff range, target/pre-trade/end holdings, exact used return observations,
return-input identities, transitions, returns, benchmark input identities, and statistics. Each QVM
artifact now exposes the `as_of` and `cross_layer_fingerprint` already sealed by its governed factor
batches; both must match the exact canonical PIT manifest used by that cutoff. Input manifest
checksums and QVM model hashes are revalidated when loaded. Duplicate or non-monotonic cutoffs,
duplicate manifests, look-ahead chronology, incomplete benchmark coverage, and inconsistent return
contracts fail closed.

Annualized return, sample volatility, and Sharpe remain deterministic mechanical calculations.
Fewer than 12 monthly observations are explicitly labelled
`INSUFFICIENT_SAMPLE_FOR_INFERENCE`; even longer fixture runs remain mechanical and not Research
Grade evidence. A benchmark is accepted only as a complete sequence of the same governed,
content-addressed return-input artifacts.

## Remaining boundary

Authentic, authorized, survivorship-safe PIT histories with verified universe snapshots, dividends,
corporate actions, and delisting economics remain external. V1 rejects any request to label a run
legitimate until a future canonical Research Grade authorization can prove those controls. All runs
retain `NO_TRADE`, `HUMAN_ONLY`, `live_execution_enabled=false`, and
`real_data_readiness=NOT_READY`.
