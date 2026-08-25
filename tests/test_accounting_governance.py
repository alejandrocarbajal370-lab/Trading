from __future__ import annotations

import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from fundamentals.governance import (
    AccountingDataset,
    AccountingGovernanceError,
    AccountingLineageEntry,
    AccountingMetadata,
    AccountingProvider,
    FinancialFact,
    MissingFundamentalsPolicy,
    canonical_accounting_checksum,
    govern_accounting,
)

AS_OF = datetime.datetime(2025, 9, 1, tzinfo=datetime.UTC)
SOURCE = "fixture_filings"
VERSION = "fixture-2025-09-v1"


def _facts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fact_id": "ACME:revenue:FY2024",
                "entity": "ACME",
                "metric": "revenue",
                "fiscal_period": "FY2024",
                "period_end": "2024-12-31",
                "filing_date": "2025-02-15T14:00:00Z",
                "available_at": "2025-02-15T14:05:00Z",
                "value": 100.0,
                "unit": "USD",
                "source": SOURCE,
                "dataset_version": VERSION,
                "revision": 0,
                "revision_type": "ORIGINAL",
                "supersedes_revision": None,
            },
            {
                "fact_id": "ACME:revenue:FY2024",
                "entity": "ACME",
                "metric": "revenue",
                "fiscal_period": "FY2024",
                "period_end": "2024-12-31",
                "filing_date": "2025-08-15T14:00:00Z",
                "available_at": "2025-08-15T14:05:00Z",
                "value": 105.0,
                "unit": "USD",
                "source": SOURCE,
                "dataset_version": VERSION,
                "revision": 1,
                "revision_type": "RESTATEMENT",
                "supersedes_revision": 0,
            },
            {
                "fact_id": "ACME:assets:Q2-2025",
                "entity": "ACME",
                "metric": "assets",
                "fiscal_period": "Q2-2025",
                "period_end": "2025-06-30",
                "filing_date": "2025-07-30T14:00:00Z",
                "available_at": "2025-07-30T14:02:00Z",
                "value": 220.0,
                "unit": "USD",
                "source": SOURCE,
                "dataset_version": VERSION,
                "revision": 0,
                "revision_type": "ORIGINAL",
                "supersedes_revision": None,
            },
        ]
    )


def _govern(frame: pd.DataFrame | None = None) -> AccountingDataset:
    return govern_accounting(
        _facts() if frame is None else frame,
        source=SOURCE,
        dataset_version=VERSION,
        available_at=AS_OF,
        lineage=(
            AccountingLineageEntry(
                source=SOURCE,
                dataset="regulatory_filings",
                dataset_version="provider-export-7",
                transformation="normalized-without-revision-collapse",
            ),
        ),
        as_of=AS_OF,
    )


def test_valid_pit_accounting_contract_and_snapshot() -> None:
    governed = _govern()
    snapshot = governed.snapshot(cutoff=AS_OF, required={("ACME", "revenue")})
    revenue = snapshot.loc[snapshot["metric"] == "revenue"].iloc[0]
    assert revenue["value"] == 105.0
    assert revenue["revision_type"] == "RESTATEMENT"
    assert governed.metadata.contract_version == "accounting-pit-governance-v1"
    assert governed.metadata.lineage[0].dataset == "regulatory_filings"


def test_typed_financial_fact_rejects_naive_availability() -> None:
    payload = _facts().iloc[0].to_dict()
    payload["available_at"] = datetime.datetime(2025, 2, 15, 14, 5, tzinfo=datetime.UTC).replace(
        tzinfo=None
    )
    with pytest.raises(ValidationError, match="timezone-aware"):
        FinancialFact.model_validate(payload)


@pytest.mark.parametrize("column", ["filing_date", "available_at"])
def test_future_accounting_data_fails_closed(column: str) -> None:
    frame = _facts()
    frame.loc[0, column] = "2025-09-02T00:00:00Z"
    with pytest.raises(AccountingGovernanceError, match="PIT violation"):
        _govern(frame)


def test_available_at_before_filing_fails() -> None:
    frame = _facts()
    frame.loc[0, "available_at"] = "2025-02-14T00:00:00Z"
    with pytest.raises(AccountingGovernanceError, match="available_at precedes"):
        _govern(frame)


def test_restatement_does_not_rewrite_historical_snapshot() -> None:
    governed = _govern()
    before = governed.snapshot(cutoff=datetime.datetime(2025, 3, 1, tzinfo=datetime.UTC))
    after = governed.snapshot(cutoff=AS_OF)
    assert before.loc[before["metric"] == "revenue", "value"].tolist() == [100.0]
    assert before.loc[before["metric"] == "revenue", "revision"].tolist() == [0]
    assert after.loc[after["metric"] == "revenue", "value"].tolist() == [105.0]
    assert len(governed.frame.loc[governed.frame["metric"] == "revenue"]) == 2


