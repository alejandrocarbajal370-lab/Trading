# Phase 6 — QVM Alpha Model Research Design

**Document version:** `phase6-qvm-design-v1.1`
**Status:** frozen design proposed for independent review; implementation not authorized  
**Base:** `main@2331a46f664f58e2a4bffed97e91ccd9831ddbdc`  
**Mode:** `RESEARCH_ONLY`  
**Mandatory safety state:** `trade_decision=NO_TRADE`, `live_execution_enabled=false`

## 1. Mandate and operating boundary

Phase 6 will research whether a compact Quality, Value, and Momentum model can rank liquid US
long-only equities while putting permanent-capital-loss avoidance ahead of return maximization.
The intended holding horizon is weeks through 12–18 months. The research snapshot and cohort
formation cadence is monthly. Daily EOD data, risk, health, and event monitoring is a separate
control plane and may invalidate a snapshot; it does not trigger an intramonth rebalance or trade.

The model is descriptive research, not an investment instruction. It produces metric scores,
factor scores, a composite research score, ranks, cohorts, diagnostics, and review/block flags
only. It must not produce target weights, positions, orders, signals, backtests, broker messages,
or live execution. Every artifact must retain `NO_TRADE` and execution disabled.

## 2. Authoritative input contract

The only admissible entry point is `sealed-pre-phase6-admission-v2`, delivered by PR #18 at
`dd25fc0068545bffa8e2c9f8c5b36d345ba209fd`. It accepts the verified Phase 5.6 chain through
exact sealed Quality/Value/Momentum batches. Direct `FactorBatch`, DataFrame, partial Q/V/M, or APIs
marked `research_legacy` or `phase6_eligible=false` are forbidden.

An input snapshot is admitted only when all of the following are true:

1. The cross-layer manifest health is exactly `PASS` and its contract versions are supported.
2. Universe membership is `ELIGIBLE` under the checksum-verified US liquid-equity snapshot.
3. Quality, Value, and Momentum batches share the exact cross-layer fingerprint, eligible-symbols
   hash, universe ID/hash, `as_of`, availability policy, entity policy, base currency, unit
   ontology, and accounting/market/FX identities required by the Phase 5.6 sealed contract.
4. Factor dataset hashes recompute exactly, all observation lineage is non-empty, and every
   `available_at <= as_of` under the governed timing policy.
5. The observation status is `PASS`, its value is finite, and confidence is at least `0.80`.
6. Sector and industry labels, when used for peers, are PIT-governed and known by `as_of`.

Any mismatch in items 1–4 fails the complete run closed. Item 5 makes that observation ineligible
under the missing-data policy below. Missing or ungoverned peer labels prohibit peer
neutralization but do not repair or infer a label.

The score artifact must bind the source cross-layer fingerprint, all factor dataset hashes, the
design/ruleset version, transformation parameters, active metric set, peer assignment hash, and
canonical output hash. Reordering input rows must not change any hash or result.

## 3. Initial factor set

The initial set is deliberately compact. A primary metric contributes to a factor score. A
diagnostic explains or challenges it but does not contribute. A red flag acts through the capital
preservation overlay. A deferred item cannot be used until its PIT contract is approved.

| Pillar | Metric | Role | Economic direction | Availability / reason |
|---|---|---|---|---|
| Quality | ROIC | primary | higher | available; direct operating profitability anchor |
| Quality | FCF margin | primary | higher | available; cash profitability anchor |
| Quality | CFO / net income | primary | higher within valid domain | available; cash backing, with pathology rules below |
| Quality | cash accrual quality = `-(NI-CFO)/assets` | primary | higher | `raw_accrual_ratio=(NI-CFO)/assets`, `lower_is_better`, is sealed by PR #18 |
| Quality | ROIC stability | primary | lower dispersion | available when history is sufficient |
| Quality | margin stability | primary | lower dispersion | available when history is sufficient |
| Quality | net debt / EBITDA | primary | lower | available only for positive EBITDA; stress handled separately |
| Quality | ROIC/FCF consistency and persistence | diagnostic | higher | useful context but redundant with level/stability |
| Quality | dilution / shares CAGR | red flag, deferred | lower | only `share_count_change` foundation exists; multi-period PIT CAGR contract absent |
| Quality | interest coverage | deferred | higher | not in the sealed metric registry |
| Value | FCF yield | primary | higher | available; cash-based valuation anchor |
| Value | EBIT yield | primary | higher | available; capital-structure-aware operating yield |
| Value | earnings yield | primary | higher | available; secondary equity valuation anchor |
| Value | EV / EBIT | diagnostic | lower | available but reciprocal/redundant with EBIT yield |
| Value | EV / EBITDA | diagnostic | lower | available; depreciation/capital-intensity caveat |
| Value | sector/history relative valuation | deferred | contextual | PR #18 admission does not provide an approved PIT historical-relative contract |
| Momentum | 12–1 momentum | primary | higher | available; canonical medium-term trend measure |
| Momentum | volatility-adjusted 12–1 | primary | higher | available; distinguishes unstable price paths |
| Momentum | 6-month momentum | diagnostic | higher | available but overlaps 12–1 |
| Momentum | trend stability 12m | diagnostic | higher | available; explanatory confirmation, not independent return evidence |
| Momentum | relative strength 6m | diagnostic | higher | available only with governed compatible benchmark |

