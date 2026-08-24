# PRE-Phase 6 remediation contract

Status: research-only. Phase 6 scoring has not started. `NO_TRADE` and
`live_execution_enabled=false` are invariant.

## Internal contracts

- Confidence policy `conservative-input-min-v1` forbids synthetic defaults. Derived confidence is
  the component-wise minimum of relevant inputs; overall confidence is the minimum component.
  Missing or invalid confidence fails closed. Derived `available_at` is the maximum actual input
  availability timestamp.
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
- Critical hashes use `typed-canonical-json-v1`; relevant manifests bind git SHA, lockfile hash,
  Python, pandas, NumPy, and platform via `research-runtime-v1`.
- Status mapping is exhaustive under `factor-status-taxonomy-v1`; unknown states fail closed.
- The exclusive PRE-Phase 6 admission entry point accepts exact sealed governed batches and has no
  score or ranking output.

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
