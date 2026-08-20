import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.phase3 import run_phase3
from fundamentals.csv_source import CsvFundamentalSource
from fundamentals.financial_engine import calculate_financial_metrics

FIXTURE = Path("tests/fixtures/financial_reconciliation.csv")


def _snapshot() -> pd.DataFrame:
    return CsvFundamentalSource(FIXTURE).fetch(symbols={"TEST"})


def _metric(frame: pd.DataFrame, name: str) -> pd.Series:
    return frame.set_index("metric").loc[name]


def test_manual_reconciliation_has_exact_expected_outputs() -> None:
    result = calculate_financial_metrics(_snapshot()).set_index("metric")
    expected = {
        "free_cash_flow": 100.0,
        "free_cash_flow_margin": 0.2,
        "net_debt": 75.0,
        "net_debt_to_ebitda": 0.5,
        "cfo_to_net_income": 1.5,
        "roic_v1": 0.25,
    }
    assert result["value"].to_dict() == expected
    assert set(result["status"]) == {"PASS"}
    assert all("manual_fixture" in lineage for lineage in result["input_lineage"])


@pytest.mark.parametrize(
    ("input_metric", "value", "output_metric", "reason"),
    [
        ("ebitda", -1, "net_debt_to_ebitda", "must be positive"),
        ("net_income", 0, "cfo_to_net_income", "is zero"),
        ("revenue", 0, "free_cash_flow_margin", "is zero"),
        ("tax_rate", -0.1, "roic_v1", "between 0 and 1"),
        ("tax_rate", 1.1, "roic_v1", "between 0 and 1"),
        ("revenue", np.inf, "free_cash_flow_margin", "non-finite"),
    ],
)
def test_invalid_edge_inputs_are_not_computed(
    input_metric: str, value: float, output_metric: str, reason: str
) -> None:
    snapshot = _snapshot()
    snapshot.loc[snapshot["metric"] == input_metric, "value"] = value
    result = _metric(calculate_financial_metrics(snapshot), output_metric)
    assert result["status"] == "NOT_COMPUTED"
    assert pd.isna(result["value"])
    assert reason in result["reason"]


def test_missing_input_is_explicit_and_never_defaults_to_zero() -> None:
    snapshot = _snapshot().query("metric != 'cash'")
    result = _metric(calculate_financial_metrics(snapshot), "net_debt")
    assert result["status"] == "MISSING"
    assert result["reason"] == "missing inputs: cash"
    assert pd.isna(result["value"])


def test_explicit_no_debt_and_negative_fcf_are_valid_values() -> None:
    snapshot = _snapshot()
    snapshot.loc[snapshot["metric"] == "total_debt", "value"] = 0
    snapshot.loc[snapshot["metric"] == "capital_expenditures", "value"] = 140
    result = calculate_financial_metrics(snapshot).set_index("metric")
    assert result.loc["net_debt", "value"] == -25
    assert result.loc["free_cash_flow", "value"] == -20
    assert result.loc["net_debt", "status"] == "PASS"
    assert result.loc["free_cash_flow", "status"] == "PASS"


@pytest.mark.parametrize(("second_value", "reason"), [(120, "duplicate"), (121, "conflicting")])
def test_duplicate_and_conflicting_inputs_are_rejected(
    second_value: float, reason: str
) -> None:
    snapshot = _snapshot()
    duplicate = snapshot[snapshot["metric"] == "cash_from_operations"].copy()
    duplicate["value"] = second_value
    result = _metric(
        calculate_financial_metrics(pd.concat([snapshot, duplicate], ignore_index=True)),
        "free_cash_flow",
    )
    assert result["status"] == "NOT_COMPUTED"
    assert reason in result["reason"]


def test_phase3_writes_outputs_and_preserves_no_trade(tmp_path: Path) -> None:
    result = run_phase3(
        symbols={"TEST"},
        data_date=datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
        source_path=FIXTURE,
        output_root=tmp_path,
    )
    names = {path.name for path in result.phase2.output_dir.iterdir()}
    assert {"financial_metrics.csv", "financial_health.json"} <= names
    health = json.loads((result.phase2.output_dir / "financial_health.json").read_text())
    summary = json.loads((result.phase2.output_dir / "run_summary.json").read_text())
    manifest = json.loads((result.phase2.output_dir / "validation_manifest.json").read_text())
    assert health["status"] == "PASS"
    assert summary["overall_status"] == "PASS"
    assert manifest["checks"]["financial_metrics"] == "PASS"
    assert summary["trade_decision"] == "NO_TRADE"
    assert summary["live_execution_enabled"] is False
