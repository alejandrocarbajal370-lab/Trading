# ADR 0001 — Phase 7F External Trust Boundary Architecture

Status: **IMPLEMENTED CONTRACT DESIGN; DRAFT REVIEW; NO REAL EVIDENCE ADMITTED**

## Context

Phase 7E is integrated at `4c0825a662c9d0bc086dad9d81a2fc3f929686c3`. It defines ten
provider-agnostic evidence gates and deliberately leaves each one `OPEN_EXTERNAL`. Its real
verifier cannot produce `VERIFIED` because the repository has neither an independently governed
custody trust anchor nor a governed reviewer identity registry.

The next work must not select a provider, manufacture evidence, or integrate real data. It must
first define the boundary through which future external evidence and review decisions could become
authentic inputs. We name that bounded design phase **Phase 7F — External Trust Boundary
Architecture**. This ADR establishes the roadmap; it does not implement a production resolver.

## Decision

Phase 7F specifies provider-neutral contracts for:

1. a canonical trust-anchor registry whose entries identify an independently controlled evidence
   system, authority, supported artifact classes, version, activation/revocation times, and audit
   lineage;
2. an evidence resolver that returns immutable source bytes plus canonical source identity,
   retrieval time, version, custody metadata, and integrity digest, while treating network,
   authorization, ambiguity, revocation, and mismatch failures as closed gates;
3. a governed reviewer identity registry with stable actor IDs, aliases, roles, validity windows,
   revocation, authority provenance, and maker/checker separation based on canonical identity;
4. a provider/dataset onboarding envelope that binds a candidate and declared scope to required
   authorities without treating registration, credentials, or connectivity as approval;
5. deterministic admission ordering: candidate declaration, authority resolution, evidence
   resolution, reviewer resolution, policy/scope/time validation, maker-checker decision, gate
   derivation, and independent aggregate audit;
6. explicit interfaces between those contracts and Phase 7E, without enabling a real `VERIFIED`
   result until independently provisioned implementations and authentic external records exist.

All contracts and examples created in Phase 7F remain `CONTRACT_TEST_ONLY`. Repository files,
fixtures, caller-provided objects, self-hashes, environment variables, and display names are never
canonical external authorities.

## Gap classification

### A — Internal work implementable without a real provider

- trust-anchor and evidence-resolver interface semantics;
- reviewer identity, alias, role, validity, and revocation semantics;
- provider/dataset onboarding envelope and declared-scope binding;
- failure taxonomy and fail-closed admission ordering;
- synthetic/adversarial contract tests and integration seam with Phase 7E;
- roadmap and audit requirements for independently provisioned implementations.

### B — External evidence or authority required

- provider and exact dataset/version selection;
- authoritative custody endpoints and their independently controlled configuration;
- governed identity authority and real reviewer appointments;
- legal/licensing approval and retention/WORM control proof;
- historical PIT/security-master completeness, real FX, shares outstanding PIT, restatement
  materiality, corporate-action economics, operations/monitoring, and scale evidence;
- independent evidence review and final admission audit.

### C — Future work blocked by A or B

- production resolver adapters and live external-evidence admission;
- provider data adapters and real-data coverage/reconciliation runs;
- operational and scale qualification using representative workloads;
- any transition from `QVM_NOT_READY`, `INSUFFICIENT_REAL_DATA`, or `NOT_AUTHORIZED`;
- backtesting, signals, portfolio construction, sizing, target prices, broker integration, orders,
  execution, dashboard, or Excel work.

## Phase 7F acceptance criteria

Phase 7F may be called contract-design complete only when:

- every authority and resolver contract is versioned, provider-neutral, and has canonical primitive
  serialization semantics;
- trust-anchor, artifact, provider, dataset, scope, policy, reviewer, decision, and time bindings
  are explicit and cannot be supplied by an untrusted result DTO;
- duplicate aliases, same-actor maker/checker, unknown or revoked actors, unknown or revoked trust
  anchors, stale/ambiguous sources, integrity mismatches, partial scope, and resolution failures all
  fail closed;
- contract tests prove that synthetic fixtures can validate mechanics but cannot produce real
  `VERIFIED` gates or readiness;
- Phase 7E remains the sole gate vocabulary and its ten real gates remain `OPEN_EXTERNAL` in the
  absence of independently provisioned authorities and authentic evidence;
- the order and audit record for future admission are deterministic and independently reviewable;
- tests, Ruff, diff checks, and CI pass; and an independent re-audit is required before merge.

## Out of scope

Provider selection or procurement, credentials, live endpoints, real reviewer enrollment, legal
approval, evidence collection, production custody configuration, real gate closure, real-data
integration, readiness promotion, backtesting, investment outputs, and execution are excluded.

## Consequences and roadmap

Phase 7F is the next internal phase because it closes the architectural trust-boundary gap that
Phase 7E explicitly identifies, while remaining independent of provider selection. It cannot close
any external gate.

After Phase 7F, external authority provisioning and provider/dataset selection must occur outside
the repository's self-asserted trust domain. Only then may a separately authorized evidence-review
phase exercise the boundary with authentic records. Real-data adapter integration and operational
qualification follow successful evidence admission; readiness review follows those validations and
must remain a separate decision.

## Permanent safety state

- `trade_decision=NO_TRADE`
- `live_execution_enabled=false`
- `signals_generated=false`
- real route `QVM_NOT_READY`
- `global_readiness=INSUFFICIENT_REAL_DATA`
- backtesting `NOT_AUTHORIZED`
- no provider is selected and no real evidence is represented as admitted
