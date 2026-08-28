from __future__ import annotations

import datetime
import math
import re
from enum import StrEnum
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data.fx import FXConversion, FXDataset, FXGovernanceError
from fundamentals.governance import AccountingDataset, canonical_accounting_checksum
from governance.canonical import runtime_fingerprint, typed_hash
from governance.pre_phase6 import metric_applicability
from governance.research_chain import GovernedFactorBatch
from research.pre_phase6_readiness import PrePhase6Admission, admit_sealed_for_phase6

CONFIDENCE_THRESHOLD: Literal[0.8] = 0.8
CONFIDENCE_CONTRACT_VERSION = "governed-confidence-evidence-v3"
CONFIDENCE_POLICY_VERSION = "contractual-control-min-0.80-v2"
SUFFICIENCY_POLICY_VERSION = "qv-phase6-exact-v2"
FX_USE_POLICY_VERSION = "fx-exact-direct-no-fill-v2"
READINESS_POLICY_VERSION = "phase7d-readiness-v3"
ADMISSION_CONTRACT_VERSION = "qvm-real-data-admission-v3.2"
SHA = r"^[0-9a-f]{64}$"


class Phase7DContractError(ValueError):
    pass


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _strict_probability(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("confidence must be numeric or None")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("confidence must be finite within [0,1]")
    return result


class UpstreamEvidenceProof(ContractModel):
    version: Literal["phase7d-upstream-evidence-reference-v2"] = (
        "phase7d-upstream-evidence-reference-v2"
    )
    component: Literal[
        "data_confidence", "mapping_confidence", "calculation_confidence", "economic_confidence"
    ]
    evidence_type: Literal[
        "ACCOUNTING_CONTENT_VERIFIED",
        "EXACT_MAPPING_REPLAY",
        "CALCULATION_REPLAY",
        "ECONOMIC_VALIDATION",
    ]
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=SHA)
    as_of: datetime.datetime
    governed_object_type: Literal[
        "AccountingDataset",
        "MappingPolicy",
        "CalculationPolicy",
        "EconomicValidation",
    ]
    governed_object_id: str
    governed_object_hash: str = Field(pattern=SHA)
    score: float | None
    proof_hash: str = Field(pattern=SHA)

    @field_validator("score", mode="before")
    @classmethod
    def strict_score(cls, value: object) -> object:
        return _strict_probability(value)

    @model_validator(mode="after")
    def verify(self) -> UpstreamEvidenceProof:
        expected = {
            "data_confidence": "ACCOUNTING_CONTENT_VERIFIED",
            "mapping_confidence": "EXACT_MAPPING_REPLAY",
            "calculation_confidence": "CALCULATION_REPLAY",
            "economic_confidence": "ECONOMIC_VALIDATION",
        }[self.component]
        if self.evidence_type != expected:
            raise ValueError("evidence component/type mismatch")
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("upstream evidence hash mismatch")
        return self


class CanonicalUpstreamEvidence(ContractModel):
    """A context-owned object. Its identity is recomputed, never caller-declared."""

    component: Literal[
        "data_confidence", "mapping_confidence", "calculation_confidence", "economic_confidence"
    ]
    evidence_type: Literal[
        "ACCOUNTING_CONTENT_VERIFIED",
        "EXACT_MAPPING_REPLAY",
        "CALCULATION_REPLAY",
        "ECONOMIC_VALIDATION",
    ]
    governed_object_type: Literal[
        "AccountingDataset", "MappingPolicy", "CalculationPolicy", "EconomicValidation"
    ]
    governed_object_id: str
    governed_object_hash: str = Field(pattern=SHA)
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=SHA)
    as_of: datetime.datetime
    score: float | None

    @field_validator("score", mode="before")
    @classmethod
    def strict_score(cls, value: object) -> object:
        return _strict_probability(value)


class UpstreamProofContext(ContractModel):
    evidence: tuple[CanonicalUpstreamEvidence, ...]


def canonical_confidence_evidence(
    accounting: AccountingDataset,
    *,
    component: str,
    as_of: datetime.datetime,
    economic_validation: CanonicalUpstreamEvidence | None = None,
) -> CanonicalUpstreamEvidence:
    """Build evidence only from governed datasets/policies, never naked hashes."""
    if component == "economic_confidence":
        if economic_validation is None:
            raise Phase7DContractError("economic confidence requires governed external evidence")
        return economic_validation
    kind = {
        "data_confidence": "ACCOUNTING_CONTENT_VERIFIED",
        "mapping_confidence": "EXACT_MAPPING_REPLAY",
        "calculation_confidence": "CALCULATION_REPLAY",
    }[component]
    object_type = {
        "data_confidence": "AccountingDataset",
        "mapping_confidence": "MappingPolicy",
        "calculation_confidence": "CalculationPolicy",
    }[component]
    object_id = {
        "data_confidence": accounting.metadata.canonical_id,
        "mapping_confidence": SUFFICIENCY_POLICY_VERSION,
        "calculation_confidence": "accounting-qv-adapter-v2",
    }[component]
    object_hash = {
        "data_confidence": canonical_accounting_checksum(accounting.snapshot(cutoff=as_of)),
        "mapping_confidence": sufficiency_policy_hash(),
        "calculation_confidence": typed_hash(
            {"adapter": "accounting-qv-adapter-v2", "matrix": sufficiency_policy_hash()}
        ),
    }[component]
    return CanonicalUpstreamEvidence(
        component=component,
        evidence_type=kind,
        governed_object_type=object_type,
        governed_object_id=object_id,
        governed_object_hash=object_hash,
        accounting_canonical_id=accounting.metadata.canonical_id,
        accounting_checksum=accounting.metadata.checksum,
        as_of=as_of,
        score=1.0,
    )


def reference_upstream_evidence(evidence: CanonicalUpstreamEvidence) -> UpstreamEvidenceProof:
    values = evidence.model_dump(mode="python")
    payload = {
        "version": "phase7d-upstream-evidence-reference-v2",
        **evidence.model_dump(mode="json"),
    }
    return UpstreamEvidenceProof(**values, proof_hash=typed_hash(payload))


def verify_upstream_evidence(
    proof: UpstreamEvidenceProof, context: UpstreamProofContext
) -> CanonicalUpstreamEvidence:
    candidates = [
        x
        for x in context.evidence
        if (
            x.component,
            x.evidence_type,
            x.governed_object_type,
            x.governed_object_id,
            x.governed_object_hash,
            x.accounting_canonical_id,
            x.accounting_checksum,
            x.as_of,
            x.score,
        )
        == (
            proof.component,
            proof.evidence_type,
            proof.governed_object_type,
            proof.governed_object_id,
            proof.governed_object_hash,
            proof.accounting_canonical_id,
            proof.accounting_checksum,
            proof.as_of,
            proof.score,
        )
    ]
    if len(candidates) != 1:
        raise Phase7DContractError("upstream evidence reference is not resolvable")
    return candidates[0]


