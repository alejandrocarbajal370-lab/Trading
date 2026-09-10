# ADR 0022 — CORSO Fixed Income and Multi-Asset Future Scope

Status: **ACCEPTED SCOPE; FUTURE / NOT IMPLEMENTED / NOT AUTHORIZED**

## Decision

The definitive name of the Investment OS is **CORSO**. “Aurora” is the superseded former name and
may appear only in historical material when explicitly identified as such. This naming decision
does not authorize automatic renaming of modules, APIs, persisted identifiers or other technical
contracts where compatibility could be affected.

CORSO must evolve from its current equity/QVM research foundation into a governed multi-asset
Investment OS with three distinct capabilities:

1. **Equity / renta variable.** Preserve the current US QVM/equity research stack and define a
   separate future Mexican Equity scope where market-specific methodology requires it.
2. **Fixed Income / renta fija.** Build a future governed debt/bond valuation and risk model,
   separate from equity QVM wherever metrics or methodologies are not comparable.
3. **Multi-Asset Portfolio Construction.** Later combine governed Equity and Fixed Income outputs
   to evaluate candidate allocations between both asset classes, subject to human review.

Fixed Income is a parallel future vertical, not a replacement for QVM. This ADR records required
scope only. It does not authorize implementation, scoring, ranking, capital allocation, portfolio
construction, recommendations or backtesting.

## Future Mexican Equity scope

Mexican Equity is an explicit future CORSO vertical. Its eligible universe may include shares
listed on governed Mexican markets only after a future, governed universe and security master
define instrument, issuer, listing, venue, currency and eligibility identity. Mexican Equity must
be treated separately by market, currency and applicable microstructure rules; the current US
Equity/QVM engine must not be assumed to transfer without local methodology, recalibration and
validation.

Before any use, a separately authorized future capability must govern and validate local
methodology; point-in-time data and lineage; corporate actions; trading calendars and market
microstructure; liquidity and market depth; transaction costs; FX and reporting-currency effects;
and other locally applicable conventions. This scope does not select or provision a local data
provider, create a Mexican security master, or implement a Mexican Equity model.

Any future Mexican Equity universe, including an index or universe proxy used for research,
backtesting or selection, must preserve historical constituent membership point-in-time. A current
security master or a current constituent list is not sufficient. Governed membership must include
`effective_from` / `effective_to` or equivalent point-in-time semantics and, where applicable,
preserve universe entries and exits, ticker or listing changes, mergers, spin-offs, delistings and
share-class changes. The universe must never be reconstructed retrospectively using only current
constituents. Any future Mexican Equity backtest or selection must fail closed when historical
constituent coverage is insufficient. This requirement explicitly prevents survivorship bias and
look-ahead in universe construction; it does not create or populate a security master.

Mexican Equity remains **FUTURE / NOT IMPLEMENTED / NOT AUTHORIZED**.

## Future Fixed Income model scope

According to instrument type and governed data availability, the future model must cover at least:

- a debt-specific instrument/security master and issuer/obligor identity;
- bond type, seniority, secured/unsecured status and capital-structure position;
- currency, coupon type/rate, issue date, maturity date and payment frequency;
- clean price, dirty price and accrued interest;
- appropriate yield measures, including current yield, YTM, and YTC/YTW when applicable;
- cash-flow schedule, day-count convention and settlement convention;
- duration, modified duration and convexity;
- benchmark/reference curve, plus a distinct risk-free or near-risk-free reference curve when
  methodologically applicable, and appropriate spread measures such as G-spread, Z-spread or OAS
  only when sufficient data exists;
- credit quality and ratings as auxiliary evidence, never unquestioned truth;
- issuer fundamentals, leverage, coverage, liquidity and default-risk indicators;
- recovery rate, governed recovery assumptions, loss-given-default (`LGD = 1 - recovery`, unless a
  future instrument-specific definition or policy requires otherwise), and expected-loss or
  credit-loss decomposition where methodologically applicable;
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

### Future recovery and credit-loss governance

Recovery must be modelled separately from observed market data and from issuer default-probability
or hazard assumptions. Future valuation, spread, expected-loss and risk calculations that depend
on recovery must preserve the recovery input's provenance, source, version, timestamp and
assumptions; those assumptions must be source-governed and point-in-time aware where applicable.
They must never be silently hardcoded as universal constants.

