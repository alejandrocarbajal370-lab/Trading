from __future__ import annotations

from research.pre_phase6_scale_smoke import run_synthetic_scale_smoke


def test_phase6_synthetic_end_to_end_ten_securities(tmp_path) -> None:
    report = run_synthetic_scale_smoke(
        security_count=10, workdir=tmp_path / "ten", phase6_scoring=True
    )
    assert report["security_count"] == 10
    assert report["phase6_active_metric_set"] == ()
    assert report["phase6_composite_eligible"] == 0
    assert report["phase6_cohort_publication_status"] == "FAIL"
    assert report["trade_decision"] == "NO_TRADE"
    assert report["live_execution_enabled"] is False
    assert report["signals_generated"] is False
    assert report["backtesting_performed"] is False


def test_phase6_synthetic_end_to_end_one_hundred_securities(tmp_path) -> None:
    report = run_synthetic_scale_smoke(
        security_count=100, workdir=tmp_path / "hundred", phase6_scoring=True
    )
    assert report["security_count"] == 100
    assert report["phase6_composite_eligible"] == 100
    assert report["phase6_cohort_publication_status"] == "PASS"
    assert len(report["phase6_artifact_hash"]) == 64
    assert report["trade_decision"] == "NO_TRADE"
    assert report["live_execution_enabled"] is False
    assert report["signals_generated"] is False
    assert report["backtesting_performed"] is False