No metric is promoted because it exists. Promotion requires an approved economic definition,
PIT lineage, pathology policy, tests, and preregistered ablation.

## 4. Eligibility and missing-data taxonomy

Every non-usable observation must carry exactly one primary missing class plus optional detail:

| Class | Meaning | Default consequence |
|---|---|---|
| `STRUCTURAL_MISSING` | metric is economically undefined for the issuer/industry | exclude metric; never impute |
| `PROVIDER_MISSING` | expected fact absent from provider | exclude metric; REVIEW when primary |
| `NOT_APPLICABLE` | approved contract says metric does not apply | exclude metric; never convert to zero |
| `PIT_UNAVAILABLE` | fact/history was not public by cutoff | exclude metric; PIT violation itself fails run |
| `INVALID_QUALITY` | conflict, low confidence, invalid lineage/unit/domain, non-finite value | exclude metric; critical integrity issue fails run |
| `INSUFFICIENT_HISTORY` | fewer governed observations than the metric contract requires | exclude history metric |

There is no silent imputation, cross-company fill, sector median fill, zero fill, or stale-value
carry-forward. Missing metrics never receive a neutral score.

### 4.1 Activation and company coverage

- A primary metric is active for a snapshot only with at least 30 eligible observations and at
  least 40% coverage of the governed universe. Otherwise it is inactive for every company and the
  artifact records why.
- Quality requires at least 70% of its active within-factor weight, including at least one of ROIC
  or FCF margin and at least one of CFO conversion or cash accrual quality.
- Value requires at least 65% of active within-factor weight and at least one of FCF yield or EBIT
  yield.
- Momentum requires both primary metrics (100% coverage for the company).
- Available primary weights are renormalized only within a factor after these gates pass. Weights
  are never shifted across Q, V, and M.
- A company enters the composite model only when all three factor scores pass. Otherwise it remains
  in the audit output with `MODEL_INELIGIBLE` and no composite score or rank.
- A snapshot may publish research cohorts only when at least 100 companies and at least 60% of the
  governed universe have complete composite scores. Below either threshold the run is `FAIL` for
  cohort publication, while diagnostic artifacts remain available.

## 5. Pathological and outlier policy

Domain validation happens before clipping or normalization. An invalid value is never made valid
by winsorization.

- **Negative or zero earnings:** earnings yield is ineligible; negative earnings creates
  `LOSS_MAKING_REVIEW`. CFO/net-income is ineligible when net income is `<= 0` because its sign can
  invert the economic meaning.
- **Negative or zero EBIT:** EBIT yield and EV/EBIT are ineligible;
  `NEGATIVE_EBIT_REVIEW` is raised.
- **Negative or zero EBITDA:** EV/EBITDA and net debt/EBITDA are ineligible. It is not treated as
  cheap or low leverage; `NEGATIVE_EBITDA_BLOCK` freezes model eligibility.
- **Negative FCF:** FCF yield and FCF margin retain the negative value and score as poor after
  robust normalization. Two consecutive comparable annual negative-FCF observations or a current
  collapse flag produces REVIEW; persistent/acute collapse may BLOCK under section 10.
- **Negative equity:** no book-based metric is in the initial set. If detected in governed facts,
  it is a capital-structure REVIEW and cannot be repurposed as a value input.
