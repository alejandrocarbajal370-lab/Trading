from __future__ import annotations

import datetime
import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data.fx import FXConversion, FXDataset, FXGovernanceError
from fundamentals.governance import AccountingDataset
from governance.canonical import runtime_fingerprint, typed_hash
from governance.research_chain import GovernedFactorBatch
from research.pre_phase6_readiness import PrePhase6Admission, admit_sealed_for_phase6

CONFIDENCE_CONTRACT_VERSION = "governed-confidence-evidence-v1"
CONFIDENCE_POLICY_VERSION = "contractual-control-min-v1"
FX_USE_POLICY_VERSION = "fx-exact-direct-no-fill-v1"
SUFFICIENCY_POLICY_VERSION = "qv-metric-sufficiency-v1"
READINESS_POLICY_VERSION = "phase7d-readiness-v1"
ADMISSION_CONTRACT_VERSION = "qvm-real-data-admission-v3"


class Phase7DContractError(ValueError):
    """Raised when a Phase 7D proof cannot be verified without an assumption."""


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(ContractModel):
    source: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    evidence_type: Literal[
        "RAW_VERIFIED", "EXACT_MAPPING", "PIT_VALIDATED", "CALCULATION_REPLAY"
    ]
    evidence_reference_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale_code: str = Field(min_length=1)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"evidence_hash"})

    @model_validator(mode="after")
    def verify_hash(self) -> Evidence:
        if typed_hash(self.payload()) != self.evidence_hash:
            raise ValueError("confidence evidence hash mismatch")
        return self


def seal_evidence(**values: object) -> Evidence:
    payload = {**values}
    return Evidence(**payload, evidence_hash=typed_hash(payload))


class ConfidenceComponent(ContractModel):
    name: Literal[
        "data_confidence",
        "mapping_confidence",
        "calculation_confidence",
        "economic_confidence",
    ]
    score: float | None
    semantics: Literal["DETERMINISTIC_CONTRACT_CONTROL", "EMPIRICAL_PREDICTIVE"]
    evidence: tuple[Evidence, ...] = ()
    rationale_code: str = Field(min_length=1)

    @field_validator("score", mode="before")
    @classmethod
    def strict_probability(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("confidence score must be a numeric probability or None")
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("confidence score must be finite and within [0,1]")
        return value

    @model_validator(mode="after")
    def evidence_required(self) -> ConfidenceComponent:
        if self.score is not None and not self.evidence:
            raise ValueError("a confidence score requires verifiable evidence")
        if self.score is None and self.evidence:
            raise ValueError("UNKNOWN confidence cannot carry score evidence")
        return self


class GovernedConfidenceProof(ContractModel):
    contract_version: Literal["governed-confidence-evidence-v1"] = CONFIDENCE_CONTRACT_VERSION
    policy_version: Literal["contractual-control-min-v1"] = CONFIDENCE_POLICY_VERSION
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime.datetime
    components: tuple[ConfidenceComponent, ...]
    governed_score: float | None
    state: Literal["CONTRACTUAL_CONTROL_PASS", "UNKNOWN", "BELOW_THRESHOLD"]
    threshold: float = Field(default=0.80, ge=0, le=1, allow_inf_nan=False)
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"proof_hash"})

    @model_validator(mode="after")
    def verify(self) -> GovernedConfidenceProof:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("confidence as_of must be timezone-aware")
        names = [item.name for item in self.components]
        required = {"data_confidence", "mapping_confidence", "calculation_confidence"}
        if len(names) != len(set(names)) or not required <= set(names):
            raise ValueError("confidence components must be unique and include all required controls")
        required_items = [item for item in self.components if item.name in required]
        if any(item.semantics != "DETERMINISTIC_CONTRACT_CONTROL" for item in required_items):
            raise ValueError("Phase 7D required confidence is contractual, not predictive")
        expected = None if any(item.score is None for item in required_items) else min(
            item.score for item in required_items if item.score is not None
        )
        if self.governed_score != expected:
            raise ValueError("governed confidence must be the minimum required component")
        expected_state = (
            "UNKNOWN" if expected is None else
            "CONTRACTUAL_CONTROL_PASS" if expected >= self.threshold else "BELOW_THRESHOLD"
        )
        if self.state != expected_state:
            raise ValueError("confidence state is inconsistent with evidence and threshold")
        if typed_hash(self.payload()) != self.proof_hash:
            raise ValueError("confidence proof hash mismatch")
        return self