class ConfidenceComponent(ContractModel):
    name: Literal[
        "data_confidence", "mapping_confidence", "calculation_confidence", "economic_confidence"
    ]
    score: float | None
    semantics: Literal["DETERMINISTIC_CONTRACT_CONTROL"] = "DETERMINISTIC_CONTRACT_CONTROL"
    upstream_proofs: tuple[UpstreamEvidenceProof, ...] = Field(min_length=1)
    rationale_code: str

    @field_validator("score", mode="before")
    @classmethod
    def strict_score(cls, value: object) -> object:
        return _strict_probability(value)

    @model_validator(mode="after")
    def verify(self) -> ConfidenceComponent:
        if any(x.component != self.name for x in self.upstream_proofs):
            raise ValueError("confidence evidence component mismatch")
        score = (
            None
            if any(x.score is None for x in self.upstream_proofs)
            else min(x.score for x in self.upstream_proofs if x.score is not None)
        )
        if score != self.score:
            raise ValueError("score not recomputed from upstream proofs")
        return self


def confidence_policy_hash() -> str:
    return typed_hash(
        {
            "version": CONFIDENCE_POLICY_VERSION,
            "threshold": 0.8,
            "aggregation": "MIN_ALL_SUPPLIED",
            "semantics": "CONTRACTUAL_NOT_PREDICTIVE",
        }
    )


class GovernedConfidenceProof(ContractModel):
    contract_version: Literal["governed-confidence-evidence-v3"] = CONFIDENCE_CONTRACT_VERSION
    policy_version: Literal["contractual-control-min-0.80-v2"] = CONFIDENCE_POLICY_VERSION
    policy_hash: str = Field(pattern=SHA)
    threshold: Literal[0.8] = 0.8
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=SHA)
    as_of: datetime.datetime
    components: tuple[ConfidenceComponent, ...]
    governed_score: float | None
    state: Literal["CONTRACTUAL_CONTROL_PASS", "UNKNOWN", "BELOW_THRESHOLD"]
    proof_hash: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def verify(self) -> GovernedConfidenceProof:
        required = {"data_confidence", "mapping_confidence", "calculation_confidence"}
        names = [x.name for x in self.components]
        if len(names) != len(set(names)) or not required <= set(names):
            raise ValueError("invalid confidence components")
        if self.policy_hash != confidence_policy_hash():
            raise ValueError("non-canonical confidence policy")
        if any(
            (p.accounting_canonical_id, p.accounting_checksum, p.as_of)
            != (self.accounting_canonical_id, self.accounting_checksum, self.as_of)
            for c in self.components
            for p in c.upstream_proofs
        ):
            raise ValueError("upstream confidence identity mismatch")
        score = (
            None
            if any(x.score is None for x in self.components)
            else min(x.score for x in self.components if x.score is not None)
        )
        state = (
            "UNKNOWN"
            if score is None
            else ("CONTRACTUAL_CONTROL_PASS" if score >= 0.8 else "BELOW_THRESHOLD")
        )
        if (score, state) != (self.governed_score, self.state):
            raise ValueError("confidence aggregation mismatch")
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("confidence proof hash mismatch")
        return self


def seal_confidence(
    accounting: AccountingDataset,
    *,
    as_of: datetime.datetime,
    components: tuple[ConfidenceComponent, ...],
) -> GovernedConfidenceProof:
    score = (
        None
        if any(x.score is None for x in components)
        else min(x.score for x in components if x.score is not None)
    )
    state = (
        "UNKNOWN"
        if score is None
        else ("CONTRACTUAL_CONTROL_PASS" if score >= 0.8 else "BELOW_THRESHOLD")
    )
    values = {
        "policy_hash": confidence_policy_hash(),
        "threshold": 0.8,
        "accounting_canonical_id": accounting.metadata.canonical_id,
        "accounting_checksum": accounting.metadata.checksum,
        "as_of": as_of,
        "components": components,
        "governed_score": score,
        "state": state,
    }
    payload = {
        "contract_version": CONFIDENCE_CONTRACT_VERSION,
        "policy_version": CONFIDENCE_POLICY_VERSION,
        **values,
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "components": [x.model_dump(mode="json") for x in components],
    }
    return GovernedConfidenceProof(**values, proof_hash=typed_hash(payload))


def verify_governed_confidence(
    proof: GovernedConfidenceProof,
    *,
    accounting: AccountingDataset,
    upstream_context: UpstreamProofContext,
) -> GovernedConfidenceProof:
    """Resolve every reference. Self-hash proves integrity, never authenticity."""
    parsed = GovernedConfidenceProof.model_validate(proof.model_dump(mode="python"))
    if (parsed.accounting_canonical_id, parsed.accounting_checksum) != (
        accounting.metadata.canonical_id,
        accounting.metadata.checksum,
    ):
        raise Phase7DContractError("confidence Accounting identity mismatch")
    for component in parsed.components:
        for reference in component.upstream_proofs:
            verify_upstream_evidence(reference, upstream_context)
    return parsed


class SufficiencyClass(StrEnum):
    REQUIRED_PRIMARY = "REQUIRED_PRIMARY"
    OPTIONAL_DIAGNOSTIC = "OPTIONAL_DIAGNOSTIC"


class MetricRequirement(ContractModel):
    factor: Literal["Quality", "Value"]
    output_metric: str
    classification: SufficiencyClass
    required_inputs: tuple[str, ...]
    formula: str
    history_periods: int = 1
    forbidden_proxies: tuple[str, ...] = ()


