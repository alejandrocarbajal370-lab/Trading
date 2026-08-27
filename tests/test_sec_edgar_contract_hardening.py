from __future__ import annotations

import datetime
import gzip
import io
import json
import urllib.error
import zlib
from email.message import Message

import pytest

import data.connectors.sec_edgar as sec
import data.raw_snapshots as raw
from data.raw_snapshots import RawSnapshotStore

NOW = datetime.datetime(2026, 8, 25, 20, tzinfo=datetime.UTC)
ACC_A = "0000000001-26-000001"
ACC_B = "0000000001-26-000002"


class Response:
    def __init__(self, body, *, encoding="identity", url="https://data.sec.gov/x", content_type="application/json"):
        self.body, self.url, self.code = body, url, 200
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Encoding"] = encoding

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size): return self.body
    def geturl(self): return self.url
    def getcode(self): return self.code


@pytest.mark.parametrize("encoding,encoded", [
    ("gzip", gzip.compress(b'{"ok":true}')),
    ("deflate", zlib.compress(b'{"ok":true}')),
    ("gzip", b'{"ok":true}'),  # already decoded by an intermediary
])
def test_default_transport_decodes_supported_content_encoding(monkeypatch, encoding, encoded):
    monkeypatch.setattr(sec.urllib.request, "urlopen", lambda *args, **kwargs: Response(encoded, encoding=encoding))
    result = sec._default_transport("https://data.sec.gov/x", {"User-Agent": "A a@b.co"}, 2)
    assert json.loads(result.body) == {"ok": True}


