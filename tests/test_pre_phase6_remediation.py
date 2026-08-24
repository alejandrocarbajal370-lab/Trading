from __future__ import annotations

import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from data.provider_contracts import ProviderKind, ProviderSnapshot, require_real_provider
from factors.qvm import METRIC_SEMANTICS_REGISTRY
from fundamentals.financial_engine import calculate_financial_metrics
from governance.canonical import runtime_fingerprint, typed_frame_hash, typed_hash
from governance.pre_phase6 import (
    ClassificationRecord,
    ConfidenceVector,
    conservative_confidence,
    governed_status,
    metric_applicability,
    peer_assignment_hash,
)
from research.pre_phase6_readiness import (
    ReadinessState,
    admit_sealed_for_phase6,
    run_blind_coverage,
)
from research.pre_phase6_scale_smoke import run_synthetic_scale_smoke

AS_OF = datetime.datetime(2025, 1, 31, 23, 59, tzinfo=datetime.UTC)


def _classification(symbol: str, industry: str = "Machinery") -> ClassificationRecord:
    return ClassificationRecord(
        symbol=symbol, sector="Industrials", industry=industry, source="synthetic-contract-fixture",
        taxonomy="TEST-TAXONOMY", taxonomy_version="v1",
        available_at=datetime.datetime(2025, 1, 30, tzinfo=datetime.UTC),
    )


def test_confidence_policy_is_conservative_and_has_no_synthetic_default() -> None:
    result = conservative_confidence([
        ConfidenceVector(data_confidence=0.9, calculation_confidence=0.8, economic_confidence=0.7),
        ConfidenceVector(data_confidence=0.6, calculation_confidence=0.95, economic_confidence=0.75),
    ])
    assert result.model_dump() == {
        "data_confidence": 0.6, "calculation_confidence": 0.8,
        "economic_confidence": 0.7, "policy_version": "conservative-input-min-v1",
    }
    assert result.governed_confidence == 0.6
    with pytest.raises(ValueError, match="required"):
        conservative_confidence([])
    with pytest.raises(ValidationError):
        ConfidenceVector(data_confidence=1.1, calculation_confidence=0.8, economic_confidence=0.8)


def test_peer_assignment_hash_is_order_independent_and_mutation_sensitive() -> None:
    records = [_classification("BBB"), _classification("AAA")]
    first = peer_assignment_hash(records, as_of=AS_OF, universe_snapshot_hash="a" * 64)
    assert first == peer_assignment_hash(list(reversed(records)), as_of=AS_OF,
                                         universe_snapshot_hash="a" * 64)
    changed = [_classification("BBB", "Aerospace"), _classification("AAA")]
    assert first != peer_assignment_hash(changed, as_of=AS_OF, universe_snapshot_hash="a" * 64)
    with pytest.raises(ValueError, match="taxonomy"):
        ClassificationRecord(symbol="CCC", sector="Industrials", industry="Machinery",
                             source="fixture", taxonomy="UNKNOWN", taxonomy_version="v1",
                             available_at=AS_OF)
    with pytest.raises(ValueError, match="future"):
        peer_assignment_hash([_classification("AAA").model_copy(
            update={"available_at": AS_OF + datetime.timedelta(seconds=1)})],
            as_of=AS_OF, universe_snapshot_hash="a" * 64)


def test_typed_canonicalization_preserves_types_and_order_independence() -> None:
    assert typed_hash(1) != typed_hash("1")
    first = pd.DataFrame([{"symbol": "B", "value": 2.0}, {"symbol": "A", "value": 1.0}])
    second = first.iloc[::-1].reset_index(drop=True)
    assert typed_frame_hash(first, ["symbol"]) == typed_frame_hash(second, ["symbol"])
    runtime = runtime_fingerprint()
    assert len(runtime.fingerprint) == 64
    assert len(runtime.requirements_lock_sha256) == 64
    assert typed_frame_hash(first, ["symbol"]) != typed_frame_hash(
        first.assign(value=first["value"].astype("int64")), ["symbol"]
    )
    assert typed_hash(datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)) == typed_hash(
        datetime.datetime(2024, 12, 31, 18, tzinfo=datetime.timezone(datetime.timedelta(hours=-6)))
    )


