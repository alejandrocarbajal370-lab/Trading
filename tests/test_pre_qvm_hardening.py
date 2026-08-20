import datetime
from pathlib import Path

import pandas as pd
import pytest

from fundamentals.confidence import metric_confidence
from fundamentals.contracts import CapitalAllocationRecord, SectorBenchmark
from fundamentals.csv_source import CsvFundamentalSource
from fundamentals.history import historical_snapshot, preserve_version_history
from fundamentals.normalization import FinancialNormalizer, NormalizationError
from fundamentals.periods import PeriodAssemblyError, assemble_ttm, classify_period
from fundamentals.quality import accounting_quality_health, evaluate_accounting_quality
from research.registry import ResearchExperiment, ResearchRegistry

FIXTURE = Path("tests/fixtures/financial_reconciliation.csv")


def test_normalization_requires_explicit_concept_mapping_and_never_uses_proxy() -> None:
    raw = pd.DataFrame(
        [
            {
                "source": "sec",
                "raw_concept": "us-gaap:Revenues",
                "period_type": "duration",
                "unit": "USD",
                "value": 1,
            }
        ]
    )
    normalized = FinancialNormalizer().normalize(raw)
    assert normalized.loc[0, "metric"] == "revenue"
    assert normalized.loc[0, "proxy_used"] == False
    raw.loc[0, "raw_concept"] = "custom:AdjustedRevenue"
    with pytest.raises(NormalizationError, match="unmapped raw concept"):
        FinancialNormalizer().normalize(raw)


def test_version_history_preserves_original_and_pit_never_leaks_restatement() -> None:
    records = CsvFundamentalSource(Path("tests/fixtures/fundamentals_pit.csv")).fetch(
        symbols={"AAPL"}
    )
    history = preserve_version_history(records)
    assert len(history) == 3
    old = historical_snapshot(history, available_at=pd.Timestamp("2025-11-01T00:00:00Z"))
    new = historical_snapshot(history, available_at=pd.Timestamp("2025-12-01T00:00:00Z"))
    assert old["value"].tolist() == [100]
    assert new["value"].tolist() == [105]


def test_period_classification_and_ttm_are_pit_and_require_contiguous_quarters() -> None:
    base = (
        CsvFundamentalSource(FIXTURE).fetch(symbols={"TEST"}).query("metric == 'revenue'").iloc[0]
    )
    quarters = []
    for start, end, value, available in [
        ("2025-01-01", "2025-03-31", 10, "2025-05-01T00:00:00Z"),
        ("2025-04-01", "2025-06-30", 20, "2025-08-01T00:00:00Z"),
        ("2025-07-01", "2025-09-30", 30, "2025-11-01T00:00:00Z"),
        ("2025-10-01", "2025-12-31", 40, "2026-02-01T00:00:00Z"),
    ]:
        row = base.copy()
        row["fiscal_period_start"] = datetime.date.fromisoformat(start)
        row["fiscal_period_end"] = datetime.date.fromisoformat(end)
        row["value"] = value
        row["available_at"] = pd.Timestamp(available)
        row["filed_at"] = pd.Timestamp(available)
        quarters.append(row)
    frame = pd.DataFrame(quarters)
    assert (
        classify_period(
            frame.iloc[0]["fiscal_period_start"], frame.iloc[0]["fiscal_period_end"], "duration"
        )
        == "quarterly"
    )
    assert assemble_ttm(frame, cutoff=pd.Timestamp("2025-12-01T00:00:00Z")).empty
    ttm = assemble_ttm(frame, cutoff=pd.Timestamp("2026-03-01T00:00:00Z"))
    assert ttm.iloc[0]["value"] == 100
    assert ttm.iloc[0]["period_kind"] == "ttm"
    broken = frame.copy()
    broken.iloc[1, broken.columns.get_loc("fiscal_period_start")] = datetime.date(2025, 4, 2)
    with pytest.raises(PeriodAssemblyError, match="non-contiguous"):
        assemble_ttm(broken, cutoff=pd.Timestamp("2026-03-01T00:00:00Z"))


def test_quality_and_confidence_are_diagnostics_not_investment_signals() -> None:
    snapshot = CsvFundamentalSource(FIXTURE).fetch(symbols={"TEST"})
    assets = snapshot.iloc[[0]].copy()
    assets["metric"] = "total_assets"
    assets["period_type"] = "instant"
    assets["fiscal_period_start"] = None
    assets["value"] = 1000
    checks = evaluate_accounting_quality(pd.concat([snapshot, assets]))
    assert {"cfo_to_net_income", "accrual_ratio"} <= set(checks["check"])
    assert accounting_quality_health(checks)["is_investment_signal"] is False
    confidence = metric_confidence(snapshot)
    assert confidence["confidence"].between(0, 1).all()


def test_fx_metadata_is_stored_without_conversion() -> None:
    snapshot = CsvFundamentalSource(FIXTURE).fetch(symbols={"TEST"})
    assert set(snapshot["reporting_currency"].dropna()) == {"USD"}
    assert snapshot["fx_rate"].isna().all()
    assert snapshot.loc[snapshot["metric"] == "revenue", "value"].iloc[0] == 500


def test_future_context_contracts_contain_pit_availability_without_scoring() -> None:
    benchmark = SectorBenchmark(
        "software",
        "free_cash_flow_margin",
        0.2,
        pd.Timestamp("2025-12-31"),
        pd.Timestamp("2026-02-01", tz="UTC"),
        30,
        "fixture",
    )
    action = CapitalAllocationRecord(
        "TEST",
        "buyback",
        10,
        "USD",
        pd.Timestamp("2025-12-31", tz="UTC"),
        pd.Timestamp("2026-02-01", tz="UTC"),
        "filing",
        "10-k",
    )
    assert benchmark.available_at.tz is not None
    assert action.action == "buyback"
    assert not hasattr(benchmark, "score")


def test_research_registry_rejects_duplicate_preregistration(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "registry.jsonl")
    experiment = ResearchExperiment(
        "quality-001",
        "Cash conversion predicts persistence",
        "future_fcf",
        "US equities",
        "2010-01-01",
        "2020-12-31",
        "2026-08-20T00:00:00Z",
    )
    registry.register(experiment)
    with pytest.raises(ValueError, match="duplicate experiment_id"):
        registry.register(experiment)