def test_snapshot_selection_is_temporal_even_when_input_rows_are_reverse_revision_order() -> None:
    frame = _facts().iloc[[1, 0, 2]].reset_index(drop=True)
    governed = _govern(frame)

    before_restatement = governed.snapshot(
        cutoff=datetime.datetime(2025, 3, 1, tzinfo=datetime.UTC)
    )
    after_restatement = governed.snapshot(cutoff=AS_OF)

    assert before_restatement.loc[
        before_restatement["metric"] == "revenue", "revision"
    ].tolist() == [0]
    assert after_restatement.loc[after_restatement["metric"] == "revenue", "revision"].tolist() == [
        1
    ]


def test_revision_order_diverging_from_availability_fails_closed() -> None:
    frame = _facts()
    frame.loc[1, "filing_date"] = "2025-02-14T14:00:00Z"
    frame.loc[1, "available_at"] = "2025-02-14T14:05:00Z"
    with pytest.raises(AccountingGovernanceError, match="revision mismatch"):
        _govern(frame)


def test_restatement_unit_change_fails_closed() -> None:
    frame = _facts()
    frame.loc[1, "unit"] = "EUR"
    with pytest.raises(AccountingGovernanceError, match="revision mismatch"):
        _govern(frame)


def test_restatement_filing_date_must_be_monotonic() -> None:
    frame = _facts()
    frame.loc[1, "filing_date"] = "2025-02-14T14:00:00Z"
    frame.loc[1, "available_at"] = "2025-08-15T14:05:00Z"
    with pytest.raises(AccountingGovernanceError, match="revision mismatch"):
        _govern(frame)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda frame: frame.assign(revision=[0, 2, 0]),
        lambda frame: frame.assign(supersedes_revision=[None, 7, None]),
        lambda frame: frame.assign(revision_type=["ORIGINAL", "ORIGINAL", "ORIGINAL"]),
        lambda frame: frame.assign(fact_id=["a", "b", "c"]),
    ],
)
def test_revision_mismatch_fails(mutation) -> None:
    with pytest.raises(AccountingGovernanceError, match="revision mismatch"):
        _govern(mutation(_facts()))


def test_duplicate_facts_fail() -> None:
    frame = pd.concat([_facts(), _facts().iloc[[0]]], ignore_index=True)
    with pytest.raises(AccountingGovernanceError, match="duplicate facts"):
        _govern(frame)


def test_checksum_mismatch_detects_silent_history_mutation() -> None:
    governed = _govern()
    tampered = governed.frame.copy()
    tampered.loc[0, "value"] = 999
    with pytest.raises(AccountingGovernanceError, match="checksum mismatch"):
        AccountingDataset(frame=tampered, metadata=governed.metadata)


def test_checksum_and_identity_are_reproducible_across_row_order() -> None:
    first = _govern()
    second = _govern(_facts().sample(frac=1, random_state=11).reset_index(drop=True))
    assert first.metadata.checksum == second.metadata.checksum
    assert first.metadata.canonical_id == second.metadata.canonical_id
    assert canonical_accounting_checksum(first.frame) == first.metadata.checksum


def test_missing_fundamentals_fail_or_are_allowed_according_to_policy() -> None:
    governed = _govern()
    required = {("ACME", "revenue"), ("ACME", "cash_flow")}
    with pytest.raises(AccountingGovernanceError, match="missing fundamentals"):
        governed.snapshot(cutoff=AS_OF, required=required)

    allowed = govern_accounting(
        _facts(),
        source=SOURCE,
        dataset_version=VERSION,
        available_at=AS_OF,
        lineage=(AccountingLineageEntry(source=SOURCE, dataset="filings", dataset_version="v7"),),
        as_of=AS_OF,
        missing_policy=MissingFundamentalsPolicy(action="ALLOW"),
    )
    assert len(allowed.snapshot(cutoff=AS_OF, required=required)) == 2


def test_provider_source_and_dataset_contract() -> None:
    class FixtureProvider:
        name = SOURCE
        dataset_version = VERSION

        def fetch_accounting(
            self, *, entities: set[str], as_of: datetime.datetime
        ) -> AccountingDataset:
            assert entities == {"ACME"}
            assert as_of == AS_OF
            return _govern()

    provider = FixtureProvider()
    assert isinstance(provider, AccountingProvider)
    assert provider.fetch_accounting(entities={"ACME"}, as_of=AS_OF).metadata.source == SOURCE

    frame = _facts()
    frame.loc[0, "source"] = "other"
    with pytest.raises(AccountingGovernanceError, match="provider/source contract"):
        _govern(frame)


def test_metadata_rejects_unverifiable_lineage_and_unknown_fields() -> None:
    governed = _govern()
    payload = governed.metadata.model_dump()
    payload["lineage"] = ()
    payload["score"] = 1
    with pytest.raises(ValidationError):
        AccountingMetadata.model_validate(payload)


def test_research_only_boundary_remains_explicit() -> None:
    governed = _govern()
    assert not hasattr(governed, "score")
    assert not hasattr(governed, "rank")
    assert not hasattr(governed, "weights")
    assert not hasattr(governed, "execute")
