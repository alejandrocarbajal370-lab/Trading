# PRE-Phase 6 remediation contract

Status: integrated prerequisite. Phase 6 research-only scoring was subsequently integrated;
`NO_TRADE` and `live_execution_enabled=false` remain invariant.

## Internal contracts

- Confidence policy `conservative-input-min-v1` forbids synthetic defaults. Derived confidence is
  the component-wise minimum of relevant inputs; overall confidence is the minimum component.
  Missing or invalid confidence fails closed. Derived `available_at` is the maximum actual input
  availability timestamp.
- Market Data uses `market-data-confidence-min-input-lookback-v1`. Momentum admission requires a
  provider confidence or the three declared confidence components; the used-window confidence is
  their minimum. There is no `1.0` fallback. A final `1.0` is possible only when every declared
  provider/contract input is actually `1.0`.
- Classification contract `pit-classification-v1` preserves sector and industry, source,
  taxonomy/version, and PIT availability. `peer-assignment-v1` is row-order independent and binds
  the complete mapping to `as_of` and universe snapshot hash.
- The accrual ontology is `raw_accrual_ratio = (NI-CFO)/assets`, unit ratio,
  `lower_is_better`. Higher CFO improves the observation; larger positive accruals worsen it.
- Applicability policy `sector-applicability-v1` makes non-applicable metrics explicit. It never
  imputes or scores them. Banks, insurers, REITs, and Financials have explicit EV, leverage, and
  CFO-conversion restrictions or review states.
- Market cap preserves `original_market_cap` and `original_market_cap_currency`; converted
  `market_cap_currency` always equals `base_currency`.
- Critical hashes use `typed-canonical-json-v1`: factor observation/dataset, governed factor batch,
  peer assignment, universe snapshot, cross-layer fingerprint, sealed QVM lineage, and admission
  artifact. Row order is non-semantic; dtype and timestamp semantics remain typed. Historical
  untyped hashes remain readable in historical artifacts only and are not accepted by the v2
  admission boundary. Runtime identity binds git SHA, lockfile hash, Python, pandas, NumPy, platform,
  and implementation via `research-runtime-v1`; critical `UNAVAILABLE` fields are rejected.
- Status mapping is exhaustive under `factor-status-taxonomy-v1`; unknown states fail closed.
- The exclusive `sealed-pre-phase6-admission-v2` entry point accepts exactly one Quality, Value, and
  Momentum governed batch. It revalidates serialized batches, outer identities, exact symbols,
  dataset/batch hashes, taxonomy/applicability, PASS/finite/confidence>=0.80 observations, runtime,
  and every research-only invariant. Its output contains hashes and admission evidence, never
  batches, scores, ranks, cohorts, weights, portfolios, signals, or execution instructions.

## Design decisions frozen before implementation

These rules are design constraints only; none is implemented as scoring:

1. Confidence filtering occurs before metric activation. Applicability is evaluated next, then PIT
   peer fallback, then metric/factor/composite coverage gates.
2. A tie that crosses a cohort boundary remains intact. Cohort size may expand; symbols never split
   an economically equal tie. Symbol is only a stable display order.
3. Five-MAD clipping before rank-Gaussian is intended solely to collapse extreme tails and create
   explicit ties. Sensitivities at 3-MAD, 5-MAD, and no clipping are preregistered diagnostics, not
   return-selected alternatives.
4. Degenerate scale (`s=0`) produces an explicit non-active metric. Percentile conventions and
   minimum peer sizes require golden examples before implementation.
5. “Active within-factor weight” denominator is the sum of configured weights for applicable,
   confidence-passing observations in that factor; unavailable/non-applicable metrics receive no
   weight and are not imputed.
6. Capital-preservation thresholds are policy/diagnostic settings, separate from alpha parameters.
   Alternative factor weights are future preregistered experiments and cannot replace the initial
   baseline during implementation.

## External readiness

Provider interfaces are contract-closed for Fundamentals PIT, FX, historical security master and
constituents, restatements, independent corporate actions, and multiyear shares outstanding PIT.
They require source, dataset version, checksum/canonical identity, `available_at`, PIT semantics,
raw retention, lineage, licensing, and fail-closed behavior.

No provider is invented or claimed ready. All six remain `REAL-DATA-OPEN` until licensed real
snapshots pass their contracts. The blind-coverage command therefore reports
`INSUFFICIENT_REAL_DATA`; synthetic tests validate only the harness. It never reads outcomes or
returns, optimizes thresholds, or calculates scores.

The CI-safe scale smoke executes the complete synthetic path (universe, Market Data confidence, FX,
Accounting confidence, cross-layer integration, Financial Engine, Quality/Value/Momentum, sealing,
governed QVM identity, and admission) with three securities twice, including reversed input order.
The same workload is configurable through 5,000 securities outside CI; observed runtime/memory are
reported without brittle thresholds:

```bash
python -m research.pre_phase6_scale_smoke --securities 5000
```

The benchmark uses process peak RSS rather than `tracemalloc`: allocation tracing was measured to
dominate the workload and made the reported pipeline runtime misleading. Stage timings identify
fixture generation, Universe, Market Data, FX, Accounting, cross-layer integration, factors, and
QVM/admission independently. The 5,000-security case remains explicitly **not demonstrated**.

## Fourth-remediation integrity closure

- Every observation factor must equal its sealed batch factor at construction and at final
  admission. Mixed-factor content fails even if inner and outer hashes are recomputed.
- Alpha Vantage adjusted history has no provider confidence. Policy
  `alpha-vantage-adjusted-history-observable-fields-v1` derives a conservative `0.90` ceiling only
  after required price and corporate-action fields validate; it never emits synthetic `1.0`.
- `research-runtime-v1` recomputes its fingerprint from every runtime field during validation.
  `model_copy` mutations with stale fingerprints fail when batches are consumed.
- Governance order is fixed by `pre-phase6-governance-order-v1` and included in the governed batch
  identity. Reordering changes identity; stale or unsupported order fails closed.
- Blind readiness states are distinct: `SYNTHETIC_CONTRACT_VALIDATED`,
  `INSUFFICIENT_REAL_DATA`, and `REAL_DATA_READY`. Real readiness requires content-addressed provider
  evidence, exact effective symbols, calculated history counts, peer membership, exact batch
  bindings, and complete provider kinds. Boolean declarations cannot produce real-data readiness.
- The admission boundary reparses every batch and rechecks identities, hashes, runtime, Q/V/M
  uniqueness, exact symbols, status, applicability, finite values, confidence, and safety flags.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
ruff check .
pytest
pre-phase6-blind-coverage
```

Branch protection and required-check configuration are an operational gate and must be verified
from GitHub. A local workflow file alone is not proof that protection is enabled.
