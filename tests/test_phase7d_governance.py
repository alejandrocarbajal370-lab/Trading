from __future__ import annotations

import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from data.fx import FXLineageEntry, FXStalenessPolicy, govern_fx
from fundamentals.governance import AccountingLineageEntry, govern_accounting
from governance.phase7d import (
    DEFAULT_SUFFICIENCY_MATRIX,
    ConfidenceComponent,
    Evidence,
    GovernedConfidenceProof,
    Phase7DContractError,
    adapt_accounting_factor_inputs,
    admit_qvm_v3,
    governed_fx_conversion,
    seal_confidence,
    seal_evidence,
)

AS_OF = datetime.datetime(2025, 4, 1, 20, tzinfo=datetime.UTC)


def _accounting():
    frame = pd.DataFrame([{
        "fact_id": "f1", "entity": "PERM-1", "metric": "net_income",
        "fiscal_period": "FY-2024", "period_end": "2024-12-31",
        "filing_date": "2025-02-01T12:00:00Z", "available_at": "2025-02-01T12:00:00Z",
        "value": 100.0, "unit": "USD", "source": "sec_edgar", "dataset_version": "v1",
        "revision": 0, "revision_type": "ORIGINAL", "supersedes_revision": None,
    }])
    return govern_accounting(frame, source="sec_edgar", dataset_version="v1", as_of=AS_OF,
        available_at=AS_OF, lineage=(AccountingLineageEntry(source="sec_edgar",
        dataset="companyfacts", dataset_version="v1"),))


def _evidence(kind: str, code: str):
    return seal_evidence(source="phase7c", source_record_id=code, version="v1",
        evidence_type=kind, evidence_reference_hash="a" * 64, rationale_code=code)


def _components(score: float | None = 1.0):
    specs = (("data_confidence", "RAW_VERIFIED"),
             ("mapping_confidence", "EXACT_MAPPING"),
             ("calculation_confidence", "CALCULATION_REPLAY"))
    return tuple(ConfidenceComponent(name=name, score=score,
        semantics="DETERMINISTIC_CONTRACT_CONTROL",
        evidence=() if score is None else (_evidence(kind, name),), rationale_code=name)
        for name, kind in specs)


@pytest.mark.parametrize("value", [True, "0.9", float("nan"), float("inf"), -0.1, 1.1])
def test_confidence_rejects_non_strict_invalid_values(value):
    with pytest.raises((ValidationError, TypeError)):
        ConfidenceComponent(name="data_confidence", score=value,
            semantics="DETERMINISTIC_CONTRACT_CONTROL", evidence=(_evidence("RAW_VERIFIED", "x"),),
            rationale_code="x")


def test_confidence_requires_evidence_and_unknown_never_becomes_one():
    with pytest.raises(ValidationError, match="requires verifiable evidence"):
        ConfidenceComponent(name="data_confidence", score=1.0,
            semantics="DETERMINISTIC_CONTRACT_CONTROL", rationale_code="declarative")
    proof = seal_confidence(_accounting(), as_of=AS_OF, components=_components(None))
    assert proof.governed_score is None and proof.state == "UNKNOWN"


def test_confidence_min_policy_threshold_and_low_blocking():
    parts = list(_components())
    parts[1] = ConfidenceComponent(name="mapping_confidence", score=0.80,
        semantics="DETERMINISTIC_CONTRACT_CONTROL", evidence=(_evidence("EXACT_MAPPING", "m"),),
        rationale_code="m")
    proof = seal_confidence(_accounting(), as_of=AS_OF, components=tuple(parts))
    assert proof.governed_score == 0.80 and proof.state == "CONTRACTUAL_CONTROL_PASS"
    low = parts.copy()
    low[1] = low[1].model_copy(update={"score": 0.79})
    assert seal_confidence(_accounting(), as_of=AS_OF, components=tuple(low)).state == "BELOW_THRESHOLD"


def test_confidence_evidence_and_outer_mutations_are_rejected():
    evidence = _evidence("RAW_VERIFIED", "raw")
    with pytest.raises(ValidationError, match="evidence hash mismatch"):
        Evidence.model_validate({**evidence.model_dump(), "source_record_id": "forged"})
    proof = seal_confidence(_accounting(), as_of=AS_OF, components=_components())
    with pytest.raises(ValidationError, match="proof hash mismatch"):
        GovernedConfidenceProof.model_validate({**proof.model_dump(), "threshold": 0.81})


def _fx(pair="EUR/USD", base="EUR", quote="USD", rate=1.1, market="2025-03-31T16:00:00Z"):
    frame = pd.DataFrame([{"currency_pair": pair, "base_currency": base,
        "quote_currency": quote, "market_timestamp": market,
        "available_at": "2025-03-31T17:00:00Z", "rate": rate,
        "source_record_id": "fix-1", "raw_evidence_hash": "b" * 64}])
    return govern_fx(frame, source="fixture-contract-only", dataset_version="v1", as_of=AS_OF,
        available_at=AS_OF, lineage=(FXLineageEntry(source="fixture-contract-only", dataset="fx",
        dataset_version="v1"),), staleness_policy=FXStalenessPolicy(maximum_sessions=1))


