from __future__ import annotations

import datetime
import email.utils
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from data.raw_snapshots import RawSnapshotManifest, RawSnapshotStore

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_DATASET_VERSION = "sec-edgar-companyfacts-submissions-v2"
SEC_HTTP_POLICY_VERSION = "sec-fair-access-http-v2"
SEC_RETENTION_POLICY = "immutable raw response retained indefinitely pending legal review"
SUPPORTED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"})
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
REQUIRED_SUBMISSION_COLUMNS = (
    "accessionNumber", "acceptanceDateTime", "filingDate", "form",
)


class SecEdgarError(RuntimeError):
    """Fail-closed SEC ingestion failure."""


@dataclass(frozen=True)
class SecEdgarResponse:
    body: bytes
    content_type: str
    status_code: int = 200
    final_url: str = ""
    content_encoding: str = "identity"
    retry_after: str | None = None


@dataclass(frozen=True)
class SecFundamentalsResult:
    facts: pd.DataFrame
    raw_manifests: tuple[RawSnapshotManifest, ...]
    completeness_by_symbol: dict[str, str]
    provider: str = "sec_edgar"
    dataset_version: str = SEC_DATASET_VERSION
    http_policy_version: str = SEC_HTTP_POLICY_VERSION
    licensed_for_use: bool = False
    readiness_state: str = "OPEN_EXTERNAL_LEGAL_APPROVAL"
    qvm_binding_state: str = "INGESTED_NOT_QVM_BOUND"
    trade_decision: str = "NO_TRADE"
    live_execution_enabled: bool = False
    signals_generated: bool = False


Transport = Callable[[str, dict[str, str], float], SecEdgarResponse]


def _validate_sec_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "data.sec.gov" or parsed.port not in (None, 443):
        raise SecEdgarError("SEC URL must be HTTPS on data.sec.gov")
    if parsed.username or parsed.password or parsed.fragment:
        raise SecEdgarError("unsafe SEC URL")


def canonical_accession(value: object) -> str:
    """Return the unique SEC 10-2-6 accession representation."""
    if not isinstance(value, str):
        raise SecEdgarError("invalid SEC accession")
    text = value.strip()
    if re.fullmatch(r"\d{18}", text):
        digits = text
    elif re.fullmatch(r"\d{10}-\d{2}-\d{6}", text):
        digits = text.replace("-", "")
    else:
        raise SecEdgarError("invalid SEC accession")
    if digits == "0" * 18:
        raise SecEdgarError("placeholder SEC accession")
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def _valid_json_bytes(body: bytes) -> bool:
    try:
        return isinstance(json.loads(body), (dict, list))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def _bounded_decompress(body: bytes, window: int, label: str) -> bytes:
    try:
        decoder = zlib.decompressobj(window)
        decoded = decoder.decompress(body, MAX_RESPONSE_BYTES + 1)
        if decoder.unconsumed_tail or len(decoded) > MAX_RESPONSE_BYTES:
            raise SecEdgarError("SEC response exceeds maximum size")
        decoded += decoder.flush(MAX_RESPONSE_BYTES + 1 - len(decoded))
    except zlib.error as error:
        raise SecEdgarError(f"invalid {label} SEC response") from error
    if len(decoded) > MAX_RESPONSE_BYTES or not decoder.eof:
        raise SecEdgarError(
            "SEC response exceeds maximum size" if len(decoded) > MAX_RESPONSE_BYTES
            else f"invalid {label} SEC response"
        )
    return decoded


def _decode_body(body: bytes, encoding: str) -> bytes:
    normalized = encoding.strip().lower()
    if normalized in ("", "identity"):
        return body
    if normalized == "gzip":
        if body.startswith(b"\x1f\x8b"):
            return _bounded_decompress(body, zlib.MAX_WBITS | 16, "gzip")
        if _valid_json_bytes(body):
            return body  # urllib/intermediary already decoded the declared wire encoding
        raise SecEdgarError("invalid gzip SEC response")
    if normalized == "deflate":
        for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                return _bounded_decompress(body, window, "deflate")
            except SecEdgarError as error:
                if "maximum size" in str(error):
                    raise
        if _valid_json_bytes(body):
            return body
        raise SecEdgarError("invalid deflate SEC response")
    raise SecEdgarError(f"unsupported SEC Content-Encoding: {encoding}")


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> SecEdgarResponse:
    _validate_sec_url(url)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            _validate_sec_url(final_url)
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise SecEdgarError("SEC response exceeds maximum size")
            encoding = response.headers.get("Content-Encoding", "identity")
            return SecEdgarResponse(
                _decode_body(body, encoding), response.headers.get_content_type().lower(),
                response.getcode(), final_url, encoding, response.headers.get("Retry-After"),
            )
    except urllib.error.HTTPError as error:
        _validate_sec_url(error.geturl())
        body = error.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise SecEdgarError("SEC response exceeds maximum size")
        encoding = error.headers.get("Content-Encoding", "identity")
        return SecEdgarResponse(
            _decode_body(body, encoding), error.headers.get_content_type().lower(),
            error.code, error.geturl(), encoding,
            error.headers.get("Retry-After"),
        )
    except (urllib.error.URLError, TimeoutError) as error:
        raise SecEdgarError(f"SEC request failed for {url}") from error


