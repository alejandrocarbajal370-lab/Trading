from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data.fx import FX_CONTRACT_VERSION, FXDataset, FXGovernanceError
from data.market_data import (
    MARKET_DATA_CONTRACT_VERSION,
    MarketDataDataset,
    MarketDataGovernanceError,
)
from fundamentals.governance import (
    ACCOUNTING_CONTRACT_VERSION,
    AccountingDataset,
    AccountingGovernanceError,
)

CROSS_LAYER_CONTRACT_VERSION = "cross-layer-governance-v1"


class CrossLayerGovernanceError(ValueError):
    """Raised when governed inputs cannot be aligned without an unsafe assumption."""


class CrossLayerManifest(BaseModel):
    """Immutable identity for the exact PIT inputs admitted to downstream research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["cross-layer-governance-v1"] = CROSS_LAYER_CONTRACT_VERSION
    as_of: datetime.datetime
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    entity_policy: Literal["EXACT_ELIGIBLE_SET"] = "EXACT_ELIGIBLE_SET"
    fx_translation_policy: Literal["FISCAL_PERIOD_END"] = "FISCAL_PERIOD_END"
    market_data_contract_version: Literal["market-data-governance-v1"]
    market_data_canonical_id: str
    market_data_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_contract_version: Literal["fx-governance-v1"]
    fx_canonical_id: str
    fx_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    accounting_contract_version: Literal["accounting-pit-governance-v1"]
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_entities: tuple[str, ...] = Field(min_length=1)
    required_fundamentals: tuple[str, ...]
    market_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accounting_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_conversions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    health: Literal["PASS"] = "PASS"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    scores_calculated: Literal[False] = False
    ranking_calculated: Literal[False] = False
    portfolio_constructed: Literal[False] = False

    @field_validator("as_of")
    @classmethod
    def aware_as_of(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value


@dataclass(frozen=True)
class CrossLayerGovernanceResult:
    market_snapshot: pd.DataFrame
    accounting_snapshot: pd.DataFrame
    fx_conversions: pd.DataFrame
    manifest: CrossLayerManifest


def write_governed_inputs(
    result: CrossLayerGovernanceResult, *, output_root: Path
) -> Path:
    """Write the immutable cross-layer bundle at its content-addressed location."""
    output_dir = output_root / f"cross_layer_{result.manifest.fingerprint}"
    expected = {
        "market_snapshot.csv": result.market_snapshot.to_csv(index=False, lineterminator="\n"),
        "accounting_snapshot.csv": result.accounting_snapshot.to_csv(
            index=False, lineterminator="\n"
        ),
        "fx_conversions.csv": result.fx_conversions.to_csv(index=False, lineterminator="\n"),
        "cross_layer_manifest.json": json.dumps(
            result.manifest.model_dump(mode="json"), indent=2, sort_keys=True
        )
        + "\n",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in expected.items():
        path = output_dir / name
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise CrossLayerGovernanceError(
                    f"immutable cross-layer output conflict: {path}"
                )
            continue
        path.write_text(content, encoding="utf-8")
    return output_dir


def _sha256_frame(frame: pd.DataFrame, sort_by: list[str]) -> str:
    canonical = frame.copy(deep=True)
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    for column in canonical.columns:
        canonical[column] = canonical[column].map(
            lambda value: "" if pd.isna(value) else str(value)
        )
    canonical = canonical.sort_values(sort_by, kind="stable").reset_index(drop=True)
    return hashlib.sha256(
        canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()


def _currency(value: object) -> str:
    currency = str(value).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise CrossLayerGovernanceError(f"invalid currency: {value!r}")
    return currency


def _normalized_entities(values: set[str]) -> tuple[str, ...]:
    entities = tuple(sorted(str(item).strip().upper() for item in values))
    if not entities or any(not item for item in entities):
        raise CrossLayerGovernanceError("eligible_entities must contain non-empty identifiers")
    return entities


def _assert_intact(
    market_data: MarketDataDataset, fx: FXDataset, accounting: AccountingDataset
) -> None:
    try:
        MarketDataDataset(frame=market_data.frame, metadata=market_data.metadata)
        FXDataset(frame=fx.frame, metadata=fx.metadata)
        AccountingDataset(frame=accounting.frame, metadata=accounting.metadata)
    except (MarketDataGovernanceError, FXGovernanceError, AccountingGovernanceError) as error:
        raise CrossLayerGovernanceError(f"governed input mutation detected: {error}") from error


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def integrate_governed_inputs(
    *,
    market_data: MarketDataDataset,
    fx: FXDataset,
    accounting: AccountingDataset,
    eligible_entities: set[str],
    as_of: datetime.datetime,
    base_currency: str,
    required_fundamentals: set[str] | None = None,
) -> CrossLayerGovernanceResult:
    """Align governed market, FX, and accounting data at one reproducible PIT cutoff.

    Monetary accounting facts are translated at fiscal-period end. Non-currency units are
    preserved. No imputation, proxy, score, ranking, or trade decision is produced.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise CrossLayerGovernanceError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(datetime.UTC)
    entities = _normalized_entities(eligible_entities)
    base = _currency(base_currency)
    required_metrics = tuple(sorted(required_fundamentals or set()))
    _assert_intact(market_data, fx, accounting)

    metadata = (market_data.metadata, fx.metadata, accounting.metadata)
    if any(item.available_at.astimezone(datetime.UTC) > cutoff for item in metadata):
        raise CrossLayerGovernanceError("PIT violation: governed dataset availability exceeds as_of")
    if market_data.metadata.contract_version != MARKET_DATA_CONTRACT_VERSION:
        raise CrossLayerGovernanceError("unsupported market-data governance contract")
    if fx.metadata.contract_version != FX_CONTRACT_VERSION:
        raise CrossLayerGovernanceError("unsupported FX governance contract")
    if accounting.metadata.contract_version != ACCOUNTING_CONTRACT_VERSION:
        raise CrossLayerGovernanceError("unsupported accounting governance contract")

    market = market_data.frame.loc[
        pd.to_datetime(market_data.frame["available_at"], utc=True) <= cutoff
    ].copy()
    market = market.loc[pd.to_datetime(market["date"]).dt.date <= cutoff.date()]
    observed_market = set(market["symbol"].astype(str).str.upper())
    expected = set(entities)
    if observed_market != expected:
        raise CrossLayerGovernanceError(
            f"entity alignment failure: market={sorted(observed_market)}, eligible={list(entities)}"
        )
    currency_counts = market.groupby("symbol")["currency"].nunique(dropna=False)
    if (currency_counts != 1).any():
        raise CrossLayerGovernanceError("currency alignment failure: market entity has mixed currency")
    market["currency"] = market["currency"].map(_currency)

    required = {(entity, metric) for entity in entities for metric in required_metrics}
    try:
        facts = accounting.snapshot(cutoff=cutoff, required=required).copy()
    except AccountingGovernanceError as error:
        raise CrossLayerGovernanceError(str(error)) from error
    observed_accounting = set(facts["entity"].astype(str).str.upper())
    if observed_accounting != expected:
        raise CrossLayerGovernanceError(
            "entity alignment failure: accounting and eligible entity sets differ"
        )

    converted_rows: list[dict[str, object]] = []
    converted_facts = facts.copy(deep=True)
    converted_facts["original_value"] = pd.to_numeric(converted_facts["value"], errors="raise")
    converted_facts["original_unit"] = converted_facts["unit"].astype(str).str.upper()
    for index, row in converted_facts.iterrows():
        unit = str(row["original_unit"])
        if len(unit) == 3 and unit.isalpha():
            period_end = pd.Timestamp(row["period_end"], tz="UTC").to_pydatetime().replace(
                hour=23, minute=59, second=59
            )
            try:
                conversion = fx.convert(
                    float(row["original_value"]),
                    source_currency=unit,
                    target_currency=base,
                    market_at=period_end,
                    cutoff=cutoff,
                )
            except FXGovernanceError as error:
                raise CrossLayerGovernanceError(
                    f"FX translation failed for {row['entity']}/{row['metric']}: {error}"
                ) from error
            converted_facts.at[index, "value"] = conversion.converted_amount
            converted_facts.at[index, "unit"] = base
            converted_rows.append(
                {
                    "entity": row["entity"],
                    "metric": row["metric"],
                    "period_end": row["period_end"],
                    **conversion.__dict__,
                }
            )
        else:
            converted_rows.append(
                {
                    "entity": row["entity"],
                    "metric": row["metric"],
                    "period_end": row["period_end"],
                    "amount": float(row["original_value"]),
                    "source_currency": None,
                    "target_currency": None,
                    "converted_amount": float(row["original_value"]),
                    "rate": None,
                    "conversion_method": "not_applicable",
                    "rate_market_timestamp": None,
                    "rate_available_at": None,
                    "fx_canonical_id": None,
                    "fx_checksum": None,
                    "fx_source": None,
                    "fx_dataset_version": None,
                }
            )
    conversions = pd.DataFrame(converted_rows)
    market_hash = _sha256_frame(market, ["symbol", "date"])
    accounting_hash = _sha256_frame(
        converted_facts, ["entity", "metric", "period_end", "revision"]
    )
    conversions_hash = _sha256_frame(conversions, ["entity", "metric", "period_end"])
    identity = {
        "contract_version": CROSS_LAYER_CONTRACT_VERSION,
        "as_of": cutoff.isoformat(),
        "base_currency": base,
        "entity_policy": "EXACT_ELIGIBLE_SET",
        "fx_translation_policy": "FISCAL_PERIOD_END",
        "eligible_entities": entities,
        "required_fundamentals": required_metrics,
        "market": market_data.metadata.canonical_id,
        "fx": fx.metadata.canonical_id,
        "accounting": accounting.metadata.canonical_id,
        "market_snapshot_sha256": market_hash,
        "accounting_snapshot_sha256": accounting_hash,
        "fx_conversions_sha256": conversions_hash,
    }
    manifest = CrossLayerManifest(
        as_of=cutoff,
        base_currency=base,
        market_data_contract_version=market_data.metadata.contract_version,
        market_data_canonical_id=market_data.metadata.canonical_id,
        market_data_checksum=market_data.metadata.checksum,
        fx_contract_version=fx.metadata.contract_version,
        fx_canonical_id=fx.metadata.canonical_id,
        fx_checksum=fx.metadata.checksum,
        accounting_contract_version=accounting.metadata.contract_version,
        accounting_canonical_id=accounting.metadata.canonical_id,
        accounting_checksum=accounting.metadata.checksum,
        eligible_entities=entities,
        required_fundamentals=required_metrics,
        market_snapshot_sha256=market_hash,
        accounting_snapshot_sha256=accounting_hash,
        fx_conversions_sha256=conversions_hash,
        fingerprint=_fingerprint(identity),
    )
    return CrossLayerGovernanceResult(market, converted_facts, conversions, manifest)
