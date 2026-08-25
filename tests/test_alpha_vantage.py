import datetime
import json
import urllib.error
from pathlib import Path
from typing import Self

import pytest

from data.connectors.alpha_vantage import (
    AlphaVantageMomentumHistoricalPriceSource,
    AlphaVantagePriceSource,
)
from data.connectors.base import (
    MomentumHistoricalPriceSource,
    PriceSource,
    PriceSourceConfigurationError,
    PriceSourceRequestError,
    PriceSourceResponseError,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.body = json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_fetch_maps_provider_payload_to_price_contract() -> None:
    fixture = Path("tests/fixtures/alpha_vantage_eod.json")
    payload = json.loads(fixture.read_text())
    seen: dict[str, object] = {}

    def opener(request: object, *, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url  # type: ignore[attr-defined]
        seen["timeout"] = timeout
        return FakeResponse(payload)

    source = AlphaVantagePriceSource(api_key="test-key", timeout_seconds=3, opener=opener)
    result = source.fetch(symbols={"AAPL"}, data_date=datetime.date(2026, 8, 19))

    assert result.to_dict("records") == [
        {
            "symbol": "AAPL",
            "date": datetime.date(2026, 8, 19),
            "open": 230.1,
            "high": 233.4,
            "low": 229.8,
            "close": 232.75,
            "volume": 50_210_000.0,
        }
    ]
    assert "apikey=test-key" in str(seen["url"])
    assert "function=TIME_SERIES_DAILY" in str(seen["url"])
    assert "outputsize=compact" in str(seen["url"])
    assert "DAILY_ADJUSTED" not in str(seen["url"])
    assert seen["timeout"] == 3


def test_request_retries_transient_network_failures() -> None:
    fixture = json.loads(Path("tests/fixtures/alpha_vantage_eod.json").read_text())
    attempts = 0
    delays: list[float] = []

    def opener(*_: object, **__: object) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.URLError("temporary")
        return FakeResponse(fixture)

    source = AlphaVantagePriceSource(
        api_key="test-key", max_retries=2, opener=opener, sleeper=delays.append
    )
    source.fetch(symbols={"AAPL"}, data_date=datetime.date(2026, 8, 19))

    assert attempts == 3
    assert delays == [0.25, 0.5]


def test_request_raises_explicit_error_after_retries() -> None:
    def opener(*_: object, **__: object) -> FakeResponse:
        raise TimeoutError

    source = AlphaVantagePriceSource(
        api_key="test-key", max_retries=1, opener=opener, sleeper=lambda _: None
    )
    with pytest.raises(PriceSourceRequestError, match="after 2 attempts"):
        source.fetch(symbols={"AAPL"}, data_date=datetime.date(2026, 8, 19))


def test_provider_error_payload_is_explicit() -> None:
    source = AlphaVantagePriceSource(
        api_key="test-key", opener=lambda *_args, **_kwargs: FakeResponse({"Note": "rate limit"})
    )
    with pytest.raises(PriceSourceResponseError, match="rate limit"):
        source.fetch(symbols={"AAPL"}, data_date=datetime.date(2026, 8, 19))


def test_environment_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    with pytest.raises(PriceSourceConfigurationError, match="ALPHA_VANTAGE_API_KEY"):
        AlphaVantagePriceSource.from_env()


def test_fetch_history_maps_adjusted_price_and_corporate_action_lineage() -> None:
    payload = json.loads(Path("tests/fixtures/alpha_vantage_daily.json").read_text())
    source = AlphaVantageMomentumHistoricalPriceSource(
        api_key="test-key", opener=lambda *_args, **_kwargs: FakeResponse(payload)
    )
    row = source.fetch_history(symbols={"AAPL"}, as_of=datetime.date(2026, 8, 19)).iloc[0]
    assert row["adjusted_close"] == 231.5
    assert row["raw_close"] == 232.75
    assert row["price_basis"] == "ADJUSTED"
    assert row["corporate_action_status"] == "APPLIED"
    assert row["corporate_action_type"] == "DIVIDEND"
    assert json.loads(row["input_lineage"])[0]["provider_function"] == (
        "TIME_SERIES_DAILY_ADJUSTED"
    )
    assert row["historical_access_tier"] == "premium_required"
    assert row["confidence"] == 0.90
    assert row["confidence"] < 1.0
    assert row["confidence_policy_version"] == (
        "alpha-vantage-adjusted-history-observable-fields-v1"
    )
    assert source.metadata == {
        "provider": "alpha_vantage",
        "dataset": "TIME_SERIES_DAILY_ADJUSTED",
        "provider_function": "TIME_SERIES_DAILY_ADJUSTED",
        "dataset_version": "daily-adjusted-full-v1",
        "outputsize": "full",
        "access_tier": "premium_required",
        "price_basis": "split_dividend_adjusted",
    }


def test_operational_and_momentum_sources_implement_separate_contracts() -> None:
    assert isinstance(AlphaVantagePriceSource(api_key="x"), PriceSource)
    assert isinstance(
        AlphaVantageMomentumHistoricalPriceSource(api_key="x"), MomentumHistoricalPriceSource
    )
    assert not hasattr(AlphaVantagePriceSource(api_key="x"), "fetch_history")
