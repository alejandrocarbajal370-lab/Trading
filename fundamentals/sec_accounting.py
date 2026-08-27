from __future__ import annotations

import datetime
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from data.connectors.sec_edgar import (
    SecEdgarError,
    SecEdgarFundamentalsSource,
    SecFundamentalsResult,
    canonical_accession,
)
from data.raw_snapshots import RawSnapshotError, RawSnapshotManifest, RawSnapshotStore
from data.sec_universe_binding import SecAcquisitionPlan
from fundamentals.governance import (
    AccountingDataset,
    AccountingGovernanceError,
    AccountingLineageEntry,
    govern_accounting,
)
from governance.canonical import runtime_fingerprint

SEC_MAPPING_REGISTRY_VERSION = "sec-canonical-fundamentals-v2"
SEC_RAW_PROOF_VERSION = "phase7c-raw-proof-v2"
SEC_UNIT_REGISTRY_VERSION = "sec-unit-currency-registry-v1"
FORM_PERIOD_POLICY_VERSION = "sec-form-period-policy-v2"
RAW_TEMPORAL_POLICY_VERSION = "sec-raw-temporal-exact-cutoff-v1"
SEC_ACCOUNTING_ADAPTER_VERSION = "sec-accounting-binding-v3"


class SecAccountingBindingError(AccountingGovernanceError):
    """SEC facts cannot be bound without guessing or losing proof."""


class SecConceptMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    taxonomy: Literal["us-gaap", "ifrs-full"]
    concept: str = Field(min_length=1)
    canonical_metric: str = Field(min_length=1)
    period_type: Literal["instant", "duration"]
    unit_family: Literal["currency", "shares", "pure", "percent"]
    sign: Literal["as_reported", "negate"] = "as_reported"


class SecMappingRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["sec-canonical-fundamentals-v2"] = SEC_MAPPING_REGISTRY_VERSION
    mappings: tuple[SecConceptMapping, ...]
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "mappings": [mapping.model_dump(mode="json") for mapping in self.mappings],
        }

    @model_validator(mode="after")
    def verify(self) -> SecMappingRegistry:
        identities = [(item.taxonomy, item.concept) for item in self.mappings]
        if identities != sorted(identities) or len(identities) != len(set(identities)):
            raise ValueError("SEC mappings must be unique and canonical")
        if _hash(self.payload()) != self.registry_hash:
            raise ValueError("SEC mapping registry hash mismatch")
        return self


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_mapping_registry() -> SecMappingRegistry:
    # These are exact registrations, never substring/label heuristics. Economically
    # non-identical tags (including most debt variants) intentionally remain unmapped.
    mappings = tuple(
        sorted(
            (
                SecConceptMapping(taxonomy="us-gaap", concept="Assets", canonical_metric="total_assets", period_type="instant", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="CashAndCashEquivalentsAtCarryingValue", canonical_metric="cash", period_type="instant", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="NetCashProvidedByUsedInOperatingActivities", canonical_metric="cash_from_operations", period_type="duration", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="NetIncomeLoss", canonical_metric="net_income", period_type="duration", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="OperatingIncomeLoss", canonical_metric="operating_income", period_type="duration", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="PaymentsToAcquirePropertyPlantAndEquipment", canonical_metric="capital_expenditures", period_type="duration", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="RevenueFromContractWithCustomerExcludingAssessedTax", canonical_metric="revenue", period_type="duration", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="Revenues", canonical_metric="revenue", period_type="duration", unit_family="currency"),
                SecConceptMapping(taxonomy="us-gaap", concept="StockholdersEquity", canonical_metric="total_equity", period_type="instant", unit_family="currency"),
            ),
            key=lambda item: (item.taxonomy, item.concept),
        )
    )
    payload = {"version": SEC_MAPPING_REGISTRY_VERSION, "mappings": [item.model_dump(mode="json") for item in mappings]}
    return SecMappingRegistry(mappings=mappings, registry_hash=_hash(payload))


DEFAULT_SEC_MAPPING_REGISTRY = build_mapping_registry()


class SecUnitRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["sec-unit-currency-registry-v1"] = SEC_UNIT_REGISTRY_VERSION
    currencies: tuple[str, ...]
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify(self) -> SecUnitRegistry:
        if self.currencies != tuple(sorted(set(self.currencies))):
            raise ValueError("currency registry must be unique and canonical")
        if any(not item.isupper() or len(item) != 3 or not item.isalpha() for item in self.currencies):
            raise ValueError("currency registry contains an invalid code")
        if _hash({"version": self.version, "currencies": self.currencies}) != self.registry_hash:
            raise ValueError("currency registry hash mismatch")
        return self


def build_unit_registry() -> SecUnitRegistry:
    # Explicit Phase 7C authority. This is deliberately smaller than "three letters"
    # and can only be expanded by changing the versioned, hashed policy.
    currencies = tuple(sorted(("CNY", "EUR", "GBP", "JPY", "USD")))
    payload = {"version": SEC_UNIT_REGISTRY_VERSION, "currencies": currencies}
    return SecUnitRegistry(currencies=currencies, registry_hash=_hash(payload))


DEFAULT_SEC_UNIT_REGISTRY = build_unit_registry()


class VerifiedSecRawEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["phase7c-raw-proof-v2"] = SEC_RAW_PROOF_VERSION
    as_of: datetime.datetime
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    unit_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    form_period_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_temporal_policy_version: Literal["sec-raw-temporal-exact-cutoff-v1"] = RAW_TEMPORAL_POLICY_VERSION
    raw_resource_cutoffs: tuple[str, ...]
    raw_manifest_identities: tuple[str, ...]
    canonical_selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_fingerprint: str = Field(min_length=1)
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"proof_hash"})

    @model_validator(mode="after")
    def verify(self) -> VerifiedSecRawEvidence:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("raw proof as_of must be timezone-aware")
        if self.raw_manifest_identities != tuple(sorted(set(self.raw_manifest_identities))):
            raise ValueError("raw proof manifests must be unique and canonical")
        if self.raw_resource_cutoffs != tuple(sorted(set(self.raw_resource_cutoffs))):
            raise ValueError("raw proof resource cutoffs must be unique and canonical")
        if _hash(self.payload()) != self.proof_hash:
            raise ValueError("raw proof hash mismatch")
        return self


@dataclass(frozen=True)
class SecAccountingBindingResult:
    accounting: AccountingDataset
    registry_hash: str
    mapped_metrics: tuple[str, ...]
    unmapped_concepts: tuple[str, ...]
    raw_proof: VerifiedSecRawEvidence
    readiness_state: str = "ACCOUNTING_BOUND_QVM_NOT_READY"
    global_readiness: str = "INSUFFICIENT_REAL_DATA"
    trade_decision: str = "NO_TRADE"
    live_execution_enabled: bool = False
    signals_generated: bool = False


def _currency_unit(value: object, registry: SecUnitRegistry) -> str:
    # SEC units are case-sensitive governed tokens here; normalization would hide
    # malformed/custom input and weaken the raw-to-canonical proof.
    unit = value if isinstance(value, str) else ""
    if unit not in registry.currencies:
        raise SecAccountingBindingError("SEC concept/unit family mismatch")
    return unit


FORM_PERIOD_POLICY = {
    "version": FORM_PERIOD_POLICY_VERSION,
    "form_fp": {
        "10-K": ("FY",), "10-K/A": ("FY",), "20-F": ("FY",), "20-F/A": ("FY",),
        "10-Q": ("Q1", "Q2", "Q3"), "10-Q/A": ("Q1", "Q2", "Q3"),
    },
    "unsupported_semantic_forms": ("6-K", "6-K/A", "40-F", "40-F/A"),
    "duration_ranges": {
        "FY": {"ANNUAL": (330, 400)},
        "Q1": {"QUARTER": (60, 120)},
        "Q2": {"QUARTER": (60, 120), "YTD": (121, 210)},
        "Q3": {"QUARTER": (60, 120), "YTD": (121, 300)},
    },
}
FORM_PERIOD_POLICY_HASH = _hash(FORM_PERIOD_POLICY)


