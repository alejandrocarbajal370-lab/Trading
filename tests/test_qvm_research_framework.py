import datetime
import json

import pandas as pd
import pytest

from factors.qvm import (
    FactorBatch,
    FactorObservation,
    evaluate_qvm_research,
    factor_dataset_hash,
    observation_from_row,
    qvm_lineage_hash,
)
from research.qvm_runner import run_qvm_research

AS_OF = datetime.date(2025, 3, 15)
AVAILABLE = datetime.datetime(2025, 3, 14, 22, tzinfo=datetime.UTC)
UNIVERSE_HASH = "a" * 64


def _observation(
    factor: str, symbol: str, value: float, *, metric: str | None = None
) -> FactorObservation:
    return FactorObservation(
        symbol=symbol,
        factor=factor,
        metric=metric or f"{factor.lower()}_metric",
        value=value,
        unit="ratio",
        as_of=AS_OF,
        available_at=AVAILABLE,
        confidence=0.95,
        lineage={"source": f"{factor.lower()}_fixture"},
        universe_snapshot_id="universe-2025-03-15",
        status="PASS",
        sector="Industrials",
    )


def _batches() -> tuple[FactorBatch, ...]:
    observations = {
        factor: tuple(
            _observation(factor, symbol, value) for symbol, value in (("AAA", 1.0), ("BBB", -1.0))
        )
        for factor in ("Quality", "Value", "Momentum")
    }
    dataset_hashes = {factor: factor_dataset_hash(items) for factor, items in observations.items()}
    lineage_hash = qvm_lineage_hash(
        universe_snapshot_id="universe-2025-03-15",
        universe_snapshot_hash=UNIVERSE_HASH,
        factor_dataset_hashes=dataset_hashes,
        as_of=AS_OF,
        availability_policy="KNOWN_BY_AS_OF",
        entity_policy="symbol",
    )
    return tuple(
        FactorBatch(
            factor=factor,
            universe_snapshot_id="universe-2025-03-15",
            as_of=AS_OF,
            availability_policy="KNOWN_BY_AS_OF",
            entity_policy="symbol",
            universe_snapshot_hash=UNIVERSE_HASH,
            factor_dataset_hash=dataset_hashes[factor],
            lineage_hash=lineage_hash,
            observations=observations[factor],
        )
        for factor in ("Quality", "Value", "Momentum")
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("as_of", datetime.date(2025, 3, 14), "PIT"),
        ("universe_snapshot_id", "universe-other", "universe"),
        ("lineage_hash", "b" * 64, "lineage"),
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


def _custom_batches(metrics: dict[str, tuple[str, tuple[float, float]]]) -> tuple[FactorBatch, ...]:
    base = _batches()
    batches = []
    for batch in base:
        metric, values = metrics[batch.factor]
        observations = tuple(
            _observation(batch.factor, symbol, value, metric=metric)
            for symbol, value in zip(("AAA", "BBB"), values, strict=True)
        )
        batches.append(
            batch.model_copy(
                update={
                    "observations": observations,
                    "factor_dataset_hash": factor_dataset_hash(observations),
                }
            )
        )
    hashes = {batch.factor: batch.factor_dataset_hash for batch in batches}
    lineage_hash = qvm_lineage_hash(
        universe_snapshot_id="universe-2025-03-15",
        universe_snapshot_hash=UNIVERSE_HASH,
        factor_dataset_hashes=hashes,
        as_of=AS_OF,
        availability_policy="KNOWN_BY_AS_OF",
        entity_policy="symbol",
    )
    return tuple(batch.model_copy(update={"lineage_hash": lineage_hash}) for batch in batches)


def test_compatible_metric_correlation_calculates_result() -> None:
    result = evaluate_qvm_research(
        _custom_batches(
            {
                "Quality": ("roic", (0.20, 0.10)),
                "Value": ("fcf_yield", (0.05, 0.10)),
                "Momentum": ("momentum_12_1", (0.30, 0.10)),
            }
        )
    )
    diagnostics = result.health["diagnostics"]
    pairs = diagnostics["metric_correlations"]
    compatible = next(
        pair
        for pair in pairs
        if {pair["left_metric"], pair["right_metric"]} == {"roic", "fcf_yield"}
    )
    assert compatible["status"] == "NOT_AVAILABLE"
    assert compatible["reason"] == "metrics are not semantically comparable"

    comparable = _custom_batches(
        {
            "Quality": ("roic", (0.20, 0.10)),
            "Value": ("fcf_margin", (0.30, 0.15)),
            "Momentum": ("momentum_12_1", (0.30, 0.10)),
        }
    )
    pair = next(
        item
        for item in evaluate_qvm_research(comparable).health["diagnostics"]["metric_correlations"]
        if {item["left_metric"], item["right_metric"]} == {"roic", "fcf_margin"}
    )
    assert pair["status"] == "AVAILABLE"
    assert pair["correlation"] == pytest.approx(1.0)
    assert result.health["diagnostics"]["coverage_by_factor"] == {
        "Quality": 1.0,
        "Value": 1.0,
        "Momentum": 1.0,
    }
    assert result.health["diagnostics"]["sector_concentration"] == {"Industrials": 2}


def test_incompatible_metric_correlation_is_not_available_with_reason() -> None:
    result = evaluate_qvm_research(
        _custom_batches(
            {
                "Quality": ("roic", (0.20, 0.10)),
                "Value": ("ev_to_ebit", (30.0, 10.0)),
                "Momentum": ("momentum_12_1", (0.30, 0.10)),
            }
        )
    )
    pair = next(
        item
        for item in result.health["diagnostics"]["metric_correlations"]
        if {item["left_metric"], item["right_metric"]} == {"roic", "ev_to_ebit"}
    )
    assert pair == {
        "left_metric": "ev_to_ebit",
        "right_metric": "roic",
        "status": "NOT_AVAILABLE",
        "reason": "metrics are not semantically comparable",
        "correlation": None,
    }


def test_ev_to_ebit_uses_economic_direction_not_numeric_sign() -> None:
    result = evaluate_qvm_research(
        _custom_batches(
            {
                "Quality": ("roic", (0.20, 0.10)),
                "Value": ("ev_to_ebit", (30.0, 10.0)),
                "Momentum": ("momentum_12_1", (0.30, 0.10)),
            }
        )
    )
    conflict = result.health["diagnostics"]["factor_conflicts"]["conflicts"][0]
    ev_evidence = next(item for item in conflict["evidence"] if item["metric"] == "ev_to_ebit")
    assert ev_evidence["economic_signal"] == "negative"
    assert ev_evidence["meaning"] == "EV/EBIT valuation multiple"
    assert conflict["factor_signals"] == {
        "Momentum": "positive",
        "Quality": "positive",
        "Value": "negative",
    }


def test_lineage_hash_mismatch_fails_closed() -> None:
    batches = list(_batches())
    batches[0] = batches[0].model_copy(update={"factor_dataset_hash": "b" * 64})
    with pytest.raises(ValueError, match="factor dataset hash mismatch"):
        evaluate_qvm_research(tuple(batches))


def test_lineage_hash_is_reproducible() -> None:
    first = _batches()
    second = _batches()
    assert first[0].lineage_hash == second[0].lineage_hash
    assert evaluate_qvm_research(first).lineage["lineage_hash"] == first[0].lineage_hash


def test_outputs_are_reproducible_and_complete(tmp_path) -> None:
    first = run_qvm_research(batches=_batches(), output_root=tmp_path)
    second = run_qvm_research(batches=_batches(), output_root=tmp_path)
    assert first.output_dir == second.output_dir
    assert first.research_run == second.research_run
    assert {path.name for path in first.output_dir.iterdir()} == {
        "qvm_factor_matrix.csv",
        "qvm_health.json",
        "qvm_lineage.json",
        "qvm_validation_report.json",
        "qvm_research_run.json",
    }
    report = json.loads((first.output_dir / "qvm_validation_report.json").read_text())
    assert not any(report["prohibited_outputs"].values())


@pytest.mark.parametrize(
    ("factor", "available_column"),
    [
        ("Quality", "source_available_at"),
        ("Value", "source_available_at"),
        ("Momentum", "available_at"),
    ],
)
def test_existing_factor_rows_adapt_without_recalculating(
    factor: str, available_column: str
) -> None:
    row = pd.Series(
        {
            "symbol": "AAA",
            "metric": "existing_metric",
            "value": 0.5,
            "confidence": 0.9,
            "status": "PASS",
            "reason": None,
            available_column: "2025-03-14T22:00:00+00:00",
            "lineage": json.dumps({"dataset": {"snapshot_id": "fixture"}}),
            "unit": "ratio",
            "sector": "Industrials",
        }
    )
    adapted = observation_from_row(
        row, factor=factor, universe_snapshot_id="universe-2025-03-15", as_of=AS_OF
    )
    assert adapted.value == 0.5
    assert adapted.metric == "existing_metric"
    assert adapted.normalized_value is None
    assert adapted.normalization.applied is False
