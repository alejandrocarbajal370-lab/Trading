from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(frozen=True)
class DataHealthResult:
    expected_rows: int
    received_rows: int
    coverage: float
    duplicate_rows: int
    stale_critical_rows: int
    invalid_price_rows: int
    critical_missing_rows: int
    point_in_time_violations: int
    status: HealthStatus
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


def evaluate_data_health(
    *,
    expected_rows: int,
    received_rows: int,
    duplicate_rows: int = 0,
    stale_critical_rows: int = 0,
    invalid_price_rows: int = 0,
    critical_missing_rows: int = 0,
    point_in_time_violations: int = 0,
    minimum_coverage: float = 0.98,
) -> DataHealthResult:
    if expected_rows <= 0:
        raise ValueError("expected_rows must be positive")
    if received_rows < 0:
        raise ValueError("received_rows cannot be negative")

    coverage = received_rows / expected_rows
    critical_reasons: list[str] = []
    warning_reasons: list[str] = []

    if coverage < minimum_coverage:
        critical_reasons.append(
            f"universe coverage {coverage:.2%} below minimum {minimum_coverage:.2%}"
        )
    if stale_critical_rows > 0:
        critical_reasons.append(f"{stale_critical_rows} stale critical rows")
    if invalid_price_rows > 0:
        critical_reasons.append(f"{invalid_price_rows} invalid price rows")
    if critical_missing_rows > 0:
        critical_reasons.append(f"{critical_missing_rows} critical missing rows")
    if point_in_time_violations > 0:
        critical_reasons.append(f"{point_in_time_violations} point-in-time violations")
    if duplicate_rows > 0:
        warning_reasons.append(f"{duplicate_rows} duplicate rows")

    if critical_reasons:
        status = HealthStatus.FAIL
    elif warning_reasons:
        status = HealthStatus.WARNING
    else:
        status = HealthStatus.PASS

    return DataHealthResult(
        expected_rows=expected_rows,
        received_rows=received_rows,
        coverage=coverage,
        duplicate_rows=duplicate_rows,
        stale_critical_rows=stale_critical_rows,
        invalid_price_rows=invalid_price_rows,
        critical_missing_rows=critical_missing_rows,
        point_in_time_violations=point_in_time_violations,
        status=status,
        reasons=tuple(critical_reasons + warning_reasons),
    )