def seal_confidence(
    accounting: AccountingDataset,
    *,
    as_of: datetime.datetime,
    components: tuple[ConfidenceComponent, ...],
    threshold: float = 0.80,
) -> GovernedConfidenceProof:
    # Revalidate the physical Accounting content at this trust boundary.
    AccountingDataset(frame=accounting.frame.copy(deep=True), metadata=accounting.metadata)
    required = {"data_confidence", "mapping_confidence", "calculation_confidence"}
    controlled = [item for item in components if item.name in required]
    score = None if len(controlled) != 3 or any(x.score is None for x in controlled) else min(
        x.score for x in controlled if x.score is not None
    )
    state = "UNKNOWN" if score is None else (
        "CONTRACTUAL_CONTROL_PASS" if score >= threshold else "BELOW_THRESHOLD"
    )
    values = {
        "accounting_canonical_id": accounting.metadata.canonical_id,
        "accounting_checksum": accounting.metadata.checksum,
        "as_of": as_of,
        "components": components,
        "governed_score": score,
        "state": state,
        "threshold": threshold,
    }
    payload = {
        "contract_version": CONFIDENCE_CONTRACT_VERSION,
        "policy_version": CONFIDENCE_POLICY_VERSION,
        **values,
    }
    # Hash the exact JSON representation the receiving model will verify.
    payload["as_of"] = as_of.isoformat().replace("+00:00", "Z")
    payload["components"] = [item.model_dump(mode="json") for item in components]
    return GovernedConfidenceProof(**values, proof_hash=typed_hash(payload))


class SufficiencyClass(StrEnum):
    REQUIRED_PRIMARY = "REQUIRED_PRIMARY"
    OPTIONAL_DIAGNOSTIC = "OPTIONAL_DIAGNOSTIC"
    DEFERRED_UNMAPPED = "DEFERRED_UNMAPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MetricRequirement(ContractModel):
    factor: Literal["Quality", "Value"]
    output_metric: str
    classification: SufficiencyClass
    required_inputs: tuple[str, ...]
    forbidden_proxies: tuple[str, ...] = ()
    rationale: str


class MetricSufficiencyMatrix(ContractModel):
    version: Literal["qv-metric-sufficiency-v1"] = SUFFICIENCY_POLICY_VERSION
    requirements: tuple[MetricRequirement, ...]
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify(self) -> MetricSufficiencyMatrix:
        keys = [(x.factor, x.output_metric) for x in self.requirements]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("metric sufficiency matrix must be unique and canonical")
        if typed_hash({"version": self.version, "requirements": self.requirements}) != self.matrix_hash:
            raise ValueError("metric sufficiency matrix hash mismatch")
        return self