- **Near-zero denominator:** a denominator is near zero when
  `abs(d) <= max(1e-12, 1e-6 * peer_median(abs(d)))`. The ratio is ineligible. If the peer median
  is unavailable, the absolute guard alone applies and the limitation is recorded.
- **Infinite/NaN values:** ineligible as `INVALID_QUALITY`; never clipped.
- **Enterprise value `<= 0`:** EV-based metrics are ineligible and corporate-action/data review
  is required.
- **Extreme leverage:** net debt/EBITDA `>= 6.0x` is BLOCK; `>= 4.0x` and `< 6.0x` is REVIEW.
  Net cash (negative ratio with positive EBITDA) is valid but is capped by normalization and does
  not create unlimited favorable score.
- **Distress:** an active bankruptcy/delisting ambiguity, negative EBITDA with positive net debt,
  or unresolved going-concern/restatement integrity issue is BLOCK. A blocked company has no
  composite score regardless of apparent value or momentum.

## 6. Exact cross-sectional transformation

Transformations are calculated separately by metric and monthly `as_of`, using only eligible
observations. They are applied in this order:

1. Apply the economic direction: multiply lower-is-better metrics by `-1`. Cash accrual quality is
   explicitly `-1 * raw_accrual_ratio`; PR #18 seals the source metric as `lower_is_better`.
   Contextual/non-directional metrics cannot be scored.
2. Assign the PIT peer group. Fundamental Quality and Value metrics use industry peers when
   `n >= 20`; otherwise sector peers when `n >= 30`; otherwise the full eligible universe when
   `n >= 100`, tagged `MARKET_FALLBACK`. Momentum uses the full eligible universe by default.
   If no permitted group meets its minimum, that metric is ineligible for the affected company.
3. Robust-clip within the assigned group. Let `m = median(x)`,
   `s = 1.4826 * median(|x-m|)`. When `s > 0`, clip to `[m-5s, m+5s]`. When `s = 0`, the metric is
   inactive for the entire assigned group with status `NO_CROSS_SECTIONAL_VARIATION`; it receives
   no percentile, score, or weight. There is no percentile fallback. This conservative rule avoids
   manufacturing dispersion when a majority tie makes robust scale undefined, including the case
   of one isolated outlier.
4. Convert clipped values to midranks with deterministic ties: equal values receive the average
   rank; `p=(rank-0.5)/n`.
5. Produce the metric score `z = clip(Phi^-1(p), -3, 3)`, where `Phi^-1` is the standard-normal
   inverse CDF. This rank-Gaussian score is the scoring value. A classical mean/std z-score is not
   used because ratios are skewed and fragile to tails.

The raw value, directed value, clip bounds, peer type/ID/size, rank, percentile, score, missing
class, and transformation version must all be emitted. Sector/industry neutralization is therefore
implemented by peer ranking, not by regression residuals. Size neutrality is not used in V1:
liquidity and minimum-size controls belong to the governed universe, and neutralizing size without
a preregistered hypothesis could remove economically relevant information. Size exposure is a
mandatory diagnostic.

## 7. Score math and frozen baseline weights

For company `i`, primary metric score `z_ij` and available active weights `w_j`, a factor score is:

`F_i = sum(w_j * z_ij) / sum(w_j available for i)`

subject to the coverage gates in section 4. Factor scores are clipped to `[-3, 3]` only after the
weighted mean. Frozen within-factor baseline weights are:

| Factor | Primary metric | Weight |
|---|---|---:|
| Quality | ROIC | 20% |
| Quality | FCF margin | 20% |
| Quality | CFO / net income | 15% |
| Quality | cash accrual quality | 15% |
| Quality | ROIC stability | 10% |
| Quality | margin stability | 10% |
| Quality | net debt / EBITDA | 10% |
| Value | FCF yield | 40% |
| Value | EBIT yield | 35% |
| Value | earnings yield | 25% |
| Momentum | 12–1 momentum | 60% |
| Momentum | volatility-adjusted 12–1 | 40% |

The mandatory composite baseline is equal-factor weight:

`QVM_i = (Quality_i + Value_i + Momentum_i) / 3`.