def _form_period(row: pd.Series, start: datetime.date | None, end: datetime.date) -> str:
    form, fp = row.get("form"), row.get("fiscal_period")
    if not isinstance(form, str) or not isinstance(fp, str):
        raise SecAccountingBindingError("SEC form/fiscal period identity is missing")
    form, fp = form.strip().upper(), fp.strip().upper()
    unsupported = set(FORM_PERIOD_POLICY["unsupported_semantic_forms"])
    matrix = FORM_PERIOD_POLICY["form_fp"]
    if form in unsupported:
        raise SecAccountingBindingError("SEC form has no explicit Phase 7C fiscal semantics")
    if form not in matrix or fp not in matrix[form]:
        raise SecAccountingBindingError("SEC form/fiscal period is incoherent")
    if start is None:
        return "INSTANT"
    days = (end - start).days + 1
    classifications = FORM_PERIOD_POLICY["duration_ranges"][fp]
    matches = [name for name, limits in classifications.items() if limits[0] <= days <= limits[1]]
    if len(matches) != 1:
        raise SecAccountingBindingError("SEC duration is outside the governed fiscal policy")
    return matches[0]


def _period(row: pd.Series, expected: str) -> tuple[datetime.date | None, datetime.date]:
    if row["period_type"] != expected:
        raise SecAccountingBindingError("SEC instant/duration semantic mismatch")
    try:
        end = pd.Timestamp(row["period_end"]).date()
        start = None if pd.isna(row["fiscal_period_start"]) else pd.Timestamp(row["fiscal_period_start"]).date()
    except (TypeError, ValueError) as error:
        raise SecAccountingBindingError("SEC fiscal period is invalid") from error
    if expected == "duration":
        if start is None or start > end:
            raise SecAccountingBindingError("SEC duration period is invalid")
    elif start is not None:
        raise SecAccountingBindingError("SEC instant fact must not have a period start")
    return start, end


def _fiscal_label(row: pd.Series, start: datetime.date | None, end: datetime.date, duration_semantics: str) -> str:
    fp, fy = row.get("fiscal_period"), row.get("fiscal_year")
    if not isinstance(fp, str) or not fp.strip() or pd.isna(fy):
        raise SecAccountingBindingError("SEC fiscal identity is missing")
    label = fp.strip().upper()
    return f"{label}-{int(fy)}:{duration_semantics}:{start.isoformat() if start else end.isoformat()}:{end.isoformat()}"


