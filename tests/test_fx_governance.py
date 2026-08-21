from __future__ import annotations

import datetime

import pandas as pd
import pytest

from data.fx import (
    FXDataset,
    FXGovernanceError,
    FXLineageEntry,
    FXProvider,
    canonical_fx_checksum,
    govern_fx,
)

AS_OF = datetime.datetime(2025, 1, 31, 23, 59, tzinfo=datetime.UTC)


def _rates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "currency_pair": "JPY/USD",
                "base_currency": "JPY",
                "quote_currency": "USD",
                "market_timestamp": "2025-01-30T21:00:00Z",
                "available_at": "2025-01-30T21:01:00Z",
                "rate": 0.00645,
            },
            {
                "currency_pair": "JPY/USD",
                "base_currency": "JPY",
                "quote_currency": "USD",
                "market_timestamp": "2025-01-31T21:00:00Z",
                "available_at": "2025-01-31T21:01:00Z",
                "rate": 0.00650,
            },
            {
                "currency_pair": "EUR/USD",
                "base_currency": "EUR",
                "quote_currency": "USD",
                "market_timestamp": "2025-01-31T21:00:00Z",
                "available_at": "2025-01-31T21:02:00Z",
                "rate": 1.04,
            },
        ]
    )


def _govern(frame: pd.DataFrame | None = None) -> FXDataset:
    return govern_fx(
        _rates() if frame is None else frame,
        source="fixture_provider",
        dataset_version="fixture-2025-01-31-v1",
        available_at=AS_OF,
        lineage=(
            FXLineageEntry(
                source="fixture_provider",
                dataset="daily_fx_closes",
                dataset_version="provider-v7",
            ),
        ),
        as_of=AS_OF,
        maximum_staleness=datetime.timedelta(days=2),
    )


def test_valid_pit_fx_and_historical_conversion_preserve_lineage() -> None:
    governed = _govern()
    converted = governed.convert(
        1_000_000,
        source_currency="JPY",
        target_currency="USD",
        market_at=datetime.datetime(2025, 1, 30, 23, tzinfo=datetime.UTC),
        cutoff=datetime.datetime(2025, 1, 31, 12, tzinfo=datetime.UTC),
    )
    assert converted.converted_amount == pytest.approx(6450)
    assert converted.rate_market_timestamp.date() == datetime.date(2025, 1, 30)
    assert converted.fx_canonical_id == governed.metadata.canonical_id
    assert converted.fx_checksum == governed.metadata.checksum


@pytest.mark.parametrize("column", ["market_timestamp", "available_at"])
def test_future_fx_fails_closed(column: str) -> None:
    frame = _rates()
    frame.loc[0, column] = "2025-02-01T00:00:00Z"
    with pytest.raises(FXGovernanceError, match="PIT violation"):
        _govern(frame)


def test_hash_mismatch_fails() -> None:
    governed = _govern()
    tampered = governed.frame.copy()
    tampered.loc[0, "rate"] *= 2
    with pytest.raises(FXGovernanceError, match="checksum mismatch"):
        FXDataset(frame=tampered, metadata=governed.metadata)


def test_checksum_and_conversion_are_reproducible() -> None:
    first = _govern()
    second = _govern(_rates().sample(frac=1, random_state=5).reset_index(drop=True))
    assert first.metadata.checksum == second.metadata.checksum
    assert canonical_fx_checksum(first.frame) == first.metadata.checksum
    arguments = {
        "source_currency": "EUR",
        "target_currency": "USD",
        "market_at": AS_OF,
        "cutoff": AS_OF,
    }
    assert first.convert(10, **arguments) == second.convert(10, **arguments)


@pytest.mark.parametrize("value", [None, "", "US", "US12"])
def test_missing_or_invalid_currency_fails(value: object) -> None:
    frame = _rates()
    frame.loc[0, "base_currency"] = value
    with pytest.raises(FXGovernanceError, match="currency"):
        _govern(frame)


def test_invalid_pair_fails() -> None:
    with pytest.raises(FXGovernanceError, match="invalid currency pair"):
        _govern(_rates().assign(currency_pair="USD/JPY"))


def test_stale_fx_fails() -> None:
    with pytest.raises(FXGovernanceError, match="stale FX"):
        govern_fx(
            _rates(),
            source="fixture_provider",
            dataset_version="v1",
            available_at=AS_OF,
            lineage=(FXLineageEntry(source="fixture", dataset="fx", dataset_version="v1"),),
            as_of=AS_OF + datetime.timedelta(days=10),
            maximum_staleness=datetime.timedelta(days=2),
        )


def test_conversion_fails_when_only_future_or_unavailable_rate_exists() -> None:
    governed = _govern()
    with pytest.raises(FXGovernanceError, match="no PIT-safe"):
        governed.convert(
            10,
            source_currency="EUR",
            target_currency="USD",
            market_at=datetime.datetime(2025, 1, 31, 21, tzinfo=datetime.UTC),
            cutoff=datetime.datetime(2025, 1, 31, 21, 1, tzinfo=datetime.UTC),
        )


def test_provider_contract_is_generic_and_runtime_checkable() -> None:
    class FixtureProvider:
        name = "fixture"
        dataset_version = "v1"

        def fetch_fx(
            self, *, currency_pairs: set[str], as_of: datetime.datetime
        ) -> FXDataset:
            assert currency_pairs == {"JPY/USD"}
            assert as_of == AS_OF
            return _govern()

    provider = FixtureProvider()
    assert isinstance(provider, FXProvider)
    assert provider.fetch_fx(currency_pairs={"JPY/USD"}, as_of=AS_OF).metadata.source


def test_research_only_boundary_remains_explicit() -> None:
    governed = _govern()
    assert not hasattr(governed, "score")
    assert not hasattr(governed, "rank")
    assert not hasattr(governed, "execute")