An additional all-primary-metrics-equal baseline must be reported as a sensitivity check, but it
cannot replace equal-factor QVM because it implicitly overweights the factor with more metrics.
No weights may be optimized on the full history. Alternative factor weights are not part of the
initial implementation; they may exist only as future, separately preregistered experiments for
later OOS comparison. The equal-weight result remains the reference, and no alternative is
promotable in this design phase.

## 8. Ranking and research cohorts

Only model-eligible, non-blocked companies are ranked. Sort by composite score descending, then
Quality descending, then Value descending, then Momentum descending, and finally normalized symbol
ascending as the deterministic identity tie-breaker. Economically identical composite/factor
values retain the same midrank percentile even though the symbol tie-breaker fixes row order.

Publish research labels only: deciles when `n >= 100`, otherwise quintiles when `50 <= n < 100`.
The primary cohorts are top 10%, middle 40–60%, and bottom 10% when deciles are available; with
quintiles, top/middle/bottom quintiles are used and tagged as a fallback. No cohort is a portfolio,
selection list, target position, or trade signal.

## 9. Capital-preservation overlay

Overlay outcomes are `PASS`, `REVIEW`, or `BLOCK`. Flags do not add points. REVIEW preserves a
research score but excludes the company from an automatically publishable top cohort until human
resolution. BLOCK removes composite eligibility.

| Flag | Trigger frozen for V1 | Outcome |
|---|---|---|
| Material restatement/revision | unresolved revision affecting any primary input, or a primary-input change `>=10%` when comparable | BLOCK unresolved; REVIEW resolved/material |
| Accounting deterioration | CFO conversion `<0.8` or raw accrual ratio `>0.10`; two concurrent warnings | REVIEW; BLOCK when combined with negative EBITDA/FCF distress |
| Extreme leverage | net debt/EBITDA `>=4x` | REVIEW; `>=6x` BLOCK |
| FCF collapse | current FCF margin down `>=50%` relative and `>=5` percentage points versus prior comparable annual period, or turns negative | REVIEW; BLOCK after two consecutive negative comparable annual periods with positive net debt |
| Dilution | governed annual shares growth `>5%` | REVIEW; deferred until PIT share-CAGR contract exists |
| Data confidence | confidence `<0.80`, invalid lineage/hash/PIT, or unresolved provider conflict | metric exclusion; integrity mismatch BLOCK/run fail |
| Corporate action ambiguity | unresolved split, merger, spin-off, symbol mapping, or adjusted-price ambiguity affecting lookback | BLOCK |

Thresholds are conservative research controls, not empirically optimized alpha parameters. They
must be preregistered before later outcome evaluation.

## 10. Validation plan and implementation gates

Scoring implementation cannot be considered complete until all gates pass:

1. **Contract/unit tests:** schema, enum, version, immutable configuration, exact Phase 5.6-only
   admission, and safety-state assertions.
2. **Golden deterministic tests:** hand-calculated raw-to-score examples including ties, peer
   fallback, missing coverage, and overlay outcomes.
3. **Monotonicity tests:** improving a higher-is-better input cannot reduce its metric score within
   a fixed cross-section; improving a lower-is-better input cannot reduce it after direction.
4. **Sign/direction tests:** negative EBIT/EBITDA/earnings never appear cheap; lower stability and
   leverage score better; raw positive accruals score worse.
5. **Missing tests:** every taxonomy class, no imputation, metric/factor/model thresholds, and no
   cross-factor weight transfer.
6. **Peer-neutrality tests:** industry/sector/market minimums, no unknown-label inference,
   within-peer median near zero, and deterministic fallback labels.
7. **Outlier/pathology tests:** near-zero denominators, infinities, negative fundamentals, net cash,
   extreme leverage, zero MAD, and clipped-tail monotonicity.
8. **Order/reproducibility tests:** shuffled rows and stable ties produce byte-identical canonical
   artifacts and hashes.
9. **Lineage/fingerprint tests:** any upstream/config/peer/metric mutation changes the fingerprint;
   mismatches fail closed.
10. **Adversarial tests:** future data, duplicate identities, stale facts, hash spoofing, sector
    relabeling, corporate-action ambiguity, value traps, and impressive momentum with distress.
11. **Ablation plan:** preregister and compare Quality-only, Value-only, Momentum-only, equal-QVM,
    and each single-primary-metric removal. Report coverage, rank stability, sector/size exposure,
    turnover proxy, and later OOS outcomes without selecting on the same sample.
