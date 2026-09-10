# ADR 0021 — CORSO Fixed Income and Multi-Asset Future Scope

Status: **ACCEPTED SCOPE; FUTURE / NOT IMPLEMENTED / NOT AUTHORIZED**

## Decision

The definitive name of the Investment OS is **CORSO**. “Aurora” is the superseded former name and
may appear only in historical material when explicitly identified as such. This naming decision
does not authorize automatic renaming of modules, APIs, persisted identifiers or other technical
contracts where compatibility could be affected.

CORSO must evolve from its current equity/QVM research foundation into a governed multi-asset
Investment OS with three distinct capabilities:

1. **Equity / renta variable.** Preserve the current QVM/equity research stack.
2. **Fixed Income / renta fija.** Build a future governed debt/bond valuation and risk model,
   separate from equity QVM wherever metrics or methodologies are not comparable.
3. **Multi-Asset Portfolio Construction.** Later combine governed Equity and Fixed Income outputs
   to evaluate candidate allocations between both asset classes, subject to human review.

Fixed Income is a parallel future vertical, not a replacement for QVM. This ADR records required
scope only. It does not authorize implementation, scoring, ranking, capital allocation, portfolio
construction, recommendations or backtesting.

## Future Fixed Income model scope

According to instrument type and governed data availability, the future model must cover at least:

- a debt-specific instrument/security master and issuer/obligor identity;
- bond type, seniority, secured/unsecured status and capital-structure position;
- currency, coupon type/rate, issue date, maturity date and payment frequency;
- clean price, dirty price and accrued interest;
- appropriate yield measures, including current yield, YTM, and YTC/YTW when applicable;
- cash-flow schedule, day-count convention and settlement convention;
- duration, modified duration and convexity;
- benchmark/reference curve and methodologically appropriate spread measures such as G-spread,
  Z-spread or OAS only when sufficient data exists;
- credit quality and ratings as auxiliary evidence, never unquestioned truth;
- issuer fundamentals, leverage, coverage, liquidity and default-risk indicators;
- covenant, call, put, convertible and subordination features when applicable;
- embedded optionality when applicable;
- FX exposure and MXN-reporting decomposition when applicable;
- liquidity, bid-ask and market depth when available;
- taxes, withholding and reporting context as governed future inputs, never hardcoded assumptions;
- relevant corporate actions, calls, tenders, defaults and restructurings; and
- point-in-time lineage, provenance, timestamps, data quality, reconciliation and fail-closed
  behavior.

No single bond-scoring formula is selected or implied. The methodology must be designed and
validated separately before it can support ranking or capital allocation. Sovereign,
investment-grade corporate, high-yield, floating-rate, callable, convertible, subordinated,
AT1/CoCo and other debt types may require different methodologies; one universal score must not be
assumed.

## Future portfolio objective

An approximately `50% Fixed Income / 50% Equity` portfolio is an initial allocation to study, not
an optimum, target or mandatory allocation. A future, separately authorized CORSO capability may
generate and compare governed candidates such as 20/80, 30/70, 40/60, 50/50 and 60/40.

“Best” must not mean maximum return alone. The governing mandate remains:

> Minimize probability of permanent capital loss → maximize return subject to that.

Once the required models, data and methods have been separately authorized and validated, a future
comparison should consider governed expected-return assumptions; volatility and other risk;
drawdown and permanent-loss considerations; cross-asset correlation and diversification;
duration/interest-rate, credit/default and FX risks; liquidity; concentration; cash requirements;
authorized tax-aware effects; transaction costs and turnover; stress/scenario behavior;
appropriate risk-adjusted and after-cost/after-tax metrics; portfolio constraints; and the user
mandate.

## Target architecture

```text
Equity canonical data       -> Equity/QVM model          \
Fixed Income canonical data -> FI valuation/risk model    +-> governed multi-asset portfolio construction
FX / macro / tax / liquidity / constraints              /    -> candidate allocations -> human review
```

CORSO may eventually propose allocations or rebalances only for human review. ADR 0020 remains
binding: execution is `HUMAN_ONLY` and manual at Broker X outside CORSO. CORSO must not submit,
modify, cancel or transmit orders; move or withdraw cash; or change banking instructions.
`live_execution_enabled=false` remains permanent under the current mandate.

## Roadmap placement

The immediate roadmap is unchanged: Step 5 is **CLOSED** and Step 6 is **NOT STARTED**. Fixed Income
is placed after sufficient foundations and asset-specific canonical data governance, and before
definitive multi-asset portfolio construction. The conceptual future order is:

1. complete the currently governed evidence, external-gate and REAL provider-admission sequence;
2. preserve and govern the Equity/QVM vertical and its separately authorized validation path;
3. establish Fixed Income canonical data foundations;
4. design, govern and separately validate instrument-appropriate FI valuation/risk methodologies;
5. complete any separately authorized asset-specific backtesting and tax-aware dependencies; and
6. only then consider governed multi-asset portfolio construction and candidate allocations.

Sequence placement grants no implementation or activation authority. No optimizer, efficient
frontier, expected-return model, Fixed Income score/ranking, portfolio weight or recommendation is
implemented by this ADR. Backtesting and portfolio construction remain `NOT_AUTHORIZED` until
their corresponding phases.

## Preserved safety state

- Step 5: `CLOSED`
- Step 6: `NOT STARTED`
- all 10/10 gates: `OPEN_EXTERNAL`
- REAL provider, legal, trust, custody and admission: `NOT_PROVISIONED`
- real route: `QVM_NOT_READY`
- global readiness: `INSUFFICIENT_REAL_DATA`
- `trade_decision=NO_TRADE`
- `signals_generated=false`
- `live_execution_enabled=false`
- backtesting: `NOT_AUTHORIZED`
- portfolio construction: `NOT_AUTHORIZED / NOT IMPLEMENTED`
- Fixed Income scoring/ranking: `NOT_AUTHORIZED / NOT IMPLEMENTED`
- capital-allocation recommendations: `NOT_AUTHORIZED / NOT IMPLEMENTED`

**Paso 6: NOT STARTED. NO FIXED-INCOME MODEL / PORTFOLIO OPTIMIZER IMPLEMENTED.**
