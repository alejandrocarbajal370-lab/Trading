import datetime
import json
from pathlib import Path

import pandas as pd

from core.phase3 import run_phase3
from core.phase36 import run_phase36
from factors.value import VALUE_CONTRACT
from research.datasets import file_sha256
from research.quality_runner import run_quality_experiment
from research.quality_validation import run_quality_validation
from research.registry import DatasetRegistration, ResearchExperiment, ResearchRegistry
from research.value_runner import run_value_experiment
from universe.validation import UniverseRules

FUNDAMENTALS = Path("tests/fixtures/financial_reconciliation.csv")


def _universe_source(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "region": "North America",
                "sector": "Industrials",
                "industry": "Machinery",
                "market_cap": 1_000_000_000,
                "market_cap_currency": "USD",
                "average_volume": 1_000_000,
                "average_dollar_volume": 20_000_000,
                "listing_date": "2020-01-01T00:00:00Z",
                "source": "universe_fixture",
                "source_timestamp": "2026-02-28T22:00:00Z",
                "available_at": "2026-02-28T22:00:00Z",
            }
        ]
    ).to_csv(path, index=False)


def test_golden_research_pipeline_is_auditable_and_non_trading(tmp_path: Path) -> None:
    cutoff = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
    phase3 = run_phase3(
        symbols={"TEST"},
        data_date=cutoff,
        source_path=FUNDAMENTALS,
        output_root=tmp_path / "validation",
        now=cutoff,
    )
    financial_path = phase3.phase2.output_dir / "financial_metrics.csv"
    financial = pd.read_csv(financial_path)
    assert financial["confidence"].notna().all()
    assert financial["confidence"].between(0, 1).all()
    assert {"roic_v1", "accrual_ratio", "free_cash_flow_margin"} <= set(financial["metric"])

    universe_source = tmp_path / "universe.csv"
    _universe_source(universe_source)
    phase36 = run_phase36(
        source_path=universe_source,
        rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=cutoff,
        output_root=tmp_path / "universe_validation",
        snapshot_root=tmp_path / "universe_snapshots",
        now=cutoff,
    )
    universe_membership_path = phase36.snapshot_dir / "universe_membership.csv"

    dataset = DatasetRegistration(
        dataset_id="financial-intelligence-metrics",
        snapshot_id="financial-2025-12-31",
        path=str(financial_path),
        sha256=file_sha256(financial_path),
        lineage=("Phase 3 financial_metrics.csv",),
    )
    experiment = ResearchExperiment(
        experiment_id="quality-e2e-001",
        experiment_version="1.0",
        hypothesis="Quality metrics are reproducible from governed PIT financial data.",
        outcome_metric="quality_metric_coverage",
        universe="Governed one-name fixture universe",
        universe_snapshot_id="universe-2026-03-01",
        ruleset_version="universe-v1",
        sample_start="2025-01-01",
        sample_end="2025-12-31",
        preregistered_at="2026-03-01T00:00:00+00:00",
        created_at="2026-03-01T00:00:00+00:00",
        metrics_evaluated=("roic", "fcf_margin", "cfo_conversion", "accrual_quality"),
        expected_result="Integrated Quality metrics retain confidence and lineage.",
        observed_result="PENDING",
        decision="REVIEW",
        status="READY",
        datasets=(dataset,),
        data_lineage=("Phase 2 PIT", "Phase 3 Financial Intelligence", "Universe snapshot"),
    )
    registry_path = tmp_path / "registry.jsonl"
    ResearchRegistry(registry_path).register(experiment)

    quality_run = run_quality_experiment(
        registry_path=registry_path,
        experiment_id=experiment.experiment_id,
        experiment_version=experiment.experiment_version,
        output_root=tmp_path / "research",
        universe_snapshot_dir=phase36.snapshot_dir,
    )
    quality_path = quality_run.output_dir / "quality_metrics.csv"
    quality = pd.read_csv(quality_path).set_index("metric")
    assert quality.loc["roic", "status"] == "PASS"
    assert quality.loc["accrual_quality", "status"] == "PASS"
    assert quality.loc["roic", "confidence"] > 0
    assert quality_run.research_run["universe_governance"]["verified"] is True
    assert quality_run.research_run["trade_decision"] == "NO_TRADE"
    assert quality_run.research_run["live_execution_enabled"] is False

    validation = run_quality_validation(
        quality_metrics_path=quality_path,
        universe_membership_path=universe_membership_path,
        financial_metrics_path=financial_path,
        experiment_id=experiment.experiment_id,
        universe_snapshot_id=experiment.universe_snapshot_id,
        dataset_snapshot_id=dataset.snapshot_id,
        output_root=tmp_path / "research_validation",
        minimum_pass_coverage=0.0,
    )
    coverage = {item["metric"]: item for item in validation.report["coverage"]}
    assert coverage["accrual_quality"]["passing_symbols"] == 1
    assert validation.report["pit_violations"] == 0
    assert validation.report["trade_decision"] == "NO_TRADE"
    assert validation.report["live_execution_enabled"] is False

    phase3_summary = json.loads(
        (phase3.phase2.output_dir / "run_summary.json").read_text(encoding="utf-8")
    )
    universe_summary = json.loads(
        (phase36.output_dir / "run_summary.json").read_text(encoding="utf-8")
    )
    assert phase3_summary["overall_status"] == "PASS"
    assert universe_summary["overall_status"] in {"PASS", "WARNING"}


