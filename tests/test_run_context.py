from datetime import datetime
from zoneinfo import ZoneInfo

from core.run_context import build_run_context


def test_run_context_is_deterministic_for_same_inputs() -> None:
    now = datetime(2026, 8, 20, 18, 0, tzinfo=ZoneInfo("America/Mexico_City"))
    kwargs = {
        "mode": "research",
        "model_version": "QVM_v0.1",
        "git_commit": "abc123",
        "data_date": "2026-08-20",
        "now": now,
    }
    first = build_run_context(**kwargs)
    second = build_run_context(**kwargs)
    assert first == second
    assert first.run_id.startswith("20260820_180000_RESEARCH_")