12. **Safety regression:** assert no signal, portfolio, order, backtest, broker, or execution output;
    assert `NO_TRADE` and `live_execution_enabled=false` in every success and failure path.

## 11. Anti-overfitting rules

- Equal-factor weighting is the mandatory baseline and cannot be omitted from a report.
- Never tune weights, clipping, thresholds, lookbacks, cohorts, or peer minimums on the full
  history.
- Parameters remain few, interpretable, discrete, versioned, and preregistered.
- Reserve walk-forward/out-of-sample evaluation for the later authorized validation/backtesting
  phase. The holdout may not inform this contract.
- Separate hypothesis development, parameter choice, and final evaluation windows.
- Report every attempted variant and ablation in the append-only research registry; no selective
  deletion of failed experiments.
- Any claimed improvement must later show marginal value net of turnover and realistic costs.
- Statistical evidence, economic rationale, stability across regimes, and coverage must all be
  reported; a higher in-sample return alone is insufficient.

## 12. Required research outputs

A future implementation should emit content-addressed, immutable artifacts:

- `phase6_score_manifest.json`: ruleset, identities, safety state, counts, hashes, parameters.
- `phase6_metric_scores.parquet`: raw/directed/clipped values, peer metadata, status and lineage.
- `phase6_factor_scores.parquet`: coverage, active weights, Q/V/M scores and reasons.
- `phase6_qvm_research_cohorts.parquet`: eligible research ranks/cohorts and overlay state.
- `phase6_diagnostics.json`: missingness, exposure, distributions, correlations, flags, fallbacks.
- `phase6_validation_report.json`: gate-by-gate PASS/FAIL and canonical fingerprints.

Filenames describe a contract, not authorization to implement them in this design change.

## 13. Frozen decisions

- Phase 5.6 verified chain is the exclusive source; health/identity/PIT failures fail closed.
- Long-only US liquid-equity research, monthly cohorts, daily monitoring separate, no trading.
- Compact primary set and diagnostic/deferred separation in section 3.
- Rank-Gaussian scoring after explicit direction and robust five-MAD clipping.
- Fundamental peer hierarchy `industry >=20 -> sector >=30 -> market >=100`; Momentum is market-wide.
- No size neutralization in V1; mandatory size-exposure diagnostics.
- Explicit missing taxonomy, no imputation, factor/model coverage gates.
- Equal-factor QVM baseline and the within-factor weights in section 7.
- Deterministic ranking/ties, research-only cohorts, and non-additive REVIEW/BLOCK overlay.
- Full validation and anti-overfitting gates before later performance evaluation.

## 14. Open decisions and prerequisites for implementation

These items require independent audit or a separately authorized contract change; they are not
permission to code the model now:

1. Treat PR #18 head `dd25fc0068545bffa8e2c9f8c5b36d345ba209fd` as the final PRE-Phase 6
   contract for admission, typed identities, confidence, status taxonomy, PIT sector/industry,
   peer assignment, applicability, and `raw_accrual_ratio` semantics. Any later head requires a new
   independent audit reference.
2. Add a governed multi-period shares-outstanding contract before activating dilution thresholds.
3. Define an authoritative PIT restatement-materiality and corporate-action resolution feed before
   their overlay flags can move from contract placeholders to automated decisions.
4. Validate whether the proposed confidence threshold, peer minimums, and company/snapshot coverage
   gates preserve adequate coverage on a blinded representative snapshot. This is a contract
   feasibility check, not return optimization.

## 15. Explicit non-goals

This design does not implement or authorize portfolio construction, position sizing, risk budgets,
turnover control, transaction costs, backtesting, expected returns, buy/sell signals, broker
integration, order generation, reconciliation, paper trading, leverage, shorts, options, or live
execution. It does not merge code and does not enable trading. Phase 6 remains `RESEARCH_ONLY`.


## 16. PRE-Phase 6 audit clarifications (design only)

These clarifications freeze contract intent and do not implement scoring.

1. **Gate order:** confidence filter -> sector/industry applicability and metric activation -> PIT
   industry/sector/market peer fallback -> metric coverage -> within-factor coverage -> composite
   coverage. No later gate may revive an observation rejected earlier.
