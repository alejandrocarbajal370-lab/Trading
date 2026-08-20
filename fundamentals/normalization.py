from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


class NormalizationError(ValueError):
    """Raised when a raw concept cannot be mapped without guessing."""


@dataclass(frozen=True)
class ConceptMapping:
    source: str
    raw_concept: str
    canonical_metric: str
    expected_period_type: str
    expected_unit_kind: str


DEFAULT_MAPPINGS = (
    ConceptMapping("sec", "us-gaap:Revenues", "revenue", "duration", "monetary"),
    ConceptMapping(
        "sec",
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "cash_from_operations",
        "duration",
        "monetary",
    ),
    ConceptMapping(
        "sec",
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "capital_expenditures",
        "duration",
        "monetary",
    ),
    ConceptMapping("sec", "us-gaap:NetIncomeLoss", "net_income", "duration", "monetary"),
    ConceptMapping(
        "sec", "us-gaap:OperatingIncomeLoss", "operating_income", "duration", "monetary"
    ),
    ConceptMapping(
        "sec", "us-gaap:CashAndCashEquivalentsAtCarryingValue", "cash", "instant", "monetary"
    ),
    ConceptMapping("sec", "us-gaap:StockholdersEquity", "total_equity", "instant", "monetary"),
    ConceptMapping("sec", "us-gaap:Assets", "total_assets", "instant", "monetary"),
)


class FinancialNormalizer:
    def __init__(self, mappings: tuple[ConceptMapping, ...] = DEFAULT_MAPPINGS) -> None:
        self._mappings = {(item.source, item.raw_concept): item for item in mappings}

    def normalize(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map raw concepts explicitly. Unknown concepts are rejected, never proxied."""
        required = {"source", "raw_concept", "period_type", "unit", "value"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise NormalizationError(f"raw fundamentals missing fields: {', '.join(missing)}")
        output = raw.copy()
        mapped: list[str] = []
        for row in output.itertuples(index=False):
            mapping = self._mappings.get((str(row.source), str(row.raw_concept)))
            if mapping is None:
                raise NormalizationError(
                    f"unmapped raw concept: source={row.source}, concept={row.raw_concept}"
                )
            if row.period_type != mapping.expected_period_type:
                raise NormalizationError(f"period type mismatch for {row.raw_concept}")
            unit_is_currency = len(str(row.unit)) == 3 and str(row.unit).isalpha()
            if mapping.expected_unit_kind == "monetary" and not unit_is_currency:
                raise NormalizationError(f"unit kind mismatch for {row.raw_concept}")
            mapped.append(mapping.canonical_metric)
        output["metric"] = mapped
        output["normalization_method"] = "explicit_mapping"
        output["proxy_used"] = False
        return output