def _requirements() -> tuple[MetricRequirement, ...]:
    r = "REQUIRED_PRIMARY"
    rows = [
        (
            "Quality",
            "cfo_conversion",
            r,
            ("cash_from_operations", "net_income"),
            "cash_from_operations/net_income",
            1,
        ),
        (
            "Quality",
            "fcf_margin",
            r,
            ("cash_from_operations", "capital_expenditures", "revenue"),
            "(cash_from_operations-capital_expenditures)/revenue",
            1,
        ),
        (
            "Quality",
            "margin_stability",
            r,
            ("cash_from_operations", "capital_expenditures", "revenue"),
            "stdev(fcf_margin history)",
            2,
        ),
        (
            "Quality",
            "net_debt_to_ebitda",
            r,
            ("total_debt", "cash", "ebitda"),
            "(total_debt-cash)/ebitda",
            1,
        ),
        (
            "Quality",
            "raw_accrual_ratio",
            r,
            ("net_income", "cash_from_operations", "total_assets"),
            "(net_income-cash_from_operations)/total_assets",
            1,
        ),
        (
            "Quality",
            "roic",
            r,
            ("ebit", "tax_rate", "total_debt", "total_equity", "cash"),
            "ebit*(1-tax_rate)/(total_debt+total_equity-cash)",
            1,
        ),
        (
            "Quality",
            "roic_stability",
            r,
            ("ebit", "tax_rate", "total_debt", "total_equity", "cash"),
            "stdev(roic history)",
            2,
        ),
        (
            "Quality",
            "share_count_change",
            "OPTIONAL_DIAGNOSTIC",
            ("shares_history",),
            "reported",
            1,
        ),
        ("Value", "earnings_yield", r, ("net_income", "market_cap"), "net_income/market_cap", 1),
        (
            "Value",
            "fcf_yield",
            r,
            ("cash_from_operations", "capital_expenditures", "market_cap"),
            "(cash_from_operations-capital_expenditures)/market_cap",
            1,
        ),
        ("Value", "ebit_yield", r, ("ebit", "enterprise_value"), "ebit/enterprise_value", 1),
        ("Value", "ev_to_ebit", r, ("enterprise_value", "ebit"), "enterprise_value/ebit", 1),
        (
            "Value",
            "ev_to_ebitda",
            "OPTIONAL_DIAGNOSTIC",
            ("enterprise_value", "ebitda"),
            "enterprise_value/ebitda",
            1,
        ),
    ]
    return tuple(
        MetricRequirement(
            factor=a,
            output_metric=b,
            classification=c,
            required_inputs=d,
            formula=e,
            history_periods=f,
            forbidden_proxies=("NO_ECONOMIC_PROXY",)
            if b
            in {
                "roic",
                "roic_stability",
                "net_debt_to_ebitda",
                "ebit_yield",
                "ev_to_ebit",
                "ev_to_ebitda",
            }
            else (),
        )
        for a, b, c, d, e, f in sorted(rows)
    )


def sufficiency_policy_hash() -> str:
    return typed_hash({"version": SUFFICIENCY_POLICY_VERSION, "requirements": _requirements()})


class MetricSufficiencyMatrix(ContractModel):
    version: Literal["qv-phase6-exact-v2"] = SUFFICIENCY_POLICY_VERSION
    requirements: tuple[MetricRequirement, ...]
    matrix_hash: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def verify(self) -> MetricSufficiencyMatrix:
        if self.requirements != _requirements() or self.matrix_hash != sufficiency_policy_hash():
            raise ValueError("non-canonical Phase 6 sufficiency policy")
        return self


DEFAULT_SUFFICIENCY_MATRIX = MetricSufficiencyMatrix(
    requirements=_requirements(), matrix_hash=sufficiency_policy_hash()
)


class InputLineage(ContractModel):
    fact_id: str
    entity: str
    metric: str
    fiscal_year: int
    fiscal_period: str
    period_semantics: Literal["ANNUAL", "QUARTER", "YTD", "INSTANT"]
    period_start: datetime.date | None
    period_end: datetime.date
    unit: str
    currency: str | None
    available_at: datetime.datetime
    value: float


class FactorInputState(ContractModel):
    factor: Literal["Quality", "Value"]
    metric: str
    entity: str
    sector: str | None
    industry: str | None
    state: Literal["PASS", "NOT_COMPUTED", "NOT_APPLICABLE", "FX_REQUIRED"]
    reason: str
    formula: str
    value: float | None
    unit: str | None
    inputs: tuple[InputLineage, ...]


class FactorInputAdapterProof(ContractModel):
    adapter_version: Literal["accounting-qv-adapter-v2"] = "accounting-qv-adapter-v2"
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=SHA)
    accounting_snapshot_checksum: str = Field(pattern=SHA)
    confidence_proof_hash: str = Field(pattern=SHA)
    sufficiency_matrix_hash: str = Field(pattern=SHA)
    as_of: datetime.datetime
    states: tuple[FactorInputState, ...]
    proof_hash: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def verify(self) -> FactorInputAdapterProof:
        if self.sufficiency_matrix_hash != sufficiency_policy_hash():
            raise ValueError("non-canonical adapter policy")
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("adapter hash mismatch")
        return self


AccountingFactorAdapterProof = FactorInputAdapterProof


def _lineage(row: pd.Series) -> InputLineage:
    label = str(row.fiscal_period).upper()
    years = re.findall(r"(?:19|20)\d{2}", label)
    year = int(years[-1]) if years else pd.Timestamp(row.period_end).year
    start = (
        pd.Timestamp(row.fiscal_period_start).date()
        if "fiscal_period_start" in row.index and pd.notna(row.fiscal_period_start)
        else None
    )
    semantics = (
        "INSTANT"
        if "period_type" in row.index and str(row.period_type).lower() == "instant"
        else ("YTD" if "YTD" in label else ("QUARTER" if re.search(r"Q[1-4]", label) else "ANNUAL"))
    )
    unit = str(row.unit).upper()
    currency = unit if re.fullmatch(r"[A-Z]{3}", unit) else None
    return InputLineage(
        fact_id=str(row.fact_id),
        entity=str(row.entity),
        metric=str(row.metric),
        fiscal_year=year,
        fiscal_period=str(row.fiscal_period),
        period_semantics=semantics,
        period_start=start,
        period_end=pd.Timestamp(row.period_end).date(),
        unit=unit,
        currency=currency,
        available_at=pd.Timestamp(row.available_at).to_pydatetime(),
        value=float(row.value),
    )


def _calc(metric: str, v: dict[str, float]) -> float:
    formulas = {
        "cfo_conversion": lambda: v["cash_from_operations"] / v["net_income"],
        "fcf_margin": lambda: (
            (v["cash_from_operations"] - v["capital_expenditures"]) / v["revenue"]
        ),
        "raw_accrual_ratio": lambda: (
            (v["net_income"] - v["cash_from_operations"]) / v["total_assets"]
        ),
        "roic": lambda: (
            v["ebit"] * (1 - v["tax_rate"]) / (v["total_debt"] + v["total_equity"] - v["cash"])
        ),
        "net_debt_to_ebitda": lambda: (v["total_debt"] - v["cash"]) / v["ebitda"],
        "earnings_yield": lambda: v["net_income"] / v["market_cap"],
        "fcf_yield": lambda: (
            (v["cash_from_operations"] - v["capital_expenditures"]) / v["market_cap"]
        ),
        "ebit_yield": lambda: v["ebit"] / v["enterprise_value"],
        "ev_to_ebit": lambda: v["enterprise_value"] / v["ebit"],
        "ev_to_ebitda": lambda: v["enterprise_value"] / v["ebitda"],
    }
    return formulas[metric]()