2. **Cohort ties:** an equal-value midrank group that crosses a cohort boundary remains intact.
   The cohort expands as needed; symbol ordering is display-only and never splits an economic tie.
3. **Five-MAD clipping:** clipping before rank-Gaussian is intended only to collapse extreme tails
   into explicit ties. Sensitivities at 3-MAD, 5-MAD, and no clipping are preregistered diagnostics,
   not alternatives selected using returns.
4. **Degenerate cases:** scale `s=0` makes the metric inactive with
   `NO_CROSS_SECTIONAL_VARIATION`, without percentile fallback, score, or weight.
5. **Active within-factor denominator:** the denominator is the sum of configured weights for
   applicable observations that passed confidence. Missing or non-applicable observations receive
   no weight and are never imputed.
6. **Policy versus alpha:** capital-preservation thresholds are separately versioned
   policy/diagnostic settings, not alpha parameters.
7. **Alternative weights:** alternatives remain future preregistered experiments and are not
   promotable candidates during the initial implementation.
8. **Corrected upstream contracts:** `raw_accrual_ratio=(NI-CFO)/assets` with
   `lower_is_better`, sealed PIT industry/sector identity, deterministic peer assignment, typed QVM
   lineage, and exact Q/V/M admission are supplied by PR #18 head
   `dd25fc0068545bffa8e2c9f8c5b36d345ba209fd`. They must pass re-audit before scoring starts.

### 16.1 Frozen golden examples

These examples are exact future test vectors. They document design only and do not authorize or
implement scoring.

1. **No variation:** directed values `[5, 5, 5, 5]` give `m=5`, `MAD=0`, `s=0`. The metric is
   inactive as `NO_CROSS_SECTIONAL_VARIATION`; all four percentile/score fields are null.
2. **Majority tie plus outlier:** directed values `[0, 0, 0, 0, 100]` give `m=0`, `MAD=0`, `s=0`.
   The entire group is inactive. The outlier does not trigger a percentile fallback and cannot
   manufacture four favorable/unfavorable scores.
3. **Peer minimums:** industry size `20` uses industry; industry `19` plus sector `30` uses sector;
   industry `19`, sector `29`, and market `100` uses `MARKET_FALLBACK`; sizes `19/29/99` are
   ineligible. The comparisons are inclusive at `20`, `30`, and `100`.
4. **Midrank and percentile:** for ascending directed values `[10, 10, 20, 40]`, ranks are
   `[1.5, 1.5, 3, 4]` and `p=(rank-0.5)/4` gives `[0.25, 0.25, 0.625, 0.875]`. The corresponding
   unclipped inverse-normal values, rounded to five decimals, are
   `[-0.67449, -0.67449, 0.31864, 1.15035]`.
5. **Cohort boundary ties at n=100:** if positions `9–12` share the boundary value, the top-decile
   cohort expands from `1–10` to `1–12`. If positions `38–41` and `59–63` are the tie groups crossing
   the nominal middle `40–60` boundaries, the middle cohort expands to `38–63`. If positions
   `89–92` tie across the bottom-decile boundary, the bottom cohort expands to `89–100`. Symbol
   order never splits these groups.
6. **Metric activation:** in a universe of `100`, `39` eligible PASS observations mean 39% and the
   metric is inactive; `40` mean 40% and it is active because `n>=30`. In a universe of `60`, `30`
   observations mean 50% and activate; `29` remain inactive because the count floor fails.
7. **Quality company coverage:** with all Quality primaries active, denominator `1.00`, available
   ROIC+FCF margin+CFO conversion weights total `0.55`, so coverage is 55% and fails the 70% gate.
   For a bank where net debt/EBITDA is `NOT_APPLICABLE`, the denominator is `0.90`; available
   ROIC+FCF margin+CFO conversion+accrual weights total `0.70`, so coverage is `0.70/0.90 =
   77.777...%` and passes both named-anchor requirements. If CFO conversion is also unavailable,
   coverage is `0.55/0.90 = 61.111...%` and fails even though the accrual anchor remains.
8. **Value and Momentum coverage:** Value with only EBIT yield+earnings yield has `0.60/1.00=60%`
   and fails 65%; FCF yield+EBIT yield has `0.75/1.00=75%` and passes. Momentum requires both
   primaries, so one of two is exactly 60% or 40% by configured weight but always fails the frozen
   100% requirement.
