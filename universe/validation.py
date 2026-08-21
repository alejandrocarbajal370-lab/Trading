from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = (
    "symbol",
    "exchange",
    "asset_type",
    "country",
    "region",
    "sector",
    "industry",
    "market_cap",
    "average_volume",
    "average_dollar_volume",
    "listing_date",
    "source",
    "source_timestamp",
    "available_at",
)
OUTPUT_COLUMNS = (
    *REQUIRED_COLUMNS,
    "eligibility_status",
    "exclusion_reason",
    "universe_confidence",
    "lineage",
)
VALID_ASSET_TYPES = frozenset({"COMMON_STOCK", "PREFERRED_STOCK", "ADR", "ETF", "REIT"})


class UniverseValidationError(ValueError):
    """The universe source violates its contract."""


@dataclass(frozen=True)
class UniverseRules:
    ruleset_version: str = "universe-v1"
    minimum_market_cap: float | None = None
    minimum_average_volume: float | None = None
    minimum_average_dollar_volume: float | None = None
    allowed_asset_types: tuple[str, ...] = ("COMMON_STOCK",)
    minimum_listing_age_days: int | None = None
    allowed_exchanges: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.ruleset_version.strip():
            raise UniverseValidationError("ruleset_version must be present")
        numeric = {
            "minimum_market_cap": self.minimum_market_cap,
            "minimum_average_volume": self.minimum_average_volume,
            "minimum_average_dollar_volume": self.minimum_average_dollar_volume,
            "minimum_listing_age_days": self.minimum_listing_age_days,
        }
        if any(value is not None and value < 0 for value in numeric.values()):
            raise UniverseValidationError("universe thresholds must be non-negative")
        unknown = set(self.allowed_asset_types) - VALID_ASSET_TYPES
        if unknown:
            raise UniverseValidationError(f"invalid configured asset types: {', '.join(sorted(unknown))}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(records: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(REQUIRED_COLUMNS) - set(records.columns))
    if missing:
        raise UniverseValidationError(f"missing required fields: {', '.join(missing)}")
    frame = records.loc[:, REQUIRED_COLUMNS].copy()
    frame["symbol"] = frame["symbol"].astype("string").str.strip().str.upper()
    frame["exchange"] = frame["exchange"].astype("string").str.strip().str.upper()
    frame["asset_type"] = frame["asset_type"].astype("string").str.strip().str.upper()
    if frame["symbol"].isna().any() or (frame["symbol"] == "").any():
        raise UniverseValidationError("symbol must be present")
    duplicates = sorted(frame.loc[frame["symbol"].duplicated(keep=False), "symbol"].unique())
    if duplicates:
        raise UniverseValidationError(f"duplicate symbols: {', '.join(duplicates)}")
    invalid = sorted(set(frame["asset_type"].dropna()) - VALID_ASSET_TYPES)
    if invalid:
        raise UniverseValidationError(f"invalid asset types: {', '.join(invalid)}")
    for column in ("market_cap", "average_volume", "average_dollar_volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if (frame[column].dropna() < 0).any():
            raise UniverseValidationError(f"{column} must be non-negative")
    for column in ("listing_date", "source_timestamp", "available_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    if frame[["source_timestamp", "available_at"]].isna().any().any():
        raise UniverseValidationError("source_timestamp and available_at must be valid timestamps")
    return frame


def validate_universe(
    records: pd.DataFrame, *, rules: UniverseRules, as_of: pd.Timestamp
) -> pd.DataFrame:
    """Return every source asset with an explicit inclusion or exclusion decision."""
    frame = _normalize(records)
    cutoff = pd.Timestamp(as_of)
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    allowed_assets = set(rules.allowed_asset_types)
    allowed_exchanges = {exchange.upper() for exchange in rules.allowed_exchanges}
    rows: list[dict[str, Any]] = []
    for _, source_row in frame.iterrows():
        reasons: list[str] = []
        if source_row["available_at"] > cutoff:
            reasons.append("not_available_at_cutoff")
        if source_row["asset_type"] not in allowed_assets:
            reasons.append("asset_type_not_allowed")
        if allowed_exchanges and source_row["exchange"] not in allowed_exchanges:
            reasons.append("exchange_not_allowed")
        checks = (
            ("market_cap", rules.minimum_market_cap, "market_cap_below_minimum"),
            ("average_volume", rules.minimum_average_volume, "average_volume_below_minimum"),
            (
                "average_dollar_volume",
                rules.minimum_average_dollar_volume,
                "average_dollar_volume_below_minimum",
            ),
        )
        for field, threshold, reason in checks:
            value = source_row[field]
            if threshold is not None and pd.isna(value):
                reasons.append(f"missing_{field}")
            elif threshold is not None and value < threshold:
                reasons.append(reason)
        listing_date = source_row["listing_date"]
        if rules.minimum_listing_age_days is not None:
            if pd.isna(listing_date):
                reasons.append("missing_listing_date")
            elif (cutoff.normalize() - listing_date.normalize()).days < rules.minimum_listing_age_days:
                reasons.append("listing_age_below_minimum")
        completeness_fields = [
            "exchange",
            "asset_type",
            "country",
            "region",
            "market_cap",
            "average_volume",
            "average_dollar_volume",
            "listing_date",
            "source",
        ]
        completeness = sum(not pd.isna(source_row[field]) for field in completeness_fields) / len(
            completeness_fields
        )
        row = source_row.to_dict()
        row.update(
            eligibility_status="EXCLUDED" if reasons else "ELIGIBLE",
            exclusion_reason=";".join(reasons),
            universe_confidence=round(completeness, 4),
            lineage=json.dumps(
                {
                    "source": source_row["source"],
                    "source_timestamp": source_row["source_timestamp"].isoformat(),
                    "available_at": source_row["available_at"].isoformat(),
                    "as_of": cutoff.isoformat(),
                },
                sort_keys=True,
            ),
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def universe_health(membership: pd.DataFrame, *, rules: UniverseRules) -> dict[str, Any]:
    eligible = int((membership["eligibility_status"] == "ELIGIBLE").sum())
    excluded = int((membership["eligibility_status"] == "EXCLUDED").sum())
    reasons = (
        membership.loc[membership["exclusion_reason"] != "", "exclusion_reason"]
        .str.split(";")
        .explode()
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return {
        "status": "PASS" if eligible else "WARNING",
        "records": len(membership),
        "eligible": eligible,
        "excluded": excluded,
        "exclusion_reasons": reasons,
        "rules": rules.to_dict(),
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