def test_default_transport_rejects_redirect_off_host_and_oversize(monkeypatch):
    monkeypatch.setattr(sec.urllib.request, "urlopen", lambda *a, **k: Response(b"{}", url="https://evil.test/x"))
    with pytest.raises(sec.SecEdgarError, match="data.sec.gov"):
        sec._default_transport("https://data.sec.gov/x", {}, 2)


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_declared_encoding_rejects_invalid_bytes(monkeypatch, encoding):
    monkeypatch.setattr(
        sec.urllib.request, "urlopen", lambda *a, **k: Response(b"not-json", encoding=encoding)
    )
    with pytest.raises(sec.SecEdgarError, match=f"invalid {encoding}"):
        sec._default_transport("https://data.sec.gov/x", {}, 2)
    monkeypatch.setattr(sec.urllib.request, "urlopen", lambda *a, **k: Response(b"x" * (sec.MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(sec.SecEdgarError, match="maximum size"):
        sec._default_transport("https://data.sec.gov/x", {}, 2)


def _source(tmp_path, transport, **kwargs):
    return sec.SecEdgarFundamentalsSource(
        "Trading research@example.org", RawSnapshotStore(tmp_path), transport=transport,
        clock=lambda: NOW + datetime.timedelta(days=1), **kwargs)


def test_every_request_is_throttled_including_retries(tmp_path):
    ticks = [0.0]
    calls, sleeps = [], []
    def monotonic(): return ticks[0]
    def sleeper(delay): sleeps.append(delay); ticks[0] += delay
    def transport(url, headers, timeout):
        calls.append(url)
        return sec.SecEdgarResponse(b"{}", "application/json", 429, url, retry_after="2")
    source = _source(tmp_path, transport, max_retries=2, monotonic=monotonic, sleeper=sleeper)
    with pytest.raises(sec.SecEdgarError, match="retry budget"):
        source._json("/submissions/CIK0000320193.json", "x", NOW)
    assert len(calls) == 3
    assert sleeps == [2.0, pytest.approx(0.0), 2.0, pytest.approx(0.0)]


def test_compressed_retry_response_is_decoded_bounded_and_keeps_retry_policy(tmp_path):
    ticks = [0.0]
    sleeps = []
    def monotonic(): return ticks[0]
    def sleeper(delay): sleeps.append(delay); ticks[0] += delay
    url = "https://data.sec.gov/submissions/CIK0000320193.json"
    source = _source(
        tmp_path,
        lambda *a: sec.SecEdgarResponse(
            gzip.compress(b'{"error":"slow down"}'), "application/json", 429, url,
            "gzip", "3",
        ),
        max_retries=1, monotonic=monotonic, sleeper=sleeper,
    )
    with pytest.raises(sec.SecEdgarError, match="retry budget"):
        source._json("/submissions/CIK0000320193.json", "x", NOW)
    assert sleeps == [3.0, pytest.approx(0.0)]


def test_compressed_oversized_http_error_is_rejected(monkeypatch):
    compressed = gzip.compress(b"x" * (sec.MAX_RESPONSE_BYTES + 1))
    headers = Message()
    headers["Content-Type"] = "application/json"
    headers["Content-Encoding"] = "gzip"
    error = urllib.error.HTTPError(
        "https://data.sec.gov/x", 500, "error", headers, io.BytesIO(compressed)
    )
    monkeypatch.setattr(sec.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
    with pytest.raises(sec.SecEdgarError, match="maximum size"):
        sec._default_transport("https://data.sec.gov/x", {}, 2)


@pytest.mark.parametrize("timestamp,message", [
    (None, "invalid acceptance"), ("not-a-date", "invalid acceptance"),
    ("2026-01-01T12:00:00", "naive acceptance"),
])
def test_acceptance_chronology_fails_closed(tmp_path, timestamp, message):
    source = _source(tmp_path, lambda *a: sec.SecEdgarResponse(b"{}", "application/json"))
    with pytest.raises(sec.SecEdgarError, match=message):
        source._acceptance_by_accession({"accessionNumber": [ACC_A], "acceptanceDateTime": [timestamp]})


def test_accession_duplicates_identical_and_conflicting_fail(tmp_path):
    source = _source(tmp_path, lambda *a: sec.SecEdgarResponse(b"{}", "application/json"))
    payload = {"accessionNumber": [ACC_A, ACC_A.replace("-", "")], "acceptanceDateTime": [
        "2026-01-01T12:00:00Z", "2026-01-01T12:00:00Z"]}
    with pytest.raises(sec.SecEdgarError, match="duplicate accession"):
        source._acceptance_by_accession(payload)
    payload["acceptanceDateTime"][1] = "2026-01-02T12:00:00Z"
    with pytest.raises(sec.SecEdgarError, match="duplicate accession"):
        source._acceptance_by_accession(payload)


def test_accession_merge_rejects_duplicate_across_recent_and_history():
    target = {ACC_A: NOW}
    with pytest.raises(sec.SecEdgarError, match="across SEC submission resources"):
        sec.SecEdgarFundamentalsSource._merge_accessions(target, {ACC_A: NOW}, "X")


def test_unique_accession_reordering_preserves_index(tmp_path):
    source = _source(tmp_path, lambda *a: sec.SecEdgarResponse(b"{}", "application/json"))
    left = {"accessionNumber": [ACC_A, ACC_B], "acceptanceDateTime": [NOW.isoformat(), (NOW - datetime.timedelta(days=1)).isoformat()]}
    right = {key: list(reversed(value)) for key, value in left.items()}
    assert source._acceptance_by_accession(left) == source._acceptance_by_accession(right)


@pytest.mark.parametrize("value", ["", "abc", "0001-26-000001", "0" * 18, None])
def test_accession_rejects_malformed_and_placeholders(value):
    with pytest.raises(sec.SecEdgarError, match="accession"):
        sec.canonical_accession(value)


def test_accession_formats_share_one_canonical_identity():
    assert sec.canonical_accession(ACC_A) == sec.canonical_accession(ACC_A.replace("-", ""))


def test_cik_canonicalization_and_placeholder_policy():
    assert sec.SecEdgarFundamentalsSource._canonical_cik("BABA", "1577552") == "0001577552"
    with pytest.raises(sec.SecEdgarError, match="placeholder"):
        sec.SecEdgarFundamentalsSource._canonical_cik("X", "0")


def test_raw_refetch_reuses_content_but_records_distinct_acquisitions(tmp_path):
    store = RawSnapshotStore(tmp_path)
    common = {"provider": "sec", "resource": "x", "request_url": "https://data.sec.gov/x",
              "payload": b"{}", "content_type": "application/json",
              "licensing_status": "PENDING_LEGAL_APPROVAL", "retention_policy": "retain",
              "as_of": NOW}
    first = store.preserve(**common, acquired_at=NOW)
    second = store.preserve(**common, acquired_at=NOW + datetime.timedelta(seconds=1))
    assert first.sha256 == second.sha256
    assert first.acquisition_id != second.acquisition_id
    assert first.as_of == second.as_of and first.acquired_at != second.acquired_at
    assert len(list(tmp_path.rglob("content/*/*/payload.json"))) == 1
    assert len(list(tmp_path.rglob("acquisitions/*.json"))) == 2


def test_raw_publication_failure_cleans_files_created_by_attempt(tmp_path, monkeypatch):
    store = RawSnapshotStore(tmp_path)
    monkeypatch.setattr(
        raw.RawSnapshotStore, "verify", staticmethod(
            lambda _: (_ for _ in ()).throw(raw.RawSnapshotError("verification failed"))
        )
    )
    with pytest.raises(raw.RawSnapshotError, match="verification failed"):
        store.preserve(
            provider="sec", resource="x", request_url="https://data.sec.gov/x",
            payload=b"{}", content_type="application/json",
            licensing_status="PENDING_LEGAL_APPROVAL", retention_policy="retain",
            as_of=NOW, acquired_at=NOW,
        )
    assert not list(tmp_path.rglob("*.json"))


def test_fact_identity_dedupes_only_equivalent_and_preserves_context():
    accepted = {ACC_A: NOW - datetime.timedelta(days=1)}
    base = {"end": "2025-12-31", "val": 1, "accn": ACC_A.replace("-", ""), "form": "10-K", "filed": "2026-01-01"}
    payload = {"cik": 1, "facts": {"us-gaap": {"Assets": {"units": {"USD": [base, dict(base)]}}}}}
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][1]["accn"] = ACC_A
    rows = sec.SecEdgarFundamentalsSource._facts("X", payload, accepted, NOW)
    assert len(rows) == 1 and rows[0]["period_type"] == "instant" and rows[0]["confidence"] is None
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][1]["val"] = 2
    with pytest.raises(sec.SecEdgarError, match="conflicting duplicate company fact"):
        sec.SecEdgarFundamentalsSource._facts("X", payload, accepted, NOW)


def test_dei_never_becomes_economic_fact_and_amendment_is_not_materiality():
    accepted = {ACC_A: NOW}
    fact = {"end": "2025-12-31", "val": "X", "accn": ACC_A, "form": "10-K/A", "filed": "2026-01-01"}
    payload = {"cik": 1, "facts": {"dei": {"EntityRegistrantName": {"units": {"pure": [fact]}}}}}
    row = sec.SecEdgarFundamentalsSource._facts("X", payload, accepted, NOW)[0]
    assert row["taxonomy_class"] == "dei"
    assert row["economic_mapping_eligible"] is False
    assert row["amendment_observed"] is True
    assert row["qvm_binding_state"] == "INGESTED_NOT_QVM_BOUND"
    assert "material" not in row


def test_mixed_valid_and_future_facts_excludes_only_future():
    accepted = {ACC_A: NOW, ACC_B: NOW + datetime.timedelta(seconds=1)}
    facts = [{"end": "2025-12-31", "val": 1, "accn": accession, "form": "10-K",
              "filed": "2026-01-01"} for accession in accepted]
    payload = {"cik": 1, "facts": {"us-gaap": {"Assets": {"units": {"USD": facts}}}}}
    rows = sec.SecEdgarFundamentalsSource._facts("X", payload, accepted, NOW)
    assert [row["accession"] for row in rows] == [ACC_A]
    assert rows[0]["available_at"] == NOW  # exact boundary is visible


@pytest.mark.parametrize("status", [500, 503])
def test_5xx_retries_are_bounded(tmp_path, status):
    calls = []
    def transport(url, headers, timeout):
        calls.append(url)
        return sec.SecEdgarResponse(b"{}", "application/json", status, url)
    source = _source(tmp_path, transport, max_retries=1, sleeper=lambda _: None)
    with pytest.raises(sec.SecEdgarError, match="retry budget"):
        source._json("/submissions/CIK0000320193.json", "x", NOW)
    assert len(calls) == 2


def test_invalid_media_type_fails_before_preservation(tmp_path):
    url = "https://data.sec.gov/submissions/CIK0000320193.json"
    source = _source(tmp_path, lambda *a: sec.SecEdgarResponse(b"<html>", "text/html", 200, url))
    with pytest.raises(sec.SecEdgarError, match="Content-Type"):
        source._json("/submissions/CIK0000320193.json", "x", NOW)
    assert not list(tmp_path.rglob("*.json"))


def test_history_metadata_reports_count_and_date_gaps():
    metadata = {"filingCount": 2, "filingFrom": "2025-01-01", "filingTo": "2025-02-01"}
    history = {
        "accessionNumber": [ACC_A, ACC_B],
        "acceptanceDateTime": ["2025-01-02T00:00:00Z", "2025-02-02T00:00:00Z"],
        "filingDate": ["2025-01-01", "2025-02-01"],
        "form": ["10-K", "10-Q"],
    }
    assert sec.SecEdgarFundamentalsSource._history_metadata_consistent(metadata, history)
    metadata["filingCount"] = 3
    assert not sec.SecEdgarFundamentalsSource._history_metadata_consistent(metadata, history)


@pytest.mark.parametrize("column", ["filingDate", "acceptanceDateTime", "form"])
def test_submission_schema_truncation_never_validates(column):
    history = {
        "accessionNumber": [ACC_A, ACC_B],
        "acceptanceDateTime": ["2025-01-02T00:00:00Z", "2025-02-02T00:00:00Z"],
        "filingDate": ["2025-01-01", "2025-02-01"],
        "form": ["10-K", "10-Q"],
    }
    history[column] = history[column][:-1]
    assert not sec.SecEdgarFundamentalsSource._submission_columns_consistent(history)


def test_submission_missing_column_and_date_bounds_never_validate():
    history = {
        "accessionNumber": [ACC_A], "acceptanceDateTime": ["2025-01-02T00:00:00Z"],
        "filingDate": ["2025-01-01"], "form": ["10-K"],
    }
    assert not sec.SecEdgarFundamentalsSource._submission_columns_consistent(
        {key: value for key, value in history.items() if key != "form"}
    )
    metadata = {"filingCount": 1, "filingFrom": "2024-01-01", "filingTo": "2025-01-01"}
    assert not sec.SecEdgarFundamentalsSource._history_metadata_consistent(metadata, history)