The future framework must account for recovery seniority and capital-structure dependence and,
where relevant, distinguish senior secured, senior unsecured, subordinated, preferred/hybrid,
AT1/CoCo, and distressed or restructured debt. The exact framework may differ by instrument,
jurisdiction, seniority, collateral, restructuring regime and data availability. Future authorized
stress or scenario models may vary recovery assumptions explicitly. A separately governed
methodology and ADR are required before production use; this ADR implements no recovery estimation
or recovery model.

### Future reference-curve governance

A benchmark/reference curve is not automatically a risk-free curve. Future methodology must define
and govern risk-free or near-risk-free reference selection per relevant currency, market and
instrument context, including OIS or an equivalent reference where appropriate. Sovereign or other
reference curves may be used when justified, but must not be silently treated as risk-free.

Every future curve-dependent calculation must identify its actual reference curve and preserve its
source, observation timestamp, point-in-time provenance, curve version and methodology. Where an
implementation requires them, it must also govern currency-specific curve conventions and tenor,
interpolation and bootstrap conventions. G-spread, Z-spread and OAS must identify the curve actually
used rather than assume `benchmark == risk-free`. Analysis should distinguish spread versus the
selected benchmark, spread versus the selected risk-free or near-risk-free reference, and credit,
liquidity and option components where analytically possible. Cross-currency comparisons must not
silently treat different sovereign or reference curves as equivalent risk-free bases.

No current vendor, country curve, rate or universal curve methodology is selected by this scope.

### Future Mexican Fixed Income scope

Mexican Fixed Income is explicitly within the future governed Fixed Income engine. Subject to a
future governed universe, instrument eligibility and data availability, its scope must be able to
cover Mexican sovereign/government debt, including CETES, Bonos M, Udibonos and other eligible
government instruments where applicable; Mexican corporate debt; Mexican bank and financial debt;
and eligible instruments denominated in MXN or other currencies.

Future methodology must govern appropriate local curves and references, instrument and settlement
conventions, and inflation/indexation treatment for Udibonos and other instruments where applicable.
It must also address credit/default risk; recovery and LGD; liquidity; taxes and withholding; FX
and reporting currency; and relevant Mexican legal, market and cash-flow conventions. A sovereign
MXN curve is a benchmark/reference curve, not automatically a risk-free curve: the future method
must distinguish it from a separately justified risk-free or near-risk-free methodology where
applicable and identify the actual curve used.

This scope does not select or provision local data providers, a Mexican debt security master, local
curves, a Mexican tax engine or a Mexican debt valuation/risk model. Mexican Fixed Income remains
**FUTURE / NOT IMPLEMENTED / NOT AUTHORIZED**.

### Future nominal versus real/inflation-linked methodology

The future Mexican Fixed Income layer must explicitly distinguish nominal debt, including CETES
and Bonos M where methodologically applicable, from real, inflation-linked or indexed debt,
including Udibonos. It must preserve and must not mix nominal versus real yield basis; nominal
versus real/reference curves; inflation/indexation basis; accrued and indexed-principal mechanics
where applicable; and duration, DV01 and other risk sensitivities consistent with the instrument's
basis. Expected-inflation or breakeven decomposition must be governed when methodologically
applicable.

Comparisons and spread attribution must not combine incompatible nominal and real bases. Any
conversion or comparison between nominal and real/inflation-linked instruments requires a governed
methodology and appropriate point-in-time inputs; inflation assumptions or breakevens must never be
silently supplied by default. This section authorizes no pricing, curve construction or risk-model
implementation.

## Future local-asset versus MXN base-currency return governance

Any future cross-currency performance, comparison or portfolio layer must preserve two distinct
return concepts:

- `LOCAL_ASSET_RETURN`: the asset return in its own currency and applicable local-return basis; and
- `BASE_CURRENCY_RETURN_MXN`: the asset return expressed in the portfolio's MXN base/reporting
  currency.

