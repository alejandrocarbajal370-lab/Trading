from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data.fx import FXDataset, FXGovernanceError
from data.market_data import MarketDataDataset, MarketDataGovernanceError
from fundamentals.governance import (
    ACCOUNTING_PERIOD_ADAPTER_VERSION,
    AccountingDataset,
    AccountingGovernanceError,
)
from governance.units import UNIT_ONTOLOGY_VERSION, normalize_unit, unit_kind
from research.datasets import DatasetVersionError, verify_universe_snapshot

CROSS_LAYER_CONTRACT_VERSION = "cross-layer-governance-v3"
AVAILABILITY_POLICY_VERSION = "known-by-common-cutoff-v1"
ENTITY_POLICY_VERSION = "exact-eligible-set-v1"
CALENDAR_ALIGNMENT_POLICY_VERSION = "cross-layer-temporal-alignment-v1"
MARKET_CAP_CURRENCY_POLICY_VERSION = "explicit-market-cap-currency-v1"
VALUE_TEMPORAL_SELECTION_POLICY_VERSION = "value-fy-flow-and-period-end-instant-v1"


class CrossLayerGovernanceError(ValueError):
    """Raised when governed inputs cannot be aligned without an unsafe assumption."""


class CrossLayerManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["cross-layer-governance-v3"] = CROSS_LAYER_CONTRACT_VERSION
    as_of: datetime.datetime
    universe_snapshot_id: str
    universe_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    membership_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_symbols_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_symbols_count: int = Field(gt=0)
    universe_ruleset_version: str
    universe_as_of: datetime.datetime
    availability_policy_version: Literal["known-by-common-cutoff-v1"] = AVAILABILITY_POLICY_VERSION
    entity_policy_version: Literal["exact-eligible-set-v1"] = ENTITY_POLICY_VERSION
    calendar_alignment_policy_version: Literal["cross-layer-temporal-alignment-v1"] = CALENDAR_ALIGNMENT_POLICY_VERSION
    market_cap_currency_policy_version: Literal["explicit-market-cap-currency-v1"] = MARKET_CAP_CURRENCY_POLICY_VERSION
    accounting_period_adapter_version: Literal["accounting-period-semantics-v1"] = ACCOUNTING_PERIOD_ADAPTER_VERSION
    value_temporal_selection_policy_version: Literal["value-fy-flow-and-period-end-instant-v1"] = VALUE_TEMPORAL_SELECTION_POLICY_VERSION
    unit_ontology_version: Literal["unit-ontology-v1"] = UNIT_ONTOLOGY_VERSION
    fx_translation_policy: Literal["FISCAL_PERIOD_END"] = "FISCAL_PERIOD_END"
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    market_data_contract_version: Literal["market-data-governance-v1"]
    market_data_canonical_id: str
    market_data_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_data_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_contract_version: Literal["fx-governance-v1"]
    fx_canonical_id: str
    fx_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    fx_staleness_policy_version: str
    fx_conversions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accounting_contract_version: Literal["accounting-pit-governance-v1"]
    accounting_canonical_id: str
    accounting_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    accounting_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_fundamentals: tuple[str, ...]
    cross_layer_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    health: Literal["PASS"] = "PASS"
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    live_execution_enabled: Literal[False] = False
    scores_calculated: Literal[False] = False
    ranking_calculated: Literal[False] = False
    portfolio_constructed: Literal[False] = False
    backtesting_performed: Literal[False] = False
    signals_generated: Literal[False] = False
    execution_enabled: Literal[False] = False

    @field_validator("as_of", "universe_as_of")
    @classmethod
    def aware_timestamp(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cross-layer timestamps must be timezone-aware")
        return value

    @property
    def fingerprint(self) -> str:
        return self.cross_layer_fingerprint


@dataclass(frozen=True)
class CrossLayerGovernanceResult:
    market_data: MarketDataDataset
    fx_data: FXDataset
    accounting_data: AccountingDataset
    universe_membership: pd.DataFrame
    market_snapshot: pd.DataFrame
    accounting_snapshot: pd.DataFrame
    fx_conversions: pd.DataFrame
    manifest: CrossLayerManifest


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def eligible_symbols_hash(symbols: set[str] | tuple[str, ...]) -> str:
    normalized = sorted({str(item).strip().upper() for item in symbols})
    if not normalized or any(not item for item in normalized):
        raise CrossLayerGovernanceError("eligible universe must contain symbols")
    return _hash({"version": ENTITY_POLICY_VERSION, "symbols": normalized})


def _frame_hash(frame: pd.DataFrame, keys: list[str]) -> str:
    data = frame.reindex(sorted(frame.columns), axis=1).copy()
    for column in data:
        data[column] = data[column].map(lambda value: "" if pd.isna(value) else str(value))
    return hashlib.sha256(data.sort_values(keys, kind="stable").to_csv(index=False, lineterminator="\n").encode()).hexdigest()


def _verify_inputs(market: MarketDataDataset, fx: FXDataset, accounting: AccountingDataset) -> None:
    try:
        MarketDataDataset(market.frame, market.metadata)
        FXDataset(fx.frame, fx.metadata)
        AccountingDataset(accounting.frame, accounting.metadata)
    except (MarketDataGovernanceError, FXGovernanceError, AccountingGovernanceError) as error:
        raise CrossLayerGovernanceError(f"post-governance mutation detected: {error}") from error


def _universe(directory: Path, cutoff: datetime.datetime) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        verified = verify_universe_snapshot(directory)
    except DatasetVersionError as error:
        raise CrossLayerGovernanceError(str(error)) from error
    membership = pd.read_csv(verified.membership_path)
    universe_as_of = pd.Timestamp(verified.metadata.get("as_of"))
    if universe_as_of.tzinfo is None or universe_as_of.utcoffset() is None:
        raise CrossLayerGovernanceError("universe as_of must be timezone-aware")
    universe_as_of = universe_as_of.tz_convert("UTC")
    if universe_as_of.to_pydatetime() != cutoff:
        raise CrossLayerGovernanceError("universe as_of does not match cross-layer as_of")
    source = pd.to_datetime(membership["source_timestamp"], utc=True, errors="raise")
    available = pd.to_datetime(membership["available_at"], utc=True, errors="raise")
    if (source > available).any() or (available > pd.Timestamp(cutoff)).any():
        raise CrossLayerGovernanceError("universe chronology violates source_timestamp <= available_at <= as_of")
    symbols = tuple(sorted(membership.loc[membership["eligibility_status"] == "ELIGIBLE", "symbol"].astype(str).str.strip().str.upper().unique()))
    if not symbols:
        raise CrossLayerGovernanceError("governed universe has no eligible symbols")
    snapshot_id = f"universe-{universe_as_of.date().isoformat()}"
    snapshot_hash = _hash({"id": snapshot_id, "membership": verified.membership_sha256, "validation": verified.validation_sha256, "ruleset": verified.metadata["ruleset"]})
    return membership, {"id": snapshot_id, "hash": snapshot_hash, "membership": verified.membership_sha256, "validation": verified.validation_sha256, "ruleset": verified.metadata["ruleset"]["version"], "as_of": universe_as_of.to_pydatetime(), "symbols": symbols, "symbols_hash": eligible_symbols_hash(symbols)}


def integrate_governed_inputs(*, universe_snapshot_dir: Path, market_data: MarketDataDataset,
    fx: FXDataset, accounting: AccountingDataset, as_of: datetime.datetime, base_currency: str,
    required_fundamentals: set[str] | None = None, reference_symbols: set[str] | None = None,
) -> CrossLayerGovernanceResult:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise CrossLayerGovernanceError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(datetime.UTC)
    base = normalize_unit(base_currency)
    if unit_kind(base) != "MONETARY":
        raise CrossLayerGovernanceError("base_currency must be monetary")
    _verify_inputs(market_data, fx, accounting)
    membership, universe = _universe(universe_snapshot_dir, cutoff)
    for metadata in (market_data.metadata, fx.metadata, accounting.metadata):
        if metadata.available_at.astimezone(datetime.UTC) > cutoff:
            raise CrossLayerGovernanceError("PIT violation: dataset availability exceeds as_of")
    allowed_market = set(universe["symbols"]) | {str(x).strip().upper() for x in reference_symbols or set()}
    market = market_data.frame.loc[pd.to_datetime(market_data.frame["available_at"], utc=True) <= cutoff].copy()
    if set(market["symbol"].astype(str).str.upper()) != allowed_market:
        raise CrossLayerGovernanceError("market symbols do not match eligible universe and explicit references")
    market["currency"] = market["currency"].map(normalize_unit)
    if any(unit_kind(unit) != "MONETARY" for unit in market["currency"]):
        raise CrossLayerGovernanceError("market currency must be monetary")
    required = tuple(sorted(required_fundamentals or set()))
    required_pairs = {(symbol, metric) for symbol in universe["symbols"] for metric in required}
    try:
        facts = accounting.snapshot(cutoff=cutoff, required=required_pairs).copy()
    except AccountingGovernanceError as error:
        raise CrossLayerGovernanceError(str(error)) from error
    if set(facts["entity"].astype(str).str.upper()) != set(universe["symbols"]):
        raise CrossLayerGovernanceError("accounting entities do not exactly match eligible universe")
    facts["original_value"] = pd.to_numeric(facts["value"], errors="raise")
    facts["original_unit"] = facts["unit"].map(normalize_unit)
    required_period_columns = {"fiscal_period_start", "period_type"}
    if not required_period_columns <= set(facts.columns):
        raise CrossLayerGovernanceError(
            "accounting snapshot lacks explicit fiscal_period_start/period_type"
        )
    rows: list[dict[str, Any]] = []
    for index, row in facts.iterrows():
        unit = row["original_unit"]
        if unit_kind(unit) == "MONETARY":
            market_at = pd.Timestamp(row["period_end"], tz="UTC").replace(hour=23, minute=59, second=59).to_pydatetime()
            try:
                converted = fx.convert(float(row["original_value"]), source_currency=unit, target_currency=base, market_at=market_at, cutoff=cutoff)
            except FXGovernanceError as error:
                raise CrossLayerGovernanceError(f"FX translation failed for {row['entity']}/{row['metric']}: {error}") from error
            facts.at[index, "value"], facts.at[index, "unit"] = converted.converted_amount, base
            conversion = converted.__dict__
        else:
            conversion = {"amount": float(row["original_value"]), "source_currency": None, "target_currency": None, "converted_amount": float(row["original_value"]), "rate": None, "conversion_method": "not_applicable", "rate_market_timestamp": None, "rate_available_at": None, "fx_canonical_id": None, "fx_checksum": None, "fx_source": None, "fx_dataset_version": None}
        rows.append({"entity": row["entity"], "metric": row["metric"], "period_end": row["period_end"], **conversion})
    membership = membership.copy(deep=True)
    membership["original_market_cap"] = membership["market_cap"]
    membership["base_currency"] = base
    for symbol in universe["symbols"]:
        member_index = membership.index[membership["symbol"] == symbol]
        if len(member_index) != 1:
            raise CrossLayerGovernanceError(f"ambiguous universe membership for {symbol}")
        member = membership.loc[member_index[0]]
        try:
            source_currency = normalize_unit(member["market_cap_currency"])
        except (TypeError, ValueError) as error:
            raise CrossLayerGovernanceError(
                f"invalid or missing market_cap_currency for {symbol}: {error}"
            ) from error
        if unit_kind(source_currency) != "MONETARY":
            raise CrossLayerGovernanceError(
                f"market_cap_currency must be monetary for {symbol}"
            )
        market_at = pd.Timestamp(member["source_timestamp"]).to_pydatetime()
        source_amount = float(
            member["market_cap"]
        )
        try:
            converted = fx.convert(source_amount, source_currency=source_currency,
                target_currency=base, market_at=market_at, cutoff=cutoff)
        except FXGovernanceError as error:
            raise CrossLayerGovernanceError(f"market_cap FX translation failed for {symbol}: {error}") from error
        membership.loc[member_index, "market_cap"] = converted.converted_amount
        membership.loc[member_index, "market_cap_currency"] = source_currency
        rows.append({"entity": symbol, "metric": "market_cap",
            "period_end": pd.Timestamp(member["source_timestamp"]).date(),
            "conversion_policy_version": MARKET_CAP_CURRENCY_POLICY_VERSION,
            **converted.__dict__})
    conversions = pd.DataFrame(rows)
    hashes = {"market": _frame_hash(market, ["symbol", "date"]), "accounting": _frame_hash(facts, ["entity", "metric", "period_end", "revision"]), "fx": _frame_hash(conversions, ["entity", "metric", "period_end"])}
    identity = {"contract": CROSS_LAYER_CONTRACT_VERSION, "as_of": cutoff.isoformat(), "universe": universe, "policies": [AVAILABILITY_POLICY_VERSION, ENTITY_POLICY_VERSION, CALENDAR_ALIGNMENT_POLICY_VERSION, UNIT_ONTOLOGY_VERSION, "FISCAL_PERIOD_END", MARKET_CAP_CURRENCY_POLICY_VERSION, ACCOUNTING_PERIOD_ADAPTER_VERSION, VALUE_TEMPORAL_SELECTION_POLICY_VERSION], "base": base, "market": market_data.metadata.model_dump(mode="json"), "fx": fx.metadata.model_dump(mode="json"), "accounting": accounting.metadata.model_dump(mode="json"), "hashes": hashes, "required": required}
    manifest = CrossLayerManifest(as_of=cutoff, universe_snapshot_id=universe["id"], universe_snapshot_hash=universe["hash"], membership_hash=universe["membership"], validation_hash=universe["validation"], eligible_symbols_hash=universe["symbols_hash"], eligible_symbols_count=len(universe["symbols"]), universe_ruleset_version=universe["ruleset"], universe_as_of=universe["as_of"], base_currency=base, market_data_contract_version=market_data.metadata.contract_version, market_data_canonical_id=market_data.metadata.canonical_id, market_data_checksum=market_data.metadata.checksum, market_data_snapshot_sha256=hashes["market"], fx_contract_version=fx.metadata.contract_version, fx_canonical_id=fx.metadata.canonical_id, fx_checksum=fx.metadata.checksum, fx_staleness_policy_version=fx.metadata.staleness_policy.version, fx_conversions_sha256=hashes["fx"], accounting_contract_version=accounting.metadata.contract_version, accounting_canonical_id=accounting.metadata.canonical_id, accounting_checksum=accounting.metadata.checksum, accounting_snapshot_sha256=hashes["accounting"], required_fundamentals=required, cross_layer_fingerprint=_hash(identity))
    return CrossLayerGovernanceResult(market_data, fx, accounting, membership, market, facts,
        conversions, manifest)


def write_governed_inputs(result: CrossLayerGovernanceResult, *, output_root: Path) -> Path:
    output = output_root / f"cross_layer_{result.manifest.cross_layer_fingerprint}"
    payloads = {"universe_membership.csv": result.universe_membership.to_csv(index=False, lineterminator="\n"), "market_snapshot.csv": result.market_snapshot.to_csv(index=False, lineterminator="\n"), "accounting_snapshot.csv": result.accounting_snapshot.to_csv(index=False, lineterminator="\n"), "fx_conversions.csv": result.fx_conversions.to_csv(index=False, lineterminator="\n"), "cross_layer_manifest.json": json.dumps(result.manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"}
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        path = output / name
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise CrossLayerGovernanceError(f"immutable cross-layer output conflict: {path}")
        path.write_text(payload, encoding="utf-8")
    return output
