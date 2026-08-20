from data.validation.health import HealthStatus, evaluate_data_health


def test_data_health_passes_clean_run() -> None:
    result = evaluate_data_health(expected_rows=812, received_rows=812)
    assert result.status is HealthStatus.PASS
    assert result.coverage == 1.0


def test_data_health_blocks_low_coverage() -> None:
    result = evaluate_data_health(expected_rows=812, received_rows=400)
    assert result.status is HealthStatus.FAIL
    assert any("coverage" in reason for reason in result.reasons)


def test_data_health_blocks_point_in_time_violation() -> None:
    result = evaluate_data_health(
        expected_rows=812,
        received_rows=812,
        point_in_time_violations=1,
    )
    assert result.status is HealthStatus.FAIL