For non-MXN assets, a governed decomposition must separately identify FX return with point-in-time
lineage and combine it consistently with local asset return. Where appropriate for the instrument,
period and return convention, the conceptual relationship is
`R_MXN = (1 + R_LOCAL) * (1 + R_FX) - 1`; the exact convention must be documented and governed
before use. A USD or other local-currency return must never be compared directly with an MXN return
without consistent conversion.

Future performance attribution must distinguish asset return, FX contribution and combined
base-currency return. Fees, taxes and cash flows must be incorporated in the appropriate governed
layer without omission or double counting. Any future optimization or portfolio comparison must
operate in a coherent reporting/base currency while retaining local asset return for diagnosis and
attribution. This requirement implements no performance engine, optimizer or portfolio comparison.

## Future portfolio objective

An approximately `50% Fixed Income / 50% Equity` portfolio is an initial allocation to study, not
an optimum, target or mandatory allocation. A future, separately authorized CORSO capability may
generate and compare governed candidates such as 20/80, 30/70, 40/60, 50/50 and 60/40.

“Best” must not mean maximum return alone. The governing mandate remains:

> Minimize probability of permanent capital loss → maximize return subject to that.

Once the required models, data and methods have been separately authorized and validated, a future
engine must compare alternative Fixed Income/Equity weights under an explicit objective function
and governed constraints. That comparison should consider expected-return assumptions; volatility and other risk;
drawdown and permanent-loss considerations; cross-asset correlation and diversification;
duration/interest-rate, credit/default and FX risks; liquidity; concentration; cash requirements;
authorized tax-aware effects; transaction costs and turnover; stress/scenario behavior;
appropriate risk-adjusted and after-cost/after-tax metrics; portfolio constraints; and the user
mandate. This requirement defines future scope only and does not create real portfolio construction.

When separately implemented, validated and authorized, the future portfolio layer must be able to
compare and combine US Equity, Mexican Equity, applicable US/global Fixed Income, Mexican Fixed
Income, and cash or low-risk sleeves where appropriate. It must evaluate alternative mixes and
justify which is more attractive under the governed capital-preservation-first objective using
expected return, volatility and other risk, drawdown, correlation and diversification, liquidity,
costs, taxes, FX, concentration and appropriate risk-adjusted metrics. The initial 50/50 scenario
is never a fixed optimal target.

## Target architecture

```text
US Equity canonical data       -> US Equity/QVM engine            \
Mexican Equity canonical data  -> future Mexican Equity engine     \
Fixed Income canonical data    -> future FI valuation/risk engine   +-> future governed multi-asset portfolio layer
FX / macro / tax / liquidity / constraints                         /    -> candidate allocations -> human review
```

CORSO must use separate Equity engine(s), a Fixed Income engine, and a future multi-asset portfolio
layer whenever asset-class or market methodology requires it. It must not force one formula across
stocks and bonds or assume one market's model is valid in another market without governed
recalibration and validation.

CORSO may eventually propose allocations or rebalances only for human review. ADR 0020 remains
binding: execution is `HUMAN_ONLY` and manual at Broker X outside CORSO. CORSO must not submit,
modify, cancel or transmit orders; move or withdraw cash; or change banking instructions.
`live_execution_enabled=false` remains permanent under the current mandate.

## Roadmap placement

This ADR does **not** establish, advance, reopen or roll back Step 6. Step 6 status is owned by its
separately governed implementation/foundation record and must be read from that record and the
current canonical roadmap. This future-scope ADR must never be used as an independent source of
truth for Step 6 readiness.

Fixed Income is placed after sufficient foundations and asset-specific canonical data governance,
and before definitive multi-asset portfolio construction. The conceptual future order is:

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
- Step 6: **not modified by this ADR; defer to the canonical Step 6 governance record**
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
- Mexican Equity model and security master: `NOT_AUTHORIZED / NOT_IMPLEMENTED`
- Mexican debt model, local curves and tax engine: `NOT_AUTHORIZED / NOT_IMPLEMENTED`
- local Mexican data providers: `NOT_PROVISIONED`

**NO FIXED-INCOME MODEL, MEXICAN EQUITY MODEL, MEXICAN DEBT MODEL OR PORTFOLIO OPTIMIZER IS
IMPLEMENTED. THIS ADR DOES NOT MODIFY STEP 6 STATUS.**