def adapt_accounting_factor_inputs(
    accounting: AccountingDataset,
    *,
    confidence: GovernedConfidenceProof,
    upstream_context: UpstreamProofContext,
    as_of: datetime.datetime,
    entity_context: dict[str, tuple[str | None, str | None]] | None = None,
    sufficiency: MetricSufficiencyMatrix = DEFAULT_SUFFICIENCY_MATRIX,
) -> FactorInputAdapterProof:
    if type(accounting) is not AccountingDataset:
        raise TypeError("exact AccountingDataset required")
    confidence = verify_governed_confidence(
        confidence, accounting=accounting, upstream_context=upstream_context
    )
    MetricSufficiencyMatrix.model_validate(sufficiency.model_dump())
    if (confidence.accounting_canonical_id, confidence.accounting_checksum, confidence.as_of) != (
        accounting.metadata.canonical_id,
        accounting.metadata.checksum,
        as_of,
    ):
        raise Phase7DContractError("confidence Accounting identity mismatch")
    snap = accounting.snapshot(cutoff=as_of)
    states = []
    context = entity_context or {}
    for entity in sorted(snap.entity.astype(str).unique()):
        sector, industry = context.get(entity, (None, None))
        rows = snap.loc[snap.entity == entity]
        for req in sufficiency.requirements:
            app = metric_applicability(req.output_metric, sector, industry)
            if app.state == "NOT_APPLICABLE":
                states.append(
                    FactorInputState(
                        factor=req.factor,
                        metric=req.output_metric,
                        entity=entity,
                        sector=sector,
                        industry=industry,
                        state="NOT_APPLICABLE",
                        reason=app.reason,
                        formula=req.formula,
                        value=None,
                        unit=None,
                        inputs=(),
                    )
                )
                continue
            groups = {}
            for _, row in rows.loc[rows.metric.isin(req.required_inputs)].iterrows():
                x = _lineage(row)
                # Instant balance-sheet facts may legitimately join duration facts at
                # the same fiscal period end. Duration facts must still share their
                # exact period label/start through the compatibility check below.
                key = (x.fiscal_year, x.fiscal_period, x.period_end)
                groups.setdefault(key, {})[x.metric] = x
            complete = [g for g in groups.values() if set(g) == set(req.required_inputs)]
            compatible = [
                g
                for g in complete
                if len({x.unit for x in g.values() if x.metric != "tax_rate"}) == 1
                and len(
                    {
                        (x.period_semantics, x.period_start)
                        for x in g.values()
                        if x.period_semantics != "INSTANT"
                    }
                )
                <= 1
            ]
            if len(compatible) < req.history_periods:
                cross = next(
                    (
                        g
                        for g in complete
                        if len({x.currency for x in g.values() if x.currency}) > 1
                    ),
                    None,
                )
                states.append(
                    FactorInputState(
                        factor=req.factor,
                        metric=req.output_metric,
                        entity=entity,
                        sector=sector,
                        industry=industry,
                        state="FX_REQUIRED" if cross else "NOT_COMPUTED",
                        reason="governed direct FX required"
                        if cross
                        else "missing/incompatible entity-period-semantics-unit inputs",
                        formula=req.formula,
                        value=None,
                        unit=None,
                        inputs=tuple(sorted((cross or {}).values(), key=lambda x: x.metric)),
                    )
                )
                continue
            group = compatible[-1]
            inputs = tuple(sorted(group.values(), key=lambda x: x.metric))
            try:
                if req.output_metric in {"margin_stability", "roic_stability"}:
                    base = "fcf_margin" if req.output_metric == "margin_stability" else "roic"
                    history = [
                        _calc(base, {k: x.value for k, x in period.items()})
                        for period in compatible
                    ]
                    mean = sum(history) / len(history)
                    value = math.sqrt(sum((x - mean) ** 2 for x in history) / len(history))
                    inputs = tuple(
                        sorted(
                            (item for period in compatible for item in period.values()),
                            key=lambda x: (x.period_end, x.metric),
                        )
                    )
                else:
                    value = _calc(req.output_metric, {k: x.value for k, x in group.items()})
                assert math.isfinite(value)
            except (KeyError, ZeroDivisionError, AssertionError):
                value = None
            states.append(
                FactorInputState(
                    factor=req.factor,
                    metric=req.output_metric,
                    entity=entity,
                    sector=sector,
                    industry=industry,
                    state="PASS" if value is not None else "NOT_COMPUTED",
                    reason="exact formula replay"
                    if value is not None
                    else "invalid denominator/history",
                    formula=req.formula,
                    value=value,
                    unit="ratio" if value is not None else None,
                    inputs=inputs,
                )
            )
    values = {
        "accounting_canonical_id": accounting.metadata.canonical_id,
        "accounting_checksum": accounting.metadata.checksum,
        "accounting_snapshot_checksum": canonical_accounting_checksum(snap),
        "confidence_proof_hash": confidence.proof_hash,
        "sufficiency_matrix_hash": sufficiency_policy_hash(),
        "as_of": as_of,
        "states": tuple(sorted(states, key=lambda x: (x.factor, x.metric, x.entity))),
    }
    payload = {
        "adapter_version": "accounting-qv-adapter-v2",
        **values,
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "states": [x.model_dump(mode="json") for x in values["states"]],
    }
    return FactorInputAdapterProof(**values, proof_hash=typed_hash(payload))


class FXConversionUse(ContractModel):
    input_fact_id: str
    adapter_proof_hash: str | None
    source_currency: str
    target_currency: str
    amount: float
    rate: float
    converted_amount: float
    semantics: Literal["TARGET=SOURCE*DIRECT_RATE", "IDENTITY"]
    market_timestamp: datetime.datetime | None
    available_at: datetime.datetime | None
    source: str | None
    source_record_id: str | None
    raw_evidence_hash: str | None
    fx_canonical_id: str | None
    fx_checksum: str | None
    fx_dataset_version: str | None
    staleness_policy_hash: str | None