def test_golden_governed_universe_to_financial_intelligence_to_value(tmp_path: Path) -> None:
    cutoff = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
    phase3 = run_phase3(
        symbols={"TEST"},
        data_date=cutoff,
        source_path=FUNDAMENTALS,
        output_root=tmp_path / "validation",
        now=cutoff,
    )
    universe_source = tmp_path / "universe.csv"
    _universe_source(universe_source)
    phase36 = run_phase36(
        source_path=universe_source,
        rules=UniverseRules(allowed_exchanges=("NYSE",)),
        as_of=cutoff,
        output_root=tmp_path / "universe_validation",
        snapshot_root=tmp_path / "universe_snapshots",
        now=cutoff,
    )

    financial_metrics = pd.read_csv(phase3.phase2.output_dir / "financial_metrics.csv")
    financial_snapshot = phase3.phase2.snapshot
    membership = pd.read_csv(phase36.snapshot_dir / "universe_membership.csv")
    derived = financial_metrics.set_index("metric")
    source = financial_snapshot.set_index("metric")
    market_cap = float(membership.set_index("symbol").loc["TEST", "market_cap"])
    enterprise_value = market_cap + float(source.loc["total_debt", "value"]) - float(
        source.loc["cash", "value"]
    )
    values = {
        "free_cash_flow": float(derived.loc["free_cash_flow", "value"]),
        "earnings": float(source.loc["net_income", "value"]),
        "ebit": float(source.loc["operating_income", "value"]),
        "ebitda": float(source.loc["ebitda", "value"]),
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
    }
    rows = []
    for metric, value in values.items():
        instant = metric in {"market_cap", "enterprise_value"}
        lineage_source = "Phase 3.6 governed universe" if instant else "Phase 3 financial intelligence"
        rows.append(
            {
                "symbol": "TEST",
                "valuation_as_of": "2026-03-01",
                "fiscal_period_end": "2025-12-31",
                "period_basis": "INSTANT" if instant else "FY",
                "metric": metric,
                "value": value,
                "unit": "currency",
                "currency": "USD",
                "available_at": "2026-02-28T22:00:00+00:00" if instant else "2026-02-02T00:00:00+00:00",
                "status": "PASS",
                "reason": None,
                "confidence": 1.0,
                "input_lineage": json.dumps([{"source": lineage_source, "metric": metric}]),
                "industry": "Machinery",
            }
        )
    value_input_path = tmp_path / "governed_value_inputs.csv"
    pd.DataFrame(rows).to_csv(value_input_path, index=False)
    dataset = DatasetRegistration(
        dataset_id="governed-value-inputs",
        snapshot_id="financial-2025-12-31",
        path=str(value_input_path),
        sha256=file_sha256(value_input_path),
        lineage=("Phase 3 financial intelligence", "Phase 3.6 governed universe"),
    )
    experiment = ResearchExperiment(
        experiment_id="value-e2e-001",
        experiment_version="1.0",
        hypothesis=VALUE_CONTRACT.hypothesis,
        outcome_metric="individual_value_metric_coverage",
        universe="Governed one-name fixture universe",
        universe_snapshot_id="universe-2026-03-01",
        ruleset_version="universe-v1",
        sample_start="2025-01-01",
        sample_end="2025-12-31",
        preregistered_at="2026-03-01T00:00:00+00:00",
        created_at="2026-03-01T00:00:00+00:00",
        metrics_evaluated=tuple(item.name for item in VALUE_CONTRACT.definitions),
        expected_result="Value metrics retain governed financial and universe lineage.",
        observed_result="PENDING",
        decision="REVIEW",
        status="READY",
        datasets=(dataset,),
        data_lineage=("Phase 3", "Phase 3.6", "Value Engine"),
    )
    registry_path = tmp_path / "value_registry.jsonl"
    ResearchRegistry(registry_path).register(experiment)
    result = run_value_experiment(
        registry_path=registry_path,
        experiment_id=experiment.experiment_id,
        experiment_version=experiment.experiment_version,
        output_root=tmp_path / "value_research",
        universe_snapshot_dir=phase36.snapshot_dir,
    )
    metrics = pd.read_csv(result.output_dir / "value_metrics.csv").set_index("metric")
    assert metrics.loc["fcf_yield", "status"] == "PASS"
    assert metrics.loc["ev_to_ebit", "status"] == "WARNING"
    assert "extreme" in metrics.loc["ev_to_ebit", "reason"]
    assert result.research_run["universe_governance"]["membership_sha256"]
    assert result.research_run["universe_governance"]["health"] in {"PASS", "WARNING"}
    assert result.research_run["trade_decision"] == "NO_TRADE"
    assert result.research_run["live_execution_enabled"] is False