def build_sufficiency_matrix() -> MetricSufficiencyMatrix:
    rows = tuple(sorted((
        MetricRequirement(factor="Quality", output_metric="cfo_conversion", classification="REQUIRED_PRIMARY", required_inputs=("cash_from_operations", "net_income"), rationale="exact reported inputs available"),
        MetricRequirement(factor="Quality", output_metric="fcf_margin", classification="REQUIRED_PRIMARY", required_inputs=("cash_from_operations", "capital_expenditures", "revenue"), rationale="FCF is CFO minus capex; no proxy"),
        MetricRequirement(factor="Quality", output_metric="raw_accrual_ratio", classification="OPTIONAL_DIAGNOSTIC", required_inputs=("net_income", "cash_from_operations", "total_assets"), rationale="exact diagnostic inputs available"),
        MetricRequirement(factor="Quality", output_metric="roic", classification="DEFERRED_UNMAPPED", required_inputs=("ebit", "tax_rate", "total_debt", "total_equity", "cash"), forbidden_proxies=("operating_income->ebit",), rationale="debt, tax and governed EBIT semantics remain absent"),
        MetricRequirement(factor="Quality", output_metric="net_debt_to_ebitda", classification="DEFERRED_UNMAPPED", required_inputs=("total_debt", "cash", "ebitda"), forbidden_proxies=("operating_income->ebitda",), rationale="debt and EBITDA remain absent"),
        MetricRequirement(factor="Quality", output_metric="share_count_change", classification="DEFERRED_UNMAPPED", required_inputs=("shares_history",), rationale="shares PIT remains OPEN-EXTERNAL"),
        MetricRequirement(factor="Value", output_metric="earnings_yield", classification="REQUIRED_PRIMARY", required_inputs=("net_income", "market_cap"), rationale="market cap requires governed market data and currency"),
        MetricRequirement(factor="Value", output_metric="fcf_yield", classification="REQUIRED_PRIMARY", required_inputs=("cash_from_operations", "capital_expenditures", "market_cap"), rationale="market cap and comparable currency required"),
        MetricRequirement(factor="Value", output_metric="ebit_yield", classification="DEFERRED_UNMAPPED", required_inputs=("ebit", "enterprise_value"), forbidden_proxies=("operating_income->ebit",), rationale="EBIT and EV remain absent"),
        MetricRequirement(factor="Value", output_metric="ev_to_ebitda", classification="OPTIONAL_DIAGNOSTIC", required_inputs=("enterprise_value", "ebitda"), forbidden_proxies=("operating_income->ebitda",), rationale="EV and EBITDA remain absent"),
    ), key=lambda x: (x.factor, x.output_metric)))
    return MetricSufficiencyMatrix(requirements=rows, matrix_hash=typed_hash(
        {"version": SUFFICIENCY_POLICY_VERSION, "requirements": rows}
    ))


DEFAULT_SUFFICIENCY_MATRIX = build_sufficiency_matrix()


class FactorInputState(ContractModel):
    factor: Literal["Quality", "Value"]
    metric: str
    state: Literal["PASS", "MISSING_REQUIRED", "DEFERRED_UNMAPPED", "NOT_APPLICABLE"]
    observed_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]


class AccountingFactorAdapterProof(ContractModel):
    adapter_version: Literal["accounting-qv-adapter-v1"] = "accounting-qv-adapter-v1"
    accounting_canonical_id: str
    accounting_checksum: str
    confidence_proof_hash: str
    sufficiency_matrix_hash: str
    as_of: datetime.datetime
    states: tuple[FactorInputState, ...]
    proof_hash: str

    @model_validator(mode="after")
    def verify(self) -> AccountingFactorAdapterProof:
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("Accounting factor adapter proof hash mismatch")
        return self