class FXUseProof(ContractModel):
    policy_version: Literal["fx-exact-direct-no-fill-v2"] = FX_USE_POLICY_VERSION
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=SHA)
    adapter_proof_hash: str | None
    fx_canonical_id: str | None
    fx_checksum: str | None
    conversions: tuple[FXConversionUse, ...] = Field(min_length=1)
    proof_hash: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def verify(self) -> FXUseProof:
        cross = [x for x in self.conversions if x.source_currency != x.target_currency]
        if cross and (not self.fx_canonical_id or not self.fx_checksum):
            raise ValueError("cross FX lacks governed dataset")
        if any(x.semantics != "TARGET=SOURCE*DIRECT_RATE" for x in cross):
            raise ValueError("FX orientation mismatch")
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("FX use hash mismatch")
        return self


def governed_fx_conversion(
    fx: FXDataset | None,
    *,
    accounting: AccountingDataset,
    amount: float,
    source_currency: str,
    target_currency: str,
    market_at: datetime.datetime,
    cutoff: datetime.datetime,
    input_fact_id: str = "UNBOUND",
    adapter_proof_hash: str | None = None,
) -> tuple[FXConversion, FXUseProof]:
    same = source_currency.upper() == target_currency.upper()
    if same and fx is None:
        c = FXConversion(
            amount=float(amount),
            source_currency=source_currency.upper(),
            target_currency=target_currency.upper(),
            converted_amount=float(amount),
            rate=1.0,
            conversion_method="identity",
            rate_market_timestamp=None,
            rate_available_at=None,
            fx_canonical_id=None,
            fx_checksum=None,
            fx_source=None,
            fx_dataset_version=None,
        )
        record = raw = None
    else:
        if fx is None:
            raise Phase7DContractError("cross-currency requires governed FX")
        c = fx.convert(
            amount,
            source_currency=source_currency,
            target_currency=target_currency,
            market_at=market_at,
            cutoff=cutoff,
        )
        if not same and c.conversion_method != "direct":
            raise FXGovernanceError("implicit inverse forbidden")
        row = fx.frame.loc[
            (fx.frame.base_currency == c.source_currency)
            & (fx.frame.quote_currency == c.target_currency)
            & (fx.frame.market_timestamp == pd.Timestamp(c.rate_market_timestamp))
            & (fx.frame.available_at == pd.Timestamp(c.rate_available_at))
        ].iloc[0]
        row_identity = typed_hash(row.to_dict())
        record = str(row["source_record_id"]) if "source_record_id" in row else row_identity
        raw = str(row["raw_evidence_hash"]) if "raw_evidence_hash" in row else row_identity
    use = FXConversionUse(
        input_fact_id=input_fact_id,
        adapter_proof_hash=adapter_proof_hash,
        source_currency=c.source_currency,
        target_currency=c.target_currency,
        amount=c.amount,
        rate=c.rate,
        converted_amount=c.converted_amount,
        semantics="IDENTITY" if same else "TARGET=SOURCE*DIRECT_RATE",
        market_timestamp=c.rate_market_timestamp,
        available_at=c.rate_available_at,
        source=c.fx_source,
        source_record_id=record,
        raw_evidence_hash=raw,
        fx_canonical_id=c.fx_canonical_id,
        fx_checksum=c.fx_checksum,
        fx_dataset_version=c.fx_dataset_version,
        staleness_policy_hash=None
        if same
        else typed_hash(fx.metadata.staleness_policy.model_dump(mode="json")),
    )
    values = {
        "accounting_canonical_id": accounting.metadata.canonical_id,
        "accounting_checksum": accounting.metadata.checksum,
        "adapter_proof_hash": adapter_proof_hash,
        "fx_canonical_id": c.fx_canonical_id,
        "fx_checksum": c.fx_checksum,
        "conversions": (use,),
    }
    return c, FXUseProof(
        **values,
        proof_hash=typed_hash(
            {
                "policy_version": FX_USE_POLICY_VERSION,
                **values,
                "conversions": [use.model_dump(mode="json")],
            }
        ),
    )


