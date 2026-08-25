from __future__ import annotations

import datetime
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from data.raw_snapshots import RawSnapshotManifest, RawSnapshotStore

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_DATASET_VERSION = "sec-edgar-companyfacts-submissions-v1"
SEC_RETENTION_POLICY = "immutable raw response retained indefinitely pending legal review"
SUPPORTED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A"})


class SecEdgarError(RuntimeError):
    """Fail-closed SEC ingestion failure."""


@dataclass(frozen=True)
class SecEdgarResponse:
    body: bytes
    content_type: str


@dataclass(frozen=True)
class SecFundamentalsResult:
    facts: pd.DataFrame
    raw_manifests: tuple[RawSnapshotManifest, ...]
    provider: str = "sec_edgar"
    dataset_version: str = SEC_DATASET_VERSION
    licensed_for_use: bool = False
    readiness_state: str = "OPEN_EXTERNAL_LEGAL_APPROVAL"
    trade_decision: str = "NO_TRADE"
    live_execution_enabled: bool = False
    signals_generated: bool = False


Transport = Callable[[str, dict[str, str], float], SecEdgarResponse]


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> SecEdgarResponse:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return SecEdgarResponse(
                body=response.read(),
                content_type=response.headers.get_content_type(),
            )
    except (urllib.error.URLError, TimeoutError) as error:
        raise SecEdgarError(f"SEC request failed for {url}") from error


