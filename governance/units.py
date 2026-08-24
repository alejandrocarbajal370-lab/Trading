from __future__ import annotations

from typing import Literal

UNIT_ONTOLOGY_VERSION = "unit-ontology-v1"
MONETARY_UNITS = frozenset({"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "MXN", "BRL", "CNY", "HKD"})
NON_MONETARY_UNITS = frozenset({"RATIO", "PERCENTAGE", "RETURN", "SHARES", "DAYS", "MULTIPLE", "COUNT", "BPS"})


class UnitOntologyError(ValueError):
    """Raised when an upstream unit has no explicit governed meaning."""


def normalize_unit(value: object) -> str:
    unit = str(value).strip().upper()
    if unit not in MONETARY_UNITS | NON_MONETARY_UNITS:
        raise UnitOntologyError(f"unknown unit under {UNIT_ONTOLOGY_VERSION}: {value!r}")
    return unit


def unit_kind(value: object) -> Literal["MONETARY", "NON_MONETARY"]:
    unit = normalize_unit(value)
    return "MONETARY" if unit in MONETARY_UNITS else "NON_MONETARY"
