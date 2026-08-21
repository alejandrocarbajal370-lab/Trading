import json
from pathlib import Path

import pandas as pd
import pytest

from research.quality_validation import build_quality_validation_report, run_quality_validation


def _lineage(source: str = "sec_fixture") -> str:
    return json.dumps({"dataset": {"snapshot_id": "financial-2024"}, "source": source})


def _quality() -> pd.DataFrame:
    rows = []
    values = {
        "AAA": {"roic": 0.20, "fcf_margin": 0.15, "cfo_conversion": 1.2},
        "BBB": {"roic": 0.10, "fcf_margin": 0.05, "cfo_conversion": 0.9},
    }
    for symbol, metrics in values.items():
        for metric, value in metrics.items():
            rows.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "value": value,
                    "status": "PASS",
                    "reason": None,
                    "sector": "Technology" if symbol == "AAA" else "Industrials",
                    "industry": "Software" if symbol == "AAA" else "Machinery",
                    "lineage": _lineage(),
                }
            )
    return pd.DataFrame(rows)


def _universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "eligibility_status": "ELIGIBLE",
                "exclusion_reason": "",
                "universe_confidence": 1.0,
                "sector": "Technology",
                "industry": "Software",
                "lineage": json.dumps({"source": "universe_fixture"}),
            },
            {
                "symbol": "BBB",
                "eligibility_status": "ELIGIBLE",
                "exclusion_reason": "",
                "universe_confidence": 1.0,
                "sector": "Industrials",
                "industry": "Machinery",
                "lineage": json.dumps({"source": "universe_fixture"}),
            },
            {
                "symbol": "CCC",
                "eligibility_status": "ELIGIBLE",
                "exclusion_reason": "",
                "universe_confidence": 0.8,
                "sector": "Healthcare",
                "industry": "Biotechnology",
                "lineage": json.dumps({"source": "universe_fixture"}),
            },
        ]
    )


def _financial() -> pd.DataFrame:
    rows = []
    for metric, history in {
        "roic_v1": (0.10, 0.15, 0.20),
        "free_cash_flow": (80.0, 90.0, 100.0),
        "free_cash_flow_margin": (0.10, 0.12, 0.15),
    }.items():
        for period, value in zip(("2022-12-31", "2023-12-31", "2024-12-31"), history, strict=True):
            rows.append(
                {
                    "symbol": "AAA",
                    "fiscal_period_end": period,
                    "metric": metric,
                    "value": value,
                    "status": "PASS",
                    "reason": None,
                    "input_lineage": json.dumps([{"source": "sec_fixture"}]),
                }
            )
    return pd.DataFrame(rows)


