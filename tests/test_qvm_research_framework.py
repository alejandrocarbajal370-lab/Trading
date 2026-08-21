import datetime
import json

import pandas as pd
import pytest

from factors.qvm import FactorBatch, FactorObservation, evaluate_qvm_research, observation_from_row
from research.qvm_runner import run_qvm_research

AS_OF = datetime.date(2025, 3, 15)
AVAILABLE = datetime.datetime(2025, 3, 14, 22, tzinfo=datetime.UTC)


def _observation(factor: str, symbol: str, value: float, *, metric: str | None = None) -> FactorObservation:
    return FactorObservation(
        symbol=symbol, factor=factor, metric=metric or f"{factor.lower()}_metric", value=value,
        unit="ratio", as_of=AS_OF, available_at=AVAILABLE, confidence=0.95,
        lineage={"source": f"{factor.lower()}_fixture"},
        universe_snapshot_id="universe-2025-03-15", status="PASS", sector="Industrials",
    )


def _batches() -> tuple[FactorBatch, ...]:
    return tuple(
        FactorBatch(
            factor=factor, universe_snapshot_id="universe-2025-03-15", as_of=AS_OF,
            availability_policy="KNOWN_BY_AS_OF", entity_policy="symbol",
            lineage_id="integrated-snapshot-001",
            observations=tuple(_observation(factor, symbol, value) for symbol, value in (("AAA", 1.0), ("BBB", -1.0))),
        )
        for factor in ("Quality", "Value", "Momentum")
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("as_of", datetime.date(2025, 3, 14), "PIT"),
        ("universe_snapshot_id", "universe-other", "universe"),
        ("lineage_id", "other-lineage", "lineage"),
        ("availability_policy", "NEXT_OPEN", "availability"),
    ],
)
def test_alignment_mismatch_fails_closed(field: str, value: object, reason: str) -> None:
    batches = list(_batches())
    batches[2] = batches[2].model_copy(update={field: value})
    with pytest.raises(ValueError, match=reason):
        evaluate_qvm_research(tuple(batches))


def test_factor_missing_fails_closed() -> None:
    with pytest.raises(ValueError, match="factor missing: Momentum"):
        evaluate_qvm_research(_batches()[:2])


def test_universe_membership_mismatch_fails_closed() -> None:
    batches = list(_batches())
    batches[2] = batches[2].model_copy(update={"observations": batches[2].observations[:1]})
    with pytest.raises(ValueError, match="governed universe membership"):
        evaluate_qvm_research(tuple(batches))


def test_common_contract_rejects_future_availability() -> None:
    with pytest.raises(ValueError, match="available_at exceeds"):
        FactorObservation.model_validate(
            _observation("Quality", "AAA", 1.0).model_dump()
            | {"available_at": datetime.datetime(2025, 3, 16, tzinfo=datetime.UTC)}
        )


def test_matrix_preserves_individual_metrics_without_score_or_ranking() -> None:
    result = evaluate_qvm_research(_batches())
    assert set(result.matrix["symbol"]) == {"AAA", "BBB"}
    assert "quality__quality_metric" in result.matrix
    assert "value__value_metric" in result.matrix
    assert "momentum__momentum_metric" in result.matrix
    assert not any("score" in column or "rank" in column for column in result.matrix.columns)
    assert result.health["composite_score_calculated"] is False
    assert result.health["ranking_calculated"] is False
    assert result.health["trade_decision"] == "NO_TRADE"
    assert result.health["live_execution_enabled"] is False


def test_correlation_diagnostics_are_descriptive() -> None:
    result = evaluate_qvm_research(_batches())
    correlations = result.health["diagnostics"]["factor_correlations"]
    assert correlations["Quality"]["Value"] == pytest.approx(1.0)
    assert result.health["diagnostics"]["coverage_by_factor"] == {
        "Quality": 1.0, "Value": 1.0, "Momentum": 1.0
    }
    assert result.health["diagnostics"]["sector_concentration"] == {"Industrials": 2}


def test_outputs_are_reproducible_and_complete(tmp_path) -> None:
    first = run_qvm_research(batches=_batches(), output_root=tmp_path)
    second = run_qvm_research(batches=_batches(), output_root=tmp_path)
    assert first.output_dir == second.output_dir
    assert first.research_run == second.research_run
    assert {path.name for path in first.output_dir.iterdir()} == {
        "qvm_factor_matrix.csv", "qvm_health.json", "qvm_lineage.json",
        "qvm_validation_report.json", "qvm_research_run.json",
    }
    report = json.loads((first.output_dir / "qvm_validation_report.json").read_text())
    assert not any(report["prohibited_outputs"].values())


@pytest.mark.parametrize(
    ("factor", "available_column"),
    [("Quality", "source_available_at"), ("Value", "source_available_at"), ("Momentum", "available_at")],
)
def test_existing_factor_rows_adapt_without_recalculating(factor: str, available_column: str) -> None:
    row = pd.Series({
        "symbol": "AAA", "metric": "existing_metric", "value": 0.5,
        "confidence": 0.9, "status": "PASS", "reason": None,
        available_column: "2025-03-14T22:00:00+00:00",
        "lineage": json.dumps({"dataset": {"snapshot_id": "fixture"}}),
        "unit": "ratio", "sector": "Industrials",
    })
    adapted = observation_from_row(
        row, factor=factor, universe_snapshot_id="universe-2025-03-15", as_of=AS_OF
    )
    assert adapted.value == 0.5
    assert adapted.metric == "existing_metric"
    assert adapted.normalized_value is None
    assert adapted.normalization.applied is False