def test_status_taxonomy_and_sector_applicability_fail_closed() -> None:
    assert governed_status("PASS").value == "PASS"
    with pytest.raises(ValueError, match="unknown governed status"):
        governed_status("NEUTRAL")
    assert metric_applicability("net_debt_to_ebitda", "Financials", "Banks").state == "NOT_APPLICABLE"
    assert metric_applicability("cfo_conversion", "Financials", "Insurance").state == "NOT_APPLICABLE"
    assert metric_applicability("cfo_conversion", "Real Estate", "REITs").state == "REVIEW"
    assert metric_applicability("roic", "Industrials", "Machinery").state == "APPLICABLE"


def _accrual_metric(cfo: float) -> float:
    base = {"symbol": "AAA", "fiscal_period_start": datetime.date(2024, 1, 1),
            "fiscal_period_end": datetime.date(2024, 12, 31), "period_type": "duration",
            "available_at": AS_OF, "unit": "USD", "source": "synthetic-contract-fixture",
            "confidence": 0.9}
    rows = [{**base, "metric": "net_income", "value": 20.0},
            {**base, "metric": "cash_from_operations", "value": cfo},
            {**base, "metric": "total_assets", "value": 100.0,
             "fiscal_period_start": None, "period_type": "instant"}]
    result = calculate_financial_metrics(pd.DataFrame(rows))
    return float(result.query("metric == 'accrual_ratio'").iloc[0]["value"])


def test_raw_accrual_ratio_golden_sign_and_monotonicity() -> None:
    assert _accrual_metric(10.0) == pytest.approx(0.1)
    assert _accrual_metric(30.0) == pytest.approx(-0.1)
    semantics = METRIC_SEMANTICS_REGISTRY[("Quality", "raw_accrual_ratio")]
    assert semantics.direction == "lower_is_better"
    assert _accrual_metric(30.0) < _accrual_metric(10.0)


def test_provider_contract_and_blind_harness_are_honest_about_external_data() -> None:
    snapshot = ProviderSnapshot(
        kind=ProviderKind.FUNDAMENTALS_PIT, source="synthetic-contract-fixture",
        dataset_version="v1", canonical_id="fixture:fundamentals",
        checksum="a" * 64, available_at=AS_OF,
        pit_semantics="known-by available_at", raw_snapshot_reference="fixture://fundamentals",
        raw_snapshot_retention="test lifetime", lineage=("synthetic",),
        real_data=False, licensed_for_use=False,
    )
    with pytest.raises(ValueError, match="REAL-DATA-OPEN"):
        require_real_provider(snapshot, expected=ProviderKind.FUNDAMENTALS_PIT)
    report = run_blind_coverage(batches=(), providers=(snapshot,), as_of=AS_OF,
                                synthetic_contract_test=True)
    assert report.state == ReadinessState.INSUFFICIENT_REAL_DATA
    assert ProviderKind.FX.value in report.provider_gaps
    assert report.outcomes_or_returns_used is False
    assert report.scores_calculated is False


def test_pre_phase6_admission_rejects_legacy() -> None:
    with pytest.raises(TypeError, match="GovernedFactorBatch"):
        admit_sealed_for_phase6(batches=(object(),))  # type: ignore[arg-type]


def test_ci_safe_scale_smoke_runs_full_pipeline_and_is_reorder_deterministic(tmp_path) -> None:
    first = run_synthetic_scale_smoke(
        security_count=3, workdir=tmp_path / "ordered", reorder_inputs=False
    )
    second = run_synthetic_scale_smoke(
        security_count=3, workdir=tmp_path / "reordered", reorder_inputs=True
    )
    identity_fields = {
        "cross_layer_fingerprint",
        "factor_batch_hashes",
        "qvm_sealed_lineage_hash",
        "admission_artifact_hash",
    }
    assert {key: first[key] for key in identity_fields} == {
        key: second[key] for key in identity_fields
    }
    assert first["security_count"] == 3
    assert first["market_rows"] > first["security_count"]
    assert first["accounting_rows"] == 3 * 11
    assert first["qvm_governance_mode"] == "phase5.6_cross_layer_verified"
    assert first["scores_calculated"] is False
    assert first["signals_generated"] is False
    assert first["trade_decision"] == "NO_TRADE"
    assert first["live_execution_enabled"] is False