def test_quality_coverage_keeps_missing_universe_members_visible() -> None:
    report, _ = build_quality_validation_report(
        _quality(),
        _universe(),
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.5,
    )
    roic = next(item for item in report["coverage"] if item["metric"] == "roic")
    assert roic["eligible_symbols"] == 3
    assert roic["passing_symbols"] == 2
    assert roic["pass_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert report["availability_summary"]["DATA_UNAVAILABLE"] == 1


def test_low_coverage_generates_warning_without_ranking() -> None:
    report, _ = build_quality_validation_report(
        _quality(),
        _universe(),
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.9,
    )
    assert report["health"] == "WARNING"
    assert any("low pass coverage for roic" in item for item in report["warnings"])
    assert report["ranking_calculated"] is False
    assert report["composite_score_calculated"] is False


def test_distribution_flags_descriptive_outlier() -> None:
    quality = _quality()
    additions = []
    for index, value in enumerate((0.11, 0.12, 0.13, 0.14, 2.5), start=1):
        additions.append(
            {
                "symbol": f"X{index}",
                "metric": "roic",
                "value": value,
                "status": "PASS",
                "reason": None,
                "lineage": _lineage(),
            }
        )
    quality = pd.concat([quality, pd.DataFrame(additions)], ignore_index=True)
    universe = _universe()
    extra_universe = pd.DataFrame(
        [
            {
                "symbol": f"X{index}",
                "eligibility_status": "ELIGIBLE",
                "exclusion_reason": "",
                "universe_confidence": 1.0,
                "lineage": json.dumps({"source": "universe_fixture"}),
            }
            for index in range(1, 6)
        ]
    )
    universe = pd.concat([universe, extra_universe], ignore_index=True)
    report, _ = build_quality_validation_report(
        quality,
        universe,
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.0,
    )
    roic = next(item for item in report["distributions"] if item["metric"] == "roic")
    assert any(item["symbol"] == "X5" for item in roic["outliers"])


def test_quality_symbol_outside_eligible_universe_does_not_contaminate_distribution() -> None:
    quality = pd.concat(
        [
            _quality(),
            pd.DataFrame(
                [
                    {
                        "symbol": "OUT",
                        "metric": "roic",
                        "value": 99.0,
                        "status": "PASS",
                        "reason": None,
                        "lineage": _lineage(),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    report, _ = build_quality_validation_report(
        quality,
        _universe(),
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.0,
    )
    roic = next(item for item in report["distributions"] if item["metric"] == "roic")
    assert roic["max"] == pytest.approx(0.20)
    assert report["quality_symbols_outside_eligible_universe"] == ["OUT"]
    assert any("outside the eligible universe" in item for item in report["warnings"])


def test_empty_eligible_universe_is_a_fail() -> None:
    universe = _universe().copy()
    universe["eligibility_status"] = "EXCLUDED"
    universe["exclusion_reason"] = "test_exclusion"
    report, _ = build_quality_validation_report(
        _quality(),
        universe,
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.0,
    )
    assert report["health"] == "FAIL"
    assert "eligible universe is empty" in report["failures"]


def test_trends_are_descriptive_and_preserve_direction() -> None:
    report, trends = build_quality_validation_report(
        _quality(),
        _universe(),
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        financial_metrics=_financial(),
        minimum_pass_coverage=0.0,
    )
    result = trends.set_index("metric")
    assert result.loc["roic_trend", "direction"] == "IMPROVING"
    assert result.loc["fcf_trend", "direction"] == "IMPROVING"
    assert result.loc["margin_trend", "direction"] == "IMPROVING"
    assert report["trade_decision"] == "NO_TRADE"


def test_pit_violation_fails_validation() -> None:
    quality = _quality()
    quality.loc[quality.index[0], ["status", "reason"]] = [
        "NOT_COMPUTED",
        "PIT violation: available_at exceeds data_date",
    ]
    report, _ = build_quality_validation_report(
        quality,
        _universe(),
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.0,
    )
    assert report["health"] == "FAIL"
    assert report["pit_violations"] == 1


def test_invalid_lineage_fails_validation() -> None:
    quality = _quality()
    quality.loc[quality.index[0], "lineage"] = "{broken"
    report, _ = build_quality_validation_report(
        quality,
        _universe(),
        experiment_id="quality-validation-001",
        universe_snapshot_id="universe-2024",
        dataset_snapshot_id="financial-2024",
        minimum_pass_coverage=0.0,
    )
    assert report["health"] == "FAIL"
    assert report["lineage_health"]["invalid_quality_lineage"] == 1


def test_quality_validation_run_is_reproducible(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality_metrics.csv"
    universe_path = tmp_path / "universe_membership.csv"
    financial_path = tmp_path / "financial_metrics.csv"
    _quality().to_csv(quality_path, index=False)
    _universe().to_csv(universe_path, index=False)
    _financial().to_csv(financial_path, index=False)
    kwargs = {
        "quality_metrics_path": quality_path,
        "universe_membership_path": universe_path,
        "financial_metrics_path": financial_path,
        "experiment_id": "quality-validation-001",
        "universe_snapshot_id": "universe-2024",
        "dataset_snapshot_id": "financial-2024",
        "output_root": tmp_path / "outputs",
        "minimum_pass_coverage": 0.0,
    }
    first = run_quality_validation(**kwargs)
    second = run_quality_validation(**kwargs)
    assert first.output_dir == second.output_dir
    assert first.report == second.report
    assert (first.output_dir / "quality_validation_report.json").is_file()
    assert (first.output_dir / "quality_availability.csv").is_file()
    assert (first.output_dir / "quality_trends.csv").is_file()
