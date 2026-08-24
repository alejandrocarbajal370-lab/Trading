from __future__ import annotations

import datetime
import json

import pandas as pd
import pytest
from pydantic import ValidationError

from data.market_calendar import get_trading_calendar
from data.market_data import (
    LineageEntry,
    MarketDataDataset,
    MarketDataGovernanceError,
    MarketDataMetadata,
    canonical_market_data_checksum,
    govern_market_data,
)
from factors.momentum import evaluate_momentum_metrics

AS_OF = datetime.datetime(2025, 1, 31, 23, 59, tzinfo=datetime.UTC)


def _raw_prices() -> pd.DataFrame:
    sessions = get_trading_calendar("XNYS").sessions(datetime.date(2023, 12, 20), AS_OF.date())
    rows: list[dict[str, object]] = []
    for symbol, growth in (("AAA", 0.001), ("SPY", 0.0004)):
        for index, day in enumerate(sessions):
            raw = 100.0 * (1 + growth) ** index
            factor = 0.5 if symbol == "AAA" and day <= datetime.date(2024, 8, 1) else 1.0
            action = symbol == "AAA" and day == datetime.date(2024, 8, 1)
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "raw_close": raw,
                    "adjusted_close": raw * factor,
                    "currency": "USD",
                    "available_at": f"{day.isoformat()}T22:00:00+00:00",
                    "corporate_action_status": "APPLIED" if action else "NONE",
                    "corporate_action_type": "SPLIT" if action else None,
                    "adjustment_factor": factor,
                    "confidence": 1.0,
                }
            )
    return pd.DataFrame(rows)


def _govern(frame: pd.DataFrame | None = None) -> MarketDataDataset:
    return govern_market_data(
        _raw_prices() if frame is None else frame,
        source="fixture_provider",
        dataset_version="fixture-2025-01-31-v1",
        available_at=AS_OF,
        lineage=(
            LineageEntry(
                source="fixture_provider",
                dataset="adjusted_daily_history",
                dataset_version="provider-v1",
            ),
        ),
        trading_calendar="XNYS",
        as_of=AS_OF,
        maximum_staleness_sessions=0,
    )


def test_hash_and_canonical_identity_are_reproducible_across_row_order() -> None:
    first = _govern()
    second = _govern(_raw_prices().sample(frac=1, random_state=7).reset_index(drop=True))
    assert first.metadata.checksum == second.metadata.checksum
    assert first.metadata.canonical_id == second.metadata.canonical_id
    assert canonical_market_data_checksum(first.frame) == first.metadata.checksum


def test_dataset_detects_mutation_after_governance() -> None:
    governed = _govern()
    tampered = governed.frame.copy()
    tampered.loc[0, "adjusted_close"] *= 2
    with pytest.raises(MarketDataGovernanceError, match="checksum mismatch"):
        MarketDataDataset(frame=tampered, metadata=governed.metadata)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda frame: frame.drop(columns=["raw_close"]), "missing required"),
        (lambda frame: frame.assign(available_at="2025-02-01T00:00:00+00:00"), "PIT"),
        (lambda frame: frame.assign(adjustment_factor=2.0), "do not reconcile"),
        (
            lambda frame: frame.drop(
                frame[(frame.symbol == "AAA") & (frame.date == datetime.date(2025, 1, 15))].index
            ),
            "missing market sessions",
        ),
    ],
)
def test_invalid_market_data_fails_closed(mutation, reason: str) -> None:
    with pytest.raises(MarketDataGovernanceError, match=reason):
        _govern(mutation(_raw_prices()))


def test_stale_dataset_fails_closed() -> None:
    cutoff = AS_OF.date() - datetime.timedelta(days=10)
    frame = _raw_prices().loc[lambda data: data["date"] <= cutoff]
    with pytest.raises(MarketDataGovernanceError, match="stale"):
        _govern(frame)


def test_metadata_rejects_unknown_fields_and_naive_pit_time() -> None:
    governed = _govern()
    payload = governed.metadata.model_dump()
    payload["available_at"] = datetime.datetime.fromisoformat("2025-01-31T00:00:00")
    payload["score"] = 1
    with pytest.raises(ValidationError):
        MarketDataMetadata.model_validate(payload)


def test_golden_governed_market_data_to_momentum_preserves_pit_and_lineage() -> None:
    governed = _govern()
    evaluation = evaluate_momentum_metrics(
        governed.momentum_frame(),
        experiment_id="phase-5.5.1-golden",
        dataset_lineage=governed.metadata.model_dump(mode="json"),
        as_of=AS_OF.date(),
        benchmark_symbol="SPY",
    )
    assert evaluation.health["status"] == "PASS"
    assert set(evaluation.metrics["status"]) == {"PASS"}
    lineage = json.loads(evaluation.metrics.iloc[0]["lineage"])
    assert lineage["dataset"]["canonical_id"] == governed.metadata.canonical_id
    assert lineage["dataset"]["checksum"] == governed.metadata.checksum
    assert lineage["price_inputs"][0]["canonical_id"] == governed.metadata.canonical_id
    assert evaluation.health["trade_decision"] == "NO_TRADE"
    assert evaluation.health["live_execution_enabled"] is False
    assert evaluation.health["ranking_calculated"] is False


def test_momentum_confidence_has_no_default_and_fails_closed_when_absent() -> None:
    governed = _govern(_raw_prices().drop(columns=["confidence"]))
    with pytest.raises(MarketDataGovernanceError, match="defaults are forbidden"):
        governed.momentum_frame()


def test_momentum_confidence_is_conservative_and_never_promoted() -> None:
    frame = _raw_prices().drop(columns=["confidence"]).assign(
        data_confidence=0.96,
        calculation_confidence=0.91,
        economic_confidence=0.83,
    )
    governed = _govern(frame)
    momentum = governed.momentum_frame()
    assert set(momentum["confidence"]) == {0.83}
    lineage = json.loads(momentum.iloc[0]["input_lineage"])[0]
    assert lineage["confidence_policy_version"] == "market-data-confidence-min-input-lookback-v1"
    assert lineage["confidence_inputs"] == [
        "data_confidence",
        "calculation_confidence",
        "economic_confidence",
    ]


def test_low_market_confidence_never_reaches_momentum_pass() -> None:
    governed = _govern(_raw_prices().assign(confidence=0.79))
    evaluation = evaluate_momentum_metrics(
        governed.momentum_frame(),
        experiment_id="low-confidence-e2e",
        dataset_lineage=governed.metadata.model_dump(mode="json"),
        as_of=AS_OF.date(),
        benchmark_symbol="SPY",
        low_confidence_threshold=0.80,
    )
    assert set(evaluation.metrics["status"]) == {"LOW_CONFIDENCE"}


def test_confidence_one_is_preserved_only_when_provider_declares_one() -> None:
    governed = _govern(_raw_prices().assign(confidence=1.0))
    assert set(governed.momentum_frame()["confidence"]) == {1.0}
