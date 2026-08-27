from __future__ import annotations

import datetime
import json

import pytest

from data.connectors.sec_edgar import SecEdgarError, SecEdgarFundamentalsSource, SecEdgarResponse
from data.raw_snapshots import RawSnapshotError, RawSnapshotStore

NOW = datetime.datetime(2026, 8, 25, 20, 0, tzinfo=datetime.UTC)


def _payloads(*, accepted="2026-02-01T16:00:00.000Z", files=None):
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-26-000001"],
                "acceptanceDateTime": [accepted],
                "filingDate": ["2026-02-01"],
                "form": ["10-K"],
            },
            "files": [] if files is None else files,
        }
    }
    companyfacts = {
        "cik": 1,
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [{
            "start": "2025-10-01", "end": "2025-12-31", "val": 100,
            "accn": "0000000001-26-000001", "fy": 2025, "fp": "FY", "form": "10-K",
            "filed": "2026-02-01", "frame": "CY2025Q4",
        }]}}}},
    }
    return submissions, companyfacts


def _source(tmp_path, submissions, facts, history=None):
    def transport(url, headers, timeout):
        assert "research@example.org" in headers["User-Agent"]
        if "submissions-001" in url:
            body = history
        else:
            body = submissions if "/submissions/" in url else facts
        return SecEdgarResponse(json.dumps(body).encode(), "application/json")
    return SecEdgarFundamentalsSource(
        user_agent="Trading research@example.org",
        raw_store=RawSnapshotStore(tmp_path),
        transport=transport,
    )


def test_real_sec_ingestion_preserves_raw_and_acceptance_time(tmp_path):
    submissions, facts = _payloads()
    result = _source(tmp_path, submissions, facts).fetch(cik_by_symbol={"abc": "1"}, as_of=NOW)
    row = result.facts.iloc[0]
    assert row["symbol"] == "ABC"
    assert row["raw_concept"] == "us-gaap:Revenues"
    assert row["available_at"] == datetime.datetime(2026, 2, 1, 16, tzinfo=datetime.UTC)
    assert row["confidence"] is None
    assert result.licensed_for_use is False
    assert result.readiness_state == "OPEN_EXTERNAL_LEGAL_APPROVAL"
    assert len(result.raw_manifests) == 2
    for path in tmp_path.rglob("acquisitions/*.json"):
        RawSnapshotStore.verify(path)


def test_future_filing_is_not_visible_and_no_data_fails_closed(tmp_path):
    submissions, facts = _payloads(accepted="2027-02-01T16:00:00.000Z")
    with pytest.raises(SecEdgarError, match="only future acceptance"):
        _source(tmp_path, submissions, facts).fetch(cik_by_symbol={"ABC": "1"}, as_of=NOW)


def test_missing_acceptance_timestamp_fails_closed(tmp_path):
    submissions, facts = _payloads()
    for column in ("accessionNumber", "acceptanceDateTime", "filingDate", "form"):
        submissions["filings"]["recent"][column] = []
    with pytest.raises(SecEdgarError, match="missing acceptance timestamp"):
        _source(tmp_path, submissions, facts).fetch(cik_by_symbol={"ABC": "1"}, as_of=NOW)


def test_historical_submission_files_are_fetched_and_preserved(tmp_path):
    submissions, facts = _payloads(files=[{"name": "CIK0000000001-submissions-001.json"}])
    history = {column: [] for column in (
        "accessionNumber", "acceptanceDateTime", "filingDate", "form"
    )}
    result = _source(tmp_path, submissions, facts, history).fetch(
        cik_by_symbol={"ABC": "1"}, as_of=NOW
    )
    assert len(result.raw_manifests) == 3


def test_recent_history_duplicate_canonical_accession_is_rejected(tmp_path):
    metadata = {
        "name": "CIK0000000001-submissions-001.json", "filingCount": 1,
        "filingFrom": "2025-01-01", "filingTo": "2025-01-01",
    }
    submissions, facts = _payloads(files=[metadata])
    recent = submissions["filings"]["recent"]
    recent["accessionNumber"] = ["000000000126000001"]
    history = {
        "accessionNumber": ["0000000001-26-000001"],
        "acceptanceDateTime": recent["acceptanceDateTime"],
        "filingDate": ["2025-01-01"], "form": ["10-K"],
    }
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["accn"] = "000000000126000001"
    with pytest.raises(SecEdgarError, match="duplicate accession across"):
        _source(tmp_path, submissions, facts, history).fetch(
            cik_by_symbol={"ABC": "1"}, as_of=NOW
        )


@pytest.mark.parametrize("column", ["filingDate", "acceptanceDateTime", "form"])
def test_truncated_history_is_gaps_detected(tmp_path, column):
    metadata = {
        "name": "CIK0000000001-submissions-001.json", "filingCount": 1,
        "filingFrom": "2025-01-01", "filingTo": "2025-01-01",
    }
    submissions, facts = _payloads(files=[metadata])
    history = {
        "accessionNumber": ["0000000001-25-000001"],
        "acceptanceDateTime": ["2025-01-02T00:00:00Z"],
        "filingDate": ["2025-01-01"], "form": ["10-K"],
    }
    history[column] = []
    result = _source(tmp_path, submissions, facts, history).fetch(
        cik_by_symbol={"ABC": "1"}, as_of=NOW
    )
    assert result.completeness_by_symbol == {"ABC": "GAPS_DETECTED"}


def test_unsafe_historical_submission_reference_is_rejected(tmp_path):
    submissions, facts = _payloads(files=[{"name": "../escape.json"}])
    with pytest.raises(SecEdgarError, match="unsafe historical"):
        _source(tmp_path, submissions, facts).fetch(cik_by_symbol={"ABC": "1"}, as_of=NOW)


def test_placeholder_identity_and_excess_rate_are_rejected(tmp_path):
    with pytest.raises(SecEdgarError, match="placeholder"):
        SecEdgarFundamentalsSource("Your Name your.email@example.com", RawSnapshotStore(tmp_path))
    with pytest.raises(SecEdgarError, match="10 requests"):
        SecEdgarFundamentalsSource(
            "Trading research@example.org", RawSnapshotStore(tmp_path),
            minimum_request_interval_seconds=0.01,
        )


def test_raw_snapshot_tampering_is_detected(tmp_path):
    store = RawSnapshotStore(tmp_path)
    store.preserve(
        provider="sec", resource="x", request_url="https://example.test/x", payload=b"{}",
        fetched_at=NOW, content_type="application/json",
        licensing_status="PENDING_LEGAL_APPROVAL", retention_policy="retain",
    )
    manifest_path = next(tmp_path.rglob("acquisitions/*.json"))
    manifest = RawSnapshotStore.verify(manifest_path)
    (manifest_path.parent / manifest.payload_file).resolve().write_bytes(b"tampered")
    with pytest.raises(RawSnapshotError, match="mismatch"):
        store.verify(manifest_path)