def verify_fx_use_proof(
    proof: FXUseProof,
    *,
    fx_dataset: FXDataset | None,
    accounting: AccountingDataset,
    adapter_proof_hash: str | None,
) -> FXUseProof:
    parsed = FXUseProof.model_validate(proof.model_dump(mode="python"))
    if (parsed.accounting_canonical_id, parsed.accounting_checksum, parsed.adapter_proof_hash) != (
        accounting.metadata.canonical_id,
        accounting.metadata.checksum,
        adapter_proof_hash,
    ):
        raise Phase7DContractError("FX consuming identity mismatch")
    for item in parsed.conversions:
        if item.source_currency == item.target_currency:
            expected = (
                1.0,
                item.amount,
                "IDENTITY",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            observed = (
                item.rate,
                item.converted_amount,
                item.semantics,
                item.market_timestamp,
                item.available_at,
                item.source,
                item.source_record_id,
                item.raw_evidence_hash,
                item.fx_canonical_id,
                item.fx_checksum,
                item.fx_dataset_version,
            )
            if observed != expected:
                raise Phase7DContractError("fabricated same-currency FX lineage")
            continue
        if fx_dataset is None:
            raise Phase7DContractError("cross FX lacks governed dataset")
        if (parsed.fx_canonical_id, parsed.fx_checksum, item.fx_canonical_id, item.fx_checksum) != (
            fx_dataset.metadata.canonical_id,
            fx_dataset.metadata.checksum,
            fx_dataset.metadata.canonical_id,
            fx_dataset.metadata.checksum,
        ):
            raise Phase7DContractError("FX dataset identity mismatch")
        rows = fx_dataset.frame.loc[
            (fx_dataset.frame.base_currency == item.source_currency)
            & (fx_dataset.frame.quote_currency == item.target_currency)
            & (fx_dataset.frame.market_timestamp == pd.Timestamp(item.market_timestamp))
            & (fx_dataset.frame.available_at == pd.Timestamp(item.available_at))
        ]
        if len(rows) != 1:
            raise Phase7DContractError("exact FX observation is not resolvable")
        row = rows.iloc[0]
        row_identity = typed_hash(row.to_dict())
        expected_record = (
            str(row["source_record_id"]) if "source_record_id" in row else row_identity
        )
        expected_raw = str(row["raw_evidence_hash"]) if "raw_evidence_hash" in row else row_identity
        if (
            item.rate != float(row.rate)
            or item.converted_amount != item.amount * float(row.rate)
            or item.source != fx_dataset.metadata.source
            or item.source_record_id != expected_record
            or item.raw_evidence_hash != expected_raw
            or item.fx_dataset_version != fx_dataset.metadata.dataset_version
            or item.staleness_policy_hash
            != typed_hash(fx_dataset.metadata.staleness_policy.model_dump(mode="json"))
            or item.semantics != "TARGET=SOURCE*DIRECT_RATE"
        ):
            raise Phase7DContractError("FX exact-lineage replay mismatch")
    return parsed


class ProviderGateEvidence(ContractModel):
    gate: Literal["LEGAL_ACCESS", "HISTORICAL_PIT", "OPERATIONS_MONITORED"]
    provider: str
    dataset_identity: str
    evidence_source: str
    evidence_record_id: str
    evidence_hash: str = Field(pattern=SHA)
    as_of: datetime.datetime


class ProviderEvidenceContext(ContractModel):
    evidence: tuple[ProviderGateEvidence, ...]


class ProviderReadinessProof(ContractModel):
    version: Literal["provider-readiness-v2"] = "provider-readiness-v2"
    provider: str
    dataset_identity: str
    gate_references: tuple[ProviderGateEvidence, ...]
    state: Literal["VERIFIED", "OPEN_EXTERNAL"]
    as_of: datetime.datetime
    proof_hash: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def verify(self) -> ProviderReadinessProof:
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("provider proof hash mismatch")
        return self


def assess_provider_readiness(
    *,
    provider: str,
    dataset_identity: str,
    as_of: datetime.datetime,
    evidence: tuple[ProviderGateEvidence, ...] = (),
) -> ProviderReadinessProof:
    required = {"LEGAL_ACCESS", "HISTORICAL_PIT", "OPERATIONS_MONITORED"}
    matched = tuple(
        x
        for x in evidence
        if (x.provider, x.dataset_identity, x.as_of) == (provider, dataset_identity, as_of)
    )
    state = (
        "VERIFIED"
        if {x.gate for x in matched} == required and len(matched) == 3
        else "OPEN_EXTERNAL"
    )
    values = {
        "provider": provider,
        "dataset_identity": dataset_identity,
        "gate_references": matched,
        "state": state,
        "as_of": as_of,
    }
    payload = {
        "version": "provider-readiness-v2",
        **values,
        "gate_references": [x.model_dump(mode="json") for x in matched],
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
    }
    return ProviderReadinessProof(**values, proof_hash=typed_hash(payload))


def verify_provider_readiness(
    proof: ProviderReadinessProof, context: ProviderEvidenceContext
) -> ProviderReadinessProof:
    parsed = ProviderReadinessProof.model_validate(proof.model_dump(mode="python"))
    required = {"LEGAL_ACCESS", "HISTORICAL_PIT", "OPERATIONS_MONITORED"}
    resolved = [x for x in parsed.gate_references if x in context.evidence]
    if parsed.state != "VERIFIED" or len(resolved) != 3 or {x.gate for x in resolved} != required:
        raise Phase7DContractError("provider readiness remains OPEN_EXTERNAL")
    return parsed


class PipelineState(StrEnum):
    ACCOUNTING_BOUND = "ACCOUNTING_BOUND"
    CONFIDENCE_BOUND = "CONFIDENCE_BOUND"
    FACTOR_INPUTS_BOUND = "FACTOR_INPUTS_BOUND"
    QVM_NOT_READY = "QVM_NOT_READY"
    QVM_ADMISSIBLE = "QVM_ADMISSIBLE"


READINESS_EDGES = {
    (PipelineState.ACCOUNTING_BOUND, PipelineState.CONFIDENCE_BOUND): "GovernedConfidenceProof",
    (PipelineState.CONFIDENCE_BOUND, PipelineState.FACTOR_INPUTS_BOUND): "FactorInputAdapterProof",
    (PipelineState.FACTOR_INPUTS_BOUND, PipelineState.QVM_NOT_READY): "ProviderReadinessProof",
    (PipelineState.FACTOR_INPUTS_BOUND, PipelineState.QVM_ADMISSIBLE): "PrePhase6Admission",
}


def readiness_policy_hash() -> str:
    return typed_hash(
        {
            "version": READINESS_POLICY_VERSION,
            "edges": sorted((a.value, b.value, kind) for (a, b), kind in READINESS_EDGES.items()),
        }
    )


class ReadinessTransition(ContractModel):
    from_state: PipelineState
    to_state: PipelineState
    prerequisite_type: Literal[
        "GovernedConfidenceProof",
        "FactorInputAdapterProof",
        "ProviderReadinessProof",
        "PrePhase6Admission",
    ]
    prerequisite_hash: str = Field(pattern=SHA)


class ReadinessStateProof(ContractModel):
    policy_version: Literal["phase7d-readiness-v3"] = READINESS_POLICY_VERSION
    policy_hash: str = Field(pattern=SHA)
    transitions: tuple[ReadinessTransition, ...] = Field(min_length=1)
    state: PipelineState
    proof_hash: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def verify(self) -> ReadinessStateProof:
        if self.policy_hash != readiness_policy_hash() or (
            self.transitions[0].from_state != "ACCOUNTING_BOUND"
            or any(
                a.to_state != b.from_state for a, b in zip(self.transitions, self.transitions[1:])
            )
            or self.transitions[-1].to_state != self.state
        ):
            raise ValueError("readiness transition jump")
        for transition in self.transitions:
            if (
                READINESS_EDGES.get((transition.from_state, transition.to_state))
                != transition.prerequisite_type
            ):
                raise ValueError("non-canonical readiness edge or prerequisite")
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("readiness hash mismatch")
        return self


def _readiness(
    admissible: bool, confidence_hash: str, adapter_hash: str, terminal_hash: str
) -> ReadinessStateProof:
    end = PipelineState.QVM_ADMISSIBLE if admissible else PipelineState.QVM_NOT_READY
    ts = (
        ReadinessTransition(
            from_state="ACCOUNTING_BOUND",
            to_state="CONFIDENCE_BOUND",
            prerequisite_type="GovernedConfidenceProof",
            prerequisite_hash=confidence_hash,
        ),
        ReadinessTransition(
            from_state="CONFIDENCE_BOUND",
            to_state="FACTOR_INPUTS_BOUND",
            prerequisite_type="FactorInputAdapterProof",
            prerequisite_hash=adapter_hash,
        ),
        ReadinessTransition(
            from_state="FACTOR_INPUTS_BOUND",
            to_state=end,
            prerequisite_type="PrePhase6Admission" if admissible else "ProviderReadinessProof",
            prerequisite_hash=terminal_hash,
        ),
    )
    return ReadinessStateProof(
        policy_hash=readiness_policy_hash(),
        transitions=ts,
        state=end,
        proof_hash=typed_hash(
            {
                "policy_version": READINESS_POLICY_VERSION,
                "policy_hash": readiness_policy_hash(),
                "transitions": [x.model_dump(mode="json") for x in ts],
                "state": end,
            }
        ),
    )


def verify_readiness_state(
    proof: ReadinessStateProof,
    *,
    confidence_hash: str,
    adapter_hash: str,
    terminal_type: str,
    terminal_hash: str,
) -> ReadinessStateProof:
    parsed = ReadinessStateProof.model_validate(proof.model_dump(mode="python"))
    expected = (confidence_hash, adapter_hash, terminal_hash)
    if tuple(x.prerequisite_hash for x in parsed.transitions) != expected:
        raise Phase7DContractError("readiness prerequisite is not resolvable")
    if parsed.transitions[-1].prerequisite_type != terminal_type:
        raise Phase7DContractError("readiness terminal prerequisite mismatch")
    return parsed


class QVMAdmissionV3(ContractModel):
    contract_version: Literal["qvm-real-data-admission-v3.2"] = ADMISSION_CONTRACT_VERSION
    state: Literal["QVM_ADMISSIBLE", "QVM_NOT_READY"]
    reasons: tuple[str, ...]
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=SHA)
    confidence_proof_hash: str | None
    adapter_proof_hash: str | None
    fx_proof_hash: str | None
    sufficiency_matrix_hash: str = Field(pattern=SHA)
    provider_proof_hashes: tuple[str, ...]
    batch_identity_hashes: tuple[str, ...]
    phase6_admission: PrePhase6Admission | None
    readiness_proof: ReadinessStateProof
    runtime_fingerprint: str
    admission_hash: str = Field(pattern=SHA)
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    research_only: Literal[True] = True
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False

    @model_validator(mode="after")
    def verify(self) -> QVMAdmissionV3:
        if (
            typed_hash(self.model_dump(mode="json", exclude={"admission_hash"}))
            != self.admission_hash
        ):
            raise ValueError("Phase 7D admission hash mismatch")
        if self.state == "QVM_ADMISSIBLE" and (
            self.reasons
            or self.phase6_admission is None
            or self.readiness_proof.state != "QVM_ADMISSIBLE"
        ):
            raise ValueError("admission prerequisites missing")
        return self


