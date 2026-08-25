# Phase 6 QVM Research Engine V1

This implementation is strictly `RESEARCH_ONLY`. Its sole public consumer boundary is
`run_phase6_qvm_research(admission=..., batches=...)`, which accepts the exact
`sealed-pre-phase6-admission-v2` artifact and exact `GovernedFactorBatch` contracts. The consumer
reconstructs admission from the supplied sealed batches and requires exact equality before any
score is calculated.

The engine implements the frozen five-MAD transform, the `s=0` inactive rule, deterministic
midranks, industry/sector/market peer fallback, directionality, active/applicable denominators,
frozen within-factor weights, equal Q/V/M composite, research-only rankings/cohorts, and the
automatable subset of the capital-preservation overlay. Every typed result is frozen and includes
a canonical content hash. The final artifact binds admission, sealed lineage, factor batch,
peer-assignment, active-metric, policy, runtime, and output identities.

The dilution, restatement-materiality, FCF-history, and corporate-action overlay checks remain
fail-closed upstream or unautomated because their governed PIT contracts are explicitly deferred
by the design. No real provider is treated as ready; successful fixtures remain synthetic contract
validation only.

This change adds no portfolio construction, position sizing, orders, broker messages, execution,
signals, backtesting, performance evaluation, outcome-driven tuning, or weight optimization.
Every composite and cohort retains `trade_decision=NO_TRADE`, `live_execution_enabled=false`,
`signals_generated=false`, and `research_only=true`.