def test_same_currency_is_explicit_identity_without_provider():
    conversion, proof = governed_fx_conversion(None, accounting=_accounting(), amount=10,
        source_currency="USD", target_currency="USD", market_at=AS_OF, cutoff=AS_OF)
    assert conversion.conversion_method == "identity" and conversion.rate == 1.0
    assert proof.fx_canonical_id is None


def test_cross_currency_requires_exact_direct_governed_observation():
    with pytest.raises(Phase7DContractError, match="requires governed FX"):
        governed_fx_conversion(None, accounting=_accounting(), amount=10,
            source_currency="EUR", target_currency="USD", market_at=AS_OF, cutoff=AS_OF)
    conversion, proof = governed_fx_conversion(_fx(), accounting=_accounting(), amount=10,
        source_currency="EUR", target_currency="USD", market_at=AS_OF, cutoff=AS_OF)
    assert conversion.converted_amount == pytest.approx(11) and proof.fx_checksum
    with pytest.raises(ValueError, match="forbids implicit inverse"):
        governed_fx_conversion(_fx(), accounting=_accounting(), amount=10,
            source_currency="USD", target_currency="EUR", market_at=AS_OF, cutoff=AS_OF)


@pytest.mark.parametrize("rate", [0, -1, float("nan"), float("inf"), True, "1.1"])
def test_fx_invalid_rate_is_rejected(rate):
    with pytest.raises((ValueError, TypeError)):
        _fx(rate=rate)


def test_fx_future_and_stale_are_rejected():
    with pytest.raises(ValueError, match="PIT violation"):
        _fx(market="2025-04-02T16:00:00Z")
    with pytest.raises(ValueError, match="stale FX"):
        governed_fx_conversion(_fx(market="2025-03-20T16:00:00Z"), accounting=_accounting(),
            amount=1, source_currency="EUR", target_currency="USD", market_at=AS_OF, cutoff=AS_OF)


def test_sufficiency_forbids_economic_proxies_and_is_sealed():
    by_name = {row.output_metric: row for row in DEFAULT_SUFFICIENCY_MATRIX.requirements}
    assert by_name["roic"].classification == "DEFERRED_UNMAPPED"
    assert "operating_income->ebit" in by_name["roic"].forbidden_proxies
    assert by_name["ev_to_ebitda"].required_inputs == ("enterprise_value", "ebitda")
    with pytest.raises(ValidationError, match="matrix hash mismatch"):
        DEFAULT_SUFFICIENCY_MATRIX.__class__.model_validate({
            **DEFAULT_SUFFICIENCY_MATRIX.model_dump(), "matrix_hash": "0" * 64})


def test_accounting_adapter_revalidates_proofs_and_exposes_partial_states():
    accounting = _accounting()
    confidence = seal_confidence(accounting, as_of=AS_OF, components=_components())
    adapter = adapt_accounting_factor_inputs(accounting, confidence=confidence, as_of=AS_OF)
    states = {item.metric: item.state for item in adapter.states}
    assert states["cfo_conversion"] == "MISSING_REQUIRED"
    assert states["roic"] == "DEFERRED_UNMAPPED"
    with pytest.raises(TypeError, match="exact AccountingDataset"):
        adapt_accounting_factor_inputs(pd.DataFrame(), confidence=confidence, as_of=AS_OF)  # type: ignore[arg-type]


def test_v3_returns_not_ready_without_scoring_or_synthetic_promotion():
    accounting = _accounting()
    result = admit_qvm_v3(accounting=accounting, confidence=None, fx_proof=None,
        sufficiency=DEFAULT_SUFFICIENCY_MATRIX, batches=(),
        required_metric_states={"Quality.roic": "DEFERRED_UNMAPPED", "Value.fcf_yield": "MISSING"},
        cross_currency_value=True)
    assert result.state == "QVM_NOT_READY"
    assert result.phase6_admission is None
    assert result.trade_decision == "NO_TRADE" and result.live_execution_enabled is False
    assert result.signals_generated is False and result.global_readiness == "INSUFFICIENT_REAL_DATA"
    assert "CONFIDENCE_PROOF_MISSING" in result.reasons and "FX_PROOF_REQUIRED" in result.reasons


def test_v3_rejects_legacy_batch_bypass_if_other_gates_close():
    accounting = _accounting()
    confidence = seal_confidence(accounting, as_of=AS_OF, components=_components())
    result = admit_qvm_v3(accounting=accounting, confidence=confidence, fx_proof=None,
        sufficiency=DEFAULT_SUFFICIENCY_MATRIX, batches=(pd.DataFrame(),),  # type: ignore[arg-type]
        required_metric_states={"Quality.cfo_conversion": "PASS"}, cross_currency_value=False,
        providers_real_data_ready=True)
    assert result.state == "QVM_NOT_READY"
    assert any("exact GovernedFactorBatch" in reason for reason in result.reasons)