@dataclass(frozen=True)
class SecEdgarFundamentalsSource:
    """Real SEC Company Facts ingestion with accession acceptance-time PIT joins."""

    user_agent: str
    raw_store: RawSnapshotStore
    transport: Transport = _default_transport
    timeout_seconds: float = 20.0
    minimum_request_interval_seconds: float = 0.11
    licensing_approved: bool = False

    def __post_init__(self) -> None:
        if not re.search(r"\S+@\S+\.\S+", self.user_agent):
            raise SecEdgarError("SEC_USER_AGENT must identify an organization and contact email")
        if "your.email@example.com" in self.user_agent.lower():
            raise SecEdgarError("placeholder SEC_USER_AGENT is forbidden")
        if self.minimum_request_interval_seconds < 0.1:
            raise SecEdgarError("SEC fair-access rate must not exceed 10 requests per second")

    def fetch(self, *, cik_by_symbol: dict[str, str], as_of: datetime.datetime) -> SecFundamentalsResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SecEdgarError("as_of must be timezone-aware")
        if not cik_by_symbol:
            raise SecEdgarError("CIK mapping is required; ticker inference is forbidden")
        rows: list[dict[str, object]] = []
        manifests: list[RawSnapshotManifest] = []
        for position, (symbol, raw_cik) in enumerate(sorted(cik_by_symbol.items())):
            cik = str(raw_cik).strip().zfill(10)
            if not re.fullmatch(r"\d{10}", cik):
                raise SecEdgarError(f"invalid CIK for {symbol}")
            submissions, submission_manifest = self._json(
                f"/submissions/CIK{cik}.json", f"submissions:{cik}", as_of
            )
            filings = submissions.get("filings")
            if not isinstance(filings, dict):
                raise SecEdgarError(f"SEC submissions response lacks filings for {symbol}")
            accepted = self._acceptance_by_accession(submissions)
            historical_files = filings.get("files", [])
            if not isinstance(historical_files, list):
                raise SecEdgarError(f"SEC historical submissions index is malformed for {symbol}")
            for item in historical_files:
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", name):
                    raise SecEdgarError(f"unsafe historical submissions reference for {symbol}")
                history, history_manifest = self._json(
                    f"/submissions/{name}", f"submissions-history:{cik}:{name}", as_of
                )
                overlap = set(accepted) & set(self._acceptance_by_accession(history))
                if overlap:
                    raise SecEdgarError(f"duplicate accession across SEC submission files for {symbol}")
                accepted.update(self._acceptance_by_accession(history))
                manifests.append(history_manifest)
            facts, facts_manifest = self._json(
                f"/api/xbrl/companyfacts/CIK{cik}.json", f"companyfacts:{cik}", as_of
            )
            manifests.extend((submission_manifest, facts_manifest))
            rows.extend(self._facts(symbol.strip().upper(), facts, accepted, as_of))
            if position + 1 < len(cik_by_symbol):
                time.sleep(self.minimum_request_interval_seconds)
        if not rows:
            raise SecEdgarError("SEC returned no PIT-eligible supported fundamentals")
        return SecFundamentalsResult(
            facts=pd.DataFrame(rows).sort_values(
                ["symbol", "raw_concept", "period_end", "available_at", "accession"],
                kind="stable",
                ignore_index=True,
            ),
            raw_manifests=tuple(manifests),
            licensed_for_use=self.licensing_approved,
            readiness_state=("INGESTED_NOT_QVM_BOUND" if self.licensing_approved else "OPEN_EXTERNAL_LEGAL_APPROVAL"),
        )

    def _json(self, path: str, resource: str, fetched_at: datetime.datetime) -> tuple[dict[str, object], RawSnapshotManifest]:
        url = f"{SEC_DATA_BASE_URL}{path}"
        response = self.transport(
            url,
            {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"},
            self.timeout_seconds,
        )
        manifest = self.raw_store.preserve(
            provider="sec_edgar",
            resource=resource,
            request_url=url,
            payload=response.body,
            fetched_at=fetched_at,
            content_type=response.content_type,
            licensing_status="APPROVED" if self.licensing_approved else "PENDING_LEGAL_APPROVAL",
            retention_policy=SEC_RETENTION_POLICY,
        )
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SecEdgarError(f"SEC returned invalid JSON for {resource}") from error
        if not isinstance(payload, dict):
            raise SecEdgarError(f"SEC returned a non-object for {resource}")
        return payload, manifest

    @staticmethod
    def _acceptance_by_accession(payload: dict[str, object]) -> dict[str, datetime.datetime]:
        try:
            filings = payload.get("filings")
            recent = filings["recent"] if isinstance(filings, dict) else payload
            accessions = recent["accessionNumber"]
            timestamps = recent["acceptanceDateTime"]
        except (KeyError, TypeError) as error:
            raise SecEdgarError("SEC submissions response lacks acceptance chronology") from error
        if not isinstance(accessions, list) or not isinstance(timestamps, list) or len(accessions) != len(timestamps):
            raise SecEdgarError("SEC submissions columns are inconsistent")
        result: dict[str, datetime.datetime] = {}
        for accession, timestamp in zip(accessions, timestamps, strict=True):
            parsed = pd.Timestamp(timestamp)
            if parsed.tzinfo is None:
                parsed = parsed.tz_localize("America/New_York")
            result[str(accession)] = parsed.tz_convert("UTC").to_pydatetime()
        return result

    @staticmethod
    def _facts(symbol: str, payload: dict[str, object], accepted: dict[str, datetime.datetime], as_of: datetime.datetime) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        facts = payload.get("facts")
        if not isinstance(facts, dict):
            raise SecEdgarError(f"SEC companyfacts lacks facts for {symbol}")
        cutoff = as_of.astimezone(datetime.UTC)
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
                        accession = str(observation.get("accn", ""))
                        if accession not in accepted:
                            raise SecEdgarError(f"missing acceptance timestamp for {symbol}/{accession}")
                        available_at = accepted[accession]
                        if available_at > cutoff:
                            continue
                        start = observation.get("start")
                        output.append({
                            "symbol": symbol,
                            "cik": str(payload.get("cik", "")),
                            "raw_concept": f"{taxonomy}:{concept}",
                            "period_type": "duration" if start else "instant",
                            "fiscal_period_start": start,
                            "period_end": observation.get("end"),
                            "fiscal_year": observation.get("fy"),
                            "fiscal_period": observation.get("fp"),
                            "form": observation.get("form"),
                            "filed_date": observation.get("filed"),
                            "available_at": available_at,
                            "value": observation.get("val"),
                            "unit": str(unit).upper(),
                            "accession": accession,
                            "frame": observation.get("frame"),
                            "source": "sec_edgar",
                            "dataset_version": SEC_DATASET_VERSION,
                            "confidence": None,
                        })
        return output