def adapt_accounting_factor_inputs(
    accounting: AccountingDataset,
    *,
    confidence: GovernedConfidenceProof,
    sufficiency: MetricSufficiencyMatrix = DEFAULT_SUFFICIENCY_MATRIX,
    as_of: datetime.datetime,
) -> AccountingFactorAdapterProof:
    if type(accounting) is not AccountingDataset:
        raise TypeError("Accounting adapters accept only exact AccountingDataset contracts")
    AccountingDataset(frame=accounting.frame.copy(deep=True), metadata=accounting.metadata)
    confidence = GovernedConfidenceProof.model_validate(confidence.model_dump(mode="python"))
    if (confidence.accounting_canonical_id, confidence.accounting_checksum) != (
        accounting.metadata.canonical_id, accounting.metadata.checksum
    ):
        raise Phase7DContractError("confidence proof does not bind the AccountingDataset")
    snapshot = accounting.snapshot(cutoff=as_of)
    observed = set(snapshot["metric"].astype(str))
    states = []
    for requirement in sufficiency.requirements:
        found = tuple(sorted(observed & set(requirement.required_inputs)))
        missing = tuple(sorted(set(requirement.required_inputs) - observed))
        if requirement.classification == SufficiencyClass.NOT_APPLICABLE:
            state = "NOT_APPLICABLE"
        elif requirement.classification == SufficiencyClass.DEFERRED_UNMAPPED:
            state = "DEFERRED_UNMAPPED"
        else:
            state = "PASS" if not missing and confidence.state == "CONTRACTUAL_CONTROL_PASS" else "MISSING_REQUIRED"
        states.append(FactorInputState(factor=requirement.factor, metric=requirement.output_metric,
            state=state, observed_inputs=found, missing_inputs=missing))
    values = {"adapter_version": "accounting-qv-adapter-v1",
        "accounting_canonical_id": accounting.metadata.canonical_id,
        "accounting_checksum": accounting.metadata.checksum,
        "confidence_proof_hash": confidence.proof_hash,
        "sufficiency_matrix_hash": sufficiency.matrix_hash, "as_of": as_of,
        "states": tuple(states)}
    hash_values = {**values, "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "states": [item.model_dump(mode="json") for item in states]}
    return AccountingFactorAdapterProof(**values, proof_hash=typed_hash(hash_values))


class PipelineState(StrEnum):
    RAW_INGESTED = "RAW_INGESTED"
    CANONICAL_MAPPED = "CANONICAL_MAPPED"
    ACCOUNTING_BOUND = "ACCOUNTING_BOUND"
    CONFIDENCE_BOUND = "CONFIDENCE_BOUND"
    FX_BOUND = "FX_BOUND"
    FACTOR_INPUTS_PARTIAL = "FACTOR_INPUTS_PARTIAL"
    QVM_NOT_READY = "QVM_NOT_READY"
    QVM_ADMISSIBLE = "QVM_ADMISSIBLE"


class ReadinessStateProof(ContractModel):
    policy_version: Literal["phase7d-readiness-v1"] = READINESS_POLICY_VERSION
    state: PipelineState
    prerequisite_proof_hashes: tuple[str, ...] = Field(min_length=1)
    proof_hash: str

    @model_validator(mode="after")
    def verify(self) -> ReadinessStateProof:
        if self.prerequisite_proof_hashes != tuple(sorted(set(self.prerequisite_proof_hashes))):
            raise ValueError("readiness proofs must be unique and canonical")
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("readiness proof hash mismatch")
        return self


class FXUseProof(ContractModel):
    policy_version: Literal["fx-exact-direct-no-fill-v1"] = FX_USE_POLICY_VERSION
    accounting_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_canonical_id: str | None
    fx_checksum: str | None
    conversions: tuple[dict[str, object], ...]
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify(self) -> FXUseProof:
        if typed_hash(self.model_dump(mode="json", exclude={"proof_hash"})) != self.proof_hash:
            raise ValueError("FX use proof hash mismatch")
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
) -> tuple[FXConversion, FXUseProof]:
    if source_currency.strip().upper() == target_currency.strip().upper():
        if fx is None:
            conversion = FXConversion(amount=float(amount), source_currency=source_currency.upper(),
                target_currency=target_currency.upper(), converted_amount=float(amount), rate=1.0,
                conversion_method="identity", rate_market_timestamp=None, rate_available_at=None,
                fx_canonical_id=None, fx_checksum=None, fx_source=None, fx_dataset_version=None)
        else:
            conversion = fx.convert(amount, source_currency=source_currency,
                target_currency=target_currency, market_at=market_at, cutoff=cutoff)
    else:
        if fx is None:
            raise Phase7DContractError("cross-currency Value requires governed FX")
        conversion = fx.convert(amount, source_currency=source_currency,
            target_currency=target_currency, market_at=market_at, cutoff=cutoff)
        if conversion.conversion_method != "direct":
            raise FXGovernanceError("Phase 7D forbids implicit inverse FX; an exact direct pair is required")
    row = {
        "source_currency": conversion.source_currency, "target_currency": conversion.target_currency,
        "amount": conversion.amount, "converted_amount": conversion.converted_amount,
        "rate": conversion.rate, "method": conversion.conversion_method,
        "market_timestamp": conversion.rate_market_timestamp,
        "available_at": conversion.rate_available_at,
    }
    values = {"policy_version": FX_USE_POLICY_VERSION,
        "accounting_checksum": accounting.metadata.checksum,
        "fx_canonical_id": conversion.fx_canonical_id, "fx_checksum": conversion.fx_checksum,
        "conversions": (row,)}
    hash_values = {**values, "conversions": ({
        **row,
        "market_timestamp": None if conversion.rate_market_timestamp is None else conversion.rate_market_timestamp.isoformat().replace("+00:00", "Z"),
        "available_at": None if conversion.rate_available_at is None else conversion.rate_available_at.isoformat().replace("+00:00", "Z"),
    },)}
    return conversion, FXUseProof(**values, proof_hash=typed_hash(hash_values))