def admit_qvm_v3(
    *,
    accounting: AccountingDataset,
    confidence: GovernedConfidenceProof | None,
    adapter: FactorInputAdapterProof | None,
    fx_dataset: FXDataset | None,
    fx_proof: FXUseProof | None,
    batches: tuple[GovernedFactorBatch, ...],
    provider_proofs: tuple[ProviderReadinessProof, ...] = (),
    upstream_context: UpstreamProofContext | None = None,
    provider_context: ProviderEvidenceContext | None = None,
) -> QVMAdmissionV3:
    upstream_context = upstream_context or UpstreamProofContext(evidence=())
    provider_context = provider_context or ProviderEvidenceContext(evidence=())
    AccountingDataset(frame=accounting.frame.copy(deep=True), metadata=accounting.metadata)
    reasons = []
    if confidence is None:
        reasons.append("CONFIDENCE_PROOF_MISSING")
    else:
        try:
            confidence = verify_governed_confidence(
                confidence, accounting=accounting, upstream_context=upstream_context
            )
        except (TypeError, ValueError):
            reasons.append("CONFIDENCE_UPSTREAM_UNRESOLVED")
        if (confidence.accounting_canonical_id, confidence.accounting_checksum) != (
            accounting.metadata.canonical_id,
            accounting.metadata.checksum,
        ):
            reasons.append("CONFIDENCE_ACCOUNTING_IDENTITY_MISMATCH")
        if confidence.state != "CONTRACTUAL_CONTROL_PASS":
            reasons.append(f"CONFIDENCE_{confidence.state}")
    if adapter is None:
        reasons.append("ADAPTER_PROOF_MISSING")
    else:
        adapter = FactorInputAdapterProof.model_validate(adapter.model_dump(mode="python"))
        if (adapter.accounting_canonical_id, adapter.accounting_checksum) != (
            accounting.metadata.canonical_id,
            accounting.metadata.checksum,
        ):
            reasons.append("ADAPTER_ACCOUNTING_IDENTITY_MISMATCH")
        if confidence and adapter.confidence_proof_hash != confidence.proof_hash:
            reasons.append("ADAPTER_CONFIDENCE_MISMATCH")
        if confidence:
            contexts = {
                item.symbol: (item.sector, item.industry)
                for batch in batches
                for item in batch.classification_records
            }
            try:
                replayed = adapt_accounting_factor_inputs(
                    accounting,
                    confidence=confidence,
                    upstream_context=upstream_context,
                    as_of=confidence.as_of,
                    entity_context=contexts,
                )
                if replayed.proof_hash != adapter.proof_hash:
                    reasons.append("ADAPTER_REPLAY_MISMATCH")
            except (TypeError, ValueError):
                reasons.append("ADAPTER_REPLAY_REJECTED")
        for x in adapter.states:
            req = next(
                r
                for r in DEFAULT_SUFFICIENCY_MATRIX.requirements
                if (r.factor, r.output_metric) == (x.factor, x.metric)
            )
            if req.classification == "REQUIRED_PRIMARY" and x.state not in {
                "PASS",
                "NOT_APPLICABLE",
            }:
                reasons.append(f"REQUIRED_METRIC_NOT_PASS:{x.factor}.{x.metric}.{x.entity}")
    actual_cross = (
        []
        if adapter is None
        else [i for x in adapter.states if x.state == "FX_REQUIRED" for i in x.inputs]
    )
    target_currency = next((b.base_currency for b in batches if b.factor == "Value"), None)
    required_fx_fact_ids = {
        item.fact_id
        for state in (() if adapter is None else adapter.states)
        if state.factor == "Value" and state.state == "PASS"
        for item in state.inputs
        if item.currency and target_currency and item.currency != target_currency
    }
    if actual_cross and (fx_dataset is None or fx_proof is None):
        reasons.append("FX_PROOF_REQUIRED")
    if required_fx_fact_ids and (fx_dataset is None or fx_proof is None):
        reasons.append("FX_PROOF_REQUIRED")
    if fx_proof:
        fx_proof = FXUseProof.model_validate(fx_proof.model_dump(mode="python"))
        if fx_proof.accounting_checksum != accounting.metadata.checksum:
            reasons.append("FX_ACCOUNTING_IDENTITY_MISMATCH")
        if adapter and fx_proof.adapter_proof_hash != adapter.proof_hash:
            reasons.append("FX_ADAPTER_IDENTITY_MISMATCH")
        if fx_dataset is None or (
            fx_proof.fx_canonical_id
            and (fx_proof.fx_canonical_id, fx_proof.fx_checksum)
            != (fx_dataset.metadata.canonical_id, fx_dataset.metadata.checksum)
        ):
            reasons.append("FX_DATASET_IDENTITY_MISMATCH")
        observed_fx_fact_ids = {
            item.input_fact_id
            for item in fx_proof.conversions
            if item.source_currency != item.target_currency
        }
        if observed_fx_fact_ids != required_fx_fact_ids:
            reasons.append("FX_CONVERSION_SET_MISMATCH")
        if fx_dataset is not None:
            try:
                verify_fx_use_proof(
                    fx_proof,
                    fx_dataset=fx_dataset,
                    accounting=accounting,
                    adapter_proof_hash=None if adapter is None else adapter.proof_hash,
                )
            except (TypeError, ValueError, FXGovernanceError):
                reasons.append("FX_EXACT_LINEAGE_REPLAY_FAILED")
    for p in provider_proofs:
        try:
            verify_provider_readiness(p, provider_context)
        except (TypeError, ValueError):
            reasons.append(f"PROVIDER_OPEN_EXTERNAL:{p.provider}")
    if not provider_proofs:
        reasons.append("PROVIDER_REAL_DATA_OPEN")
    valid = []
    try:
        valid = [GovernedFactorBatch.model_validate(x.model_dump(mode="python")) for x in batches]
        for b in valid:
            if (b.accounting_canonical_id, b.accounting_checksum) != (
                accounting.metadata.canonical_id,
                accounting.metadata.checksum,
            ):
                reasons.append(f"BATCH_ACCOUNTING_IDENTITY_MISMATCH:{b.factor}")
            if confidence and b.as_of != confidence.as_of:
                reasons.append(f"BATCH_AS_OF_MISMATCH:{b.factor}")
            if b.runtime.fingerprint != runtime_fingerprint().fingerprint:
                reasons.append(f"BATCH_RUNTIME_MISMATCH:{b.factor}")
    except (TypeError, ValueError, AttributeError) as error:
        reasons.append(f"BATCH_VALIDATION_REJECTED:{error}")
    phase6 = None
    if not reasons:
        try:
            phase6 = admit_sealed_for_phase6(batches=tuple(valid))
        except (TypeError, ValueError) as error:
            reasons.append(f"PHASE6_ADMISSION_REJECTED:{error}")
    admissible = not reasons
    phase_hash = "0" * 64 if phase6 is None else typed_hash(phase6.model_dump(mode="json"))
    readiness = _readiness(
        admissible,
        "0" * 64 if confidence is None else confidence.proof_hash,
        "0" * 64 if adapter is None else adapter.proof_hash,
        phase_hash
        if admissible
        else ("0" * 64 if not provider_proofs else provider_proofs[0].proof_hash),
    )
    values = {
        "state": "QVM_ADMISSIBLE" if admissible else "QVM_NOT_READY",
        "reasons": tuple(reasons),
        "accounting_canonical_id": accounting.metadata.canonical_id,
        "accounting_checksum": accounting.metadata.checksum,
        "confidence_proof_hash": None if confidence is None else confidence.proof_hash,
        "adapter_proof_hash": None if adapter is None else adapter.proof_hash,
        "fx_proof_hash": None if fx_proof is None else fx_proof.proof_hash,
        "sufficiency_matrix_hash": sufficiency_policy_hash(),
        "provider_proof_hashes": tuple(sorted(p.proof_hash for p in provider_proofs)),
        "batch_identity_hashes": tuple(sorted(b.batch_identity_hash for b in valid)),
        "phase6_admission": phase6,
        "readiness_proof": readiness,
        "runtime_fingerprint": runtime_fingerprint().fingerprint,
        "global_readiness": "INSUFFICIENT_REAL_DATA",
        "research_only": True,
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
        "signals_generated": False,
    }
    payload = {
        "contract_version": ADMISSION_CONTRACT_VERSION,
        **values,
        "phase6_admission": None if phase6 is None else phase6.model_dump(mode="json"),
        "readiness_proof": readiness.model_dump(mode="json"),
    }
    return QVMAdmissionV3(**values, admission_hash=typed_hash(payload))