def _verified_payloads(
    sec: SecFundamentalsResult, raw_store: RawSnapshotStore, as_of: datetime.datetime,
) -> tuple[dict[str, tuple[RawSnapshotManifest, dict[str, object]]], tuple[str, ...], tuple[str, ...]]:
    verified: dict[str, tuple[RawSnapshotManifest, dict[str, object]]] = {}
    identities: list[str] = []
    cutoffs: list[str] = []
    expected_cutoff = as_of.astimezone(datetime.UTC)
    for declared in sec.raw_manifests:
        path = raw_store.root / declared.provider / "acquisitions" / f"{declared.acquisition_id}.json"
        try:
            observed = raw_store.verify(path)
            if observed != declared:
                raise SecAccountingBindingError("declared raw manifest differs from verified storage")
            payload_path = (path.parent / observed.payload_file).resolve(strict=True)
            payload = json.loads(payload_path.read_bytes())
        except (RawSnapshotError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SecAccountingBindingError("raw SEC manifest/payload proof is not physically verifiable") from error
        if not isinstance(payload, dict) or observed.provider != "sec_edgar":
            raise SecAccountingBindingError("raw SEC resource payload/provider is invalid")
        if observed.as_of != expected_cutoff:
            raise SecAccountingBindingError("raw SEC manifest as_of violates exact-cutoff policy")
        if observed.resource in verified:
            raise SecAccountingBindingError("duplicate raw SEC resource acquisition")
        verified[observed.resource] = (observed, payload)
        identities.append(_hash(observed.model_dump(mode="json")))
        cutoffs.append(f"{observed.resource}:{observed.as_of.isoformat()}")
    if not verified:
        raise SecAccountingBindingError("raw SEC snapshot proof is required")
    return verified, tuple(sorted(identities)), tuple(sorted(cutoffs))


def _submission_chronology(
    resources: dict[str, tuple[RawSnapshotManifest, dict[str, object]]], cik: str,
) -> tuple[dict[str, tuple[datetime.datetime, str]], tuple[str, ...]]:
    chronology: dict[str, tuple[datetime.datetime, str]] = {}
    hashes: list[str] = []
    matches = [(name, pair) for name, pair in resources.items()
               if (name == f"submissions:{cik}" or name.startswith(f"submissions-history:{cik}:"))]
    if not matches or f"submissions:{cik}" not in resources:
        raise SecAccountingBindingError("verified SEC submissions proof is missing")
    for name, (manifest, payload) in matches:
        raw = payload.get("filings", {}).get("recent") if name == f"submissions:{cik}" else payload
        if not SecEdgarFundamentalsSource._submission_columns_consistent(raw):
            raise SecAccountingBindingError("verified SEC submissions columns are inconsistent")
        assert isinstance(raw, dict)
        hashes.append(manifest.sha256)
        for accession, accepted, form in zip(
            raw["accessionNumber"], raw["acceptanceDateTime"], raw["form"], strict=True
        ):
            try:
                key = canonical_accession(accession)
                stamp = pd.Timestamp(accepted)
            except (SecEdgarError, TypeError, ValueError) as error:
                raise SecAccountingBindingError("verified SEC accession chronology is invalid") from error
            if pd.isna(stamp) or stamp.tzinfo is None or not isinstance(form, str) or not form.strip():
                raise SecAccountingBindingError("verified SEC accession chronology is invalid")
            value = (stamp.tz_convert("UTC").to_pydatetime(), form.strip().upper())
            if key in chronology:
                raise SecAccountingBindingError("duplicate SEC accession chronology after canonicalization")
            chronology[key] = value
    return chronology, tuple(sorted(hashes))


def _rebuild_raw_facts(
    sec: SecFundamentalsResult,
    resources: dict[str, tuple[RawSnapshotManifest, dict[str, object]]],
    plan: SecAcquisitionPlan,
    as_of: datetime.datetime,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for issuer in plan.issuers:
        cik = issuer.canonical_cik
        company = resources.get(f"companyfacts:{cik}")
        if company is None:
            raise SecAccountingBindingError("verified SEC Company Facts proof is missing")
        company_manifest, payload = company
        payload_cik = payload.get("cik")
        if isinstance(payload_cik, bool) or not str(payload_cik).isdigit() or str(payload_cik).zfill(10) != cik:
            raise SecAccountingBindingError("SEC Company Facts resource/CIK identity mismatch")
        chronology, submission_hashes = _submission_chronology(resources, cik)
        accepted = {key: value[0] for key, value in chronology.items()}
        try:
            rebuilt = SecEdgarFundamentalsSource._facts(cik, payload, accepted, as_of)
        except SecEdgarError as error:
            raise SecAccountingBindingError(f"verified SEC raw fact reconstruction failed: {error}") from error
        for row in rebuilt:
            accession = row["accession"]
            if chronology[accession][1] != str(row["form"]).upper():
                raise SecAccountingBindingError("Company Facts form conflicts with verified Submissions")
            row["raw_snapshot_sha256"] = company_manifest.sha256
            row["submission_snapshot_sha256"] = json.dumps(submission_hashes)
            rows.append(row)
    rebuilt_frame = pd.DataFrame(rows)
    if rebuilt_frame.empty:
        raise SecAccountingBindingError("verified SEC raw evidence contains no eligible facts")
    columns = (
        "cik", "taxonomy", "concept", "period_type", "fiscal_period_start", "period_end",
        "fiscal_year", "fiscal_period", "form", "filed_date", "available_at", "value", "unit",
        "accession", "frame", "economic_mapping_eligible", "raw_snapshot_sha256",
        "submission_snapshot_sha256",
    )
    if any(column not in sec.facts.columns for column in columns):
        raise SecAccountingBindingError("declarative SEC facts lack raw-proof comparison fields")
    def records(frame: pd.DataFrame) -> list[str]:
        normalized = frame.loc[:, columns].copy()
        for column in normalized.columns:
            normalized[column] = normalized[column].map(
                lambda value: None if pd.isna(value) else (
                    pd.Timestamp(value).isoformat() if isinstance(value, (pd.Timestamp, datetime.datetime)) else value
                )
            )
        return sorted(_hash(record) for record in normalized.to_dict("records"))
    if records(sec.facts) != records(rebuilt_frame):
        raise SecAccountingBindingError("SEC canonical facts do not exactly reconstruct from verified raw evidence")
    return rebuilt_frame


def bind_sec_to_accounting(
    sec: SecFundamentalsResult,
    *,
    plan: SecAcquisitionPlan,
    as_of: datetime.datetime,
    raw_store: RawSnapshotStore,
    registry: SecMappingRegistry = DEFAULT_SEC_MAPPING_REGISTRY,
    unit_registry: SecUnitRegistry = DEFAULT_SEC_UNIT_REGISTRY,
) -> SecAccountingBindingResult:
    """Bind exact registered SEC facts to issuer-level governed AccountingDataset."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SecAccountingBindingError("as_of must be timezone-aware")
    registry = SecMappingRegistry.model_validate(registry.model_dump(mode="python"))
    unit_registry = SecUnitRegistry.model_validate(unit_registry.model_dump(mode="python"))
    if plan.as_of != as_of:
        raise SecAccountingBindingError("SEC plan/as_of mismatch")
    resources, raw_manifest_identities, raw_resource_cutoffs = _verified_payloads(sec, raw_store, as_of)
    rebuilt_facts = _rebuild_raw_facts(sec, resources, plan, as_of.astimezone(datetime.UTC))
    companyfacts = {
        resource.split(":", 1)[1]: manifest
        for resource, (manifest, _) in resources.items()
        if resource.startswith("companyfacts:")
    }
    issuers = {issuer.canonical_cik: issuer for issuer in plan.issuers}
    mappings = {(item.taxonomy, item.concept): item for item in registry.mappings}
    runtime = runtime_fingerprint()
    output: list[dict[str, object]] = []
    unmapped: set[str] = set()

    for _, row in rebuilt_facts.iterrows():
        taxonomy, concept = row.get("taxonomy"), row.get("concept")
        mapping = mappings.get((taxonomy, concept))
        raw_name = f"{taxonomy}:{concept}"
        if mapping is None:
            unmapped.add(raw_name)
            continue
        cik_value = row.get("cik")
        if isinstance(cik_value, bool) or not isinstance(cik_value, (str, int)):
            raise SecAccountingBindingError("SEC fact CIK is invalid")
        cik_text = str(cik_value).strip()
        if not cik_text.isdigit():
            raise SecAccountingBindingError("SEC fact CIK is invalid")
        cik = cik_text.zfill(10)
        issuer = issuers.get(cik)
        manifest = companyfacts.get(cik)
        if issuer is None or manifest is None:
            raise SecAccountingBindingError("SEC fact lacks issuer/raw snapshot proof")
        if row.get("raw_snapshot_sha256") != manifest.sha256:
            raise SecAccountingBindingError("SEC raw snapshot hash proof mismatch")
        try:
            submission_hashes = json.loads(row.get("submission_snapshot_sha256"))
        except (TypeError, json.JSONDecodeError) as error:
            raise SecAccountingBindingError("SEC submission snapshot proof is invalid") from error
        known_submission_hashes = {
            item.sha256 for resource, (item, _) in resources.items()
            if resource.startswith("submissions") and cik in resource
        }
        if not isinstance(submission_hashes, list) or not submission_hashes or set(submission_hashes) != known_submission_hashes:
            raise SecAccountingBindingError("SEC acceptance lineage proof mismatch")
        if taxonomy in {"dei", "custom/other"} or row.get("economic_mapping_eligible") is not True:
            raise SecAccountingBindingError("metadata/custom SEC concept cannot be economic")
        if mapping.unit_family != "currency":
            raise SecAccountingBindingError("Phase 7C mapping unit adapter is not implemented")
        unit = _currency_unit(row.get("unit"), unit_registry)
        start, end = _period(row, mapping.period_type)
        duration_semantics = _form_period(row, start, end)
        available = pd.Timestamp(row.get("available_at"))
        if pd.isna(available) or available.tzinfo is None:
            raise SecAccountingBindingError("SEC acceptanceDateTime is required and timezone-aware")
        available = available.tz_convert("UTC")
        cutoff = pd.Timestamp(as_of).tz_convert("UTC")
        if available > cutoff:
            raise SecAccountingBindingError("SEC acceptanceDateTime exceeds cutoff")
        accession, form = row.get("accession"), row.get("form")
        if not isinstance(accession, str) or not isinstance(form, str):
            raise SecAccountingBindingError("SEC accession/form lineage is missing")
        fiscal_period = _fiscal_label(row, start, end, duration_semantics)
        try:
            value = float(pd.to_numeric(row.get("value"), errors="raise"))
        except (TypeError, ValueError) as error:
            raise SecAccountingBindingError("SEC economic value is non-numeric") from error
        if not math.isfinite(value):
            raise SecAccountingBindingError("SEC economic value is non-numeric")
        value *= -1.0 if mapping.sign == "negate" else 1.0
        filing_date = available  # acceptanceDateTime is the governed knowledge timestamp.
        canonical_fact_identity = _hash({
            "canonical_cik": cik, "issuer_id": issuer.issuer_id,
            "taxonomy": taxonomy, "concept": concept,
            "canonical_metric": mapping.canonical_metric,
            "original_unit": row.get("unit"), "canonical_unit": unit,
            "unit_family": mapping.unit_family, "accession": accession, "form": form,
            "start": start, "end": end, "frame": row.get("frame"),
            "period_type": mapping.period_type, "available_at": available.isoformat(),
            "duration_semantics": duration_semantics,
            "mapping_registry_hash": registry.registry_hash,
        })
        output.append({
            "fact_id": _hash({"issuer_id": issuer.issuer_id, "metric": mapping.canonical_metric, "fiscal_period": fiscal_period, "unit": unit}),
            "entity": issuer.issuer_id,
            "metric": mapping.canonical_metric,
            "fiscal_period": fiscal_period,
            "period_end": end,
            "filing_date": filing_date,
            "available_at": available,
            "value": value,
            "unit": unit,
            "source": "sec_edgar_canonical",
            "dataset_version": SEC_ACCOUNTING_ADAPTER_VERSION,
            "revision": 0,
            "revision_type": "ORIGINAL",
            "supersedes_revision": None,
            "fiscal_period_start": start,
            "period_type": mapping.period_type,
            "duration_semantics": duration_semantics,
            "taxonomy": taxonomy,
            "concept": concept,
            "accession": accession,
            "form": form,
            "frame": row.get("frame"),
            "acceptance_datetime": available.isoformat(),
            "reported_filed_date": row.get("filed_date"),
            "canonical_cik": cik,
            "issuer_id": issuer.issuer_id,
            "applicable_permanent_ids": json.dumps(issuer.permanent_ids),
            "mapping_registry_hash": registry.registry_hash,
            "unit_registry_hash": unit_registry.registry_hash,
            "form_period_policy_hash": FORM_PERIOD_POLICY_HASH,
            "canonical_fact_identity": canonical_fact_identity,
            "original_sec_unit": row.get("unit"),
            "canonical_unit_family": mapping.unit_family,
            "raw_snapshot_sha256": manifest.sha256,
            "submission_snapshot_sha256": json.dumps(submission_hashes, sort_keys=True),
            "sec_plan_hash": plan.plan_hash,
            "runtime_fingerprint": runtime.fingerprint,
            "data_confidence": None,
            "mapping_confidence": None,
            "calculation_confidence": None,
        })

    if not output:
        raise SecAccountingBindingError("no registered SEC economic facts were mapped")
    frame = pd.DataFrame(output)
    identity = ["entity", "metric", "fiscal_period", "period_end", "unit", "available_at"]
    for key, group in frame.groupby(identity, dropna=False, sort=False):
        if len(group) > 1:
            semantic = group[["value", "accession", "form", "frame", "taxonomy", "concept", "raw_snapshot_sha256"]].drop_duplicates()
            if len(semantic) != 1:
                raise SecAccountingBindingError(f"conflicting/ambiguous SEC economic facts: {key}")
    frame = frame.drop_duplicates()
    if frame.duplicated(identity).any():
        raise SecAccountingBindingError("ambiguous SEC contexts require an explicit registry policy")

    economic = ["entity", "metric", "fiscal_period", "period_end"]
    rebuilt: list[pd.DataFrame] = []
    for _, group in frame.groupby(economic, dropna=False, sort=False):
        ordered = group.sort_values(["available_at", "accession"], kind="stable").copy()
        if ordered["available_at"].duplicated().any():
            raise SecAccountingBindingError("same-time conflicting SEC revisions")
        ordered["revision"] = range(len(ordered))
        ordered["revision_type"] = ["ORIGINAL", *(["RESTATEMENT"] * (len(ordered) - 1))]
        ordered["supersedes_revision"] = [None, *range(len(ordered) - 1)]
        rebuilt.append(ordered)
    frame = pd.concat(rebuilt, ignore_index=True)
    selection_columns = [
        "canonical_cik", "taxonomy", "concept", "metric", "unit", "accession", "form",
        "fiscal_period_start", "period_end", "period_type", "available_at", "value", "frame",
        "duration_semantics",
        "mapping_registry_hash", "unit_registry_hash", "form_period_policy_hash",
        "canonical_fact_identity", "original_sec_unit", "canonical_unit_family",
        "raw_snapshot_sha256", "submission_snapshot_sha256",
    ]
    selection_hash = _hash(sorted(
        _hash({key: (None if pd.isna(row[key]) else str(row[key])) for key in selection_columns})
        for _, row in frame.iterrows()
    ))
    proof_payload = {
        "version": SEC_RAW_PROOF_VERSION,
        "as_of": as_of.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan.plan_hash,
        "mapping_registry_hash": registry.registry_hash,
        "unit_registry_hash": unit_registry.registry_hash,
        "form_period_policy_hash": FORM_PERIOD_POLICY_HASH,
        "raw_temporal_policy_version": RAW_TEMPORAL_POLICY_VERSION,
        "raw_resource_cutoffs": raw_resource_cutoffs,
        "raw_manifest_identities": raw_manifest_identities,
        "canonical_selection_hash": selection_hash,
        "runtime_fingerprint": runtime.fingerprint,
    }
    raw_proof = VerifiedSecRawEvidence(**proof_payload, proof_hash=_hash(proof_payload))
    frame["phase7c_raw_proof_hash"] = raw_proof.proof_hash
    dataset = govern_accounting(
        frame,
        source="sec_edgar_canonical",
        dataset_version=SEC_ACCOUNTING_ADAPTER_VERSION,
        available_at=as_of,
        as_of=as_of,
        lineage=(
            AccountingLineageEntry(source="sec_edgar", dataset="companyfacts+submissions", dataset_version=sec.dataset_version, transformation=f"{SEC_ACCOUNTING_ADAPTER_VERSION}:{raw_proof.proof_hash}"),
            AccountingLineageEntry(source="security_master", dataset="issuer-cik-plan", dataset_version=plan.contract_version, transformation=plan.plan_hash),
        ),
    )
    return SecAccountingBindingResult(
        accounting=dataset,
        registry_hash=registry.registry_hash,
        mapped_metrics=tuple(sorted(frame["metric"].unique())),
        unmapped_concepts=tuple(sorted(unmapped)),
        raw_proof=raw_proof,
    )