class QVMAdmissionV3(ContractModel):
    contract_version: Literal["qvm-real-data-admission-v3"] = ADMISSION_CONTRACT_VERSION
    state: Literal["QVM_ADMISSIBLE", "QVM_NOT_READY"]
    reasons: tuple[str, ...]
    confidence_proof_hash: str | None
    fx_proof_hash: str | None
    sufficiency_matrix_hash: str
    phase6_admission: PrePhase6Admission | None
    runtime_fingerprint: str
    admission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    global_readiness: Literal["INSUFFICIENT_REAL_DATA"] = "INSUFFICIENT_REAL_DATA"
    research_only: Literal[True] = True
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    signals_generated: Literal[False] = False

    @model_validator(mode="after")
    def verify(self) -> QVMAdmissionV3:
        expected = typed_hash(self.model_dump(mode="json", exclude={"admission_hash"}))
        if expected != self.admission_hash:
            raise ValueError("Phase 7D admission hash mismatch")
        if self.state == "QVM_ADMISSIBLE" and (self.reasons or self.phase6_admission is None):
            raise ValueError("admissible state requires Phase 6 proof and no unresolved reasons")
        return self


def admit_qvm_v3(
    *,
    accounting: AccountingDataset,
    confidence: GovernedConfidenceProof | None,
    fx_proof: FXUseProof | None,
    sufficiency: MetricSufficiencyMatrix,
    batches: tuple[GovernedFactorBatch, ...],
    required_metric_states: dict[str, str],
    cross_currency_value: bool,
    providers_real_data_ready: bool = False,
) -> QVMAdmissionV3:
    """Fail-closed real-data wrapper; Phase 6 remains the sole scoring admission implementation."""
    AccountingDataset(frame=accounting.frame.copy(deep=True), metadata=accounting.metadata)
    confidence = None if confidence is None else GovernedConfidenceProof.model_validate(
        confidence.model_dump(mode="python"))
    sufficiency = MetricSufficiencyMatrix.model_validate(sufficiency.model_dump(mode="python"))
    fx_proof = None if fx_proof is None else FXUseProof.model_validate(fx_proof.model_dump(mode="python"))
    reasons: list[str] = []
    if confidence is None:
        reasons.append("CONFIDENCE_PROOF_MISSING")
    else:
        if confidence.accounting_checksum != accounting.metadata.checksum or confidence.accounting_canonical_id != accounting.metadata.canonical_id:
            reasons.append("CONFIDENCE_ACCOUNTING_IDENTITY_MISMATCH")
        if confidence.state != "CONTRACTUAL_CONTROL_PASS":
            reasons.append(f"CONFIDENCE_{confidence.state}")
    if cross_currency_value and fx_proof is None:
        reasons.append("FX_PROOF_REQUIRED")
    if fx_proof is not None and fx_proof.accounting_checksum != accounting.metadata.checksum:
        reasons.append("FX_ACCOUNTING_IDENTITY_MISMATCH")
    unresolved = sorted(k for k, v in required_metric_states.items() if v != "PASS")
    reasons.extend(f"REQUIRED_METRIC_NOT_PASS:{item}" for item in unresolved)
    if not providers_real_data_ready:
        reasons.append("PROVIDER_REAL_DATA_OPEN")
    phase6 = None
    if not reasons:
        try:
            phase6 = admit_sealed_for_phase6(batches=batches)
        except (TypeError, ValueError) as error:
            reasons.append(f"PHASE6_ADMISSION_REJECTED:{error}")
    values = {
        "state": "QVM_ADMISSIBLE" if not reasons else "QVM_NOT_READY",
        "reasons": tuple(reasons),
        "confidence_proof_hash": None if confidence is None else confidence.proof_hash,
        "fx_proof_hash": None if fx_proof is None else fx_proof.proof_hash,
        "sufficiency_matrix_hash": sufficiency.matrix_hash,
        "phase6_admission": phase6,
        "runtime_fingerprint": runtime_fingerprint().fingerprint,
        "global_readiness": "INSUFFICIENT_REAL_DATA",
        "research_only": True, "trade_decision": "NO_TRADE",
        "live_execution_enabled": False, "signals_generated": False,
    }
    return QVMAdmissionV3(**values, admission_hash=typed_hash(
        {"contract_version": ADMISSION_CONTRACT_VERSION, **values}
    ))