def verify_qvm_admission_v3(
    admission: QVMAdmissionV3,
    *,
    accounting: AccountingDataset,
    confidence: GovernedConfidenceProof | None,
    adapter: FactorInputAdapterProof | None,
    fx_dataset: FXDataset | None,
    fx_proof: FXUseProof | None,
    batches: tuple[GovernedFactorBatch, ...],
    provider_proofs: tuple[ProviderReadinessProof, ...] = (),
    upstream_context: UpstreamProofContext | None = None,
    provider_context: ProviderEvidenceContext | None = None,
) -> QVMAdmissionV3:
    """Governed verification for both ADMISSIBLE and NOT_READY artifacts."""
    upstream_context = upstream_context or UpstreamProofContext(evidence=())
    provider_context = provider_context or ProviderEvidenceContext(evidence=())
    parsed = QVMAdmissionV3.model_validate(admission.model_dump(mode="python"))
    expected = admit_qvm_v3(
        accounting=accounting,
        confidence=confidence,
        adapter=adapter,
        fx_dataset=fx_dataset,
        fx_proof=fx_proof,
        batches=batches,
        provider_proofs=provider_proofs,
        upstream_context=upstream_context,
        provider_context=provider_context,
    )
    if parsed != expected:
        raise Phase7DContractError("admission is not derivable from governed upstream context")
    terminal_type = (
        "PrePhase6Admission" if parsed.state == "QVM_ADMISSIBLE" else "ProviderReadinessProof"
    )
    terminal_hash = (
        typed_hash(parsed.phase6_admission.model_dump(mode="json"))
        if parsed.phase6_admission is not None
        else ("0" * 64 if not provider_proofs else provider_proofs[0].proof_hash)
    )
    verify_readiness_state(
        parsed.readiness_proof,
        confidence_hash="0" * 64 if confidence is None else confidence.proof_hash,
        adapter_hash="0" * 64 if adapter is None else adapter.proof_hash,
        terminal_type=terminal_type,
        terminal_hash=terminal_hash,
    )
    return parsed
