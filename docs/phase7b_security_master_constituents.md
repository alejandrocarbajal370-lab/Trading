# Phase 7B — Security Master + Historical Constituents PIT Foundation

This phase contract-closes the research-only boundary
`historical constituents/security master PIT -> governed Universe -> permanent identity -> CIK -> SEC`.
It does not map SEC facts into Accounting/QVM or authorize backtesting, signals, portfolios, or
execution. The fixed state is `INSUFFICIENT_REAL_DATA`, `NO_TRADE`, execution disabled, and no signals.

## Provider audit

No provider is connected. Existing repository connectors do not supply historical index membership
plus stable security identity. SEC ticker/CIK files are periodically updated search associations whose
accuracy and scope SEC does not guarantee. Nasdaq Trader symbol directories are current directories,
not demonstrated historical constituent/security-master archives. Either could only become a
raw-preserved `PARTIAL_REAL_PROVIDER`.

Official evidence reviewed: [SEC EDGAR data access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data),
[Nasdaq Trader symbol definitions](https://nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs), and
[S&P DJI data/index licensing](https://www.spglobal.com/spdji/en/about-us/data-index-licensing/).

Historical S&P constituent data is licensed. Integration requires an approved agreement covering use,
retention, derived artifacts, and redistribution. Current web constituent lists, including Wikipedia,
are prohibited as PIT history because they are survivorship-biased and cannot prove `available_at`.

| Capability | State | Remaining condition |
|---|---|---|
| Security-master PIT contract | CLOSED | Implemented stable identity, temporal listing/ticker, CIK lineage, provider/legal metadata |
| Historical-constituents PIT contract | CLOSED | Implemented entry/exit, record validity, availability and permanent-ID joins |
| Reconstruction, validation and hashes | CONTRACT-CLOSED | Provider/source/runtime/membership/master/CIK are sealed fail-closed |
| Governed Universe -> SEC integration | CONTRACT-CLOSED | E2E contract test; ticker lists are not accepted |
| SEC ticker associations | PARTIAL | Current CIK association only; no proven permanent security ID or membership history |
| Nasdaq symbol directories | PARTIAL | Current listing evidence; historical completeness unproven |
| Real security master + historical constituents | OPEN-EXTERNAL | License provider, prove coverage/PIT semantics, preserve raw acquisitions |
| Structural merger/spinoff relationships | CONTRACT-CLOSED | Identity lineage only; economics remain out of scope |
| Global readiness | OPEN-EXTERNAL | Remains `INSUFFICIENT_REAL_DATA` |

Reconstruction rejects placeholder lineage, malformed hashes, future evidence, inactive listings,
outsiders, duplicates, overlaps/conflicts, ambiguous identities, required-but-missing CIKs, stale hashes,
and observations that do not exactly cover membership. Tickers are attributes: change and reuse never
create or merge permanent identities. `historical_completeness` is fixed to false, so a current list
cannot promote itself to complete history.

A real provider must use the existing content-addressed `RawSnapshotStore` for every response and bind
the acquisition event, content hash, licensing status, and retention policy. Before changing
`OPEN_EXTERNAL`, independently verify legal rights; stable-ID semantics; listing/delisting, ticker/name,
share-class, merger/spinoff and constituent entry/exit coverage; corrections; announcement/effective
dates; `available_at`; rate limits; retention; replay; and adversarial dead/reused securities.

An independent integral audit of code, legal rights, raw evidence, PIT chronology, hashes, and the
Universe->SEC boundary is required before merge.