def _taxonomy_class(taxonomy: str) -> str:
    return taxonomy if taxonomy in {"us-gaap", "ifrs-full", "dei", "srt"} else "custom/other"


@dataclass(frozen=True)
class SecEdgarFundamentalsSource:
    """Governed SEC raw-fact ingestion, deliberately not an Accounting/QVM binding."""

    user_agent: str
    raw_store: RawSnapshotStore
    transport: Transport = _default_transport
    timeout_seconds: float = 20.0
    minimum_request_interval_seconds: float = 0.11
    licensing_approved: bool = False
    max_retries: int = 2
    allow_naive_acceptance: bool = False
    clock: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(datetime.UTC)
    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    _request_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    _last_request_at: list[float | None] = field(default_factory=lambda: [None], init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not re.search(r"\S+@\S+\.\S+", self.user_agent):
            raise SecEdgarError("SEC_USER_AGENT must identify an organization and contact email")
        if "your.email@example.com" in self.user_agent.lower():
            raise SecEdgarError("placeholder SEC_USER_AGENT is forbidden")
        if self.minimum_request_interval_seconds < 0.1:
            raise SecEdgarError("SEC fair-access rate must not exceed 10 requests per second")
        if self.timeout_seconds <= 0 or not 0 <= self.max_retries <= 5:
            raise SecEdgarError("invalid bounded HTTP policy")

    def fetch(self, *, cik_by_symbol: dict[str, str], as_of: datetime.datetime) -> SecFundamentalsResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SecEdgarError("as_of must be timezone-aware")
        if not cik_by_symbol:
            raise SecEdgarError("CIK mapping is required; ticker inference is forbidden")
        cutoff = as_of.astimezone(datetime.UTC)
        rows: list[dict[str, object]] = []
        manifests: list[RawSnapshotManifest] = []
        completeness: dict[str, str] = {}
        for symbol, raw_cik in sorted(cik_by_symbol.items()):
            cik = self._canonical_cik(symbol, raw_cik)
            submissions, submission_manifest = self._json(
                f"/submissions/CIK{cik}.json", f"submissions:{cik}", cutoff)
            filings = submissions.get("filings")
            if not isinstance(filings, dict):
                raise SecEdgarError(f"SEC submissions response lacks filings for {symbol}")
            recent = filings.get("recent")
            recent_schema_valid = self._submission_columns_consistent(recent)
            if not recent_schema_valid:
                raise SecEdgarError(f"SEC recent submissions columns are inconsistent for {symbol}")
            accepted = self._acceptance_by_accession(recent)
            historical_files = filings.get("files", [])
            if not isinstance(historical_files, list):
                raise SecEdgarError(f"SEC historical submissions index is malformed for {symbol}")
            completeness[symbol.upper()] = "COMPLETE_WITHIN_SEC_REFERENCES"
            for item in historical_files:
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", name):
                    raise SecEdgarError(f"unsafe historical submissions reference for {symbol}")
                history, history_manifest = self._json(
                    f"/submissions/{name}", f"submissions-history:{cik}:{name}", cutoff)
                schema_valid = self._submission_columns_consistent(history)
                if schema_valid:
                    self._merge_accessions(accepted, self._acceptance_by_accession(history), symbol)
                if not schema_valid or not self._history_metadata_consistent(item, history):
                    completeness[symbol.upper()] = "GAPS_DETECTED"
                manifests.append(history_manifest)
            facts, facts_manifest = self._json(
                f"/api/xbrl/companyfacts/CIK{cik}.json", f"companyfacts:{cik}", cutoff)
            manifests.extend((submission_manifest, facts_manifest))
            fact_rows = self._facts(symbol.strip().upper(), facts, accepted, cutoff)
            submission_hashes = tuple(
                sorted(
                    manifest.sha256
                    for manifest in manifests
                    if manifest.resource.startswith("submissions")
                    and cik in manifest.resource
                )
            )
            for row in fact_rows:
                row["raw_snapshot_sha256"] = facts_manifest.sha256
                row["submission_snapshot_sha256"] = json.dumps(submission_hashes)
            rows.extend(fact_rows)
        if not rows:
            raise SecEdgarError("SEC returned no PIT-eligible supported fundamentals")
        return SecFundamentalsResult(
            pd.DataFrame(rows).sort_values(
                ["symbol", "taxonomy", "concept", "period_end", "available_at", "accession"],
                kind="stable", ignore_index=True), tuple(manifests), completeness,
            licensed_for_use=self.licensing_approved,
            readiness_state="INGESTED_NOT_QVM_BOUND" if self.licensing_approved else "OPEN_EXTERNAL_LEGAL_APPROVAL",
        )

    @staticmethod
    def _canonical_cik(symbol: str, raw_cik: str) -> str:
        text = str(raw_cik).strip()
        if not re.fullmatch(r"\d{1,10}", text):
            raise SecEdgarError(f"invalid CIK for {symbol}")
        cik = text.zfill(10)
        if cik == "0000000000":
            raise SecEdgarError(f"placeholder CIK for {symbol}")
        return cik

    def _throttle(self) -> None:
        with self._request_lock:
            now = self.monotonic()
            previous = self._last_request_at[0]
            if previous is not None:
                self.sleeper(max(0.0, self.minimum_request_interval_seconds - (now - previous)))
                now = self.monotonic()
            self._last_request_at[0] = now

    def _json(self, path: str, resource: str, as_of: datetime.datetime) -> tuple[dict[str, object], RawSnapshotManifest]:
        allowed = r"/(?:submissions/(?:CIK\d{10}(?:-submissions-\d{3})?\.json)|api/xbrl/companyfacts/CIK\d{10}\.json)"
        if not re.fullmatch(allowed, path):
            raise SecEdgarError("SEC resource path is not allowlisted")
        url = f"{SEC_DATA_BASE_URL}{path}"
        for attempt in range(self.max_retries + 1):
            self._throttle()
            response = self.transport(url, {
                "User-Agent": self.user_agent, "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate"}, self.timeout_seconds)
            _validate_sec_url(response.final_url or url)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise SecEdgarError("SEC response exceeds maximum size")
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                if attempt == self.max_retries:
                    raise SecEdgarError(f"SEC retry budget exhausted for {resource}")
                self.sleeper(self._retry_delay(response.retry_after, attempt))
                continue
            if response.status_code != 200:
                raise SecEdgarError(f"unexpected SEC HTTP status {response.status_code} for {resource}")
            body = _decode_body(response.body, response.content_encoding)
            if len(body) > MAX_RESPONSE_BYTES:
                raise SecEdgarError("SEC response exceeds maximum size")
            if response.content_type.lower() not in {"application/json", "application/geo+json"}:
                raise SecEdgarError(f"unexpected SEC Content-Type for {resource}")
            acquired_at = self.clock()
            if acquired_at.tzinfo is None or acquired_at.utcoffset() is None:
                raise SecEdgarError("acquisition clock must be timezone-aware")
            manifest = self.raw_store.preserve(
                provider="sec_edgar", resource=resource, request_url=url, payload=body,
                as_of=as_of, acquired_at=acquired_at, content_type=response.content_type,
                licensing_status="APPROVED" if self.licensing_approved else "PENDING_LEGAL_APPROVAL",
                retention_policy=SEC_RETENTION_POLICY)
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SecEdgarError(f"SEC returned invalid JSON for {resource}") from error
            if not isinstance(payload, dict):
                raise SecEdgarError(f"SEC returned a non-object for {resource}")
            return payload, manifest
        raise AssertionError("unreachable")

    def _retry_delay(self, retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return min(30.0, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    parsed = email.utils.parsedate_to_datetime(retry_after)
                    return min(30.0, max(0.0, (parsed - self.clock()).total_seconds()))
                except (TypeError, ValueError):
                    pass
        return float(2**attempt)

    def _acceptance_by_accession(self, payload: object) -> dict[str, datetime.datetime]:
        try:
            accessions, timestamps = payload["accessionNumber"], payload["acceptanceDateTime"]
        except (KeyError, TypeError) as error:
            raise SecEdgarError("SEC submissions response lacks acceptance chronology") from error
        if not isinstance(accessions, list) or not isinstance(timestamps, list) or len(accessions) != len(timestamps):
            raise SecEdgarError("SEC submissions columns are inconsistent")
        result: dict[str, datetime.datetime] = {}
        for accession, timestamp in zip(accessions, timestamps, strict=True):
            accession_text = canonical_accession(accession)
            if timestamp is None:
                raise SecEdgarError("invalid acceptance chronology")
            try:
                parsed = pd.Timestamp(timestamp)
            except (TypeError, ValueError) as error:
                raise SecEdgarError("invalid acceptance chronology") from error
            if pd.isna(parsed):
                raise SecEdgarError("invalid acceptance chronology")
            if parsed.tzinfo is None:
                if not self.allow_naive_acceptance:
                    raise SecEdgarError("naive acceptance timestamp is forbidden")
                parsed = parsed.tz_localize("America/New_York", ambiguous="raise", nonexistent="raise")
            normalized = parsed.tz_convert("UTC").to_pydatetime()
            if accession_text in result and result[accession_text] != normalized:
                raise SecEdgarError("conflicting duplicate accession")
            result[accession_text] = normalized
        return result

    @staticmethod
    def _submission_columns_consistent(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        columns = [payload.get(name) for name in REQUIRED_SUBMISSION_COLUMNS]
        return all(isinstance(column, list) for column in columns) and len({len(column) for column in columns}) == 1

    @staticmethod
    def _merge_accessions(target: dict[str, datetime.datetime], incoming: dict[str, datetime.datetime], symbol: str) -> None:
        for accession, accepted_at in incoming.items():
            if accession in target and target[accession] != accepted_at:
                raise SecEdgarError(f"conflicting duplicate accession for {symbol}")
            target.setdefault(accession, accepted_at)

    @staticmethod
    def _history_metadata_consistent(metadata: object, history: dict[str, object]) -> bool:
        if not isinstance(metadata, dict) or not SecEdgarFundamentalsSource._submission_columns_consistent(history):
            return False
        count = metadata.get("filingCount")
        if not isinstance(count, int) or isinstance(count, bool) or count != len(history["accessionNumber"]):
            return False
        dates = history.get("filingDate")
        filing_from, filing_to = metadata.get("filingFrom"), metadata.get("filingTo")
        if not dates:
            return count == 0 and filing_from is None and filing_to is None
        if not all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in dates):
            return False
        return filing_from == min(dates) and filing_to == max(dates)

    @staticmethod
    def _facts(symbol: str, payload: dict[str, object], accepted: dict[str, datetime.datetime], as_of: datetime.datetime) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        identities: dict[tuple[object, ...], dict[str, object]] = {}
        facts = payload.get("facts")
        if not isinstance(facts, dict):
            raise SecEdgarError(f"SEC companyfacts lacks facts for {symbol}")
        future_observed = False
        for taxonomy, concepts in facts.items():
            if not isinstance(concepts, dict):
                raise SecEdgarError(f"malformed SEC taxonomy for {symbol}")
            for concept, definition in concepts.items():
                units = definition.get("units") if isinstance(definition, dict) else None
                if not isinstance(units, dict):
                    continue
                for unit, observations in units.items():
                    if not isinstance(observations, list):
                        raise SecEdgarError(f"malformed SEC units for {symbol}/{concept}")
                    for observation in observations:
                        if not isinstance(observation, dict) or observation.get("form") not in SUPPORTED_FORMS:
                            continue
                        accession = canonical_accession(observation.get("accn"))
                        if accession not in accepted:
                            raise SecEdgarError(f"missing acceptance timestamp for {symbol}/{accession}")
                        available_at = accepted[accession]
                        if available_at > as_of:
                            future_observed = True
                            continue
                        start, end, frame = observation.get("start"), observation.get("end"), observation.get("frame")
                        identity = (taxonomy, concept, str(unit).upper(), observation.get("form"), accession, start, end, frame)
                        semantic = {"value": observation.get("val"), "fy": observation.get("fy"),
                                    "fp": observation.get("fp"), "filed": observation.get("filed")}
                        if identity in identities:
                            if identities[identity] != semantic:
                                raise SecEdgarError(f"conflicting duplicate company fact for {symbol}/{concept}")
                            continue
                        identities[identity] = semantic
                        output.append({
                            "symbol": symbol, "cik": str(payload.get("cik", "")),
                            "taxonomy": taxonomy, "taxonomy_class": _taxonomy_class(str(taxonomy)),
                            "concept": concept, "raw_concept": f"{taxonomy}:{concept}",
                            "period_type": "duration" if start else "instant",
                            "fiscal_period_start": start, "period_end": end,
                            "fiscal_year": observation.get("fy"), "fiscal_period": observation.get("fp"),
                            "form": observation.get("form"), "filed_date": observation.get("filed"),
                            "available_at": available_at, "value": observation.get("val"),
                            "unit": str(unit).upper(), "accession": accession, "frame": frame,
                            "amendment_observed": str(observation.get("form", "")).endswith("/A"),
                            "economic_mapping_eligible": taxonomy != "dei", "source": "sec_edgar",
                            "dataset_version": SEC_DATASET_VERSION, "confidence": None,
                            "qvm_binding_state": "INGESTED_NOT_QVM_BOUND",
                        })
        if future_observed and not output:
            raise SecEdgarError("only future acceptance observations exist at cutoff")
        return output
