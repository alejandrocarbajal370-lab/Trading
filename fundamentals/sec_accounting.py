from __future__ import annotations

import datetime
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from data.connectors.sec_edgar import SecFundamentalsResult
from data.sec_universe_binding import SecAcquisitionPlan
from fundamentals.governance import (
    AccountingDataset,
    AccountingGovernanceError,
    AccountingLineageEntry,
    govern_accounting,
)
from governance.canonical import runtime_fingerprint

SEC_MAPPING_REGISTRY_VERSION = "sec-canonical-fundamentals-v1"
SEC_ACCOUNTING_ADAPTER_VERSION = "sec-accounting-binding-v1"


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
    version: Literal["sec-canonical-fundamentals-v1"] = SEC_MAPPING_REGISTRY_VERSION
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
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
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


@dataclass(frozen=True)
class SecAccountingBindingResult:
    accounting: AccountingDataset
    registry_hash: str
    mapped_metrics: tuple[str, ...]
    unmapped_concepts: tuple[str, ...]
    readiness_state: str = "ACCOUNTING_BOUND_QVM_NOT_READY"
    global_readiness: str = "INSUFFICIENT_REAL_DATA"
    trade_decision: str = "NO_TRADE"
    live_execution_enabled: bool = False
    signals_generated: bool = False


def _currency_unit(value: object) -> str:
    unit = value if isinstance(value, str) else ""
    unit = unit.strip().upper()
    if len(unit) != 3 or not unit.isalpha() or unit in {"USD/SHARES", "PURE"}:
        raise SecAccountingBindingError("SEC concept/unit family mismatch")
    return unit


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


def _fiscal_label(row: pd.Series, start: datetime.date | None, end: datetime.date) -> str:
    fp, fy = row.get("fiscal_period"), row.get("fiscal_year")
    if not isinstance(fp, str) or not fp.strip() or pd.isna(fy):
        raise SecAccountingBindingError("SEC fiscal identity is missing")
    label = fp.strip().upper()
    if start is not None:
        days = (end - start).days + 1
        if label == "FY" and not 330 <= days <= 400:
            raise SecAccountingBindingError("SEC FY duration is incompatible with period dates")
        if label in {"Q1", "Q2", "Q3", "Q4"} and not 60 <= days <= 120:
            raise SecAccountingBindingError("SEC quarter duration is incompatible with period dates")
    return f"{label}-{int(fy)}:{start.isoformat() if start else end.isoformat()}:{end.isoformat()}"


def bind_sec_to_accounting(
    sec: SecFundamentalsResult,
    *,
    plan: SecAcquisitionPlan,
    as_of: datetime.datetime,
    registry: SecMappingRegistry = DEFAULT_SEC_MAPPING_REGISTRY,
) -> SecAccountingBindingResult:
    """Bind exact registered SEC facts to issuer-level governed AccountingDataset."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SecAccountingBindingError("as_of must be timezone-aware")
    registry = SecMappingRegistry.model_validate(registry.model_dump(mode="python"))
    if plan.as_of != as_of:
        raise SecAccountingBindingError("SEC plan/as_of mismatch")
    manifests = {manifest.sha256: manifest for manifest in sec.raw_manifests}
    if not manifests:
        raise SecAccountingBindingError("raw SEC snapshot proof is required")
    companyfacts = {
        manifest.resource.split(":", 1)[1]: manifest
        for manifest in manifests.values()
        if manifest.resource.startswith("companyfacts:")
    }
    issuers = {issuer.canonical_cik: issuer for issuer in plan.issuers}
    mappings = {(item.taxonomy, item.concept): item for item in registry.mappings}
    runtime = runtime_fingerprint()
    output: list[dict[str, object]] = []
    unmapped: set[str] = set()

    for _, row in sec.facts.iterrows():
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
            item.sha256
            for item in sec.raw_manifests
            if item.resource.startswith("submissions") and cik in item.resource
        }
        if not isinstance(submission_hashes, list) or not submission_hashes or set(submission_hashes) != known_submission_hashes:
            raise SecAccountingBindingError("SEC acceptance lineage proof mismatch")
        if taxonomy in {"dei", "custom/other"} or row.get("economic_mapping_eligible") is not True:
            raise SecAccountingBindingError("metadata/custom SEC concept cannot be economic")
        unit = _currency_unit(row.get("unit"))
        start, end = _period(row, mapping.period_type)
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
        fiscal_period = _fiscal_label(row, start, end)
        try:
            value = float(pd.to_numeric(row.get("value"), errors="raise"))
        except (TypeError, ValueError) as error:
            raise SecAccountingBindingError("SEC economic value is non-numeric") from error
        if not math.isfinite(value):
            raise SecAccountingBindingError("SEC economic value is non-numeric")
        value *= -1.0 if mapping.sign == "negate" else 1.0
        filing_date = available  # acceptanceDateTime is the governed knowledge timestamp.
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
    dataset = govern_accounting(
        frame,
        source="sec_edgar_canonical",
        dataset_version=SEC_ACCOUNTING_ADAPTER_VERSION,
        available_at=as_of,
        as_of=as_of,
        lineage=(
            AccountingLineageEntry(source="sec_edgar", dataset="companyfacts", dataset_version=sec.dataset_version, transformation=f"{SEC_ACCOUNTING_ADAPTER_VERSION}:{registry.registry_hash}"),
            AccountingLineageEntry(source="security_master", dataset="issuer-cik-plan", dataset_version=plan.contract_version, transformation=plan.plan_hash),
        ),
    )
    return SecAccountingBindingResult(
        accounting=dataset,
        registry_hash=registry.registry_hash,
        mapped_metrics=tuple(sorted(frame["metric"].unique())),
        unmapped_concepts=tuple(sorted(unmapped)),
    )
